# 配置说明 / Configuration

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

> 面向运维 / 部署人员。本文档说明「AI 需求评审工作流平台」(FastAPI + SQLite，部门内网部署) 的三层配置体系：环境变量、应用配置文件、品牌配置文件。
>
> For ops / deployment engineers. This document describes the three-layer configuration of the *AI Requirement Review Workflow Platform* (FastAPI + SQLite, deployed on the department intranet): environment variables, application config file, and branding config file.

---

<a id="中文"></a>

## 中文

### 配置三层总览

| 层级 Layer | 来源 Source | 作用 Purpose | 修改后是否需重启 |
|------------|-------------|--------------|------------------|
| ① 环境变量 | `.env`(由 `.env.example` 复制) | 密钥、端口、部署路径等部署相关 | 否(start.sh 启动时读取;改后下次重启生效) |
| ② 应用配置 | `src/config.yaml` | 数据库、认证、模型、上传、评审流程参数 | 是 |
| ③ 品牌配置 | `runtime/config/ui-branding.yaml` | 界面文案、主题色、Logo / favicon | 否(运行时读取) |

**优先级(从高到低)**:环境变量 > `config.yaml` 中通过 `${ENV}` 引用的环境变量(启动时动态展开) > `config.yaml` 默认值。品牌配置单独按「`ui-branding.yaml` > `config.yaml` 的 `ui_branding` 段 > 代码内置默认值」合并。

---

### 一、环境变量(`.env`)

从 `.env.example` 复制为 `.env` 后填入真实值。`*` 标注的 LLM Key 至少需填一个,否则平台无可用模型。

| 变量 | 必填 | 标记 | 说明 |
|------|------|------|------|
| `DEEPSEEK_API_KEY` | 否* | 🔐 [敏感] | DeepSeek API 密钥 |
| `QWEN_API_KEY` | 否* | 🔐 [敏感] | 通义千问 API 密钥 |
| `GLM_API_KEY` | 否* | 🔐 [敏感] | 智谱 GLM API 密钥 |
| `OPENAI_API_KEY` | 否* | 🔐 [敏感] | OpenAI API 密钥 |
| `OPENAI_API_BASE` | 否 | — | OpenAI 兼容 API 基址,留空用官方 endpoint |
| `EMBEDDING_MODEL` | 否 | — | 知识库向量模型,默认 `text-embedding-3-small` |
| `EMBEDDING_DIMENSIONS` | 否 | — | 向量维度,默认 `1536` |
| `JWT_SECRET` | **是(生产)** | 🔐 [敏感] | JWT 签名密钥,**至少 32 字符**随机串。生成: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_INITIAL_PASSWORD` | 否 | 🔐 [敏感] | 覆盖首个 admin 账号初始密码;不填则用内置预设并告警 |
| `SERVER_PORT` | 否 | — | 服务端口,默认 `17957` |
| `SERVER_HOST` | 否 | — | 监听地址,默认 `127.0.0.1`(仅回环,经反代对外);直连部署设 `0.0.0.0` |
| `ROOT_PATH` | 否 | — | 子路径反代部署前缀,如 `/prd-review`;根路径部署留空 |
| `RUNTIME_ROOT` | 否 | — | 运行时数据目录,默认 `<项目目录>/runtime` |
| `CONFIG_PATH` | 否 | — | 应用配置文件路径,默认 `src/config.yaml` |
| `AGENT_API_BASE` | 否 | — | Agent 自回调基地址,默认 `http://127.0.0.1:<SERVER_PORT>` |

> \* LLM Keys 至少填一个,否则没有可用模型。

#### 🔐 JWT_SECRET 安全校验规则(重点,生产必读)

服务层 `assert_jwt_secret_safe()` 在启动时校验,以下三种情况会**抛 RuntimeError 阻止启动**:

1. **空值** —— 未配置或纯空白。
2. **已知不安全占位值** —— 命中黑名单将被拒绝:
   - `change-me-in-production`
   - `change-this-to-a-random-secret-string`
   - `secret`
   - `jwt-secret`
   - `your-secret-key`
3. **长度 < 32 字符** —— 过短,易被暴力破解。

**生成推荐**(64 字节十六进制,128 字符):

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**注意**:`start.sh` 在 `JWT_SECRET` 为空时会**自动生成一个临时 session 密钥**(仅适合本地开发试用)。但**生产环境必须显式配置一个持久随机密钥**,否则每次重启后所有已签发 token 全部失效,用户需要重新登录。

---

### 二、应用配置(`src/config.yaml`)

