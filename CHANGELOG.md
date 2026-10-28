# Changelog

All notable changes to vertciti chat. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/) (pre-1.0: minor = breaking).

## [Unreleased] — 0.2.0

Remediation of the independent SOTA assessment (issue #10). The API changes below
are **breaking** for any caller of 0.1.

### Security
- Three principals instead of one shared key: anonymous signed **visitor tokens**
  (`POST /v1/visitor`, no signup) for the public page, `CHAT_API_KEY` for services,
  `CHAT_ADMIN_KEY` for operator functions. Sessions are owned; other callers get 404.
- Kill switch and unkill are **two-step** (`/v1/risk/kill|unkill` prepare →
  `/v1/risk/confirm` with the exact phrase within 120 s) and admin-only.
- Audit log is **hash-chained**; `GET /v1/risk/audit/verify` recomputes it and
  `scripts/audit_anchor.py` exports the daily head for external anchoring.
- Idempotency keys scoped to caller and session (a shared key used to replay another
  session's reply). Memory namespaces matched literally (LIKE wildcards escaped).
  Dotted-path PII redaction (`contact.email`, `people.phone`).
- Security headers on every API response; strict CSP (no inline script) on the page;
  validated trace ids; `/docs` and `/openapi.json` off in prod; runtime internals are
  no longer forwarded to browsers.
- Prod refuses to start without real credentials, CORS origins and a database path.
- All GitHub Actions pinned by commit SHA; hash-locked Python installs; locked
  Playwright; release workflow with CycloneDX SBOM and build provenance attestations.

### Fixed
- One slow runtime stream no longer blocks the whole server (async client); every
  stream has an idle timeout, a total deadline and a size cap.
- Replaying a stream no longer re-runs (and re-bills) the agent.
- Daily quota is per visitor plus a per-IP ceiling, checked and counted atomically,
  on the UTC day (it used to be one global quota with a race).
- `/health` returns 503 when the database cannot serve and reports the kill state.
- 404 and 422 bodies follow the `{code, message, trace_id}` contract and never echo input.
- README quick start works: dev credentials are printed, `frontend/serve.sh` is
  executable, local CORS is allowed by default in dev.
- `workbench_entry` is recorded once a session exists; CTAs no longer duplicate.

### Added
- Message lifecycle (`pending → streaming → done | error | interrupted`), restart
  reconciliation, versioned schema migrations (`schema_version`).
- `GET /v1/chat/sessions` (own chats), `DELETE /v1/chat/sessions/{id}` (erasure),
  `GET /v1/usage`, `/healthz`, `GET /v1/risk/audit/verify`.
- Retention: conversations deleted after `CHAT_RETENTION_DAYS` (default 30).
- Page: stop button (Esc), delayed thinking indicator, retry for unsent messages,
  status chip with heartbeat, session in URL and past chats, two-click delete,
  usage and cost meter, ⌘/Ctrl+K palette, `?` sheet, `/`, G-chords, full zh/en.
- Bilingual CTAs (`?lang=` / `Accept-Language`).
- JSON logs with trace ids; event severity taxonomy; `reply_success_ratio` in metrics.
- Ops: `scripts/backup.py`, `scripts/restore_drill.py` (records RTO/RPO),
  `scripts/audit_anchor.py`; docs: RUNBOOK, PRIVACY, SLO, ARCHITECTURE, PRODUCT.
- CI: blocking ruff + mypy, traceability matrix check, OpenAPI contract snapshot,
  node tests, browser end-to-end gate (33 checks), fail-closed licence gate.

### Changed
- `POST /v1/risk/kill` and `/unkill` return `202` with a challenge instead of acting.
- `/v1/metrics/summary`, `/v1/risk/*` need `CHAT_ADMIN_KEY`; `/v1/memory/*` and
  `/v1/llm/route` need `CHAT_API_KEY`; the chat endpoints accept a visitor token or
  the service key.
- `POST /v1/events` accepts only `cta_click`, `workbench_entry`, `module_switch`.
- `max_tokens` defaults to 1024 and is capped (`CHAT_LLM_MAX_TOKENS[_CAP]`).

## [0.1.0-dev] — 2026-10-23

Initial P0 scope: chat sessions with SSE, LLM router, memory endpoints, module kill
switch, funnel CTA and cost accounting, static chat page.
