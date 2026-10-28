# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Kill switch tests (contract §2.4/§5): two-step engage/clear, admin only,
module kill blocks every model-work path, erasure keeps working, platform scope
is an honest reservation, audit trail exists."""

import pytest
from conftest import kill, mint


@pytest.mark.req("INT-2", "SWE-134d")
def test_kill_is_two_step(client, admin_headers, session_id, auth_headers):
    r = client.post("/v1/risk/kill", json={"scope": "module", "reason_code": "d", "actor": "t"},
                    headers=admin_headers)
    assert r.status_code == 202
    assert r.json()["pending"] is True
    # preparing alone changes nothing
    assert client.post(f"/v1/chat/sessions/{session_id}/messages", json={"content": "inline"},
                       headers=auth_headers).status_code == 200


@pytest.mark.req("INT-2")
def test_confirm_requires_exact_phrase_once_and_in_time(client, admin_headers):
    p = client.post("/v1/risk/kill", json={"scope": "module", "reason_code": "d", "actor": "t"},
                    headers=admin_headers).json()
    bad = client.post("/v1/risk/confirm", json={"challenge_id": p["challenge_id"],
                                                "confirm_phrase": "yes"}, headers=admin_headers)
    assert bad.status_code == 400
    ok = client.post("/v1/risk/confirm", json={"challenge_id": p["challenge_id"],
                                               "confirm_phrase": p["confirm_phrase"]},
                     headers=admin_headers)
    assert ok.status_code == 200
    again = client.post("/v1/risk/confirm", json={"challenge_id": p["challenge_id"],
                                                  "confirm_phrase": p["confirm_phrase"]},
                        headers=admin_headers)
    assert again.status_code == 409


@pytest.mark.req("INT-2")
def test_expired_challenge_refused(client, admin_headers):
    from app import db as _db

    p = client.post("/v1/risk/unkill", json={"scope": "module", "actor": "t"},
                    headers=admin_headers).json()
    _db.get_store().execute("UPDATE risk_challenges SET expires_at='2000-01-01T00:00:00+00:00'")
    r = client.post("/v1/risk/confirm", json={"challenge_id": p["challenge_id"],
                                              "confirm_phrase": p["confirm_phrase"]},
                    headers=admin_headers)
    assert r.status_code == 409


@pytest.mark.req("KILL-module")
def test_kill_module_blocks_every_model_path(client, admin_headers, auth_headers, session_id):
    v = mint(client)
    kill(client, admin_headers)
    checks = [
        client.post(f"/v1/chat/sessions/{session_id}/messages", json={"content": "x"},
                    headers=auth_headers),
        client.post("/v1/chat/sessions", json={}, headers=auth_headers),
        client.post("/v1/visitor"),
        client.post("/v1/llm/route", json={"model_policy": "default", "messages": [],
                                           "idempotency_key": "kk1"}, headers=auth_headers),
        client.post("/v1/memory/store", json={"namespace": "chat:x", "key": "k", "payload": {}},
                    headers=auth_headers),
        client.post("/v1/memory/recall", json={"namespace": "chat:x"}, headers=auth_headers),
        client.post("/v1/events", json={"type": "cta_click"}, headers=v),
    ]
    for r in checks:
        assert r.status_code == 503, r.request.url
        assert r.json()["code"] == "chat_killed"


@pytest.mark.req("KILL-module", "PRIV-erasure")
def test_erasure_and_reads_work_while_killed(client, admin_headers, auth_headers, session_id):
    kill(client, admin_headers)
    assert client.get(f"/v1/chat/sessions/{session_id}", headers=auth_headers).status_code == 200
    assert client.request("DELETE", "/v1/memory/forget", json={"namespace": "chat:x", "key": "k"},
                          headers=auth_headers).status_code == 200
    assert client.delete(f"/v1/chat/sessions/{session_id}", headers=auth_headers).status_code == 200


@pytest.mark.req("ARCH-6", "KILL-module")
def test_health_reports_kill_state(client, admin_headers):
    kill(client, admin_headers)
    body = client.get("/health").json()
    assert body["killed"] is True
    assert body["status"] == "killed"
    assert body["components"]["kill_switch"].startswith("🔴")


@pytest.mark.req("KILL-module")
def test_unkill_recovers(client, admin_headers, auth_headers, session_id):
    kill(client, admin_headers)
    r = kill(client, admin_headers, action="unkill")
    assert r.json()["killed"] is False
    m = client.post(f"/v1/chat/sessions/{session_id}/messages", json={"content": "inline back"},
                    headers=auth_headers)
    assert m.status_code == 200


@pytest.mark.req("KILL-platform")
def test_platform_scope_is_honest_reservation(client, admin_headers):
    r = kill(client, admin_headers, scope="platform")
    body = r.json()
    assert body["platform_hook_connected"] is False
    assert body["honesty"] == "🟡"


@pytest.mark.req("SEC-A4", "KILL-module")
def test_kill_audit_trail(client, admin_headers):
    kill(client, admin_headers)
    kill(client, admin_headers, action="unkill")
    r = client.get("/v1/risk/audit", headers=admin_headers)
    actions = [e["action"] for e in r.json()["events"]]
    for a in ("risk.kill.prepared", "risk.kill", "risk.unkill.prepared", "risk.unkill"):
        assert a in actions
    assert all(e["row_hash"] for e in r.json()["events"])


def test_status_shape(client, admin_headers):
    r = client.get("/v1/risk/status", headers=admin_headers)
    body = r.json()
    assert "module" in body and "platform" in body
    assert body["platform"]["platform_hook_connected"] is False
