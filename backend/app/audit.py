# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Append-only audit log. Kill events and cross-module access violations are
always recorded here (contract v1 §2.4 / §5). Never write secrets or raw PII
into audit details — callers pass sanitized summaries only."""

from __future__ import annotations

from . import db as _db


def record(action: str, actor: str, detail: dict | None = None) -> None:
    _db.get_store().execute(
        "INSERT INTO audit_log(ts, actor, action, detail_json) VALUES(?,?,?,?)",
        (_db.utcnow(), actor, action, _db.dumps(detail or {})),
    )


def recent(limit: int = 50) -> list[dict]:
    rows = _db.get_store().fetchall(
        "SELECT ts, actor, action, detail_json FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [
        {"ts": r["ts"], "actor": r["actor"], "action": r["action"], "detail": r["detail_json"]}
        for r in rows
    ]
