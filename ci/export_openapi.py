#!/usr/bin/env python3
# Copyright (c) 2026 vertciti. All rights reserved.
"""Write the API contract snapshot (docs/openapi.json) from the running app
definition. tests/test_contract.py fails when the code and the snapshot
disagree, so every API change is a reviewed diff of this file (SOTA VER-5)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "openapi.json"


def schema() -> dict:
    os.environ.setdefault("CHAT_ENV", "test")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import create_app

    return create_app().openapi()


def render() -> str:
    return json.dumps(schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
