# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Kill switch, contract v1 §2.4 shape, two levels:

- scope=module: local one-stop for the chat module itself — IMPLEMENTED. While
  engaged, every endpoint that starts or feeds model work answers 503
  `chat_killed`: visitor minting, session creation, messages, streams, the LLM
  route, memory store/recall and client events. Reading or deleting your own
  data, health, and the risk endpoints keep working.
- scope=platform: platform-wide kill. The platform base (P) is not built yet,
  so this records the signal + audit trail and answers honestly that no
  platform hook is connected (🟡). It is a reservation, not a claim.

Engaging and clearing the switch are each two independent operator actions
(NPR 7150.2D SWE-134(d), mapped by analogy): `POST /v1/risk/kill` or
`/v1/risk/unkill` only *prepares* a challenge; `POST /v1/risk/confirm` with the
challenge id and the exact confirmation phrase executes it within 120 s. Only
the admin credential (CHAT_ADMIN_KEY) can do either.

Every prepare, confirm and refusal is written to the hash-chained audit log.
Manual verification: scripts/kill-drill.sh
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter

from . import audit
from . import db as _db
from .auth import AdminPrincipal
from .config import get_settings
from .errors import BadRequest, ChatKilled, Conflict, NotFound
from .models import ConfirmRequest, KillRequest, UnkillRequest
from .rate_limit import limiter

router = APIRouter(prefix="/v1/risk", tags=["risk"])

CHALLENGE_TTL_SECONDS = 120


def confirm_phrase(action: str, scope: str) -> str:
    return f"{action} {scope}"


def _set(scope: str, killed: bool, reason_code: str | None, actor: str) -> None:
    _db.get_store().execute(
        """INSERT INTO kill_state(scope, killed, reason_code, actor, updated_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(scope) DO UPDATE SET killed=excluded.killed,
             reason_code=excluded.reason_code, actor=excluded.actor,
             updated_at=excluded.updated_at""",
        (scope, int(killed), reason_code, actor, _db.utcnow()),
    )


def _get(scope: str) -> dict[str, Any]:
    row = _db.get_store().fetchone(
        "SELECT killed, reason_code, actor, updated_at FROM kill_state WHERE scope=?", (scope,))
    if not row:
        return {"killed": False, "reason_code": None, "actor": None, "updated_at": None}
    return {"killed": bool(row["killed"]), "reason_code": row["reason_code"],
            "actor": row["actor"], "updated_at": row["updated_at"]}


def is_killed() -> bool:
    row = _db.get_store().fetchone("SELECT killed FROM kill_state WHERE scope='module'")
    return bool(row and row["killed"])


def check_not_killed() -> None:
    if is_killed():
        raise ChatKilled("chat module is stopped (kill switch engaged)")


def _prepare(action: str, scope: str, reason_code: str | None, actor: str, who: str) -> dict:
    challenge_id = secrets.token_hex(12)
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    _db.get_store().execute(
        "INSERT INTO risk_challenges(id, action, scope, reason_code, actor, created_at, expires_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (challenge_id, action, scope, reason_code, actor, now.isoformat(), expires.isoformat()),
    )
    audit.record(f"risk.{action}.prepared", actor,
                 {"scope": scope, "reason_code": reason_code, "by": who, "challenge": challenge_id})
    return {
        "pending": True,
        "action": action,
        "scope": scope,
        "challenge_id": challenge_id,
        "confirm_phrase": confirm_phrase(action, scope),
        "expires_at": expires.isoformat(),
        "next": "POST /v1/risk/confirm {challenge_id, confirm_phrase}",
        "honesty": get_settings().honesty,
    }


@router.post("/kill", status_code=202)
def kill(body: KillRequest, admin: AdminPrincipal) -> dict:
    limiter.enforce(admin)
    return _prepare("kill", body.scope, body.reason_code, body.actor, admin.subject)


@router.post("/unkill", status_code=202)
def unkill(body: UnkillRequest, admin: AdminPrincipal) -> dict:
    limiter.enforce(admin)
    return _prepare("unkill", body.scope, body.reason_code, body.actor, admin.subject)


@router.post("/confirm")
def confirm(body: ConfirmRequest, admin: AdminPrincipal) -> dict:
    limiter.enforce(admin)
    now = datetime.now(UTC).isoformat()

    def claim(conn: Any) -> Any:
        row = conn.execute("SELECT * FROM risk_challenges WHERE id=?", (body.challenge_id,)).fetchone()
        if not row:
            raise NotFound("unknown challenge")
        if row["used"]:
            raise Conflict("challenge already used")
        if row["expires_at"] < now:
            raise Conflict("challenge expired; prepare again")
        if body.confirm_phrase != confirm_phrase(row["action"], row["scope"]):
            expected = confirm_phrase(row["action"], row["scope"])
            raise BadRequest(f"confirm_phrase must be exactly '{expected}'")
        conn.execute("UPDATE risk_challenges SET used=1 WHERE id=?", (body.challenge_id,))
        return dict(row)

    try:
        ch = _db.get_store().atomic(claim)
    except (NotFound, Conflict, BadRequest) as e:
        audit.record("risk.confirm.refused", admin.subject,
                     {"challenge": body.challenge_id, "code": e.code})
        raise

    killed = ch["action"] == "kill"
    _set(ch["scope"], killed, ch["reason_code"], ch["actor"])
    audit.record(f"risk.{ch['action']}", ch["actor"],
                 {"scope": ch["scope"], "reason_code": ch["reason_code"], "by": admin.subject,
                  "challenge": ch["id"]})
    if ch["scope"] == "platform":
        return {
            "scope": "platform",
            "killed": killed,
            "platform_hook_connected": False,
            "note": "platform signal recorded; no platform base (P) connected yet — "
                    "the local chat module kill is the enforced one",
            "honesty": "🟡",
        }
    return {"scope": "module", "killed": killed, "honesty": get_settings().honesty}


@router.get("/status")
def status(admin: AdminPrincipal) -> dict:
    return {
        "module": _get("module"),
        "platform": {**_get("platform"), "platform_hook_connected": False},
        "honesty": "🟡",  # platform level is a reservation until P exists
    }


@router.get("/audit")
def kill_audit(admin: AdminPrincipal, limit: int = 50) -> dict:
    events = audit.recent(limit, actions=(
        "risk.kill", "risk.unkill", "risk.kill.prepared", "risk.unkill.prepared",
        "risk.confirm.refused",
    ))
    return {"events": events, "honesty": get_settings().honesty}


@router.get("/audit/verify")
def audit_verify(admin: AdminPrincipal) -> dict:
    """Recompute the audit hash chain. Anchor `head` outside the system daily."""
    return {**audit.verify(), "honesty": get_settings().honesty}
