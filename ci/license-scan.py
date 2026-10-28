#!/usr/bin/env python3
# Copyright (c) 2026 vertciti. All rights reserved.
# vertciti clean-room SBOM license gate: every pinned dependency in
# backend/requirements.txt must have a permissive license; copyleft blocks
# the build. License facts are fetched from PyPI metadata (no vendored data).

import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REQ = REPO / "backend" / "requirements.txt"

COPYLEFT = re.compile(r"GNU (General|Affero|Lesser)|AGPL|GPL|SSPL|Polyform|BUSL|CC-BY-NC", re.IGNORECASE)
PERMISSIVE = re.compile(r"MIT|Apache|BSD|ISC|PSF|Python Software|MPL|Unlicense|CC0|WTFPL", re.IGNORECASE)


def pypi_license(name: str):
    url = f"https://pypi.org/pypi/{name}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "vertciti-chat-ci/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        info = json.load(resp)["info"]
    lic = info.get("license") or ""
    expr = info.get("license_expression") or ""
    classifiers = " ".join(info.get("classifiers") or [])
    label = expr or lic or classifiers[:80]
    return f"{lic} {expr} {classifiers}", label.strip()


def main() -> int:
    strict = "--strict" in sys.argv
    failed, warned = [], []
    for line in REQ.read_text().splitlines():
        # hash-locked lock file: one "name==version \" line per package,
        # followed by "--hash=..." and "# via" lines that are not packages
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.\-]*)==", line)
        if not m:
            continue
        name = m.group(1)
        try:
            blob, label = pypi_license(name)
        except Exception as e:  # noqa: BLE001 - network hiccup: fail closed in strict, warn otherwise
            (failed if strict else warned).append(f"{name}: metadata fetch failed ({e})")
            continue
        if COPYLEFT.search(blob):
            failed.append(f"{name}: copyleft license detected: {label}")
        elif not PERMISSIVE.search(blob):
            warned.append(f"{name}: license unclear: {label or '(empty metadata)'}")
        else:
            print(f"  ok  {name}: {label[:60]}")
    for w in warned:
        print(f"  warn {w}")
    for f in failed:
        print(f"  FAIL {f}")
    if failed:
        print("license gate: FAILED")
        return 1
    print("license gate: PASS" + (" (with warnings)" if warned else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
