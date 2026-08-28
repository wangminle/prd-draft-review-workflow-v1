# 打包与部署指南 / Packaging and Deployment

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

<a id="中文"></a>

## 中文

> 适用版本：V0.3.16（2026-08-28）。本文讲「代码如何从开发机分发到目标服务器」，与 [部署加固指南](deployment-hardening.md) 互补——那篇讲目标服务器的网络拓扑、守护进程与安全加固，本文讲打包产物与分发安装流程。

## 1. 目标与范围

提供一条可复现、可审计的「开发机 → 目标服务器」分发链路，覆盖：

- 在开发机生成只含代码与配置模板的分发包（不含密钥、不含业务数据）。
- 全新服务器的首次部署。
- 已部署服务器的版本更新（含自动备份与健康检查、失败自动回滚）。
- 运行时数据与品牌配置的迁移。

核心约束（与 `CLAUDE.md` 一致）：

- **数据与代码分离**：分发包绝不包含 `runtime/` 业务数据（数据库、上传文件、向量库、日志、结果）。
- **开源合规**：分发包不含品牌名称、内部域名等真实标识，只携带 `ui-branding.example.yaml` 模板。
- **密钥隔离**：`.env` 不进包，每台服务器各自配置。

## 2. 三套脚本分工

| 脚本 | 运行位置 | 作用 |
| --- | --- | --- |
| `package.sh` | 开发机 | 把当前代码与配置模板打成 `*-code-config*.tar.gz` 分发包 |
| `start.sh` | 目标服务器 | 服务的 `start / stop / restart / status`，管理 PID 与日志 |
| `update.sh` | 目标服务器 | 接收分发包，执行 校验 → 备份 → 替换 → 品牌迁移 scan/plan → 健康检查 → 失败回滚 |

总体流程：

```text
开发机                          目标服务器
 package.sh ──┐
              ├─ *-code-config*.zip（默认）──►  首次部署：unzip + 装依赖 + start.sh
              ├─ *-code-config*.tar.gz      ──►  版本更新：update.sh（自动备份/校验/回滚）
```

## 3. 打包（开发机执行）

### 3.1 用法

```bash
./package.sh                      # 默认：zip 格式，输出到 ./dist
./package.sh --format tar.gz      # 改为 tar.gz（update.sh 自动更新流程需要）
./package.sh --format both        # 同时产出 zip 和 tar.gz
./package.sh --list               # 额外打印包内文件清单
./package.sh --output /tmp        # 指定输出目录
./package.sh --build-no 0598      # 指定构建号（默认时间戳 YYYYMMDDHHMM）
```

产物命名：`prd-draft-review-workflow-v1-code-config-v{版本}-build{构建号}.{zip|tar.gz}`，版本号取自根目录 `VERSION` 文件（与 `update.sh` 同源；旧包回退 `src/app/version.py` / `src/main.py`）。默认 zip；tar.gz 是 `update.sh` 自动识别的格式。

### 3.2 包内包含

| 类别 | 成员 |
| --- | --- |
| 代码目录 | `src/` `tools/` `tests/` `docs/` `skills/` |
| 根脚本 | `start.sh` `update.sh` |
| 依赖清单 | `requirements.txt` `pyproject.toml` `package.json` |
| 文档与协议 | `README.md` `CLAUDE.md` `LICENSE` `.env.example` |
| 配置模板 | `runtime/config/ui-branding.example.yaml` |

> 说明：`update.sh` 的更新流程同步 `src tools tests docs skills` 与若干根文件（含 `package.json` 和 `package-lock.json`）。若 `pi-coding-agent` 版本变化，更新后需在目标服务器执行 `npm install` 以安装新依赖。Python 应用依赖以 `requirements.txt` 为准，安装用 `pip`。`pyproject.toml` 只含 pytest/ruff 等工具配置，**不是**应用依赖清单。仓库不跟踪 `uv.lock`（空壳 lock 会误导部分平台走 `uv sync` 而装不到包）；分发包也不包含 `uv.lock`。

### 3.3 包内排除（自动）

