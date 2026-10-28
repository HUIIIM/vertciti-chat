# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""SQLite storage layer (dev / single node). Contract §4: `module_id` is a
first-class row-level isolation key across memory, audit and event data.

Schema changes are versioned: `schema_version` records every applied migration
and `MIGRATIONS` is append-only. Never edit an applied migration; add a new one.

Production path: pgvector lives in the future platform base (P). The delegating
`MemoryStore` interface is in `memory_store.py`; this module stays uncoupled
from any vector backend.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

# v1: the original dev schema (kept verbatim so existing databases upgrade).
SCHEMA_V1 = """
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

# v2: principals own sessions, assistant messages carry a lifecycle status,
# audit rows are hash-chained, events carry a severity, and dangerous risk
# actions are two-step (prepare -> confirm).
SCHEMA_V2 = """
ALTER TABLE sessions ADD COLUMN owner TEXT;
CREATE INDEX IF NOT EXISTS idx_sessions_owner ON sessions(owner, created_at);
ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'done';
ALTER TABLE audit_log ADD COLUMN prev_hash TEXT;
ALTER TABLE audit_log ADD COLUMN row_hash TEXT;
ALTER TABLE events ADD COLUMN severity TEXT NOT NULL DEFAULT 'ACTIVITY_LO';
ALTER TABLE events ADD COLUMN subject TEXT;
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE TABLE IF NOT EXISTS risk_challenges(
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    scope TEXT NOT NULL,
    reason_code TEXT,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
"""


def _migrate_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_V1)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_V2)
    # Existing audit rows predate the chain; seal them now so verify() covers
    # everything from this point on. (Rows written before v2 cannot prove they
    # were not edited before this migration ran; that is stated in the docs.)
    from .audit import backfill_chain

    backfill_chain(conn)


MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "base dev schema", _migrate_v1),
    (2, "owners, message status, audit chain, event severity, risk challenges", _migrate_v2),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def utcday() -> str:
    """The quota day is a UTC calendar day, like every other timestamp here."""
    return datetime.now(UTC).date().isoformat()


class Store:
    """Thread-safe SQLite store. One instance per process.

    Every statement runs under one process-wide lock, so read-modify-write
    sequences inside `atomic()` are serialised (quota, audit chain, challenges).
    """

    def __init__(self, path: str = "") -> None:
        if not path:
            here = Path(__file__).resolve().parent.parent
            path = str(here / "data" / "chat.db")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._local = threading.local()
        with self._lock:
            conn = self._conn()
            conn.execute("PRAGMA journal_mode=WAL")
            self._migrate(conn)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version("
            "version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        row = conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
        current = row["v"] or 0
        for version, description, apply in MIGRATIONS:
            if version <= current:
                continue
            apply(conn)
            conn.execute(
                "INSERT INTO schema_version(version, description, applied_at) VALUES(?,?,?)",
                (version, description, utcnow()),
            )
            conn.commit()

    # -- generic helpers -----------------------------------------------------
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            conn = self._conn()
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn().execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn().execute(sql, params).fetchall()

    def atomic(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run fn(conn) as one transaction under the store lock."""
        with self._lock:
            conn = self._conn()
            try:
                result = fn(conn)
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
            return result

    def schema_version(self) -> int:
        row = self.fetchone("SELECT MAX(version) v FROM schema_version")
        return int(row["v"] or 0) if row else 0

    def ping(self) -> None:
        """Raise if the database cannot serve a read. Used by /health."""
        self.fetchone("SELECT 1 FROM schema_version LIMIT 1")


_store: Store | None = None
_store_lock = threading.Lock()


def get_store(db_path: str = "") -> Store:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = Store(db_path or os.environ.get("CHAT_DB_PATH", ""))
    return _store


def reset_store() -> None:
    """Test hook."""
    global _store
    _store = None


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
