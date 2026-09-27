# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Chat session API (P0). SSE from day one — the stream endpoint is the primary
interaction surface; the non-streaming message call is a convenience wrapper.

Flow:
  POST /v1/chat/sessions -> session_id
  POST /v1/chat/sessions/{id}/messages {content, stream:false} -> full reply
  POST /v1/chat/sessions/{id}/messages {content, stream:true}  -> {message_id, stream_url}
  GET  /v1/chat/sessions/{id}/stream?message_id=...            -> SSE token events

The assistant brain is the anomalies clean-room runtime, reached over HTTP
only (M1). If it is unreachable we answer honestly (🟡 + error event) — we
never fabricate a reply.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from . import anomalies_client, audit, db as _db
from .auth import require_api_key
from .config import get_settings
from .errors import (
    ChatKilled,
    NotFound,
    QuotaExceeded,
    RateLimited,
    ServiceUnavailable,
)
from .models import CreateSessionRequest, SendMessageRequest
from .rate_limit import limiter

router = APIRouter(prefix="/v1/chat", tags=["chat"])

HISTORY_LIMIT = 20


def _new_id() -> str:
    return uuid.uuid4().hex


def _honesty() -> str:
    return get_settings().honesty


def _check_not_killed() -> None:
    row = _db.get_store().fetchone("SELECT killed FROM kill_state WHERE scope='module'")
    if row and row["killed"]:
        raise ChatKilled("chat module is stopped (kill switch engaged)")


def _get_session_or_404(session_id: str) -> dict:
    row = _db.get_store().fetchone("SELECT id, title, created_at FROM sessions WHERE id=?", (session_id,))
    if not row:
        raise NotFound(f"session {session_id} not found")
    return dict(row)


