#!/usr/bin/env bash
# End-to-end gate: mock runtime (:8100) + backend (:8120) + frontend (:3120),
# then ci/e2e_chat.js drives the real page in Chromium.
#   ci/check-e2e.sh   (needs node + playwright on NODE_PATH, and PY with the backend deps)
set -uo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
WORK=$(mktemp -d)
export CHAT_ENV=dev CHAT_DB_PATH="$WORK/e2e.db"
CHAT_ADMIN_KEY=$($PY -c "import secrets;print(secrets.token_urlsafe(24))")
export CHAT_ADMIN_KEY
export CHAT_RETENTION_DAYS=30

$PY ci/mock_runtime.py 8100 & RT=$!
(cd backend && exec ../$PY -m uvicorn app.main:app --host 127.0.0.1 --port 8120 --no-access-log) \
  >"$WORK/backend.log" 2>&1 & BE=$!
python3 frontend/serve.py --port 3120 >"$WORK/frontend.log" 2>&1 & FE=$!
trap 'kill $RT $BE $FE 2>/dev/null; rm -rf "$WORK"' EXIT

for _ in $(seq 1 40); do
  curl -sf http://127.0.0.1:8120/health >/dev/null && curl -sf http://127.0.0.1:3120/ >/dev/null && break
  sleep 0.25
done
node ci/e2e_chat.js
status=$?
if [ $status -ne 0 ]; then echo "--- backend log (tail)"; tail -30 "$WORK/backend.log"; fi
exit $status
