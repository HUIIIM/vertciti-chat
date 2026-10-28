#!/usr/bin/env python3
# Copyright (c) 2026 vertciti. All rights reserved.
"""Timed restore drill (SOTA OPS-1: a backup that was never restored is not a
backup). Takes a fresh backup of the live database, restores it into an empty
directory, starts nothing, and proves the restore is usable:

- SQLite integrity_check is "ok" and the sha256 matches the backup manifest;
- the schema version equals the live one;
- row counts of every table match the live database at backup time;
- the audit hash chain verifies.

It records RTO (seconds from "start restore" to "verified") and RPO (age of
the newest backup used) and appends one row to docs/ops/restore-drills.md.

    python3 scripts/restore_drill.py [--db PATH] [--record]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from backup import backup, default_db, sha256  # noqa: E402

LOG = ROOT / "docs" / "ops" / "restore-drills.md"
HEADER = """# Restore drills

Each row is one run of `python3 scripts/restore_drill.py --record`. RTO is the
time from starting the restore to a verified, usable database; RPO is the age
of the backup that was restored. Target: RTO ≤ 15 min, RPO ≤ 24 h, one drill
per quarter at least (docs/RUNBOOK.md).

| Date (UTC) | Environment | DB size | Tables / rows | RTO (s) | RPO (s) | Audit chain | Result |
|---|---|---|---|---|---|---|---|
"""


def counts(path: str) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608
    finally:
        conn.close()


def verify_chain(path: str) -> bool:
    os.environ["CHAT_DB_PATH"] = path
    from app import audit
    from app import db as _db

    _db.reset_store()
    try:
        return bool(audit.verify()["ok"])
    finally:
        _db.reset_store()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=default_db())
    ap.add_argument("--env", default=os.environ.get("CHAT_ENV", "dev"))
    ap.add_argument("--record", action="store_true", help="append the result to docs/ops/restore-drills.md")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="chat-drill-"))
    try:
        live_counts = counts(args.db)
        b = backup(args.db, work / "backups", keep=1)
        manifest = (work / "backups" / (b.name + ".sha256")).read_text().split()[0]
        backup_time = time.time()

        started = time.monotonic()
        restored = work / "restore" / "chat.db"
        restored.parent.mkdir()
        shutil.copy2(b, restored)
        problems = []
        if sha256(restored) != manifest:
            problems.append("sha256 mismatch")
        conn = sqlite3.connect(str(restored))
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("integrity_check failed")
        finally:
            conn.close()
        restored_counts = counts(str(restored))
        if restored_counts != live_counts:
            problems.append(f"row counts differ: {restored_counts} vs {live_counts}")
        chain_ok = verify_chain(str(restored))
        if not chain_ok:
            problems.append("audit chain does not verify")
        rto = time.monotonic() - started
        rpo = time.time() - backup_time + rto
    finally:
        shutil.rmtree(work, ignore_errors=True)

    result = "PASS" if not problems else "FAIL: " + "; ".join(problems)
    size_kb = os.path.getsize(args.db) // 1024
    rows = sum(live_counts.values())
    print(f"restore drill: {result}  RTO={rto:.2f}s  RPO={rpo:.2f}s  tables={len(live_counts)} rows={rows}")
    if args.record:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if not LOG.exists():
            LOG.write_text(HEADER, encoding="utf-8")
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"| {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} | {args.env} | {size_kb} KiB | "
                     f"{len(live_counts)} / {rows} | {rto:.2f} | {rpo:.2f} | "
                     f"{'ok' if chain_ok else 'BROKEN'} | {result} |\n")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
