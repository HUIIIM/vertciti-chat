# Restore drills

Each row is one run of `python3 scripts/restore_drill.py --record`. RTO is the
time from starting the restore to a verified, usable database; RPO is the age
of the backup that was restored. Target: RTO ≤ 15 min, RPO ≤ 24 h, one drill
per quarter at least (docs/RUNBOOK.md).

The 2026-10-28 row was run in a development container against a dev database seeded through
the real API (40 visitors, 200 messages, a kill/confirm cycle). It proves the procedure, not
production timings; the first production drill is due after the first deployment.

| Date (UTC) | Environment | DB size | Tables / rows | RTO (s) | RPO (s) | Audit chain | Result |
|---|---|---|---|---|---|---|---|
| 2026-10-28 02:39 | dev | 364 KiB | 10 / 768 | 0.01 | 0.02 | ok | PASS |
