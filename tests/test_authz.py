# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Per-subject authorization regression tests (SEC-A1): every route, every
principal. A visitor must never reach another visitor's data or any operator
function; the service key must never reach operator functions; the admin key
must not chat."""

import pytest
from conftest import mint


def _session(client, headers):
    return client.post("/v1/chat/sessions", json={}, headers=headers).json()["session_id"]


@pytest.mark.req("SEC-A1")
@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/chat/sessions/{sid}"),
    ("GET", "/v1/chat/sessions/{sid}/cost"),
    ("DELETE", "/v1/chat/sessions/{sid}"),
    ("POST", "/v1/chat/sessions/{sid}/messages"),
    ("GET", "/v1/chat/sessions/{sid}/stream?message_id={mid}"),
])
def test_visitor_cannot_reach_another_visitors_session(client, method, path):
    owner, other = mint(client), mint(client)
    sid = _session(client, owner)
    mid = client.post(f"/v1/chat/sessions/{sid}/messages", json={"content": "inline secret"},
                      headers=owner).json()["message_id"]
    url = path.format(sid=sid, mid=mid)
    r = client.request(method, url, headers=other,
                       json={"content": "x"} if method == "POST" else None)
    assert r.status_code == 404, (method, url, r.status_code)
    assert "secret" not in r.text
    # the owner still can
    assert client.get(f"/v1/chat/sessions/{sid}", headers=owner).status_code == 200


@pytest.mark.req("SEC-A1")
def test_service_key_cannot_read_visitor_sessions(client, auth_headers):
    v = mint(client)
    sid = _session(client, v)
    assert client.get(f"/v1/chat/sessions/{sid}", headers=auth_headers).status_code == 404


@pytest.mark.req("SEC-A1")
def test_session_list_only_shows_own(client):
    a, b = mint(client), mint(client)
    sa = _session(client, a)
    _session(client, b)
    ids = [s["id"] for s in client.get("/v1/chat/sessions", headers=a).json()["sessions"]]
    assert ids == [sa]


@pytest.mark.req("SEC-A1", "INT-2")
@pytest.mark.parametrize("method,path,body", [
    ("POST", "/v1/risk/kill", {"scope": "module", "reason_code": "x", "actor": "x"}),
    ("POST", "/v1/risk/unkill", {"scope": "module", "actor": "x"}),
    ("POST", "/v1/risk/confirm", {"challenge_id": "x", "confirm_phrase": "x"}),
    ("GET", "/v1/risk/status", None),
    ("GET", "/v1/risk/audit", None),
    ("GET", "/v1/risk/audit/verify", None),
    ("GET", "/v1/metrics/summary", None),
])
def test_operator_routes_are_admin_only(client, auth_headers, method, path, body):
    for headers in (mint(client), auth_headers):
        r = client.request(method, path, headers=headers, json=body)
        assert r.status_code == 403, (path, r.status_code)
        assert r.json()["code"] == "forbidden"


@pytest.mark.req("SEC-A1")
@pytest.mark.parametrize("method,path,body", [
    ("POST", "/v1/memory/store", {"namespace": "chat:x", "key": "k", "payload": {}}),
    ("POST", "/v1/memory/recall", {"namespace": "chat:x"}),
    ("DELETE", "/v1/memory/forget", {"namespace": "chat:x", "key": "k"}),
    ("POST", "/v1/llm/route", {"model_policy": "default", "messages": [], "idempotency_key": "k"}),
])
def test_service_routes_reject_visitors_and_admin(client, admin_headers, method, path, body):
    for headers in (mint(client), admin_headers):
        r = client.request(method, path, headers=headers, json=body)
        assert r.status_code == 403, (path, r.status_code)


@pytest.mark.req("SEC-A1")
def test_admin_key_cannot_chat(client, admin_headers):
    assert client.post("/v1/chat/sessions", json={}, headers=admin_headers).status_code == 403


@pytest.mark.req("SEC-A1")
def test_events_only_against_own_sessions(client):
    a, b = mint(client), mint(client)
    sa = _session(client, a)
    r = client.post("/v1/events", json={"type": "cta_click", "session_id": sa}, headers=b)
    assert r.status_code == 404
    assert client.post("/v1/events", json={"type": "cta_click", "session_id": sa},
                       headers=a).status_code == 200


@pytest.mark.req("SEC-A1", "ARCH-8")
def test_events_reject_unknown_types_and_large_details(client):
    v = mint(client)
    assert client.post("/v1/events", json={"type": "anything_goes"}, headers=v).status_code == 422
    big = {"x": "a" * 5000}
    assert client.post("/v1/events", json={"type": "cta_click", "detail": big},
                       headers=v).status_code == 422
