# API 参考 / API Reference

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

---

本文件为「AI 需求评审工作流平台」的 API 参考，面向集成方与二次开发者。所有业务接口均以 `/api` 为前缀,后端基于 FastAPI。

> 版本号对应 `src/main.py` 中的 `APP_VERSION`（当前为 `0.3.10`）。以下端点均来自源码 `src/main.py` 与 `src/app/routers/`,如发现与代码不一致,以代码为准。

---

<a id="中文"></a>

## 中文

### 概述

平台为部门内网部署的需求评审工作流平台。请求与响应体统一使用 JSON,所有接口默认返回 UTF-8 编码。

详细的请求/响应字段定义请参见 `src/app/schemas/` 与 `src/app/models/` 下对应的 Pydantic schema 与 ORM 模型。本参考不逐字段展开,重点描述每个端点的用途与鉴权要求。

### 认证机制

平台采用两套并行的鉴权机制,请按端点类型正确选择。

#### 1. 普通请求 — Bearer JWT

绝大多数接口使用标准 HTTP Header:

```
Authorization: Bearer <JWT token>
```

- 通过 `POST /api/auth/login` 获取 token。
- token 有效期 **480 分钟(8 小时)**,签发算法 **HS256**,密码使用 **bcrypt** 哈希校验。
- 相关配置见 `src/config.yaml` 的 `auth` 段(`access_token_expire_minutes`、`algorithm`、`secret_key`)。
- token 缺失或过期返回 `401 Unauthorized`。

#### 2. SSE 流式端点 — 短票据(ticket)

SSE(Server-Sent Events)流式端点(如通知流、审查进度流)的浏览器 `EventSource` 客户端**无法自定义 Header**,因此不能使用 Bearer。平台改为使用一次性短票据:

1. 先 `POST /api/auth/sse-ticket`(需 Bearer 鉴权)换取一次性 ticket。
2. 发起 SSE 连接时,以 query 参数携带:`GET <endpoint>?ticket=<ticket>`。

票据特性:

- TTL **60 秒**(`auth.sse_ticket_ttl_seconds`),进程内内存存储,**一次性消费**(consume 后即失效)。
- **不再通过 query 传递 JWT token**;只用 ticket 换取用户身份。

> 注:Agent 流式端点 `POST /api/agent/runs/{run_id}/stream` 与聊天 `POST /api/chat` 虽然返回 `text/event-stream`,但它们是 **POST** 请求,可携带 Header,因此仍使用普通 Bearer,不需要 ticket。**只有 GET 类型的 SSE 端点**需要短票据。

#### 鉴权标记说明

下文表格中「鉴权」列含义:

| 标记 | 含义 |
| --- | --- |
| 公开 | 无需鉴权(登录、注册等);注册受 `allow_public_registration` 开关控制 |
| 用户 | 普通登录用户,使用 `Authorization: Bearer <token>` |
| admin | 管理员角色(`user.role == "admin"`) |
| SSE短票据 | GET 类型的 SSE 端点,使用 `?ticket=<ticket>` |

### 健康检查与品牌配置(无前缀特殊端点)

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/api/health` | 健康检查,返回 `{"status":"ok","version":"0.3.10"}` | 公开 |
| GET | `/api/app/branding` | 品牌配置(登录页 logo、顶栏 logo、favicon 等) | 公开 |
| GET | `/assets/branding/{path}` | 静态品牌资产文件(防目录穿越) | 公开 |
| POST | `/api/log` | 前端日志上报(写入 `runtime/logs/frontend.jsonl` 并记审计) | 用户(可选) |

### 认证 `/api/auth`

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/login` | 登录,返回 JWT token | 公开 |
| POST | `/register` | 注册(受 `allow_public_registration` 开关控制;注册后自动加入默认 workspace) | 公开 |
| POST | `/sse-ticket` | 获取一次性 SSE 短票据(TTL 60s) | 用户 |
| GET | `/me` | 获取当前用户信息 | 用户 |
| PUT | `/password` | 修改当前用户密码 | 用户 |

