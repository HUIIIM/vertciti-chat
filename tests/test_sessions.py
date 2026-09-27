# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Chat session API tests: create / get / send (blocking) / stream (SSE) /
cost / idempotency / honesty labels."""

import json


def test_create_session(client, auth_headers):
    r = client.post("/v1/chat/sessions", json={"title": "hello"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"]
    assert body["honesty"] == "🟡"


def test_get_session_empty(client, auth_headers, session_id):
    r = client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_get_session_404(client, auth_headers):
    r = client.get("/v1/chat/sessions/nope", headers=auth_headers)
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert "trace_id" in body


def test_send_message_blocking(client, auth_headers, session_id):
    r = client.post(
        f"/v1/chat/sessions/{session_id}/messages",
        json={"content": "你好", "stream": False},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "echo: 你好"
    assert body["run_id"] == "run-fake-1"
    assert body["cards"][0]["kind"] == "clarify_card"
    assert body["honesty"] == "🟡"

    # message persisted
    g = client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers)
    roles = [m["role"] for m in g.json()["messages"]]
    assert roles == ["user", "assistant"]


def test_send_message_stream_mode_then_sse(client, auth_headers, session_id):
    r = client.post(
        f"/v1/chat/sessions/{session_id}/messages",
        json={"content": "hi", "stream": True},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stream_url"].startswith(f"/v1/chat/sessions/{session_id}/stream?message_id=")

    s = client.get(body["stream_url"], headers=auth_headers)
    assert s.status_code == 200
    assert "text/event-stream" in s.headers["content-type"]
    events = [json.loads(line[6:]) for line in s.text.splitlines() if line.startswith("data:")]
    types = [e["type"] for e in events]
    assert types[0] == "meta"
    assert "token" in types
    assert types[-1] == "done"
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert tokens == "hello"
    assert events[-1]["honesty"] == "🟡"

    # streamed text persisted onto the assistant message
    g = client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers)
    assistant = [m for m in g.json()["messages"] if m["role"] == "assistant"][0]
    assert assistant["content"] == "hello"


def test_send_message_unknown_session(client, auth_headers):
    r = client.post("/v1/chat/sessions/nope/messages", json={"content": "x"}, headers=auth_headers)
    assert r.status_code == 404


def test_message_idempotency(client, auth_headers, session_id):
    payload = {"content": "once", "idempotency_key": "idem-1"}
    r1 = client.post(f"/v1/chat/sessions/{session_id}/messages", json=payload, headers=auth_headers)
    r2 = client.post(f"/v1/chat/sessions/{session_id}/messages", json=payload, headers=auth_headers)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["message_id"] == r2.json()["message_id"]
    g = client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers)
    users = [m for m in g.json()["messages"] if m["role"] == "user"]
    assert len(users) == 1  # second POST did not duplicate


def test_session_cost_endpoint(client, auth_headers, session_id):
    client.post(f"/v1/chat/sessions/{session_id}/messages",
                json={"content": "x"}, headers=auth_headers)
    r = client.get(f"/v1/chat/sessions/{session_id}/cost", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["assistant_messages"] == 1
    assert body["honesty"] == "🟡"


def test_agent_unavailable_is_honest(client, auth_headers, session_id, monkeypatch):
    from app import anomalies_client

    def boom(message, history=None):
        raise anomalies_client.AnomaliesUnavailable("down")

    monkeypatch.setattr(anomalies_client, "post_chat", boom)
    r = client.post(f"/v1/chat/sessions/{session_id}/messages",
                    json={"content": "x"}, headers=auth_headers)
    assert r.status_code == 503
    assert "虚假" in r.json()["message"] or "暂不可用" in r.json()["message"]
