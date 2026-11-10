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

- **登录签发**:用户通过 `POST /api/auth/login` 验证账号密码后获取 JWT。密码以 **bcrypt 哈希**存储,明文不可逆;密码 UTF-8 编码后不得超过 **72 字节**(bcrypt 算法上限),超限在注册/改密/管理员创建与重置入口统一返回 422。
- **算法与有效期**:JWT 签名算法 **HS256**,Token 有效期 **480 分钟(8 小时)**,前端存储于 `localStorage`。
- **会话撤销(auth_version)**:JWT 携带 `av` 会话版本号,与 `users.auth_version` 逐请求比对;用户改密或管理员重置密码即通过原子 SQL 更新递增版本号(杜绝并发丢失更新),该用户全部旧 JWT 立即失效,需重新登录。升级前签发的无 `av` 旧 Token 一律视为失效。SSE 一次性票据签发时绑定 `auth_version`,消费时与数据库比对(改密前签发的票据立即失效);通知流与审查进度流的生成器循环内周期校验会话版本,改密/重置后旧长连接收到 `session_revoked` 事件并停止推送。
- **JWT_SECRET 安全校验(启动期硬阻断)**:Service 层 `assert_jwt_secret_safe` 拒绝已知不安全占位值和不足 32 字符的密钥,直接抛 `RuntimeError` 阻止进程启动。空值不会拒绝启动：`./start.sh` 会先生成随机密钥并写入项目根目录 `.env`；不走官方脚本时 `config.py` 会生成进程内临时密钥（不落盘，重启后 token 失效）。占位值示例:`change-me-in-production`、`change-this-to-a-random-secret-string`、`secret`、`jwt-secret`、`your-secret-key`。配置方法见 [configuration.md](./configuration.md)。
- **SSE 短票据(避免 Token 泄露)**:通知流与审查进度流通过 EventSource 建连,使用**一次性短票据**:
  - `POST /api/auth/sse-ticket` 获取票据,**TTL 60 秒**,单次消费即失效;
  - 以 `?ticket=` 查询参数连接 SSE。
  - **不再通过 query 传递 JWT Token**,避免 Token 被写入访问日志、Referer 或浏览器历史。
  - Agent 流使用 POST fetch,通过 `Authorization: Bearer` 请求头认证。
- **注册策略**:`allow_public_registration` 控制是否开放公开注册;注册**不再自动提权为管理员**;首个 `admin` 通过离线方式初始化,杜绝"注册即管理员"风险。

### 三、访问控制(BOLA 防护重点)

- **对象级权限拆分**:`ReviewRequest` / `Round` / `Participant`、`Artifact` 等对象在 `object_access` 层面做了细粒度**读 vs 写**拆分,而非仅做资源级粗粒度校验。
- **BOLA( Broken Object-Level Authorization)防护**:通过读/写权限拆分,阻止跨用户越权访问。例如:
  - `Observer` 只读,无法写入或确认;
  - 发起人 / `Reviewer` / `Approver` / 项目管理员可写可确认;
  - 只读角色(如 `viewer`、`Observer`)无法篡改对象,**阻止只读角色越权写入**。
- **工作空间成员校验**:相关操作使用 `require_action` 与活跃成员校验。聊天使用知识库时要求目标空间 `read` 权限,审查启动要求项目 `write` 权限与活跃成员资格,**拒绝伪造 `workspace_id` 绕过配额**(`WorkspaceBudget` + `BudgetGuard` 硬限)。
- **只读角色防篡改**:`viewer` / `Observer` 等只读角色不可写、不可确认。
- **协作审查审批链**:`approver_ids` 中的每个审批人必须是项目所在 workspace 的 **active `write` 成员**,且不得是发起人本人。轮次决策始终要求 active `write` 成员资格且禁止发起人自批。已有参与者行时,该行必须是 active `Approver`。兼容旧请求缺少该用户参与者行的情况,此时仅轮次指定的 `approver_id` 可决策。添加参与者同样要求目标是 active 成员。
- **评论写权限**:发表、删除、解决评论都要求对目标对象具备写权限;删除评论还要求是评论作者。`Observer` / `viewer` 与已停用成员不能通过评论接口绕过对象权限。
- **项目资料引用边界**:项目只能引用团队公开资料,`private` 或个人 `owner_type=user` 的资料在新增引用时直接拒绝;历史脏引用在审查上下文加载时同样过滤。

