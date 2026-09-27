# PORTS.md — vertciti chat 端口约定

本约定自 2026-09-27 生效。不得占用 translator（8000/3000）与 anomalies 运行时
（8100/3100）的端口。

## 约定表

| 用途 | 端口 | 备注 |
|---|---|---|
| chat **后端 dev**（uvicorn） | **8120** | `backend/run.sh`；`backend/app/main.py` 的 `__main__` 默认值 |
| chat **前端 dev**（静态） | **3120** | `frontend/serve.sh`（`python3 -m http.server 3120`） |
| anomalies 运行时后端（HTTP 集成） | 8100 | ❌ **禁止占用** — 仅经 HTTP 产品面调用（M1），`ANOMALIES_BASE_URL` 可配 |
| translator 项目 | 8000 / 3000 | ❌ **禁止占用** |

## 端口被占时的处理流程

1. 先查是谁占着：`lsof -i :8120` 或 `ss -ltnp | grep :8120`。
2. 是自己残留进程 → kill 后重起；是别人的服务 → **绝不抢**，换端口（+100，如 8220/3220）。
3. 换端口后同步改 `backend/run.sh`、`frontend/serve.sh`、`frontend/app.js` 的默认
   `CHAT_API_BASE`，并在本文件"偏离记录"登记（日期＋原因＋当前值）。

## 偏离记录

（暂无偏离；保持为空即表示一切按约定表执行。）
