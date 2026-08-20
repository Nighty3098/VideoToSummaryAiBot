import sqlite3
import threading
from datetime import datetime
from typing import Optional

from config import DB_PATH

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER UNIQUE NOT NULL,
            username    TEXT,
            first_name  TEXT,
            is_allowed  INTEGER DEFAULT 0,
            lang        TEXT,
            added_by    INTEGER,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            type            TEXT,
            duration_seconds REAL,
            status          TEXT,
            error_message   TEXT,
            file_size       INTEGER,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at    TIMESTAMP
        );
    """)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
    if "lang" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN lang TEXT")
    conn.commit()


def is_user_allowed(user_id: int) -> bool:
    cur = _get_conn().execute(
        "SELECT is_allowed FROM users WHERE user_id = ?", (user_id,)
    )
    row = cur.fetchone()
    return row is not None and row["is_allowed"] == 1


def get_user(user_id: int) -> Optional[dict]:
    cur = _get_conn().execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    )
    row = cur.fetchone()
    return dict(row) if row else None


def add_user(user_id: int, username: str, first_name: str, added_by: int):
    conn = _get_conn()
    conn.execute(
        """INSERT INTO users (user_id, username, first_name, is_allowed, added_by)
           VALUES (?, ?, ?, 1, ?)
           ON CONFLICT(user_id) DO UPDATE SET is_allowed=1, username=?, first_name=?""",
        (user_id, username, first_name, added_by, username, first_name),
    )
    conn.commit()


def remove_user(user_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute("UPDATE users SET is_allowed=0 WHERE user_id=?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def set_user_lang(user_id: int, lang: str):
    conn = _get_conn()
    conn.execute(
        """INSERT INTO users (user_id, lang, is_allowed) VALUES (?, ?, 0)
           ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang""",
        (user_id, lang),
    )
    conn.commit()


def upsert_user_profile(user_id: int, username: str = "", first_name: str = ""):
    """Save/refresh username and first_name without touching lang/is_allowed."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE
           SET username=excluded.username, first_name=excluded.first_name""",
        (user_id, username or "", first_name or ""),
    )
    conn.commit()


def get_user_lang(user_id: int) -> str | None:
    """Return the user's saved language, or None if not chosen yet."""
    cur = _get_conn().execute("SELECT lang FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    lang = row["lang"] if row else None
    return lang if lang in ("en", "ru") else None


def ensure_allowed(user_id: int):
    """Create (or re-enable) a user row without touching name/lang."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO users (user_id, is_allowed) VALUES (?, 1)
           ON CONFLICT(user_id) DO UPDATE SET is_allowed=1""",
        (user_id,),
    )
    conn.commit()


def get_allowed_users(page: int = 0, per_page: int = 10) -> list[dict]:
    offset = page * per_page
    cur = _get_conn().execute(
        "SELECT * FROM users WHERE is_allowed=1 ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    return [dict(r) for r in cur.fetchall()]


def get_allowed_users_count() -> int:
    cur = _get_conn().execute(
        "SELECT COUNT(*) as cnt FROM users WHERE is_allowed=1"
    )
    return cur.fetchone()["cnt"]


def log_request(
    user_id: int,
    req_type: str,
    status: str,
    duration_seconds: float = None,
    error_message: str = None,
    file_size: int = None,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO requests (user_id, type, duration_seconds, status, error_message, file_size)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, req_type, duration_seconds, status, error_message, file_size),
    )
    conn.commit()
    return cur.lastrowid


def update_request(request_id: int, **kwargs):
    allowed = {"status", "duration_seconds", "error_message", "completed_at"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(request_id)
    conn = _get_conn()
    conn.execute(f"UPDATE requests SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()


def reset_stats():
    conn = _get_conn()
    conn.execute("DELETE FROM requests")
    conn.commit()


def get_stats() -> dict:
    conn = _get_conn()
    total_users = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_allowed=1").fetchone()["c"]
    total_requests = conn.execute("SELECT COUNT(*) as c FROM requests").fetchone()["c"]
    today = datetime.now().strftime("%Y-%m-%d")
    today_requests = conn.execute(
        "SELECT COUNT(*) as c FROM requests WHERE date(created_at)=?", (today,)
    ).fetchone()["c"]
    completed = conn.execute(
        "SELECT COUNT(*) as c FROM requests WHERE status='completed'"
    ).fetchone()["c"]
    errors = conn.execute(
        "SELECT COUNT(*) as c FROM requests WHERE status='error'"
    ).fetchone()["c"]
    return {
        "total_users": total_users,
        "total_requests": total_requests,
        "today_requests": today_requests,
        "completed": completed,
        "errors": errors,
    }
