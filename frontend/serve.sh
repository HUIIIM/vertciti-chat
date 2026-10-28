#!/bin/bash
# vertciti chat frontend dev server (port 3120 per PORTS.md).
set -euo pipefail
# PORTS.md 约定端口占用自检：被占用则报错退出，不静默顶掉
if (exec 3<>/dev/tcp/127.0.0.1/3120) 2>/dev/null; then
  echo "端口 3120 已被占用，拒绝启动（见 PORTS.md）" >&2
  exit 1
fi
cd "$(dirname "$0")"
python3 -m http.server 3120
