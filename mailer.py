"""
邮件发送模块：QQ邮箱 SMTP，HTML 格式
直接展示网页原文内容，关键信息加粗高亮
"""
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, RECIPIENT_EMAIL,
    EMAIL_SUBJECT_MORNING, EMAIL_SUBJECT_EVENING,
)

# 需要高亮的字段关键词（正则）
HIGHLIGHT_PATTERNS = [
    # 薪资
    (r'(薪资待遇[：:]\s*[^\n]{0,100})', r'<strong style="color:#e65100;">\1</strong>'),
    (r'(薪资[：:]\s*[^\n]{0,80})', r'<strong style="color:#e65100;">\1</strong>'),
    (r'(月薪[：:]\s*[^\n]{0,80})', r'<strong style="color:#e65100;">\1</strong>'),
    (r'(年薪[：:]\s*[^\n]{0,80})', r'<strong style="color:#e65100;">\1</strong>'),
    (r'(\d+k以上)', r'<strong style="color:#e65100;">\1</strong>'),
    (r'(\d+k-\d+k)', r'<strong style="color:#e65100;">\1</strong>'),
    # 招聘人数
    (r'(招聘人数[：:]\s*[^\n]{0,50})', r'<strong style="color:#1565c0;">\1</strong>'),
    (r'(选聘\S*?\d+名)', r'<strong style="color:#1565c0;">\1</strong>'),
    # 工作地点
    (r'(工作地点[：:]\s*[^\n]{0,80})', r'<strong style="color:#2e7d32;">\1</strong>'),
    (r'(工作地址[：:]\s*[^\n]{0,80})', r'<strong style="color:#2e7d32;">\1</strong>'),
    (r'(公司地址[：:]\s*[^\n]{0,80})', r'<strong style="color:#2e7d32;">\1</strong>'),
    # 岗位需求/要求
    (r'(任职要求[：:])', r'<strong style="color:#6a1b9a;">\1</strong>'),
    (r'(岗位要求[：:])', r'<strong style="color:#6a1b9a;">\1</strong>'),
    (r'(基本要求[：:])', r'<strong style="color:#6a1b9a;">\1</strong>'),
    (r'(学历要求[：:]\s*[^\n]{0,80})', r'<strong style="color:#6a1b9a;">\1</strong>'),
    (r'(专业要求[：:]\s*[^\n]{0,100})', r'<strong style="color:#6a1b9a;">\1</strong>'),
    # 工作类型/时长
    (r'(工作类型[：:]\s*[^\n]{0,50})', r'<strong style="color:#00695c;">\1</strong>'),
    (r'(工作形式[：:]\s*[^\n]{0,50})', r'<strong style="color:#00695c;">\1</strong>'),
    (r'(全职|实习|兼职|校招|社招)', r'<strong style="color:#00695c;">\1</strong>'),
    # 截止日期/报名时间
    (r'(网[上申]报[名名]时间[：:]\s*[^\n]{0,100})', r'<strong style="color:#d84315;">\1</strong>'),
    (r'(报名时间[：:]\s*[^\n]{0,80})', r'<strong style="color:#d84315;">\1</strong>'),
    (r'(截止\S*?[：:]\s*[^\n]{0,80})', r'<strong style="color:#d84315;">\1</strong>'),
    (r'(招聘期限[：:]\s*[^\n]{0,50})', r'<strong style="color:#d84315;">\1</strong>'),
    # 联系方式
    (r'(联系\S*?[：:]\s*[^\n]{0,100})', r'<strong style="color:#0277bd;">\1</strong>'),
    (r'(\S*?邮箱[：:]\s*[^\n]{0,80})', r'<strong style="color:#0277bd;">\1</strong>'),
    (r'(\S*?电话[：:]\s*[^\n]{0,80})', r'<strong style="color:#0277bd;">\1</strong>'),
    # 用人单位
    (r'(单位名称[：:]\s*[^\n]{0,80})', r'<strong style="color:#37474f;">\1</strong>'),
    # 发布日期
    (r'(发布日期[：:]\s*[^\n]{0,30})', r'<span style="color:#999;font-size:11px;">\1</span>'),
    (r'(更新时间[：:]\s*[^\n]{0,30})', r'<span style="color:#999;font-size:11px;">\1</span>'),
]

