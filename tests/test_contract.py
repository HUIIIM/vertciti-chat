# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Front-end/back-end contract (VER-5): the committed OpenAPI snapshot must
match the code, and every API path the page calls must exist in it."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.req("VER-5")
def test_openapi_snapshot_matches_code(app):
    committed = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert app.openapi() == committed, (
        "API changed: run `python3 ci/export_openapi.py` and commit docs/openapi.json")


@pytest.mark.req("VER-5")
def test_frontend_calls_only_documented_paths():
    schema = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    templates = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$") for p in schema["paths"]]
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    used = set()
    for literal in re.findall(r'"(/v1/[^"?]*|/health)', js):
        used.add(literal if not literal.endswith("/") else literal + "x")
    # paths built by concatenation: "/v1/chat/sessions/" + id + "/stream"
    for a, b in re.findall(r'"(/v1/chat/sessions/)" \+ encodeURIComponent\([^)]*\) \+ "(/[a-z]+)', js):
        used.add(f"{a}x{b}")
    assert used, "no API paths found in app.js"
    missing = sorted(p for p in used if not any(t.match(p) for t in templates))
    assert not missing, f"app.js calls undocumented paths: {missing}"
