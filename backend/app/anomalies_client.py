# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""HTTP integration with the anomalies clean-room agent runtime (M1:
HTTP product-surface calls only — no imports, no shared packages, no shared
database, no shared secrets with that codebase).

Endpoints used: POST /api/v1/chat (send message) and
GET /api/v1/chat/stream?run_id= (SSE). All failures surface as
AnomaliesUnavailable so callers can answer honestly (🟡) instead of faking.
"""

from __future__ import annotations

import json
from typing import Iterator

import httpx

from .config import get_settings


# NOTE: all httpx clients here use trust_env=False. The runtime is a local /
# intranet service; its traffic (including the Bearer key) must never be routed
# through an egress proxy, and localhost must never depend on no_proxy config.
class AnomaliesUnavailable(Exception):
    """The runtime is not reachable or not configured. Callers must be honest."""


def _headers() -> dict:
    settings = get_settings()
    headers = {"Content-Type": "application/json"}
    if settings.anomalies_api_key:
        headers["Authorization"] = f"Bearer {settings.anomalies_api_key}"
    return headers


def post_chat(message: str, history: list[dict] | None = None) -> dict:
    """POST /api/v1/chat -> {run_id, reply, cards}. Never raises httpx errors."""
    settings = get_settings()
    body = {"message": message, "history": history or []}
    try:
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            resp = client.post(
                f"{settings.anomalies_base_url}/api/v1/chat",
                headers=_headers(),
                json=body,
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
        raise AnomaliesUnavailable(f"runtime unreachable at {settings.anomalies_base_url}: {e}") from e
    if resp.status_code >= 500:
        raise AnomaliesUnavailable(f"runtime error {resp.status_code}")
    if resp.status_code == 401:
        raise AnomaliesUnavailable("runtime rejected our key (401)")
    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise AnomaliesUnavailable("runtime returned non-JSON") from e
    return {
        "run_id": data.get("run_id"),
        "reply": data.get("reply", ""),
        "cards": data.get("cards", []),
    }


def stream_chat(run_id: str) -> Iterator[tuple[str, str]]:
    """GET /api/v1/chat/stream?run_id= -> yields (event, data) SSE tuples."""
    settings = get_settings()
    try:
        with httpx.Client(timeout=None, trust_env=False) as client:
            with client.stream(
                "GET",
                f"{settings.anomalies_base_url}/api/v1/chat/stream",
                headers=_headers(),
                params={"run_id": run_id},
                timeout=120.0,
            ) as resp:
                if resp.status_code >= 400:
                    raise AnomaliesUnavailable(f"stream rejected: {resp.status_code}")
                event = "message"
                data_lines: list[str] = []
                for line in resp.iter_lines():
                    if not line:
                        if data_lines:
                            yield event, "\n".join(data_lines)
                        event, data_lines = "message", []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                if data_lines:
                    yield event, "\n".join(data_lines)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
        raise AnomaliesUnavailable(f"stream unreachable: {e}") from e


def probe() -> bool:
    """Cheap liveness probe for the honesty badge. Never raises."""
    settings = get_settings()
    try:
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            resp = client.get(f"{settings.anomalies_base_url}/api/v1/health")
            return resp.status_code < 500
    except Exception:
        return False