### 对话 `/api/chat`

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/` | 发送对话消息(流式 SSE 输出,POST 故用 Bearer) | 用户 |
| GET | `/conversations/{conv_id}/context` | 获取对话上下文项列表 | 用户 |
| POST | `/conversations/{conv_id}/context` | 添加上下文项 | 用户 |
| PUT | `/conversations/{conv_id}/context/{item_id}` | 更新上下文项 | 用户 |
| DELETE | `/conversations/{conv_id}/context/{item_id}` | 删除上下文项 | 用户 |
| GET | `/models` | 获取可用模型列表 | 用户 |
| GET | `/prompts` | 获取可用 Prompt 模板列表 | 用户 |

### 历史记录 `/api/history`

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/conversations` | 会话列表(分页) | 用户 |
| GET | `/conversations/{conv_id}` | 会话详情 | 用户 |
| DELETE | `/conversations/{conv_id}` | 删除会话 | 用户 |
| GET | `/search` | 搜索会话 | 用户 |

### 上传 `/api/upload`

聊天附件上传与 URL 内容抓取。

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/file` | 上传文件并提取文本(`multipart/form-data`) | 用户 |
| POST | `/url` | 提交 URL 进行内容抓取(禁止访问内网地址) | 用户 |

### 需求评审 `/api/review` — 项目与文档

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/projects` | 评审项目列表(按用户所在 workspace 过滤可见性) | 用户 |
| POST | `/projects` | 创建评审项目 | 用户 |
| GET | `/projects/{project_id}` | 项目详情(含文档列表) | 用户 |
| DELETE | `/projects/{project_id}` | 删除项目(运行中任务需先结束) | 用户 |
| POST | `/projects/{project_id}/documents` | 上传评审文档(`.docx`) | 用户 |
| POST | `/projects/{project_id}/historical-documents` | 上传历史文档(draft 模式用作背景资料) | 用户 |
| GET | `/projects/{project_id}/documents` | 文档列表 | 用户 |
| DELETE | `/projects/{project_id}/documents/{doc_id}` | 删除文档 | 用户 |
| GET | `/projects/{project_id}/context` | 获取项目评审上下文(规格、必选章节等) | 用户 |
| PUT | `/projects/{project_id}/context` | 更新项目评审上下文(生成新版本) | 用户 |
| POST | `/project/{project_id}/sources` | 关联知识库来源(支持快照版本) | 用户 |
| GET | `/project/{project_id}/sources` | 项目已关联的知识来源 | 用户 |

### 需求评审 `/api/review` — 评审任务

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/projects/{project_id}/reviews` | 评审任务列表 | 用户 |
| POST | `/projects/{project_id}/reviews` | 发起评审(传 `mode`: `quick`/`review`/`pm`/`insight`/`full`/`draft`,`model_id`) | 用户 |
| GET | `/projects/{project_id}/reviews/{review_id}` | 评审任务进度流(SSE,**GET 端点**) | SSE短票据 |
| GET | `/projects/{project_id}/reviews/{review_id}/status` | 评审任务状态(轮询用) | 用户 |
| POST | `/projects/{project_id}/reviews/{review_id}/cancel` | 取消运行中的评审任务 | 用户 |
| GET | `/projects/{project_id}/reviews/{review_id}/analyses` | 逐篇文档分析结果 | 用户 |
| GET | `/projects/{project_id}/reviews/{review_id}/system-review` | 体系评审结果 | 用户 |
| GET | `/projects/{project_id}/reviews/{review_id}/report` | 评审报告(支持 `format=json\|markdown`) | 用户 |

### 需求评审 `/api/review` — Prompt 模板

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/prompts` | 评审 Prompt 模板列表 | 用户 |
| POST | `/prompts` | 创建 Prompt 模板 | admin |
| PUT | `/prompts/{prompt_id}` | 更新 Prompt 模板 | admin |

