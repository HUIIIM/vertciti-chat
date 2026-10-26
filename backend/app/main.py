# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""vertciti chat backend (codename `chat`, module id `chat`).

Dev:  uvicorn app.main:app --port 8120
Health: GET /health (no auth)
"""

from __future__ import annotations

import logging
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import anomalies_client, audit, db as _db
from . import chat_api, funnel, kill, llm, memory_api
from .auth import require_api_key
from .config import get_settings
from .errors import AppError
from .models import LLMRouteRequest
from .rate_limit import limiter

# Access log: method/path/status only. Headers (Authorization!) are never logged.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("chat")


def _trace_id() -> str:
    return uuid.uuid4().hex


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="vertciti chat", version="0.1.0-dev")

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["X-API-Key", "Authorization", "Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        trace = request.headers.get("x-request-id") or _trace_id()
        request.state.trace_id = trace
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace
        # Log path + status only; never query strings or headers.
        log.info("%s %s -> %s", request.method, request.url.path, response.status_code)
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        body = {
            "code": exc.code,
            "message": exc.message,
            "trace_id": getattr(request.state, "trace_id", _trace_id()),
        }
        if exc.detail:
            body["detail"] = exc.detail
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.warning("unhandled error on %s: %s", request.url.path, type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "internal error",
                "trace_id": getattr(request.state, "trace_id", _trace_id()),
            },
        )

    @app.get("/health")
    def health():
        anomalies_ok = anomalies_client.probe()
        llm_ready = bool(
            (settings.llm_api_key and settings.llm_base_url)
            or settings.llm_provider == "fake"
        ) and bool(settings.model_default or settings.model_quality or settings.model_cheap)
        return {
            "status": "ok",
            "module": "chat",
            # TODO(brand): 终名走品牌＋GC 确认；当前为 interim 描述性命名
            "name": "vertciti 智能助手",
            "honesty": settings.honesty,
            "components": {
                "chat_api": "🟢",
                "memory": "🟢",
                "kill_switch": "🟢",
                "llm_router": "🟢" if llm_ready else "🟡",
                # The runtime is a separate service; 🟡 here means "not reachable
                # from this dev box right now" — never presented as 🟢.
                "anomalies_runtime": "🟢" if anomalies_ok else "🟡",
            },
            "notes": [] if llm_ready else ["llm 未配置：设 CHAT_LLM_BASE_URL/CHAT_LLM_API_KEY 后切 🟢"],
        }

    @app.post("/v1/llm/route")
    def llm_route(body: LLMRouteRequest, identity: dict = Depends(require_api_key)):
        """Contract v1 §2.1. Module is bound server-side to 'chat'."""
        from .errors import ChatKilled, RateLimited

        row = _db.get_store().fetchone("SELECT killed FROM kill_state WHERE scope='module'")
        if row and row["killed"]:
            raise ChatKilled("chat module is stopped (kill switch engaged)")
        ok, retry = limiter.check_request(identity)
        if not ok:
            raise RateLimited("rate limit exceeded", retry_after=retry)
        limiter.count_request(identity)
        return llm.route(
            messages=body.messages,
            model_policy=body.model_policy,
            max_tokens=body.max_tokens,
            fallback_chain=body.fallback_chain,
            budget_units=body.budget_units,
            idempotency_key=body.idempotency_key,
            actor=identity["key_hash"],
        )

    app.include_router(chat_api.router)
    app.include_router(memory_api.router)
    app.include_router(kill.router)
    app.include_router(funnel.router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    if settings.dev_key_generated:
        print(f"[chat] dev API key (in-process only, not persisted): {settings.api_key}")
    uvicorn.run(app, host="127.0.0.1", port=8120)