- `node_modules/`（体积大，目标机本地 `npm install`）
- `.git/`、`.venv/`、`__pycache__/`、`*.pyc`、`.pytest_cache` 等缓存
- `.env`（密钥文件）、`.DS_Store`、`*.swp`
- `runtime/` 下的业务数据：`data/` `uploads/` `logs/` `results/` `vector*/` `storage/`
- `runtime/config/ui-branding.yaml`（真实品牌配置，仅保留 `*.example.yaml` 模板）
- `eval/` 实验与评估目录（含 POC 选型与正式验收）

### 3.4 自检

打包完成后，脚本内置自检（复刻 `update.sh` 的 `validate_update_package` 规则），任一不通过即删除产物并失败退出：

- 必须含 `src/main.py`
- 不得含不安全路径（绝对路径或 `..`）
- 不得含 `runtime/data|uploads|logs|results|storage|vector` 业务数据目录
- 不得含裸 `.env`、`node_modules`、`.git`
- 不得含 macOS AppleDouble 文件（`._*`），避免污染 Linux 部署目录

## 4. 首次部署（全新服务器）

### 4.1 环境前置

目标服务器需具备：Python 3.10+、Node.js 22.19+、npm（Pi Agent 功能需要；不用 Agent 可不装 Node）。

### 4.2 步骤

```bash
# 1) 传输并解压（部署目录可自定，下例为 /opt/ai-review）
mkdir -p /opt/ai-review
#    默认 zip 分发包：
unzip prd-draft-review-workflow-v1-code-config-v0.3.16-build*.zip -d /opt/ai-review
#    若是 tar.gz 分发包：tar -xzf prd-draft-review-workflow-v1-code-config-v0.3.16-build*.tar.gz -C /opt/ai-review
cd /opt/ai-review

# 2) 配置密钥（包内只有 .env.example，不含真实密钥）
cp .env.example .env
#    编辑 .env：填 DEEPSEEK_API_KEY/QWEN_API_KEY/GLM_API_KEY/OPENAI_API_KEY；
#              JWT_SECRET 可留空（首次启动写入项目根目录 .env 并复用）；
#              示例占位值或过短密钥仍会拒绝启动：
#                python3 -c "import secrets; print(secrets.token_hex(32))"
#              可选 ADMIN_INITIAL_PASSWORD 覆盖首次 admin 密码；
#              按需设置 SERVER_PORT（默认 17957）。

# 3) 安装依赖（建议在虚拟环境中）
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
npm install            # 仅 Pi Agent 功能需要

# 4) 品牌/端口配置（可选；不改则使用代码内置默认值）
cp runtime/config/ui-branding.example.yaml runtime/config/ui-branding.yaml
#    编辑 ui-branding.yaml：填入品牌名、Logo、登录页提示等。

# 5) 启动
./start.sh start       # PID 写入 runtime/server.pid，日志写入 runtime/logs/app.log
./start.sh status      # 查看运行状态并做健康检查
```

健康检查端点：`GET http://<host>:<port>/api/health`，正常返回 `{"status":"ok","version":"0.3.16"}`。

> 生产环境建议用 Nginx 反向代理 + systemd 守护，详见 [部署加固指南](deployment-hardening.md)。systemd 的 `EnvironmentFile` 应指向 `.env`，避免 `JWT_SECRET` 落在命令行参数中。应用停机时会先取消审查后台任务与 Embedding Worker，再释放数据库引擎。

### 4.3 子路径前缀部署（可选）

默认部署假定应用独占站点根路径（`https://host/`）。若需要与其他应用共用入口、把本应用挂在子路径下（如 `https://host/prd-review/`），按以下方式配置：

1. `.env` 中设置前缀与监听地址：

   ```bash
   ROOT_PATH=/prd-review     # 与应用挂载的子路径一致，不要带尾部斜杠
   SERVER_HOST=127.0.0.1     # 默认即回环监听，只经反代暴露
   SERVER_PORT=17957
   ```

   `start.sh` 会把 `ROOT_PATH` 传给 `uvicorn --root-path`；前端会根据页面实际路径自动拼接 API 前缀，无需额外配置。