下表为默认值,一般无需修改;修改后**必须重启服务**才生效。其中 `${JWT_SECRET}` 等会在启动时展开为同名环境变量的值。

#### server

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `server.host` | `"0.0.0.0"` | 配置文件中的默认值;**实际监听受 `SERVER_HOST` 环境变量控制**,`start.sh` 默认用 `127.0.0.1` |
| `server.port` | `17957` | 端口(同样可被 `SERVER_PORT` 环境变量覆盖) |

#### database

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `database.path` | `"runtime/data/app.db"` | SQLite 数据库文件路径 |

#### auth

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `auth.secret_key` | `"${JWT_SECRET}"` | 引用环境变量(见上文校验规则) |
| `auth.algorithm` | `"HS256"` | JWT 签名算法 |
| `auth.access_token_expire_minutes` | `480` | token 有效期,即 **8 小时** |
| `auth.allow_public_registration` | `true` | 是否允许公开注册;**生产环境建议关闭** |
| `auth.sse_ticket_ttl_seconds` | `60` | SSE 短票据有效期(秒) |

#### models(预置 4 个模型,以 deepseek 为例)

每个模型对象字段:`id`、`name`、`adapter`(`openai_compatible`)、`base_url`、`api_key`(引用 `${ENV}`)、`model`、`max_tokens`、`temperature`、`enabled`。

| 模型 | id | base_url | model | max_tokens | temperature | 默认 enabled |
|------|----|----------|-------|-----------|-------------|--------------|
| DeepSeek Chat | `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` | `4096` | `0.7` | **`true`** |
| 通义千问 | `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | `4096` | `0.7` | `false` |
| 智谱 GLM | `glm` | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | `4096` | `0.7` | `false` |
| OpenAI(兼容) | — | 由 `OPENAI_API_BASE` 或官方 endpoint | — | `4096` | `0.7` | 视配置 |

`defaults.model: deepseek` 指定默认模型。切换默认模型时,确保对应模型的 `api_key` 已配置且 `enabled: true`。

#### upload(聊天附件)

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `upload.max_file_size_mb` | `20` | 聊天附件上限 |
| `upload.allowed_extensions` | `.txt .pdf .docx .md .csv .json` | 允许的附件扩展名 |
| `upload.upload_dir` | `runtime/uploads` | 附件存储目录 |

#### review(评审专属,独立配置)

**`review.upload`**(评审文档,与聊天附件分开限制):

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `review.upload.max_file_size_mb` | `50` | 评审文档上限(**比聊天附件 20MB 更大**) |
| `review.upload.allowed_extensions` | `.docx` | **只接受 Word 文档** |
| `review.upload.upload_dir` | `runtime/data/review_uploads` | 评审文档存储目录 |

**`review.skills_dir`**:`"./skills"` —— 评审技能目录。

**`review.retry`**(LLM 调用重试):

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `max_attempts` | `5` | 最大重试次数 |
| `initial_delay_ms` | `2000` | 首次重试延迟(毫秒) |
| `backoff_factor` | `2.0` | 退避因子(指数退避) |
| `max_delay_ms` | `30000` | 单次最大延迟(毫秒) |
| `timeout_seconds` | `300` | 请求总超时(秒) |
| `connect_timeout_seconds` | `10` | 连接超时(秒) |

**`review.pipeline`**(评审流水线):

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `step_max_retries` | `3` | 单步最大重试 |
| `step_retry_delay` | `5` | 步骤间重试延迟(秒) |
| `max_concurrent_docs` | `3` | **并发分析文档数** |

**`review.llm`**(评审专用 LLM 参数):

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `temperature` | `0.3` | **评审用更低温度**以保证输出稳定 |
| `max_tokens` | `4096` | 单次最大 token |

---

### 三、品牌配置(`runtime/config/ui-branding.yaml`)

将 `runtime/config/ui-branding.example.yaml` 复制为 `runtime/config/ui-branding.yaml` 后修改。**缺少此文件时自动使用通用默认品牌**,不影响启动。

**优先级(从高到低)**:
1. `runtime/config/ui-branding.yaml`
2. `src/config.yaml` 的 `ui_branding` 段
3. 代码内置默认值

#### 文案字段

| 字段 | 说明 |
|------|------|
| `app_title` | 应用标题 |
| `app_version` | 应用版本号 |
| `login_title` | 登录页主标题 |
| `login_subtitle` | 登录页副标题 |
| `login_notice` | 登录页提示,留空用默认;多行用 YAML block string(`\|`) |
| `topbar_title` | 顶栏标题 |
| `review_workspace_label` | 需求审查工作台标签 |
| `admin_label` | 管理后台标签 |

#### 主题色 `theme`

| 字段 | 示例 | 说明 |
|------|------|------|
| `primary` | `"#005AAA"` | 主题主色 |
| `primary_hover` | `"#2E7CC0"` | 主色悬停态 |
| `accent` | `"#23C343"` | 强调色 |

#### Logo / favicon(资产路径)

| 字段 | 说明 |
|------|------|
| `login_logo` | 登录页 Logo,**只填文件名** |
| `topbar_logo` | 顶栏 Logo,**只填文件名** |
| `favicon` | 站点 favicon,**只填文件名** |

资产文件放在 `runtime/assets/branding/` 目录下。

#### 🔐 资产路径安全约束(重要)

品牌配置中的资产字段**只允许文件名或安全相对路径**,后端 `serve_branding_asset` / `_validate_asset_path_safe()` 会校验路径必须解析到 `runtime/assets/branding/` 目录内。以下情况**违规,返回 404 并记录警告日志**:

- ❌ **绝对路径**(如 `/etc/passwd`、`C:\logo.png`)
- ❌ **`..` 路径穿越**(如 `../../secret.txt`)
- ❌ **外部 URL**(如 `https://cdn.example.com/logo.png`)

