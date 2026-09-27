# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Per-key / per-IP rate limiting (capability-map E6: the survival line for a
free public chatbot). Token-bucket per minute + daily per-key message quota.

429 responses carry `retry-after` per the platform contract.
"""

from __future__ import annotations

import threading
import time
from datetime import date

from . import db as _db
from .auth import key_hash
from .config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}  # id -> (tokens, last_refill)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def check_request(self, identity: dict) -> tuple[bool, int]:
        """Minute-bucket for all requests. Returns (allowed, retry_after_seconds)."""
        settings = get_settings()
        capacity = settings.rate_per_minute
        key = f"{identity['key_hash']}:{identity['ip']}"
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(capacity), now))
            tokens = min(float(capacity), tokens + (now - last) * (capacity / 60.0))
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True, 0
            retry = max(1, int(60.0 / capacity * (1.0 - tokens)) + 1)
            self._buckets[key] = (tokens, now)
            return False, retry

    def check_message_quota(self, identity: dict) -> tuple[bool, int]:
        """Daily per-key message quota."""
        settings = get_settings()
        day = date.today().isoformat()
        store = _db.get_store()
        row = store.fetchone(
            "SELECT messages FROM usage_daily WHERE key_hash=? AND day=?",
            (identity["key_hash"], day),
        )
        used = row["messages"] if row else 0
        if used >= settings.daily_message_limit:
            return False, 0
        return True, settings.daily_message_limit - used - 1

    def count_request(self, identity: dict) -> None:
        day = date.today().isoformat()
        _db.get_store().execute(
            """INSERT INTO usage_daily(key_hash, day, requests, messages)
               VALUES(?,?,1,0)
               ON CONFLICT(key_hash, day) DO UPDATE SET requests=requests+1""",
            (identity["key_hash"], day),
        )

    def count_message(self, identity: dict) -> None:
        day = date.today().isoformat()
        _db.get_store().execute(
            """INSERT INTO usage_daily(key_hash, day, requests, messages)
               VALUES(?,?,0,1)
               ON CONFLICT(key_hash, day) DO UPDATE SET messages=messages+1""",
            (identity["key_hash"], day),
        )


limiter = RateLimiter()
