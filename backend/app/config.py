# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Central configuration, read from environment only.

Security rule (contract v1 §2.1): API keys live in process memory or arrive via
the surrogate mechanism. They are NEVER written to disk, never enter logs, and
never enter build artifacts. This module is the only place that touches them.
"""

from __future__ import annotations

import json
import os
import secrets


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


class Settings:
    """Process-lifetime settings. Construct once via get_settings()."""

    def __init__(self) -> None:
        self.env_name: str = _env("CHAT_ENV", "dev")

        # --- auth ---
        self.api_key: str = os.environ.get("CHAT_API_KEY", "")
        self.dev_key_generated: bool = False
        if not self.api_key:
            # Dev convenience only: an ephemeral in-process key. It is printed
            # once to stdout at startup and never persisted.
            self.api_key = secrets.token_urlsafe(24)
            self.dev_key_generated = True

        # --- storage ---
        self.db_path: str = _env("CHAT_DB_PATH", "")

        # --- anomalies runtime HTTP integration (M1: HTTP only, no imports) ---
        self.anomalies_base_url: str = _env("ANOMALIES_BASE_URL", "http://127.0.0.1:8100")
        self.anomalies_api_key: str = os.environ.get("ANOMALIES_API_KEY", "")

        # --- LLM routing: model ids are NEVER hardcoded; policy -> env mapping ---
        self.model_default: str = _env("CHAT_MODEL_DEFAULT", "")
        self.model_quality: str = _env("CHAT_MODEL_QUALITY", "")
        self.model_cheap: str = _env("CHAT_MODEL_CHEAP", "")
        self.llm_base_url: str = _env("CHAT_LLM_BASE_URL", "")
        self.llm_api_key: str = os.environ.get("CHAT_LLM_API_KEY", "")
        self.llm_provider: str = _env("CHAT_LLM_PROVIDER", "openai_compat")  # or "fake" (tests)

        # --- cost accounting: cents (integer minor units) per 1M tokens ---
        self.price_table: dict = {}
        raw = _env("CHAT_PRICE_TABLE", "")
        if raw:
            try:
                self.price_table = json.loads(raw)
            except json.JSONDecodeError:
                self.price_table = {}

        # --- rate limits (E6: free-tier survival line) ---
        self.rate_per_minute: int = _env_int("CHAT_RATE_PER_MINUTE", 60)
        self.daily_message_limit: int = _env_int("CHAT_DAILY_MESSAGE_LIMIT", 200)

        # --- CORS: deny cross-origin by default, allowlist via env ---
        self.cors_origins: list[str] = [
            o.strip() for o in _env("CHAT_CORS_ORIGINS", "").split(",") if o.strip()
        ]

        # --- honesty label: only 🟢 when prod AND llm actually configured ---
        llm_ready = bool(self.llm_api_key and self.llm_base_url) or self.llm_provider == "fake"
        self.honesty: str = "🟢" if (self.env_name == "prod" and llm_ready) else "🟡"


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
