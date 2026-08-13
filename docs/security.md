# 安全与权限 / Security & Permissions

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

---

> **读者对象 / Audience**:安全审查人员、运维与平台管理员 / Security reviewers, operations and platform administrators.
>
> 本文基于源码实证梳理「AI 需求评审工作流平台」已落地的安全与权限模型,所有条目均对应可核查的代码能力,而非规划。

---

<a id="中文"></a>

## 中文

本平台部署于**部门内网**,承载敏感的需求文档、专家意见与分析产物,**安全是核心诉求**。本文档系统梳理已落地的认证、访问控制、Agent 安全、数据安全与运行时安全机制,所有条目均有源码支撑。

### 一、三层角色体系

平台采用「系统级 → 工作空间级 → 协作评审级」三层角色,职责清晰、最小权限。

| 层级 | 字段 / 取值 | 职责 |
| --- | --- | --- |
| **系统级角色** | `users.role`:`user` / `admin` | `admin` 可访问 `/api/admin` 进行治理与运营;普通用户不可提权。 |
| **工作空间角色** | `workspace_members.role`(`VALID_MEMBER_ROLES`):`owner` / `admin` / `member` / `viewer` | 空间维度的所有权与管理、成员、只读查看者。 |
| **协作评审角色** | `review_participants`:`Observer` / `Reviewer` / `Approver` / 发起人 / 项目管理员 | `Observer` 只读(不可写、不可确认);`Reviewer` 可写;`Approver` 可做决策;发起人、项目管理员可写可确认。 |

- **统一权限入口**:所有 workspace 域与 review 域操作均经过 `require_action` + `is_active_member` 校验,避免在业务路由里分散实现鉴权逻辑。
- **非活跃成员拦截**:非活跃成员自动被阻止访问项目与引用来源,即使持有历史 ID。

### 二、认证机制(JWT + bcrypt)

- **登录签发**:用户通过 `POST /api/auth/login` 验证账号密码后获取 JWT。密码以 **bcrypt 哈希**存储,明文不可逆。
- **算法与有效期**:JWT 签名算法 **HS256**,Token 有效期 **480 分钟(8 小时)**,前端存储于 `localStorage`。
- **JWT_SECRET 安全校验(启动期硬阻断)**:Service 层 `assert_jwt_secret_safe` 拒绝已知不安全占位值和不足 32 字符的密钥,直接抛 `RuntimeError` 阻止进程启动。空值不会拒绝启动：`./start.sh` 会先生成随机密钥并写入项目根目录 `.env`；不走官方脚本时 `config.py` 会生成进程内临时密钥（不落盘，重启后 token 失效）。占位值示例:`change-me-in-production`、`change-this-to-a-random-secret-string`、`secret`、`jwt-secret`、`your-secret-key`。配置方法见 [configuration.md](./configuration.md)。
- **SSE 短票据(避免 Token 泄露)**:SSE 流式端点(通知流、Agent 流)无法使用 `Authorization: Bearer` 头(EventSource 限制),平台改用**一次性短票据**:
  - `POST /api/auth/sse-ticket` 获取票据,**TTL 60 秒**,单次消费即失效;
  - 以 `?ticket=` 查询参数连接 SSE。
  - **不再通过 query 传递 JWT Token**,避免 Token 被写入访问日志、Referer 或浏览器历史。
- **注册策略**:`allow_public_registration` 控制是否开放公开注册;注册**不再自动提权为管理员**;首个 `admin` 通过离线方式初始化,杜绝"注册即管理员"风险。

### 三、访问控制(BOLA 防护重点)

- **对象级权限拆分**:`ReviewRequest` / `Round` / `Participant`、`Artifact` 等对象在 `object_access` 层面做了细粒度**读 vs 写**拆分,而非仅做资源级粗粒度校验。
- **BOLA( Broken Object-Level Authorization)防护**:通过读/写权限拆分,阻止跨用户越权访问。例如:
  - `Observer` 只读,无法写入或确认;
  - 发起人 / `Reviewer` / `Approver` / 项目管理员可写可确认;
  - 只读角色(如 `viewer`、`Observer`)无法篡改对象,**阻止只读角色越权写入**。
