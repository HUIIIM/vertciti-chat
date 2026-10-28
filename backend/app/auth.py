# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Authentication: three principals, never one shared key.

| principal | credential                       | may use                              |
|-----------|----------------------------------|--------------------------------------|
| visitor   | signed visitor token (anonymous) | own chat sessions, CTA, own events   |
| service   | CHAT_API_KEY                     | own chat sessions, memory, LLM route |
| admin     | CHAT_ADMIN_KEY                   | kill switch, audit, metrics          |

Visitor tokens are minted without signup (`POST /v1/visitor`) and signed with
HMAC-SHA256 under CHAT_VISITOR_SECRET, so the public page never holds a key
that can do anything beyond its own conversations.

Keys are compared in constant time. Logs and the database only ever see
hashes: the key hash, the visitor id, and an HMAC of the client IP.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from . import audit
from .config import get_settings
from .errors import Forbidden, Unauthorized

TOKEN_VERSION = "v1"  # noqa: S105 - a format tag, not a credential


@dataclass(frozen=True)
class Principal:
    kind: str  # "visitor" | "service" | "admin"
    subject: str  # stable owner id, e.g. "visitor:3f2a…" or "service:9b1c…"
    ip_hash: str

    @property
    def key_hash(self) -> str:
        """Back-compat name used by audit/quota callers: the subject id."""
        return self.subject


def key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def ip_hash(ip: str) -> str:
    """Keyed hash of the client IP: usable for limits, useless if leaked."""
    secret = get_settings().visitor_secret.encode()
    return hmac.new(secret, ip.encode(), hashlib.sha256).hexdigest()[:24]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _sign(payload: str) -> str:
    secret = get_settings().visitor_secret.encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def mint_visitor_token(now: float | None = None) -> dict:
    settings = get_settings()
    issued = int(now if now is not None else time.time())
    expires = issued + settings.visitor_token_ttl_hours * 3600
    visitor_id = secrets.token_hex(12)
    payload = f"{TOKEN_VERSION}.{visitor_id}.{expires}"
    return {
        "visitor_token": f"{payload}.{_sign(payload)}",
        "visitor_id": visitor_id,
        "expires_at": expires,
    }


def parse_visitor_token(token: str, now: float | None = None) -> str | None:
    """Return the visitor id if the token is authentic and unexpired."""
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != TOKEN_VERSION:
        return None
    version, visitor_id, expires, sig = parts
    if not hmac.compare_digest(sig, _sign(f"{version}.{visitor_id}.{expires}")):
        return None
    try:
        exp = int(expires)
    except ValueError:
        return None
    if exp < int(now if now is not None else time.time()):
        return None
    return visitor_id


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _match(provided: str, expected: str) -> bool:
    return bool(provided and expected) and hmac.compare_digest(provided, expected)


def _resolve(request: Request) -> Principal | None:
    settings = get_settings()
    iph = ip_hash(_client_ip(request))
    api_key = request.headers.get("x-api-key", "") or _bearer(request)
    if api_key:
        if _match(api_key, settings.admin_key):
            return Principal("admin", f"admin:{key_hash(api_key)}", iph)
        if _match(api_key, settings.api_key):
            return Principal("service", f"service:{key_hash(api_key)}", iph)
        return None
    token = request.headers.get("x-visitor-token", "")
    if token:
        visitor_id = parse_visitor_token(token)
        if visitor_id:
            return Principal("visitor", f"visitor:{visitor_id}", iph)
    return None


def _require(request: Request, kinds: tuple[str, ...]) -> Principal:
    principal = _resolve(request)
    if principal is None:
        audit.record("auth.failed", "anonymous", {"path": request.url.path})
        raise Unauthorized("missing or invalid credentials")
    if principal.kind not in kinds:
        audit.record(
            "auth.forbidden", principal.subject, {"path": request.url.path, "kind": principal.kind}
        )
        raise Forbidden(f"this endpoint is not available to {principal.kind} credentials")
    request.state.principal_kind = principal.kind
    return principal


async def require_chat(request: Request) -> Principal:
    return _require(request, ("visitor", "service"))


async def require_service(request: Request) -> Principal:
    return _require(request, ("service",))


async def require_admin(request: Request) -> Principal:
    return _require(request, ("admin",))


def client_ip_hash(request: Request) -> str:
    return ip_hash(_client_ip(request))


ChatPrincipal = Annotated[Principal, Depends(require_chat)]
ServicePrincipal = Annotated[Principal, Depends(require_service)]
AdminPrincipal = Annotated[Principal, Depends(require_admin)]

# Back-compat alias: the service key dependency under its old name.
require_api_key = require_service
