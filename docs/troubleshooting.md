# 常见问题 / Troubleshooting

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

<a id="中文"></a>

## 中文

本页汇总「AI 需求评审工作流平台」(FastAPI + SQLite + 原生 JS SPA,默认端口 17957,部门内网部署)在启动、运行、部署与协作评审中常见的问题与解决办法。每条按 **现象 → 原因 → 解决** 三段式说明。

排障前,建议先用健康检查确认服务是否在线:

```bash
curl http://localhost:17957/api/health
# 预期返回: {"status":"ok","version":"0.3.15"}
```

---

### 1. 启动失败:JWT_SECRET 不安全或过短

- **现象**:服务启动报 `RuntimeError`,提示 **「JWT secret 使用了公开示例/默认值」** / **「JWT secret 过短」**,服务拒绝启动。
- **原因**:`jwt_secret.py` 的 `assert_jwt_secret_safe()` 会在以下情况阻止启动:
  1. **已知不安全占位值**:`change-me-in-production`、`change-this-to-a-random-secret-string`、`secret`、`jwt-secret`、`your-secret-key`;
  2. **长度不足 32 字符**。
  空值本身不会拒绝启动：`./start.sh` 会生成随机密钥并写入项目根目录 `.env`，之后重启复用；不走 `start.sh`、直接跑 uvicorn 时，`config.py` 会生成进程内临时密钥（不落盘，重启后已签发 token 失效）。
- **解决**:
  1. 推荐用 `./start.sh` 启动：若项目根目录 `.env` 中 `JWT_SECRET` 为空，脚本会生成并写入该文件，之后重启复用。
  2. 或自行生成随机密钥（`token_hex(32)` 输出 64 个十六进制字符）:
     ```bash
     python3 -c "import secrets; print(secrets.token_hex(32))"
     ```
     写入项目根目录 `.env`:`JWT_SECRET=<生成的至少 32 字符随机串>`。
  3. 重启服务。
  > 环境文件只认项目根目录 `.env`。若仍有 `src/.env`，根目录已有 `.env` 时会被忽略并告警。

---

### 2. 启动失败:没有可用模型

- **现象**:服务能正常启动,但发起对话或评审时提示 **无可用模型**。
- **原因**:
  - `.env` 未填入任何 LLM API Key;
  - 或 `config.yaml` 中对应模型 `enabled: false`。
- **解决**:
  1. 至少填入**一个** LLM API Key(四选一或多选):`DEEPSEEK_API_KEY`、`QWEN_API_KEY`、`GLM_API_KEY`、`OPENAI_API_KEY`。
  2. 打开 `src/config.yaml`,确认对应模型的 `enabled: true`。
  3. 重启服务使配置生效。

---

### 3. 模型连接失败 / 超时

- **现象**:对话或评审过程中报 **连接错误 / 超时 / 模型不可达**。
- **原因**:
  - API Key 无效或已过期;
  - 内网到模型 endpoint 网络不通(代理、防火墙);
  - `OPENAI_API_BASE` 等 `base_url` 配置错误。
- **解决**:
  1. 在**管理后台**用「测试连接」和「测速」按钮验证当前配置是否可达。
  2. 检查 `.env` 中 `OPENAI_API_BASE`、代理设置,以及内网到模型服务的网络。
  3. 评审任务有**内置重试机制**(`config.yaml` 的 `review.retry`):`max_attempts: 7`(1 次首发 + 6 次重试)、`initial_delay_ms: 2000`、`backoff_factor: 2.0`、`max_delay_ms: 64000`、`timeout_seconds: 300`,退避等待 2/4/8/16/32/64 秒。重试等待期间页面会弹出 toast(`llm_retry` SSE 事件,不写入通知列表)。瞬时抖动会自动重试,持续失败通常是上述配置或网络问题。

---

### 4. 端口被占用

