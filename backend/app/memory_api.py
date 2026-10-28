# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Memory endpoints, contract v1 §2.2 shape.

POST   /v1/memory/store   {namespace, key, payload, pii_fields?, ttl_days?, embedding?}
POST   /v1/memory/recall  {namespace?, query?, top_k?, min_score?}
DELETE /v1/memory/forget  {namespace, key}

Service principals only (CHAT_API_KEY): visitors and the admin key get 403.
Store and recall stop while the kill switch is engaged; forget never stops.
Isolation and privacy rules live in memory_store.py; this router only wires
auth, rate limiting and honesty labels.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import audit
from .auth import Principal, ServicePrincipal
from .config import get_settings
from .kill import check_not_killed
from .memory_store import MODULE_ID, enforce_module, get_memory_store, redact_pii
from .models import MemoryForgetRequest, MemoryRecallRequest, MemoryStoreRequest
from .rate_limit import limiter

router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _rl(principal: Principal) -> None:
    limiter.enforce(principal)


@router.post("/store")
def store(body: MemoryStoreRequest, principal: ServicePrincipal) -> dict:
    check_not_killed()
    _rl(principal)
    enforce_module(body.module, principal.subject)
    redacted, had_pii = redact_pii(body.payload, body.pii_fields)
    result = get_memory_store().store(
        module_id=MODULE_ID,
        namespace=body.namespace,
        key=body.key,
        payload=redacted,
        pii_redacted=had_pii,
        ttl_days=body.ttl_days,
    )
    audit.record("memory.store", principal.subject,
                 {"namespace": body.namespace, "key": body.key, "pii_redacted": had_pii})
    return {**result, "pii_redacted": had_pii, "honesty": get_settings().honesty,
            "note": "dev store: keyword recall only; vector search lands with platform base P"}


@router.post("/recall")
def recall(body: MemoryRecallRequest, principal: ServicePrincipal) -> dict:
    check_not_killed()
    _rl(principal)
    enforce_module(body.module, principal.subject)
    records = get_memory_store().recall(
        module_id=MODULE_ID, namespace=body.namespace, query=body.query,
        top_k=body.top_k, min_score=body.min_score,
    )
    return {"records": records, "count": len(records), "honesty": get_settings().honesty}


@router.delete("/forget")
def forget(body: MemoryForgetRequest, principal: ServicePrincipal) -> dict:
    """Erasure keeps working while the kill switch is engaged."""
    _rl(principal)
    enforce_module(body.module, principal.subject)
    deleted = get_memory_store().forget(module_id=MODULE_ID, namespace=body.namespace, key=body.key)
    audit.record("memory.forget", principal.subject,
                 {"namespace": body.namespace, "key": body.key, "deleted": deleted})
    return {"deleted": deleted, "honesty": get_settings().honesty}
