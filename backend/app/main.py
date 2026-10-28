# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""vertciti chat backend (codename `chat`, module id `chat`).

Dev:    ./backend/run.sh   (prints generated dev credentials once at startup)
Health: GET /health or /healthz (no auth; 503 when the database is unusable)
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import anomalies_client, chat_api, funnel, kill, llm, memory_api, retention
from . import db as _db
from .auth import ServicePrincipal
from .config import get_settings
from .errors import AppError
from .memory_store import check_backend
from .models import LLMRouteRequest
from .rate_limit import limiter

VERSION = "0.2.0-dev"
TRACE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
LOG_FIELDS = ("trace_id", "method", "path", "status", "duration_ms", "principal")


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Never includes headers, bodies or queries."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        for key in LOG_FIELDS:
            if hasattr(record, key):
                out[key] = getattr(record, key)
        return json.dumps(out, ensure_ascii=False)


def _configure_logging() -> logging.Logger:
    logger = logging.getLogger("chat")
    if not any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


log = _configure_logging()


def _trace_id(request: Request) -> str:
    incoming = request.headers.get("x-request-id", "")
    # Only accept a well-formed id; anything else could forge log lines.
    return incoming if TRACE_RE.match(incoming) else uuid.uuid4().hex


def _error_body(request: Request, code: str, message: str, **extra: Any) -> dict[str, Any]:
    trace = getattr(request.state, "trace_id", None) or uuid.uuid4().hex
    return {"code": code, "message": message, "trace_id": trace, **extra}


def _security_headers(response: Response, prod: bool) -> None:
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if prod:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


def _print_dev_credentials() -> None:
    settings = get_settings()
    if settings.env_name != "dev" or not settings.generated:
        return
    names = {"CHAT_API_KEY": settings.api_key, "CHAT_ADMIN_KEY": settings.admin_key}
    lines = ["[chat] dev credentials (generated for this process only, not persisted):"]
    for name in settings.generated:
        if name in names:
            lines.append(f"[chat]   {name}={names[name]}")
    lines.append("[chat]   the web page needs no key: it mints an anonymous visitor token")
    print("\n".join(lines), flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_backend()
    store = _db.get_store()
    reconciled = retention.reconcile_after_restart()
    purged = retention.purge()
    log.info("startup", extra={"principal": "system"})
    log.info(f"schema v{store.schema_version()} reconciled={reconciled} purged={purged}")
    _print_dev_credentials()
    yield


def create_app() -> FastAPI:
    settings = get_settings()  # raises ConfigError in prod when misconfigured
    app = FastAPI(
        title="vertciti chat",
        version=VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["X-API-Key", "X-Visitor-Token", "Authorization", "Content-Type",
                           "X-Request-ID"],
            expose_headers=["X-Trace-ID", "Retry-After"],
        )

    @app.middleware("http")
    async def request_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace = _trace_id(request)
        request.state.trace_id = trace
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace
        _security_headers(response, settings.is_prod)
        log.info(
            "request",
            extra={
                "trace_id": trace,
                "method": request.method,
                # path only: never query strings (stream ids) or headers (keys)
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "principal": getattr(request.state, "principal_kind", "none"),
            },
        )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        body = _error_body(request, exc.code, exc.message)
        if exc.detail:
            body["detail"] = exc.detail
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and reasons only: the offending input may be PII.
        fields = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=_error_body(request, "validation_error", "request validation failed",
                                detail={"fields": fields}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        log.warning(
            f"unhandled {type(exc).__name__}",
            extra={"trace_id": getattr(request.state, "trace_id", ""), "path": request.url.path},
        )
        return JSONResponse(status_code=500,
                            content=_error_body(request, "internal_error", "internal error"))

    def health(response: Response) -> dict[str, Any]:
        """Liveness and readiness in one: 503 unless the database can serve."""
        db_ok = True
        killed = False
        schema = None
        try:
            store = _db.get_store()
            store.ping()
            schema = store.schema_version()
            killed = kill.is_killed()
        except Exception:  # noqa: BLE001 - health must report, not raise
            db_ok = False
        anomalies_ok = anomalies_client.probe()
        llm_ready = bool(
            (settings.llm_api_key and settings.llm_base_url)
            or settings.llm_provider == "fake"
        ) and bool(settings.model_default or settings.model_quality or settings.model_cheap)
        if not db_ok:
            response.status_code = 503
        notes = []
        if not llm_ready:
            notes.append("llm not configured: set CHAT_LLM_BASE_URL/CHAT_LLM_API_KEY")
        if killed:
            notes.append("kill switch engaged: chat is stopped")
        return {
            "status": "ok" if db_ok and not killed else ("killed" if db_ok else "unavailable"),
            "module": "chat",
            "version": VERSION,
            # TODO(brand): 终名走品牌＋GC 确认；当前为 interim 描述性命名
            "name": "vertciti 智能助手",
            "honesty": settings.honesty,
            "killed": killed,
            "schema_version": schema,
            "components": {
                "database": "🟢" if db_ok else "🔴",
                "chat_api": "🟢" if db_ok and not killed else "🔴",
                "kill_switch": "🔴 engaged" if killed else "🟢 armed",
                "llm_router": "🟢" if llm_ready else "🟡",
                # 🟡 means "not reachable from here right now" — never shown as 🟢.
                "anomalies_runtime": "🟢" if anomalies_ok else "🟡",
            },
            "notes": notes,
        }

    app.add_api_route("/health", health, methods=["GET"])
    app.add_api_route("/healthz", health, methods=["GET"], include_in_schema=False)

    @app.post("/v1/llm/route")
    def llm_route(body: LLMRouteRequest, principal: ServicePrincipal) -> dict:
        """Contract v1 §2.1. Module is bound server-side to 'chat'."""
        kill.check_not_killed()
        limiter.enforce(principal)
        return llm.route(
            messages=body.messages,
            model_policy=body.model_policy,
            max_tokens=body.max_tokens,
            fallback_chain=body.fallback_chain,
            budget_units=body.budget_units,
            idempotency_key=body.idempotency_key,
            actor=principal.subject,
        )

    app.include_router(chat_api.visitor_router)
    app.include_router(chat_api.router)
    app.include_router(memory_api.router)
    app.include_router(kill.router)
    app.include_router(funnel.router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8120, access_log=False)
