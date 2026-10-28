# 服务等级目标（SLO）· vertciti chat

两条 SLO，28 天滚动窗口。现状：**定义与数据来源已就位，告警尚未接入任何值班/寻呼系统**（尚无公网部署）。

| SLO | 目标 | 测量 | 数据来源 |
|---|---|---|---|
| 可用性 | 99.5% | 外部探针每分钟 `GET /healthz`，2xx 记为可用；503（数据库不可用）与超时记为不可用 | 外部拨测（待部署时选型） |
| 回复成功率 | 98% | `done / (done + error + interrupted)`，按 assistant 消息计 | `GET /v1/metrics/summary` 的 `reply_success_ratio`（admin）；或 SQL：`SELECT status, COUNT(*) FROM messages WHERE role='assistant' AND created_at > ? GROUP BY status` |

"interrupted" 包含用户主动停止；若它主导了失败，应在仪表盘把"用户停止"单列出来（`events` 可区分），不要拿它来掩盖运行时故障。

## 错误预算与告警

| 规则 | 条件 | 动作 |
|---|---|---|
| 快速燃烧 | 1 小时内可用性 < 97% 或回复成功率 < 90% | 寻呼值班；考虑急停（RUNBOOK §6） |
| 慢速燃烧 | 6 小时内消耗 > 10% 月度预算 | 工作时间处理 |
| 审计链 | `scripts/audit_anchor.py` 退出码 2 | 视为安全事故 |
| 备份 | 当日 `scripts/backup.py` 失败或未异地复制 | 工作时间处理 |

日志是每行一个 JSON（`ts, level, msg, trace_id, method, path, status, duration_ms, principal`），可直接进任意日志平台按上表建规则。