### 四、Agent 安全(重点)

Agent 在生产中可调用工具与模型,是最高风险面。平台采用多层防护:

- **deny-by-default 工具白名单**:工具列表默认拒绝,**空列表 → 仅允许 `rag_search`**。授权范围在 Extension 端点与 RAG 端点两处分别校验,避免单点遗漏。
- **高风险工具**:`bash` / `write` / `edit` / `read`:
  - 普通用户更新工具白名单时会剔除高风险工具,Pi 启动时也会从常规白名单剔除这些工具,执行需一次性审批放行。
  - **申请人包括管理员均不得批准自己的请求**。Pi 拦截工具时自动选择另一名 active 管理员作为审批人,找不到独立审批人时返回 `approval_unavailable`,并跳过创建待审批记录。
- **工具调用审批流**:高风险工具调用会产生待审批请求:
  - `GET /api/agent/approvals` 仅返回**当前用户作为审批人**的请求(隔离他人审批队列);
  - `POST /api/agent/approvals/{request_id}/decide` 做出批准 / 拒绝决定,通过后才放行工具执行。
- **Pi Agent 工作目录**:每次运行使用 `runtime/agent_sandboxes/<run_id>/` 作为 cwd。文件访问仍受宿主进程权限与工具审批控制,cwd 本身没有提供操作系统级文件系统隔离。
- **Pi 子进程环境**:只继承运行所需环境白名单,模型 Provider Key 与 `AGENT_*` 运行期参数由桥接层显式注入。`JWT_SECRET`、数据库配置等服务端环境变量不会随父进程环境整体传入。
- **MCP 鉴权分层**:
  - 全局 MCP 配置需**管理员**权限;
  - 工作空间级 MCP 需 **manage** 权限,普通成员不可越权改写全局/空间级 Agent 配置。
  - 管理接口保存工具策略。`MCPAdapterManager.check_policy` 在缺少显式策略时返回 `allowed=false`、`requires_approval=true`、`risk_level=high`。当前工具执行入口尚未调用此 helper。

> 关于管理员侧的工具配置与审批治理操作,参见 [admin-guide.md](./admin-guide.md)。

### 五、数据安全

- **数据与代码分离**:所有数据库、上传文件、转换中间文件、日志、评审产物统一落在 `runtime/` 目录下,默认被 `.gitignore` 忽略。源码不混入业务数据,**降低跨环境(开发 / 测试 / 生产)泄露风险**。
- **模型数据流向**:模型请求发送到配置的 API 地址。配置内网模型端点并限制部署环境出网时,可形成内网闭环。示例配置包含公网模型端点,实际数据流向取决于部署配置。
- **敏感项隔离(打包分发)**:打包脚本(`package.sh`)产出的分发包严格剔除:
  - `.env`(含密钥);
  - `runtime/` 业务数据;
  - 真实品牌配置(仅附带 `ui-branding.example.yaml` 模板);
  - 真实品牌名 / 内部域名。
- **密钥加密存储**:模型 API Key **加密存储**,不以明文落库;`JWT_SECRET` 在启动期经 `assert_jwt_secret_safe` 强制校验。
- **知识资料可见性**:私有或个人资料仅 owner 可触发重新入库。团队资料列表对存量私有或个人记录先按当前用户归属过滤再分页,避免泄露标题等元数据。FTS 检索仅返回 active 的团队资料或当前用户自己的私有资料,无用户上下文时仅返回 active 团队资料。向量结果还须通过 SQLite 的 `embedding_status=done` 与资料 active 状态校验。
- **向量补偿归属**:每批 embedding 写入携带独立 `write_token`,补偿清理只删除本批写入,并保留当前已完成身份及其他 worker 的向量。旧索引首次写入时自动补齐 token 列,兼容方式见 [configuration.md](./configuration.md)。

### 六、上传安全

- **路径穿越(Path Traversal)防护**:聊天附件以 `file_id` 安全解析文件路径,**阻止 `..` 穿越与绝对路径逃逸**。
- **聊天附件归属**:新上传附件 ID 带 `u<owner_id>_` 前缀;聊天请求的 `file_ids` 和新建上下文项都会校验附件属于当前用户,跨账号完整 ID 不再能读取他人附件。历史无前缀附件仅能通过已归属会话的持久化上下文读取。
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

