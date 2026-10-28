#!/usr/bin/env python3
# Copyright (c) 2026 vertciti. All rights reserved.
"""Minimal CycloneDX 1.5 SBOM from the hash-locked backend/requirements.txt
(no third-party tool needed): every component with its exact version, PyPI
purl and the sha256 hashes pip verifies at install time.

    python3 ci/sbom.py <version> > sbom.cdx.json
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "backend" / "requirements.txt"


def components() -> list[dict]:
    out = []
    current: dict | None = None
    for raw in LOCK.read_text().splitlines():
        line = raw.strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\;]+)", line)
        if m:
            current = {"type": "library", "name": m.group(1), "version": m.group(2),
                       "purl": f"pkg:pypi/{m.group(1).lower()}@{m.group(2)}", "hashes": []}
            out.append(current)
        for h in re.findall(r"--hash=sha256:([0-9a-f]{64})", line):
            if current is not None:
                current["hashes"].append({"alg": "SHA-256", "content": h})
    return out


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "0.0.0-dev"
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {"type": "application", "name": "vertciti-chat", "version": version},
        },
        "components": components(),
    }
    json.dump(bom, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
