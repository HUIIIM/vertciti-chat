# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Rate limiting (capability-map E6: the survival line for a free public
chatbot).

- Per-minute token buckets, two per request: one for the principal and one for
  the client IP, so minting many visitor tokens from one address does not
  multiply the allowance.
- An hourly bucket per IP for minting visitor tokens.
- Daily message quotas, consumed atomically in the database (check and
  increment in one transaction): per visitor plus a per-IP ceiling for
  anonymous traffic; one shared quota per service key.

Buckets are in-process: they reset on restart and are per worker. Running more
than one worker needs a shared store first (docs/ARCHITECTURE.md). Quotas live
in SQLite and survive restarts. The quota day is the UTC calendar day.

429 responses carry `retry-after` per the platform contract.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta

from . import db as _db
from .auth import Principal
from .config import get_settings
from .errors import QuotaExceeded, RateLimited


def _seconds_to_utc_midnight() -> int:
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}  # id -> (tokens, last_refill)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def _take(self, items: list[tuple[str, int, float]]) -> tuple[bool, int]:
        """Take one token from every bucket, or from none. items: (id, capacity, period_s)."""
        now = time.monotonic()
        with self._lock:
            state = []
            for bucket_id, capacity, period in items:
                tokens, last = self._buckets.get(bucket_id, (float(capacity), now))
                tokens = min(float(capacity), tokens + (now - last) * (capacity / period))
                state.append((bucket_id, capacity, period, tokens))
            short = [s for s in state if s[3] < 1.0]
            if short:
                retry = max(
                    int(period / capacity * (1.0 - tokens)) + 1 for _, capacity, period, tokens in short
                )
                for bucket_id, _c, _p, tokens in state:
                    self._buckets[bucket_id] = (tokens, now)
                return False, max(1, retry)
            for bucket_id, _c, _p, tokens in state:
                self._buckets[bucket_id] = (tokens - 1.0, now)
            return True, 0

    def check_request(self, principal: Principal) -> tuple[bool, int]:
        settings = get_settings()
        return self._take([
            (f"s:{principal.subject}", settings.rate_per_minute, 60.0),
            (f"ip:{principal.ip_hash}", settings.ip_rate_per_minute, 60.0),
        ])

    def check_mint(self, ip_hash: str) -> tuple[bool, int]:
        settings = get_settings()
        return self._take([(f"mint:{ip_hash}", settings.visitor_mint_per_hour, 3600.0)])

    def enforce(self, principal: Principal) -> None:
        ok, retry = self.check_request(principal)
        if not ok:
            raise RateLimited("rate limit exceeded", retry_after=retry)
        self.count_request(principal)

    # -- daily quotas (database) ----------------------------------------------
    @staticmethod
    def _limits(principal: Principal) -> list[tuple[str, int]]:
        settings = get_settings()
        if principal.kind == "visitor":
            return [
                (principal.subject, settings.visitor_daily_message_limit),
                (f"ip:{principal.ip_hash}", settings.ip_daily_message_limit),
            ]
        return [(principal.subject, settings.daily_message_limit)]

    def consume_message(self, principal: Principal) -> int:
        """Atomically check and count one message. Returns the principal's
        remaining messages today; raises QuotaExceeded without counting."""
        day = _db.utcday()
        limits = self._limits(principal)

        def txn(conn: sqlite3.Connection) -> int:
            used = {}
            for key, _limit in limits:
                row = conn.execute(
                    "SELECT messages FROM usage_daily WHERE key_hash=? AND day=?", (key, day)
                ).fetchone()
                used[key] = row["messages"] if row else 0
            for key, limit in limits:
                if used[key] >= limit:
                    raise QuotaExceeded(
                        "daily message quota exceeded", retry_after=_seconds_to_utc_midnight()
                    )
            for key, _limit in limits:
                conn.execute(
                    """INSERT INTO usage_daily(key_hash, day, requests, messages)
                       VALUES(?,?,0,1)
                       ON CONFLICT(key_hash, day) DO UPDATE SET messages=messages+1""",
                    (key, day),
                )
            first_key, first_limit = limits[0]
            return first_limit - used[first_key] - 1

        return _db.get_store().atomic(txn)

    def usage(self, principal: Principal) -> dict:
        day = _db.utcday()
        key, limit = self._limits(principal)[0]
        row = _db.get_store().fetchone(
            "SELECT messages FROM usage_daily WHERE key_hash=? AND day=?", (key, day)
        )
        used = row["messages"] if row else 0
        return {"day": day, "used": used, "limit": limit, "remaining": max(0, limit - used)}

    def count_request(self, principal: Principal) -> None:
        _db.get_store().execute(
            """INSERT INTO usage_daily(key_hash, day, requests, messages)
               VALUES(?,?,1,0)
               ON CONFLICT(key_hash, day) DO UPDATE SET requests=requests+1""",
            (principal.subject, _db.utcday()),
        )


limiter = RateLimiter()