### 协作评审 `/api/review`

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/requests` | 创建协作评审请求(必填审批人) | 用户 |
| GET | `/requests` | 请求列表 | 用户 |
| GET | `/requests/{request_id}` | 请求详情 | 用户 |
| GET | `/requests/{request_id}/rounds` | 轮次列表 | 用户 |
| POST | `/rounds/{round_id}/decide` | 审批决定(通过/驳回) | 用户 |
| POST | `/requests/{request_id}/resubmit` | 重新提交(开启新轮次) | 用户 |
| GET | `/requests/{request_id}/participants` | 参与人列表 | 用户 |
| POST | `/requests/{request_id}/participants` | 添加参与人 | 用户 |

### 产物与快照 `/api/review`

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/artifacts` | 创建产物 | 用户 |
| GET | `/artifacts` | 产物列表 | 用户 |
| GET | `/artifacts/{artifact_id}` | 产物详情 | 用户 |
| PUT | `/artifacts/{artifact_id}/content` | 更新产物内容 | 用户 |
| POST | `/artifacts/{artifact_id}/confirm` | 确认(冻结)产物 | 用户 |
| POST | `/artifacts/{artifact_id}/unconfirm` | 解除确认 | 用户 |
| POST | `/snapshots` | 创建快照 | 用户 |
| GET | `/snapshots` | 快照列表 | 用户 |
| GET | `/snapshots/{snapshot_id}` | 快照详情 | 用户 |

### 团队空间 `/api`

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/workspace` | 工作空间列表 | 用户 |
| GET | `/workspace/default` | 默认工作空间 | 用户 |
| PUT | `/workspace/default` | 设置默认工作空间 | 用户 |
| GET | `/workspace/default/members` | 默认空间成员 | 用户 |
| PUT | `/workspace/default/members/{user_id}` | 更新成员角色 | 用户 |
| GET | `/workspace/{workspace_id}/members` | 空间成员列表 | 用户 |
| GET | `/workspace/{workspace_id}/sources` | 知识来源列表 | 用户 |
| POST | `/workspace/{workspace_id}/sources` | 添加知识来源 | 用户 |
| GET | `/workspace/{workspace_id}/sources/{source_id}` | 来源详情 | 用户 |
| DELETE | `/workspace/{workspace_id}/sources/{source_id}` | 删除来源 | 用户 |
| PUT | `/workspace/{workspace_id}/sources/{source_id}/tags` | 更新来源标签 | 用户 |
| GET | `/workspace/{workspace_id}/sources/{source_id}/download` | 下载来源文件 | 用户 |
| POST | `/workspace/{workspace_id}/retrieve` | 知识检索(向量化召回) | 用户 |
| POST | `/workspace/{workspace_id}/sources/{source_id}/ingest` | 触发向量化入库 | 用户 |
| GET | `/personal/sources` | 个人知识来源列表 | 用户 |
| POST | `/personal/sources` | 添加个人来源 | 用户 |
| GET | `/personal/sources/{source_id}` | 个人来源详情 | 用户 |
| DELETE | `/personal/sources/{source_id}` | 删除个人来源 | 用户 |
| GET | `/personal/sources/{source_id}/download` | 下载个人来源文件 | 用户 |
| POST | `/personal/retrieve` | 个人知识检索 | 用户 |

### Agent `/api/agent`

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/profile` | Agent 身份配置 | 用户 |
| PUT | `/profile` | 更新 Agent 配置 | 用户 |
| GET | `/profile/authorizations` | 授权范围列表 | 用户 |
| POST | `/profile/authorizations` | 添加授权 | 用户 |
| DELETE | `/profile/authorizations/{auth_id}` | 删除授权 | 用户 |
| GET | `/tools` | 可用工具列表 | 用户 |
| POST | `/runs` | 创建 Agent 运行 | 用户 |
| GET | `/runs` | 运行历史 | 用户 |
| GET | `/runs/{run_id}` | 运行详情 | 用户 |
| POST | `/runs/{run_id}/stream` | Agent 流式对话(SSE,**POST 故用 Bearer**) | 用户 |
| POST | `/runs/{run_id}/execute` | 执行工具调用 | 用户 |
| POST | `/runs/{run_id}/rag` | RAG 检索 | 用户 |
| GET | `/approvals` | 待审批的工具调用(仅当前用户作为审批人) | 用户 |
| POST | `/approvals/{request_id}/decide` | 审批决定 | 用户 |
| GET | `/mcp/servers` | MCP 服务器列表 | 用户 |
| POST | `/mcp/servers` | 添加 MCP 服务器 | 用户 |
| GET | `/mcp/servers/{server_id}/policies` | MCP 服务器策略 | 用户 |
| POST | `/mcp/servers/{server_id}/policies` | 设置 MCP 服务器策略 | 用户 |

