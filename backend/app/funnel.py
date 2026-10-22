# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (D67 / D147 clean-room chain; the 2023 line is read-only
# learning material only).

"""Funnel CTA (contract v1 §2.5) + cost / conversion accounting (capability-map
loyalty item ③: cost accounting and conversion tracking go live the same day).

- Every CTA to the main business carries
  utm_source=workbench&utm_medium=chat&utm_campaign=<campaign>.
- The chat module is fully free; no paywall anywhere (D144).
- `POST /v1/events` records cta_click / workbench_entry / module_switch etc.
- `GET /v1/metrics/summary` exposes total cost and cost-per-lead so the
  "single lead cost" north-star metric is computable from day one.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends

from . import db as _db
from .auth import require_api_key
from .config import get_settings
from .errors import RateLimited
from .models import EventRequest
from .rate_limit import limiter

router = APIRouter(tags=["funnel"])

MAIN_SITE = "https://vertciti.com/"

CAMPAIGNS = {
    "procurement_concierge": {
        "title": "AI 采购代办",
        "blurb": "让 AI 替你跑腿采购：把需求丢给 vertciti 采购代办，按单收费。",
        "path": "/",
        "title_en": "AI procurement concierge",
        "blurb_en": "Hand your sourcing to an AI: vertciti procurement concierge, priced per order.",
        "path_en": "/en.html",
    },
    "capability_catalog": {
        "title": "能力菜单",
        "blurb": "看看 vertciti 智能体都能替你做什么（真实能力，明码标价）。",
        "path": "/",
        "title_en": "Capability menu",
        "blurb_en": "See what vertciti agents can actually do for you (real capabilities, clear prices).",
        "path_en": "/en.html",
    },
}


def cta_url(campaign: str, lang: str = "zh") -> str:
    params = urlencode({
        "utm_source": "workbench",
        "utm_medium": "chat",
        "utm_campaign": campaign,
    })
    spec = CAMPAIGNS[campaign]
    path = spec["path_en"] if lang == "en" else spec["path"]
    return f"{MAIN_SITE.rstrip('/')}{path}?{params}"


@router.get("/v1/cta/funnel")
def funnel(identity: dict = Depends(require_api_key)):
    ok, retry = limiter.check_request(identity)
    if not ok:
        raise RateLimited("rate limit exceeded", retry_after=retry)
    limiter.count_request(identity)
    return {
        "ctas": [
            {
                "campaign": name,
                "title": spec["title"],
                "blurb": spec["blurb"],
                "url": cta_url(name),
                # Bilingual: the chat UI is zh/en, so every CTA ships both.
                "title_en": spec["title_en"],
                "blurb_en": spec["blurb_en"],
                "url_en": cta_url(name, "en"),
                "free": True,
            }
            for name, spec in CAMPAIGNS.items()
        ],
        "honesty": get_settings().honesty,
    }


@router.post("/v1/events")
def record_event(body: EventRequest, identity: dict = Depends(require_api_key)):
    ok, retry = limiter.check_request(identity)
    if not ok:
        raise RateLimited("rate limit exceeded", retry_after=retry)
    limiter.count_request(identity)
    _db.get_store().execute(
        "INSERT INTO events(ts, type, session_id, detail_json) VALUES(?,?,?,?)",
        (_db.utcnow(), body.type, body.session_id, _db.dumps(body.detail or {})),
    )
    return {"recorded": True, "honesty": get_settings().honesty}


@router.get("/v1/metrics/summary")
def metrics_summary(identity: dict = Depends(require_api_key)):
    ok, retry = limiter.check_request(identity)
    if not ok:
        raise RateLimited("rate limit exceeded", retry_after=retry)
    limiter.count_request(identity)
    store = _db.get_store()
    cost = store.fetchone(
        "SELECT COALESCE(SUM(cost_cents),0) c, COUNT(*) n FROM messages WHERE role='assistant'")
    clicks = store.fetchone(
        "SELECT COUNT(*) n FROM events WHERE type='cta_click'")
    sessions = store.fetchone("SELECT COUNT(*) n FROM sessions")
    total_cost = cost["c"] or 0
    leads = clicks["n"] or 0
    return {
        "sessions": sessions["n"] or 0,
        "assistant_messages": cost["n"] or 0,
        "total_cost_cents": total_cost,
        "cta_clicks": leads,
        # North-star: single-lead cost. null until the first click — never faked.
        "cost_per_lead_cents": (total_cost // leads) if leads else None,
        "honesty": get_settings().honesty,
    }
