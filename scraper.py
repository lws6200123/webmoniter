"""
网页抓取模块：静态页面 (requests+BS4) + 动态页面 (Playwright)
支持列表->详情页面的自动跟踪
"""
import time
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
    '#content', '.content', '.main-content',
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


def _find_list_items(page) -> list[dict]:
    """
    在列表中找出可点击的条目
    返回 [{"text": "标题文字", "href": "链接或onclick"}, ...]
    """
    items = page.evaluate("""() => {
        const results = [];
        const seenTexts = new Set();

        // 优先在列表/表格区域找
        const containers = document.querySelectorAll(
            'table a, ul a, ol a, .list a, [class*="list"] a, [id*="list"] a, ' +
            '.news a, [class*="news"] a, .jobs a, [class*="job"] a, ' +
            '.content a, [class*="item"] a, .entry a'
        );
        const anchors = containers.length > 0 ? containers : document.querySelectorAll('a');

        for (let i = 0; i < anchors.length; i++) {
            const a = anchors[i];
            const text = (a.innerText || a.textContent || '').trim();

            if (!text || text.length < 8) continue;
            if (text === '下一页' || text === '上一页' || text === '首页' || text === '尾页') continue;
            if (text === '查看详情') continue;
            if (/^[0-9]+$/.test(text)) continue;
            if (text.length > 120) continue;

            const rect = a.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;

            const key = text.substring(0, 40);
            if (seenTexts.has(key)) continue;
            seenTexts.add(key);

            results.push({
                text: text.substring(0, 100),
                href: a.href || a.getAttribute('onclick') || '',
                tagName: a.tagName
            });
        }
        return results;
    }""")

    return items


def fetch_dynamic(url: str, follow_links: bool = True, max_detail_pages: int = 5) -> str:
    """
    动态页面抓取：Playwright headless 浏览器
    通过文字匹配定位链接，逐个点击并捕获弹窗/详情页
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

        all_text_parts = []

        try:
            # 1. 加载列表页
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)

            # 2. 提取列表概览
            list_text = _extract_page_text(page)
            list_preview = list_text[:600].replace("\n", " | ")
            all_text_parts.append(f"=== 列表页概览 ===\n{list_preview}")

            if not follow_links:
                all_text_parts.append(f"\n=== 列表页完整内容 ===\n{list_text}")
                return "\n\n".join(all_text_parts)[:MAX_CONTENT_LENGTH]

            # 3. 发现条目
            items = _find_list_items(page)
            if len(items) > max_detail_pages:
                items = items[:max_detail_pages]

            print(f"    [scraper] 发现 {len(items)} 个条目，将逐一提取详情...")

            # 4. 按文字匹配点击（不依赖序号）
            list_url = page.url
            for i, item in enumerate(items):
                item_text = item["text"]
                print(f"    [scraper] [{i+1}/{len(items)}] {item_text[:50]}...")

                try:
                    # 按文字匹配定位元素
                    try:
                        target = page.get_by_text(item_text, exact=False).first
                        if not target:
                            target = page.locator(f"a:has-text('{item_text[:30]}')").first
                    except Exception:
                        continue

                    detail_text = ""

                    # 尝试捕获弹窗
                    try:
                        with context.expect_page(timeout=10000) as popup_event:
                            target.click(force=True)
                        popup_page = popup_event.value
                        popup_page.wait_for_load_state("domcontentloaded", timeout=15000)
                        popup_page.wait_for_timeout(1000)
                        detail_text = _extract_page_text(popup_page)
                        if not detail_text:
                            detail_text = "[弹窗打开但无文字内容]"
                        popup_page.close()
                    except Exception:
                        # 无弹窗：可能是页面内变化
                        page.wait_for_timeout(2000)
                        current_text = _extract_page_text(page)
                        if current_text[:200] != list_text[:200]:
                            detail_text = current_text
                        else:
                            detail_text = "[点击后内容无变化，可能需额外操作]"

                    if len(detail_text) > 2500:
                        detail_text = detail_text[:2500] + "... [已截断]"

                    all_text_parts.append(f"\n=== 详情: {item_text} ===\n{detail_text or '[空]'}")

                    time.sleep(3)

                except Exception as e:
                    all_text_parts.append(f"\n=== 详情: {item_text} ===\n[失败: {e}]")
                    time.sleep(2)

        except Exception as e:
            all_text_parts.append(f"[Playwright 失败: {e}]")
        finally:
            browser.close()

    text = "\n\n".join(all_text_parts)
    if len(text) > MAX_CONTENT_LENGTH:
        text = text[:MAX_CONTENT_LENGTH] + "\n\n... [内容过长，已截断]"
    return text


def fetch_url(url: str, use_dynamic: bool = False) -> str:
    """统一入口"""
    if use_dynamic:
        return fetch_dynamic(url, follow_links=True)
    else:
        return fetch_static(url)
