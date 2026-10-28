# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Platform behaviour: audit hash chain, health that reflects the database,
schema migrations, production guard, error contract, security headers,
trace ids, retention."""

import sqlite3

import pytest

# --- audit chain (SEC-A4) ----------------------------------------------------------

@pytest.mark.req("SEC-A4")
def test_audit_chain_verifies_and_detects_tampering(client, admin_headers):
    from app import audit
    from app import db as _db

    for i in range(3):
        audit.record("test.event", "t", {"i": i})
    ok = client.get("/v1/risk/audit/verify", headers=admin_headers).json()
    assert ok["ok"] is True and ok["head"] and ok["count"] >= 3

    # Regression: a one-line UPDATE used to rewrite history undetected.
    _db.get_store().execute(
        "UPDATE audit_log SET actor='ghost' WHERE action='test.event' AND detail_json='{\"i\":1}'")
    bad = client.get("/v1/risk/audit/verify", headers=admin_headers).json()
    assert bad["ok"] is False and bad["first_bad_id"] is not None


@pytest.mark.req("SEC-A4")
def test_audit_chain_detects_deletion(client):
    from app import audit
    from app import db as _db

    for i in range(3):
        audit.record("test.event", "t", {"i": i})
    _db.get_store().execute("DELETE FROM audit_log WHERE detail_json='{\"i\":1}'")
    assert audit.verify()["ok"] is False


# --- health (ARCH-6) ---------------------------------------------------------------

@pytest.mark.req("ARCH-6")
def test_health_503_when_database_unusable(client, monkeypatch):
    """Regression: /health said 200 while every write failed."""
    from app import db as _db

    def broken():
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(_db, "get_store", broken)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["components"]["database"] == "🔴"
    assert client.get("/healthz").status_code == 503


@pytest.mark.req("ARCH-5")
def test_schema_version_recorded(client):
    body = client.get("/health").json()
    from app.db import SCHEMA_VERSION
    assert body["schema_version"] == SCHEMA_VERSION


@pytest.mark.req("ARCH-5")
def test_v1_database_upgrades_in_place(tmp_path):
    """A database created by the original schema (no version table) upgrades,
    keeps its rows, and gets its audit rows sealed into the chain."""
    from app import audit
    from app import db as _db

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(_db.SCHEMA_V1)
    conn.execute("INSERT INTO sessions(id, title, created_at) VALUES('s1','t','2026-10-01T00:00:00+00:00')")
    conn.execute("INSERT INTO audit_log(ts, actor, action, detail_json) "
                 "VALUES('2026-10-01T00:00:00+00:00','a','risk.kill','{}')")
    conn.commit()
    conn.close()

    _db.reset_store()
    store = _db.get_store(path)
    assert store.schema_version() == _db.SCHEMA_VERSION
    assert store.fetchone("SELECT COUNT(*) n FROM sessions")["n"] == 1
    assert audit.verify()["ok"] is True
    _db.reset_store()


# --- configuration (ARCH-5) ----------------------------------------------------------

@pytest.mark.req("ARCH-5")
def test_prod_refuses_to_start_without_real_config(monkeypatch):
    from app.config import ConfigError, Settings

    monkeypatch.setenv("CHAT_ENV", "prod")
    for name in ("CHAT_API_KEY", "CHAT_ADMIN_KEY", "CHAT_VISITOR_SECRET", "CHAT_CORS_ORIGINS",
                 "CHAT_DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigError) as e:
        Settings()
    for name in ("CHAT_API_KEY", "CHAT_ADMIN_KEY", "CHAT_VISITOR_SECRET", "CHAT_CORS_ORIGINS"):
        assert name in str(e.value)


@pytest.mark.req("ARCH-5", "SEC-A6")
def test_prod_with_full_config_starts_without_docs(monkeypatch, tmp_path):
    from app.config import reset_settings
    from app.main import create_app

    monkeypatch.setenv("CHAT_ENV", "prod")
    monkeypatch.setenv("CHAT_API_KEY", "s" * 32)
    monkeypatch.setenv("CHAT_ADMIN_KEY", "a" * 32)
    monkeypatch.setenv("CHAT_VISITOR_SECRET", "v" * 32)
    monkeypatch.setenv("CHAT_CORS_ORIGINS", "https://chat.example")
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "p.db"))
    reset_settings()
    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        assert "max-age" in c.get("/health").headers["Strict-Transport-Security"]
    reset_settings()


@pytest.mark.req("ARCH-5")
def test_prod_rejects_admin_key_equal_to_service_key(monkeypatch):
    from app.config import ConfigError, Settings

    monkeypatch.setenv("CHAT_ENV", "prod")
    monkeypatch.setenv("CHAT_API_KEY", "x" * 32)
    monkeypatch.setenv("CHAT_ADMIN_KEY", "x" * 32)
    monkeypatch.setenv("CHAT_VISITOR_SECRET", "v" * 32)
    monkeypatch.setenv("CHAT_CORS_ORIGINS", "https://chat.example")
    monkeypatch.setenv("CHAT_DB_PATH", "/tmp/x.db")
    with pytest.raises(ConfigError, match="must differ"):
        Settings()


@pytest.mark.req("DOC-1")
def test_dev_defaults_allow_local_frontend_and_print_credentials(monkeypatch, capsys):
    """Regression: the README quick start failed (no CORS, key never printed)."""
    from app import main
    from app.config import Settings, reset_settings

    monkeypatch.setenv("CHAT_ENV", "dev")
    for name in ("CHAT_API_KEY", "CHAT_ADMIN_KEY", "CHAT_VISITOR_SECRET", "CHAT_CORS_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    reset_settings()
    s = Settings()
    assert "http://127.0.0.1:3120" in s.cors_origins
    main._print_dev_credentials()
    out = capsys.readouterr().out
    assert "CHAT_API_KEY=" in out and "CHAT_ADMIN_KEY=" in out
    reset_settings()


# --- error contract, headers, trace ids ----------------------------------------------

@pytest.mark.req("SEC-error-contract")
def test_framework_errors_use_contract_shape(client, auth_headers):
    """Regression: 404/422 used framework {detail} bodies."""
    r = client.get("/no/such/path")
    assert r.status_code == 404
    assert set(r.json()) >= {"code", "message", "trace_id"}
    r = client.post("/v1/chat/sessions", json={"title": 123}, headers=auth_headers)
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert "123" not in r.text  # inputs are not echoed back


@pytest.mark.req("SEC-A6")
def test_security_headers_on_every_response(client):
    for r in (client.get("/health"), client.get("/no/such/path")):
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'none'" in r.headers["Content-Security-Policy"]


@pytest.mark.req("OPS-2")
def test_trace_id_echoed_only_when_well_formed(client):
    good = client.get("/health", headers={"X-Request-ID": "abc123def456"})
    assert good.headers["X-Trace-ID"] == "abc123def456"
    bad = client.get("/health", headers={"X-Request-ID": "x\nforged log line"})
    assert bad.headers["X-Trace-ID"] != "x\nforged log line"
    assert len(bad.headers["X-Trace-ID"]) == 32


@pytest.mark.req("OPS-2")
def test_logs_are_json_with_trace_id(client):
    import io
    import json
    import logging

    from app.main import JsonFormatter

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("chat")
    logger.addHandler(handler)
    try:
        client.get("/health", headers={"X-Request-ID": "trace-for-log-test"})
    finally:
        logger.removeHandler(handler)
    lines = buf.getvalue().splitlines()
    records = [json.loads(ln) for ln in lines]
    req = [r for r in records if r.get("trace_id") == "trace-for-log-test"]
    assert req and req[0]["path"] == "/health" and req[0]["status"] == 200


# --- retention (PRIV) ------------------------------------------------------------------

@pytest.mark.req("PRIV-retention")
def test_retention_purges_old_conversations(client, auth_headers, session_id):
    from app import db as _db
    from app import retention

    client.post(f"/v1/chat/sessions/{session_id}/messages", json={"content": "inline old"},
                headers=auth_headers)
    _db.get_store().execute("UPDATE sessions SET created_at='2000-01-01T00:00:00+00:00'")
    out = retention.purge()
    assert out["sessions"] == 1 and out["messages"] == 2
    assert client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers).status_code == 404


@pytest.mark.req("PRIV-retention", "DES-6")
def test_visitor_is_told_the_retention_period(client):
    body = client.post("/v1/visitor").json()
    assert body["retention_days"] == 30