- **Login issuance**: Users call `POST /api/auth/login`; upon successful credential verification a JWT is returned. Passwords are stored as **bcrypt hashes** (non-reversible); passwords must not exceed **72 bytes** when UTF-8 encoded (the bcrypt algorithm limit) — oversized passwords are rejected with HTTP 422 at the register / change-password / admin create & reset entry points.
- **Algorithm & lifetime**: JWT is signed with **HS256**; the token is valid for **480 minutes (8 hours)** and stored in `localStorage` on the client.
- **Session revocation (auth_version)**: JWTs carry an `av` session-version claim compared per-request against `users.auth_version`; a password change or admin password reset increments the version via an atomic SQL update (no lost updates under concurrency), immediately invalidating all of that user's old JWTs and forcing re-login. Pre-upgrade tokens without an `av` claim are treated as invalid. SSE one-time tickets are bound to `auth_version` at issuance and validated against the database when consumed (tickets issued before a password change are rejected); the notification and review-progress stream generators re-check the session version in their loops, so established streams receive a `session_revoked` event and stop pushing after a password change or reset.
- **JWT_SECRET safety check (hard-fail at startup)**: The service-layer `assert_jwt_secret_safe` rejects known insecure placeholders and secrets shorter than 32 characters (`MIN_JWT_SECRET_LENGTH = 32`) by raising `RuntimeError`. An empty value does not refuse startup: `./start.sh` generates a random secret and writes it to the project-root `.env`; if you skip the official script, `config.py` generates an in-process ephemeral secret (not persisted; tokens die after restart). Placeholder examples: `change-me-in-production`, `change-this-to-a-random-secret-string`, `secret`, `jwt-secret`, `your-secret-key`. For configuration see [configuration.md](./configuration.md).
- **SSE short-lived ticket (avoids token leakage)**: Notification and review-progress streams connect through EventSource with **single-use short-lived tickets**:
  - Obtain a ticket via `POST /api/auth/sse-ticket`, **TTL 60 seconds**, consumed once and then invalidated;
  - Connect to SSE with a `?ticket=` query parameter.
  - **JWT tokens are no longer passed via the query string**, preventing them from leaking into access logs, `Referer` headers or browser history.
  - The Agent stream uses POST fetch with an `Authorization: Bearer` header.
- **Registration policy**: `allow_public_registration` controls whether public sign-up is open; registration **no longer auto-promotes to admin**; the first `admin` is bootstrapped offline, eliminating the "register-and-become-admin" risk.

### 3. Access Control (BOLA Protection Focus)

- **Object-level permission split**: Objects such as `ReviewRequest` / `Round` / `Participant` and `Artifact` have fine-grained **read-vs-write** splitting at the `object_access` layer, rather than coarse resource-level checks only.
- **BOLA (Broken Object-Level Authorization) protection**: The read/write split prevents cross-user unauthorized access. For example:
  - `Observer` is read-only and cannot write or confirm;
  - The initiator / `Reviewer` / `Approver` / project admin can write and confirm;
  - Read-only roles (e.g. `viewer`, `Observer`) cannot tamper with objects — **read-only roles are blocked from writing**.
- **Workspace membership verification**: Relevant operations use `require_action` and active-membership checks. Chat knowledge access requires `read` permission on the target workspace. Review start requires project `write` permission and active membership, **rejecting forged `workspace_id` attempts to bypass quotas** (`WorkspaceBudget` + `BudgetGuard` hard limits).
- **Read-only tamper protection**: Read-only roles such as `viewer` / `Observer` cannot write or confirm.
- **Collaborative review approval chain**: every ID in `approver_ids` must be an **active `write` member** of the project workspace and must not be the initiator. Every round decision requires active `write` membership and prohibits initiator self-approval. When the user has a participant row, it must be an active `Approver` row. For legacy requests without that user's participant row, only the round's designated `approver_id` may decide. Adding a participant likewise requires an active target member.
- **Comment write permission**: creating, deleting and resolving comments all require write access to the target object; deleting also requires being the comment author. `Observer` / `viewer` and inactive members cannot bypass object permissions through comment endpoints.
- **Project knowledge-reference boundary**: projects may reference only team-visible sources; `private` or personal (`owner_type=user`) sources are rejected when adding a reference, and legacy dirty references are filtered when review context is loaded.

