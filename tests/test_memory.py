# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Memory tests (contract §2.2): store/recall/forget, pii redaction (incl.
dotted paths), literal namespace prefixes, TTL, module isolation
(cross-module 403 + audit)."""

import json as _json

import pytest


def _store(client, h, ns, key, payload, **kw):
    r = client.post("/v1/memory/store", json={"namespace": ns, "key": key, "payload": payload, **kw},
                    headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _recall(client, h, ns, query=""):
    return client.post("/v1/memory/recall", json={"namespace": ns, "query": query}, headers=h).json()


@pytest.mark.req("MEM-contract")
def test_store_recall_forget(client, auth_headers):
    body = _store(client, auth_headers, "chat:prefs", "lang", {"value": "zh"}, ttl_days=30)
    assert body["stored"] is True
    assert body["pii_redacted"] is False
    assert "dev store" in body["note"]  # honest about keyword recall

    recs = _recall(client, auth_headers, "chat:prefs", "lang")["records"]
    assert len(recs) == 1
    assert recs[0]["key"] == "lang"

    r = client.request("DELETE", "/v1/memory/forget",
                       json={"namespace": "chat:prefs", "key": "lang"}, headers=auth_headers)
    assert r.json()["deleted"] is True
    assert _recall(client, auth_headers, "chat:prefs", "lang")["count"] == 0


@pytest.mark.req("PRIV-redaction")
def test_pii_fields_redacted(client, auth_headers):
    _store(client, auth_headers, "chat:lead", "u1", {"email": "a@b.com", "note": "hi"},
           pii_fields=["email"])
    rec = _recall(client, auth_headers, "chat:lead", "u1")["records"][0]
    payload = _json.loads(rec["payload"])
    assert payload["email"] == "[REDACTED]"
    assert payload["note"] == "hi"
    assert rec["pii_redacted"] is True


@pytest.mark.req("PRIV-redaction")
def test_nested_pii_marker_redacted(client, auth_headers):
    _store(client, auth_headers, "chat:lead", "u2", {"phone": {"pii": True, "value": "13800000000"}})
    payload = _json.loads(_recall(client, auth_headers, "chat:lead", "u2")["records"][0]["payload"])
    assert payload["phone"] == "[REDACTED]"


@pytest.mark.req("PRIV-redaction")
def test_dotted_path_pii_redacted(client, auth_headers):
    """Regression: `pii_fields: ["contact.email"]` used to be stored in plaintext."""
    _store(client, auth_headers, "chat:lead", "n1",
           {"contact": {"email": "a@b.com", "city": "NYC"},
            "people": [{"phone": "1"}, {"phone": "2"}]},
           pii_fields=["contact.email", "people.phone"])
    rec = _recall(client, auth_headers, "chat:lead", "n1")["records"][0]
    payload = _json.loads(rec["payload"])
    assert payload["contact"] == {"email": "[REDACTED]", "city": "NYC"}
    assert payload["people"] == [{"phone": "[REDACTED]"}, {"phone": "[REDACTED]"}]
    assert rec["pii_redacted"] is True
    assert "a@b.com" not in _json.dumps(rec)


@pytest.mark.req("MEM-isolation")
@pytest.mark.parametrize("ns", ["%", "chat:____", "chat:_%"])
def test_namespace_wildcards_are_literal(client, auth_headers, ns):
    """Regression: LIKE wildcards in the namespace matched other namespaces."""
    _store(client, auth_headers, "chat:lead", "a", {"v": 1})
    _store(client, auth_headers, "chat:prefs", "b", {"v": 2})
    assert _recall(client, auth_headers, ns)["count"] == 0


@pytest.mark.req("MEM-contract")
def test_namespace_prefix_and_empty_namespace(client, auth_headers):
    _store(client, auth_headers, "chat:lead", "a", {"v": 1})
    _store(client, auth_headers, "chat:prefs", "b", {"v": 2})
    assert _recall(client, auth_headers, "chat:le")["count"] == 1
    assert _recall(client, auth_headers, "")["count"] == 2  # all of this module, by contract


@pytest.mark.req("PRIV-retention")
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
    row = _db.get_store().fetchone("SELECT COUNT(*) n FROM memory_records WHERE key='old'")
    assert row["n"] == 0


@pytest.mark.req("MEM-isolation")
def test_cross_module_store_denied_and_audited(client, auth_headers):
    r = client.post("/v1/memory/store", json={
        "module": "translator", "namespace": "x", "key": "k", "payload": {},
    }, headers=auth_headers)
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"

    from app import audit as audit_mod
    actions = [e["action"] for e in audit_mod.recent(20)]
    assert "memory.cross_module_denied" in actions


@pytest.mark.req("MEM-isolation")
def test_cross_module_recall_denied(client, auth_headers):
    r = client.post("/v1/memory/recall", json={"module": "agent", "query": "x"},
                    headers=auth_headers)
    assert r.status_code == 403


@pytest.mark.req("ARCH-5")
def test_unbuilt_memory_backend_fails_at_startup(monkeypatch):
    from app.config import ConfigError
    from app.memory_store import check_backend

    monkeypatch.setenv("CHAT_MEMORY_BACKEND", "pgvector")
    with pytest.raises(ConfigError):
        check_backend()