- **工作空间成员校验**:所有相关操作经 `require_action` + `is_active_member`;聊天与审查启动均校验知识空间成员资格,**拒绝伪造 `workspace_id` 绕过配额**(`WorkspaceBudget` + `BudgetGuard` 硬限)。
- **只读角色防篡改**:`viewer` / `Observer` 等只读角色不可写、不可确认。

### 四、Agent 安全(重点)

Agent 在生产中可调用工具与模型,是最高风险面。平台采用多层防护:

- **deny-by-default 工具白名单**:工具列表默认拒绝,**空列表 → 仅允许 `rag_search`**。授权范围在 Extension 端点与 RAG 端点两处分别校验,避免单点遗漏。
- **高风险工具**:`bash` / `write` / `edit` / `read`:
  - 普通用户**不可自行启用**,也**不可自审批**;
  - 需管理员配置,并要求**独立审批人**(创建工具时 `approver_id` 必填,创建者本人不能同时是审批人)。
- **工具调用审批流**:高风险工具调用会产生待审批请求:
  - `GET /api/agent/approvals` 仅返回**当前用户作为审批人**的请求(隔离他人审批队列);
  - `POST /api/agent/approvals/{request_id}/decide` 做出批准 / 拒绝决定,通过后才放行工具执行。
- **Pi Agent cwd 沙箱**:Agent 的工作目录被沙箱化在 `runtime/agent_sandboxes/` 下,限制文件操作的辐射范围。
- **MCP 鉴权分层**:
  - 全局 MCP 配置需**管理员**权限;
  - 工作空间级 MCP 需 **manage** 权限,普通成员不可越权改写全局/空间级 Agent 配置。

> 关于管理员侧的工具配置与审批治理操作,参见 [admin-guide.md](./admin-guide.md)。

### 五、数据安全

- **数据与代码分离**:所有数据库、上传文件、转换中间文件、日志、评审产物统一落在 `runtime/` 目录下,默认被 `.gitignore` 忽略。源码不混入业务数据,**降低跨环境(开发 / 测试 / 生产)泄露风险**。
- **内网闭环**:整套工作流运行于部门内网,对接内网大模型或企业可控模型;需求文档、专家意见、分析结果**全程不出网**。
- **敏感项隔离(打包分发)**:打包脚本(`package.sh`)产出的分发包严格剔除:
  - `.env`(含密钥);
  - `runtime/` 业务数据;
  - 真实品牌配置(仅附带 `ui-branding.example.yaml` 模板);
  - 真实品牌名 / 内部域名。
- **密钥加密存储**:模型 API Key **加密存储**,不以明文落库;`JWT_SECRET` 在启动期经 `assert_jwt_secret_safe` 强制校验。

### 六、上传安全

- **路径穿越(Path Traversal)防护**:聊天附件以 `file_id` 安全解析文件路径,**阻止 `..` 穿越与绝对路径逃逸**。
- **品牌资产路径校验**:`serve_branding_asset` 校验请求路径必须落在 `runtime/assets/branding/` 目录内,拒绝 `..` 穿越与绝对路径越界。
- **扩展名 / 大小限制**:
  - 聊天附件:`.txt` / `.pdf` / `.docx` / `.md` / `.csv` / `.json`,**≤ 20 MB**;
  - 评审文档:`.docx`,**≤ 50 MB**。
- **外键约束**:SQLite 启用 `foreign_keys=ON`,依赖外键约束保证引用完整性。

### 七、运行时安全

- **优雅停机**:应用生命周期(`lifespan`)在关闭时会**先取消审查后台任务与 Embedding Worker**,再释放 SQLAlchemy 引擎,避免脏数据与连接泄漏。
- **防缓存中间件**:`NoCacheMiddleware` 为敏感响应设置禁缓存头,防止敏感数据被浏览器或中间代理缓存。

---

<a id="english"></a>

## English

