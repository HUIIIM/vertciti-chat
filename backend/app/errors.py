# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Contract-shaped application errors. All error bodies are
{code, message, trace_id}; 429 responses carry a `retry-after` header."""

from __future__ import annotations


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str = "", *, retry_after: int | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message or self.code
        self.retry_after = retry_after
        self.detail = detail or {}


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class QuotaExceeded(AppError):
    status_code = 429
    code = "quota_exceeded"


class BudgetExceeded(AppError):
    status_code = 402
    code = "budget_exceeded"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


class ChatKilled(AppError):
    status_code = 503
    code = "chat_killed"


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"
