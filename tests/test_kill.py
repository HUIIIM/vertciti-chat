# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Kill switch tests (contract §2.4/§5): module kill blocks chat + LLM routes,
unkill recovers, platform scope is an honest reservation, audit trail exists."""


def _kill(client, auth_headers, scope="module"):
    return client.post("/v1/risk/kill", json={
        "scope": scope, "reason_code": "drill", "actor": "test",
    }, headers=auth_headers)


def test_kill_module_blocks_messages(client, auth_headers, session_id):
    r = _kill(client, auth_headers)
    assert r.status_code == 200
    assert r.json()["killed"] is True

    m = client.post(f"/v1/chat/sessions/{session_id}/messages",
                    json={"content": "x"}, headers=auth_headers)
    assert m.status_code == 503
    assert m.json()["code"] == "chat_killed"

    l = client.post("/v1/llm/route", json={
        "model_policy": "default", "messages": [], "idempotency_key": "kk1",
    }, headers=auth_headers)
    assert l.status_code == 503

    s = client.get(f"/v1/chat/sessions/{session_id}/stream?message_id=zzz",
                   headers=auth_headers)
    assert s.status_code == 503


def test_unkill_recovers(client, auth_headers, session_id):
    _kill(client, auth_headers)
    r = client.post("/v1/risk/unkill", json={"scope": "module", "actor": "test"},
                    headers=auth_headers)
    assert r.json()["killed"] is False
    m = client.post(f"/v1/chat/sessions/{session_id}/messages",
                    json={"content": "back"}, headers=auth_headers)
    assert m.status_code == 200


def test_platform_scope_is_honest_reservation(client, auth_headers):
    r = _kill(client, auth_headers, scope="platform")
    assert r.status_code == 200
    body = r.json()
    assert body["platform_hook_connected"] is False
    assert body["honesty"] == "🟡"


def test_kill_audit_trail(client, auth_headers):
    _kill(client, auth_headers)
    client.post("/v1/risk/unkill", json={"scope": "module", "actor": "test"},
                headers=auth_headers)
    r = client.get("/v1/risk/audit", headers=auth_headers)
    actions = [e["action"] for e in r.json()["events"]]
    assert "risk.kill" in actions
    assert "risk.unkill" in actions


def test_status_shape(client, auth_headers):
    r = client.get("/v1/risk/status", headers=auth_headers)
    body = r.json()
    assert "module" in body and "platform" in body
    assert body["platform"]["platform_hook_connected"] is False
