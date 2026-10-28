# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Chat session API tests: create / list / get / delete / send (blocking) /
stream (SSE) lifecycle / cost / scoped idempotency / honesty labels."""

import json

import pytest
from conftest import mint


def _events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data:")]


@pytest.mark.req("CHAT-sessions")
def test_create_session(client, auth_headers):
    r = client.post("/v1/chat/sessions", json={"title": "hello"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"]
    assert body["honesty"] == "🟡"


@pytest.mark.req("CHAT-sessions")
def test_get_session_empty(client, auth_headers, session_id):
    r = client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["messages"] == []


@pytest.mark.req("CHAT-sessions", "SEC-error-contract")
def test_get_session_404(client, auth_headers):
    r = client.get("/v1/chat/sessions/nope", headers=auth_headers)
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert "trace_id" in body


@pytest.mark.req("CHAT-sessions")
def test_send_message_blocking(client, auth_headers, session_id):
    r = client.post(f"/v1/chat/sessions/{session_id}/messages",
                    json={"content": "inline 你好", "stream": False}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "echo: inline 你好"
    assert body["run_id"] is None
    assert body["honesty"] == "🟡"
    g = client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers).json()
    assert [m["role"] for m in g["messages"]] == ["user", "assistant"]
    assert g["messages"][1]["status"] == "done"


@pytest.mark.req("CHAT-stream")
def test_send_message_stream_mode_then_sse(client, auth_headers, session_id):
    r = client.post(f"/v1/chat/sessions/{session_id}/messages",
                    json={"content": "hi", "stream": True}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["stream_url"].startswith(f"/v1/chat/sessions/{session_id}/stream?message_id=")
    assert body["cards"][0]["kind"] == "clarify_card"

    s = client.get(body["stream_url"], headers=auth_headers)
    assert s.status_code == 200
    assert "text/event-stream" in s.headers["content-type"]
    events = _events(s.text)
    types = [e["type"] for e in events]
    assert types[0] == "meta"
    assert types[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "token") == "hello"
    done = events[-1]
    assert done["status"] == "done"
    assert done["honesty"] == "🟡"
    assert "remaining_today" in done and "session_cost_cents" in done

    g = client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers).json()
    assistant = next(m for m in g["messages"] if m["role"] == "assistant")
    assert assistant["content"] == "hello"
    assert assistant["status"] == "done"


@pytest.mark.req("CHAT-stream", "COST-replay")
def test_stream_replay_does_not_rerun_the_runtime(client, auth_headers, session_id, monkeypatch):
    """Regression: a second GET of the same stream re-ran the agent (re-billed)."""
    from app import anomalies_client

    calls = []

    async def counting_stream(run_id):
        calls.append(run_id)
        yield "message", '{"text": "once"}'

    monkeypatch.setattr(anomalies_client, "stream_chat", counting_stream)
    url = client.post(f"/v1/chat/sessions/{session_id}/messages",
                      json={"content": "run", "stream": True}, headers=auth_headers).json()["stream_url"]
    first = _events(client.get(url, headers=auth_headers).text)
    second = _events(client.get(url, headers=auth_headers).text)
    assert len(calls) == 1
    assert second[0]["replay"] is True
    assert "".join(e.get("text", "") for e in second if e["type"] == "token") == "once"
    assert first[-1]["status"] == second[-1]["status"] == "done"


@pytest.mark.req("CHAT-stream", "SEC-A7")
def test_runtime_internals_not_forwarded(client, auth_headers, session_id, monkeypatch):
    from app import anomalies_client

    async def noisy(run_id):
        yield "tool_call", '{"secret_internal": "do not leak", "args": [1, 2]}'
        yield "message", '{"text": "ok"}'

    monkeypatch.setattr(anomalies_client, "stream_chat", noisy)
    url = client.post(f"/v1/chat/sessions/{session_id}/messages",
                      json={"content": "run", "stream": True}, headers=auth_headers).json()["stream_url"]
    text = client.get(url, headers=auth_headers).text
    assert "do not leak" not in text
    assert {"type": "agent", "event": "tool_call"} in _events(text)


@pytest.mark.req("CHAT-sessions")
def test_send_message_unknown_session(client, auth_headers):
    r = client.post("/v1/chat/sessions/nope/messages", json={"content": "x"}, headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.req("LLM-idempotency")
def test_message_idempotency(client, auth_headers, session_id):
    payload = {"content": "inline once", "idempotency_key": "idem-1"}
    r1 = client.post(f"/v1/chat/sessions/{session_id}/messages", json=payload, headers=auth_headers)
    r2 = client.post(f"/v1/chat/sessions/{session_id}/messages", json=payload, headers=auth_headers)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["message_id"] == r2.json()["message_id"]
    g = client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers)
    assert len([m for m in g.json()["messages"] if m["role"] == "user"]) == 1


@pytest.mark.req("LLM-idempotency", "SEC-A1")
def test_idempotency_key_scoped_to_session_and_caller(client):
    """Regression: a global key replayed session A's reply into session B and
    silently dropped B's message."""
    a, b = mint(client), mint(client)
    sa = client.post("/v1/chat/sessions", json={}, headers=a).json()["session_id"]
    sa2 = client.post("/v1/chat/sessions", json={}, headers=a).json()["session_id"]
    sb = client.post("/v1/chat/sessions", json={}, headers=b).json()["session_id"]
    ra = client.post(f"/v1/chat/sessions/{sa}/messages",
                     json={"content": "inline secret-A", "idempotency_key": "shared"}, headers=a).json()
    ra2 = client.post(f"/v1/chat/sessions/{sa2}/messages",
                      json={"content": "inline A2", "idempotency_key": "shared"}, headers=a).json()
    rb = client.post(f"/v1/chat/sessions/{sb}/messages",
                     json={"content": "inline B", "idempotency_key": "shared"}, headers=b).json()
    assert len({ra["message_id"], ra2["message_id"], rb["message_id"]}) == 3
    assert "secret-A" not in rb["reply"]
    assert len(client.get(f"/v1/chat/sessions/{sb}", headers=b).json()["messages"]) == 2