# 要去掉的导航/页脚行
STRIP_LINES = [
    "毕业生派遣", "单位登录", "注册", "校园招聘", "专场招聘会",
    "校园双选会", "空中宣讲", "招聘公告", "岗位信息", "实习信息",
    "基层就业", "学院就业", "科研助理", "你现在的位置:", "首页",
    "上一页", "下一页", "联系我们", "办公地址：", "电子邮箱：",
    "就业热线", "就业手续办理：", "单位服务热线：", "生涯规划咨询：",
    "教师登录", '"科大就业"公众号', "Copyright", "皖ICP备",
    "Designed", "by Wanhu", "操作", "查看详情",
]


def _clean_and_highlight(content: str) -> str:
    """清洗内容（去掉导航行）+ 关键字段高亮"""
    # 1. 去掉导航行
    lines = content.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append("")
            continue
        skip = False
        for noise in STRIP_LINES:
            if noise in stripped and len(stripped) < 30:
                skip = True
                break
        if not skip:
            clean_lines.append(line)

    text = "\n".join(clean_lines)

    # 2. 合并连续空行
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 3. HTML 转义
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 4. 高亮关键字段
    for pattern, replacement in HIGHLIGHT_PATTERNS:
        text = re.sub(pattern, replacement, text)

    # 5. 换行转 <br>
    text = text.replace("\n", "<br>")

    return text


def _build_detail_section(structured: list[dict], details: list[dict]) -> str:
    """
    直接展示每条详情的原文，关键信息加粗
    """
    if not details:
        return "<p style='color:#999;'>暂无招聘详情内容</p>"

    html_parts = []

    # 用 structured 的结果构建快速信息条
    if structured:
        quick_info = '<div style="background:#f5f5f5;padding:10px;border-radius:6px;margin-bottom:12px;font-size:12px;">'
        quick_info += "<strong>快速概览:</strong><br>"
        for s in structured[:15]:
            parts = []
            if s.get("company") and s["company"] != "未注明":
                parts.append(f"<b>{s['company']}</b>")
            if s.get("position") and s["position"] != "未注明":
                parts.append(s["position"])
            if s.get("salary") and s["salary"] != "未注明":
                parts.append(f"💰{s['salary']}")
            if s.get("location") and s["location"] != "未注明":
                parts.append(f"📍{s['location']}")
            if s.get("work_type") and s["work_type"] != "未注明":
                parts.append(f"📋{s['work_type']}")
            title = s.get("title", "")[:60]
            if parts:
                quick_info += f"• {title} → {' | '.join(parts)}<br>"
        quick_info += "</div>"
        html_parts.append(quick_info)

    # 每条详情的原文
    for i, d in enumerate(details):
        title = d.get("title", "无标题")
        date_str = d.get("date", "")
        content = d.get("content", "")

        # 跳过无内容和纯失败的
        if not content or content.startswith("[提取失败"):
            continue
        if content.startswith("[弹窗未捕获"):
            continue

        highlighted = _clean_and_highlight(content)

        date_tag = f' <span style="color:#999;font-size:11px;">({date_str})</span>' if date_str else ""

        html_parts.append(f"""
        <div style="border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin-bottom:12px;">
            <div style="font-weight:bold;font-size:14px;color:#1a73e8;margin-bottom:8px;">
                {i+1}. {title}{date_tag}
            </div>
            <div style="font-size:13px;line-height:1.8;color:#333;word-break:break-all;">
                {highlighted}
            </div>
        </div>""")

    return "\n".join(html_parts) if html_parts else "<p style='color:#999;'>所有详情内容为空</p>"