> 示例:`login_logo: "my-company-logo.png"` 正确;`login_logo: "/var/www/logo.png"` 或 `login_logo: "https://..."` 将被拒绝。

---

### 四、配置场景示例

#### 最小配置(本地试用)

```bash
# .env —— 仅本地试用,start.sh 会自动生成临时 JWT_SECRET
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
# JWT_SECRET 留空,start.sh 自动生成临时 session 密钥(重启后 token 失效)
```

#### 生产配置(推荐)

```bash
# .env —— 生产环境
# 1) 至少配置一个 LLM Key
DEEPSEEK_API_KEY=sk-your-deepseek-key-here

# 2) 持久随机 JWT_SECRET(至少 32 字符,生产必填)
#    生成: python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=<替换为上面命令生成的 128 字符随机串>

# 3) 部署相关
SERVER_HOST=127.0.0.1      # 经反向代理对外暴露(推荐);直连改为 0.0.0.0
SERVER_PORT=17957
ROOT_PATH=                 # 根路径部署留空;子路径如 /prd-review

# 4) 可选:覆盖首个 admin 初始密码
# ADMIN_INITIAL_PASSWORD=<强密码>
```

> 生产环境建议同时在 `src/config.yaml` 中将 `auth.allow_public_registration` 改为 `false`。

---

<a id="english"></a>

## English

### Configuration Overview (Three Layers)

| Layer | Source | Purpose | Restart required? |
|-------|--------|---------|-------------------|
| ① Environment variables | `.env` (copied from `.env.example`) | Deployment-specific: keys, port, paths | No (read at start by `start.sh`; changes apply on next restart) |
| ② Application config | `src/config.yaml` | Database, auth, models, upload, review pipeline | Yes |
| ③ Branding config | `runtime/config/ui-branding.yaml` | UI copy, theme colors, Logo / favicon | No (read at runtime) |

**Priority (high → low)**: Environment variables > `${ENV}` references in `config.yaml` (expanded dynamically at startup) > `config.yaml` defaults. Branding merges separately: `ui-branding.yaml` > `ui_branding` section in `config.yaml` > built-in code defaults.

---

### 1. Environment Variables (`.env`)

Copy `.env.example` to `.env` and fill in real values. At least one `*`-marked LLM Key is required, otherwise the platform has no usable model.

| Variable | Required | Mark | Description |
|----------|----------|------|-------------|
| `DEEPSEEK_API_KEY` | No* | 🔐 [Sensitive] | DeepSeek API key |
| `QWEN_API_KEY` | No* | 🔐 [Sensitive] | Tongyi Qianwen API key |
| `GLM_API_KEY` | No* | 🔐 [Sensitive] | Zhipu GLM API key |
| `OPENAI_API_KEY` | No* | 🔐 [Sensitive] | OpenAI API key |
| `OPENAI_API_BASE` | No | — | OpenAI-compatible API base; empty = official endpoint |
| `EMBEDDING_MODEL` | No | — | Knowledge-base embedding model, default `text-embedding-3-small` |
| `EMBEDDING_DIMENSIONS` | No | — | Vector dimensions, default `1536` |
| `JWT_SECRET` | **Yes (prod)** | 🔐 [Sensitive] | JWT signing secret, **at least 32 characters** random. Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_INITIAL_PASSWORD` | No | 🔐 [Sensitive] | Override the first admin account's initial password; uses a built-in preset (with warning) if unset |
| `SERVER_PORT` | No | — | Service port, default `17957` |
| `SERVER_HOST` | No | — | Listen address, default `127.0.0.1` (loopback only, exposed via reverse proxy); set `0.0.0.0` for direct deployment |
| `ROOT_PATH` | No | — | Sub-path reverse-proxy prefix, e.g. `/prd-review`; leave empty for root-path deployment |
| `RUNTIME_ROOT` | No | — | Runtime data directory, default `<project>/runtime` |
| `CONFIG_PATH` | No | — | Application config file path, default `src/config.yaml` |
| `AGENT_API_BASE` | No | — | Agent self-callback base URL, default `http://127.0.0.1:<SERVER_PORT>` |

