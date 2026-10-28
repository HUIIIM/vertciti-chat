# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Stream bounds and failure modes (ARCH-4, ARCH-5): a slow run cannot block
the server, every run has a hard deadline and size cap, concurrent streams of
one reply are refused, and restarts reconcile orphaned replies."""

import asyncio
import json
import threading
import time

import pytest


def _events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data:")]


def _start_run(client, headers, sid):
    return client.post(f"/v1/chat/sessions/{sid}/messages", json={"content": "run", "stream": True},
                       headers=headers).json()


@pytest.mark.req("ARCH-4")
def test_slow_stream_does_not_block_other_requests(client, auth_headers, session_id, monkeypatch):
    """Regression: a sync runtime stream inside the async SSE generator froze
    /health for 13 s while one slow run was streaming."""
    from app import anomalies_client

    async def slow(run_id):
        for word in ("a", "b", "c"):
            await asyncio.sleep(0.6)
            yield "message", json.dumps({"text": word})

    monkeypatch.setattr(anomalies_client, "stream_chat", slow)
    url = _start_run(client, auth_headers, session_id)["stream_url"]
    t = threading.Thread(target=lambda: client.get(url, headers=auth_headers))
    t.start()
    time.sleep(0.3)
    started = time.monotonic()
    assert client.get("/health").status_code == 200
    elapsed = time.monotonic() - started
    t.join()
    assert elapsed < 0.5, f"/health took {elapsed:.2f}s while a stream was running"


@pytest.mark.req("ARCH-4")
def test_stream_deadline_cuts_the_run(client, auth_headers, session_id, monkeypatch):
    from app import anomalies_client

    async def too_long(run_id):
        yield "message", '{"text": "part"}'
        raise anomalies_client.StreamDeadlineExceeded("cut")

    monkeypatch.setattr(anomalies_client, "stream_chat", too_long)
    url = _start_run(client, auth_headers, session_id)["stream_url"]
    events = _events(client.get(url, headers=auth_headers).text)
    assert {"type": "error", "code": "stream_deadline",
            "message": "the reply took too long and was stopped"} in events
    assert events[-1]["status"] == "error"


@pytest.mark.req("ARCH-4")
def test_real_client_enforces_total_deadline(monkeypatch):
    """The production client itself stops after CHAT_STREAM_MAX_SECONDS."""
    import httpx

    from app import anomalies_client
    from app.config import reset_settings

    monkeypatch.setenv("CHAT_STREAM_MAX_SECONDS", "1")
    reset_settings()

    async def endless_body():
        while True:
            yield b'data: {"text": "x"}\n\n'
            await asyncio.sleep(0.2)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=endless_body())

    real = httpx.AsyncClient

    def patched(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(anomalies_client.httpx, "AsyncClient", patched)

    async def consume():
        got = 0
        with pytest.raises(anomalies_client.StreamDeadlineExceeded):
            async for _ in anomalies_client.stream_chat("r"):
                got += 1
        return got

    started = time.monotonic()
    got = asyncio.run(consume())
    assert got >= 1
    assert time.monotonic() - started < 3


@pytest.mark.req("ARCH-4")
def test_reply_size_capped(client, auth_headers, session_id, monkeypatch):
    from app import anomalies_client
    from app.config import reset_settings

    monkeypatch.setenv("CHAT_STREAM_MAX_CHARS", "10")
    reset_settings()

    async def chatty(run_id):
        for _ in range(10):
            yield "message", '{"text": "abcd"}'

    monkeypatch.setattr(anomalies_client, "stream_chat", chatty)
    url = _start_run(client, auth_headers, session_id)["stream_url"]
    events = _events(client.get(url, headers=auth_headers).text)
    assert sum(len(e["text"]) for e in events if e["type"] == "token") == 10
    assert {"type": "notice", "code": "reply_truncated"} in events


@pytest.mark.req("ARCH-5")
def test_concurrent_stream_of_same_reply_refused(client, auth_headers, session_id):
    from app import db as _db

    body = _start_run(client, auth_headers, session_id)
    _db.get_store().execute("UPDATE messages SET status='streaming' WHERE id=?", (body["message_id"],))
    r = client.get(body["stream_url"], headers=auth_headers)
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"


@pytest.mark.req("ARCH-5")
def test_restart_reconciles_orphaned_streams(client, auth_headers, session_id):
    from app import db as _db
    from app import retention

    body = _start_run(client, auth_headers, session_id)
    _db.get_store().execute("UPDATE messages SET status='streaming' WHERE id=?", (body["message_id"],))
    assert retention.reconcile_after_restart()["interrupted"] == 1
    row = _db.get_store().fetchone("SELECT status FROM messages WHERE id=?", (body["message_id"],))
    assert row["status"] == "interrupted"
    # an interrupted reply replays what it has instead of re-running
    events = _events(client.get(body["stream_url"], headers=auth_headers).text)
    assert events[0]["replay"] is True
    assert events[-1]["status"] == "interrupted"


@pytest.mark.req("ARCH-5", "INT-3")
def test_client_disconnect_marks_interrupted_and_keeps_partial(auth_headers, session_id, client,
                                                              monkeypatch):
    """Stopping a reply (closing the stream) saves what arrived as interrupted."""
    from app import anomalies_client
    from app import db as _db

    async def slow(run_id):
        yield "message", '{"text": "first "}'
        await asyncio.sleep(5)
        yield "message", '{"text": "never"}'

    monkeypatch.setattr(anomalies_client, "stream_chat", slow)
    body = _start_run(client, auth_headers, session_id)
    with client.stream("GET", body["stream_url"], headers=auth_headers) as r:
        for line in r.iter_lines():
            if '"token"' in line:
                break
    deadline = time.monotonic() + 3
    status = None
    while time.monotonic() < deadline:
        row = _db.get_store().fetchone("SELECT status, content FROM messages WHERE id=?",
                                       (body["message_id"],))
        status = row["status"]
        if status == "interrupted":
            break
        time.sleep(0.05)
    assert status == "interrupted"
    assert row["content"] == "first "
