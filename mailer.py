"""
邮件发送模块：QQ邮箱 SMTP，HTML 格式邮件
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, RECIPIENT_EMAIL,
    EMAIL_SUBJECT_MORNING, EMAIL_SUBJECT_EVENING,
)


def build_html_body(results: list[dict], is_morning: bool) -> str:
    """
    根据分析结果构建 HTML 邮件正文
    results: [{"url_name": str, "url": str, "category": str,
               "summary": str, "keywords": list, "changes": list}]
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tag = "上午版" if is_morning else "晚间版(含变化)"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; max-width: 700px; margin: 0 auto; padding: 20px;">
<h2 style="color: #1a73e8;">📊 网页监控日报 — {tag}</h2>
<p style="color: #666;">抓取时间: {now} | 共监控 <strong>{len(results)}</strong> 个网址</p>
<hr style="border: 0; border-top: 2px solid #eee;">
"""

    for i, r in enumerate(results):
        # 网址名称和链接
        name = r.get("url_name") or r.get("url", "未命名")
        url = r.get("url", "")
        category = r.get("category", "未分类")
        summary = r.get("summary", "无摘要")
        keywords = r.get("keywords", [])
        changes = r.get("changes", [])

        # 关键词标签
        kw_tags = " ".join(
            f'<span style="background:#e8f0fe;color:#1a73e8;padding:2px 8px;border-radius:12px;font-size:12px;margin:0 2px;">#{kw}</span>'
            for kw in keywords
        )

        # 变化标签（仅晚上）
        change_html = ""
        if not is_morning and changes:
            change_items = "".join(
                f'<li>{c["type"]} {c["description"]}</li>'
                for c in changes
            )
            change_html = f"""
<div style="margin-top:8px;padding:8px 12px;background:#fff8e1;border-left:3px solid #f9ab00;font-size:13px;">
  <strong>📌 变化:</strong><ul style="margin:4px 0;padding-left:20px;">{change_items}</ul>
</div>"""

        html += f"""
<div style="border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin-bottom:14px;">
  <div style="font-weight:bold;font-size:15px;margin-bottom:4px;">
    <span style="color:#333;">{i+1}. {name}</span>
    <span style="font-size:11px;color:#999;font-weight:normal;margin-left:4px;">[{category}]</span>
  </div>
  <div style="font-size:12px;color:#999;margin-bottom:8px;">
    <a href="{url}" style="color:#1a73e8;">{url}</a>
  </div>
  <div style="font-size:14px;color:#333;line-height:1.6;">{summary}</div>
  <div style="margin-top:8px;">{kw_tags}</div>
  {change_html}
</div>"""

    html += """
<hr style="border: 0; border-top: 1px solid #eee; margin-top: 20px;">
<p style="color: #999; font-size: 11px; text-align: center;">
  📬 由 Web Monitor 自动生成并发送
</p>
</body></html>"""

    return html


def send_email(results: list[dict], is_morning: bool = True) -> bool:
    """
    发送邮件
    results: 分析结果列表
    is_morning: True=上午版, False=晚间版
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        print("[mailer] 未配置 SMTP，跳过邮件发送")
        return False

    subject = EMAIL_SUBJECT_MORNING if is_morning else EMAIL_SUBJECT_EVENING

    # 构建邮件
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT_EMAIL

    html_body = build_html_body(results, is_morning)
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
