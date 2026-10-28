# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Chat session API (P0). SSE from day one — the stream endpoint is the primary
interaction surface; the non-streaming message call is a convenience wrapper.

Flow:
  POST   /v1/visitor                                   -> anonymous visitor token (no signup)
  POST   /v1/chat/sessions                             -> session_id (owned by the caller)
  GET    /v1/chat/sessions                             -> the caller's own sessions
  GET    /v1/chat/sessions/{id}                        -> one owned session with messages
  DELETE /v1/chat/sessions/{id}                        -> erase it (messages and events)
  POST   /v1/chat/sessions/{id}/messages {stream:false} -> full reply
  POST   /v1/chat/sessions/{id}/messages {stream:true}  -> {message_id, stream_url}
  GET    /v1/chat/sessions/{id}/stream?message_id=...   -> SSE token events
  GET    /v1/usage                                     -> today's quota for the caller

Ownership: every session belongs to the principal that created it. Anyone
else gets 404 (not 403), so session ids cannot be probed.

Assistant message lifecycle (`messages.status`):
  pending -> streaming -> done | error | interrupted
A finished message is replayed from storage; the runtime is called at most
once per message. Restarts mark orphaned `streaming` rows `interrupted`.

The assistant brain is the anomalies clean-room runtime, reached over HTTP
only (M1). If it is unreachable we answer honestly (🟡 + error event) — we
never fabricate a reply.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from . import anomalies_client, audit, retention
from . import db as _db
from .auth import ChatPrincipal, Principal, client_ip_hash, mint_visitor_token
from .config import get_settings
from .errors import Conflict, NotFound, RateLimited, ServiceUnavailable
from .events import record_event
from .kill import check_not_killed
from .models import CreateSessionRequest, SendMessageRequest
from .rate_limit import limiter

router = APIRouter(prefix="/v1/chat", tags=["chat"])
visitor_router = APIRouter(tags=["visitor"])

HISTORY_LIMIT = 20  # messages; the character budget below is the binding limit
FINAL_STATUSES = ("done", "error", "interrupted")


def _new_id() -> str:
    return uuid.uuid4().hex


def _honesty() -> str:
    return get_settings().honesty


def scoped_idempotency_key(endpoint: str, subject: str, scope: str, key: str) -> str:
    """Idempotency keys are only meaningful inside (endpoint, caller, scope):
    the same client key in another session or from another caller is a new
    request, never a replay of someone else's response."""
    raw = "\x1f".join((endpoint, subject, scope, key))
    return hashlib.sha256(raw.encode()).hexdigest()


def get_owned_session(session_id: str, principal: Principal) -> dict[str, Any]:
    row = _db.get_store().fetchone(
        "SELECT id, title, created_at FROM sessions WHERE id=? AND owner=?",
        (session_id, principal.subject),
    )
    if not row:
        raise NotFound("session not found")
    return dict(row)


def _history(session_id: str) -> list[dict]:
    """Recent turns, newest first until the character budget is spent."""
    budget = get_settings().history_max_chars
    rows = _db.get_store().fetchall(
        "SELECT role, content FROM messages WHERE session_id=? AND content != '' "
        "ORDER BY created_at DESC LIMIT ?",
        (session_id, HISTORY_LIMIT),
    )
    picked: list[dict] = []
    used = 0
    for r in rows:
        size = len(r["content"])
        if used + size > budget:
            break
        picked.append({"role": r["role"], "content": r["content"]})
        used += size
    return list(reversed(picked))


