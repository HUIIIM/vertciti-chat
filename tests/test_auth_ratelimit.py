# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Auth (E5) + rate limiting (E6): 401 shape, visitor tokens, 429 with
retry-after, atomic daily quotas per visitor and per IP, UTC quota day."""

import time

import pytest
from conftest import TEST_KEY, mint


def _reconfigure(monkeypatch, **env):
    from app.config import reset_settings
    from app.rate_limit import limiter

    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    reset_settings()
    limiter.reset()


@pytest.mark.req("SEC-A1", "E5")
def test_missing_credentials_401(client):
    r = client.post("/v1/chat/sessions", json={})
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "unauthorized"
    assert "trace_id" in body


@pytest.mark.req("SEC-A1", "E5")
def test_wrong_key_401(client):
    r = client.post("/v1/chat/sessions", json={}, headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


@pytest.mark.req("E5")
def test_bearer_header_accepted(client):
    r = client.post("/v1/chat/sessions", json={}, headers={"Authorization": f"Bearer {TEST_KEY}"})
    assert r.status_code == 200


@pytest.mark.req("SEC-A1", "PRODUCT-free-no-signup")
def test_visitor_token_needs_no_key_and_works(client):
    headers = mint(client)
    r = client.post("/v1/chat/sessions", json={}, headers=headers)
    assert r.status_code == 200


@pytest.mark.req("SEC-A1")
def test_tampered_or_expired_visitor_token_rejected(client):
    from app.auth import mint_visitor_token, parse_visitor_token

    tok = mint_visitor_token()["visitor_token"]
    forged = tok[:-1] + ("0" if tok[-1] != "0" else "1")
    assert client.post("/v1/chat/sessions", json={},
                       headers={"X-Visitor-Token": forged}).status_code == 401
    old = mint_visitor_token(now=time.time() - 10 * 365 * 86400)["visitor_token"]
    assert parse_visitor_token(old) is None
    assert client.post("/v1/chat/sessions", json={},
                       headers={"X-Visitor-Token": old}).status_code == 401


@pytest.mark.req("E6")
def test_rate_limit_429_with_retry_after(client, auth_headers, monkeypatch):
    _reconfigure(monkeypatch, CHAT_RATE_PER_MINUTE=2)
    assert client.post("/v1/chat/sessions", json={}, headers=auth_headers).status_code == 200
    assert client.post("/v1/chat/sessions", json={}, headers=auth_headers).status_code == 200
    r = client.post("/v1/chat/sessions", json={}, headers=auth_headers)
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limited"
    assert "retry-after" in r.headers


@pytest.mark.req("E6", "SEC-A1")
def test_per_ip_bucket_caps_many_visitor_tokens(client, monkeypatch):
    """Minting new tokens from one address must not multiply the allowance."""
    _reconfigure(monkeypatch, CHAT_IP_RATE_PER_MINUTE=3)
    codes = [client.post("/v1/chat/sessions", json={}, headers=mint(client)).status_code
             for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429


@pytest.mark.req("E6")
def test_visitor_mint_is_rate_limited_per_ip(client, monkeypatch):
    _reconfigure(monkeypatch, CHAT_VISITOR_MINT_PER_HOUR=2)
    assert client.post("/v1/visitor").status_code == 200
    assert client.post("/v1/visitor").status_code == 200
    r = client.post("/v1/visitor")
    assert r.status_code == 429
    assert "retry-after" in r.headers


@pytest.mark.req("E6")
def test_daily_message_quota(client, auth_headers, session_id, monkeypatch):
    _reconfigure(monkeypatch, CHAT_DAILY_MESSAGE_LIMIT=1)
    r1 = client.post(f"/v1/chat/sessions/{session_id}/messages",
                     json={"content": "inline one"}, headers=auth_headers)
    assert r1.status_code == 200
    assert r1.json()["remaining_today"] == 0
    r2 = client.post(f"/v1/chat/sessions/{session_id}/messages",
                     json={"content": "inline two"}, headers=auth_headers)
    assert r2.status_code == 429
    assert r2.json()["code"] == "quota_exceeded"
    assert int(r2.headers["retry-after"]) <= 86400


@pytest.mark.req("E6", "SEC-A1")
def test_visitor_quota_is_per_visitor_not_global(client, monkeypatch):
    """Regression: the quota used to be keyed on the one shared key, so one
    visitor exhausted it for everybody."""
    _reconfigure(monkeypatch, CHAT_VISITOR_DAILY_MESSAGE_LIMIT=1)
    a, b = mint(client), mint(client)
    sa = client.post("/v1/chat/sessions", json={}, headers=a).json()["session_id"]
    sb = client.post("/v1/chat/sessions", json={}, headers=b).json()["session_id"]
    assert client.post(f"/v1/chat/sessions/{sa}/messages", json={"content": "inline"},
                       headers=a).status_code == 200
    assert client.post(f"/v1/chat/sessions/{sa}/messages", json={"content": "inline"},
                       headers=a).status_code == 429
    assert client.post(f"/v1/chat/sessions/{sb}/messages", json={"content": "inline"},
                       headers=b).status_code == 200


@pytest.mark.req("E6")
def test_ip_daily_ceiling_across_visitors(client, monkeypatch):
    _reconfigure(monkeypatch, CHAT_IP_DAILY_MESSAGE_LIMIT=2)
    codes = []
    for _ in range(3):
        h = mint(client)
        sid = client.post("/v1/chat/sessions", json={}, headers=h).json()["session_id"]
        codes.append(client.post(f"/v1/chat/sessions/{sid}/messages",
                                 json={"content": "inline"}, headers=h).status_code)
    assert codes == [200, 200, 429]


@pytest.mark.req("E6")
def test_quota_is_atomic_under_concurrency(client, auth_headers, session_id, monkeypatch):
    """Regression: check and increment were separate statements (TOCTOU)."""
    from concurrent.futures import ThreadPoolExecutor

    _reconfigure(monkeypatch, CHAT_DAILY_MESSAGE_LIMIT=5)

    def send(_):
        return client.post(f"/v1/chat/sessions/{session_id}/messages",
                           json={"content": "inline x"}, headers=auth_headers).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(send, range(12)))
    assert codes.count(200) == 5
    assert codes.count(429) == 7


@pytest.mark.req("E6")
def test_quota_day_is_utc(client, auth_headers, session_id):
    from datetime import UTC, datetime

    client.post(f"/v1/chat/sessions/{session_id}/messages", json={"content": "inline"},
                headers=auth_headers)
    usage = client.get("/v1/usage", headers=auth_headers).json()
    assert usage["day"] == datetime.now(UTC).date().isoformat()
    assert usage["used"] == 1
