# 运行手册 · vertciti chat

面向值班的人：部署、回滚、备份恢复、密钥轮换、审计锚定、急停与事故响应。每一步都能照抄执行。
现状：尚无公网部署；以下流程在 dev 环境验证过（见各节"已验证"）。

## 1. 部署

**单进程、单实例。** 限流桶与 SQLite 都在本进程内（见 [ARCHITECTURE.md](ARCHITECTURE.md) §单进程状态），
在外置共享存储之前不要开第二个 worker 或第二台实例。

1. 准备环境变量（全部列在 [`.env.example`](../.env.example)）。`CHAT_ENV=prod` 时以下缺一则拒绝启动：
   `CHAT_API_KEY`、`CHAT_ADMIN_KEY`、`CHAT_VISITOR_SECRET`（各 ≥24 字符且互不相同）、`CHAT_CORS_ORIGINS`、`CHAT_DB_PATH`。
2. 安装（哈希锁定）：`python3 -m venv .venv && .venv/bin/pip install --require-hashes -r backend/requirements.txt`
3. 启动：`cd backend && ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8120 --no-access-log`
   放在 TLS 反向代理之后（HSTS 只在 prod 发出）。代理必须：
   - 透传或生成 `X-Request-ID`（8–64 位 `[A-Za-z0-9_-]`），日志按它串联；
   - 静态页按 `frontend/serve.py` 的同一组响应头发出（CSP 无 `unsafe-inline`、nosniff、`frame-ancestors 'none'`、Referrer-Policy）；
   - 把真实客户端 IP 作为连接来源交给 uvicorn（否则按 IP 的限额会把所有人算成代理一个 IP）。
4. 前端：发布 `frontend/` 目录；把 `index.html` 里 `<meta name="vc-api-base">` 填成 API 源。
5. 验证：`curl -f https://<api>/healthz`（数据库不可用时为 503）；运行一次 `CHAT_BASE=https://<api> CHAT_ADMIN_KEY=… scripts/kill-drill.sh`。

## 2. 回滚

回滚 = 重新部署上一个发布标签（Release 页有源码包、SBOM 与来源证明）。

1. `git checkout vX.Y.(Z-1)`，按 §1 重装依赖并重启。
2. 数据库只前进不后退：迁移只追加（`schema_version`）。若新版本加过列，旧代码会忽略新列，可直接回滚；
   若某个发布在 CHANGELOG 标注"不可回滚"，先按 §3 恢复该版本之前的备份。

## 3. 备份与恢复（RPO ≤ 24 h，RTO ≤ 15 min）

- 每日备份（cron / systemd timer）：`CHAT_BACKUP_OFFSITE_CMD="rclone copy --immutable remote:chat-backups" scripts/backup.py`
  使用 SQLite 在线备份 API，校验 `integrity_check`，写 `.sha256`，保留最近 14 份；
  设置了 `CHAT_BACKUP_OFFSITE_CMD` 才会复制到异地，未设置时脚本明确告警"仅本机"。
- 恢复：停服务 → 取最新备份并核对 `.sha256` → 复制为 `CHAT_DB_PATH` → 启动 → `/healthz` 200 →
  `GET /v1/risk/audit/verify`（admin）`ok: true` 且 `head` 与当日锚定一致。
- **每季度计时演练**：`scripts/restore_drill.py --record` 自动完成"备份→恢复到空目录→完整性/行数/审计链校验"，
  并把 RTO/RPO 追加到 [ops/restore-drills.md](ops/restore-drills.md)。已验证：2026-10-28 在 dev 种子库上通过（见该表）。
- 尚未完成：异地存储目标需要运营方提供（桶 / 远端），在此之前异地备份不成立。

## 4. 密钥轮换

| 密钥 | 影响 | 步骤 |
|---|---|---|
| `CHAT_API_KEY` | 调用 memory / LLM route 的服务 | 先把新 key 发给调用方 → 换环境变量重启 → 旧 key 立即失效 |
| `CHAT_ADMIN_KEY` | 值班人员 | 换环境变量重启；只交给值班人员，绝不进浏览器或其他模块 |
| `CHAT_VISITOR_SECRET` | 所有访客令牌立即失效 | 换环境变量重启；页面收到 401 会自动重新领取令牌，但访客将看不到旧的"历史对话"（会话归属于旧访客 id） |
| `ANOMALIES_API_KEY` / `CHAT_LLM_API_KEY` | 上游调用 | 先在上游签发新 key → 换环境变量重启 → 在上游吊销旧 key |

疑似泄露时：立即轮换，然后按 §6 事故流程处理。

## 5. 审计链锚定（每日）

审计表是哈希链（`prev_hash`/`row_hash`），能发现单行改动或删除；但拥有数据库写权限的人可以整链重写。
防线是**每天把链头锚定到本系统之外**：

```bash
CHAT_ADMIN_KEY=... scripts/audit_anchor.py --url https://<api> >> <另一个仓库或只追加存储>/chat-anchors.jsonl
```

链校验失败时脚本拒绝输出（退出码 2），这本身就是事故，转 §6。外部记录的位置由运营方决定；在它建立之前，
"篡改可发现"只对数据库外的人成立（README 已如实写明）。

## 6. 急停与事故响应

**急停（两步，仅 admin key）：**

```bash
curl -s -X POST https://<api>/v1/risk/kill -H "X-API-Key: $CHAT_ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"scope":"module","reason_code":"incident","actor":"<你的名字>"}'          # 返回 challenge_id 与 confirm_phrase
curl -s -X POST https://<api>/v1/risk/confirm -H "X-API-Key: $CHAT_ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"challenge_id":"<上一步>","confirm_phrase":"kill module"}'
```

生效后：新访客、建会话、发消息、流、LLM route、memory 写读、事件全部 503 `chat_killed`；
读取/删除自己的数据、健康检查、风控接口照常；页面状态显示"已停止服务"。恢复用 `/v1/risk/unkill` + confirm。

**事故流程：** 1) 判断是否需要急停（数据外泄、费用失控、内容事故 → 先停）；2) 在 GitHub 开私密安全通告或事故 issue，
记录时间线（UTC）；3) 保全证据：`scripts/backup.py`、`/v1/risk/audit/verify` 结果、相关 `trace_id` 的日志；
4) 修复后按 §1 验证再 unkill；5) 72 小时内写复盘（原因、影响面、修复、防再发的测试）。

## 7. 日常检查

| 频率 | 动作 |
|---|---|
| 每日 | 备份成功且异地复制成功；审计链锚定；`/v1/metrics/summary` 的 `reply_success_ratio` |
| 每周 | Dependabot PR 合并；`pip-audit -r backend/requirements.txt` |
| 每季度 | `scripts/restore_drill.py --record`；`scripts/kill-drill.sh`；轮换 admin key |
