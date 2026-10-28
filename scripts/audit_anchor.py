#!/usr/bin/env python3
# Copyright (c) 2026 vertciti. All rights reserved.
"""Print today's audit anchor: one JSON line with the verified head hash of the
hash-chained audit log. Append it to a record this system cannot rewrite (a
separate repository, a write-once bucket, a signed tag) once a day; see
docs/RUNBOOK.md. Exits non-zero, printing nothing to anchor, if the chain does
not verify: never anchor a broken chain.

    python3 scripts/audit_anchor.py [--db PATH] >> /path/outside/this/system/anchors.jsonl
    # or against a running server (admin key):
    python3 scripts/audit_anchor.py --url http://127.0.0.1:8120
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def from_db(path: str) -> dict:
    os.environ["CHAT_DB_PATH"] = path
    sys.path.insert(0, str(ROOT / "backend"))
    from app import audit

    return audit.verify()


def from_url(url: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
    if parsed.scheme != "https" and not local:
        raise SystemExit("--url must be https:// (or a local http address)")
    key = os.environ.get("CHAT_ADMIN_KEY", "")
    endpoint = url.rstrip("/") + "/v1/risk/audit/verify"
    req = urllib.request.Request(endpoint, headers={"X-API-Key": key})  # noqa: S310 - scheme checked above
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - scheme checked above
        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser()
    default_db = os.environ.get("CHAT_DB_PATH") or str(ROOT / "backend" / "data" / "chat.db")
    ap.add_argument("--db", default=default_db)
    ap.add_argument("--url", default="")
    args = ap.parse_args()
    result = from_url(args.url) if args.url else from_db(args.db)
    if not result.get("ok"):
        print(f"audit chain BROKEN at row {result.get('first_bad_id')}: do not anchor; "
              "start incident response (docs/RUNBOOK.md)", file=sys.stderr)
        return 2
    print(json.dumps({"date": datetime.now(UTC).date().isoformat(), "module": "chat",
                      "head": result["head"], "rows": result["count"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