- **现象**:启动报 **端口占用 / `Address already in use`**。
- **原因**:默认端口 `17957` 被其他进程占用,或上一个实例未正常退出(残留进程)。
- **解决**(任选其一):
  ```bash
  ./start.sh stop          # 停止旧实例后再启动
  lsof -i:17957            # 查看占用端口的进程
  ```
  - 如需换端口:在 `.env` 设置 `SERVER_PORT=<其他端口>` 后重启。

---

### 5. 子路径反代 404 / 静态资源丢失

- **现象**:平台挂在子路径(如 `/prd-review/`)下时,**页面白屏或 API 404**。
- **原因**:
  - `ROOT_PATH` 未设置;
  - 反向代理未剥离前缀,后端收到带双前缀的路径,无法匹配路由;
  - 缺少尾斜杠跳转。
- **解决**:
  1. 在 `.env` 中设置 `ROOT_PATH=/prd-review`(**无尾斜杠**)。
  2. 反向代理须**剥离前缀**后转发(Caddy 用 `handle_path`,Nginx 的 `proxy_pass` 带尾部 `/`),配置示例详见[打包部署指南 §4.3](packaging-and-deployment.md)。
  3. 配置 `/prd-review` → `/prd-review/` 的**尾斜杠跳转**(308;前端使用 `./` 相对路径加载静态资源,缺尾斜杠会导致相对路径错位)。
  4. 完成后清浏览器缓存验证。

---

### 6. Agent 工具调用被拒

- **现象**:Agent 调用 `bash`、`write`、`edit`、`read` 等工具时被拒,或提示 **无权限**。
- **原因**:平台采用 **deny-by-default 白名单**策略:
  - 空授权列表仅允许 `rag_search`;
  - 高风险工具(`bash`/`write`/`edit`/`read`)需**管理员配置 + 指定独立审批人**;
  - 普通用户**不可自行启用或自审批**高风险工具。
- **解决**:
  1. 管理员在 **Agent 管理**页面配置授权范围与高风险工具白名单。
  2. 为高风险工具指定**独立审批人**(`approver_id`),该审批人须与申请者不同。
  3. 待审批请求通过 `GET /api/agent/approvals` 查看;审批人通过 `POST decide` 批准或拒绝。

---

### 7. 知识库向量化卡住 / 检索无结果

- **现象**:上传知识文档后**检索不到内容**,或来源一直处于 `pending` 状态。
- **原因**:
  - Embedding Worker 在后台**异步向量化**尚未完成;
  - Embedding API Key 未配置;
  - 或 FTS(全文检索)兜底未生效。
- **解决**:
  1. 确认 `EMBEDDING_MODEL` 配置正确(默认 `text-embedding-3-small`),且 Embedding API Key 已配置。
  2. 查看 embedding worker 日志(`runtime/logs/app.log`)确认无报错。
  3. 手动触发重新向量化:`POST /workspace/{id}/sources/{source_id}/ingest`。
  4. **个人知识库**有 FTS 兜底:即便向量化失败,仍可通过全文检索命中。

---

### 8. SQLite 文件锁 / 数据库写错误

- **现象**:服务日志报 **`database is locked`** 或数据库写错误。
- **原因**:
  - SQLite 文件锁冲突,通常由**多进程并发写入**或上一个实例未正常关闭引起;
  - `aiosqlite` 对文件锁较为敏感。
- **解决**:
  1. 确保**仅运行单实例**(`./start.sh status` 确认进程数)。
  2. 进行数据迁移或备份前,**务必先停服**:`./start.sh stop`。
  3. 迁移完成后重启服务。

---

### 9. 版本更新失败 / 回滚

- **现象**:`update.sh` 更新后健康检查失败;或提示 **「代码已经是 X.X.X,无需更新」**。
- **原因**:
  - 版本号未变更(发布前未更新根目录 `VERSION` 文件,更新包内版本与目标机当前版本相同);
  - 更新包中混入了 runtime 业务数据。
