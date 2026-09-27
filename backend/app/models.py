# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Pydantic request/response models. All success bodies carry an `honesty`
label (🟢🟡⚪ per design philosophy; dev/transitional states are honestly 🟡)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    stream: bool = False
    idempotency_key: str | None = None


class LLMRouteRequest(BaseModel):
    # NOTE: no `module` field is accepted — the server binds module="chat".
    model_policy: Literal["default", "quality", "cheap"]
    messages: list[dict[str, Any]]
    max_tokens: int | None = None
    fallback_chain: bool = True
    budget_units: int | None = None
    idempotency_key: str


class MemoryStoreRequest(BaseModel):
    module: str | None = None  # if present and != chat -> 403 (server enforces)
    namespace: str
    key: str
    embedding: list[float] | None = None  # accepted per contract; unused by sqlite dev store (honest 🟡)
    payload: dict[str, Any]
    pii_fields: list[str] | None = None
    ttl_days: int | None = None


class MemoryRecallRequest(BaseModel):
    module: str | None = None
    namespace: str = ""
    query: str = ""
    top_k: int = 5
    min_score: float = 0.0


class MemoryForgetRequest(BaseModel):
    module: str | None = None
    namespace: str
    key: str


class KillRequest(BaseModel):
    scope: Literal["module", "platform"]
    reason_code: str
    actor: str


class UnkillRequest(BaseModel):
    scope: Literal["module", "platform"]
    actor: str


class EventRequest(BaseModel):
    type: str
    session_id: str | None = None
    detail: dict[str, Any] | None = None
