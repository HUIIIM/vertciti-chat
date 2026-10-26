# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Shared pytest fixtures. The anomalies runtime is stubbed at the HTTP-client
boundary (monkeypatched functions) — never imported, per M1."""

import os
import sys

import pytest

TEST_KEY = "test-key-123"

os.environ["CHAT_ENV"] = "test"
os.environ["CHAT_API_KEY"] = TEST_KEY
os.environ["CHAT_LLM_PROVIDER"] = "fake"
os.environ["CHAT_MODEL_DEFAULT"] = "fake-default"
os.environ["CHAT_MODEL_QUALITY"] = "fake-quality"
os.environ["CHAT_MODEL_CHEAP"] = "fake-cheap"
os.environ["CHAT_PRICE_TABLE"] = (
    '{"default":{"in":100,"out":300},"quality":{"in":500,"out":1500},"cheap":{"in":20,"out":60}}'
)
os.environ["CHAT_RATE_PER_MINUTE"] = "1000"
os.environ["CHAT_DAILY_MESSAGE_LIMIT"] = "1000"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import anomalies_client, db as _db  # noqa: E402
from app.config import reset_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.rate_limit import limiter  # noqa: E402


def fake_post_chat(message, history=None):
    return {
        "run_id": "run-fake-1",
        "reply": f"echo: {message}",
        "cards": [{"kind": "clarify_card", "question": "需要澄清吗？"}],
    }


def fake_stream_chat(run_id):
    yield "message", '{"text": "hel"}'
    yield "message", '{"text": "lo"}'


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test.db")
    monkeypatch.setenv("CHAT_DB_PATH", db_file)
    reset_settings()
    _db.reset_store()
    limiter.reset()
    monkeypatch.setattr(anomalies_client, "post_chat", fake_post_chat)
    monkeypatch.setattr(anomalies_client, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(anomalies_client, "probe", lambda: True)
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def auth_headers():
    return {"X-API-Key": TEST_KEY}


@pytest.fixture()
def session_id(client, auth_headers):
    r = client.post("/v1/chat/sessions", json={"title": "t"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]