### 4. Agent Security (Focus Area)

Agents can invoke tools and models in production, which is the highest-risk surface. The platform applies layered defense:

- **Deny-by-default tool allowlist**: The tool list is denied by default; an **empty list allows only `rag_search`**. The authorization scope is enforced in two places — the Extension endpoint and the RAG endpoint — to avoid a single point of failure.
- **High-risk tools** — `bash` / `write` / `edit` / `read`:
  - High-risk tools are stripped when regular users update their allowlist and from the regular allowlist when Pi starts. Execution requires a one-shot approval.
  - **Requesters, including admins, cannot approve their own requests**. On a blocked tool call, Pi selects another active admin as approver. If none exists, it emits `approval_unavailable` and skips creating a pending approval record.
- **Tool-call approval flow**: A high-risk tool call produces a pending approval request:
  - `GET /api/agent/approvals` returns only requests where **the current user is the approver** (isolating other users' approval queues);
  - `POST /api/agent/approvals/{request_id}/decide` makes an approve / reject decision; only after approval is the tool actually executed.
- **Pi Agent working directory**: Each run uses `runtime/agent_sandboxes/<run_id>/` as its cwd. File access remains governed by host-process permissions and tool approvals. The cwd provides no operating-system filesystem isolation.
- **Pi subprocess environment**: Only an allowlist of required environment variables is inherited. The bridge explicitly supplies the model Provider Key and `AGENT_*` runtime parameters. Server variables such as `JWT_SECRET` and database configuration are excluded from wholesale parent-environment inheritance.
- **Layered MCP authentication**:
  - Global MCP configuration requires **admin** privileges;
  - Workspace-level MCP requires **manage** privileges, so ordinary members cannot overwrite global or workspace Agent configuration.
  - Management endpoints persist tool policies. Without an explicit policy, `MCPAdapterManager.check_policy` returns `allowed=false`, `requires_approval=true` and `risk_level=high`. Current tool-execution entry points do not call this helper.

> For admin-side tool configuration and approval governance operations, see [admin-guide.md](./admin-guide.md).

### 5. Data Security

- **Data / code separation**: All databases, uploaded files, conversion intermediates, logs and review artifacts live under the `runtime/` directory, which is `.gitignore`d by default. Source code never mixes with business data, **reducing cross-environment (dev / test / prod) leakage risk**.
- **Model data flow**: Model requests go to the configured API endpoints. An intranet-only deployment requires internal model endpoints and deployment-level outbound network restrictions. The example configuration includes public model endpoints, so actual data flow depends on deployment configuration.
- **Sensitive-item isolation (packaging)**: The packaging script (`package.sh`) strictly excludes from the distribution package:
  - `.env` (contains secrets);
  - `runtime/` business data;
  - real branding configuration (only the `ui-branding.example.yaml` template is shipped);
  - real brand names / internal domain names.
- **Encrypted secret storage**: Model API keys are **stored encrypted**, never in plaintext; `JWT_SECRET` is mandatorily validated at startup via `assert_jwt_secret_safe`.
- **Knowledge-source visibility**: Only the owner can trigger re-ingestion of private or personal sources. Team-source lists filter legacy private or personal records by the current owner before pagination, preventing title and other metadata disclosure. FTS returns active team sources or the current user's own private sources. Without a user context it returns only active team sources. Vector results must also pass SQLite checks for `embedding_status=done` and an active source.
- **Vector compensation ownership**: Each embedding batch carries a unique `write_token`. Compensation deletes only that batch's writes while retaining currently completed identities and vectors from other workers. The token column is added automatically on the first write to an old index. Compatibility details are in [configuration.md](./configuration.md).

### 6. Upload Security

- **Path traversal protection**: Chat attachments resolve paths via a safe `file_id`, **blocking `..` traversal and absolute-path escapes**.
- **Chat attachment ownership**: newly uploaded attachment IDs carry a `u<owner_id>_` prefix; chat request `file_ids` and newly created context items validate that the attachment belongs to the current user, so a complete cross-account ID can no longer read another user's attachment. Legacy unprefixed attachments are readable only through persisted context of the owning conversation.
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