- **解决**:
  1. **版本号相同**时,使用 `./update.sh --force` 强制更新。
  2. 打包务必使用 `package.sh`(不含 `runtime/` 业务数据),避免覆盖目标机的真实数据。
  3. **健康检查失败会自动回滚**(除非显式加 `--no-rollback`)。
  4. **Pi Agent 更新后需手动执行 `npm install`**:`update.sh` 会同步 `package.json` 和 `package-lock.json`，但不会自动执行 `npm install`；需在目标服务器手动运行 `npm install`。

---

### 10. 前端品牌信息未更新

- **现象**:修改了品牌配置(名称、Logo、配色等),但页面显示**没有变化**。
- **原因**:
  - 品牌配置**优先级**:`runtime/config/ui-branding.yaml` > `config.yaml` > 代码默认值;
  - 或 `app_version` 未同步;
  - 或浏览器/CDN 缓存。
- **解决**:
  1. 确认 `runtime/config/ui-branding.yaml` 存在且字段正确(这是最高优先级)。
  2. `app_version` 由 `update.sh` 自动同步;手动改品牌时,直接编辑 yaml,或执行 `python3 tools/migrate_branding.py apply`。
  3. **清浏览器缓存**或强制刷新(Ctrl/Cmd + Shift + R)。服务端已加 `NoCacheMiddleware`,但 CDN/浏览器层仍可能缓存。

---

### 11. 协作评审无法审批

- **现象**:在协作评审中点击审批/决策时,返回 **403「只有指定的审批人可以做出决策」**。
- **原因**:
  - 当前登录用户**不是该评审轮次的指定审批人**(`approver_id`);
  - 或当前用户不具备 `Approver` 角色。
- **解决**:
  1. 确认审批人身份:核对当前轮次指定的 `approver_id`。
  2. 新建评审轮次会**继承** `approver_id`,如需更换请由管理员重新指定。
  3. 确保审批人账号拥有 `Approver` 角色。

---

### 12. 发起评审返回 409「必需 Skill 已被禁用」

- **现象**:点击开始评审时返回 **409**,提示「必需 Skill 已被禁用,无法发起审查:{skill_id 列表}。请在管理后台重新启用后再试。」。
- **原因**:管理员在 **Skill 管理**中禁用了必需 Skill(`prd-overview-classify`/`prd-per-analysis`/`system-review`/`report-generator` 任一),评审启动前置门控会拒绝创建任务。
- **解决**:由管理员在管理后台(Skill 管理)重新启用对应 Skill 后再发起评审。
> 可选 Skill(`requirement-insights`)被禁用**不会**触发 409:`insight`/`full`/`draft` 模式会自动跳过「需求洞察」步骤**降级运行**,任务终态为 `completed_with_warnings`,降级明细记录在任务 `step_details` 中。

---

### 13. 健康检查与日志(排障入口)

- **健康检查端点**:`GET /api/health`
  ```bash
  curl http://localhost:17957/api/health
  # 预期返回: {"status":"ok","version":"0.3.15"}
  ```
  - `status` 不为 `ok` 或请求失败,说明服务未正常启动或端口不可达。
  - `version` 用于确认是否为目标版本(更新失败排查)。
- **应用日志**:`runtime/logs/app.log`
  - 包含启动报错、模型调用失败、评审重试、Agent 工具调用等关键信息。
- **其他日志**:`runtime/logs/` 目录下还有 `service.log`(服务级)、`audit.jsonl`(审计)、`llm_sessions.jsonl`(LLM 会话)等,可按需查阅。

---

### 如何获取帮助 / How to get help

按以下顺序自助排查:

1. **健康检查**:确认服务是否在线 → `GET /api/health`。
2. **查阅日志**:重点看 `runtime/logs/app.log`。
3. **重启服务**:多数瞬时问题可通过 `./start.sh restart` 解决。
4. **查阅相关文档**:
   - [configuration.md](configuration.md) — 完整配置项(模型、Prompt、品牌、端口、反代、Agent 授权等)
   - [packaging-and-deployment.md](packaging-and-deployment.md) — 生产环境打包与部署、`update.sh` / `package.sh`
   - [admin-guide.md](admin-guide.md) — 管理员指南(用户、角色、模型、Agent 工具授权)
   - [security.md](security.md) — 安全相关(JWT 密钥、审批流、审计日志)
