#!/bin/bash
# vertciti chat kill drill（手动验证，契约 §5）：
# 建会话 -> 发消息（通） -> kill module -> 发消息（503 chat_killed） ->
# stream 被拦 -> unkill -> 发消息（通） -> 审计留痕。
set -euo pipefail

BASE="${CHAT_BASE:-http://127.0.0.1:8120}"
KEY="${CHAT_API_KEY:?请先 export CHAT_API_KEY（dev 启动时打印的一次性 key）}"
H=(-s -H "X-API-Key: $KEY" -H "Content-Type: application/json")

pass=0; fail=0
check() { # check <desc> <expected_code> <curl_args...>
  local desc="$1" want="$2"; shift 2
  local code
  code=$(curl "${H[@]}" -o /dev/null -w "%{http_code}" "$@")
  if [ "$code" = "$want" ]; then echo "PASS: $desc ($code)"; pass=$((pass+1));
  else echo "FAIL: $desc (want $want, got $code)"; fail=$((fail+1)); fi
}

echo "== kill drill =="
SID=$(curl "${H[@]}" -X POST "$BASE/v1/chat/sessions" -d '{}' | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
echo "session: $SID"

check "发消息（kill 前应通）" 200 -X POST "$BASE/v1/chat/sessions/$SID/messages" -d '{"content":"drill ping"}'
check "kill module" 200 -X POST "$BASE/v1/risk/kill" -d '{"scope":"module","reason_code":"drill","actor":"kill-drill"}'
check "发消息（kill 后应 503）" 503 -X POST "$BASE/v1/chat/sessions/$SID/messages" -d '{"content":"blocked?"}'
check "stream（kill 后应 503）" 503 "$BASE/v1/chat/sessions/$SID/stream?message_id=zzz"
check "llm route（kill 后应 503）" 503 -X POST "$BASE/v1/llm/route" \
  -d '{"model_policy":"default","messages":[],"idempotency_key":"drill-1"}'
check "unkill" 200 -X POST "$BASE/v1/risk/unkill" -d '{"scope":"module","actor":"kill-drill"}'
check "发消息（恢复后应通）" 200 -X POST "$BASE/v1/chat/sessions/$SID/messages" -d '{"content":"recovered"}'

AUDIT=$(curl "${H[@]}" "$BASE/v1/risk/audit")
echo "$AUDIT" | grep -q "risk.kill" && echo "PASS: 审计含 risk.kill" && pass=$((pass+1)) || { echo "FAIL: 审计缺 risk.kill"; fail=$((fail+1)); }

echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
