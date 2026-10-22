# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Funnel CTA + cost/conversion accounting tests (contract §2.5, loyalty ③)."""


def test_funnel_ctas_have_utm_and_free(client, auth_headers):
    r = client.get("/v1/cta/funnel", headers=auth_headers)
    assert r.status_code == 200
    for cta in r.json()["ctas"]:
        assert "utm_source=workbench" in cta["url"]
        assert "utm_medium=chat" in cta["url"]
        assert "utm_campaign=" in cta["url"]
        assert cta["free"] is True


def test_cta_click_recorded_and_cost_per_lead(client, auth_headers, session_id):
    r = client.get("/v1/metrics/summary", headers=auth_headers)
    assert r.json()["cost_per_lead_cents"] is None  # no leads yet: honest null

    client.post("/v1/events", json={
        "type": "cta_click", "session_id": session_id,
        "detail": {"target": "https://vertciti.com/", "utm_campaign": "procurement_concierge"},
    }, headers=auth_headers)
    client.post("/v1/events", json={
        "type": "cta_click", "session_id": session_id, "detail": {},
    }, headers=auth_headers)

    r = client.get("/v1/metrics/summary", headers=auth_headers)
    body = r.json()
    assert body["cta_clicks"] == 2
    assert body["cost_per_lead_cents"] == body["total_cost_cents"] // 2


def test_health_honesty_labels(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "chat"
    assert body["honesty"] == "🟡"
    assert body["components"]["chat_api"] == "🟢"
    assert body["components"]["anomalies_runtime"] == "🟢"  # probed True in fixture
    assert "AutoGPT" not in r.text  # D146: 旧项目名称永不出现在用户可见面


def test_workbench_entry_event(client, auth_headers):
    r = client.post("/v1/events", json={
        "type": "workbench_entry", "detail": {"module": "chat", "utm_source": "workbench"},
    }, headers=auth_headers)
    assert r.json()["recorded"] is True


def test_funnel_ctas_are_bilingual(client, auth_headers):
    r = client.get("/v1/cta/funnel", headers=auth_headers)
    for cta in r.json()["ctas"]:
        assert cta["title_en"] and cta["blurb_en"]
        assert "/en.html?" in cta["url_en"] and "utm_campaign=" in cta["url_en"]
        assert "/en.html" not in cta["url"]
