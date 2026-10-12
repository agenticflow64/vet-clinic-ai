"""SQLite-хранилище: услуги с эмбеддингами, заявки, история диалогов, кэш эмбеддингов.

Схема простая, миграций нет — при изменении схемы достаточно удалить data/*.db
и перезапустить ингест.
"""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

# FastAPI выполняет sync-эндпоинты в threadpool: одно соединение SQLite
# открываем с check_same_thread=False и защищаем записи локом.
_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    price INTEGER,
    source TEXT NOT NULL DEFAULT 'full',
    embedding TEXT
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    pet_name TEXT,
    pet_type TEXT NOT NULL,
    service TEXT,
    preferred_time TEXT,
    phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_cache (
    text_hash TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status);
"""

APPOINTMENT_STATUSES = ("new", "confirmed", "done", "cancelled")


def connect(db_path: Path | str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with _write_lock:
        conn.executescript(SCHEMA)
    return conn


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


# --- услуги -----------------------------------------------------------------


def replace_services(conn: sqlite3.Connection, services: list[dict]) -> None:
    with _write_lock:
        conn.execute("DELETE FROM services")
        conn.executemany(
            "INSERT INTO services (id, category, name, price, source, embedding) "
            "VALUES (:id, :category, :name, :price, :source, :embedding)",
            services,
        )
        conn.commit()


def get_services(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, category, name, price, source, embedding FROM services ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


# --- сообщения --------------------------------------------------------------


def add_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    intent: str | None = None,
) -> None:
    with _write_lock:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, intent, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, intent, time.time()),
        )
        conn.commit()


def get_history(conn: sqlite3.Connection, session_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content, intent FROM messages WHERE session_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "intent": r["intent"]}
        for r in reversed(rows)
    ]


def has_pending_booking(conn: sqlite3.Connection, session_id: str) -> bool:
    """Сессия в состоянии записи: был интент booking и заявка ещё не создана."""
    started = conn.execute(
        "SELECT 1 FROM messages WHERE session_id = ? AND intent = 'booking' LIMIT 1",
        (session_id,),
    ).fetchone()
    if not started:
        return False
    created = conn.execute(
        "SELECT 1 FROM appointments WHERE session_id = ? LIMIT 1", (session_id,)
    ).fetchone()
    return created is None


# --- заявки -----------------------------------------------------------------


def create_appointment(conn: sqlite3.Connection, data: dict) -> int:
    with _write_lock:
        cur = conn.execute(
            "INSERT INTO appointments "
            "(session_id, pet_name, pet_type, service, preferred_time, phone, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                data["session_id"],
                data.get("pet_name"),
                data["pet_type"],
                data.get("service"),
                data.get("preferred_time"),
                data["phone"],
                time.time(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def list_appointments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM appointments ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def update_appointment_status(
    conn: sqlite3.Connection, appointment_id: int, status: str
) -> bool:
    if status not in APPOINTMENT_STATUSES:
        return False
    with _write_lock:
        cur = conn.execute(
            "UPDATE appointments SET status = ? WHERE id = ?", (status, appointment_id)
        )
        conn.commit()
        return cur.rowcount > 0


# --- кэш эмбеддингов ---------------------------------------------------------


def cache_get(conn: sqlite3.Connection, text_hash: str, model: str) -> list[float] | None:
    row = conn.execute(
        "SELECT vector FROM embedding_cache WHERE text_hash = ? AND model = ?",
        (text_hash, model),
    ).fetchone()
    return json.loads(row["vector"]) if row else None


def cache_put(
    conn: sqlite3.Connection, text_hash: str, model: str, vector: list[float]
) -> None:
    with _write_lock:
        conn.execute(
            "INSERT OR REPLACE INTO embedding_cache (text_hash, model, dim, vector) "
            "VALUES (?, ?, ?, ?)",
            (text_hash, model, len(vector), json.dumps(vector)),
        )
        conn.commit()