### Pi Agent `/api/pi-agent`

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/config` | Pi Agent 配置 | 用户 |
| PUT | `/config` | 更新配置 | 用户 |
| PUT | `/config/llm-api-key` | 设置 LLM API Key | 用户 |
| PUT | `/config/search-api-key` | 设置搜索 API Key | 用户 |
| PUT | `/config/vision-api-key` | 设置视觉 API Key | 用户 |
| POST | `/config/test-connection` | 测试连接 | 用户 |
| POST | `/config/speed-test` | 测速 | 用户 |

### 通知与评论 `/api/notifications`

> 列表接口 `GET /api/notifications`(路由为空字符串)。评论子资源挂在同一前缀下。

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/` | 通知列表(分页/按状态过滤) | 用户 |
| GET | `/stream` | 通知 SSE 流(**GET 端点**) | SSE短票据 |
| GET | `/unread-count` | 未读通知数 | 用户 |
| PUT | `/{notification_id}/read` | 标记已读 | 用户 |
| PUT | `/{notification_id}/archive` | 归档通知 | 用户 |
| POST | `/batch-read` | 批量已读 | 用户 |
| GET | `/comments` | 评论列表 | 用户 |
| POST | `/comments` | 发表评论(支持 @mention) | 用户 |
| DELETE | `/comments/{comment_id}` | 删除评论 | 用户 |
| PUT | `/comments/{comment_id}/resolve` | 解决评论 | 用户 |

### 管理后台 `/api/admin`(需 admin 角色)

所有端点均要求管理员角色。

**用户管理**

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/users` | 用户列表 | admin |
| POST | `/users` | 创建用户 | admin |
| PUT | `/users/{user_id}` | 更新用户 | admin |
| DELETE | `/users/{user_id}` | 删除用户 | admin |

**模型管理**

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/models` | 模型列表 | admin |
| POST | `/models` | 添加模型 | admin |
| PUT | `/models/{model_id}` | 更新模型配置 | admin |
| PUT | `/models/{model_id}/api-key` | 设置模型 API Key | admin |
| DELETE | `/models/{model_id}` | 删除模型 | admin |
| PUT | `/models/order` | 调整模型排序 | admin |
| POST | `/models/{model_id}/test-connection` | 测试模型连接 | admin |
| POST | `/models/{model_id}/speed-test` | 模型测速 | admin |

**Prompt 管理**

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/prompts` | Prompt 列表 | admin |
| POST | `/prompts` | 创建 Prompt | admin |
| PUT | `/prompts/{prompt_id}` | 更新 Prompt | admin |
| DELETE | `/prompts/{prompt_id}` | 删除 Prompt | admin |

**Skill 管理**

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/skills` | Skill 列表 | admin |
| PUT | `/skills/{skill_id}` | 更新 Skill 元数据 | admin |
| PUT | `/skills/{skill_id}/toggle` | 启停 Skill | admin |

