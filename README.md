# vertciti chat（codename `chat`，module id `chat`）

chatbot clean-room 重建项目第二步：在 anomalies clean-room 运行时之上重建的
chat 新工程。**P0 范围，全部带测试。**

- 用户可见 interim 名：**vertciti 智能助手 / vertciti Assistant**（纯描述性命名；
  <!-- TODO(brand): 终名走品牌设计组＋GC 确认，本任务不定终名 -->
  旧项目名称（D146）永不出现在代码与用户可见面）。
- 与 anomalies 运行时的关系：**HTTP 集成**（M1/D147 双向零依赖铁律）——只调
  `POST /api/v1/chat` 与 `GET /api/v1/chat/stream?run_id=`；不 import 其代码、
  不共享包/库/密钥。2023 旧线为只读学习材料，一行未抄（CI 门禁 enforcement）。

## 目录

```
vertciti-chat/
  backend/app/        FastAPI 后端（chat_api / llm / memory_api+memory_store /
                      kill / funnel / auth / rate_limit / audit / anomalies_client）
  backend/requirements.txt  （版本锁定）
  backend/run.sh      后端 dev 启动（:8120）
  frontend/           静态 chat UI（index.html / app.js / style.css / serve.sh :3120）
  tests/              pytest（conftest 统一 fixture）
  ci/                 m1-gate.sh / license-scan.py / run-ci.sh
  scripts/            kill-drill.sh（手动 kill 演练）
  PORTS.md ROADMAP.md README.md LICENSE
```

## 快速启动

```bash
cd ~/workspace/vertciti-chat
./backend/run.sh            # :8120，首次启动打印 dev API key（仅进程内存，不落盘）
./frontend/serve.sh         # :3120，浏览器打开 http://127.0.0.1:3120
# 联调 anomalies 运行时（另一工程，HTTP 调用）：
#   cd ~/workspace/anomalies-autogpt/backend && <其 README 的 :8100 启动方式>
```

环境变量（全部可选，有 dev 默认值；key 类只读 env/进程内存）：

| 变量 | 说明 |
|---|---|
| `CHAT_API_KEY` | 本服务 API key；未设则启动时生成一次性内存 key 并打印 |
| `CHAT_ENV` | `dev`（默认）/ `test` / `prod` |
| `ANOMALIES_BASE_URL` | 运行时地址（默认 `http://127.0.0.1:8100`） |
| `ANOMALIES_API_KEY` | 运行时 Bearer key（transient，不落盘不记日志） |
| `CHAT_MODEL_DEFAULT/_QUALITY/_CHEAP` | model_policy→模型 ID 映射（**不硬编码模型 ID**） |
| `CHAT_LLM_BASE_URL` / `CHAT_LLM_API_KEY` | OpenAI-compatible LLM endpoint |
| `CHAT_LLM_PROVIDER=fake` | 确定性测试替身 |
| `CHAT_PRICE_TABLE` | JSON：各 policy 每 1M tokens 的进/出价（整数分） |
| `CHAT_RATE_PER_MINUTE` / `CHAT_DAILY_MESSAGE_LIMIT` | 限流配额（默认 60/200） |
| `CHAT_CORS_ORIGINS` | 跨域白名单（默认空=拒绝跨域） |
| `CHAT_DB_PATH` | sqlite 路径（默认 `backend/data/chat.db`） |

## P0 对照（任务清单 → 落点）

| # | 要求 | 落点 |
|---|---|---|
| 1 | 会话 API（建会话/发消息/SSE 流） | `chat_api.py`：`POST /v1/chat/sessions`、`POST …/messages`（`stream:true`→`stream_url`）、`GET …/stream`（SSE 第一天即有） |
| 2 | LLM 路由（契约 §2.1） | `llm.py`＋`main.py:/v1/llm/route`：module 服务端绑定 `chat`；policy→env 映射；`budget_units` 熔断；幂等键；key 零落盘 |
| 3 | 记忆三端点（契约 §2.2） | `memory_api.py`＋`memory_store.py`：store/recall/forget；`module_id='chat'` 行级隔离；跨模块 403＋审计；pii 脱敏；TTL；`MemoryStore` 委托接口（pgvector 待底座 P） |
| 4 | 鉴权＋限流（E5/E6） | `auth.py`（API key，常量时间比较，hash 计数）＋`rate_limit.py`（分钟桶＋日配额；429 带 `retry-after`） |
| 5 | Kill switch 两级 | `kill.py`：`POST /v1/risk/kill` scope=module 真生效（503 `chat_killed`）/scope=platform 诚实预留 hook；审计；`scripts/kill-drill.sh` |
| 6 | 🟢🟡⚪ 诚实标签 | 全响应 `honesty` 字段；`/health` 分组件标注；dev/过渡态一律 🟡，不用 🟡 充 🟢 |
| 7 | 漏斗 CTA（契约 §2.5） | `funnel.py`：`GET /v1/cta/funnel`（`utm_source=workbench&utm_medium=chat`）；全免费无付费墙 |
| 8 | 前端聊天 UI | `frontend/`：vertciti 品牌小写、SSE 实时输出、诚实徽章、移动端可用 |
| 9 | CI 门禁 | `ci/m1-gate.sh`（2023 标识＋D146 旧称命中即失败）＋`ci/license-scan.py`（copyleft 阻断） |
| 10 | 成本＋转化埋点 | 每次 LLM 调用记 tokens/费用（整数分）；`POST /v1/events`（`cta_click` 等）；`GET /v1/metrics/summary` 给出"单线索成本" |

## 诚实状态（dev）

- 🟢 chat API / 记忆 / kill switch / 鉴权限流：已实现＋测试覆盖。
- 🟡 LLM 路由：未配 `CHAT_LLM_BASE_URL`＋key 前为"未配置"态，诚实 503，不伪造。
- 🟡 anomalies 运行时：独立服务；连不上时消息接口诚实 503、SSE 发 `error` 事件。
- 🟡 记忆 recall：sqlite 关键词实现；语义向量检索待底座 P（接口已委托，不硬耦合）。
- 🟡 平台总 kill：P 未建，hook 预留（`/v1/risk/status` 如实标注未连接）。

## 测试

```bash
./.venv/bin/python -m pytest tests/ -q   # 或 bash ci/run-ci.sh（一键：门禁+license+测试）
```

## 纪律

- D67 clean-room：2023 旧线只读学习，本工程每一行均为独立表达；文件头带
  vertciti clean-room 版权头。
- M1/D147：与 anomalies 运行时、2023 线之间只允许 HTTP 产品面调用。
- D142：禁发事项不进文档/代码注释；无依据数字不写；引用决策用 D 编号。
- 密钥：只读进程内存/env，永不落盘、不进日志（access 日志只记方法/路径/状态码）。

## 安全设计

- **治理模块**：`backend/app/` 下 `kill.py`（熔断/终止）、`audit.py`（审计日志）、`rate_limit.py`（限流）为内置安全治理件，随每次请求链路执行。
- **零依赖铁律**（M1/D147）：与 anomalies 运行时仅 HTTP 集成，不 import 其代码、不共享包/库/密钥。
- **密钥管理**：无硬编码密钥；LLM key 只走环境变量/进程内存。
- **启动自检**：`backend/run.sh`（8120）与 `frontend/serve.sh`（3120）启动前检查端口占用，被占用则拒绝启动（PORTS.md 约定）。
