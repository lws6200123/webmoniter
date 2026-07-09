"""
Web Monitor — 网页信息监控工具 CLI
用法:
  python main.py add <url> [--name <名称>] [--category <分类>] [--dynamic]
  python main.py delete <id|url>
  python main.py list
  python main.py run [--morning|--evening]
  python main.py test <url> [--dynamic]
"""
import sys
import io
import argparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from database import init_db, add_url, delete_url, list_urls, get_active_urls, save_snapshot, get_latest_morning_snapshot
from scraper import fetch_url, fetch_dynamic
from analyzer import analyze_morning, analyze_evening, analyze_summary, analyze_structured
from mailer import notify


def cmd_add(args):
    """添加网址"""
    try:
        url_id = add_url(
            url=args.url,
            name=args.name or "",
            category=args.category or "",
            use_dynamic=args.dynamic,
        )
        print(f"[OK] 已添加 [{url_id}] {args.name or args.url}")
    except ValueError as e:
        print(f"[ERROR] {e}")


def cmd_delete(args):
    """删除网址"""
    identifier = args.identifier
    try:
        identifier = int(identifier)
    except ValueError:
        pass
    ok = delete_url(identifier)
    print(f"[OK] 已删除: {identifier}" if ok else f"[ERROR] 未找到: {identifier}")


def cmd_list(args):
    """列出所有网址"""
    urls = list_urls(active_only=not args.all)
    if not urls:
        print("暂无监控网址，使用 'add' 命令添加")
        return
    print(f"\n监控网址列表 (共 {len(urls)} 个):\n")
    print(f"{'ID':<4} {'名称':<16} {'分类':<10} {'类型':<8} {'URL'}")
    print("-" * 80)
    for u in urls:
        d_type = "[动态]" if u["use_dynamic"] else "[静态]"
        name = u["name"] or "-"
        cat = u["category"] or "-"
        print(f"{u['id']:<4} {name:<16} {cat:<10} {d_type:<8} {u['url']}")


def _process_url(url_record: dict, is_morning: bool) -> dict:
    """
    处理单个网址：抓取 → 分析 → 返回结构化报告
    """
    name = url_record["name"] or url_record["url"]
    url = url_record["url"]
    use_dynamic = bool(url_record["use_dynamic"])

    report = {
        "url_name": name,
        "url": url,
        "summary": {},
        "structured": [],
        "details": [],      # 原始抓取详情（供邮件展示原文）
        "changes": [],
    }

    # === 1. 抓取 ===
    print(f"    抓取网页...")
    try:
        if use_dynamic:
            data = fetch_dynamic(url, follow_links=True)
            list_overview = data["list_overview"]
            details = data["details"]
            # 从抓到数据中构建快照文本（不再重复调用 fetch_dynamic）
            parts = [f"=== 列表页 ===\n{list_overview}"]
            for d in details:
                parts.append(f"\n=== {d['title']} ({d.get('date', '?')}) ===\n{d['content']}")
            full_content = "\n\n".join(parts)
        else:
            full_content = fetch_url(url, use_dynamic=False)
            list_overview = full_content
            details = []
    except Exception as e:
        print(f"    [ERROR] 抓取失败: {e}")
        report["summary"] = {"category": "抓取失败", "summary": str(e), "keywords": []}
        return report

    # === 2. 分析 ===
    if is_morning:
        print(f"    分析列表概览...")
        report["summary"] = analyze_summary(list_overview, url_name=name)

        if details and use_dynamic:
            print(f"    结构化提取 {len(details)} 条详情...")
            report["structured"] = analyze_structured(details, url_name=name)
            report["details"] = details  # 保留原始详情供邮件展示

        # 保存快照
        save_snapshot(url_record["id"], full_content,
                      report["summary"].get("summary", ""),
                      report["summary"].get("keywords", []),
                      is_morning=True)
    else:
        # 晚上：对比上午快照
        morning_snap = get_latest_morning_snapshot(url_record["id"])
        morning_content = morning_snap["content"] if morning_snap else ""

        print(f"    分析+对比上午快照...")
        evening_analysis = analyze_evening(morning_content, full_content, url_name=name)
        report["summary"] = evening_analysis
        report["changes"] = evening_analysis.get("changes", [])

        if details and use_dynamic:
            print(f"    结构化提取 {len(details)} 条详情...")
            report["structured"] = analyze_structured(details, url_name=name)
            report["details"] = details

        save_snapshot(url_record["id"], full_content,
                      evening_analysis.get("summary", ""),
                      evening_analysis.get("keywords", []),
                      is_morning=False)

    return report