2. 反向代理须**剥离前缀**后转发给后端（`start.sh` 已将 `ROOT_PATH` 传给 `uvicorn --root-path`，后端路由基于剥离后的路径匹配；若不剥离，路径会带上多余前缀导致 404）。Caddy 示例：

   ```
   redir /prd-review /prd-review/ 308
   handle_path /prd-review/* {
       reverse_proxy 127.0.0.1:17957
   }
   ```

   Nginx 等价配置：

   ```nginx
   location = /prd-review { return 308 /prd-review/; }
   location /prd-review/ {
       proxy_pass http://127.0.0.1:17957/;   # 注意：proxy_pass 带尾部 / ，Nginx 自动剥离 /prd-review/ 前缀
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   }
   ```

   `/prd-review` → `/prd-review/` 的尾斜杠跳转是必须的：前端静态资源使用 `./` 相对路径，缺少尾斜杠时浏览器会把相对路径解析到站点根。

3. 验证：`curl http://127.0.0.1:17957/api/health`（本机直连，无前缀）与 `curl https://host/prd-review/api/health`（经反代，带前缀）均应返回 `{"status":"ok",...}`。

## 5. 版本更新（已部署服务器）

### 5.1 用法

```bash
# 把新包放到项目根目录，直接执行（脚本会自动在当前目录查找 *code-config*.tar.gz）
./update.sh
# 或显式指定包路径
./update.sh --package ./prd-draft-review-workflow-v1-code-config-v0.3.16-build*.tar.gz
```

常用选项：

| 选项 | 作用 |
| --- | --- |
| `--package PATH` | 指定更新包路径 |
| `--force` | 当前版本与目标版本相同时仍强制更新 |
| `--skip-migrate` | 跳过品牌迁移 scan/plan 检查 |
| `--skip-backup` | 跳过备份（失败时将无法自动回滚，慎用） |
| `--no-rollback` | 健康检查失败时不自动回滚 |

### 5.2 更新流程

`update.sh` 依次执行：

1. **版本比对**：解包后优先读取更新包内根目录 `VERSION` 文件（记为 `PACKAGE_VERSION`；缺失时回退 `src/app/version.py` / `src/main.py` 的 `APP_VERSION`），与目标机当前版本比较；相同且未 `--force` 则退出。
2. **包校验**：路径安全、无业务数据目录、含 `src/main.py`。
3. **停止服务**：调用 `start.sh stop`。
4. **备份**：把当前代码、`runtime/config`、`runtime/assets`、`.env` 备份到 `runtime/update_backups/backup-<版本>-<时间戳>/`。
5. **品牌迁移 scan/plan**（替换代码**之前**）：读取旧 HTML 中的文本配置，生成 `runtime/config/ui-branding.scan-report.md` 差异报告。**只生成报告，不自动 apply**——避免覆盖目标机已有的品牌配置。
6. **替换代码**：覆盖 `src tools tests docs skills` 与根文件。
7. **同步版本号**：把 `runtime/config/ui-branding.yaml` 的 `app_version` 对齐到新版本。
8. **启动 + 健康检查**：`start.sh start` 后轮询 `/api/health`。
9. **失败回滚**：健康检查不过则从第 4 步的备份还原并重启。

### 5.3 版本号一致性

`update.sh` 以更新包内根目录 `VERSION`（读出的 `PACKAGE_VERSION`）为准，与目标机当前版本比较：两者相同且未加 `--force` 时才拒绝更新。脚本顶部的 `NEW_VERSION` 仅在包内读取失败时作为回退值，不再决定是否更新。发布新版本时只需更新根目录 `VERSION`（打包脚本会自动取该值命名产物）；`package.json` 的 `version` 建议同步保持一致。

## 6. 运行时数据迁移（跨服务器搬家，可选）

分发包不含运行时数据。若要把现有业务数据迁到新服务器：

