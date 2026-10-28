# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Data retention and restart reconciliation (docs/PRIVACY.md).

- Conversations (sessions, messages, their events) older than
  CHAT_RETENTION_DAYS are deleted. The page tells users this number.
- Idempotency records are kept for one day; usage counters for 35 days.
- The audit log is append-only and holds no conversation content; it is not
  purged here.
- At startup, assistant replies left `streaming` by a previous process are
  marked `interrupted`, and `pending` ones older than one day are expired.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta

from . import db as _db
from .config import get_settings

_last_purge = 0.0
_lock = threading.Lock()
PURGE_INTERVAL_SECONDS = 3600


def _cutoff(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def purge() -> dict[str, int]:
    days = get_settings().retention_days
    cutoff = _cutoff(days)

    def txn(conn: sqlite3.Connection) -> dict[str, int]:
        old = [r["id"] for r in conn.execute(
            "SELECT id FROM sessions WHERE created_at < ?", (cutoff,)).fetchall()]
        msgs = 0
        for sid in old:
            msgs += conn.execute("DELETE FROM messages WHERE session_id=?", (sid,)).rowcount
            conn.execute("DELETE FROM events WHERE session_id=?", (sid,))
            conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
        events = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,)).rowcount
        idem = conn.execute("DELETE FROM idempotency WHERE created_at < ?", (_cutoff(1),)).rowcount
        usage = conn.execute(
            "DELETE FROM usage_daily WHERE day < ?", (_cutoff(35)[:10],)).rowcount
        conn.execute("DELETE FROM risk_challenges WHERE expires_at < ?", (_cutoff(1),))
        return {"sessions": len(old), "messages": msgs, "events": events,
                "idempotency": idem, "usage_rows": usage}

    return _db.get_store().atomic(txn)


def maybe_purge() -> None:
    """Cheap hook for hot paths: purge at most once per hour per process."""
    global _last_purge
    now = time.monotonic()
    with _lock:
        if now - _last_purge < PURGE_INTERVAL_SECONDS and _last_purge:
            return
        _last_purge = now
    purge()


def reconcile_after_restart() -> dict[str, int]:
    def txn(conn: sqlite3.Connection) -> dict[str, int]:
        streaming = conn.execute(
            "UPDATE messages SET status='interrupted' WHERE status='streaming'").rowcount
        stale = conn.execute(
            "UPDATE messages SET status='interrupted' WHERE status='pending' AND created_at < ?",
            (_cutoff(1),),
        ).rowcount
        return {"interrupted": streaming, "expired_pending": stale}

    return _db.get_store().atomic(txn)


def reset() -> None:
    """Test hook."""
    global _last_purge
    _last_purge = 0.0
