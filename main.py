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

# 修复 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from database import init_db, add_url, delete_url, list_urls, get_active_urls, save_snapshot, get_latest_morning_snapshot
from scraper import fetch_url
from analyzer import analyze_morning, analyze_evening
from mailer import send_email


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
    if ok:
        print(f"[OK] 已删除: {identifier}")
    else:
        print(f"[ERROR] 未找到: {identifier}")


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


def cmd_run(args):
    """执行一次完整的抓取->分析->发送流程"""
    hour = datetime.now().hour
    is_morning = args.morning or (not args.evening and hour < 15)

    tag = "[上午]" if is_morning else "[晚间]"
    print(f"\n{tag} 监控任务开始...")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    urls = get_active_urls()
    if not urls:
        print("暂无监控网址")
        return

    results = []

    for i, u in enumerate(urls):
        name = u["name"] or u["url"]
        print(f"[{i+1}/{len(urls)}] 抓取: {name} ...")

        # 1. 抓取网页
        try:
            content = fetch_url(u["url"], use_dynamic=bool(u["use_dynamic"]))
            content_preview = content[:80].replace("\n", " ")
            print(f"    抓取成功 ({len(content)} 字符): {content_preview}...")
        except Exception as e:
            print(f"    [ERROR] 抓取失败: {e}")
            results.append({
                "url_name": name, "url": u["url"],
                "category": "抓取失败", "summary": str(e),
                "keywords": [], "changes": [],
            })
            continue

        # 2. LLM 分析
        if is_morning:
            print(f"    分析中...")
            analysis = analyze_morning(content, url_name=name)
            keywords = analysis.get("keywords", [])
            print(f"    分类: {analysis.get('category')}, 关键词: {keywords}")

            save_snapshot(u["id"], content, analysis.get("summary", ""), keywords, is_morning=True)

            results.append({
                "url_name": name, "url": u["url"],
                "category": analysis.get("category", ""),
                "summary": analysis.get("summary", ""),
                "keywords": keywords,
                "changes": [],
            })
        else:
            morning_snap = get_latest_morning_snapshot(u["id"])
            morning_content = morning_snap["content"] if morning_snap else ""
            print(f"    分析+对比上午快照...")
            analysis = analyze_evening(morning_content, content, url_name=name)
            keywords = analysis.get("keywords", [])
            changes = analysis.get("changes", [])
            print(f"    分类: {analysis.get('category')}, 变化: {len(changes)} 项")

            save_snapshot(u["id"], content, analysis.get("summary", ""), keywords, is_morning=False)

            results.append({
                "url_name": name, "url": u["url"],
                "category": analysis.get("category", ""),
                "summary": analysis.get("summary", ""),
                "keywords": keywords,
                "changes": changes,
            })

    # 3. 发送邮件
    print(f"\n发送邮件...")
    if results:
        send_email(results, is_morning=is_morning)
    else:
        print("   无结果，跳过邮件")

    print(f"\n[OK] {tag} 监控任务完成")


def cmd_test(args):
    """测试抓取单个网址（不保存，不发邮件）"""
    print(f"\n测试抓取: {args.url}")
    print(f"   类型: {'动态(Playwright)' if args.dynamic else '静态(requests)'}\n")

    try:
        content = fetch_url(args.url, use_dynamic=args.dynamic)
        print(f"抓取成功，共 {len(content)} 字符\n")
        print("=" * 60)
        print(content[:2000])
        if len(content) > 2000:
            print(f"\n... [剩余 {len(content) - 2000} 字符未显示]")
        print("=" * 60)

        print("\n测试 LLM 分析...")
        analysis = analyze_morning(content, url_name=args.url)
        print(f"   分类: {analysis.get('category')}")
        print(f"   摘要: {analysis.get('summary')}")
        print(f"   关键词: {analysis.get('keywords')}")

    except Exception as e:
        print(f"[ERROR] 失败: {e}")


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
