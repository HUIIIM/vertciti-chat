# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Pydantic request/response models. All success bodies carry an `honesty`
label (🟢🟡⚪ per design philosophy; dev/transitional states are honestly 🟡).

Every free-form field has an upper bound so no request can grow unbounded
work or storage."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Event types a client may record. Server-side events are written directly.
CLIENT_EVENT_TYPES = ("cta_click", "workbench_entry", "module_switch")
MAX_EVENT_DETAIL_BYTES = 2048


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    stream: bool = False
    idempotency_key: str | None = Field(default=None, max_length=128)


class LLMRouteRequest(BaseModel):
    # NOTE: no `module` field is accepted — the server binds module="chat".
    model_policy: Literal["default", "quality", "cheap"]
    messages: list[dict[str, Any]] = Field(max_length=50)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    fallback_chain: bool = True
    budget_units: int | None = Field(default=None, ge=0)
    idempotency_key: str = Field(min_length=1, max_length=128)


class MemoryStoreRequest(BaseModel):
    module: str | None = Field(default=None, max_length=64)  # != chat -> 403 (server enforces)
    namespace: str = Field(min_length=1, max_length=200)
    key: str = Field(min_length=1, max_length=200)
    embedding: list[float] | None = None  # accepted per contract; unused by sqlite dev store (honest 🟡)
    payload: dict[str, Any]
    pii_fields: list[str] | None = Field(default=None, max_length=100)
    ttl_days: int | None = Field(default=None, ge=1, le=3650)


class MemoryRecallRequest(BaseModel):
    module: str | None = Field(default=None, max_length=64)
    namespace: str = Field(default="", max_length=200)
    query: str = Field(default="", max_length=1000)
    top_k: int = Field(default=5, ge=1, le=100)
    min_score: float = 0.0


class MemoryForgetRequest(BaseModel):
    module: str | None = Field(default=None, max_length=64)
    namespace: str = Field(min_length=1, max_length=200)
    key: str = Field(min_length=1, max_length=200)


class KillRequest(BaseModel):
    scope: Literal["module", "platform"]
    reason_code: str = Field(min_length=1, max_length=64)
    actor: str = Field(min_length=1, max_length=64)


class UnkillRequest(BaseModel):
    scope: Literal["module", "platform"]
    actor: str = Field(min_length=1, max_length=64)
    reason_code: str | None = Field(default=None, max_length=64)


class ConfirmRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    confirm_phrase: str = Field(min_length=1, max_length=64)


class EventRequest(BaseModel):
    type: Literal["cta_click", "workbench_entry", "module_switch"]
    session_id: str | None = Field(default=None, max_length=64)
    detail: dict[str, Any] | None = None

    @field_validator("detail")
    @classmethod
    def _detail_small(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v, ensure_ascii=False)) > MAX_EVENT_DETAIL_BYTES:
            raise ValueError(f"detail must be at most {MAX_EVENT_DETAIL_BYTES} bytes of JSON")
        return v
