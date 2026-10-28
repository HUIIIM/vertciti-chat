# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""LLM router tests (contract §2.1): server-bound module, policy mapping from
env (no hardcoded model ids), budget fuse, bounded tokens, caller-scoped
idempotency, honest unconfigured state. Uses the deterministic FakeProvider."""

import pytest


def _route(client, auth_headers, **kw):
    body = {
        "model_policy": "default",
        "messages": [{"role": "user", "content": "hi"}],
        "idempotency_key": kw.pop("idempotency_key", "k-" + kw.pop("tag", "x")),
        **kw,
    }
    return client.post("/v1/llm/route", json=body, headers=auth_headers)


@pytest.mark.req("LLM-cost")
def test_route_fake_provider_cost_is_integer_cents(client, auth_headers):
    r = _route(client, auth_headers, tag="cost")
    assert r.status_code == 200, r.text
    body = r.json()
    # fake: 50 in @100c/M, 20 out @300c/M -> (50*100 + 20*300)//1e6 = 0
    assert body["cost_cents"] == 0
    assert isinstance(body["cost_cents"], int)
    assert body["model_id"] == "fake-default"
    assert body["fallback_used"] is False
    assert body["honesty"] == "🟡"


@pytest.mark.req("LLM-policy")
def test_policy_selects_model_from_env(client, auth_headers):
    r = _route(client, auth_headers, model_policy="cheap", tag="cheap")
    assert r.status_code == 200
    assert r.json()["model_id"] == "fake-cheap"


@pytest.mark.req("LLM-policy")
def test_invalid_policy_rejected(client, auth_headers):
    r = _route(client, auth_headers, model_policy="ultra", tag="bad")
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


@pytest.mark.req("LLM-idempotency")
def test_idempotency_key_required(client, auth_headers):
    r = client.post("/v1/llm/route", json={
        "model_policy": "default",
        "messages": [{"role": "user", "content": "hi"}],
    }, headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.req("LLM-idempotency")
def test_idempotent_repeats_return_same(client, auth_headers):
    b1 = _route(client, auth_headers, tag="idem").json()
    b2 = _route(client, auth_headers, tag="idem").json()
    assert b1 == b2


@pytest.mark.req("ARCH-4")
def test_max_tokens_defaults_and_is_capped(client, auth_headers, monkeypatch):
    from app.config import reset_settings

    assert _route(client, auth_headers, tag="mt1").json()["max_tokens"] == 1024
    monkeypatch.setenv("CHAT_LLM_MAX_TOKENS_CAP", "256")
    reset_settings()
    assert _route(client, auth_headers, tag="mt2", max_tokens=9000).json()["max_tokens"] == 256


@pytest.mark.req("ARCH-4")
def test_message_count_bounded(client, auth_headers):
    r = _route(client, auth_headers, tag="many",
               messages=[{"role": "user", "content": "x"}] * 51)
    assert r.status_code == 422


@pytest.mark.req("LLM-budget")
def test_budget_fuse_trips(client, auth_headers, monkeypatch):
    import app.llm as llm_mod

    monkeypatch.setattr(llm_mod, "cost_cents", lambda ti, to, p: 999)
    r = _route(client, auth_headers, budget_units=10, tag="budget")
    assert r.status_code == 402
    assert r.json()["code"] == "budget_exceeded"


@pytest.mark.req("HONESTY")
def test_unconfigured_policy_model_is_honest(client, auth_headers, monkeypatch):
    from app.config import reset_settings

    monkeypatch.delenv("CHAT_MODEL_CHEAP")
    reset_settings()
    r = _route(client, auth_headers, model_policy="cheap", tag="unconf")
    assert r.status_code == 503
    assert "llm_not_configured" in r.json()["message"]