```bash
# 源服务器：打包运行时数据（停服后操作，避免数据库写竞争）
./start.sh stop
tar -czf runtime-backup-$(date +%Y%m%d).tar.gz -C runtime data uploads vector assets config

# 传输到新服务器，解压到对应 runtime/ 目录
# 新服务器：首次部署完成、启动之前放好
tar -xzf runtime-backup-*.tar.gz -C /opt/ai-review/runtime
./start.sh start
```

迁移注意：

- **数据库**（SQLite）文件锁：务必停服后再打包，`aiosqlite` 对文件锁敏感。
- **品牌配置**：若源服务器自定义过 `runtime/config/ui-branding.yaml`，迁移后可执行 `python3 tools/migrate_branding.py apply --legacy-code-dir . --legacy-runtime-dir runtime --target-runtime-dir runtime`，按 scan/plan 报告写入；apply 前务必先看 `ui-branding.scan-report.md`。
- **向量库**：`runtime/vector*/` 路径与新代码的检索引擎配置绑定，跨大版本迁移前先确认 `src/config.yaml` 的检索引擎设置一致。

## 7. 常见问题

| 现象 | 排查 |
| --- | --- |
| `update.sh` 提示「当前版本 X.X.X 与更新包版本 X.X.X 相同，无需更新」 | 目标机版本与包内根目录 `VERSION` 相同；用 `--force` 强制重新部署 |
| 更新后 Pi Agent 功能不可用 | `update.sh` 会同步 `package.json` 和 `package-lock.json`，但不会自动执行 `npm install`；需在目标服务器手动运行 `npm install` 安装/更新依赖 |
| 启动后健康检查失败 | 看 `runtime/logs/app.log`；常见为 `.env` 缺 LLM 密钥、`JWT_SECRET` 过短/示例占位值被拒绝、端口被占、依赖未装全 |
| 前端品牌信息未更新 | `ui-branding.yaml` 的 `app_version` 由 `update.sh` 自动同步；品牌名/Logo 等需手动改或执行 `migrate_branding.py apply` |
| `update.sh` 报「更新包包含 runtime 业务数据目录」 | 该包不是用 `package.sh` 打的，或打包时混入了运行时数据；重新用 `package.sh` 生成 |

## 8. 验收清单

首次部署完成后，逐项确认：

- [ ] `./start.sh status` 显示运行中，`/api/health` 返回 `status=ok`
- [ ] `.env` 中至少一个 LLM API Key 可用；`JWT_SECRET` 可留空（`./start.sh` 首次写入根目录 `.env`），示例占位值或过短密钥会被拒绝
- [ ] 浏览器访问 `http://<host>:<port>` 能打开登录页
- [ ] 首个管理员账号已初始化（生产环境建议关闭 `allow_public_registration`；可用 `ADMIN_INITIAL_PASSWORD` 覆盖初始密码）
- [ ] `runtime/` 目录权限合理（参考 [部署加固指南](deployment-hardening.md) 的权限建议）
- [ ] 备份策略就位（`runtime/update_backups/` 或独立的数据卷备份）

---

<a id="english"></a>

## English

> Applies to V0.3.16 (2026-08-28). This guide covers "how code is distributed from the dev machine to the target server". It complements [Deployment Hardening](deployment-hardening.md) — that one covers the target server's network topology, daemon, and security hardening, while this one covers packaging artifacts and the distribution/install flow.

## 1. Scope

A reproducible, auditable "dev machine → target server" distribution chain covering:

- Generating a release package on the dev machine containing only code and config templates (no secrets, no business data).
- First-time deployment on a fresh server.
- Version updates on an already-deployed server (with automatic backup, health check, and rollback on failure).
- Migration of runtime data and branding config.

Core constraints (consistent with `CLAUDE.md`):

- **Data/code separation**: the release package never contains `runtime/` business data (database, uploads, vector store, logs, results).
- **Open-source compliance**: the package contains no brand names or internal domains — only the `ui-branding.example.yaml` template.
- **Secret isolation**: `.env` is not packaged; each server configures its own.

## 2. Three Scripts

| Script | Runs on | Purpose |
| --- | --- | --- |
| `package.sh` | Dev machine | Packages current code and config templates into a `*-code-config*.tar.gz` release |
| `start.sh` | Target server | `start / stop / restart / status` for the service; manages PID and logs |
| `update.sh` | Target server | Takes the release package and runs validate → backup → replace → branding scan/plan → health check → rollback on failure |

