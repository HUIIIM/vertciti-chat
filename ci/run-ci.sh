#!/bin/bash
# vertciti chat CI: M1 门禁 -> license 扫描 -> pytest。全绿才算过。
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

echo "=== 1/3 M1 zero-dependency gate ==="
bash ci/m1-gate.sh

echo "=== 2/3 SBOM license scan ==="
.venv/bin/python ci/license-scan.py

echo "=== 3/3 pytest ==="
CHAT_ENV=test .venv/bin/python -m pytest tests/ -q

echo "CI: ALL GREEN"
