# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Append-only, hash-chained audit log (contract v1 §2.4 / §5).

Every row stores `prev_hash` (the previous row's hash, or 64 zeros for the
first row) and `row_hash = sha256(prev_hash | ts | actor | action | detail)`.
`verify()` recomputes the chain, so an UPDATE or DELETE of any row is detected
from that row onwards.

What this does NOT prove on its own: someone with write access to the database
file can rewrite the whole chain consistently. The defence is to anchor the
head hash outside this system every day (`scripts/audit-anchor.py`, see
docs/RUNBOOK.md); a rewritten chain then no longer matches the anchored head.

Never write secrets or raw PII into audit details: callers pass sanitized
summaries only.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from . import db as _db

GENESIS = "0" * 64


def _row_hash(prev_hash: str, ts: str, actor: str, action: str, detail_json: str) -> str:
    material = "\x1f".join((prev_hash, ts, actor, action, detail_json))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _head(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT row_hash FROM audit_log WHERE row_hash IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["row_hash"] if row else GENESIS


def record(action: str, actor: str, detail: dict[str, Any] | None = None) -> str:
    """Append one audit row and return its hash."""
    detail_json = _db.dumps(detail or {})

    def write(conn: sqlite3.Connection) -> str:
        ts = _db.utcnow()
        prev = _head(conn)
        row_hash = _row_hash(prev, ts, actor, action, detail_json)
        conn.execute(
            "INSERT INTO audit_log(ts, actor, action, detail_json, prev_hash, row_hash) "
            "VALUES(?,?,?,?,?,?)",
            (ts, actor, action, detail_json, prev, row_hash),
        )
        return row_hash

    return _db.get_store().atomic(write)


def backfill_chain(conn: sqlite3.Connection) -> int:
    """Seal rows written before the chain existed (migration v2)."""
    prev = GENESIS
    n = 0
    for r in conn.execute(
        "SELECT id, ts, actor, action, detail_json FROM audit_log ORDER BY id"
    ).fetchall():
        h = _row_hash(prev, r["ts"], r["actor"], r["action"], r["detail_json"])
        conn.execute("UPDATE audit_log SET prev_hash=?, row_hash=? WHERE id=?", (prev, h, r["id"]))
        prev = h
        n += 1
    return n


def verify() -> dict[str, Any]:
    """Recompute the chain. Returns {ok, count, head, first_bad_id}."""
    rows = _db.get_store().fetchall(
        "SELECT id, ts, actor, action, detail_json, prev_hash, row_hash FROM audit_log ORDER BY id"
    )
    prev = GENESIS
    for r in rows:
        expected = _row_hash(prev, r["ts"], r["actor"], r["action"], r["detail_json"])
        if r["prev_hash"] != prev or r["row_hash"] != expected:
            return {"ok": False, "count": len(rows), "head": None, "first_bad_id": r["id"]}
        prev = expected
    return {"ok": True, "count": len(rows), "head": prev, "first_bad_id": None}


def recent(limit: int = 50, actions: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    if actions:
        marks = ",".join("?" for _ in actions)
        rows = _db.get_store().fetchall(
            f"SELECT id, ts, actor, action, detail_json, row_hash FROM audit_log "  # noqa: S608
            f"WHERE action IN ({marks}) ORDER BY id DESC LIMIT ?",
            (*actions, limit),
        )
    else:
        rows = _db.get_store().fetchall(
            "SELECT id, ts, actor, action, detail_json, row_hash FROM audit_log "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    return [
        {
            "id": r["id"],
            "ts": r["ts"],
            "actor": r["actor"],
            "action": r["action"],
            "detail": r["detail_json"],
            "row_hash": r["row_hash"],
        }
        for r in rows
    ]