This platform is deployed **on the department intranet** and carries sensitive requirements documents, expert opinions and analysis artifacts. **Security is a first-class concern.** This document systematically describes the authentication, access control, Agent security, data security and runtime security mechanisms that are already implemented. Every statement below is backed by source code.

### 1. Three-Tier Role Model

The platform uses three layers — System → Workspace → Collaborative Review — with clear responsibilities and least privilege.

| Layer | Field / Values | Responsibility |
| --- | --- | --- |
| **System role** | `users.role`: `user` / `admin` | `admin` can access `/api/admin` for governance and operations; regular users cannot self-elevate. |
| **Workspace role** | `workspace_members.role` (`VALID_MEMBER_ROLES`): `owner` / `admin` / `member` / `viewer` | Workspace-level ownership, management, membership and read-only viewing. |
| **Review role** | `review_participants`: `Observer` / `Reviewer` / `Approver` / Initiator / Project Admin | `Observer` is read-only (no writes, no confirmation); `Reviewer` can write; `Approver` can make decisions; the initiator and project admin can both write and confirm. |

- **Unified authorization entry point**: All operations in the workspace and review domains pass through `require_action` + `is_active_member`, instead of ad-hoc checks scattered across business routes.
- **Inactive member blocking**: Inactive members are automatically blocked from accessing projects and source references, even if they still hold historical IDs.

### 2. Authentication (JWT + bcrypt)

- **Login issuance**: Users call `POST /api/auth/login`; upon successful credential verification a JWT is returned. Passwords are stored as **bcrypt hashes** (non-reversible).
- **Algorithm & lifetime**: JWT is signed with **HS256**; the token is valid for **480 minutes (8 hours)** and stored in `localStorage` on the client.
- **JWT_SECRET safety check (hard-fail at startup)**: The service-layer `assert_jwt_secret_safe` rejects known insecure placeholders and secrets shorter than 32 characters (`MIN_JWT_SECRET_LENGTH = 32`) by raising `RuntimeError`. An empty value does not refuse startup: `./start.sh` generates a random secret and writes it to the project-root `.env`; if you skip the official script, `config.py` generates an in-process ephemeral secret (not persisted; tokens die after restart). Placeholder examples: `change-me-in-production`, `change-this-to-a-random-secret-string`, `secret`, `jwt-secret`, `your-secret-key`. For configuration see [configuration.md](./configuration.md).
- **SSE short-lived ticket (avoids token leakage)**: SSE streaming endpoints (notification stream, Agent stream) cannot use the `Authorization: Bearer` header (an EventSource limitation), so the platform uses **single-use short-lived tickets** instead:
  - Obtain a ticket via `POST /api/auth/sse-ticket`, **TTL 60 seconds**, consumed once and then invalidated;
  - Connect to SSE with a `?ticket=` query parameter.
  - **JWT tokens are no longer passed via the query string**, preventing them from leaking into access logs, `Referer` headers or browser history.
- **Registration policy**: `allow_public_registration` controls whether public sign-up is open; registration **no longer auto-promotes to admin**; the first `admin` is bootstrapped offline, eliminating the "register-and-become-admin" risk.

### 3. Access Control (BOLA Protection Focus)

- **Object-level permission split**: Objects such as `ReviewRequest` / `Round` / `Participant` and `Artifact` have fine-grained **read-vs-write** splitting at the `object_access` layer, rather than coarse resource-level checks only.
- **BOLA (Broken Object-Level Authorization) protection**: The read/write split prevents cross-user unauthorized access. For example:
  - `Observer` is read-only and cannot write or confirm;
  - The initiator / `Reviewer` / `Approver` / project admin can write and confirm;
  - Read-only roles (e.g. `viewer`, `Observer`) cannot tamper with objects — **read-only roles are blocked from writing**.
- **Workspace membership verification**: All relevant operations go through `require_action` + `is_active_member`; chat and review start both verify knowledge-space membership and **reject forged `workspace_id` attempts to bypass quotas** (`WorkspaceBudget` + `BudgetGuard` hard limits).
- **Read-only tamper protection**: Read-only roles such as `viewer` / `Observer` cannot write or confirm.