> \* Provide at least one LLM Key, otherwise no model is available.

#### 🔐 JWT_SECRET Safety Rules (Important — Read for Production)

The service `assert_jwt_secret_safe()` validates at startup; the following three cases **raise RuntimeError and block startup**:

1. **Empty** — unset or whitespace-only.
2. **Known unsafe placeholder** — the blacklist is rejected:
   - `change-me-in-production`
   - `change-this-to-a-random-secret-string`
   - `secret`
   - `jwt-secret`
   - `your-secret-key`
3. **Length < 32 characters** — too short, brute-forceable.

**Recommended generation** (64-byte hex, 128 chars):

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**Note**: When `JWT_SECRET` is empty, `start.sh` **auto-generates a temporary session secret** (suitable for local trial only). In **production you must set a persistent random secret explicitly**, otherwise every restart invalidates all issued tokens and forces users to log in again.

---

### 2. Application Config (`src/config.yaml`)

The values below are defaults and usually need no change; any change **requires a service restart** to take effect. Values like `${JWT_SECRET}` are expanded to the matching environment variable at startup.

#### server

| Field | Default | Description |
|-------|---------|-------------|
| `server.host` | `"0.0.0.0"` | Default in the config file; **actual listening is controlled by the `SERVER_HOST` env var** — `start.sh` defaults to `127.0.0.1` |
| `server.port` | `17957` | Port (also overridable by the `SERVER_PORT` env var) |

#### database

| Field | Default | Description |
|-------|---------|-------------|
| `database.path` | `"runtime/data/app.db"` | SQLite database file path |

#### auth

| Field | Default | Description |
|-------|---------|-------------|
| `auth.secret_key` | `"${JWT_SECRET}"` | References env var (see validation rules above) |
| `auth.algorithm` | `"HS256"` | JWT signing algorithm |
| `auth.access_token_expire_minutes` | `480` | Token lifetime, i.e. **8 hours** |
| `auth.allow_public_registration` | `true` | Allow public registration; **recommended to disable in production** |
| `auth.sse_ticket_ttl_seconds` | `60` | SSE short-ticket TTL (seconds) |

#### models (4 preset models, deepseek shown as example)

Each model object has: `id`, `name`, `adapter` (`openai_compatible`), `base_url`, `api_key` (references `${ENV}`), `model`, `max_tokens`, `temperature`, `enabled`.

