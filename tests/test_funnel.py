# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Funnel CTA + cost/conversion accounting tests (contract §2.5, loyalty ③)."""

import pytest
from conftest import mint


@pytest.mark.req("FUNNEL-utm")
def test_funnel_ctas_have_utm_and_free(client, visitor_headers):
    r = client.get("/v1/cta/funnel", headers=visitor_headers)
    assert r.status_code == 200
    for cta in r.json()["ctas"]:
        for url in (cta["url"], cta["url_zh"], cta["url_en"]):
            assert "utm_source=workbench" in url
            assert "utm_medium=chat" in url
            assert "utm_campaign=" in url
        assert cta["free"] is True


@pytest.mark.req("DES-5")
def test_funnel_ctas_follow_language(client, visitor_headers):
    zh = client.get("/v1/cta/funnel?lang=zh", headers=visitor_headers).json()["ctas"][0]
    en = client.get("/v1/cta/funnel?lang=en", headers=visitor_headers).json()["ctas"][0]
    assert zh["title"] == zh["title_zh"] and en["title"] == en["title_en"]
    assert "/en.html?" in en["url"] and "/en.html" not in zh["url"]
    assert not any("一" <= ch <= "鿿" for ch in en["title"] + en["blurb"])
    by_header = client.get("/v1/cta/funnel", headers={**visitor_headers,
                                                     "Accept-Language": "en-US,en;q=0.9"})
    assert by_header.json()["ctas"][0]["lang"] == "en"


@pytest.mark.req("FUNNEL-north-star")
def test_cost_per_lead_counts_distinct_visitors(client, admin_headers):
    r = client.get("/v1/metrics/summary", headers=admin_headers)
    assert r.json()["cost_per_lead_cents"] is None  # no leads yet: honest null

    a, b = mint(client), mint(client)
    for h in (a, a, b):
        client.post("/v1/events", json={"type": "cta_click", "detail": {"utm_campaign": "c"}},
                    headers=h)
    body = client.get("/v1/metrics/summary", headers=admin_headers).json()
    assert body["cta_clicks"] == 3
    assert body["leads"] == 2
    assert body["cost_per_lead_cents"] == body["total_cost_cents"] // 2


@pytest.mark.req("SEC-A1", "FUNNEL-north-star")
def test_metrics_not_poisonable_by_visitors(client):
    v = mint(client)
    assert client.get("/v1/metrics/summary", headers=v).status_code == 403


@pytest.mark.req("ARCH-6", "HONESTY")
def test_health_honesty_labels(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "chat"
    assert body["honesty"] == "🟡"
    assert body["components"]["chat_api"] == "🟢"
    assert body["components"]["database"] == "🟢"
    assert body["components"]["anomalies_runtime"] == "🟢"  # probed True in fixture
    assert "AutoGPT" not in r.text  # 旧项目名称永不出现在用户可见面


@pytest.mark.req("FUNNEL-events")
def test_workbench_entry_event(client, visitor_headers):
    r = client.post("/v1/events", json={
        "type": "workbench_entry", "detail": {"module": "chat", "utm_source": "workbench"},
    }, headers=visitor_headers)
    assert r.json()["recorded"] is True
