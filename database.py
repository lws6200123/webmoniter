"""
SQLite 数据库操作：网址管理 + 快照存储
"""
import sqlite3
import json
from datetime import datetime
from config import DB_PATH


def get_conn():
    """获取数据库连接"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """创建表（如果不存在）"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            name TEXT,
            category TEXT,
            use_dynamic INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_id INTEGER REFERENCES urls(id),
            content TEXT,
            summary TEXT,
            keywords TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_morning INTEGER DEFAULT 1
        );
    """)
    conn.commit()
    conn.close()


# ============ URL 管理 ============

def add_url(url: str, name: str = "", category: str = "", use_dynamic: bool = False) -> int:
    """添加网址，返回 id"""
    conn = get_conn()
    try:
        cursor = conn.execute(
            "INSERT INTO urls (url, name, category, use_dynamic) VALUES (?, ?, ?, ?)",
            (url, name, category, 1 if use_dynamic else 0)
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"网址已存在: {url}")
    finally:
        conn.close()


def delete_url(identifier) -> bool:
    """删除网址，按 id(int) 或 url(str)"""
    conn = get_conn()
    if isinstance(identifier, int):
        cursor = conn.execute("DELETE FROM urls WHERE id = ?", (identifier,))
    else:
        cursor = conn.execute("DELETE FROM urls WHERE url = ?", (identifier,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def list_urls(active_only: bool = True) -> list[dict]:
    """列出所有网址"""
    conn = get_conn()
    if active_only:
        rows = conn.execute(
            "SELECT * FROM urls WHERE active = 1 ORDER BY created_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM urls ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_urls() -> list[dict]:
    """获取所有活跃的网址"""
    return list_urls(active_only=True)


# ============ 快照管理 ============

def save_snapshot(url_id: int, content: str, summary: str, keywords: list[str], is_morning: bool = True) -> int:
    """保存快照"""
    conn = get_conn()
    cursor = conn.execute(
        "INSERT INTO snapshots (url_id, content, summary, keywords, is_morning) VALUES (?, ?, ?, ?, ?)",
        (url_id, content, summary, json.dumps(keywords, ensure_ascii=False), 1 if is_morning else 0)
    )
    conn.commit()
    sid = cursor.lastrowid
    conn.close()
    return sid


def get_latest_morning_snapshot(url_id: int) -> dict | None:
    """获取指定网址今天最新的上午快照"""
    conn = get_conn()
    row = conn.execute(
        """SELECT * FROM snapshots
           WHERE url_id = ? AND is_morning = 1
           ORDER BY created_at DESC LIMIT 1""",
        (url_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_today_morning_snapshots() -> list[dict]:
    """获取今天所有网址的上午快照"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM snapshots
           WHERE is_morning = 1 AND date(created_at) = date('now', 'localtime')
           ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
