"""
网页抓取模块：静态页面 (requests+BS4) + 动态页面 (Playwright)
支持列表->详情弹窗跟踪、日期过滤、结构化信息提取
"""
import re
import time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from readability import Document
from config import REQUEST_TIMEOUT, MAX_CONTENT_LENGTH, PLAYWRIGHT_TIMEOUT

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

CONTENT_SELECTORS = [
    'article', 'main', '[role="main"]',
    '.post-content', '.article-content', '.entry-content',
    '.detail-content', '.news-content', '.info-content',
    '#content', '.content', '.main-content', '.detail',
]


def fetch_static(url: str) -> str:
    """静态页面抓取：requests + BeautifulSoup"""
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    doc = Document(resp.text)
    soup = BeautifulSoup(doc.summary(), "lxml")
    text = soup.get_text(separator="\n", strip=True)
    if len(text) > MAX_CONTENT_LENGTH:
        text = text[:MAX_CONTENT_LENGTH] + "\n\n... [内容过长，已截断]"
    return text


def _extract_page_text(page) -> str:
    """从 Playwright page 提取正文文本"""
    article_html = page.evaluate(f"""() => {{
        const selectors = {CONTENT_SELECTORS};
        for (const sel of selectors) {{
            try {{
                const el = document.querySelector(sel);
                if (el && el.innerText && el.innerText.length > 100) return el.outerHTML;
            }} catch(e) {{}}
        }}
        return document.body ? document.body.outerHTML : '';
    }}""")
    if not article_html:
        return ""
    soup = BeautifulSoup(article_html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _extract_list_items_with_dates(page) -> list[dict]:
    """
    从列表页提取条目标题+日期
    返回 [{"text": "标题", "date": "2026-07-08", "href": "...", "row_html": "..."}, ...]
    """
    items = page.evaluate("""() => {
        const results = [];
        const seenTexts = new Set();

        // 找所有可能是列表项的容器
        const rows = document.querySelectorAll(
            'table tr, .list-item, [class*="item"], .news-item, ' +
            '[class*="row"], .entry, li, .post'
        );

        for (const row of rows) {
            const anchors = row.querySelectorAll('a');
            for (const a of anchors) {
                const text = (a.innerText || a.textContent || '').trim();
                if (!text || text.length < 8) continue;
                if (text === '下一页' || text === '上一页' || text === '首页' || text === '尾页') continue;
                if (text === '查看详情' || text === '详情') continue;
                if (/^[0-9]+$/.test(text)) continue;
                if (text.length > 120) continue;

                const rect = a.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;

                const key = text.substring(0, 40);
                if (seenTexts.has(key)) continue;
                seenTexts.add(key);

                // 取整个行的文本（含日期）
                const rowText = (row.innerText || row.textContent || '').trim();

                results.push({
                    text: text.substring(0, 100),
                    rowText: rowText.substring(0, 300),
                    href: a.href || a.getAttribute('onclick') || ''
                });
                break; // 每行只取第一个有效链接
            }
        }
        return results;
    }""")

    # 从 rowText 中解析日期
    today = datetime.now().date()
    cutoff = today - timedelta(days=3)

    parsed_items = []
    for item in items:
        # 尝试提取日期
        date_str = None
        date_patterns = [
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
            r'更新时间[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
            r'发布日期[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
            r'日期[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, item["rowText"])
            if match:
                date_str = match.group(1)
                break

        # 解析日期
        item_date = None
        if date_str:
            for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
                try:
                    item_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue

        parsed_items.append({
            "text": item["text"],
            "href": item["href"],
            "date": date_str,
            "date_obj": item_date,
            "in_range": item_date is not None and item_date >= cutoff,
        })

    return parsed_items


def fetch_dynamic(url: str, follow_links: bool = True, max_detail_pages: int = 15) -> dict:
    """
    动态页面抓取
    返回 {
        "list_overview": "列表页概览",
        "details": [{"title": "标题", "date": "日期", "content": "详情文字"}, ...]
    }
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="zh-CN",
        )
        page = context.new_page()
        page.set_default_timeout(PLAYWRIGHT_TIMEOUT)

        result = {"list_overview": "", "details": []}

        try:
            # 1. 加载列表页
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)

            # 2. 提取列表概览
            list_text = _extract_page_text(page)
            result["list_overview"] = list_text[:800]

            if not follow_links:
                return result

            # 3. 提取条目并过滤日期
            all_items = _extract_list_items_with_dates(page)
            list_url = page.url

            # 打印所有条目及其日期状态
            in_range_items = [it for it in all_items if it["in_range"]]
            out_range_items = [it for it in all_items if not it["in_range"]]

            print(f"    [scraper] 共发现 {len(all_items)} 个条目")
            if out_range_items:
                print(f"    [scraper] 跳过 {len(out_range_items)} 个过期条目 (超过3天):")
                for it in out_range_items:
                    print(f"             - {it['text'][:50]} (日期: {it.get('date', '未知')})")
            print(f"    [scraper] 将提取 {len(in_range_items)} 个近3天条目")

            if len(in_range_items) > max_detail_pages:
                in_range_items = in_range_items[:max_detail_pages]

            # 4. 逐个点击条目，捕获弹窗
            for i, item in enumerate(in_range_items):
                item_text = item["text"]
                print(f"    [scraper] [{i+1}/{len(in_range_items)}] {item_text[:60]}...")

                try:
                    # ★ 关键：每次重新加载干净的列表页
                    page.goto(list_url, wait_until="domcontentloaded")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)

                    # 按文字精确匹配链接
                    try:
                        target = page.get_by_text(item_text, exact=False).first
                    except Exception:
                        print(f"             get_by_text 失败，尝试模糊匹配...")
                        try:
                            target = page.locator(f"a:text-is('{item_text}')").first
                        except Exception:
                            target = page.locator(f"a:has-text('{item_text[:20]}')").first

                    detail_content = ""

                    # 尝试用 expect_page 捕获弹窗
                    popup_captured = False
                    try:
                        with context.expect_page(timeout=12000) as popup_event:
                            target.click(force=True, timeout=5000)
                        popup_page = popup_event.value
                        popup_page.wait_for_load_state("domcontentloaded", timeout=15000)
                        popup_page.wait_for_timeout(1500)
                        detail_content = _extract_page_text(popup_page)
                        popup_page.close()
                        popup_captured = True
                    except Exception as e:
                        # 没有弹窗：检查是否有页面跳转或内容变化
                        page.wait_for_timeout(2000)
                        current_text = _extract_page_text(page)
                        # 判断内容是否真的变了（不是列表页）
                        if len(current_text) > 100 and current_text[:200] != list_text[:200]:
                            detail_content = current_text
                        else:
                            # 可能弹窗被屏蔽，尝试直接获取所有打开的页面
                            if len(context.pages) > 1:
                                for pp in context.pages:
                                    if pp != page:
                                        try:
                                            detail_content = _extract_page_text(pp)
                                            pp.close()
                                            popup_captured = True
                                            break
                                        except Exception:
                                            pass

                    if not popup_captured and not detail_content:
                        detail_content = "[弹窗未捕获，请检查网站是否屏蔽了弹出窗口]"

                    # 截断过长的单条详情
                    if len(detail_content) > 3000:
                        detail_content = detail_content[:3000] + "... [已截断]"

                    result["details"].append({
                        "title": item_text,
                        "date": item.get("date", "未知"),
                        "content": detail_content,
                    })

                    time.sleep(3)  # 请求间隔

                except Exception as e:
                    print(f"             [失败] {e}")
                    result["details"].append({
                        "title": item_text,
                        "date": item.get("date", "未知"),
                        "content": f"[提取失败: {e}]",
                    })
                    time.sleep(2)

        except Exception as e:
            print(f"    [scraper] 致命错误: {e}")
        finally:
            browser.close()

    return result


def fetch_url(url: str, use_dynamic: bool = False) -> str:
    """
    统一入口：返回合并后的文本（兼容旧接口）
    动态页面 = 列表概览 + 各详情拼接
    """
    if use_dynamic:
        data = fetch_dynamic(url, follow_links=True)
        parts = [f"=== 列表页概览 ===\n{data['list_overview']}"]
        for d in data["details"]:
            parts.append(f"\n=== 详情: {d['title']} (日期: {d['date']}) ===\n{d['content']}")
        text = "\n\n".join(parts)
        if len(text) > MAX_CONTENT_LENGTH:
            text = text[:MAX_CONTENT_LENGTH] + "\n\n... [内容过长，已截断]"
        return text
    else:
        return fetch_static(url)
