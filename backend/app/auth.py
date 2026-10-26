# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""API-key authentication (capability-map E5: server-side auth is a new,
mandatory capability for the public free chatbot).

Keys are compared in constant time, stored only as SHA-256 hashes in usage
counters, and never written to logs or disk.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Depends, Header, Request

from . import audit
from .config import get_settings
from .errors import Unauthorized


def key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _extract_key(request: Request, x_api_key: str | None) -> str:
    if x_api_key:
        return x_api_key
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    """FastAPI dependency. Returns the caller identity (key hash only)."""
    provided = _extract_key(request, x_api_key)
    expected = get_settings().api_key
    if not provided or not hmac.compare_digest(provided, expected):
        audit.record("auth.failed", "anonymous", {"path": request.url.path})
        raise Unauthorized("missing or invalid API key")
    return {"key_hash": key_hash(provided), "ip": request.client.host if request.client else "?"}