| Model | id | base_url | model | max_tokens | temperature | Default enabled |
|-------|----|----------|-------|-----------|-------------|-----------------|
| DeepSeek Chat | `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` | `4096` | `0.7` | **`true`** |
| Tongyi Qianwen | `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | `4096` | `0.7` | `false` |
| Zhipu GLM | `glm` | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | `4096` | `0.7` | `false` |
| OpenAI (compatible) | — | via `OPENAI_API_BASE` or official endpoint | — | `4096` | `0.7` | depends |

`defaults.model: deepseek` sets the default model. When switching the default, ensure the target model's `api_key` is set and `enabled: true`.

#### upload (chat attachments)

| Field | Default | Description |
|-------|---------|-------------|
| `upload.max_file_size_mb` | `20` | Chat attachment size limit |
| `upload.allowed_extensions` | `.txt .pdf .docx .md .csv .json` | Allowed attachment extensions |
| `upload.upload_dir` | `runtime/uploads` | Attachment storage directory |

#### review (review-specific, independent config)

**`review.upload`** (review documents, separate from chat attachments):

| Field | Default | Description |
|-------|---------|-------------|
| `review.upload.max_file_size_mb` | `50` | Review document limit (**larger than the 20MB chat limit**) |
| `review.upload.allowed_extensions` | `.docx` | **Only Word documents accepted** |
| `review.upload.upload_dir` | `runtime/data/review_uploads` | Review document storage directory |

**`review.skills_dir`**: `"./skills"` — review skills directory.

**`review.retry`** (LLM call retry):

| Field | Default | Description |
|-------|---------|-------------|
| `max_attempts` | `5` | Max retry attempts |
| `initial_delay_ms` | `2000` | First retry delay (ms) |
| `backoff_factor` | `2.0` | Backoff factor (exponential) |
| `max_delay_ms` | `30000` | Max single delay (ms) |
| `timeout_seconds` | `300` | Total request timeout (s) |
| `connect_timeout_seconds` | `10` | Connect timeout (s) |

**`review.pipeline`** (review pipeline):

| Field | Default | Description |
|-------|---------|-------------|
| `step_max_retries` | `3` | Max retries per step |
| `step_retry_delay` | `5` | Inter-step retry delay (s) |
| `max_concurrent_docs` | `3` | **Number of documents analyzed concurrently** |

**`review.llm`** (review-specific LLM parameters):

| Field | Default | Description |
|-------|---------|-------------|
| `temperature` | `0.3` | **Lower temperature for reviews** to ensure stable output |
| `max_tokens` | `4096` | Max tokens per call |

---

### 3. Branding Config (`runtime/config/ui-branding.yaml`)

Copy `runtime/config/ui-branding.example.yaml` to `runtime/config/ui-branding.yaml` and edit. **If the file is missing, the generic default branding is used automatically** and startup is unaffected.

**Priority (high → low)**:
1. `runtime/config/ui-branding.yaml`
2. `ui_branding` section in `src/config.yaml`
3. Built-in code defaults

#### Text fields

| Field | Description |
|-------|-------------|
| `app_title` | Application title |
| `app_version` | Application version |
| `login_title` | Login page main title |
| `login_subtitle` | Login page subtitle |
| `login_notice` | Login page notice; empty = default; multiline via YAML block string (`\|`) |
| `topbar_title` | Top bar title |
| `review_workspace_label` | Review workspace label |
| `admin_label` | Admin console label |

#### Theme colors `theme`

| Field | Example | Description |
|-------|---------|-------------|
| `primary` | `"#005AAA"` | Primary theme color |
| `primary_hover` | `"#2E7CC0"` | Primary hover state |
| `accent` | `"#23C343"` | Accent color |

#### Logo / favicon (asset paths)

| Field | Description |
|-------|-------------|
| `login_logo` | Login page Logo, **filename only** |
| `topbar_logo` | Top bar Logo, **filename only** |
| `favicon` | Site favicon, **filename only** |

Place asset files in the `runtime/assets/branding/` directory.

#### 🔐 Asset Path Security Constraint (Important)

Asset fields in the branding config **accept only filenames or safe relative paths**. The backend `serve_branding_asset` / `_validate_asset_path_safe()` verifies the resolved path stays inside `runtime/assets/branding/`. The following are **rejected with HTTP 404 and a warning log**:

- ❌ **Absolute paths** (e.g. `/etc/passwd`, `C:\logo.png`)
- ❌ **`..` path traversal** (e.g. `../../secret.txt`)
- ❌ **External URLs** (e.g. `https://cdn.example.com/logo.png`)

> Example: `login_logo: "my-company-logo.png"` is valid; `login_logo: "/var/www/logo.png"` or `login_logo: "https://..."` will be rejected.

---

### 4. Configuration Scenario Examples

#### Minimal Config (Local Trial)

```bash
# .env — local trial only; start.sh auto-generates a temporary JWT_SECRET
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
# Leave JWT_SECRET empty; start.sh generates a temporary session secret
# (tokens become invalid after restart)
```

#### Production Config (Recommended)

```bash
# .env — production
# 1) Configure at least one LLM Key
DEEPSEEK_API_KEY=sk-your-deepseek-key-here

# 2) Persistent random JWT_SECRET (>= 32 chars, required in production)
#    Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=<paste the 128-char random string from the command above>

# 3) Deployment
SERVER_HOST=127.0.0.1      # Exposed via reverse proxy (recommended); use 0.0.0.0 for direct
SERVER_PORT=17957
ROOT_PATH=                 # Empty for root-path; sub-path e.g. /prd-review

# 4) Optional: override the first admin's initial password
# ADMIN_INITIAL_PASSWORD=<strong-password>
```

> For production, also consider setting `auth.allow_public_registration` to `false` in `src/config.yaml`.
