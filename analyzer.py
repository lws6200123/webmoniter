"""
信息分析模块：调用 Claude API 做结构化提取、摘要和变化对比
"""
import json
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def _extract_text(response) -> str:
    """兼容新版 Anthropic API"""
    parts = []
    for block in response.content:
        if hasattr(block, 'text'):
            parts.append(block.text)
    return ''.join(parts).strip()


def _parse_json(text: str) -> dict:
    """解析 LLM 返回的 JSON（去掉 markdown 包裹，处理常见格式问题）"""
    text = text.strip()
    # 去掉 markdown 代码块
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) > 1:
            text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # 尝试直接解析
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result] if "title" in result else result
    except json.JSONDecodeError:
        pass

    # 尝试修复：截断未完成的最后一个字符串
    try:
        # 找到最后一个完整的对象
        fixed = text.strip()
        if fixed.endswith(','):
            fixed = fixed[:-1]
        if not fixed.endswith(']'):
            # 找到最后一个 } 后加 ]
            last_brace = fixed.rfind('}')
            if last_brace >= 0:
                fixed = fixed[:last_brace + 1] + '\n]'
        result = json.loads(fixed)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试逐个对象解析
    results = []
    # 用正则找到每个 {...} 对象
    import re
    # 简单方法：按 "title" 分割
    for match in re.finditer(r'\{[^}]*"title"[^}]*\}', text, re.DOTALL):
        try:
            obj = json.loads(match.group())
            results.append(obj)
        except json.JSONDecodeError:
            continue
    if results:
        return results

    # 最终降级
    raise ValueError(f"无法解析 JSON，原始文本前200字符: {text[:200]}")


# ======== 结构化提取 Prompt ========

EXTRACT_STRUCTURED_PROMPT = """你是一个招聘信息提取助手。用户会给你若干条招聘/公告的详细内容，请从每条中提取以下结构化字段。

对每条信息，提取：

- title: 招聘标题/职位名称
- company: 用人单位名称
- industry: 所属行业（如：教育、互联网、金融、制造业、医疗等）
- position: 具体岗位名称
- salary: 薪资待遇（如"20k以上""面议""年薪15-20万"等，没有则填"未注明"）
- location: 工作地点/城市
- work_type: 工作类型（全职/实习/兼职/校招/社招）
- education: 学历要求
- requirements: 核心要求摘要（50字以内，提炼最关键的2-3条）
- deadline: 报名/投递截止日期（没有则填"未注明"）
- contact: 联系方式（邮箱/电话/联系人，没有则填"未注明"）

如果某条信息中某字段不存在，填写"未注明"。如果内容是公告类而非招聘信息，填法一样，把能提取的字段填上。

请严格返回以下 JSON 格式（一个数组，每条一个对象）：
[
  {
    "title": "...",
    "company": "...",
    "industry": "...",
    "position": "...",
    "salary": "...",
    "location": "...",
    "work_type": "...",
    "education": "...",
    "requirements": "...",
    "deadline": "...",
    "contact": "..."
  }
]"""


def analyze_structured(details: list[dict], url_name: str = "", batch_size: int = 5) -> list[dict]:
    """
    批量提取结构化信息（自动分批，每批最多 batch_size 条）
    """
    if not details:
        return []

    all_results = []

    for batch_start in range(0, len(details), batch_size):
        batch = details[batch_start:batch_start + batch_size]
        items_text = []
        for i, d in enumerate(batch):
            items_text.append(
                f"【信息{batch_start + i + 1}】\n"
                f"原标题: {d.get('title', '未知')}\n"
                f"日期: {d.get('date', '未知')}\n"
                f"内容:\n{d.get('content', '无内容')[:3000]}\n"  # 每条限3000字符
            )

        user_message = f"网页来源: {url_name}\n\n" + "\n---\n".join(items_text)

        batch_result = _extract_single_batch(user_message)
        all_results.extend(batch_result)
        print(f"    [analyzer] 批次 {batch_start//batch_size + 1}: {len(batch_result)}/{len(batch)} 条")

    print(f"    [analyzer] 结构化提取完成，共 {len(all_results)} 条")
    return all_results


def _extract_single_batch(user_message: str) -> list[dict]:
    """提取单批（最多5条）的结构化信息"""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=EXTRACT_STRUCTURED_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        text = _extract_text(response)
        if not text or not text.strip():
            print(f"    [analyzer] 警告：LLM 返回空内容")
            return []
        return _parse_json(text)
    except Exception as e:
        print(f"    [analyzer] 批次提取失败: {e}")
        return []


# ======== 概览摘要 Prompt（保留给列表页） ========

MORNING_SUMMARY_PROMPT = """你是一个招聘信息分析助手。下面是某个网页列表页的内容概览，请写一个100字以内的摘要，概括最近发布了哪些类型的招聘信息。

返回 JSON 格式：
{
  "category": "分类（如：校园招聘、社会招聘、实习信息等）",
  "summary": "100字以内摘要",
  "keywords": ["关键词1", "关键词2", "关键词3"]
}"""

EVENING_SUMMARY_PROMPT = """你是一个招聘信息分析助手。下面是某个网页上午和晚上的内容对比，请写一个100字以内摘要，标注变化。

返回 JSON 格式：
{
  "category": "分类",
  "summary": "100字以内摘要",
  "keywords": ["关键词1", "关键词2"],
  "changes": [{"type": "新增/修改/删除", "description": "具体变化"}]
}"""


def analyze_summary(content: str, url_name: str = "") -> dict:
    """列表页概览摘要"""
    if not content or not content.strip():
        return {"category": "无内容", "summary": "页面无有效内容", "keywords": []}

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=MORNING_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": f"网页: {url_name}\n\n{content[:2000]}"}],
        )
        return _parse_json(_extract_text(response))
    except Exception as e:
        return {"category": "分析失败", "summary": f"LLM 出错: {e}", "keywords": []}


# ======== 保持旧接口兼容 ========

MORNING_SYSTEM_PROMPT = """你是一个专业的信息分析助手。用户会给你一段网页内容，请你：
1. **分类**: 判断内容属于什么类别
2. **摘要**: 用中文写一个100字以内的摘要
3. **关键词**: 提取 3-5 个关键词
请严格按照 JSON 格式返回：{"category": "...", "summary": "...", "keywords": [...]}"""

EVENING_SYSTEM_PROMPT = """你是一个专业的信息分析助手。对比上午和晚上的内容，标注变化。
返回 JSON：{"category": "...", "summary": "...", "keywords": [...], "changes": [{"type": "新增/修改/删除", "description": "..."}]}"""


def analyze_morning(content: str, url_name: str = "") -> dict:
    if not content or not content.strip():
        return {"category": "无内容", "summary": "页面无有效内容", "keywords": []}
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=MORNING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"网页来源: {url_name}\n\n网页内容:\n{content}"}],
        )
        return _parse_json(_extract_text(response))
    except Exception as e:
        return {"category": "分析失败", "summary": f"LLM 分析出错: {e}", "keywords": []}


def analyze_evening(morning_content: str, evening_content: str, url_name: str = "") -> dict:
    if not evening_content or not evening_content.strip():
        return {"category": "无内容", "summary": "页面无有效内容", "keywords": [], "changes": []}
    user_message = f"网页来源: {url_name}\n\n===== 上午 =====\n{morning_content or '(无)'}\n\n===== 晚上 =====\n{evening_content}"
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=EVENING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return _parse_json(_extract_text(response))
    except Exception as e:
        return {"category": "分析失败", "summary": f"LLM 出错: {e}", "keywords": [], "changes": []}
