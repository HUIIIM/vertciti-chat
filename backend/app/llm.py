# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Local LLM router, contract v1 §2.1 shape.

Rules enforced here:
- `module` is bound server-side to "chat" (we never trust a client self-report).
- `model_policy` ∈ {default, quality, cheap}; concrete model ids come ONLY from
  env (CHAT_MODEL_DEFAULT / _QUALITY / _CHEAP). No hardcoded model ids, ever.
- `budget_units` (integer minor units, i.e. cents) is a hard fuse: if the
  realized cost exceeds it, the call is treated as failed (BudgetExceeded).
- `idempotency_key` is required; repeats return the stored response.
- Keys live in process memory / env only. Never logged, never persisted.

Provider interface: `LLMProvider`. Dev default is an OpenAI-compatible HTTP
endpoint; `CHAT_LLM_PROVIDER=fake` selects the deterministic test double.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from . import audit, db as _db
from .config import get_settings
from .errors import BadRequest, BudgetExceeded, ServiceUnavailable

MODULE_ID = "chat"
POLICIES = ("default", "quality", "cheap")


@dataclass
class LLMResult:
    model_id: str
    output: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class LLMProvider(Protocol):
    name: str

    def complete(self, *, model_id: str, messages: list[dict], max_tokens: int | None) -> LLMResult: ...


class FakeProvider:
    """Deterministic test/dev double. Only used when explicitly selected."""

    name = "fake"

    def complete(self, *, model_id, messages, max_tokens) -> LLMResult:
        text = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
        out = f"[fake:{model_id}] {text[:200]}"
        return LLMResult(model_id=model_id, output=out, tokens_in=50, tokens_out=20, latency_ms=5)


class OpenAICompatProvider:
    """OpenAI-compatible /chat/completions endpoint. Key from env, never logged."""

    name = "openai_compat"

    def complete(self, *, model_id, messages, max_tokens) -> LLMResult:
        settings = get_settings()
        if not settings.llm_base_url or not settings.llm_api_key:
            raise ServiceUnavailable("llm_not_configured: set CHAT_LLM_BASE_URL and CHAT_LLM_API_KEY")
        body = {"model": model_id, "messages": messages}
        if max_tokens:
            body["max_tokens"] = max_tokens
        started = time.monotonic()
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{settings.llm_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json=body,
                )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            raise ServiceUnavailable(f"llm unreachable: {e}") from e
        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code >= 400:
            raise ServiceUnavailable(f"llm error {resp.status_code}")
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return LLMResult(
            model_id=data.get("model", model_id),
            output=((choice.get("message") or {}).get("content") or ""),
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
        )


def resolve_model(policy: str) -> str:
    if policy not in POLICIES:
        raise BadRequest(f"model_policy must be one of {POLICIES}")
    settings = get_settings()
    model = {"default": settings.model_default, "quality": settings.model_quality, "cheap": settings.model_cheap}[policy]
    if not model:
        raise ServiceUnavailable(
            f"llm_not_configured: no model mapped for policy '{policy}' "
            f"(set CHAT_MODEL_{policy.upper()})"
        )
    return model


def _provider() -> LLMProvider:
    if get_settings().llm_provider == "fake":
        return FakeProvider()
    return OpenAICompatProvider()


def cost_cents(tokens_in: int, tokens_out: int, policy: str) -> int:
    """Integer minor-unit cost. Price table from env (cents per 1M tokens)."""
    table = get_settings().price_table.get(policy, {})
    price_in = int(table.get("in", 0))
    price_out = int(table.get("out", 0))
    return (tokens_in * price_in + tokens_out * price_out) // 1_000_000


def route(
    *,
    messages: list[dict],
    model_policy: str,
    max_tokens: int | None = None,
    fallback_chain: bool = True,
    budget_units: int | None = None,
    idempotency_key: str,
    actor: str,
) -> dict:
    """Contract §2.1 POST /v1/llm/route. Module is fixed to 'chat'."""
    if not idempotency_key:
        raise BadRequest("idempotency_key is required")

    store = _db.get_store()
    hit = store.fetchone("SELECT response_json FROM idempotency WHERE key=?", (idempotency_key,))
    if hit:
        import json

        return json.loads(hit["response_json"])

    model_id = resolve_model(model_policy)
    result = _provider().complete(model_id=model_id, messages=messages, max_tokens=max_tokens)
    cost = cost_cents(result.tokens_in, result.tokens_out, model_policy)

    if budget_units is not None and cost > budget_units:
        audit.record(
            "llm.budget_exceeded",
            actor,
            {"policy": model_policy, "cost_cents": cost, "budget_units": budget_units},
        )
        raise BudgetExceeded(f"cost {cost}c exceeded budget {budget_units}c")

    response = {
        "model_id": result.model_id,  # factual label of the actually-resolved model
        "output": result.output,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_cents": cost,
        "fallback_used": False,
        "latency_ms": result.latency_ms,
        "honesty": get_settings().honesty,
    }
    store.execute(
        "INSERT OR IGNORE INTO idempotency(key, endpoint, response_json, created_at) VALUES(?,?,?,?)",
        (idempotency_key, "llm.route", _db.dumps(response), _db.utcnow()),
    )
    return response