def _save_message(session_id: str, role: str, content: str, *, run_id: str | None = None,
                  cards: list | None = None, status: str = "done",
                  idempotency_key: str | None = None) -> str:
    mid = _new_id()
    _db.get_store().execute(
        """INSERT INTO messages(id, session_id, role, content, run_id, cards_json,
                                tokens_in, tokens_out, cost_cents, idempotency_key, created_at, status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, session_id, role, content, run_id, _db.dumps(cards or []),
         0, 0, 0, idempotency_key, _db.utcnow(), status),
    )
    return mid


def _session_cost(session_id: str) -> dict[str, int]:
    row = _db.get_store().fetchone(
        "SELECT COUNT(*) n, COALESCE(SUM(tokens_in),0) ti, COALESCE(SUM(tokens_out),0) to_, "
        "COALESCE(SUM(cost_cents),0) c FROM messages WHERE session_id=? AND role='assistant'",
        (session_id,),
    )
    assert row is not None
    return {"assistant_messages": row["n"], "tokens_in": row["ti"],
            "tokens_out": row["to_"], "cost_cents": row["c"]}


# --- visitor tokens -------------------------------------------------------------

@visitor_router.post("/v1/visitor")
def create_visitor(request: Request) -> dict:
    """Anonymous visitor token: free, no signup, rate limited per IP."""
    check_not_killed()
    iph = client_ip_hash(request)
    ok, retry = limiter.check_mint(iph)
    if not ok:
        raise RateLimited("too many new visitors from this address", retry_after=retry)
    token = mint_visitor_token()
    settings = get_settings()
    return {**token, "daily_message_limit": settings.visitor_daily_message_limit,
            "retention_days": settings.retention_days, "honesty": _honesty()}


@visitor_router.get("/v1/usage")
def usage(principal: ChatPrincipal) -> dict:
    return {**limiter.usage(principal), "retention_days": get_settings().retention_days,
            "honesty": _honesty()}


# --- sessions -------------------------------------------------------------------

@router.post("/sessions")
def create_session(body: CreateSessionRequest, principal: ChatPrincipal) -> dict:
    check_not_killed()
    limiter.enforce(principal)
    retention.maybe_purge()
    sid = _new_id()
    created = _db.utcnow()
    _db.get_store().execute(
        "INSERT INTO sessions(id, title, created_at, owner) VALUES(?,?,?,?)",
        (sid, body.title, created, principal.subject),
    )
    record_event("session_created", sid, {"has_title": bool(body.title)}, subject=principal.subject)
    return {"session_id": sid, "created_at": created, "honesty": _honesty()}


@router.get("/sessions")
def list_sessions(principal: ChatPrincipal, limit: int = Query(default=20, ge=1, le=100)) -> dict:
    rows = _db.get_store().fetchall(
        "SELECT s.id, s.title, s.created_at, "
        "(SELECT content FROM messages m WHERE m.session_id=s.id AND m.role='user' "
        " ORDER BY m.created_at LIMIT 1) first_user "
        "FROM sessions s WHERE s.owner=? ORDER BY s.created_at DESC LIMIT ?",
        (principal.subject, limit),
    )
    return {
        "sessions": [
            {"id": r["id"], "title": r["title"] or (r["first_user"] or "")[:60],
             "created_at": r["created_at"]}
            for r in rows
        ],
        "honesty": _honesty(),
    }


@router.get("/sessions/{session_id}")
def get_session(session_id: str, principal: ChatPrincipal) -> dict:
    s = get_owned_session(session_id, principal)
    rows = _db.get_store().fetchall(
        "SELECT id, role, content, run_id, cards_json, cost_cents, created_at, status "
        "FROM messages WHERE session_id=? ORDER BY created_at",
        (session_id,),
    )
    return {
        **s,
        "messages": [
            {
                "id": r["id"], "role": r["role"], "content": r["content"],
                "run_id": r["run_id"], "cards": json.loads(r["cards_json"] or "[]"),
                "cost_cents": r["cost_cents"], "created_at": r["created_at"],
                "status": r["status"],
            }
            for r in rows
        ],
        "honesty": _honesty(),
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, principal: ChatPrincipal) -> dict:
    """Erase a conversation: its messages, its events and the session row."""
    get_owned_session(session_id, principal)

    def erase(conn: sqlite3.Connection) -> int:
        n = conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,)).rowcount
        conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return n

    removed = _db.get_store().atomic(erase)
    audit.record("chat.session_deleted", principal.subject, {"messages": removed})
    return {"deleted": True, "messages_deleted": removed, "honesty": _honesty()}


@router.get("/sessions/{session_id}/cost")
def session_cost(session_id: str, principal: ChatPrincipal) -> dict:
    get_owned_session(session_id, principal)
    return {"session_id": session_id, **_session_cost(session_id), "honesty": _honesty()}


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, body: SendMessageRequest, principal: ChatPrincipal) -> dict:
    check_not_killed()
    get_owned_session(session_id, principal)
    limiter.enforce(principal)

    idem = None
    if body.idempotency_key:
        idem = scoped_idempotency_key("chat.messages", principal.subject, session_id,
                                      body.idempotency_key)
        hit = _db.get_store().fetchone("SELECT response_json FROM idempotency WHERE key=?", (idem,))
        if hit:
            return json.loads(hit["response_json"])

    remaining = limiter.consume_message(principal)
    _save_message(session_id, "user", body.content, idempotency_key=idem)
    history = _history(session_id)  # includes this turn, as the runtime contract expects

    try:
        result = anomalies_client.post_chat(body.content, history)
    except anomalies_client.AnomaliesUnavailable as e:
        record_event("agent_unavailable", session_id, {"error": type(e).__name__},
                     subject=principal.subject)
        raise ServiceUnavailable(
            "agent runtime unavailable; no reply was generated",
            detail={"reason": "agent_unavailable"},
        ) from e

    reply = result["reply"]
    run_id = result["run_id"]
    cards = result["cards"]
    # A run streams later; an inline reply is final now.
    status = "pending" if run_id else "done"
    assistant_mid = _save_message(session_id, "assistant", reply, run_id=run_id, cards=cards,
                                  status=status)
    response: dict[str, Any] = {
        "message_id": assistant_mid,
        "run_id": run_id,
        "cards": cards,
        "remaining_today": remaining,
        "honesty": _honesty(),
    }
    if body.stream:
        response["stream_url"] = f"/v1/chat/sessions/{session_id}/stream?message_id={assistant_mid}"
    else:
        response["reply"] = reply
    record_event("message_sent", session_id,
                 {"message_id": assistant_mid, "stream": body.stream, "run": bool(run_id)},
                 subject=principal.subject)
    if idem:
        _db.get_store().execute(
            "INSERT OR IGNORE INTO idempotency(key, endpoint, response_json, created_at) VALUES(?,?,?,?)",
            (idem, "chat.messages", _db.dumps(response), _db.utcnow()),
        )
    return response


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _claim_for_stream(message_id: str, session_id: str) -> dict[str, Any]:
    """Atomically decide whether this request runs the stream or replays it."""
    def txn(conn: sqlite3.Connection) -> dict[str, Any]:
        row = conn.execute(
            "SELECT run_id, content, status FROM messages WHERE id=? AND session_id=? AND role='assistant'",
            (message_id, session_id),
        ).fetchone()
        if not row:
            raise NotFound("message not found")
        if row["status"] == "streaming":
            raise Conflict("this reply is already streaming")
        if row["status"] == "pending" and row["run_id"]:
            conn.execute("UPDATE messages SET status='streaming' WHERE id=?", (message_id,))
            return {"mode": "live", "run_id": row["run_id"]}
        return {"mode": "replay", "run_id": row["run_id"], "content": row["content"],
                "status": row["status"] if row["status"] in FINAL_STATUSES else "done"}

    return _db.get_store().atomic(txn)


def _finish(message_id: str, content: str, status: str) -> None:
    _db.get_store().execute(
        "UPDATE messages SET content=?, status=? WHERE id=?", (content, status, message_id))


def _done_payload(principal: Principal, session_id: str, message_id: str, chars: int,
                  status: str) -> dict[str, Any]:
    return {"type": "done", "message_id": message_id, "chars": chars, "status": status,
            "session_cost_cents": _session_cost(session_id)["cost_cents"],
            "remaining_today": limiter.usage(principal)["remaining"],
            "honesty": _honesty()}


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    principal: ChatPrincipal,
    message_id: str = Query(..., max_length=64),
) -> StreamingResponse:
    get_owned_session(session_id, principal)
    claim = _claim_for_stream(message_id, session_id)
    if claim["mode"] == "live":
        try:
            check_not_killed()
        except Exception:
            _finish(message_id, "", "interrupted")
            raise
    settings = get_settings()

    async def replay() -> AsyncIterator[str]:
        yield _sse_event({"type": "meta", "message_id": message_id, "honesty": _honesty(),
                          "run_id": claim["run_id"], "replay": True})
        if claim["content"]:
            yield _sse_event({"type": "token", "text": claim["content"]})
        yield _sse_event(_done_payload(principal, session_id, message_id,
                                       len(claim["content"]), claim["status"]))

    async def live() -> AsyncIterator[str]:
        full_text = ""
        status = "interrupted"  # unless we reach a normal end, the client went away
        try:
            yield _sse_event({"type": "meta", "message_id": message_id, "honesty": _honesty(),
                              "run_id": claim["run_id"], "replay": False})
            try:
                async for event, data in anomalies_client.stream_chat(claim["run_id"]):
                    text = _extract_text(data)
                    if text:
                        room = settings.stream_max_chars - len(full_text)
                        if room <= 0:
                            yield _sse_event({"type": "notice", "code": "reply_truncated"})
                            break
                        text = text[:room]
                        full_text += text
                        yield _sse_event({"type": "token", "text": text})
                    else:
                        # Runtime internals are untrusted: forward the event name only.
                        yield _sse_event({"type": "agent", "event": event[:64]})
                status = "done"
            except anomalies_client.StreamDeadlineExceeded:
                status = "error"
                yield _sse_event({"type": "error", "code": "stream_deadline",
                                  "message": "the reply took too long and was stopped"})
            except anomalies_client.AnomaliesUnavailable:
                status = "error"
                yield _sse_event({"type": "error", "code": "agent_unavailable",
                                  "message": "agent runtime unavailable"})
            yield _sse_event(_done_payload(principal, session_id, message_id, len(full_text), status))
        finally:
            _finish(message_id, full_text, status)

    return StreamingResponse(live() if claim["mode"] == "live" else replay(),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _extract_text(data: str) -> str:
    """Best-effort token extraction from the runtime's SSE payloads."""
    try:
        obj = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for k in ("text", "delta", "content", "token"):
            v = obj.get(k)
            if isinstance(v, str) and v:
                return v
    return ""
