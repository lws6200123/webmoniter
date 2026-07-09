"""
配置管理：读取 .env 环境变量和默认配置
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
BASE_DIR = Path(__file__).parent

# 加载 .env 文件
load_dotenv(BASE_DIR / ".env")

# --- Claude API ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- QQ邮箱 SMTP ---
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")

# --- PushPlus 推送（GitHub Actions 环境的备用渠道）---
# 免费注册: http://www.pushplus.plus/ → 获取 Token → 推送到微信
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")

# SMTP 服务器配置
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465  # SSL

# --- 数据库 ---
DB_PATH = BASE_DIR / "data" / "urls.db"

# --- 快照目录 ---
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"

# --- 抓取配置 ---
REQUEST_TIMEOUT = 30  # HTTP 请求超时(秒)
MAX_CONTENT_LENGTH = 8000  # 送入 LLM 的最大字符数（控制成本）
PLAYWRIGHT_TIMEOUT = 60000  # Playwright 页面加载超时(毫秒)

# --- 邮件标题 ---
EMAIL_SUBJECT_MORNING = "📊 网页监控日报 - 上午版"
EMAIL_SUBJECT_EVENING = "📊 网页监控日报 - 晚间版(含变化)"
