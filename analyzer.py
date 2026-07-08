"""
信息分析模块：调用 Claude API 做摘要、关键词提取、变化对比
"""
import json
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def _extract_text(response) -> str:
    """兼容新版 Anthropic API：正确处理 ThinkingBlock 和 TextBlock"""
    parts = []
    for block in response.content:
        if hasattr(block, 'text'):
            parts.append(block.text)
    return ''.join(parts).strip()

# 早上分析用的 system prompt
MORNING_SYSTEM_PROMPT = """你是一个专业的信息分析助手。用户会给你一段网页内容，请你：

1. **分类**: 判断内容属于什么类别（如：政策法规、行业新闻、技术博客、学术论文、产品更新等）
2. **摘要**: 用中文写一个100字以内的摘要，提取最核心的信息
3. **关键词**: 提取 3-5 个关键词（中文或英文均可）

请严格按照以下 JSON 格式返回，不要包含其他内容：
{
  "category": "类别",
  "summary": "摘要内容",
  "keywords": ["关键词1", "关键词2", "关键词3"]
}"""

# 晚上分析用的 system prompt（含变化对比）
EVENING_SYSTEM_PROMPT = """你是一个专业的信息分析助手。用户会给你两段网页内容——上午抓取的内容和晚上抓取的内容，请你：

1. **分类**: 判断内容属于什么类别
2. **摘要**: 用中文写一个100字以内的摘要，提取最核心的信息（基于最新内容）
3. **关键词**: 提取 3-5 个关键词
4. **变化**: 对比上午和晚上的内容，标注变化类型：
   - "🆕新增" — 晚上有而上午没有的信息
   - "❌删除" — 上午有而晚上没有的信息
   - "✏️修改" — 同一信息但内容有变化
   - "—" — 无变化

请严格按照以下 JSON 格式返回，不要包含其他内容：
{
  "category": "类别",
  "summary": "摘要内容",
  "keywords": ["关键词1", "关键词2"],
  "changes": [
    {"type": "🆕新增", "description": "具体新增了什么"},
    {"type": "✏️修改", "description": "具体修改了什么"}
  ]
}"""


def analyze_morning(content: str, url_name: str = "") -> dict:
    """
    早上分析：提取分类、摘要、关键词
    返回 {"category": str, "summary": str, "keywords": list}
    """
    if not content or not content.strip():
        return {"category": "无内容", "summary": "页面无有效内容", "keywords": []}

    user_message = f"网页来源: {url_name}\n\n网页内容:\n{content}"

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=MORNING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        text = _extract_text(response)
        # 尝试提取 JSON（去掉可能的 markdown 代码块包裹）
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)

    except Exception as e:
        return {"category": "分析失败", "summary": f"LLM 分析出错: {e}", "keywords": []}


def analyze_evening(morning_content: str, evening_content: str, url_name: str = "") -> dict:
    """
    晚上分析：对比上午和晚上内容，标注变化
    返回 {"category": str, "summary": str, "keywords": list, "changes": list}
    """
    if not evening_content or not evening_content.strip():
        return {"category": "无内容", "summary": "页面无有效内容", "keywords": [], "changes": []}

    user_message = f"""网页来源: {url_name}

===== 上午抓取的内容 =====
{morning_content if morning_content else "（无上午快照）"}

===== 晚上抓取的内容 =====
{evening_content}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=EVENING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        text = _extract_text(response)
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text)

    except Exception as e:
        return {"category": "分析失败", "summary": f"LLM 分析出错: {e}", "keywords": [], "changes": []}
