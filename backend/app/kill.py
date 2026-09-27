# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Kill switch, contract v1 §2.4 shape. Two levels:

- scope=module: local one-stop for the chat module itself — IMPLEMENTED. While
  engaged, all chat/LLM endpoints answer 503 `chat_killed`.
- scope=platform: platform-wide kill. The platform base (P) is not built yet,
  so this records the signal + audit trail and answers honestly that no
  platform hook is connected (🟡). It is a reservation, not a claim.

Every kill/unkill is written to the tamper-evident audit log.
Manual verification: scripts/kill-drill.sh
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import audit, db as _db
from .auth import require_api_key
from .config import get_settings
from .errors import RateLimited
from .models import KillRequest, UnkillRequest
from .rate_limit import limiter

router = APIRouter(prefix="/v1/risk", tags=["risk"])


def _set(scope: str, killed: bool, reason_code: str | None, actor: str) -> None:
    _db.get_store().execute(
        """INSERT INTO kill_state(scope, killed, reason_code, actor, updated_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(scope) DO UPDATE SET killed=excluded.killed,
             reason_code=excluded.reason_code, actor=excluded.actor,
             updated_at=excluded.updated_at""",
        (scope, int(killed), reason_code, actor, _db.utcnow()),
    )


def _get(scope: str) -> dict:
    row = _db.get_store().fetchone(
        "SELECT killed, reason_code, actor, updated_at FROM kill_state WHERE scope=?", (scope,))
    if not row:
        return {"killed": False, "reason_code": None, "actor": None, "updated_at": None}
    return {"killed": bool(row["killed"]), "reason_code": row["reason_code"],
            "actor": row["actor"], "updated_at": row["updated_at"]}


@router.post("/kill")
def kill(body: KillRequest, identity: dict = Depends(require_api_key)):
    ok, retry = limiter.check_request(identity)
    if not ok:
        raise RateLimited("rate limit exceeded", retry_after=retry)
    limiter.count_request(identity)
    _set(body.scope, True, body.reason_code, body.actor)
    audit.record("risk.kill", body.actor, {"scope": body.scope, "reason_code": body.reason_code})
    if body.scope == "platform":
        # Reservation hook: no platform base exists yet; be honest about it.
        return {
            "scope": "platform",
            "killed": True,
            "platform_hook_connected": False,
            "note": "platform kill recorded; no platform base (P) connected yet — local chat module kill is the enforced one",
            "honesty": "🟡",
        }
    return {"scope": "module", "killed": True, "honesty": get_settings().honesty}


@router.post("/unkill")
def unkill(body: UnkillRequest, identity: dict = Depends(require_api_key)):
    ok, retry = limiter.check_request(identity)
    if not ok:
        raise RateLimited("rate limit exceeded", retry_after=retry)
    limiter.count_request(identity)
    _set(body.scope, False, None, body.actor)
    audit.record("risk.unkill", body.actor, {"scope": body.scope})
    return {"scope": body.scope, "killed": False, "honesty": get_settings().honesty}


@router.get("/status")
def status(identity: dict = Depends(require_api_key)):
    return {
        "module": _get("module"),
        "platform": {**_get("platform"), "platform_hook_connected": False},
        "honesty": "🟡",  # platform level is a reservation until P exists
    }


@router.get("/audit")
def kill_audit(limit: int = 50, identity: dict = Depends(require_api_key)):
    rows = _db.get_store().fetchall(
        "SELECT ts, actor, action, detail_json FROM audit_log "
        "WHERE action IN ('risk.kill','risk.unkill') ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return {"events": [dict(r) for r in rows], "honesty": get_settings().honesty}
