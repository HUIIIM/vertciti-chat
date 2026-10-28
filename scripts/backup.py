#!/usr/bin/env python3
# Copyright (c) 2026 vertciti. All rights reserved.
"""Consistent online backup of the chat SQLite database.

Uses SQLite's backup API (safe while the server is running), writes
`<dir>/chat-<UTC timestamp>.db` plus a `.sha256` file, keeps the newest N, and,
if CHAT_BACKUP_OFFSITE_CMD is set, runs it with the backup path appended so the
copy leaves this machine (e.g. `rclone copy` or `aws s3 cp`; the command is
configured by the operator, never hard-coded here).

    python3 scripts/backup.py [--db PATH] [--dir backups] [--keep 14]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def default_db() -> str:
    return os.environ.get("CHAT_DB_PATH") or str(ROOT / "backend" / "data" / "chat.db")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(db: str, out_dir: Path, keep: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"chat-{stamp}.db"
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(str(target))
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        target.unlink(missing_ok=True)
        raise SystemExit(f"backup failed integrity_check: {ok}")
    (out_dir / (target.name + ".sha256")).write_text(f"{sha256(target)}  {target.name}\n")
    olds = sorted(out_dir.glob("chat-*.db"))[:-keep] if keep > 0 else []
    for old in olds:
        old.unlink(missing_ok=True)
        (out_dir / (old.name + ".sha256")).unlink(missing_ok=True)
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=default_db())
    ap.add_argument("--dir", default=os.environ.get("CHAT_BACKUP_DIR", str(ROOT / "backups")))
    ap.add_argument("--keep", type=int, default=int(os.environ.get("CHAT_BACKUP_KEEP", "14")))
    args = ap.parse_args()
    target = backup(args.db, Path(args.dir), args.keep)
    print(f"backup ok: {target}")
    cmd = os.environ.get("CHAT_BACKUP_OFFSITE_CMD", "")
    if cmd:
        subprocess.run([*shlex.split(cmd), str(target)], check=True)
        subprocess.run([*shlex.split(cmd), str(target) + ".sha256"], check=True)
        print("off-site copy ok")
    else:
        print("WARNING: CHAT_BACKUP_OFFSITE_CMD not set; this backup is on the same machine only",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
