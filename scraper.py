"""
网页抓取模块：静态页面 + 动态页面 (Playwright)
核心：列表页 → 点击弹窗 → 滚动加载全文 → 提取纯文本
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


def fetch_static(url: str) -> str:
    """静态页面：requests + BeautifulSoup"""
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    doc = Document(resp.text)
    soup = BeautifulSoup(doc.summary(), "lxml")
    text = soup.get_text(separator="\n", strip=True)
    return text[:MAX_CONTENT_LENGTH] if len(text) > MAX_CONTENT_LENGTH else text


def _page_text(page, filter_noise: bool = True) -> str:
    """提取 Playwright page 正文，自动去导航/页脚"""
    html = page.evaluate("""() => {
        const sel = document.querySelector(
            'article, main, [role="main"], .detail-content, .news-content, ' +
            '.info-content, #content, .content, .main-content, .detail, ' +
            '.post-content, .article-content, .entry-content'
        );
        return (sel || document.body).outerHTML;
    }""")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()

    if filter_noise:
        # 去掉明显的导航/页脚行
        noise = [
            "毕业生派遣", "单位登录", "注册", "校园招聘", "专场招聘会",
            "校园双选会", "空中宣讲", "招聘公告", "岗位信息", "实习信息",
            "基层就业", "学院就业", "科研助理", "你现在的位置", "首页",
            "上一页", "下一页", "联系我们", "办公地址", "电子邮箱",
            "就业热线", "就业手续办理", "单位服务热线", "生涯规划咨询",
            "教师登录", "科大就业", "Copyright", "皖ICP备",
            "Designed", "by Wanhu", "查看详情",
        ]
        for tnav in soup(["nav", "footer", "header"]):
            tnav.decompose()
        # 移除短导航行
        for tag in soup.find_all(text=True):
            txt = tag.strip()
            if any(n in txt for n in noise) and len(txt) < 25:
                tag.extract()

    return soup.get_text(separator="\n", strip=True)


def _scroll_to_bottom(page):
    """滚动页面到底，触发懒加载"""
    prev_height = -1
    for _ in range(10):
        cur_height = page.evaluate("document.body.scrollHeight")
        if cur_height == prev_height:
            break
        prev_height = cur_height
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
    page.evaluate("window.scrollTo(0, 0)")  # 滚回顶部


# ======== USTC 专用条目提取 ========

def _find_job_items(page) -> list[dict]:
    """
    精准识别招聘条目：从表格行中提取 标题 + 日期
    只保留能打开详情弹窗的链接（标题文字 ≥10字，不是公司名/导航）
    返回 [{"text": "标题", "date": "日期"}, ...]
    """
    items = page.evaluate("""() => {
        const results = [];
        const seenItemIds = new Set();
        const seenTexts = new Set();

        // 策略1: 找所有 itemid=XXXX 的详情链接（USTC 岗位/公告）
        const allLinks = document.querySelectorAll('a[href*="itemid="]');
        for (const a of allLinks) {
            const href = a.href || '';
            const text = (a.innerText || a.textContent || '').trim();

            // 跳过公司简介页（info.aspx）
            if (href.includes('info.aspx')) continue;

            // 提取 itemid
            const idMatch = href.match(/itemid=(\\d+)/);
            const itemId = idMatch ? idMatch[1] : '';

            // 按 itemid 去重（job title 和 "查看详情" 共享同一个 itemid）
            // 优先保留文字更长的（job title 比 "查看详情" 更有信息量）
            if (itemId && seenItemIds.has(itemId)) {
                // 更新已有条目的文字（如果当前文字更好）
                const existing = results.find(r => r.itemId === itemId);
                if (existing && text.length > 8 && text !== '查看详情' && text.length > existing.text.length) {
                    existing.text = text.substring(0, 100);
                }
                continue;
            }
            if (itemId) seenItemIds.add(itemId);

            // 跳过太短和纯导航
            if (text === '查看详情') {
                // "查看详情" 也保留，但标记为需要从附近找标题
                // 暂不处理，等 itemid 匹配时会自动和标题合并
            }
            if (text.length < 6 && text !== '查看详情') continue;
            if (/^[0-9]+$/.test(text)) continue;
            if (text.length > 150) continue;

            // 去重文字
            const textKey = text.substring(0, 40);
            if (seenTexts.has(textKey) && text !== '查看详情') continue;
            seenTexts.add(textKey);

            // 从父级容器提取日期
            let parent = a.closest('tr, li, .item, [class*="item"], div, td');
            let date = '';
            if (parent) {
                const pt = (parent.innerText || parent.textContent || '').trim();
                const dm = pt.match(/(\\d{4}[-/]\\d{1,2}[-/]\\d{1,2})/);
                if (dm) date = dm[1];
            }

            results.push({
                text: text.substring(0, 100),
                date: date || '',
                itemId: itemId,
                href: href
            });
        }

        // 策略2: 如果 itemid 链接没找到结果，回退到查找 table tr
        if (results.length === 0) {
            const rows = document.querySelectorAll('table tr');
            for (const row of rows) {
                const links = row.querySelectorAll('a');
                let bestText = '';
                let rowDate = '';
                const rowText = (row.innerText || row.textContent || '').trim();
                const dateMatch = rowText.match(/(\\d{4}[-/]\\d{1,2}[-/]\\d{1,2})/);
                if (dateMatch) rowDate = dateMatch[1];

                for (const a of links) {
                    const t = (a.innerText || a.textContent || '').trim();
                    if (!t || t === '查看详情') continue;
                    if (t.length > bestText.length) bestText = t;
                }
                if (!bestText || bestText.length < 8) continue;
                const key = bestText.substring(0, 40);
                if (seenTexts.has(key)) continue;
                seenTexts.add(key);

                results.push({
                    text: bestText.substring(0, 100),
                    date: rowDate || '',
                    itemId: '',
                    href: ''
                });
            }
        }

        // 策略3: 最后回退 —— 文字 ≥12 的普通链接
        if (results.length === 0) {
            for (const a of document.querySelectorAll('a')) {
                const t = (a.innerText || a.textContent || '').trim();
                if (!t || t.length < 12 || t.length > 120) continue;
                if (t === '下一页' || t === '上一页' || t === '首页') continue;
                if (/^[0-9]+$/.test(t)) continue;
                const rect = a.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const key = t.substring(0, 40);
                if (seenTexts.has(key)) continue;
                seenTexts.add(key);

                let parent = a.closest('tr, li, .item, [class*="item"], div');
                let date = '';
                if (parent) {
                    const pt = (parent.innerText || parent.textContent || '').trim();
                    const dm = pt.match(/(\\d{4}[-/]\\d{1,2}[-/]\\d{1,2})/);
                    if (dm) date = dm[1];
                }
                results.push({
                    text: t.substring(0, 100),
                    date: date || '',
                    itemId: '',
                    href: a.href || ''
                });
            }
        }

        return results;
    }""")

    # 日期过滤 + 噪声过滤
    today = datetime.now().date()
    cutoff = today - timedelta(days=3)

    # 噪声关键词（非职位条目标志）
    noise_words = ["皖ICP备", "Copyright", "Designed", "Wanhu", "教师登录"]

    filtered = []
    for item in items:
        text = item["text"]
        # 跳过明显噪声
        if any(n in text for n in noise_words):
            continue
        # 跳过太短的和纯数字
        if len(text) < 10:
            continue

        date_obj = None
        if item.get("date"):
            for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
                try:
                    date_obj = datetime.strptime(item["date"], fmt).date()
                    break
                except ValueError:
                    pass

        if date_obj is not None and date_obj < cutoff:
            continue

        filtered.append({
            "text": text,
            "date": item.get("date", "未知"),
        })

    return filtered


def fetch_dynamic(url: str, follow_links: bool = True, max_pages: int = 15) -> dict:
    """
    动态页面：加载列表 → 逐条点击 → 捕获弹窗 → 滚动到底 → 提取全文
    返回 {"list_overview": "列表概览", "details": [{"title","date","content"},...]}
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="zh-CN",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.set_default_timeout(PLAYWRIGHT_TIMEOUT)

        result = {"list_overview": "", "details": []}

        try:
            # 1. 加载列表页
            print("    [scraper] 加载列表页...")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)

            # 2. 列表概览
            list_text = _page_text(page, filter_noise=True)
            result["list_overview"] = list_text[:800]

            if not follow_links:
                browser.close()
                return result

            # 3. 识别可点击条目 + 日期过滤
            items = _find_job_items(page)
            list_url = page.url

            if len(items) > max_pages:
                items = items[:max_pages]

            print(f"    [scraper] 识别到 {len(items)} 个有效条目，开始逐条抓取详情...")

            for i, item in enumerate(items):
                item_text = item["text"]
                item_date = item.get("date", "")
                print(f"    [scraper] [{i+1}/{len(items)}] {item_text[:55]}...")

                detail_content = ""

                try:
                    # ★ 重新加载干净的列表页
                    page.goto(list_url, wait_until="domcontentloaded")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)

                    # 按文字或 itemid 定位链接
                    target = None
                    # 优先用 href 属性匹配（更精确）
                    if item.get("itemId"):
                        try:
                            target = page.locator(f'a[href*="itemid={item["itemId"]}"]').first
                        except Exception:
                            pass
                    # 回退到文字匹配
                    if not target:
                        try:
                            target = page.get_by_text(item_text, exact=False).first
                        except Exception:
                            pass
                    if not target:
                        try:
                            target = page.locator(f"a:has-text('{item_text[:30]}')").first
                        except Exception:
                            pass

                    if not target:
                        detail_content = "[未找到对应链接]"
                        result["details"].append({"title": item_text, "date": item_date, "content": detail_content})
                        print(f"             [跳过] 未找到链接")
                        continue

                    # ★ 尝试捕获弹窗
                    popup_captured = False
                    try:
                        with context.expect_page(timeout=15000) as popup_event:
                            target.click(force=True, timeout=5000)
                        popup_page = popup_event.value
                        popup_page.wait_for_load_state("domcontentloaded", timeout=15000)
                        popup_page.wait_for_timeout(2000)

                        # 滚动到底，加载所有内容
                        _scroll_to_bottom(popup_page)
                        popup_page.wait_for_timeout(500)

                        detail_content = _page_text(popup_page, filter_noise=True)
                        popup_page.close()
                        popup_captured = True
                    except Exception:
                        # 没弹窗：可能页面内跳转或模态框
                        page.wait_for_timeout(2000)

                        if page.url != list_url:
                            # URL 变了 = 页面跳转
                            page.wait_for_load_state("networkidle", timeout=10000)
                            page.wait_for_timeout(1000)
                            _scroll_to_bottom(page)
                            detail_content = _page_text(page, filter_noise=True)
                        else:
                            # URL 没变：检查是否有模态框/内容区变化
                            # 尝试提取正文区域（可能是 AJAX 加载）
                            detail_content = _page_text(page, filter_noise=True)

                            # 如果内容和列表页一样，说明没打开详情
                            if detail_content[:200] == list_text[:200]:
                                # 尝试最后一次：找所有打开的页面
                                other_pages = [pp for pp in context.pages if pp != page]
                                if other_pages:
                                    for pp in other_pages:
                                        try:
                                            _scroll_to_bottom(pp)
                                            detail_content = _page_text(pp, filter_noise=True)
                                            pp.close()
                                            popup_captured = True
                                            break
                                        except Exception:
                                            pass

                    if not popup_captured and detail_content[:200] == list_text[:200]:
                        detail_content = "[未成功打开详情页，内容与列表页相同]"

                    # 截断过长内容
                    if len(detail_content) > 6000:
                        detail_content = detail_content[:6000] + "\n... [已截断]"

                    result["details"].append({"title": item_text, "date": item_date, "content": detail_content})

                    if popup_captured:
                        print(f"             [弹窗] 提取 {len(detail_content)} 字符")
                    else:
                        print(f"             [直接] 提取 {len(detail_content)} 字符")

                    time.sleep(3)

                except Exception as e:
                    print(f"             [失败] {e}")
                    result["details"].append({"title": item_text, "date": item_date, "content": f"[失败: {e}]"})
                    time.sleep(2)

        except Exception as e:
            print(f"    [scraper] 致命错误: {e}")
        finally:
            browser.close()

    return result


def fetch_url(url: str, use_dynamic: bool = False) -> str:
    """合并文本（兼容旧接口）"""
    if use_dynamic:
        data = fetch_dynamic(url, follow_links=True)
        parts = [f"=== 列表页 ===\n{data['list_overview']}"]
        for d in data["details"]:
            parts.append(f"\n=== {d['title']} ({d.get('date','?')}) ===\n{d['content']}")
        text = "\n\n".join(parts)
        return text[:MAX_CONTENT_LENGTH] + "\n... [已截断]" if len(text) > MAX_CONTENT_LENGTH else text
    return fetch_static(url)
