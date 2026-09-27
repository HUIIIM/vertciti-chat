# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""SQLite storage layer (dev). Contract §4: `module_id` is a first-class row-level
isolation key across memory, audit and event data.

Production path: pgvector lives in the future platform base (P). The delegating
`MemoryStore` interface is in `memory_store.py`; this module stays uncoupled
from any vector backend.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    run_id TEXT,
    cards_json TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_cents INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE TABLE IF NOT EXISTS memory_records(
    module_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    pii_redacted INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(module_id, namespace, key)
);
CREATE TABLE IF NOT EXISTS idempotency(
    key TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    session_id TEXT,
    detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kill_state(
    scope TEXT PRIMARY KEY,
    killed INTEGER NOT NULL DEFAULT 0,
    reason_code TEXT,
    actor TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_daily(
    key_hash TEXT NOT NULL,
    day TEXT NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0,
    messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(key_hash, day)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Thread-safe SQLite store. One instance per process."""

    def __init__(self, path: str = "") -> None:
        if not path:
            here = Path(__file__).resolve().parent.parent
            path = str(here / "data" / "chat.db")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    # -- generic helpers -----------------------------------------------------
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn().execute(sql, params)
            self._conn().commit()
            return cur

    def fetchone(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn().execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn().execute(sql, params).fetchall()


_store: Store | None = None


def get_store(db_path: str = "") -> Store:
    global _store
    if _store is None:
        _store = Store(db_path or os.environ.get("CHAT_DB_PATH", ""))
    return _store


def reset_store() -> None:
    """Test hook."""
    global _store
    _store = None


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