**统计**

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/stats` | 系统统计 | admin |

### 治理与运营 `/api/governance/*`(需 admin 角色)

所有端点均要求管理员角色(由各端点内联校验 `user.role != "admin"` 抛 403)。

**成本与质量**

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/governance/cost/daily` | 每日成本统计 | admin |
| GET | `/governance/cost/total` | 总成本统计 | admin |
| POST | `/governance/cost/aggregate` | 手动触发成本聚合 | admin |
| GET | `/governance/quality/weekly` | 每周质量统计 | admin |

**Skill 与 Agent 治理**

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/governance/skills` | Skill 治理列表 | admin |
| PUT | `/governance/skills/{skill_db_id}/status` | Skill 启停 | admin |
| GET | `/governance/agents` | Agent 列表 | admin |
| PUT | `/governance/agent/{agent_id}/archive` | 归档 Agent | admin |

**权限与预算**

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/governance/permissions/audit` | 权限审计日志 | admin |
| GET | `/governance/budget/{workspace_id}` | 工作空间预算 | admin |
| PUT | `/governance/budget/{workspace_id}` | 设置工作空间预算 | admin |

> 上述治理端点位于 `/api` 前缀下(由 `governance.router` 注册于 `/api`),完整路径如 `/api/governance/cost/daily`。

### 交互式 API 文档

FastAPI 自动生成交互式文档,可直接在浏览器查看与在线调试:

- **Swagger UI**:`GET /docs`
- **ReDoc**:`GET /redoc`(FastAPI 默认同时挂载)
- OpenAPI Schema:`GET /openapi.json`

建议集成开发期间常驻 `/docs`,可即时查看每个端点的请求/响应字段、状态码与示例。

---

<a id="english"></a>

## English

### Overview

This platform is a requirements-review workflow service deployed on a department intranet. Request and response bodies are JSON, and all responses are UTF-8.

For detailed request/response field definitions, see the Pydantic schemas under `src/app/schemas/` and the ORM models under `src/app/models/`. This reference does not expand every field; it focuses on each endpoint's purpose and authentication requirements.

### Authentication

The platform uses two parallel mechanisms. Pick the correct one based on endpoint type.

#### 1. Normal requests — Bearer JWT

Most endpoints use a standard HTTP header:

```
Authorization: Bearer <JWT token>
```

- Obtain the token via `POST /api/auth/login`.
- Token lifetime is **480 minutes (8 hours)**, signed with **HS256**; passwords are verified with **bcrypt**.
- Configuration lives in the `auth` section of `src/config.yaml` (`access_token_expire_minutes`, `algorithm`, `secret_key`).
- Missing/expired tokens return `401 Unauthorized`.

#### 2. SSE streaming endpoints — short-lived ticket

Browser `EventSource` clients for SSE (Server-Sent Events) streaming endpoints (e.g., notification stream, review-progress stream) **cannot set custom headers**, so Bearer does not work. The platform uses a one-time short-lived ticket instead:

1. Call `POST /api/auth/sse-ticket` (Bearer-authenticated) to obtain a one-time ticket.
2. Open the SSE connection with the ticket as a query parameter: `GET <endpoint>?ticket=<ticket>`.

Ticket properties:

- TTL **60 seconds** (`auth.sse_ticket_ttl_seconds`), in-memory, **single-use** (invalidated on consume).
- **JWT tokens are no longer passed via query**; only the ticket is used to resolve the user identity.

> Note: The Agent streaming endpoint `POST /api/agent/runs/{run_id}/stream` and chat `POST /api/chat` also return `text/event-stream`, but they are **POST** requests that can carry headers, so they still use plain Bearer and **do not** need a ticket. **Only GET-type SSE endpoints** require the short ticket.

#### Auth legend

The "Auth" column in the tables below uses these markers:

| Marker | Meaning |
| --- | --- |
| Public | No auth required (login, register, etc.); registration is gated by `allow_public_registration` |
| User | Any logged-in user, via `Authorization: Bearer <token>` |
| admin | Administrator role (`user.role == "admin"`) |
| SSE ticket | GET-type SSE endpoint, using `?ticket=<ticket>` |

### Health Check & Branding (special endpoints without prefix)

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/api/health` | Health check, returns `{"status":"ok","version":"0.3.10"}` | Public |
| GET | `/api/app/branding` | Branding config (login logo, topbar logo, favicon, etc.) | Public |
| GET | `/assets/branding/{path}` | Static branding assets (path-traversal protected) | Public |
| POST | `/api/log` | Frontend log ingestion (writes `runtime/logs/frontend.jsonl` + audit) | User (optional) |

### Auth `/api/auth`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| POST | `/login` | Log in, returns JWT token | Public |
| POST | `/register` | Register (gated by `allow_public_registration`; auto-joins default workspace) | Public |
| POST | `/sse-ticket` | Obtain a one-time SSE ticket (TTL 60s) | User |
| GET | `/me` | Get current user info | User |
| PUT | `/password` | Change current user password | User |

### Chat `/api/chat`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| POST | `/` | Send a chat message (streaming SSE output; POST so it uses Bearer) | User |
| GET | `/conversations/{conv_id}/context` | Get conversation context items | User |
| POST | `/conversations/{conv_id}/context` | Add a context item | User |
| PUT | `/conversations/{conv_id}/context/{item_id}` | Update a context item | User |
| DELETE | `/conversations/{conv_id}/context/{item_id}` | Delete a context item | User |
| GET | `/models` | List available models | User |
| GET | `/prompts` | List available prompt templates | User |

### History `/api/history`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/conversations` | Conversation list (paginated) | User |
| GET | `/conversations/{conv_id}` | Conversation detail | User |
| DELETE | `/conversations/{conv_id}` | Delete a conversation | User |
| GET | `/search` | Search conversations | User |

### Upload `/api/upload`

Chat attachment upload and URL content fetching.

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| POST | `/file` | Upload a file and extract text (`multipart/form-data`) | User |
| POST | `/url` | Submit a URL for content scraping (intranet addresses blocked) | User |

### Requirements Review `/api/review` — Projects & Documents

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/projects` | List review projects (visibility filtered by user workspaces) | User |
| POST | `/projects` | Create a review project | User |
| GET | `/projects/{project_id}` | Project detail (includes document list) | User |
| DELETE | `/projects/{project_id}` | Delete a project (running tasks must finish first) | User |
| POST | `/projects/{project_id}/documents` | Upload review documents (`.docx`) | User |
| POST | `/projects/{project_id}/historical-documents` | Upload historical documents (used as background in draft mode) | User |
| GET | `/projects/{project_id}/documents` | Document list | User |
| DELETE | `/projects/{project_id}/documents/{doc_id}` | Delete a document | User |
| GET | `/projects/{project_id}/context` | Get project review context (specs, required sections, etc.) | User |
| PUT | `/projects/{project_id}/context` | Update project review context (creates a new version) | User |
| POST | `/project/{project_id}/sources` | Link a knowledge source (supports snapshot version) | User |
| GET | `/project/{project_id}/sources` | Sources linked to the project | User |

### Requirements Review `/api/review` — Review Tasks

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/projects/{project_id}/reviews` | List review tasks | User |
| POST | `/projects/{project_id}/reviews` | Start a review (pass `mode`: `quick`/`review`/`pm`/`insight`/`full`/`draft`, `model_id`) | User |
| GET | `/projects/{project_id}/reviews/{review_id}` | Review task progress stream (SSE, **GET endpoint**) | SSE ticket |
| GET | `/projects/{project_id}/reviews/{review_id}/status` | Review task status (for polling) | User |
| POST | `/projects/{project_id}/reviews/{review_id}/cancel` | Cancel a running review task | User |
| GET | `/projects/{project_id}/reviews/{review_id}/analyses` | Per-document analysis results | User |
| GET | `/projects/{project_id}/reviews/{review_id}/system-review` | System-level review results | User |
| GET | `/projects/{project_id}/reviews/{review_id}/report` | Review report (supports `format=json\|markdown`) | User |

### Requirements Review `/api/review` — Prompt Templates

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/prompts` | List review prompt templates | User |
| POST | `/prompts` | Create a prompt template | admin |
| PUT | `/prompts/{prompt_id}` | Update a prompt template | admin |

### Collaborative Review `/api/review`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| POST | `/requests` | Create a collaborative review request (approver required) | User |
| GET | `/requests` | List requests | User |
| GET | `/requests/{request_id}` | Request detail | User |
| GET | `/requests/{request_id}/rounds` | List rounds | User |
| POST | `/rounds/{round_id}/decide` | Approve / reject decision | User |
| POST | `/requests/{request_id}/resubmit` | Resubmit (opens a new round) | User |
| GET | `/requests/{request_id}/participants` | List participants | User |
| POST | `/requests/{request_id}/participants` | Add a participant | User |

### Artifacts & Snapshots `/api/review`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| POST | `/artifacts` | Create an artifact | User |
| GET | `/artifacts` | List artifacts | User |
| GET | `/artifacts/{artifact_id}` | Artifact detail | User |
| PUT | `/artifacts/{artifact_id}/content` | Update artifact content | User |
| POST | `/artifacts/{artifact_id}/confirm` | Confirm (freeze) an artifact | User |
| POST | `/artifacts/{artifact_id}/unconfirm` | Unconfirm an artifact | User |
| POST | `/snapshots` | Create a snapshot | User |
| GET | `/snapshots` | List snapshots | User |
| GET | `/snapshots/{snapshot_id}` | Snapshot detail | User |

### Team Workspace `/api`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/workspace` | List workspaces | User |
| GET | `/workspace/default` | Get default workspace | User |
| PUT | `/workspace/default` | Set default workspace | User |
| GET | `/workspace/default/members` | Default workspace members | User |
| PUT | `/workspace/default/members/{user_id}` | Update member role | User |
| GET | `/workspace/{workspace_id}/members` | List workspace members | User |
| GET | `/workspace/{workspace_id}/sources` | List knowledge sources | User |
| POST | `/workspace/{workspace_id}/sources` | Add a knowledge source | User |
| GET | `/workspace/{workspace_id}/sources/{source_id}` | Source detail | User |
| DELETE | `/workspace/{workspace_id}/sources/{source_id}` | Delete a source | User |
| PUT | `/workspace/{workspace_id}/sources/{source_id}/tags` | Update source tags | User |
| GET | `/workspace/{workspace_id}/sources/{source_id}/download` | Download a source file | User |
| POST | `/workspace/{workspace_id}/retrieve` | Knowledge retrieval (vectorized recall) | User |
| POST | `/workspace/{workspace_id}/sources/{source_id}/ingest` | Trigger vector ingestion | User |
| GET | `/personal/sources` | List personal knowledge sources | User |
| POST | `/personal/sources` | Add a personal source | User |
| GET | `/personal/sources/{source_id}` | Personal source detail | User |
| DELETE | `/personal/sources/{source_id}` | Delete a personal source | User |
| GET | `/personal/sources/{source_id}/download` | Download a personal source file | User |
| POST | `/personal/retrieve` | Personal knowledge retrieval | User |

### Agent `/api/agent`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/profile` | Agent identity config | User |
| PUT | `/profile` | Update Agent config | User |
| GET | `/profile/authorizations` | List authorization scopes | User |
| POST | `/profile/authorizations` | Add an authorization | User |
| DELETE | `/profile/authorizations/{auth_id}` | Delete an authorization | User |
| GET | `/tools` | List available tools | User |
| POST | `/runs` | Create an Agent run | User |
| GET | `/runs` | Run history | User |
| GET | `/runs/{run_id}` | Run detail | User |
| POST | `/runs/{run_id}/stream` | Agent streaming chat (SSE, **POST so it uses Bearer**) | User |
| POST | `/runs/{run_id}/execute` | Execute a tool call | User |
| POST | `/runs/{run_id}/rag` | RAG retrieval | User |
| GET | `/approvals` | Pending tool calls awaiting approval (only those where the current user is the approver) | User |
| POST | `/approvals/{request_id}/decide` | Approval decision | User |
| GET | `/mcp/servers` | List MCP servers | User |
| POST | `/mcp/servers` | Add an MCP server | User |
| GET | `/mcp/servers/{server_id}/policies` | MCP server policies | User |
| POST | `/mcp/servers/{server_id}/policies` | Set MCP server policies | User |

### Pi Agent `/api/pi-agent`

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/config` | Pi Agent config | User |
| PUT | `/config` | Update config | User |
| PUT | `/config/llm-api-key` | Set LLM API Key | User |
| PUT | `/config/search-api-key` | Set search API Key | User |
| PUT | `/config/vision-api-key` | Set vision API Key | User |
| POST | `/config/test-connection` | Test connection | User |
| POST | `/config/speed-test` | Speed test | User |

### Notifications & Comments `/api/notifications`

> The list endpoint is `GET /api/notifications` (route is the empty string). Comment sub-resources are mounted under the same prefix.

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/` | List notifications (paginated / filterable by status) | User |
| GET | `/stream` | Notification SSE stream (**GET endpoint**) | SSE ticket |
| GET | `/unread-count` | Unread count | User |
| PUT | `/{notification_id}/read` | Mark as read | User |
| PUT | `/{notification_id}/archive` | Archive | User |
| POST | `/batch-read` | Batch mark as read | User |
| GET | `/comments` | List comments | User |
| POST | `/comments` | Post a comment (supports @mention) | User |
| DELETE | `/comments/{comment_id}` | Delete a comment | User |
| PUT | `/comments/{comment_id}/resolve` | Resolve a comment | User |

### Admin `/api/admin` (admin role required)

All endpoints require the administrator role.

**Users**

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/users` | List users | admin |
| POST | `/users` | Create a user | admin |
| PUT | `/users/{user_id}` | Update a user | admin |
| DELETE | `/users/{user_id}` | Delete a user | admin |

**Models**

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/models` | List models | admin |
| POST | `/models` | Add a model | admin |
| PUT | `/models/{model_id}` | Update model config | admin |
| PUT | `/models/{model_id}/api-key` | Set model API Key | admin |
| DELETE | `/models/{model_id}` | Delete a model | admin |
| PUT | `/models/order` | Reorder models | admin |
| POST | `/models/{model_id}/test-connection` | Test model connection | admin |
| POST | `/models/{model_id}/speed-test` | Model speed test | admin |

**Prompts**

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/prompts` | List prompts | admin |
| POST | `/prompts` | Create a prompt | admin |
| PUT | `/prompts/{prompt_id}` | Update a prompt | admin |
| DELETE | `/prompts/{prompt_id}` | Delete a prompt | admin |

**Skills**

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/skills` | List skills | admin |
| PUT | `/skills/{skill_id}` | Update skill metadata | admin |
| PUT | `/skills/{skill_id}/toggle` | Enable/disable a skill | admin |

**Statistics**

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/stats` | System statistics | admin |

### Governance & Operations `/api/governance/*` (admin role required)

All endpoints require the administrator role (enforced inline by raising 403 when `user.role != "admin"`).

**Cost & Quality**

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/governance/cost/daily` | Daily cost statistics | admin |
| GET | `/governance/cost/total` | Total cost statistics | admin |
| POST | `/governance/cost/aggregate` | Manually trigger cost aggregation | admin |
| GET | `/governance/quality/weekly` | Weekly quality statistics | admin |

**Skill & Agent Governance**

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/governance/skills` | List skills for governance | admin |
| PUT | `/governance/skills/{skill_db_id}/status` | Enable/disable a skill | admin |
| GET | `/governance/agents` | List agents | admin |
| PUT | `/governance/agent/{agent_id}/archive` | Archive an agent | admin |

**Permissions & Budget**

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| GET | `/governance/permissions/audit` | Permission audit log | admin |
| GET | `/governance/budget/{workspace_id}` | Workspace budget | admin |
| PUT | `/governance/budget/{workspace_id}` | Set workspace budget | admin |

> These governance endpoints live under the `/api` prefix (`governance.router` is mounted at `/api`); the full path is e.g. `/api/governance/cost/daily`.

### Interactive API Documentation

FastAPI auto-generates interactive docs you can view and try in the browser:

- **Swagger UI**: `GET /docs`
- **ReDoc**: `GET /redoc` (mounted by default in FastAPI)
- OpenAPI schema: `GET /openapi.json`

Keeping `/docs` open during integration is recommended — it shows exact request/response fields, status codes, and examples for every endpoint.
