# vertciti chat

vertciti 的聊天助手工程（codename `chat`，module id `chat`）：FastAPI 后端加静态聊天界面。访客免费、免注册提问，
运营方掌握额度、成本、审计与两步急停；它通过 HTTP 调用 anomalies clean-room 运行时，是 chatbot clean-room 重建的第二步。

| | |
|---|---|
| 状态 | 开发中 · 0.2.0 未发布（独立 SOTA 评估整改版，见 [CHANGELOG](CHANGELOG.md)）；dev 模式运行，LLM 和 anomalies 运行时未配置时诚实返回 503 |
| CI | GitHub Actions：ruff、mypy、pytest、需求追溯矩阵、M1 门禁、licence 门禁（均阻断）· 前端单测 · 浏览器对比度与端到端门禁 · CodeQL · 依赖审查 · gitleaks · OpenSSF Scorecard；全部 action 按提交 SHA 固定 |
| 部署 | 自部署（dev）：Python 后端（3.13）`:8120` + 静态前端 `:3120`，SQLite，单进程（见 [RUNBOOK](docs/RUNBOOK.md)） |
| 在线演示 | 尚未部署 |
| 接口 | Web 聊天界面（匿名访客令牌，无需 key）· HTTP API（会话 / SSE 流、LLM 路由、记忆、两步急停、漏斗与埋点），契约快照 [docs/openapi.json](docs/openapi.json) |
| 许可证 | 专有（proprietary），见 [LICENSE](LICENSE) |
| 语言 | 简体中文 / English（界面与 CTA 双语） |
| 联系 | 安全漏洞：[SECURITY.md](.github/SECURITY.md) · 产品：[vertciti.com](https://vertciti.com) |

## 概览

本工程在 anomalies clean-room 运行时之上重建 chat。用户可见的名称暂定为 **vertciti 智能助手 / vertciti Assistant**
（纯描述性命名；终名由品牌设计组和 GC 确认），旧项目名称不出现在代码和用户可见面。

与 anomalies 运行时的关系是 **HTTP 集成**（M1 双向零依赖）：只调用 `POST /api/v1/chat` 与
`GET /api/v1/chat/stream?run_id=`，不 import 其代码，不共享包、库或密钥。2023 旧线只作为只读学习材料，没有抄写
任何一行，由 CI 门禁强制检查。产品一页纸见 [docs/PRODUCT.md](docs/PRODUCT.md)，架构见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 能力一览

| # | 能力 | 落点 |
|---|---|---|
| 1 | 会话 API（建 / 列 / 读 / 删 / 发消息 / SSE 流） | `chat_api.py`：会话归属调用者（他人 404）；回复生命周期 `pending → streaming → done \| error \| interrupted`；回放不重复调用运行时 |
| 2 | 三类主体 | `auth.py`：匿名访客令牌（`POST /v1/visitor`，HMAC 签名）· 服务 key `CHAT_API_KEY` · 运营 key `CHAT_ADMIN_KEY`；每条路由有越权回归测试 |
| 3 | 额度与限流 | `rate_limit.py`：主体与 IP 两个分钟桶；每访客 + 每 IP 日额度（原子扣减，UTC 日）；429 带 `retry-after` |
| 4 | 两步急停 | `kill.py`：prepare → `/v1/risk/confirm` 输入确认短语（120 s 内），仅 admin；停止全部产生模型工作的入口，读取与删除照常 |
| 5 | 审计 | `audit.py`：哈希链，`/v1/risk/audit/verify` 重算；`scripts/audit_anchor.py` 输出每日链头供外部锚定 |
| 6 | 有界流 | `anomalies_client.py`：异步、空闲超时、总时限、字数上限；一个慢请求不会卡住其他人 |
| 7 | LLM 路由（契约 §2.1） | `llm.py`：module 服务端绑定 `chat`；policy → env 映射；`budget_units` 熔断；`max_tokens` 默认与封顶；按调用者隔离的幂等键 |
| 8 | 记忆（契约 §2.2） | `memory_api.py` + `memory_store.py`：仅服务 key；模块隔离；PII 字段名或点路径脱敏；命名空间按字面前缀匹配；TTL |
| 9 | 诚实标签 | 全部响应带 `honesty`；`/health` 与 `/healthz` 分组件标注（数据库不可用 503、急停状态）；不可用时不编造回复 |
| 10 | 漏斗与成本 | `funnel.py`：双语 CTA（UTM）；事件白名单 + 严重度；admin 指标给出单线索成本与回复成功率 |
| 11 | 前端 | `frontend/`：无内联脚本（严格 CSP）、停止 / 重试 / 历史 / 删除、状态心跳、用量与成本、⌘/Ctrl+K 指令面板与 `?` 快捷键表、中英双语、移动端与深色模式 |
| 12 | 数据保留 | `retention.py`：对话默认 30 天删除；随时删除本对话；见 [PRIVACY](docs/PRIVACY.md) |

## 快速开始

```bash
git clone https://github.com/HUIIIM/vertciti-chat.git && cd vertciti-chat
./backend/run.sh      # :8120；首次运行创建 .venv 并按哈希安装依赖；打印本进程的 dev 服务 key 与 admin key
./frontend/serve.sh   # :3120；浏览器打开 http://127.0.0.1:3120，直接提问（页面自动领取匿名访客令牌）
# 联调 anomalies 运行时（另一工程，HTTP 调用）：按其 README 在 :8100 启动；
# 没有运行时可用 python3 ci/mock_runtime.py 8100 代替
```

检查与测试（与 CI 相同的门禁）：

```bash
bash ci/run-ci.sh     # ruff · mypy · pytest · 追溯矩阵 · M1 · licence · 前端单测（装了 Playwright 时含浏览器门禁）
```

全部环境变量及默认值见 [`.env.example`](.env.example)。最常用的：

| 变量 | 说明 |
|---|---|
| `CHAT_ENV` | `dev`（默认）/ `test` / `prod`；prod 缺少下面三项、CORS 或数据库路径时拒绝启动 |
| `CHAT_API_KEY` / `CHAT_ADMIN_KEY` / `CHAT_VISITOR_SECRET` | 服务 key / 运营 key / 访客令牌签名密钥；dev 未设置时按进程生成 |
| `CHAT_CORS_ORIGINS` | 跨域白名单；dev 默认放行 `http://127.0.0.1:3120` 与 `http://localhost:3120` |
| `ANOMALIES_BASE_URL` / `ANOMALIES_API_KEY` | 运行时地址与 Bearer key |
| `CHAT_LLM_BASE_URL` / `CHAT_LLM_API_KEY` / `CHAT_MODEL_*` | OpenAI 兼容 endpoint 与 policy → 模型映射 |
| `CHAT_RETENTION_DAYS` | 对话保留天数（默认 30） |

## 目录

```
vertciti-chat/
  backend/app/          FastAPI 后端（见 docs/ARCHITECTURE.md）
  backend/requirements.in / .txt          运行依赖（.txt 为哈希锁定）
  backend/requirements-dev.in / .txt      测试与检查工具（哈希锁定）
  frontend/             静态页（index.html / app.js / i18n.js / shortcuts.js / style.css / serve.py）
  tests/                pytest（每个测试标注需求 id）
  ci/                   门禁脚本、端到端、追溯矩阵、OpenAPI 快照、SBOM
  scripts/              kill-drill.sh · backup.py · restore_drill.py · audit_anchor.py
  docs/                 PRODUCT · ARCHITECTURE · RUNBOOK · PRIVACY · SLO · openapi.json · assurance/ · ops/
```

端口约定见 [PORTS.md](PORTS.md)。

## 安全与合规

- **主体分离**：浏览器只持有匿名访客令牌，只能碰自己的对话；服务 key 与运营 key 分开，运营 key 不进浏览器。
- **审计**：哈希链能发现对单行的改动或删除；拥有数据库写权限者仍可整链重写，防线是每日把链头锚定到系统之外
  （[RUNBOOK §5](docs/RUNBOOK.md)）。外部锚定存储尚待运营方建立。
- **零依赖**（M1）：与 anomalies 运行时仅 HTTP 集成，不 import 其代码、不共享包 / 库 / 密钥。
- **密钥管理**：无硬编码密钥；key 只走环境变量或进程内存，不落盘、不进日志；日志为 JSON，只记方法、路径、状态、耗时与 trace id。
- **供应链**：action 按 SHA 固定；Python 依赖按哈希安装；Playwright 按 lockfile 安装；发布产物带 SBOM 与来源证明。
- **响应头**：API 与静态页均发出 CSP、nosniff、frame 拒绝与 Referrer-Policy；prod 关闭 `/docs`。
- **工程纪律**：clean-room，每个文件带 vertciti clean-room 版权头；禁发事项不进文档或代码注释，无依据数字不写。
- 安全漏洞请私下报告，见 [SECURITY.md](.github/SECURITY.md)。

## 现状与边界（dev）

- 已实现并有测试：会话、主体与越权、额度、两步急停、审计链、有界流、记忆、LLM 路由、保留与删除、前端全部状态。
- LLM 路由：未配置 `CHAT_LLM_BASE_URL` 和 key 时返回 503，不伪造输出；`fallback_chain` 尚无备用模型，`fallback_used` 恒为 false。
- 单进程单实例：分钟限流桶在内存中；多 worker 前需外置（[ARCHITECTURE](docs/ARCHITECTURE.md)）。
- 记忆 recall：SQLite 关键词实现；语义向量检索待底座 P。平台级 kill：底座 P 未建，hook 预留并如实标注。
- 异地备份目标、审计外部锚定存储、告警接入、隐私政策法务确认：尚未完成，需运营方决定。
- 尚未部署公网实例。

路线图见 [ROADMAP.md](ROADMAP.md)。

## 文档 · 支持 · 许可证

- [CHANGELOG.md](CHANGELOG.md) · [docs/PRODUCT.md](docs/PRODUCT.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
  [docs/RUNBOOK.md](docs/RUNBOOK.md) · [docs/PRIVACY.md](docs/PRIVACY.md) · [docs/SLO.md](docs/SLO.md) ·
  [需求追溯矩阵](docs/assurance/traceability.md) · [恢复演练记录](docs/ops/restore-drills.md)
- [ROADMAP.md](ROADMAP.md) · [PORTS.md](PORTS.md) · [AGENTS.md](AGENTS.md) · 贡献：[CONTRIBUTING.md](.github/CONTRIBUTING.md)
- 安全：[SECURITY.md](.github/SECURITY.md)
- 许可证：专有（proprietary），见 [LICENSE](LICENSE)。第三方依赖哈希锁定于 `backend/requirements.txt`，许可证由
  `ci/license-scan.py` 在每次 CI 中检查（失败即阻断）。字体 Nunito Sans 为 SIL OFL，见 `frontend/fonts/OFL.txt`。

---

Built by [vertciti](https://vertciti.com) — https://vertciti.com
