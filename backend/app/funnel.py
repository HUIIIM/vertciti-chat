# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Funnel CTA (contract v1 §2.5) + cost / conversion accounting (capability-map
loyalty item ③: cost accounting and conversion tracking go live the same day).

- Every CTA to the main business carries
  utm_source=workbench&utm_medium=chat&utm_campaign=<campaign>.
- CTAs are bilingual: `?lang=en|zh` (or Accept-Language) picks `title`/`blurb`/
  `url`; both languages are always present as `*_zh` / `*_en` as well.
- The chat module is fully free; no paywall anywhere.
- `POST /v1/events` records allowlisted client events (cta_click,
  workbench_entry, module_switch) against the caller's own sessions only.
- `GET /v1/metrics/summary` (admin only) exposes total cost and cost-per-lead
  so the "single lead cost" north-star metric is computable from day one.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request

from . import db as _db
from .auth import AdminPrincipal, ChatPrincipal
from .chat_api import get_owned_session
from .config import get_settings
from .events import record_event
from .kill import check_not_killed
from .models import EventRequest
from .rate_limit import limiter

router = APIRouter(tags=["funnel"])

MAIN_SITE = "https://vertciti.com/"

CAMPAIGNS = {
    "capability_catalog": {
        "zh": {
            "title": "能力菜单",
            "blurb": "看看 vertciti 智能体都能替你做什么（真实能力，明码标价）。",
            "path": "/",
        },
        "en": {
            "title": "Capability menu",
            "blurb": "See what vertciti agents can actually do for you (real capabilities, clear prices).",
            "path": "/en.html",
        },
    },
}


def pick_lang(request: Request, explicit: str | None) -> str:
    if explicit in ("zh", "en"):
        return explicit
    accept = request.headers.get("accept-language", "").lower()
    return "en" if accept.startswith("en") else "zh"


def cta_url(campaign: str, lang: str = "zh") -> str:
    params = urlencode({
        "utm_source": "workbench",
        "utm_medium": "chat",
        "utm_campaign": campaign,
    })
    spec = CAMPAIGNS[campaign][lang]
    return f"{MAIN_SITE.rstrip('/')}{spec['path']}?{params}"


@router.get("/v1/cta/funnel")
def funnel(request: Request, principal: ChatPrincipal,
           lang: str | None = Query(default=None, pattern="^(zh|en)$")) -> dict:
    limiter.enforce(principal)
    chosen = pick_lang(request, lang)
    ctas = []
    for name, spec in CAMPAIGNS.items():
        ctas.append({
            "campaign": name,
            "lang": chosen,
            "title": spec[chosen]["title"],
            "blurb": spec[chosen]["blurb"],
            "url": cta_url(name, chosen),
            "title_zh": spec["zh"]["title"], "blurb_zh": spec["zh"]["blurb"],
            "url_zh": cta_url(name, "zh"),
            "title_en": spec["en"]["title"], "blurb_en": spec["en"]["blurb"],
            "url_en": cta_url(name, "en"),
            "free": True,
        })
    return {"ctas": ctas, "honesty": get_settings().honesty}


@router.post("/v1/events")
def post_event(body: EventRequest, principal: ChatPrincipal) -> dict:
    check_not_killed()
    limiter.enforce(principal)
    if body.session_id:
        get_owned_session(body.session_id, principal)
    record_event(body.type, body.session_id, body.detail, subject=principal.subject)
    return {"recorded": True, "honesty": get_settings().honesty}


@router.get("/v1/metrics/summary")
def metrics_summary(admin: AdminPrincipal) -> dict:
    limiter.enforce(admin)
    store = _db.get_store()
    cost = store.fetchone(
        "SELECT COALESCE(SUM(cost_cents),0) c, COUNT(*) n FROM messages WHERE role='assistant'")
    # A lead is one visitor/caller who clicked a CTA, not one click.
    leads_row = store.fetchone(
        "SELECT COUNT(DISTINCT COALESCE(subject, 'legacy:' || id)) n FROM events WHERE type='cta_click'")
    clicks = store.fetchone("SELECT COUNT(*) n FROM events WHERE type='cta_click'")
    sessions = store.fetchone("SELECT COUNT(*) n FROM sessions")
    statuses = {r["status"]: r["n"] for r in store.fetchall(
        "SELECT status, COUNT(*) n FROM messages WHERE role='assistant' GROUP BY status")}
    assert cost and leads_row and clicks and sessions
    total_cost = cost["c"] or 0
    leads = leads_row["n"] or 0
    finished = sum(statuses.get(s, 0) for s in ("done", "error", "interrupted"))
    return {
        "sessions": sessions["n"] or 0,
        "assistant_messages": cost["n"] or 0,
        "assistant_status": statuses,
        # SLO "reply success": done / (done + error + interrupted). null until data exists.
        "reply_success_ratio": (statuses.get("done", 0) / finished) if finished else None,
        "total_cost_cents": total_cost,
        "cta_clicks": clicks["n"] or 0,
        "leads": leads,
        # North-star: single-lead cost. null until the first lead — never faked.
        "cost_per_lead_cents": (total_cost // leads) if leads else None,
        "honesty": get_settings().honesty,
    }