5. 若仍无法解决,请将 `runtime/logs/app.log` 中**相关时间段的日志片段**提交给系统管理员。

---

<a id="english"></a>

## English

This page collects common issues and fixes for the **AI Requirement Review Workflow Platform** (FastAPI + SQLite + vanilla JS SPA, default port 17957, intranet deployment) across startup, runtime, deployment, and collaborative review. Each entry follows a **Symptom → Cause → Fix** format.

Before troubleshooting, verify the service is up via the health check:

```bash
curl http://localhost:17957/api/health
# Expected: {"status":"ok","version":"0.3.15"}
```

---

### 1. Startup failure: JWT_SECRET insecure or too short

- **Symptom**: The service raises a `RuntimeError` on startup, with **"JWT secret uses a public example/default value"** / **"JWT secret too short"**, and refuses to start.
- **Cause**: `jwt_secret.py`'s `assert_jwt_secret_safe()` blocks startup when:
  1. **A known insecure placeholder**: `change-me-in-production`, `change-this-to-a-random-secret-string`, `secret`, `jwt-secret`, `your-secret-key`;
  2. **Shorter than 32 characters**.
  An empty value does not refuse startup: `./start.sh` generates a random secret and writes it to the project-root `.env` for later restarts; if you run uvicorn directly, `config.py` generates an in-process ephemeral secret (not persisted; issued tokens die after restart).
- **Fix**:
  1. Prefer `./start.sh`: if project-root `.env` has an empty `JWT_SECRET`, the script generates one and writes it there for later restarts.
  2. Or generate a random secret yourself (`token_hex(32)` yields 64 hex characters):
     ```bash
     python3 -c "import secrets; print(secrets.token_hex(32))"
     ```
     Put it in the project-root `.env`: `JWT_SECRET=<generated string of at least 32 chars>`.
  3. Restart the service.
  > Only the project-root `.env` is used. A leftover `src/.env` is ignored (with a warning) when the root file already exists.

---

### 2. Startup failure: no available model

- **Symptom**: The service starts fine, but starting a chat or review reports **no available model**.
- **Cause**:
  - No LLM API key is set in `.env`;
  - Or the corresponding model in `config.yaml` has `enabled: false`.
- **Fix**:
  1. Fill in **at least one** LLM API key (pick one or more): `DEEPSEEK_API_KEY`, `QWEN_API_KEY`, `GLM_API_KEY`, `OPENAI_API_KEY`.
  2. Open `src/config.yaml` and ensure the target model has `enabled: true`.
  3. Restart for the change to take effect.

---

### 3. Model connection failure / timeout

- **Symptom**: During chat or review you see **connection errors / timeouts / model unreachable**.
- **Cause**:
  - The API key is invalid or expired;
  - The intranet cannot reach the model endpoint (proxy, firewall);
  - `base_url` (e.g. `OPENAI_API_BASE`) is misconfigured.
- **Fix**:
  1. In the **admin console**, use the **Test Connection** and **Speed Test** buttons to verify reachability.
  2. Check `.env` for `OPENAI_API_BASE`, proxy settings, and intranet connectivity to the model service.
  3. Review tasks have a **built-in retry mechanism** (`config.yaml`, `review.retry`): `max_attempts: 7` (1 initial + 6 retries), `initial_delay_ms: 2000`, `backoff_factor: 2.0`, `max_delay_ms: 64000`, `timeout_seconds: 300`, with backoff waits of 2/4/8/16/32/64 seconds. An in-page toast (`llm_retry` SSE event, not stored in the inbox) appears while waiting. Transient blips are retried automatically; persistent failure is usually config or network.

---

### 4. Port already in use