Overall flow:

```text
Dev machine                    Target server
 package.sh ──┐
              ├─ *-code-config*.zip (default) ──►  First deploy: unzip + install deps + start.sh
              ├─ *-code-config*.tar.gz       ──►  Update: update.sh (auto backup/validate/rollback)
```

## 3. Packaging (on the dev machine)

### 3.1 Usage

```bash
./package.sh                      # default: zip format, output to ./dist
./package.sh --format tar.gz      # tar.gz (required by the update.sh auto-update flow)
./package.sh --format both        # produce both zip and tar.gz
./package.sh --list               # also print the package file manifest
./package.sh --output /tmp        # specify output directory
./package.sh --build-no 0598      # specify build number (default: timestamp YYYYMMDDHHMM)
```

Artifact naming: `prd-draft-review-workflow-v1-code-config-v{version}-build{build}.{zip|tar.gz}`. The version comes from the root `VERSION` file (same source as `update.sh`; older packages fall back to `src/app/version.py` / `src/main.py`). Default is zip; tar.gz is the format `update.sh` auto-detects.

### 3.2 Package Contents

| Category | Members |
| --- | --- |
| Code dirs | `src/` `tools/` `tests/` `docs/` `skills/` |
| Root scripts | `start.sh` `update.sh` |
| Dependency manifests | `requirements.txt` `pyproject.toml` `package.json` |
| Docs & license | `README.md` `CLAUDE.md` `LICENSE` `.env.example` |
| Config template | `runtime/config/ui-branding.example.yaml` |

> Note: `update.sh` syncs `src tools tests docs skills` and several root files (including `package.json` and `package-lock.json`). If the `pi-coding-agent` version changes, run `npm install` on the target server after updating to install new dependencies. Application Python dependencies come from `requirements.txt` and are installed with `pip`. `pyproject.toml` only holds pytest/ruff tool config — **not** the app dependency list. The repo does not track `uv.lock` (an empty lockfile can mislead some platforms into `uv sync` and fail to install packages); packages also omit `uv.lock`.

### 3.3 Excluded (automatic)

- `node_modules/` (large; installed locally on the target via `npm install`)
- `.git/`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache`, etc.
- `.env` (secrets), `.DS_Store`, `*.swp`
- Business data under `runtime/`: `data/` `uploads/` `logs/` `results/` `vector*/` `storage/`
- `runtime/config/ui-branding.yaml` (real branding config; only the `*.example.yaml` template is kept)
- `eval/` experiment and evaluation directories (POC selection and formal acceptance)

### 3.4 Self-check

After packaging, the script runs a built-in self-check (mirroring `update.sh`'s `validate_update_package` rules). If any check fails, the artifact is deleted and the script exits with failure:

- Must contain `src/main.py`
- Must not contain unsafe paths (absolute paths or `..`)
- Must not contain `runtime/data|uploads|logs|results|storage|vector` business-data directories
- Must not contain a bare `.env`, `node_modules`, or `.git`
- Must not contain macOS AppleDouble files (`._*`), to avoid polluting the Linux deployment directory

## 4. First Deployment (fresh server)

### 4.1 Prerequisites

The target server needs: Python 3.10+, Node.js 22.19+, npm (required for Pi Agent; skip Node if you don't use Agent).

### 4.2 Steps

```bash
# 1) Transfer and extract (deploy dir is customizable; example uses /opt/ai-review)
mkdir -p /opt/ai-review
#    Default zip package:
unzip prd-draft-review-workflow-v1-code-config-v0.3.16-build*.zip -d /opt/ai-review
#    Or tar.gz: tar -xzf prd-draft-review-workflow-v1-code-config-v0.3.16-build*.tar.gz -C /opt/ai-review
cd /opt/ai-review