def build_html_body(report: dict, is_morning: bool) -> str:
    """构建单个网址的 HTML 邮件片段"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tag = "上午版" if is_morning else "晚间版(含变化)"

    url_name = report.get("url_name", "未知")
    url = report.get("url", "")
    summary = report.get("summary", {})
    structured = report.get("structured", [])
    details = report.get("details", [])
    changes = report.get("changes", [])

    category = summary.get("category", "")
    overview = summary.get("summary", "")
    keywords = summary.get("keywords", [])

    kw_tags = " ".join(
        f'<span style="background:#e8f0fe;color:#1a73e8;padding:2px 8px;border-radius:12px;font-size:12px;margin:0 2px;">#{kw}</span>'
        for kw in keywords
    ) if keywords else ""

    change_html = ""
    if changes:
        change_items = "".join(
            f'<li style="margin:2px 0;">{c["type"]} {c["description"]}</li>'
            for c in changes
        )
        change_html = f"""
        <div style="margin:12px 0;padding:10px 14px;background:#fff8e1;border-left:3px solid #f9ab00;font-size:13px;">
            <strong>变化:</strong><ul style="margin:4px 0;padding-left:20px;">{change_items}</ul>
        </div>"""

    detail_html = _build_detail_section(structured, details)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:'Microsoft YaHei','PingFang SC',sans-serif;max-width:750px;margin:0 auto;padding:20px;">

<div style="border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin-bottom:16px;">
  <div style="font-weight:bold;font-size:15px;">
    {url_name}
    <span style="font-size:11px;color:#999;font-weight:normal;">[{category}]</span>
  </div>
  <div style="font-size:12px;color:#999;margin-bottom:8px;">
    <a href="{url}" style="color:#1a73e8;">{url}</a>
  </div>
  <div style="font-size:14px;color:#333;line-height:1.6;">{overview}</div>
  <div style="margin-top:8px;">{kw_tags}</div>
  {change_html}
</div>

<h3 style="color:#333;font-size:15px;margin-top:16px;">详细信息原文</h3>
{detail_html}

<hr style="border:0;border-top:1px solid #eee;margin-top:20px;">
<p style="color:#999;font-size:11px;text-align:center;">由 Web Monitor 自动生成 | {tag} | {now}</p>
</body></html>"""

    return html


def send_email(report_or_reports, is_morning: bool = True) -> bool:
    """发送邮件，兼容新旧格式"""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("[mailer] 未配置 SMTP，跳过邮件发送")
        return False

    subject = EMAIL_SUBJECT_MORNING if is_morning else EMAIL_SUBJECT_EVENING
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tag = "上午版" if is_morning else "晚间版(含变化)"

    if isinstance(report_or_reports, list):
        html_parts = []
        for r in report_or_reports:
            html_parts.append(build_html_body(r, is_morning))
        separator = "<hr style='border:2px dashed #1a73e8;margin:24px 0;'>"
        html_body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
        <body style="font-family:'Microsoft YaHei','PingFang SC',sans-serif;max-width:750px;margin:0 auto;padding:20px;">
        <h2 style="color:#1a73e8;">网页监控日报 — {tag}</h2>
        <p style="color:#666;">生成时间: {now}</p>
        {separator.join(html_parts)}
        <hr style="border:0;border-top:1px solid #eee;margin-top:20px;">
        <p style="color:#999;font-size:11px;text-align:center;">由 Web Monitor 自动生成并发送</p>
        </body></html>"""
    else:
        html_body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
        <body style="font-family:'Microsoft YaHei','PingFang SC',sans-serif;max-width:750px;margin:0 auto;padding:20px;">
        <h2 style="color:#1a73e8;">网页监控日报 — {tag}</h2>
        <p style="color:#666;">生成时间: {now}</p>
        {build_html_body(report_or_reports, is_morning)}
        <hr style="border:0;border-top:1px solid #eee;margin-top:20px;">
        <p style="color:#999;font-size:11px;text-align:center;">由 Web Monitor 自动生成并发送</p>
        </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, RECIPIENT_EMAIL, msg.as_string())
        print(f"[mailer] 邮件已发送至 {RECIPIENT_EMAIL}")
        return True
    except Exception as e:
        print(f"[mailer] 邮件发送失败: {e}")
        return False
