#!/bin/bash
# vertciti chat kill drill（手动验证，契约 §5）：
# 访客建会话 -> 发消息（通） -> kill（两步：prepare + confirm） -> 发消息（503 chat_killed） ->
# 新访客被拦 -> unkill（两步） -> 发消息（通） -> 审计链校验通过。
#
#   CHAT_ADMIN_KEY=... scripts/kill-drill.sh      (dev: run.sh prints the key at startup)
set -euo pipefail

BASE="${CHAT_BASE:-http://127.0.0.1:8120}"
ADMIN="${CHAT_ADMIN_KEY:?请先 export CHAT_ADMIN_KEY（dev 启动时打印）}"
JSON=(-H "Content-Type: application/json")

pass=0; fail=0
check() { # check <desc> <expected_code> <curl_args...>
  local desc="$1" want="$2"; shift 2
  local code
  code=$(curl -s "${JSON[@]}" -o /dev/null -w "%{http_code}" "$@")
  if [ "$code" = "$want" ]; then echo "PASS: $desc ($code)"; pass=$((pass+1));
  else echo "FAIL: $desc (want $want, got $code)"; fail=$((fail+1)); fi
}
field() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }

# two-step risk action: prepare -> confirm with the exact phrase
risk() { # risk kill|unkill
  local body prep cid phrase
  if [ "$1" = kill ]; then body='{"scope":"module","reason_code":"drill","actor":"kill-drill"}';
  else body='{"scope":"module","actor":"kill-drill"}'; fi
  prep=$(curl -s "${JSON[@]}" -H "X-API-Key: $ADMIN" -X POST "$BASE/v1/risk/$1" -d "$body")
  cid=$(echo "$prep" | field challenge_id); phrase=$(echo "$prep" | field confirm_phrase)
  check "$1 confirm" 200 -H "X-API-Key: $ADMIN" -X POST "$BASE/v1/risk/confirm" \
    -d "{\"challenge_id\":\"$cid\",\"confirm_phrase\":\"$phrase\"}"
}

echo "== kill drill =="
VT=$(curl -s -X POST "$BASE/v1/visitor" | field visitor_token)
V=(-H "X-Visitor-Token: $VT")
SID=$(curl -s "${JSON[@]}" "${V[@]}" -X POST "$BASE/v1/chat/sessions" -d '{}' | field session_id)
echo "session: $SID"

check "发消息（kill 前应通）" 200 "${V[@]}" -X POST "$BASE/v1/chat/sessions/$SID/messages" -d '{"content":"drill ping"}'
risk kill
check "发消息（kill 后应 503）" 503 "${V[@]}" -X POST "$BASE/v1/chat/sessions/$SID/messages" -d '{"content":"blocked?"}'
check "新访客（kill 后应 503）" 503 -X POST "$BASE/v1/visitor"
check "读自己的会话（kill 后仍可）" 200 "${V[@]}" "$BASE/v1/chat/sessions/$SID"
risk unkill
check "发消息（恢复后应通）" 200 "${V[@]}" -X POST "$BASE/v1/chat/sessions/$SID/messages" -d '{"content":"recovered"}'

VERIFY=$(curl -s -H "X-API-Key: $ADMIN" "$BASE/v1/risk/audit/verify")
if [ "$(echo "$VERIFY" | field ok)" = "True" ]; then echo "PASS: 审计链完好"; pass=$((pass+1));
else echo "FAIL: 审计链校验失败: $VERIFY"; fail=$((fail+1)); fi

echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
