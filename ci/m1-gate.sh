#!/bin/bash
# vertciti chat — M1 双向零依赖 CI 门禁（阻断式）。
# 扫描新工程源码/文档：命中 2023 线标识（包路径/模块名/仓库名）或 D146 旧称即失败。
# 本脚本自身包含这些模式以便禁止它们，故扫描时排除自身。
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PATTERNS=(
  'vertciti-auto-gpt'
  'vertcity-auto-gpt'
  'VERTCITY-AUTO-GPT'
  'original_autogpt'
  'autogpt_platform'
  'Significant-Gravitas'
  'github-modernize'
  'Anomalies AutoGPT'
  'anomalies autogpt'
)

fail=0
while IFS= read -r -d '' file; do
  case "$file" in
    *m1-gate.sh|*test_m1_gate.py) continue ;;
  esac
  for pat in "${PATTERNS[@]}"; do
    if grep -qiF "$pat" "$file"; then
      echo "M1-GATE FAIL: $file 命中禁用标识: $pat"
      fail=1
    fi
  done
done < <(find . -path ./.venv -prune -o -path ./backend/data -prune -o \
  -type f \( -name '*.py' -o -name '*.js' -o -name '*.html' -o -name '*.css' \
  -o -name '*.md' -o -name '*.sh' -o -name '*.txt' -o -name '*.json' \) -print0)

if [ "$fail" -eq 1 ]; then
  echo "M1 gate: FAILED（疑似违反 D147 双向零依赖 / D146，上报 GC+CEO）"
  exit 1
fi
echo "M1 gate: PASS"
