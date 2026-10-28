#!/bin/bash
# vertciti chat backend dev server (port 8120 per PORTS.md).
# First run creates ../.venv and installs the hash-locked requirements.
# Prints the generated dev credentials once (they live only in this process).
set -euo pipefail
# PORTS.md 约定端口占用自检：被占用则报错退出，不静默顶掉
if (exec 3<>/dev/tcp/127.0.0.1/8120) 2>/dev/null; then
  echo "端口 8120 已被占用，拒绝启动（见 PORTS.md）" >&2
  exit 1
fi
cd "$(dirname "$0")"
if [ ! -x ../.venv/bin/uvicorn ]; then
  echo "[chat] creating ../.venv and installing backend/requirements.txt (hash-locked)" >&2
  python3 -m venv ../.venv
  ../.venv/bin/pip install --quiet --require-hashes -r requirements.txt
fi
# Our JSON request log replaces uvicorn's plain access log.
exec ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8120 --no-access-log
