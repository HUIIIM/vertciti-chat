# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Central configuration, read from environment only.

Security rule (contract v1 §2.1): API keys live in process memory or arrive via
the surrogate mechanism. They are NEVER written to disk, never enter logs, and
never enter build artifacts. This module is the only place that touches them.

Three credentials, three principals (see auth.py):

- CHAT_API_KEY        service key: trusted backends (memory, LLM route, chat).
- CHAT_ADMIN_KEY      operator key: kill switch, audit, metrics. Never given to
                      browsers or other modules.
- CHAT_VISITOR_SECRET HMAC secret that signs anonymous visitor tokens, so the
                      public page needs no shared key at all.

In `dev`/`test` any missing value is generated once per process (and printed at
startup in dev so the README quick start works). In `prod` all three are
required and startup fails without them: production never runs in dev mode.
"""

from __future__ import annotations

import json
import os
import secrets

ENVIRONMENTS = ("dev", "test", "prod")
DEV_FRONTEND_ORIGINS = ["http://127.0.0.1:3120", "http://localhost:3120"]


class ConfigError(RuntimeError):
    """Raised when the process must not start with the given environment."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


class Settings:
    """Process-lifetime settings. Construct once via get_settings()."""

    def __init__(self) -> None:
        self.env_name: str = _env("CHAT_ENV", "dev")
        if self.env_name not in ENVIRONMENTS:
            raise ConfigError(f"CHAT_ENV must be one of {ENVIRONMENTS}, got {self.env_name!r}")
        self.is_prod: bool = self.env_name == "prod"

        # --- credentials (generated only outside prod) ---
        self.generated: list[str] = []
        self.api_key: str = self._secret("CHAT_API_KEY", 24)
        self.admin_key: str = self._secret("CHAT_ADMIN_KEY", 24)
        self.visitor_secret: str = self._secret("CHAT_VISITOR_SECRET", 32)
        # kept for backwards compatibility with callers that check the flag
        self.dev_key_generated: bool = "CHAT_API_KEY" in self.generated

        # --- storage ---
        self.db_path: str = _env("CHAT_DB_PATH", "")
        self.retention_days: int = _env_int("CHAT_RETENTION_DAYS", 30, minimum=1)

        # --- anomalies runtime HTTP integration (M1: HTTP only, no imports) ---
        self.anomalies_base_url: str = _env("ANOMALIES_BASE_URL", "http://127.0.0.1:8100")
        self.anomalies_api_key: str = os.environ.get("ANOMALIES_API_KEY", "")
        # Hard upper bounds for one assistant turn (JPL-style loop bounds).
        self.stream_max_seconds: int = _env_int("CHAT_STREAM_MAX_SECONDS", 120, minimum=1)
        self.stream_idle_seconds: int = _env_int("CHAT_STREAM_IDLE_SECONDS", 30, minimum=1)
        self.stream_max_chars: int = _env_int("CHAT_STREAM_MAX_CHARS", 60000, minimum=1)
        self.history_max_chars: int = _env_int("CHAT_HISTORY_MAX_CHARS", 16000, minimum=0)

        # --- LLM routing: model ids are NEVER hardcoded; policy -> env mapping ---
        self.model_default: str = _env("CHAT_MODEL_DEFAULT", "")
        self.model_quality: str = _env("CHAT_MODEL_QUALITY", "")
        self.model_cheap: str = _env("CHAT_MODEL_CHEAP", "")
        self.llm_base_url: str = _env("CHAT_LLM_BASE_URL", "")
        self.llm_api_key: str = os.environ.get("CHAT_LLM_API_KEY", "")
        self.llm_provider: str = _env("CHAT_LLM_PROVIDER", "openai_compat")  # or "fake" (tests)
        self.llm_max_tokens_default: int = _env_int("CHAT_LLM_MAX_TOKENS", 1024, minimum=1)
        self.llm_max_tokens_cap: int = _env_int("CHAT_LLM_MAX_TOKENS_CAP", 4096, minimum=1)

        # --- cost accounting: cents (integer minor units) per 1M tokens ---
        self.price_table: dict = {}
        raw = _env("CHAT_PRICE_TABLE", "")
        if raw:
            try:
                parsed = json.loads(raw)
                self.price_table = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                self.price_table = {}

        # --- rate limits (E6: free-tier survival line) ---
        self.rate_per_minute: int = _env_int("CHAT_RATE_PER_MINUTE", 60, minimum=1)
        self.ip_rate_per_minute: int = _env_int("CHAT_IP_RATE_PER_MINUTE", 120, minimum=1)
        # Service principals (trusted backends) share one daily quota.
        self.daily_message_limit: int = _env_int("CHAT_DAILY_MESSAGE_LIMIT", 200, minimum=0)
        # Anonymous visitors: per visitor, plus a per-IP ceiling across visitors.
        self.visitor_daily_message_limit: int = _env_int("CHAT_VISITOR_DAILY_MESSAGE_LIMIT", 50, minimum=0)
        self.ip_daily_message_limit: int = _env_int("CHAT_IP_DAILY_MESSAGE_LIMIT", 200, minimum=0)
        self.visitor_mint_per_hour: int = _env_int("CHAT_VISITOR_MINT_PER_HOUR", 20, minimum=1)
        self.visitor_token_ttl_hours: int = _env_int("CHAT_VISITOR_TOKEN_TTL_HOURS", 168, minimum=1)

        # --- CORS: explicit allowlist; dev defaults to the local frontend only ---
        origins = [o.strip() for o in _env("CHAT_CORS_ORIGINS", "").split(",") if o.strip()]
        if not origins and self.env_name == "dev":
            origins = list(DEV_FRONTEND_ORIGINS)
        self.cors_origins: list[str] = origins

        # --- API docs are a dev convenience; never served in prod ---
        self.docs_enabled: bool = not self.is_prod

        # --- honesty label: only 🟢 when prod AND llm actually configured ---
        llm_ready = bool(self.llm_api_key and self.llm_base_url) or self.llm_provider == "fake"
        self.honesty: str = "🟢" if (self.is_prod and llm_ready) else "🟡"

        if self.is_prod:
            self._check_prod()

    def _secret(self, name: str, nbytes: int) -> str:
        value = os.environ.get(name, "")
        if value:
            return value
        if self.env_name == "prod":
            return ""  # _check_prod reports it; never invent prod credentials
        self.generated.append(name)
        return secrets.token_urlsafe(nbytes)

    def _check_prod(self) -> None:
        problems = []
        for name, value in (
            ("CHAT_API_KEY", self.api_key),
            ("CHAT_ADMIN_KEY", self.admin_key),
            ("CHAT_VISITOR_SECRET", self.visitor_secret),
        ):
            if len(value) < 24:
                problems.append(f"{name} must be set (>= 24 characters)")
        if self.api_key and self.api_key == self.admin_key:
            problems.append("CHAT_ADMIN_KEY must differ from CHAT_API_KEY")
        if not self.cors_origins:
            problems.append("CHAT_CORS_ORIGINS must list the production frontend origin(s)")
        if not self.db_path:
            problems.append("CHAT_DB_PATH must point at the persistent volume")
        if problems:
            raise ConfigError("refusing to start in prod: " + "; ".join(problems))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test hook: drop the cached instance so env changes take effect."""
    global _settings
    _settings = None
