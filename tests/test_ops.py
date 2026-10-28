# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Operational scripts keep working: backup, restore drill, audit anchor."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run(*args, env_db=None):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "CHAT_ENV": "test",
                               **({"CHAT_DB_PATH": env_db} if env_db else {})}, timeout=120)


@pytest.fixture()
def live_db(client, auth_headers, admin_headers, tmp_path):
    from conftest import kill

    sid = client.post("/v1/chat/sessions", json={}, headers=auth_headers).json()["session_id"]
    client.post(f"/v1/chat/sessions/{sid}/messages", json={"content": "inline keep me"}, headers=auth_headers)
    kill(client, admin_headers)
    from app import db as _db
    return _db.get_store().path


@pytest.mark.req("OPS-1")
def test_backup_and_restore_drill_pass(live_db, tmp_path):
    r = _run("scripts/backup.py", "--db", live_db, "--dir", str(tmp_path / "bk"), "--keep", "2")
    assert r.returncode == 0, r.stderr
    assert len(list((tmp_path / "bk").glob("chat-*.db"))) == 1
    assert "same machine only" in r.stderr  # honest when no off-site copy is configured
    d = _run("scripts/restore_drill.py", "--db", live_db)
    assert d.returncode == 0, d.stdout + d.stderr
    assert "restore drill: PASS" in d.stdout


@pytest.mark.req("SEC-A4")
def test_audit_anchor_prints_head_and_refuses_broken_chain(live_db):
    r = _run("scripts/audit_anchor.py", "--db", live_db)
    assert r.returncode == 0, r.stderr
    anchor = json.loads(r.stdout)
    assert len(anchor["head"]) == 64 and anchor["rows"] >= 2

    import sqlite3
    conn = sqlite3.connect(live_db)
    conn.execute("UPDATE audit_log SET actor='ghost' WHERE id=(SELECT MIN(id) FROM audit_log)")
    conn.commit()
    conn.close()
    bad = _run("scripts/audit_anchor.py", "--db", live_db)
    assert bad.returncode == 2
    assert bad.stdout == ""