# 2) Configure secrets (package only has .env.example, no real secrets)
cp .env.example .env
#    Edit .env: fill in DEEPSEEK_API_KEY/QWEN_API_KEY/GLM_API_KEY/OPENAI_API_KEY;
#              JWT_SECRET may be empty (first start writes it to the project-root .env);
#              example placeholders or short secrets are still rejected:
#                python3 -c "import secrets; print(secrets.token_hex(32))"
#              Optional ADMIN_INITIAL_PASSWORD to override the first admin password;
#              set SERVER_PORT as needed (default 17957).

# 3) Install dependencies (recommended inside a venv)
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
npm install            # only needed for Pi Agent

# 4) Branding/port config (optional; defaults are baked in if unchanged)
cp runtime/config/ui-branding.example.yaml runtime/config/ui-branding.yaml
#    Edit ui-branding.yaml: set brand name, logo, login notice, etc.

# 5) Start
./start.sh start       # PID -> runtime/server.pid, logs -> runtime/logs/app.log
./start.sh status      # show status and run a health check
```

Health check endpoint: `GET http://<host>:<port>/api/health`; a healthy response is `{"status":"ok","version":"0.3.16"}`.

> For production, prefer Nginx reverse proxy + systemd supervision — see [Deployment Hardening](deployment-hardening.md). systemd's `EnvironmentFile` should point to `.env` to keep `JWT_SECRET` out of command-line args. On shutdown the app cancels background review tasks and the Embedding Worker before disposing of the database engine.

### 4.3 Sub-path Deployment (optional)

By default the app assumes it owns the site root (`https://host/`). To mount it under a sub-path (e.g. `https://host/prd-review/`) alongside other apps:

1. Set the prefix and listen address in `.env`:

   ```bash
   ROOT_PATH=/prd-review     # match the mounted sub-path; no trailing slash
   SERVER_HOST=127.0.0.1     # default loopback; exposed only via reverse proxy
   SERVER_PORT=17957
   ```

   `start.sh` passes `ROOT_PATH` to `uvicorn --root-path`; the frontend auto-derives the API prefix from the actual page path, so no extra config is needed.

2. The reverse proxy must **strip the prefix** before forwarding to the backend (`start.sh` already passes `ROOT_PATH` to `uvicorn --root-path`; backend routes match the stripped path - without stripping, the extra prefix causes 404). Caddy example:

   ```
   redir /prd-review /prd-review/ 308
   handle_path /prd-review/* {
       reverse_proxy 127.0.0.1:17957
   }
   ```

   Nginx equivalent:

   ```nginx
   location = /prd-review { return 308 /prd-review/; }
   location /prd-review/ {
       proxy_pass http://127.0.0.1:17957/;   # trailing / makes Nginx strip the /prd-review/ prefix
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   }
   ```

   The `/prd-review` → `/prd-review/` trailing-slash redirect is mandatory: the frontend uses `./` relative paths, and without the trailing slash the browser resolves them against the site root.

3. Verify: both `curl http://127.0.0.1:17957/api/health` (direct, no prefix) and `curl https://host/prd-review/api/health` (via proxy, with prefix) should return `{"status":"ok",...}`.

## 5. Version Update (deployed server)

### 5.1 Usage

```bash
# Put the new package in the project root and run (auto-discovers *code-config*.tar.gz in the current dir)
./update.sh
# Or specify the package path explicitly
./update.sh --package ./prd-draft-review-workflow-v1-code-config-v0.3.16-build*.tar.gz
```

Common options:

| Option | Purpose |
| --- | --- |
| `--package PATH` | Specify the update package path |
| `--force` | Force update even when current and target versions match |
| `--skip-migrate` | Skip branding migration scan/plan |
| `--skip-backup` | Skip backup (disables auto-rollback on failure; use with caution) |
| `--no-rollback` | Do not auto-rollback on health-check failure |

### 5.2 Update Flow

`update.sh` runs in order:

