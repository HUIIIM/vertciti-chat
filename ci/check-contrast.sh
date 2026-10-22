#!/usr/bin/env bash
# Contrast gate: the chat page, idle and "sending" (all controls disabled), light + dark, phone + desktop.
# Any visible text - incl. disabled buttons and placeholders - below WCAG AA fails.
#   ci/check-contrast.sh        (needs node + the playwright package on NODE_PATH)
set -uo pipefail
cd "$(dirname "$0")/.."
PORT=${PORT:-3129}
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory frontend >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER' EXIT
sleep 1
fails=0
for s in light dark; do for w in 390 1280; do
  node ci/contrast_audit.js "http://127.0.0.1:$PORT/" --scheme $s --width $w || fails=$((fails + 1))
  node ci/contrast_audit.js "http://127.0.0.1:$PORT/" --scheme $s --width $w --inject ci/contrast-states.html || fails=$((fails + 1))
done; done
echo "contrast gate: $fails failing run(s)"
exit $((fails > 0))
