# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Memory service, contract v1 §2.2 shape (delegating storage interface).

`MemoryStore` is the delegation seam:
- dev today: `SqliteMemoryStore` (keyword recall — honestly 🟡, semantic search
  is NOT claimed).
- production later: a `PgVectorMemoryStore` implementing this same ABC, owned
  by the future platform base (P). This module must not hard-couple to pgvector.

Isolation (contract §4, enforced server-side):
- `module_id` is a first-class row key. This service is bound to module "chat".
- Any request attempting another module id → 403 + audit (cross-module recall
  is forbidden by contract §2.2).

Privacy (D68): fields marked pii are redacted before storage. Two marker forms
are accepted in the store payload:
  1. a top-level `pii_fields: ["email", ...]` list in the request body, or
  2. nested marker dicts {"pii": true, "value": ...} anywhere in the payload.
TTL: `ttl_days`; expired rows are purged on recall.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from . import db as _db
from .errors import Forbidden


def _now():
    return datetime.now(timezone.utc)


def redact_pii(payload: dict, pii_fields: list[str] | None = None) -> tuple[dict, bool]:
    """Return (redacted_payload, had_pii). Original values are dropped."""
    pii_fields = set(pii_fields or [])
    had = False

    def walk(node, path=()):
        nonlocal had
        if isinstance(node, dict):
            if node.get("pii") is True and "value" in node:
                had = True
                return "[REDACTED]"
            return {k: walk(v, path + (k,)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, path) for v in node]
        return node

    redacted = walk(payload)
    if isinstance(redacted, dict):
        for f in pii_fields:
            if f in redacted:
                redacted[f] = "[REDACTED]"
                had = True
    return redacted, had


class MemoryStore(ABC):
    """Delegating storage interface. Backend-agnostic; module isolation is
    enforced by callers passing the server-bound module_id."""

    @abstractmethod
    def store(self, *, module_id: str, namespace: str, key: str, payload: dict,
              pii_redacted: bool, ttl_days: int | None) -> dict: ...

    @abstractmethod
    def recall(self, *, module_id: str, namespace: str, query: str,
               top_k: int, min_score: float) -> list[dict]: ...

    @abstractmethod
    def forget(self, *, module_id: str, namespace: str, key: str) -> bool: ...

    @abstractmethod
    def purge_expired(self) -> int: ...


class SqliteMemoryStore(MemoryStore):
    """Dev implementation. Recall is keyword/prefix matching over
    namespace+key — semantic vector search is explicitly NOT claimed (🟡)."""

    def store(self, *, module_id, namespace, key, payload, pii_redacted, ttl_days) -> dict:
        expires_at = None
        if ttl_days:
            expires_at = (_now() + timedelta(days=ttl_days)).isoformat()
        _db.get_store().execute(
            """INSERT INTO memory_records(module_id, namespace, key, payload_json,
                                          pii_redacted, expires_at, created_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(module_id, namespace, key)
               DO UPDATE SET payload_json=excluded.payload_json,
                             pii_redacted=excluded.pii_redacted,
                             expires_at=excluded.expires_at""",
            (module_id, namespace, key, _db.dumps(payload), int(pii_redacted),
             expires_at, _db.utcnow()),
        )
        return {"stored": True, "expires_at": expires_at}

    def recall(self, *, module_id, namespace, query, top_k, min_score) -> list[dict]:
        self.purge_expired()
        rows = _db.get_store().fetchall(
            """SELECT namespace, key, payload_json, pii_redacted, expires_at
               FROM memory_records
               WHERE module_id=? AND namespace LIKE ? AND (expires_at IS NULL OR expires_at > ?)
               ORDER BY created_at DESC LIMIT ?""",
            (module_id, f"{namespace}%", _now().isoformat(), max(top_k * 5, top_k)),
        )
        q = (query or "").lower()
        scored = []
        for r in rows:
            hay = f"{r['namespace']} {r['key']} {r['payload_json']}".lower()
            score = 1.0 if q and q in hay else (0.5 if not q else 0.0)
            if score >= min_score and score > 0:
                scored.append(
                    {
                        "namespace": r["namespace"],
                        "key": r["key"],
                        "payload": r["payload_json"],
                        "pii_redacted": bool(r["pii_redacted"]),
                        "score": score,
                    }
                )
        return scored[:top_k]

    def forget(self, *, module_id, namespace, key) -> bool:
        cur = _db.get_store().execute(
            "DELETE FROM memory_records WHERE module_id=? AND namespace=? AND key=?",
            (module_id, namespace, key),
        )
        return cur.rowcount > 0

    def purge_expired(self) -> int:
        cur = _db.get_store().execute(
            "DELETE FROM memory_records WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (_now().isoformat(),),
        )
        return cur.rowcount


# NOTE (delegation seam): a future PgVectorMemoryStore implementing MemoryStore
# will be provided by the platform base (P). Selection would be via
# CHAT_MEMORY_BACKEND=pgvector; this module deliberately contains no pgvector
# import so the chat service never hard-couples to the vector backend.

_store_impl: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store_impl
    if _store_impl is None:
        import os

        if os.environ.get("CHAT_MEMORY_BACKEND") == "pgvector":
            from .errors import ServiceUnavailable

            raise ServiceUnavailable(
                "pgvector memory backend is not built yet (platform base P); sqlite dev store only"
            )
        _store_impl = SqliteMemoryStore()
    return _store_impl


MODULE_ID = "chat"


def enforce_module(requested: str | None, actor: str) -> None:
    """Server-side module binding. Cross-module attempts → 403 + audit."""
    if requested and requested != MODULE_ID:
        from . import audit

        audit.record("memory.cross_module_denied", actor, {"requested": requested})
        raise Forbidden(f"cross-module memory access denied (bound to '{MODULE_ID}')")