- **Symptom**: Startup reports **port in use / `Address already in use`**.
- **Cause**: The default port `17957` is taken by another process, or a previous instance did not exit cleanly (lingering process).
- **Fix** (pick one):
  ```bash
  ./start.sh stop          # stop the old instance, then start again
  lsof -i:17957            # find the process holding the port
  ```
  - To use a different port: set `SERVER_PORT=<other-port>` in `.env` and restart.

---

### 5. Sub-path reverse proxy 404 / missing static assets

- **Symptom**: When the platform is mounted under a sub-path (e.g. `/prd-review/`), the **page is blank or APIs return 404**.
- **Cause**:
  - `ROOT_PATH` is unset;
  - the reverse proxy does not strip the prefix, so the backend receives a double-prefixed path that matches no route;
  - the trailing-slash redirect is missing.
- **Fix**:
  1. Set `ROOT_PATH=/prd-review` in `.env` (**no trailing slash**).
  2. The reverse proxy must **strip the prefix** before forwarding (Caddy `handle_path`, or Nginx `proxy_pass` with a trailing `/`); see [packaging-and-deployment.md §4.3](packaging-and-deployment.md) for sample configs.
  3. Configure the `/prd-review` → `/prd-review/` **trailing-slash redirect** (308; the frontend loads static assets via `./` relative paths, so a missing trailing slash breaks them).
  4. Clear the browser cache and verify.

---

### 6. Agent tool calls rejected

- **Symptom**: The Agent's calls to `bash`, `write`, `edit`, `read` and similar tools are rejected, or it reports **no permission**.
- **Cause**: The platform uses a **deny-by-default allowlist**:
  - An empty allowlist permits only `rag_search`;
  - High-risk tools (`bash`/`write`/`edit`/`read`) require **admin configuration + a designated independent approver**;
  - Regular users **cannot enable or self-approve** high-risk tools.
- **Fix**:
  1. An admin configures the authorization scope and the high-risk tool allowlist on the **Agent management** page.
  2. Designate an **independent approver** (`approver_id`) for high-risk tools — it must differ from the requester.
  3. Pending requests are listed at `GET /api/agent/approvals`; the approver approves or rejects via `POST decide`.

---

### 7. Knowledge base vectorization stuck / no search results

- **Symptom**: After uploading knowledge documents, **search returns nothing**, or the source stays `pending`.
- **Cause**:
  - The Embedding Worker has not finished **async vectorization** yet;
  - The Embedding API key is not configured;
  - Or the FTS (full-text search) fallback is not in effect.
- **Fix**:
  1. Confirm `EMBEDDING_MODEL` is set correctly (default `text-embedding-3-small`) and the Embedding API key is present.
  2. Inspect the embedding worker logs (`runtime/logs/app.log`) for errors.
  3. Manually re-trigger ingestion: `POST /workspace/{id}/sources/{source_id}/ingest`.
  4. **Personal knowledge bases** have an FTS fallback: even if vectorization fails, full-text search can still match.

---

### 8. SQLite file lock / database write error

- **Symptom**: Service logs show **`database is locked`** or database write errors.
- **Cause**:
  - SQLite file-lock contention, usually from **multiple processes writing concurrently** or a previous instance not exiting cleanly;
  - `aiosqlite` is sensitive to file locks.
- **Fix**:
  1. Ensure **only a single instance** is running (`./start.sh status` to confirm process count).
  2. Before any data migration or backup, **always stop the service first**: `./start.sh stop`.
  3. Restart after migration completes.

---

### 9. Version update failure / rollback