@pytest.mark.req("CHAT-sessions", "COST")
def test_session_cost_endpoint(client, auth_headers, session_id):
    client.post(f"/v1/chat/sessions/{session_id}/messages", json={"content": "inline x"},
                headers=auth_headers)
    r = client.get(f"/v1/chat/sessions/{session_id}/cost", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["assistant_messages"] == 1
    assert body["honesty"] == "🟡"


@pytest.mark.req("HONESTY", "DES-6")
def test_agent_unavailable_is_honest(client, auth_headers, session_id, monkeypatch):
    from app import anomalies_client

    def boom(message, history=None):
        raise anomalies_client.AnomaliesUnavailable("down")

    monkeypatch.setattr(anomalies_client, "post_chat", boom)
    r = client.post(f"/v1/chat/sessions/{session_id}/messages",
                    json={"content": "x"}, headers=auth_headers)
    assert r.status_code == 503
    assert r.json()["detail"]["reason"] == "agent_unavailable"
    assert "no reply was generated" in r.json()["message"]
    roles = [m["role"] for m in client.get(f"/v1/chat/sessions/{session_id}",
                                           headers=auth_headers).json()["messages"]]
    assert roles == ["user"]  # no fabricated assistant reply


@pytest.mark.req("INT-5", "PRIV-erasure")
def test_list_and_delete_sessions(client, visitor_headers):
    sid = client.post("/v1/chat/sessions", json={}, headers=visitor_headers).json()["session_id"]
    client.post(f"/v1/chat/sessions/{sid}/messages", json={"content": "inline remember me"},
                headers=visitor_headers)
    listed = client.get("/v1/chat/sessions", headers=visitor_headers).json()["sessions"]
    assert listed[0]["id"] == sid
    assert listed[0]["title"].startswith("inline remember me")
    r = client.delete(f"/v1/chat/sessions/{sid}", headers=visitor_headers)
    assert r.json()["messages_deleted"] == 2
    assert client.get(f"/v1/chat/sessions/{sid}", headers=visitor_headers).status_code == 404

    from app import db as _db
    left = _db.get_store().fetchone("SELECT COUNT(*) n FROM messages WHERE session_id=?", (sid,))
    assert left["n"] == 0


@pytest.mark.req("ARCH-4")
def test_history_bounded_by_characters(client, auth_headers, session_id, monkeypatch):
    from app import anomalies_client
    from app.config import reset_settings

    monkeypatch.setenv("CHAT_HISTORY_MAX_CHARS", "50")
    reset_settings()
    seen = {}

    def capture(message, history=None):
        seen["history"] = history
        return {"run_id": None, "reply": "ok", "cards": []}

    monkeypatch.setattr(anomalies_client, "post_chat", capture)
    for _ in range(3):
        client.post(f"/v1/chat/sessions/{session_id}/messages", json={"content": "y" * 30},
                    headers=auth_headers)
    assert sum(len(m["content"]) for m in seen["history"]) <= 50
    assert seen["history"][-1]["content"] == "y" * 30  # the current turn is kept
