# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Memory endpoints, contract v1 §2.2 shape.

POST   /v1/memory/store   {namespace, key, payload, pii_fields?, ttl_days?, embedding?}
POST   /v1/memory/recall  {namespace?, query?, top_k?, min_score?}
DELETE /v1/memory/forget  {namespace, key}

Isolation and privacy rules live in memory_store.py; this router only wires
auth, rate limiting and honesty labels.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from . import audit, db as _db
from .auth import require_api_key
from .config import get_settings
from .errors import RateLimited
from .memory_store import MODULE_ID, enforce_module, get_memory_store, redact_pii
from .models import MemoryForgetRequest, MemoryRecallRequest, MemoryStoreRequest
from .rate_limit import limiter

router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _rl(identity: dict) -> None:
    ok, retry = limiter.check_request(identity)
    if not ok:
        raise RateLimited("rate limit exceeded", retry_after=retry)
    limiter.count_request(identity)


@router.post("/store")
def store(body: MemoryStoreRequest, identity: dict = Depends(require_api_key)):
    _rl(identity)
    enforce_module(body.module, identity["key_hash"])
    redacted, had_pii = redact_pii(body.payload, body.pii_fields)
    result = get_memory_store().store(
        module_id=MODULE_ID,
        namespace=body.namespace,
        key=body.key,
        payload=redacted,
        pii_redacted=had_pii,
        ttl_days=body.ttl_days,
    )
    audit.record("memory.store", identity["key_hash"],
                 {"namespace": body.namespace, "key": body.key, "pii_redacted": had_pii})
    return {**result, "pii_redacted": had_pii, "honesty": get_settings().honesty,
            "note": "dev store: keyword recall only; vector search lands with platform base P"}


@router.post("/recall")
def recall(body: MemoryRecallRequest, identity: dict = Depends(require_api_key)):
    _rl(identity)
    enforce_module(body.module, identity["key_hash"])
    records = get_memory_store().recall(
        module_id=MODULE_ID, namespace=body.namespace, query=body.query,
        top_k=body.top_k, min_score=body.min_score,
    )
    return {"records": records, "count": len(records), "honesty": get_settings().honesty}


@router.delete("/forget")
def forget(body: MemoryForgetRequest, identity: dict = Depends(require_api_key)):
    _rl(identity)
    enforce_module(body.module, identity["key_hash"])
    deleted = get_memory_store().forget(module_id=MODULE_ID, namespace=body.namespace, key=body.key)
    audit.record("memory.forget", identity["key_hash"],
                 {"namespace": body.namespace, "key": body.key, "deleted": deleted})
    return {"deleted": deleted, "honesty": get_settings().honesty}