1. **Version compare**: after unpacking, reads the package's root `VERSION` file first (`PACKAGE_VERSION`; falls back to `APP_VERSION` in `src/app/version.py` / `src/main.py`) and compares it with the current version on the target host; exits if equal and `--force` is not set.
2. **Package validation**: path safety, no business-data dirs, contains `src/main.py`.
3. **Stop service**: calls `start.sh stop`.
4. **Backup**: backs up current code, `runtime/config`, `runtime/assets`, and `.env` to `runtime/update_backups/backup-<version>-<timestamp>/`.
5. **Branding migration scan/plan** (**before** replacing code): reads text config from the old HTML and generates `runtime/config/ui-branding.scan-report.md` diff report. **Only generates the report, does not auto-apply** — to avoid overwriting the target's existing branding.
6. **Replace code**: overwrites `src tools tests docs skills` and root files.
7. **Sync version**: aligns `app_version` in `runtime/config/ui-branding.yaml` to the new version.
8. **Start + health check**: `start.sh start`, then polls `/api/health`.
9. **Rollback on failure**: if the health check fails, restores from the step-4 backup and restarts.

### 5.3 Version Consistency

`update.sh` compares the target host's current version against the package's root `VERSION` file (`PACKAGE_VERSION`): it refuses to update only when they match and `--force` is not set. The `NEW_VERSION` constant at the top of the script is only a fallback when reading the package fails and no longer decides whether to update. When releasing, you only need to bump the root `VERSION` file (the packaging script names the artifact from it); keeping the `version` in `package.json` in sync is recommended.

## 6. Runtime Data Migration (moving across servers, optional)

The release package does not contain runtime data. To migrate existing business data to a new server:

```bash
# Source server: pack runtime data (do this after stopping the service to avoid DB write contention)
./start.sh stop
tar -czf runtime-backup-$(date +%Y%m%d).tar.gz -C runtime data uploads vector assets config

# Transfer to the new server and extract into the runtime/ dir
# New server: have this in place after first deploy, before starting
tar -xzf runtime-backup-*.tar.gz -C /opt/ai-review/runtime
./start.sh start
```

Migration notes:

- **Database** (SQLite) file lock: always stop the service before packing; `aiosqlite` is sensitive to file locks.
- **Branding config**: if the source customized `runtime/config/ui-branding.yaml`, after migration run `python3 tools/migrate_branding.py apply --legacy-code-dir . --legacy-runtime-dir runtime --target-runtime-dir runtime` per the scan/plan report; review `ui-branding.scan-report.md` before applying.
- **Vector store**: `runtime/vector*/` paths are tied to the retrieval engine config in the new code; confirm the `src/config.yaml` retrieval engine settings match before cross-major-version migration.

## 7. Common Issues

| Symptom | Troubleshooting |
| --- | --- |
| `update.sh` says "code is already X.X.X, no update needed" | The target host's version matches the package's root `VERSION`; use `--force`, or confirm the root `VERSION` file was updated |
| Pi Agent doesn't work after update | `update.sh` syncs `package.json` and `package-lock.json` but does not run `npm install` automatically; run `npm install` manually on the target server |
| Health check fails after startup | Check `runtime/logs/app.log`; common causes: missing LLM keys in `.env`, `JWT_SECRET` too short or example placeholder rejected, port in use, dependencies not installed |
| Frontend branding not updated | `app_version` in `ui-branding.yaml` is synced by `update.sh`; brand name/logo must be edited manually or via `migrate_branding.py apply` |
| `update.sh` reports "package contains runtime business-data dirs" | The package wasn't built by `package.sh`, or runtime data leaked in; rebuild with `package.sh` |

## 8. Acceptance Checklist

After first deployment, confirm each item:

- [ ] `./start.sh status` shows running; `/api/health` returns `status=ok`
- [ ] At least one LLM API Key in `.env` works; `JWT_SECRET` may be empty (`./start.sh` writes it to the project-root `.env` on first start); placeholders and short secrets are rejected
- [ ] Browser opens the login page at `http://<host>:<port>`
- [ ] The first admin account is initialized (for production, consider disabling `allow_public_registration`; use `ADMIN_INITIAL_PASSWORD` to override the initial password)
- [ ] `runtime/` directory permissions are reasonable (see [Deployment Hardening](deployment-hardening.md))
- [ ] A backup strategy is in place (`runtime/update_backups/` or an independent data-volume backup)
