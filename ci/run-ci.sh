#!/bin/bash
# vertciti chat local CI: the same gates as .github/workflows/ci.yml.
# Browser gates run when Playwright is available (NODE_PATH or ci/node_modules).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PY=.venv/bin/python
[ -x "$PY" ] || { python3 -m venv .venv; .venv/bin/pip install -q --require-hashes -r backend/requirements-dev.txt; }

echo "=== ruff / mypy / pytest ==="
.venv/bin/ruff check .
.venv/bin/mypy
$PY -m pytest -q
echo "=== traceability matrix ==="
$PY ci/trace_matrix.py --check
echo "=== M1 zero-dependency gate ==="
bash ci/m1-gate.sh
echo "=== licence gate ==="
$PY ci/license-scan.py
echo "=== frontend ==="
(cd frontend && npm test --silent && npm run build --silent)
if [ -d ci/node_modules/playwright ] || node -e "require('playwright')" 2>/dev/null; then
  export NODE_PATH="${NODE_PATH:-$REPO/ci/node_modules}"
  echo "=== contrast ==="; ci/check-contrast.sh
  echo "=== end-to-end ==="; ci/check-e2e.sh
else
  echo "(browser gates skipped: install with 'cd ci && npm ci && npx playwright install chromium')"
fi
echo "CI: ALL GREEN"