def cmd_run(args):
    """执行一次完整的抓取→分析→发送流程"""
    hour = datetime.now().hour
    is_morning = args.morning or (not args.evening and hour < 15)

    tag = "[上午]" if is_morning else "[晚间]"
    print(f"\n{tag} 监控任务开始...")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    urls = get_active_urls()
    if not urls:
        print("暂无监控网址")
        return

    reports = []
    for i, u in enumerate(urls):
        name = u["name"] or u["url"]
        print(f"[{i+1}/{len(urls)}] {name}")
        report = _process_url(u, is_morning)
        reports.append(report)
        print()

    # 发送通知
    print("发送通知...")
    if reports:
        notify(reports, is_morning=is_morning)
    else:
        print("   无结果，跳过邮件")

    print(f"\n[OK] {tag} 监控任务完成")


def cmd_test(args):
    """测试抓取单个网址"""
    print(f"\n测试抓取: {args.url}")
    d_type = "动态(Playwright)" if args.dynamic else "静态(requests)"
    print(f"   类型: {d_type}\n")

    if args.dynamic:
        data = fetch_dynamic(args.url, follow_links=True)
        print(f"列表页长度: {len(data['list_overview'])} 字符")
        print(f"详情条目数: {len(data['details'])}")

        print(f"\n{'='*60}")
        print(data['list_overview'][:500])
        print(f"{'='*60}")

        if data["details"]:
            print(f"\n--- 第1条详情预览 (共{len(data['details'])}条) ---")
            first = data["details"][0]
            print(f"标题: {first['title']}")
            print(f"日期: {first['date']}")
            print(f"内容 ({len(first['content'])} 字符):")
            print(first['content'][:800])
            if len(first['content']) > 800:
                print(f"... [剩余 {len(first['content'])-800} 字符]")

            print(f"\n测试 LLM 结构化提取...")
            structured = analyze_structured(data["details"][:3], url_name=args.url)
            for s in structured:
                print(f"  - {s.get('title','?')[:40]} | {s.get('company','?')} | {s.get('salary','?')} | {s.get('location','?')}")
    else:
        content = fetch_url(args.url, use_dynamic=False)
        print(f"抓取成功，共 {len(content)} 字符\n")
        print("=" * 60)
        print(content[:2000])
        print("=" * 60)

        print("\n测试 LLM 分析...")
        analysis = analyze_morning(content, url_name=args.url)
        print(f"   分类: {analysis.get('category')}")
        print(f"   摘要: {analysis.get('summary')}")
        print(f"   关键词: {analysis.get('keywords')}")


def main():
    init_db()

    parser = argparse.ArgumentParser(description="Web Monitor — 网页信息监控工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    p_add = subparsers.add_parser("add", help="添加监控网址")
    p_add.add_argument("url", help="要监控的网址")
    p_add.add_argument("--name", default="", help="自定义名称")
    p_add.add_argument("--category", default="", help="分类标签")
    p_add.add_argument("--dynamic", action="store_true", help="使用 Playwright 动态抓取")

    p_del = subparsers.add_parser("delete", help="删除监控网址")
    p_del.add_argument("identifier", help="网址 ID 或完整 URL")

    p_list = subparsers.add_parser("list", help="列出所有监控网址")
    p_list.add_argument("--all", action="store_true", help="包含已停用的网址")

    p_run = subparsers.add_parser("run", help="执行一次监控任务")
    p_run.add_argument("--morning", action="store_true", help="强制使用上午模式")
    p_run.add_argument("--evening", action="store_true", help="强制使用晚间模式（含变化对比）")

    p_test = subparsers.add_parser("test", help="测试抓取单个网址")
    p_test.add_argument("url", help="要测试的网址")
    p_test.add_argument("--dynamic", action="store_true", help="使用 Playwright 动态抓取")

    args = parser.parse_args()

    if args.command == "add":
        cmd_add(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "test":
        cmd_test(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
