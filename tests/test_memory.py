# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Memory tests (contract §2.2): store/recall/forget, pii redaction, TTL,
module isolation (cross-module 403 + audit)."""


def test_store_recall_forget(client, auth_headers):
    r = client.post("/v1/memory/store", json={
        "namespace": "chat:prefs", "key": "lang",
        "payload": {"value": "zh"}, "ttl_days": 30,
    }, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"] is True
    assert body["pii_redacted"] is False
    assert "dev store" in body["note"]  # honest about keyword recall

    r = client.post("/v1/memory/recall", json={
        "namespace": "chat:prefs", "query": "lang",
    }, headers=auth_headers)
    assert r.status_code == 200
    recs = r.json()["records"]
    assert len(recs) == 1
    assert recs[0]["key"] == "lang"

    r = client.request("DELETE", "/v1/memory/forget",
                       json={"namespace": "chat:prefs", "key": "lang"},
                       headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    r = client.post("/v1/memory/recall", json={
        "namespace": "chat:prefs", "query": "lang",
    }, headers=auth_headers)
    assert r.json()["count"] == 0


def test_pii_fields_redacted(client, auth_headers):
    client.post("/v1/memory/store", json={
        "namespace": "chat:lead", "key": "u1",
        "payload": {"email": "a@b.com", "note": "hi"},
        "pii_fields": ["email"],
    }, headers=auth_headers)
    r = client.post("/v1/memory/recall", json={
        "namespace": "chat:lead", "query": "u1",
    }, headers=auth_headers)
    import json as _json
    payload = _json.loads(r.json()["records"][0]["payload"])
    assert payload["email"] == "[REDACTED]"
    assert payload["note"] == "hi"
    assert r.json()["records"][0]["pii_redacted"] is True


def test_nested_pii_marker_redacted(client, auth_headers):
    client.post("/v1/memory/store", json={
        "namespace": "chat:lead", "key": "u2",
        "payload": {"phone": {"pii": True, "value": "13800000000"}},
    }, headers=auth_headers)
    r = client.post("/v1/memory/recall", json={"namespace": "chat:lead", "query": "u2"},
                    headers=auth_headers)
    import json as _json
    payload = _json.loads(r.json()["records"][0]["payload"])
    assert payload["phone"] == "[REDACTED]"


def test_ttl_expiry_purged(client, auth_headers):
    from app import db as _db
    from app.memory_store import get_memory_store

    get_memory_store().store(
        module_id="chat", namespace="chat:tmp", key="old",
        payload={"v": 1}, pii_redacted=False, ttl_days=-1,  # already expired
    )
    recs = get_memory_store().recall(
        module_id="chat", namespace="chat:tmp", query="", top_k=5, min_score=0.0)
    assert recs == []
    row = _db.get_store().fetchone(
        "SELECT COUNT(*) n FROM memory_records WHERE key='old'")
    assert row["n"] == 0


def test_cross_module_store_denied_and_audited(client, auth_headers):
    r = client.post("/v1/memory/store", json={
        "module": "translator", "namespace": "x", "key": "k", "payload": {},
    }, headers=auth_headers)
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"

    from app import audit as audit_mod
    actions = [e["action"] for e in audit_mod.recent(20)]
    assert "memory.cross_module_denied" in actions


def test_cross_module_recall_denied(client, auth_headers):
    r = client.post("/v1/memory/recall", json={"module": "agent", "query": "x"},
                    headers=auth_headers)
    assert r.status_code == 403
