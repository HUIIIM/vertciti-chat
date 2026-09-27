# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Auth (E5) + rate limiting (E6) tests: 401 shape, 429 with retry-after,
daily quota, error body contract."""


def test_missing_key_401(client):
    r = client.post("/v1/chat/sessions", json={})
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "unauthorized"
    assert "trace_id" in body


def test_wrong_key_401(client):
    r = client.post("/v1/chat/sessions", json={}, headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_bearer_header_accepted(client, auth_headers):
    from conftest import TEST_KEY

    r = client.post("/v1/chat/sessions", json={},
                    headers={"Authorization": f"Bearer {TEST_KEY}"})
    assert r.status_code == 200


def test_rate_limit_429_with_retry_after(client, auth_headers, monkeypatch):
    from app.config import reset_settings
    from app.rate_limit import limiter

    monkeypatch.setenv("CHAT_RATE_PER_MINUTE", "2")
    reset_settings()
    limiter.reset()
    try:
        assert client.post("/v1/chat/sessions", json={}, headers=auth_headers).status_code == 200
        assert client.post("/v1/chat/sessions", json={}, headers=auth_headers).status_code == 200
        r = client.post("/v1/chat/sessions", json={}, headers=auth_headers)
        assert r.status_code == 429
        assert r.json()["code"] == "rate_limited"
        assert "retry-after" in r.headers
    finally:
        monkeypatch.setenv("CHAT_RATE_PER_MINUTE", "1000")
        reset_settings()
        limiter.reset()


def test_daily_message_quota(client, auth_headers, session_id, monkeypatch):
    from app.config import reset_settings

    monkeypatch.setenv("CHAT_DAILY_MESSAGE_LIMIT", "1")
    reset_settings()
    try:
        r1 = client.post(f"/v1/chat/sessions/{session_id}/messages",
                         json={"content": "one"}, headers=auth_headers)
        assert r1.status_code == 200
        r2 = client.post(f"/v1/chat/sessions/{session_id}/messages",
                         json={"content": "two"}, headers=auth_headers)
        assert r2.status_code == 429
        assert r2.json()["code"] == "quota_exceeded"
    finally:
        monkeypatch.setenv("CHAT_DAILY_MESSAGE_LIMIT", "1000")
        reset_settings()