### 4. Agent Security (Focus Area)

Agents can invoke tools and models in production, which is the highest-risk surface. The platform applies layered defense:

- **Deny-by-default tool allowlist**: The tool list is denied by default; an **empty list allows only `rag_search`**. The authorization scope is enforced in two places — the Extension endpoint and the RAG endpoint — to avoid a single point of failure.
- **High-risk tools** — `bash` / `write` / `edit` / `read`:
  - Regular users **cannot self-enable** them, nor **self-approve** them;
  - They require admin configuration and an **independent approver** (`approver_id` is mandatory at tool creation; the creator cannot also be the approver).
- **Tool-call approval flow**: A high-risk tool call produces a pending approval request:
  - `GET /api/agent/approvals` returns only requests where **the current user is the approver** (isolating other users' approval queues);
  - `POST /api/agent/approvals/{request_id}/decide` makes an approve / reject decision; only after approval is the tool actually executed.
- **Pi Agent cwd sandbox**: The Agent's working directory is sandboxed under `runtime/agent_sandboxes/`, bounding the blast radius of file operations.
- **Layered MCP authentication**:
  - Global MCP configuration requires **admin** privileges;
  - Workspace-level MCP requires **manage** privileges, so ordinary members cannot overwrite global or workspace Agent configuration.

> For admin-side tool configuration and approval governance operations, see [admin-guide.md](./admin-guide.md).

### 5. Data Security

- **Data / code separation**: All databases, uploaded files, conversion intermediates, logs and review artifacts live under the `runtime/` directory, which is `.gitignore`d by default. Source code never mixes with business data, **reducing cross-environment (dev / test / prod) leakage risk**.
- **Intranet closed loop**: The entire workflow runs inside the department intranet and talks to in-house or enterprise-controlled models; requirements documents, expert opinions and analysis results **never leave the network**.
- **Sensitive-item isolation (packaging)**: The packaging script (`package.sh`) strictly excludes from the distribution package:
  - `.env` (contains secrets);
  - `runtime/` business data;
  - real branding configuration (only the `ui-branding.example.yaml` template is shipped);
  - real brand names / internal domain names.
- **Encrypted secret storage**: Model API keys are **stored encrypted**, never in plaintext; `JWT_SECRET` is mandatorily validated at startup via `assert_jwt_secret_safe`.

### 6. Upload Security

- **Path traversal protection**: Chat attachments resolve paths via a safe `file_id`, **blocking `..` traversal and absolute-path escapes**.
- **Branding-asset path validation**: `serve_branding_asset` verifies the requested path must resolve inside `runtime/assets/branding/`, rejecting `..` traversal and absolute paths.
- **Extension / size limits**:
  - Chat attachments: `.txt` / `.pdf` / `.docx` / `.md` / `.csv` / `.json`, **≤ 20 MB**;
  - Review documents: `.docx`, **≤ 50 MB**.
- **Foreign-key constraints**: SQLite runs with `foreign_keys=ON`, relying on foreign keys to guarantee referential integrity.

### 7. Runtime Security

- **Graceful shutdown**: During application lifecycle (`lifespan`) shutdown, the system **first cancels review background tasks and the Embedding Worker**, then releases the SQLAlchemy engine, preventing dirty data and connection leaks.
- **No-cache middleware**: `NoCacheMiddleware` sets no-cache headers on sensitive responses, preventing sensitive data from being cached by browsers or intermediary proxies.

---

### 相关文档 / Related Documents

- [admin-guide.md](./admin-guide.md) — 管理员操作:工具配置、审批治理、MCP 管理 / Admin operations: tool configuration, approval governance, MCP management.
- [configuration.md](./configuration.md) — 配置项:`JWT_SECRET`、`allow_public_registration` 等 / Configuration: `JWT_SECRET`, `allow_public_registration`, etc.
- [deployment-hardening.md](./deployment-hardening.md) — 部署加固:Nginx / systemd / 文件权限等 / Deployment hardening: Nginx / systemd / file permissions.
