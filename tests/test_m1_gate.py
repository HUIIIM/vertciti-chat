# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""M1 zero-dependency gate as a pytest (mirrors ci/m1-gate.sh).

Forbids any reference to 2023-line package paths / module names / repo names
in either direction, and forbids the retired-name string in code and user-visible text.
"""

import os
import re

REPO = os.path.join(os.path.dirname(__file__), "..")

FORBIDDEN = [
    r"vertciti-auto-gpt",
    r"vertcity-auto-gpt",
    r"VERTCITY-AUTO-GPT",
    r"original_autogpt",
    r"autogpt_platform",
    r"Significant-Gravitas",
    r"github-modernize",
    r"Anomalies AutoGPT",  # retired name: never in code or user-visible text
    r"anomalies autogpt",
]

SKIP_DIRS = {".venv", "__pycache__", ".git", "data", ".pytest_cache"}
# The gate files must name the patterns to forbid them, so they skip themselves;
# ci/m1-gate.sh independently scans the repo excluding itself as well.
SKIP_FILES = {"m1-gate.sh", "test_m1_gate.py"}


def _iter_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f in SKIP_FILES:
                continue
            if f.endswith((".py", ".js", ".html", ".css", ".md", ".sh", ".txt", ".json")):
                yield os.path.join(root, f)


def test_no_2023_identifiers():
    hits = []
    patterns = [(p, re.compile(p, re.IGNORECASE)) for p in FORBIDDEN]
    for path in _iter_files():
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for name, rx in patterns:
            if rx.search(text):
                hits.append(f"{os.path.relpath(path, REPO)}: {name}")
    assert not hits, "M1 gate violations:\n" + "\n".join(hits)