def _history(session_id: str) -> list[dict]:
    rows = _db.get_store().fetchall(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
        (session_id, HISTORY_LIMIT),
    )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def _save_message(session_id, role, content, *, run_id=None, cards=None,
                  tokens_in=0, tokens_out=0, cost_cents=0, idempotency_key=None) -> str:
    mid = _new_id()
    _db.get_store().execute(
        """INSERT INTO messages(id, session_id, role, content, run_id, cards_json,
                                tokens_in, tokens_out, cost_cents, idempotency_key, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, session_id, role, content, run_id, _db.dumps(cards or []),
         tokens_in, tokens_out, cost_cents, idempotency_key, _db.utcnow()),
    )
    return mid


def _record_event(etype: str, session_id: str | None, detail: dict | None = None) -> None:
    _db.get_store().execute(
        "INSERT INTO events(ts, type, session_id, detail_json) VALUES(?,?,?,?)",
        (_db.utcnow(), etype, session_id, _db.dumps(detail or {})),
    )


@router.post("/sessions")
def create_session(body: CreateSessionRequest, identity: dict = Depends(require_api_key)):
    ok, retry = limiter.check_request(identity)
    if not ok:
        raise RateLimited("rate limit exceeded", retry_after=retry)
    limiter.count_request(identity)
    sid = _new_id()
    _db.get_store().execute(
        "INSERT INTO sessions(id, title, created_at) VALUES(?,?,?)",
        (sid, body.title or "新的对话", _db.utcnow()),
    )
    _record_event("session_created", sid, {"title": body.title})
    return {"session_id": sid, "created_at": _db.utcnow(), "honesty": _honesty()}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, identity: dict = Depends(require_api_key)):
    s = _get_session_or_404(session_id)
    rows = _db.get_store().fetchall(
        "SELECT id, role, content, run_id, cards_json, cost_cents, created_at "
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
            }
            for r in rows
        ],
        "honesty": _honesty(),
    }


@router.get("/sessions/{session_id}/cost")
def session_cost(session_id: str, identity: dict = Depends(require_api_key)):
    _get_session_or_404(session_id)
    row = _db.get_store().fetchone(
        "SELECT COUNT(*) n, COALESCE(SUM(tokens_in),0) ti, COALESCE(SUM(tokens_out),0) to_, "
        "COALESCE(SUM(cost_cents),0) c FROM messages WHERE session_id=? AND role='assistant'",
        (session_id,),
    )
    return {
        "session_id": session_id,
        "assistant_messages": row["n"],
        "tokens_in": row["ti"],
        "tokens_out": row["to_"],
        "cost_cents": row["c"],
        "honesty": _honesty(),
    }


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, body: SendMessageRequest, identity: dict = Depends(require_api_key)):
    _check_not_killed()
    _get_session_or_404(session_id)

    ok, retry = limiter.check_request(identity)
    if not ok:
        raise RateLimited("rate limit exceeded", retry_after=retry)
    limiter.count_request(identity)
    allowed, _remaining = limiter.check_message_quota(identity)
    if not allowed:
        raise QuotaExceeded("daily message quota exceeded", retry_after=86400)

    # Idempotency: repeats return the identical stored response.
    if body.idempotency_key:
        hit = _db.get_store().fetchone(
            "SELECT response_json FROM idempotency WHERE key=?", (body.idempotency_key,))
        if hit:
            return json.loads(hit["response_json"])

    limiter.count_message(identity)
    user_mid = _save_message(session_id, "user", body.content, idempotency_key=body.idempotency_key)
    history = _history(session_id)

    try:
        result = anomalies_client.post_chat(body.content, history)
    except anomalies_client.AnomaliesUnavailable as e:
        _record_event("agent_unavailable", session_id, {"error": str(e)[:200]})
        raise ServiceUnavailable(
            "智能体运行时暂不可用（dev 过渡态），请稍后重试 — 未生成任何虚假回复"
        ) from e

    reply = result.get("reply", "")
    run_id = result.get("run_id")
    cards = result.get("cards", [])

    if body.stream:
        # The inline reply (chit-chat path) is stored now; the stream endpoint
        # emits it as tokens. Agent-run tokens (run_id set) accumulate live.
        assistant_mid = _save_message(session_id, "assistant", reply, run_id=run_id, cards=cards)
        response = {
            "message_id": assistant_mid,
            "stream_url": f"/v1/chat/sessions/{session_id}/stream?message_id={assistant_mid}",
            "run_id": run_id,
            "cards": cards,
            "honesty": _honesty(),
        }
    else:
        assistant_mid = _save_message(session_id, "assistant", reply, run_id=run_id, cards=cards)
        response = {
            "message_id": assistant_mid,
            "reply": reply,
            "run_id": run_id,
            "cards": cards,
            "honesty": _honesty(),
        }
    _record_event("message_sent", session_id,
                  {"message_id": assistant_mid, "stream": body.stream, "run_id": run_id})
    if body.idempotency_key:
        _db.get_store().execute(
            "INSERT OR IGNORE INTO idempotency(key, endpoint, response_json, created_at) VALUES(?,?,?,?)",
            (body.idempotency_key, "chat.messages", _db.dumps(response), _db.utcnow()),
        )
    return response


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    message_id: str = Query(...),
    identity: dict = Depends(require_api_key),
):
    _check_not_killed()
    _get_session_or_404(session_id)
    row = _db.get_store().fetchone(
        "SELECT run_id FROM messages WHERE id=? AND session_id=?", (message_id, session_id))
    if not row:
        raise NotFound("message not found")
    run_id = row["run_id"]

    async def gen() -> AsyncIterator[str]:
        yield _sse_event({"type": "meta", "message_id": message_id,
                          "honesty": _honesty(), "run_id": run_id})
        full_text = ""
        try:
            if run_id:
                for event, data in anomalies_client.stream_chat(run_id):
                    text = _extract_text(data)
                    if text:
                        full_text += text
                        yield _sse_event({"type": "token", "text": text})
                    else:
                        yield _sse_event({"type": "agent", "event": event, "payload": data[:4000]})
            else:
                # Chit-chat / clarify path: the runtime answered inline on POST.
                prev = _db.get_store().fetchone(
                    "SELECT content FROM messages WHERE id=?", (message_id,))
                if prev and prev["content"]:
                    full_text = prev["content"]
                    yield _sse_event({"type": "token", "text": full_text})
        except anomalies_client.AnomaliesUnavailable as e:
            yield _sse_event({"type": "error", "code": "agent_unavailable",
                              "message": f"智能体运行时暂不可用（dev 过渡态）: {e}"})
        if full_text:
            _db.get_store().execute(
                "UPDATE messages SET content=? WHERE id=?", (full_text, message_id))
        yield _sse_event({"type": "done", "message_id": message_id,
                          "chars": len(full_text), "honesty": _honesty()})

    return StreamingResponse(gen(), media_type="text/event-stream",
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
