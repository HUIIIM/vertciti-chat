# vertciti chat

vertciti 的聊天助手工程（codename `chat`，module id `chat`）：FastAPI 后端加静态聊天界面，面向 vertciti 内部开发与
联调；它通过 HTTP 调用 anomalies clean-room 运行时，是 chatbot clean-room 重建的第二步。

| | |
|---|---|
| 状态 | 开发中 · P0 范围已实现并带测试；dev 模式运行，LLM 和 anomalies 运行时未配置时诚实返回 503。尚无版本号。GitHub Actions 覆盖 pytest（含 M1 门禁测试）、ruff（advisory）、CodeQL、依赖审查、gitleaks 和 OpenSSF Scorecard；license 扫描在本地 `ci/run-ci.sh` 中运行 |
| 部署 | 自部署（dev）：Python 后端（CI 用 3.13）`:8120` + 静态前端 `:3120`，SQLite |
| 在线演示 | 尚未部署 |
| 接口 | Web 聊天界面 · HTTP API（会话 / SSE 流、LLM 路由、记忆、kill switch、漏斗与埋点），API key 鉴权 |
| 许可证 | 专有（proprietary），见 [LICENSE](LICENSE) |
| 语言 | 简体中文 |
| 联系 | 安全漏洞：[SECURITY.md](.github/SECURITY.md) · 产品：[vertciti.com](https://vertciti.com) |

## 概览

本工程在 anomalies clean-room 运行时之上重建 chat，P0 范围全部带测试。用户可见的名称暂定为 **vertciti 智能助手 /
vertciti Assistant**（纯描述性命名；终名由品牌设计组和 GC 确认），旧项目名称（D146）不出现在代码和用户可见面。

与 anomalies 运行时的关系是 **HTTP 集成**（M1/D147 双向零依赖）：只调用 `POST /api/v1/chat` 与
`GET /api/v1/chat/stream?run_id=`，不 import 其代码，不共享包、库或密钥。2023 旧线只作为只读学习材料，没有抄写
任何一行，由 CI 门禁强制检查。

## 能力一览（P0 对照）

| # | 要求 | 落点 |
|---|---|---|
| 1 | 会话 API（建会话 / 发消息 / SSE 流） | `chat_api.py`：`POST /v1/chat/sessions`、`POST …/messages`（`stream:true` 返回 `stream_url`）、`GET …/stream`（SSE） |
| 2 | LLM 路由（契约 §2.1） | `llm.py` + `main.py:/v1/llm/route`：module 服务端绑定 `chat`；policy → env 映射；`budget_units` 熔断；幂等键；key 不落盘 |
| 3 | 记忆三端点（契约 §2.2） | `memory_api.py` + `memory_store.py`：store / recall / forget；`module_id='chat'` 行级隔离；跨模块 403 并审计；PII 脱敏；TTL；`MemoryStore` 委托接口（pgvector 待底座 P） |
| 4 | 鉴权与限流（E5/E6） | `auth.py`（API key，常量时间比较，hash 计数）+ `rate_limit.py`（分钟桶加日配额；429 带 `retry-after`） |
| 5 | 两级 kill switch | `kill.py`：`POST /v1/risk/kill` scope=module 生效（503 `chat_killed`），scope=platform 预留 hook；审计；`scripts/kill-drill.sh` |
| 6 | 诚实标签 | 全部响应带 `honesty` 字段（`🟢` / `🟡`）；`/health` 分组件标注；dev 和过渡态一律 `🟡` |
| 7 | 漏斗 CTA（契约 §2.5） | `funnel.py`：`GET /v1/cta/funnel`（`utm_source=workbench&utm_medium=chat`）；免费，无付费墙 |
| 8 | 前端聊天 UI | `frontend/`：vertciti 品牌小写、SSE 实时输出、诚实标签、移动端可用 |
| 9 | CI 门禁 | `ci/m1-gate.sh`（命中 2023 标识或 D146 旧称即失败；GitHub Actions 通过 `tests/test_m1_gate.py` 执行）+ `ci/license-scan.py`（阻断 copyleft；目前由 `ci/run-ci.sh` 运行） |
| 10 | 成本与转化埋点 | 每次 LLM 调用记录 tokens 和费用（整数分）；`POST /v1/events`（`cta_click` 等）；`GET /v1/metrics/summary` 给出单线索成本 |

## 快速开始

```bash
git clone https://github.com/HUIIIM/vertciti-chat.git && cd vertciti-chat
./backend/run.sh            # :8120，首次启动打印 dev API key（仅进程内存，不落盘）
./frontend/serve.sh         # :3120，浏览器打开 http://127.0.0.1:3120
# 联调 anomalies 运行时（另一工程，HTTP 调用）：按其 README 在 :8100 启动
```

运行测试：

```bash
./.venv/bin/python -m pytest tests/ -q   # 或 bash ci/run-ci.sh（门禁 + license + 测试）
```

环境变量（全部可选，有 dev 默认值；key 类只读 env 或进程内存）：

| 变量 | 说明 |
|---|---|
| `CHAT_API_KEY` | 本服务 API key；未设置时启动生成一次性内存 key 并打印 |
| `CHAT_ENV` | `dev`（默认）/ `test` / `prod` |
| `ANOMALIES_BASE_URL` | 运行时地址（默认 `http://127.0.0.1:8100`） |
| `ANOMALIES_API_KEY` | 运行时 Bearer key（transient，不落盘、不记日志） |
| `CHAT_MODEL_DEFAULT/_QUALITY/_CHEAP` | model_policy → 模型 ID 映射（不硬编码模型 ID） |
| `CHAT_LLM_BASE_URL` / `CHAT_LLM_API_KEY` | OpenAI 兼容的 LLM endpoint |
| `CHAT_LLM_PROVIDER=fake` | 确定性测试替身 |
| `CHAT_PRICE_TABLE` | JSON：各 policy 每 1M tokens 的输入 / 输出价（整数分） |
| `CHAT_RATE_PER_MINUTE` / `CHAT_DAILY_MESSAGE_LIMIT` | 限流配额（默认 60 / 200） |
| `CHAT_CORS_ORIGINS` | 跨域白名单（默认空，即拒绝跨域） |
| `CHAT_DB_PATH` | SQLite 路径（默认 `backend/data/chat.db`） |

## 架构

```
vertciti-chat/
  backend/app/        FastAPI 后端（chat_api / llm / memory_api + memory_store /
                      kill / funnel / auth / rate_limit / audit / anomalies_client）
  backend/requirements.txt  （版本锁定）
  backend/run.sh      后端 dev 启动（:8120）
  frontend/           静态 chat UI（index.html / app.js / style.css / serve.sh :3120）
  tests/              pytest（conftest 统一 fixture）
  ci/                 m1-gate.sh / license-scan.py / run-ci.sh
  scripts/            kill-drill.sh（手动 kill 演练）
  PORTS.md ROADMAP.md README.md LICENSE
```

端口约定见 [PORTS.md](PORTS.md)。

## 安全与合规

- **治理模块**：`backend/app/` 下的 `kill.py`（熔断 / 终止）、`audit.py`（审计日志）、`rate_limit.py`（限流）随每次请求
  链路执行。
- **零依赖**（M1/D147）：与 anomalies 运行时仅 HTTP 集成，不 import 其代码、不共享包 / 库 / 密钥。
- **密钥管理**：无硬编码密钥；LLM key 只走环境变量或进程内存，不落盘、不进日志（access 日志只记方法 / 路径 / 状态码）。
- **启动自检**：`backend/run.sh`（8120）与 `frontend/serve.sh`（3120）启动前检查端口占用，被占用则拒绝启动。
- **工程纪律**：D67 clean-room，每个文件带 vertciti clean-room 版权头；D142，禁发事项不进文档或代码注释，无依据数字不写，
  引用决策用 D 编号。
- 安全漏洞请私下报告，见 [SECURITY.md](.github/SECURITY.md)。

## 现状与边界（dev）

- chat API、记忆、kill switch、鉴权与限流：已实现，有测试覆盖。
- LLM 路由：未配置 `CHAT_LLM_BASE_URL` 和 key 时处于"未配置"态，返回 503，不伪造输出。
- anomalies 运行时：独立服务；连不上时消息接口返回 503，SSE 发送 `error` 事件。
- 记忆 recall：SQLite 关键词实现；语义向量检索待底座 P（接口已委托，不硬耦合）。
- 平台级 kill：底座 P 未建，hook 预留，`/v1/risk/status` 如实标注未连接。
- 尚未部署公网实例。

路线图见 [ROADMAP.md](ROADMAP.md)。

## 文档 · 支持 · 许可证

- [ROADMAP.md](ROADMAP.md) · [PORTS.md](PORTS.md) · [AGENTS.md](AGENTS.md) · 贡献：[CONTRIBUTING.md](.github/CONTRIBUTING.md)
- 安全：[SECURITY.md](.github/SECURITY.md)
- 许可证：专有（proprietary），见 [LICENSE](LICENSE)。第三方依赖版本锁定于 `backend/requirements.txt`，许可证由
  `ci/license-scan.py` 检查（`ci/run-ci.sh` 运行；GitHub Actions 尚未接入）。

---

Built by [vertciti](https://vertciti.com) — https://vertciti.com
