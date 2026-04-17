import sqlite3
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from .config import DB_PATH


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                phone TEXT NOT NULL,
                task TEXT NOT NULL,
                language TEXT DEFAULT auto,
                caller_name TEXT,
                required_info TEXT,
                restrictions TEXT,
                status TEXT DEFAULT 'pending',
                transcript TEXT,
                report TEXT,
                duration_seconds INTEGER,
                created_at TEXT,
                completed_at TEXT
            )
        """)


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_call(data: dict) -> dict:
    call_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO calls (id, phone, task, language, caller_name,
               required_info, restrictions, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (call_id, data["phone"], data["task"], data.get("language", "auto"),
             data.get("caller_name"), data.get("required_info"),
             data.get("restrictions"), now)
        )
    return get_call(call_id)


def get_call(call_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if row:
            return dict(row)
    return None


def update_call(call_id: str, updates: dict):
    sets = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [call_id]
    with get_db() as conn:
        conn.execute(f"UPDATE calls SET {sets} WHERE id = ?", vals)


def list_calls(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM calls ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
