# 架构 · vertciti chat

```
 浏览器 (frontend/, 静态, CSP)                        运营 (CHAT_ADMIN_KEY)
   │  POST /v1/visitor → 匿名访客令牌                     │ kill/unkill(两步) · audit/verify · metrics
   │  X-Visitor-Token                                      │
   ▼                                                       ▼
 ┌──────────────────────── FastAPI 单进程 (backend/app) ─────────────────────────┐
 │ main: trace id · 安全头 · JSON 日志 · 统一错误体 · /health(含库探活)            │
 │ auth: visitor | service | admin 三类主体                                          │
 │ rate_limit: 主体/IP 分钟桶(内存) · 日额度(SQLite, 原子)                           │
 │ kill: 两步急停 · check_not_killed 守卫                                             │
 │ chat_api: 会话归属 · 消息生命周期 · SSE(异步, 有界)                               │
 │ memory_api / memory_store · llm(策略→模型, 预算熔断) · funnel · events · retention │
 │ audit: 哈希链 · db: SQLite + schema_version 迁移                                   │
 └───────────────┬──────────────────────────────────────────────┬────────────────────┘
                 │ HTTP only (M1)                               │ OpenAI 兼容 HTTP
                 ▼                                              ▼
        anomalies 运行时 (另一工程)                        LLM 供应商
```

## 主体与权限

| 主体 | 凭据 | 可用 |
|---|---|---|
| visitor | HMAC 签名的匿名令牌（7 天） | 自己的会话、CTA、自己会话的事件、用量 |
| service | `CHAT_API_KEY` | 自己的会话、memory、LLM route |
| admin | `CHAT_ADMIN_KEY` | 急停、审计、指标 |

越权一律 403（主体类型不对）或 404（不是你的会话，避免探测）。每条路由的越权回归测试在 `tests/test_authz.py`。

## 一条回复的生命周期

`POST …/messages` 原子扣额度 → 存用户消息 → 调运行时：有 `run_id` 时存 assistant 行为 `pending`，否则直接 `done`。
`GET …/stream` 原子认领：`pending → streaming` 才真正调用运行时；`streaming` 时再来一个请求 409；
已结束的（`done|error|interrupted`）只回放存档，不再调用运行时（不重复计费）。
流有空闲超时、总时限、字数上限；客户端断开（停止按钮）时保存已收部分并标 `interrupted`。
进程重启时把遗留的 `streaming` 标为 `interrupted`。

## 单进程状态（ARCH-9）

| 状态 | 位置 | 多进程时的问题 | 外置方案（开关） |
|---|---|---|---|
| 分钟限流桶 | 进程内存 | 每个 worker 各算一份，额度乘以 worker 数 | Redis 令牌桶；以 `CHAT_RATE_BACKEND=redis` 切换（未实现） |
| 日额度、急停、挑战、审计 | SQLite | SQLite 单写者；多实例无法共享文件 | Postgres（与 pgvector 底座 P 同库）；迁移脚本按 `schema_version` 平移 |
| 急停判定 | 每请求查库 | 无（已在库里） | — |

结论：**在实现上面两个外置方案之前，只跑一个 worker、一个实例**（RUNBOOK §1）。

## 有界性（ARCH-4）

| 量 | 上限 | 配置 |
|---|---|---|
| 单条消息 | 20 000 字符 | 模型校验 |
| 送给运行时的历史 | 16 000 字符 / 20 条 | `CHAT_HISTORY_MAX_CHARS` |
| 单次回复时长 | 120 s（空闲 30 s） | `CHAT_STREAM_MAX_SECONDS` / `_IDLE_SECONDS` |
| 单次回复字数 | 60 000 | `CHAT_STREAM_MAX_CHARS` |
| LLM 输出 token | 默认 1024，封顶 4096 | `CHAT_LLM_MAX_TOKENS[_CAP]` |
| LLM 消息条数 | 50 | 模型校验 |
| 花费 | `budget_units` 熔断 | 请求参数 |
| 每日消息 | 访客 50 / IP 200 / 服务 200 | 见 `.env.example` |