- **Symptom**: After running `update.sh`, the health check fails; or it says **"code is already X.X.X, no update needed"**.
- **Cause**:
  - The version number is unchanged (the root `VERSION` file was not bumped before release, so the version inside the update package equals the target host's current version);
  - The update package included runtime business data.
- **Fix**:
  1. If the **version is identical**, force the update with `./update.sh --force`.
  2. Always build packages with `package.sh` (it excludes `runtime/` business data) to avoid overwriting real data on the target host.
  3. A **failed health check triggers automatic rollback** (unless `--no-rollback` is passed).
  4. **After updating Pi Agent, run `npm install` manually**: `update.sh` syncs `package.json` and `package-lock.json` but does not run `npm install` automatically; run `npm install` manually on the target server.

---

### 10. Frontend branding not updated

- **Symptom**: You changed the branding config (name, logo, colors, etc.) but the page **shows no change**.
- **Cause**:
  - Branding **priority**: `runtime/config/ui-branding.yaml` > `config.yaml` > code defaults;
  - Or `app_version` is out of sync;
  - Or browser/CDN cache.
- **Fix**:
  1. Confirm `runtime/config/ui-branding.yaml` exists and its fields are correct (highest priority).
  2. `app_version` is synced automatically by `update.sh`; for manual branding edits, edit the yaml directly, or run `python3 tools/migrate_branding.py apply`.
  3. **Clear the browser cache** or hard-refresh (Ctrl/Cmd + Shift + R). The server adds `NoCacheMiddleware`, but CDN/browser layers may still cache.

---

### 11. Collaborative review cannot be approved

- **Symptom**: Clicking approve/decide in a collaborative review returns **403 "only the designated approver can make a decision"**.
- **Cause**:
  - The current user is **not the designated approver** (`approver_id`) for this review round;
  - Or the user lacks the `Approver` role.
- **Fix**:
  1. Confirm the approver identity: check the `approver_id` designated for the current round.
  2. A new review round **inherits** `approver_id`; to change it, have an admin reassign.
  3. Ensure the approver account holds the `Approver` role.

---

### 12. Starting a review returns 409 "required Skill disabled"

- **Symptom**: Clicking Start Review returns **409** with the message "必需 Skill 已被禁用，无法发起审查：{skill_id list}。请在管理后台重新启用后再试。" (required Skill(s) disabled; re-enable them in the admin console).
- **Cause**: An admin disabled one of the required skills (`prd-overview-classify`/`prd-per-analysis`/`system-review`/`report-generator`) in **Skill Management**, so the review-start gate refuses to create the task.
- **Fix**: Have an admin re-enable the corresponding skill in the admin console (Skill Management), then start the review again.
> Disabling the optional skill (`requirement-insights`) does **not** trigger 409: `insight`/`full`/`draft` modes automatically skip the "requirement insights" step and run **degraded**; the task ends as `completed_with_warnings`, with the degradation details recorded in the task's `step_details`.

---

### 13. Health check and logs (troubleshooting entry points)

- **Health endpoint**: `GET /api/health`
  ```bash
  curl http://localhost:17957/api/health
  # Expected: {"status":"ok","version":"0.3.15"}
  ```
  - If `status` is not `ok` or the request fails, the service is not started or the port is unreachable.
  - `version` confirms whether you're on the target version (useful for diagnosing failed updates).
- **Application log**: `runtime/logs/app.log`
  - Captures startup errors, model call failures, review retries, Agent tool calls, and more.
- **Other logs**: under `runtime/logs/` there are also `service.log` (service-level), `audit.jsonl` (audit), `llm_sessions.jsonl` (LLM sessions), etc. — consult as needed.

---

### How to get help

Self-diagnose in this order:

1. **Health check**: confirm the service is up → `GET /api/health`.
2. **Read the logs**: focus on `runtime/logs/app.log`.
3. **Restart the service**: most transient issues resolve with `./start.sh restart`.
4. **Consult related docs**:
   - [configuration.md](configuration.md) — full configuration reference (models, prompts, branding, ports, reverse proxy, Agent authorization, etc.)
   - [packaging-and-deployment.md](packaging-and-deployment.md) — production packaging and deployment, `update.sh` / `package.sh`
   - [admin-guide.md](admin-guide.md) — admin guide (users, roles, models, Agent tool authorization)
   - [security.md](security.md) — security topics (JWT secret, approval flow, audit logs)
5. If the issue persists, submit the **relevant log snippet from `runtime/logs/app.log`** (around the time of the problem) to your system administrator.
