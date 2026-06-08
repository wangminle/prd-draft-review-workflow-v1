# 需求业务工作流 Cowork 版 — WBS 任务分解

> 基于 [需求业务工作流的 cowork 版工具设计规划](../2-discussion/需求业务工作流的cowork版工具设计规划-20260604.md) 的 WBS 拆解。
> 目标：将规划文档中 P0~P6 六个阶段、11 条近期行动、3 类 POC、领域对象和业务流程拆成可量化、可验收、可排期的任务单元。
> 估算口径：按 1 名后端 + 1 名前端/全栈 + 0.3 名产品/测试/评审支持；若只有 1 名全栈开发，周期乘 1.6~2.0。

---

## 范围修正（2026-06-04）

本 WBS 按**当前系统只部署给一个团队使用**来规划，不按多租户/多团队平台规划。由此产生四个约束：

1. **只有一个默认团队空间**：系统初始化时创建 1 个默认 `Workspace`，后续不在 MVP 阶段开放多团队创建、团队切换或跨团队权限。
2. **注册用户默认是本团队成员**：所有通过当前系统注册的用户自动加入默认团队空间，默认角色为 `member`；系统管理员或首个初始化管理员可升级用户为 `admin/owner`。
3. **新增“团队空间”并列页面**：前端新增一级页面“团队空间”，与“智能对话”“审查模式”“管理后台”并列，沿用当前导航、布局、按钮、卡片、表格、空状态和权限提示样式。
4. **权限先粗后细**：MVP 只做单团队内 `owner/admin/member/viewer` 粗粒度权限；个人空间、跨团队权限、细粒度 ABAC、外部系统权限同步均后置。

---

## 实施总览

| 阶段 | 目标 | 周期估算 | 子任务数 | 优先级 | 前置条件 |
| --- | --- | ---: | ---: | --- | --- |
| P0 | 团队资料库 MVP + 团队空间页面壳 | 2-3 周 | 24 | 最高 | 无 |
| P1 | 单团队权限底座与成员管理 | 2-3 周 | 10 | 高 | P0 完成 |
| P2 | 知识库检索与对话 RAG | 4-6 周 | 20 | 高 | P1 完成 + 检索 POC 通过 |
| P3 | Agent 对话与工具注册 | 4-6 周 | 18 | 中 | P2 完成 + Agent POC 通过 |
| P4 | 审查平台协作化 | 5-7 周 | 21 | 中 | P3 完成 |
| P5 | 个人账号 Agent 与消息中心 | 4-6 周 | 11 | 中 | P3 完成 |
| P6 | 治理与运营 | 3-5 周 | 11 | 低 | P4/P5 完成 |

前置闸门：
- P3 启动前必须通过安全评审和 Agent POC。
- P4-P6 需团队真实使用反馈后再定优先级。

## 快速验证标记（2026-06-08 更新）

> 标记规则：仅当仓库内同时存在直接代码实现与自动化测试/前端契约测试证据时，才标记为”已验证完成”；部分完成指代码中有相关实现但不完全满足验收标准。

- 已验证完成：**Phase 0 全部 24 项**，即 `P0.A.1~P0.E.4`。
- 已验证完成：**P1 全部 10 项**，即 `P1.A.1~P1.C.2`（791 全量回归通过）。
- 已验证完成：**POC-A 全部 6 项 + POC-B 深度验证 + POC-C 真实嵌入验证**（最终选型结论：LanceDB 单引擎首选，FTS5 降级回退，dist[0]+gap 拒答，OpenAI text-embedding-3-small；详见 `docs/3-design/检索引擎选型最终结论.md`）。
- 已验证完成：**Phase 2 全部 20 项**，即 `P2.A.1~P2.E.3 + P2.D.1~D.3 + P2.C.1~C.4`（887 全量回归通过，58+ P2 专项测试通过，34 项 P2.D.1 评估测试通过，P2.D.1 验收通过：top-5 命中率 95.8% ≥ 92%，no_answer 拒答率 87.5% ≥ 50%，无越权召回；BUG-052 检索可用性缺口已修复，BUG-053 SSE 分片解析已修复）
- 未开始：**Phase 3~Phase 6**
- 快速验证依据：
  - 数据模型/仓储与迁移：`tests/test_workspace.py`
  - 团队空间 API/权限/项目引用：`tests/test_workspace_api.py`
  - 团队空间导航、资料库、资料选择器、成员管理前端契约：`tests/test_frontend_workspace_contract.py`
  - 本次定向执行：`pytest -q tests/test_workspace.py tests/test_workspace_api.py tests/test_frontend_workspace_contract.py`，结果 **97 passed**
  - 全量回归：`pytest -q`，结果 **887 passed**

---

## 并行开发分组原则与命名/开发规范

### 分组原则

每个 Phase 继续保留 `P0.A.1` 这类任务 ID，用于需求范围和验收跟踪；排期和并行开发时额外使用 `P0-G0`、`P0-G1` 这类并行组编号。推荐执行顺序如下：

| 并行组类型 | 含义 | 一般依赖 | 适合角色 |
| --- | --- | --- | --- |
| G0 基座/数据/契约 | 表结构、迁移、默认数据、核心 API 契约、状态枚举 | 无，优先启动 | 后端/架构 |
| G1 后端服务/API | Repository、Service、Router、权限校验、后台任务 | G0 核心契约确定 | 后端 |
| G2 前端页面/交互 | 页面壳、列表、表单、选择器、状态提示、空状态 | G0 API 契约或 mock 数据 | 前端/全栈 |
| G3 集成/状态流转 | 跨页面串接、流程状态机、通知、Agent/Skill/RAG 编排 | G1 + G2 可用 | 全栈 |
| G4 测试/验收/回归 | 单元测试、API 测试、前端契约测试、权限边界、全量回归 | 随 G0~G3 增量补齐 | 测试/全栈 |

并行约束：
- 同一 Phase 内，G0 必须先产出最小可用的数据模型、状态枚举和 API 契约。
- G1 与 G2 在契约稳定后可以并行；前端允许先用 mock 数据，但最终必须回接真实 API。
- G3 不应提前启动复杂串接，除非 G1/G2 已经有可运行的最小闭环。
- G4 不是最后才做的阶段，每个并行组交付时都要同步补对应测试。
- 若只有 1 名全栈开发，可按 `G0 → G1 → G2 → G3 → G4` 串行推进；若有 2 人以上，可让后端负责 G0/G1、前端负责 G2，全栈或负责人负责 G3/G4 收口。

### 命名标准

任务与代码命名统一如下，避免后续多人并行时出现同义对象和接口漂移：

| 类别 | 标准 | 示例 |
| --- | --- | --- |
| 任务 ID | `P{phase}.{功能域}.{序号}`；并行组用 `P{phase}-G{序号}` | `P0.A.1`、`P2-G1` |
| 数据表 | 小写 snake_case，领域名清晰，不使用品牌或企业专有缩写 | `workspace_members`、`knowledge_sources`、`project_source_refs` |
| ORM/Schema/Service/Repository | PascalCase；Repository 只做持久化，Service 放业务规则 | `WorkspaceMember`、`KnowledgeSourceRepository`、`WorkspaceService` |
| API 路径 | 单团队默认入口用 `/api/workspace/default`；集合资源用复数；不要新增 `/team/*` 平行前缀 | `/api/workspace/default/members`、`/api/workspace/{id}/sources` |
| 前端模块 | 页面对象 PascalCase；JS/CSS/DOM 前缀用 kebab-case | `TeamSpacePage`、`team-space-source-list` |
| 状态枚举 | 小写 snake_case，统一在模型/Schema 中集中声明 | `active`、`archived`、`snapshot_frozen`、`approval_required` |
| runtime 路径 | 所有上传、索引、产物、日志进 `runtime/`，不得提交 | `runtime/data/knowledge_sources/`、`runtime/results/artifacts/` |

### 开发规范

- 单团队部署不等于无权限：仍保留 `WorkspaceMember`、`RolePolicy`、`ResourceACL`、`AgentAuthorization` 等底座，只是不开放多团队创建和切换。
- Router 不直接写数据库或文件系统；新增持久化必须进入 Repository/Storage，业务判断进入 Service。
- 后端权限校验必须在中间件或 Service 层统一执行，前端隐藏按钮只能作为体验优化，不能替代鉴权。
- 新增“团队空间”页面必须沿用现有“智能对话”“审查模式”“管理后台”的导航、按钮、表格、卡片、空状态和错误提示风格，不新增一套 UI 体系。
- 每个阶段至少覆盖：迁移幂等测试、权限边界测试、API 契约测试、关键前端契约测试；涉及状态机/Agent/RAG 的阶段必须补状态流转和越权回归。
- 外部凭证、真实用户数据、上传资料、索引、模型调用日志和生成产物只允许落在 `runtime/` 或环境变量中，不进入 git。
- 开源组件引入必须记录用途、许可证、运行形态和替代方案；向量库、Agent 框架、MCP 工具必须先经过 POC 决策门。

---

## Phase 0：团队资料库 MVP（已验证完成，2026-06-05）

> 目标：新增与“智能对话”“审查模式”“管理后台”并列的“团队空间”页面；团队成员能在默认团队空间中导入共享文档，并在聊天和审查中被显式引用。
> 关键约束：第一版只做"能共享、能引用、能追溯版本"，不做复杂自动 RAG。

### P0.0 并行开发分组

| 并行组 | 包含任务 | 依赖 | 可并行角色 | 并行说明 |
| --- | --- | --- | --- | --- |
| P0-G0 数据与初始化 | P0.A.1~P0.A.7 | 无 | 后端 | 先完成默认 workspace、成员入队、资料源、项目引用和旧项目迁移，给后续 API/页面稳定契约 |
| P0-G1 资料库 API | P0.B.1~P0.B.4 | P0-G0 中 Workspace/KnowledgeSource 可用 | 后端 | 上传、列表、软删除、标签接口可独立开发，文件必须落 `runtime/` |
| P0-G2 团队空间页面 | P0.E.1~P0.E.3、P0.B.5~P0.B.6 | API 契约或 mock 数据 | 前端/全栈 | “团队空间”导航和资料库主入口可与后端并行，最终回接真实 API |
| P0-G3 项目引用集成 | P0.C.1~P0.C.4 | P0-G1 + P0-G2 | 全栈 | 串接审查项目页、资料选择器、引用关系和快照版本 |
| P0-G4 权限与回归 | P0.D.1~P0.D.3、P0.E.4 | 随 P0-G0~G3 增量执行 | 后端/前端/测试 | 每组完成后补权限和契约测试，最后做全量回归 |

### P0.A 数据模型与迁移（已验证完成，2026-06-05）

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P0.A.1 | 新增 `Workspace` 表：`id`、`name`、`description`、`created_by`、`created_at`、`status`(active/archived) | 表创建、迁移幂等、种子数据 1 条默认 workspace | 1d |
| P0.A.2 | 新增 `WorkspaceMember` 表：`workspace_id`、`user_id`、`role`(owner/admin/member/viewer)、`status` | 表创建、外键约束、角色枚举校验 | 1d |
| P0.A.3 | 新增 `KnowledgeSource` 表：`workspace_id`、`source_type`(upload/lark_url/api)、`title`、`filename`、`content_hash`、`version`、`owner_id`、`status`、`metadata_json` | 表创建、content_hash 自动计算、版本号递增 | 1.5d |
| P0.A.4 | `ReviewProject` 新增 `workspace_id` 外键（ nullable，旧数据兼容） | 旧项目无 workspace 时仍可正常读写 | 0.5d |
| P0.A.5 | `KnowledgeSource` 与 `ReviewProject` 关联表 `project_source_refs`：`project_id`、`source_id`、`ref_type`(context/reference/background)、`snapshot_version` | 关联可创建/删除，快照版本号记录 | 1d |
| P0.A.6 | 数据迁移脚本：为所有现有 `ReviewProject` 自动归入默认 workspace，`created_by` 从项目 owner 填入 | 迁移后旧项目仍可用，所有项目有 workspace_id | 1d |
| P0.A.7 | 注册/用户初始化钩子：新注册用户自动加入默认 workspace，默认角色 `member`；首个初始化管理员或系统管理员为 `owner/admin` | 注册后 `WorkspaceMember` 自动存在；普通用户可进入团队空间但不能管理成员 | 1d |

### P0.B 资料上传与管理（已验证完成，2026-06-05）

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P0.B.1 | 后端 API：`POST /api/workspace/{id}/sources` 上传文件（DOCX/PDF/Markdown/图片），解析为 `KnowledgeSource` + Markdown 正文 | 上传成功返回 source_id，content_hash 正确，文件存入 runtime | 2d |
| P0.B.2 | 后端 API：`GET /api/workspace/{id}/sources` 列表（支持分页、按 source_type/tag/status 过滤） | 返回列表含元数据、版本号、content_hash | 1d |
| P0.B.3 | 后端 API：`DELETE /api/workspace/{id}/sources/{sid}` 删除资料（软删除，status→archived，不删文件） | 删除后列表不显示，但历史引用不受影响 | 0.5d |
| P0.B.4 | 后端 API：`PUT /api/workspace/{id}/sources/{sid}/tags` 更新标签/分类 | 标签更新成功，支持多标签 | 0.5d |
| P0.B.5 | 前端：资料库 Tab — 上传按钮、列表展示（文件名、类型、版本、标签、上传者）、删除操作 | UI 可正常操作，响应式布局 | 2d |
| P0.B.6 | 前端：资料详情页 — 原文件下载、Markdown 正文预览、引用项目列表 | 详情页正常展示，下载可用 | 1.5d |

### P0.C 项目引用与快照（已验证完成，2026-06-05）

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P0.C.1 | 后端 API：`POST /api/review/project/{pid}/sources` 项目引用资料，记录 `ref_type` 和 `snapshot_version` | 引用成功，项目资料列表更新 | 1d |
| P0.C.2 | 后端 API：`GET /api/review/project/{pid}/sources` 获取项目引用的资料列表 | 返回含 ref_type、snapshot_version 的列表 | 0.5d |
| P0.C.3 | 后端：审查任务启动时，自动冻结引用资料的 `snapshot_version`，后续资料更新不影响已冻结的引用 | 启动审查后引用版本号不变 | 1d |
| P0.C.4 | 前端：审查项目页新增"引用资料"按钮，弹出资料库选择器，支持多选和 ref_type 标注 | 选择器可用，引用后项目页展示资料卡片 | 2d |

### P0.D 权限与测试（已验证完成，2026-06-05）

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P0.D.1 | 权限校验：workspace owner/admin 可管理资料；member 可上传和引用；viewer 只读 | 非权限用户操作返回 403 | 1d |
| P0.D.2 | 自动化测试：workspace CRUD、资料上传/列表/删除、项目引用/快照、权限边界（8+ 条） | pytest 全量通过 | 2d |
| P0.D.3 | 前端契约测试：资料库 Tab 存在、上传按钮存在、引用选择器存在、权限受限操作不显示（4+ 条） | pytest 通过 | 1d |

### P0.E 团队空间页面壳与导航（已验证完成，2026-06-05）

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P0.E.1 | 前端新增一级导航项”团队空间”，与”智能对话””审查模式””管理后台”并列 | 顶栏/侧栏导航可见；选中态、hover、图标/文字风格与现有页面一致 | 0.5d |
| P0.E.2 | 新增团队空间页面基础布局：资料库、项目引用、成员概览、后续 Agent/治理入口的 Tab/分区占位 | 页面结构稳定，移动端/窄屏不挤压现有导航 | 1d |
| P0.E.3 | 迁移 P0.B 的资料库列表和上传入口到”团队空间 > 资料库”分区；保留从审查项目页打开资料选择器的入口 | 团队资料管理主入口在”团队空间”，审查页只负责引用选择 | 1d |
| P0.E.4 | 前端契约测试：一级导航存在”团队空间”；页面初始渲染不影响智能对话、审查模式、管理后台；普通 member 可访问资料库，管理动作按权限隐藏 | pytest 通过 | 1d |

#### P0.E 前端设计要素记录

> 以下为 P0.E 实际落地的前端结构、交互和样式要素，供后续 P1/P2 前端开发参照。所有要素沿用现有页面的 topbar、sidebar、表格、按钮、空状态和品牌注入风格。

**页面结构**：

- topbar：品牌标识（`data-branding=”topbar-logo”` / `”topbar-title”` / `”app-version”`）+ 页面 badge（`data-branding=”workspace-badge”`，蓝色 `var(--blue-4)`）+ 跨页面导航按钮（智能对话/审查模式/管理后台）+ 用户名 + 退出
- sidebar（`.workspace-sidebar`）：两个 Tab 按钮（资料库/团队成员，各配 SVG 图标）+ sidebar-toggle 收起按钮；collapsed 时 `width:0` + `overflow:hidden` + 无边框
- content（`.workspace-content`）：`flex:1` + `overflow-y:auto` + `background:var(--color-bg)`；Tab 切换通过 `.workspace-panel.active` 控制

**资料库 Tab**（P0.B.5）：

- panel-head：标题”资料库” + 上传按钮（`btn btn-primary btn-sm`，文案”+ 上传资料”）
- 列表：`.ws-sources-table` 表格，列 = 类型(emoji) / 标题(可点击进详情) / 文件名 / 版本 / 标签(.ws-tag-chip) / 状态(.ws-status-chip) / 操作(详情+删除)
- 空状态：`.ws-empty` — SVG 图标(64×64 蓝底加号) + 标题 + 描述文案
- 上传：隐藏 `<input type=”file” multiple accept=”.docx,.pdf,.md,.txt,.markdown”>`；上传中按钮文案改为”上传中…”；完成后 Toast 显示成功/失败数量
- 删除确认：复用 `#modal-overlay` 弹窗，”取消”/”删除”（红色 `var(--red-6)`）按钮

**资料详情页**（P0.B.6）：

- 进入方式：点击列表标题或”详情”按钮 → `#ws-source-detail` 显示 / `#ws-sources-list` 隐藏
- panel-head：标题 + 元信息(v版本/类型/日期) + 下载原文件按钮(需 `file_id`) + 删除按钮(owner/admin) + 返回列表按钮
- 元数据网格：`grid-template-columns:120px 1fr` — 文件名/内容哈希/标签/状态
- 正文预览：`.extracted_text` 截断 500 字 + `<pre>` 块展示，`max-height:200px;overflow-y:auto`
- 引用项目列表：`source.project_refs` 渲染为 `<ul>`
- 下载鉴权：`API.downloadWorkspaceSource()` 携带 Bearer token 获取 blob，用 `<a download>` 触发浏览器下载

**成员 Tab**：

- 成员行（`.ws-member-row`）：用户名 + 角色标签（`.ws-member-role.ws-role-{role}`），中文映射 owner→负责人 / admin→管理员 / member→成员 / viewer→观察者
- P1 增量：owner/admin 可见角色变更 dropdown（`.ws-role-select`，选项 owner/admin/member/viewer）+ 停用/恢复按钮（`.ws-member-action`）
- 角色变更确认：inline dropdown 选择后弹出 modal-overlay 确认弹窗；不能变更自身角色；owner 降级需二次确认
- 停用/恢复：停用后成员行灰化（`opacity: 0.5`）+ 角色标签旁显示"已停用" badge；恢复后还原
- 空状态：居中灰色提示文字

**权限显隐规则**：

| 操作 | owner | admin | member | viewer |
| --- | --- | --- | --- | --- |
| 上传资料 | ✓ | ✓ | ✓ | ✗ |
| 查看详情 | ✓ | ✓ | ✓ | ✓ |
| 下载原文件 | ✓ | ✓ | ✓ | ✓ |
| 删除资料 | ✓ | ✓ | ✗ | ✗ |
| 管理按钮(详情页) | ✓ | ✓ | ✗ | ✗ |
| 变更成员角色 | ✓ | ✓ | ✗ | ✗ |
| 停用/恢复成员 | ✓ | ✓ | ✗ | ✗ |
| 修改团队名称/描述 | ✓ | ✓ | ✗ | ✗ |

前端通过 `_memberRole`（从 `_loadMembers` 获取当前用户角色）判断，`canManage = owner || admin`。

**品牌注入点**：

| data-branding | 值 | 位置 |
| --- | --- | --- |
| `topbar-logo` | 品牌资产 | 页面顶栏 `.brand-dot` |
| `topbar-title` | 产品名 | 页面顶栏标题 |
| `app-version` | 版本号 | 页面顶栏副标题 |
| `workspace-badge` | “团队空间” | 页面 badge |

**CSS 类名体系**（`main.css` 4700~4950 行）：

所有 workspace 页面 CSS 类名以 `ws-` 前缀或 `workspace-` 前缀，与现有 `chat-`、`review-`、`admin-` 前缀平行。Tab 切换、sidebar 收起、空状态、表格、状态标签和角色标签均有独立类名。

---

## Phase 1：团队空间与权限底座（3 项已验证完成，2 项部分完成，其余未开始）

> 目标：在单团队部署前提下建立权限原则，确保注册用户默认属于本团队、资料访问可控、关键动作绑定具体人。
>
> 进入条件复核（2026-06-05）：**可以开始 P1**。定向执行 `pytest -q tests/test_workspace.py tests/test_workspace_api.py tests/test_frontend_workspace_contract.py`，结果 `91 passed`。但开工前应先收口两个前提：1）默认团队空间的“默认”身份不能继续依赖 `name == "默认空间"`；2）成员管理前端已经有只读骨架，后续应按增量补齐而不是按“未开始”从零估算。

### P1.0 并行开发分组

| 并行组 | 包含任务 | 依赖 | 可并行角色 | 并行说明 |
| --- | --- | --- | --- | --- |
| P1-G0 默认团队与成员 API | P1.A.1~P1.A.2 | P0 完成 | 后端 | 先固化默认团队稳定标识，再补默认入口、成员角色变更和停用语义 |
| P1-G1 权限收口与访问对齐 | P1.B.1~P1.B.3 | P1-G0 契约确定 | 后端/架构 | 先统一现有粗粒度角色判断，再把审查域访问与 workspace 成员状态对齐 |
| P1-G2 成员管理 UI | P1.A.3~P1.A.4 | P1-G0 API 契约或 mock 数据 | 前端/全栈 | 团队空间内做成员管理，不做 workspace selector |
| P1-G3 兼容与回归 | P1.B.4、P1.C.1~P1.C.2 | P1-G0~G2 | 全栈/测试 | 验证旧项目、旧对话、旧管理后台不受权限底座影响 |

### P1.A 单团队设置与成员管理

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P1.A.1 | 后端 API：`GET /api/workspace/default` 获取默认团队空间；`PUT /api/workspace/default` 更新团队名称、描述、状态；在开放改名前先把默认团队解析从名称匹配收口为稳定标识 | 不开放创建多个 workspace；默认团队信息可维护；团队改名后注册自动入队和启动迁移仍正常 | 1d | ✅ 已验证完成：`Workspace.is_default` 字段已落地；`get_default()` 按 `is_default==True` 查询；`_ensure_default_workspace()` 含旧数据 `name=="默认空间"` 自动标记 `is_default=True` 兼容；`GET /api/workspace/default` + `PUT /api/workspace/default` 端点已实现（改名/描述，owner/admin 权限，空名称 422 拒绝）；改名后注册自动入队验证通过；6 项自动化测试 |
| P1.A.2 | 后端 API：`GET /api/workspace/default/members` 成员列表；`PUT /api/workspace/default/members/{uid}` 改角色/停用；注册用户自动出现在成员列表 | 成员角色变更正确；停用后不可访问团队空间 | 1.5d | ✅ 已完成：GET/PUT 默认成员入口 + 角色变更/停用恢复 + 禁止自身变更 + 审计日志 + 6 项测试 |
| P1.A.3 | 前端：团队空间 > 成员管理分区 — 成员列表、角色变更、停用/恢复、权限提示 | UI 与现有管理后台表格/按钮样式一致；普通 member 不显示管理操作 | 1.5d | ✅ 已完成：角色下拉变更 + 停用/恢复按钮 + 确认对话框 + 权限显隐 + 5 项契约测试 |
| P1.A.4 | 移除/不实现多空间切换器；导航中只显示”团队空间”单入口，不出现 workspace selector | 不存在多团队切换 UI；旧页面不受影响 | 0.5d | ✅ 已验证完成 |

### P1.B 权限收口与访问对齐

> 单团队粗权限阶段先统一现有权限语义，不强制在 P1 先落 `RolePolicy` / `ResourceACL` 表。等 P2/P3 出现检索、Agent、消息等跨资源权限需求时，再评估是否把策略持久化为独立表。

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P1.B.1 | 统一 workspace 角色动作映射：抽出 `WorkspaceAccessService` 或同等 helper，替换 router 内 `_MANAGE_ROLES` / `_WRITE_ROLES` / `_READ_ROLES` 等硬编码集合 | owner/admin/member/viewer 四档动作集中定义；workspace API 复用同一判断入口 | 1d | ✅ 已完成：workspace_access.py 集中权限服务 + workspace.py 全部替换为 require_action |
| P1.B.2 | 审查域权限对齐：`ReviewProject` / `ReviewTask` 访问在 owner 校验外补 workspace active member 校验；成员停用后不能继续通过旧项目 owner 身份访问团队资源 | 成员移除后无法继续访问所属 workspace 的项目和团队资料；旧数据兼容 | 1.5d | ✅ 已完成：create_project + add_project_source_ref 补 is_active_member 检查 + 2 项测试 |
| P1.B.3 | 统一权限入口：workspace/review 相关 API 复用统一鉴权 helper，并记录 403/越权访问审计日志 | 无权限返回 403；权限逻辑不再散落在多个 router 分支 | 1.5d | ✅ 已完成：workspace_access.py 统一 require_action + review.py _verify_project_owner 统一接入 + 403 审计日志 + legacy 项目回退校验 |
| P1.B.4 | 旧数据兼容：无 workspace_id 的项目/资料自动归入默认团队空间，owner/admin 由系统管理员承接 | 迁移后旧数据仍可用，权限正确 | 1d | ✅ 已验证完成 |

### P1.C 权限测试与回归

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P1.C.1 | 自动化测试：默认团队读取/更新、注册用户自动入队、成员角色变更/停用、workspace/review 统一权限拦截、停用成员失去团队空间与项目访问（10+ 条） | pytest 通过 | 2d | ✅ 已完成：8 项成员管理 + 2 项审查域 = 10 条权限专项测试 + 5 项前端契约测试 |
| P1.C.2 | 回归验证：旧版审查项目/智能对话/管理后台功能不受”团队空间”页面新增影响 | 全量 pytest 通过 | 1d | ✅ 已完成：778 全量回归通过 |

---

## Phase 2：知识库检索与对话 RAG（已验证完成，2026-06-08）

> 前置：检索 POC 已通过（POC-A ✅ + POC-B ✅ 最终选型结论：**LanceDB 单引擎首选**，FTS5 降级回退，分数差拒答，OpenAI embedding。详见 `docs/3-design/检索引擎选型最终结论.md`）。
> 目标：资料可通过 FTS 和向量检索召回，对话和审查可显式引用来源。

### P2.0 并行开发分组

| 并行组 | 包含任务 | 依赖 | 可并行角色 | 并行说明 |
| --- | --- | --- | --- | --- |
| P2-G0 文档解析与索引基座 | P2.A.1~P2.A.5 | P1 完成 + POC-A+B 决策 | 后端 | 先完成 document/chunk 模型、切块策略、FTS 索引入口和 EmbeddingService |
| P2-G5 LanceDB 集成与降级 | P2.E.1~P2.E.3 | P2-G0 chunk 可用 + POC-A+B 决策 | 后端 | **必须先产出 KnowledgeVectorService API 契约**，G1 依赖此契约设计 RetrievalService |
| P2-G1 检索服务/API | P2.B.1~P2.B.4 | **P2-G5 API 契约确定** + P2-G0 可写入 chunk | 后端 | RetrievalService 消费 KnowledgeVectorService API、权限过滤、拒答策略、检索 API |
| P2-G2 引用展示前端 | P2.C.1、P2.C.3、P2.C.4 | P2-G1 API 契约或 mock 数据 | 前端/全栈 | 对话页引用按钮、来源标注、推断/引用差异样式可并行 |
| P2-G3 审查 RAG 集成 | P2.C.2 | P2-G1 + 现有 SkillRunner 上下文 | 全栈 | 将项目引用资料注入 ReviewContext，保持审查流程兼容 |
| P2-G4 评估与测试 | P2.D.1~P2.D.3 | 随 P2-G0~G3/G5 增量执行 | 后端/测试 | 用 POC 样例集持续跑命中率、延迟和越权召回 |

### P2.A 文档解析与切块

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P2.A.1 | 新增 `KnowledgeDocument` 表：`source_id`、`filename`、`content_hash`、`version`、`metadata_json`（含 section/page/paragraph 信息） | 表创建，关联 KnowledgeSource | 1d | ✅ 已完成 |
| P2.A.2 | 新增 `KnowledgeChunk` 表：`document_id`、`chunk_no`、`text`、`section`、`source_ref`、`embedding_status`(pending/done/failed)、`metadata_json` | 表创建，切块可 CRUD；`embedding_status` 追踪嵌入异步进度 | 1d | ✅ 已完成 |
| P2.A.3 | 后端服务 `KnowledgeIngestionService`：资料上传后触发 解析→切块→FTS 索引（同步完成）→提交异步 embedding 任务（非阻塞）；upload endpoint 不等待 embedding 完成即返回 | 上传立即返回；chunk FTS 索引 < 5s；embedding 后台完成后 `embedding_status` 更新为 done | 2d | ✅ 已完成 |
| P2.A.4 | 切块策略：保留标题、章节、页码、段落来源；最长 chunk 512 tokens，重叠 64 tokens（与 POC-A `MAX_CHUNK_CHARS=512, OVERLAP_CHARS=64` 一致） | 切块后可追溯来源 section；与 POC-A 切块结果可对比验证 | 1.5d | ✅ 已完成 |
| P2.A.5 | `EmbeddingService`：封装 OpenAI text-embedding-3-small API（1536 维）；支持批处理（最大 100 chunks/批）；指数退避重试（最多 3 次）；模型名和 API key 从环境变量注入，不硬编码 | 批量调用 API 成功；重试有效；模型可通过配置切换（为 BGE-M3 预留接口） | 1.5d | ✅ 已完成 |

### P2.B 检索服务

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P2.B.1 | 后端 `RetrievalService`：消费 `KnowledgeVectorService.search()` 接口；`retrieve(query, workspace_id, filters, top_k)` → 调用 `EmbeddingService.embed(query)` 得到查询向量 → 调用 `KnowledgeVectorService.search()` → 附加 `confidence` 字段后返回片段列表（含 `source_id`/`chunk_ref`/`section`/`confidence`） | 查询延迟 < 1s（LanceDB P50=10ms + embedding API ~200ms = 合计 < 500ms）；**依赖 P2.E.1 先完成 API 契约** | 2d | ✅ 已完成 |
| P2.B.2 | 检索前权限过滤：只返回当前用户在 workspace 内有 read 权限的资料切块 | 无越权召回，跨空间检索返回空 | 1.5d | ✅ 已完成 |
| P2.B.3 | 新增 `RetrievalLog` 表：`query`、`filters_json`、`hit_count`、`selected_chunks`、`latency_ms`、`user_id` | 日志可写入和查询 | 1d | ✅ 已完成 |
| P2.B.4 | 检索 API：`POST /api/workspace/{id}/retrieve` 接受 query、filters、top_k | 返回结构化结果含引用来源 | 1d | ✅ 已完成 |

### P2.C 对话与审查 RAG 集成

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P2.C.1 | 对话页新增"引用资料"按钮：用户选择资料库后，系统将资料切块作为 context 注入对话 system prompt | 对话回复含引用标注 | 2d | ✅ 已完成 |
| P2.C.2 | 审查项目上下文注入：项目引用的资料切块自动进入审查 SkillRunner 的 ReviewContext | 审查报告中引用资料来源 | 1.5d | ✅ 已完成 |
| P2.C.3 | 前端：对话消息和审查报告显示引用来源（文件名、章节、段落号），点击可跳转资料详情 | 引用标注可见且可点击 | 2d | ✅ 已完成 |
| P2.C.4 | 区分标注："引用资料得出的结论"与"模型推断"在 UI 上有不同样式 | 两类标注视觉可区分 | 1d | ✅ 已完成 |

### P2.D 检索评估与测试

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P2.D.1 | 检索评估：用 POC 样例集（20 份 PRD + 5 份规范 + 30 个问题 + **4 个 no_answer 问题**）跑 top-5 命中率和 no_answer 拒答率 | top-5 命中率 ≥ 80%（最低门槛）；使用真实 OpenAI embedding 时预期 ≥ 92%（POC-A+B 数据基准 95.2%）；no_answer 问题拒答率 ≥ 50%（校准 P2.E.3 的分数差阈值）；无越权召回 | 2d | ✅ 已完成：top-5 命中率 95.8% ≥ 92%，no_answer 拒答率 87.5% ≥ 50%，无越权召回，34 项评估测试通过 | |
| P2.D.2 | 自动化测试：切块 CRUD、FTS 检索、向量检索、权限过滤、引用注入（10+ 条） | pytest 通过 | 2d |
| P2.D.3 | 新增 `AnswerFeedback` 表：`object_type`、`object_id`、`user_id`、`rating`(helpful/unhelpful)、`comment`、`created_at` | 反馈可写入 | 0.5d | ✅ 已完成 |

### P2.E LanceDB 集成与降级（POC-A+B 选型新增）

> 选型依据：`docs/3-design/检索引擎选型最终结论.md`
> **G1 依赖本组 API 契约**：P2.E.1 必须先定义 `KnowledgeVectorService` 接口（输入/输出字段、错误类型），G1 才能开始设计 `RetrievalService`。

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P2.E.1 | `KnowledgeVectorService`：封装 LanceDB 操作；`upsert(chunks, vectors)` 批量写入（schema：`source_id`/`workspace_id`/`title`/`section`/`text`/`vector[1536]`）；`search(query_vec, workspace_id, top_k)` 带 prefilter 权限过滤，返回 `{source_id, section, text_snippet, _distance}`；索引目录 `runtime/vector/lancedb/`；**同时输出接口契约文档供 G1 参考** | LanceDB 索引创建/增量写入/workspace prefilter 查询；目录复制备份恢复（≤10ms/15MB 量级，与 POC-B 一致） | 2.5d | ✅ 已完成 |
| P2.E.2 | FTS5 降级回退：`RetrievalService` 检测到 LanceDB 不可用（ImportError / 索引文件损坏 / 查询超时）时自动回退到 FTS5 关键词检索，降级事件写入 `RetrievalLog.fallback_reason` | 模拟 LanceDB 失败，降级自动生效；`RetrievalLog` 含降级标记 | 1d | ✅ 已完成 |
| P2.E.3 | 拒答策略：基于 `_distance` 分数差判断。gap = `results[1]._distance - results[0]._distance`；gap < 阈值（默认 0.065，POC-C 校准值）时返回 `{confidence: "low", rejected: true}`；`RetrievalService.retrieve()` 结果含 `confidence` 字段 | 构造 top-1/top-2 相近的 mock 数据时拒答生效；阈值可通过配置文件调整；`confidence` 字段在 API 响应中可见 | 1.5d | ✅ 已完成 |

---

## Phase 3：Agent 对话与工具注册（未开始）

> 前置：Agent POC 已通过（见 POC-B）。
> 目标：用户能以"自己的账号 Agent"完成对话、检索、搜索和简单内容生成。

### P3.0 并行开发分组

| 并行组 | 包含任务 | 依赖 | 可并行角色 | 并行说明 |
| --- | --- | --- | --- | --- |
| P3-G0 Agent Profile 与授权 | P3.A.1~P3.A.4 | P2 完成 + POC-B 决策 | 后端/前端 | 先定义个人 Agent、团队授权范围和配置入口 |
| P3-G1 Agent Run/Trace 循环 | P3.B.1~P3.B.4 | P3-G0 数据模型 | 后端/架构 | 受限 ReAct 循环、AgentRun/AgentStep/ToolCallTrace 是 Agent 可审计的核心 |
| P3-G2 Tool Registry 与 MCP Policy | P3.C.1~P3.C.4 | P3-G0 授权模型 | 后端 | 工具注册和策略可与运行循环并行，但最终必须接入审批与 Trace |
| P3-G3 高风险人工审批 | P3.D.1~P3.D.3 | P3-G1 + P3-G2 | 全栈 | 写入/通知/归档/跨系统调用必须先挂起再审批 |
| P3-G4 对话页集成与测试 | P3.E.1~P3.E.3 | P3-G1~G3 | 前端/全栈/测试 | Agent 模式、工具轨迹、引用标注和自动化测试收口 |

### P3.A Agent Profile 与授权

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P3.A.1 | 新增 `AgentProfile` 表：`owner_type`(user/team/review)、`owner_id`、`name`、`system_policy`(system prompt)、`allowed_tools_json`、`status`(active/disabled)、`version`、`created_at` | 表创建，用户注册后自动创建个人 AgentProfile | 1d |
| P3.A.2 | 新增 `AgentAuthorization` 表：`agent_id`、`granted_by`、`scope_type`(workspace/project/personal)、`scope_id`、`permissions_json`、`expires_at` | 授权条目可创建/查询/撤销 | 1d |
| P3.A.3 | 后端 API：`GET /api/agent/profile` 获取当前用户 Agent 配置；`PUT /api/agent/profile` 更新 Agent 名/工具白名单 | API 可用，变更落库 | 1d |
| P3.A.4 | 前端：Agent 设置页 — 名称、工具开关（search/rag/SkillRunner/artifact）、授权范围查看 | UI 正常操作 | 1.5d |

### P3.B Agent 运行与 Trace

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P3.B.1 | 新增 `AgentRun` 表：`agent_id`、`user_id`、`goal`、`plan_json`(可选)、`status`(planning/running/completed/failed)、`created_at`、`finished_at` | 表创建，运行可创建/更新状态 | 1d |
| P3.B.2 | 新增 `AgentStep` 表：`run_id`、`step_no`、`step_type`(plan/tool/observe/respond)、`tool_name`、`input_ref`、`output_ref`、`status`、`latency_ms` | 步骤可记录和查询 | 1d |
| P3.B.3 | 新增 `ToolCallTrace` 表：`run_id`、`step_id`、`tool_name`、`input_json`(摘要)、`output_ref`、`status`、`risk_level`(low/medium/high)、`approval_status`(none/pending/approved/rejected) | Trace 可写入和审计查询 | 1d |
| P3.B.4 | 后端 `AgentApplicationService`：受限 ReAct 循环 — 规划→工具调用→观察→响应，最大 10 步、最大 3 次工具调用 | 循环可运行且受步数限制，超出后降级为直接回复 | 3d |

### P3.C Tool Registry 与 MCP

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P3.C.1 | `ToolRegistry` 服务：注册 Skills（6 个现有 skill 通过 registry 暴露为 Agent 可调用工具）、search、rag、artifact_generator | Agent 可通过 registry 调用 search 和 SkillRunner | 2d |
| P3.C.2 | 新增 `MCPServerConfig` 表：`workspace_id`、`name`、`server_type`、`endpoint_ref`、`status`、`metadata_json` | 配置可创建/启停 | 1d |
| P3.C.3 | 新增 `MCPToolPolicy` 表：`server_id`、`tool_name`、`allowed_roles_json`、`requires_approval`(boolean)、`risk_level`(low/medium/high) | 策略可配置，高风险工具默认 requires_approval=true | 1d |
| P3.C.4 | MCP adapter：轻量 Client 连接外部 MCP Server（Figma、搜索等），工具调用前检查 Policy | 工具调用经 Policy 检查后放行或挂起 | 2d |

### P3.D 人工审批

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P3.D.1 | 新增 `AgentApprovalRequest` 表：`run_id`、`requester_id`(agent)、`approver_id`(user)、`action_type`、`payload_ref`、`status`(pending/approved/rejected)、`decision_comment`、`created_at` | 审批可创建/查询/处理 | 1d |
| P3.D.2 | Agent 高风险动作自动生成审批请求：写入/通知/归档/跨系统调用前挂起，等待用户处理 | 高风险工具调用被拦截，审批请求可见 | 2d |
| P3.D.3 | 前端：审批面板 — 显示待审批请求列表，支持批准/拒绝/加备注 | 非管理员也能看到自己的待审批项 | 1.5d |

### P3.E 对话页 Agent 集成与测试

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P3.E.1 | 对话页：选择对话模式（普通聊天 / Agent 模式），Agent 模式显示工具调用轨迹（工具名、输入摘要、耗时） | Agent 模式可见工具调用摘要 | 2d |
| P3.E.2 | 对话页：Agent 回复标注工具来源和引用资料，与模型推断区分 | 回复含引用标注和推断标注 | 1d |
| P3.E.3 | 自动化测试：AgentProfile CRUD、AgentRun 状态流转、ToolRegistry 注册/调用、MCPToolPolicy 过滤、审批请求创建/处理（12+ 条） | pytest 通过 | 2d |

---

## Phase 4：审查平台协作化（未开始）

> 目标：形成"发起 → AI 初审 → 人工确认 → 讲解产物 → 团队评审"的闭环。

### P4.0 并行开发分组

| 并行组 | 包含任务 | 依赖 | 可并行角色 | 并行说明 |
| --- | --- | --- | --- | --- |
| P4-G0 审查请求与状态机 | P4.A.1~P4.A.5 | P3 完成 | 后端/架构 | 先定义 ReviewRequest、Participant、StageExecution 和阶段重跑规则 |
| P4-G1 快照与人工确认 | P4.B.1~P4.B.3 | P4-G0 状态机 | 全栈 | 知识快照冻结、采纳/驳回/强行通过是审查控制权核心 |
| P4-G2 讲解产物管线 | P4.C.1~P4.C.6 | P4-G0 + P4-G1 输出结构 | 后端/前端 | Artifact、presentation-generator、沙盒预览可独立推进，但来源必须追溯快照 |
| P4-G3 通知与评论 | P4.D.1~P4.D.5 | P4-G0 事件定义 | 全栈 | 通知、评论、@提及可与讲解管线并行，事件名称要统一 |
| P4-G4 测试与回归 | P4.E.1~P4.E.2 | 随 P4-G0~G3 增量执行 | 测试/全栈 | 覆盖状态流转、快照冻结、人工确认、产物生成和旧审查模式回归 |

### P4.A 发起式审查状态机

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P4.A.1 | 新增 `ReviewRequest` 表：`workspace_id`、`project_id`、`initiator_id`、`goal`(text)、`status`(initiated/snapshot_frozen/ai_reviewing/pending_confirm/modifying/forced_pass/presenting/in_review/archived)、`created_at` | 表创建，状态枚举完整 | 1d |
| P4.A.2 | 新增 `ReviewParticipant` 表：`request_id`、`user_id`、`role`(initiator/reviewer/approver/observer)、`permissions_json`、`status` | 参与者可添加和变更角色 | 1d |
| P4.A.3 | 新增 `ReviewStageExecution` 表：`request_id`、`stage`(snapshot/classify/per_analysis/system_review/confirm/presentation/review_meeting/archive)、`status`(pending/running/completed/failed)、`input_snapshot_ref`、`output_ref`、`started_at`、`finished_at` | 阶段执行可记录和重跑 | 1d |
| P4.A.4 | 后端 `ReviewInitiationService`：发起审查 → 冻结快照 → 触发 SkillRunner → 产出 AI 初审结果 | 发起后自动冻结知识快照，SkillRunner 按阶段执行 | 3d |
| P4.A.5 | 阶段重跑：支持从某阶段重新执行，不从头全量重跑 | 重跑后新结果覆盖该阶段，后续阶段可重新触发 | 1.5d |

### P4.B 知识快照与人工确认

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P4.B.1 | 新增 `KnowledgeSnapshot` 表：`workspace_id`、`project_id`、`request_id`、`source_refs_json`(资料版本列表)、`chunk_refs_json`(切块版本列表)、`prompt_version`、`skill_version`、`model_config_hash`、`created_at` | 快照可创建，审查开始后只追加不覆盖 | 1d |
| P4.B.2 | 人工确认功能：发起人对 AI 初审结果逐条采纳/驳回/强行通过，记录 `decision_comment` | 确认操作落库，驳回可附带原因 | 2d |
| P4.B.3 | 前端：审查确认页 — 显示 AI 初审问题清单，逐条操作（采纳/驳回/强行通过），强行通过需二次确认弹窗 | UI 可操作，强行通过有额外确认 | 2d |

### P4.C AI 讲解产物管线

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P4.C.1 | 新增 `Artifact` 表：`object_type`、`object_id`、`artifact_type`(html_presentation/svg_summary/mermaid_diagram/meeting_pack)、`path_ref`、`source_snapshot_ref`、`template_version`、`created_at` | 产物可记录，不覆盖历史 | 1d |
| P4.C.2 | 讲解 DSL 生成 Skill：`presentation-generator` 输入 PRD + 初审结果 + 快照，输出结构化讲解 JSON（场景列表：标题/要点/旁白/视觉/时长） | 输出 JSON 含完整场景定义，Schema 校验通过 | 2d |
| P4.C.3 | HTML/SVG 渲染：讲解 JSON → 固定模板渲染 Mermaid 图 → SVG 视觉摘要 → HTML 讲解页（可交互，章节导航） | 产物可预览，关键结论可追溯到快照 | 3d |
| P4.C.4 | 新增 Skill `skills/presentation-generator/`：SKILL.md、prompts/、templates/（讲解 JSON Schema） | Skill 独立可运行，可被 SkillRunner 编排 | 1.5d |
| P4.C.5 | 沙盒预览：AI 生成的 HTML 在 iframe sandbox 中渲染，禁止访问 cookie/API/外部网络 | 预览隔离，沙盒安全校验通过 | 1d |
| P4.C.6 | 前端：讲解产物预览页 — 章节导航、全屏播放、来源标注 | 可预览和全屏 | 2d |

### P4.D 通知与评论

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P4.D.1 | 新增 `Notification` 表：`recipient_id`、`actor_id`、`object_type`、`object_id`、`type`(review_request/approval/comment/mention)、`status`(unread/read/archived)、`created_at` | 通知可写入和查询 | 1d |
| P4.D.2 | 新增 `Comment` 表：`object_type`(review_request/artifact/source)、`object_id`、`author_id`、`body`、`parent_id`(回复)、`created_at` | 评论可创建/查询/回复 | 0.5d |
| P4.D.3 | 后端 `NotificationService`：审查事件（发起、初审完成、待确认、讲解生成、评审会）→ 创建通知 → SSE 推送 | 审查流程中关键节点触发通知 | 2d |
| P4.D.4 | 前端：通知铃铛 + Inbox 列表（未读/已读/归档），点击跳转到对应审查任务 | 通知实时到达，可跳转 | 1.5d |
| P4.D.5 | 前端：评论组件 — 审查任务页/讲解产物页下方评论区，支持回复和 @提及 | 评论可创建和展示 | 1d |

### P4.E 测试与回归

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P4.E.1 | 自动化测试：ReviewRequest 状态流转、快照冻结、人工确认操作、讲解产物生成、通知创建/推送、评论 CRUD（12+ 条） | pytest 通过 | 2d |
| P4.E.2 | 回归验证：原有 6 种审查模式仍可正常运行，SkillRunner 不受协作流程影响 | 全量 pytest 通过 | 1d |

---

## Phase 5：个人账号 Agent 与消息中心（未开始）

> 目标：他人与你的 Agent 对话后你可收到消息并回复/批注；账号从登录凭证升级为协作主体。
> 单团队部署口径：P5 不新增与“团队空间”并列的“个人空间”一级页面；个人资料先作为用户私有知识作用域存在，通过个人 Agent 设置和消息中心访问。

### P5.0 并行开发分组

| 并行组 | 包含任务 | 依赖 | 可并行角色 | 并行说明 |
| --- | --- | --- | --- | --- |
| P5-G0 个人私有知识与 Agent 行为 | P5.A.1~P5.A.4 | P3 完成 | 全栈 | 定义个人私有 scope、个人 Agent 默认行为和个人菜单/消息中心入口 |
| P5-G1 消息中心 API 与页面 | P5.B.1~P5.B.3 | P4.D 通知模型或等价基础可用 | 全栈 | 消息列表、已读、归档、类型分组可独立推进 |
| P5-G2 评论与提及增强 | P5.C.1~P5.C.3 | P4.D 评论模型或等价基础可用 | 全栈 | @提及、resolve、回复折叠与通知事件联动 |
| P5-G3 测试与隔离回归 | P5.D.1 | P5-G0~G2 | 测试/全栈 | 重点验证个人资料不进团队知识库、跨人 Agent 对话必须审批 |

### P5.A 个人空间与 Agent

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P5.A.1 | 个人私有知识作用域：每个用户有默认私有 scope，`KnowledgeSource`/`KnowledgeChunk` 可标记为 `owner_type=user`、`visibility=private` | 个人资料默认不进入团队知识库；不新增个人空间一级页面 | 1d |
| P5.A.2 | 个人 Agent 默认行为：只访问个人授权资料 + 已授权项目资料；别人向我的 Agent 提问时优先生成"待本人确认/回复"消息 | Agent 回答不越权，自动生成待确认消息 | 2d |
| P5.A.3 | Agent 间对话：用户 B 的 Agent 调用用户 A 的 Agent 时，系统创建 `AgentApprovalRequest` → A 收到通知 → A 可亲自回复或授权 Agent 代答 | 跨人对话有通知和审批链路 | 2d |
| P5.A.4 | 前端：个人 Agent 设置入口 — 个人知识库管理、Agent 配置、授权范围查看，入口放在个人菜单或消息中心，不作为一级导航页面 | UI 正常操作；一级导航仍只有团队空间/智能对话/审查模式/管理后台等主入口 | 2d |

### P5.B 消息中心完善

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P5.B.1 | 消息中心 API：`GET /api/notifications` 分页列表；`PUT /api/notifications/{id}/read` 标记已读；`POST /api/notifications/batch-read` 批量已读；`PUT /api/notifications/{id}/archive` 归档 | CRUD 可用 | 1d |
| P5.B.2 | 消息类型扩展：review_request、approval_request、comment_reply、mention、agent_conversation、task_reminder | 各类型通知可区分展示 | 0.5d |
| P5.B.3 | 前端：消息中心页 — 按类型分组、未读高亮、批量操作、跳转链接 | 完整消息中心可用 | 2d |

### P5.C 评论与提及完善

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P5.C.1 | @提及功能：评论中输入 @username 触发用户搜索，选中后创建 mention 通知 | @提及可触发通知 | 1.5d |
| P5.C.2 | 评论 resolve：审查问题行级评论可标记 resolved/forced_pass，状态变更触发通知 | resolve 操作落库，通知推送 | 1d |
| P5.C.3 | 前端：评论区支持 resolve 标记、@提及、回复折叠 | UI 功能完整 | 1.5d |

### P5.D 测试

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P5.D.1 | 自动化测试：个人空间隔离、Agent 跨人对话审批链、消息 CRUD、@提及通知、评论 resolve（10+ 条） | pytest 通过 | 2d |

---

## Phase 6：治理与运营（未开始）

> 目标：管理员能看到团队采用情况、技能调用、成本耗时、文件访问、人工确认、失败率和质量趋势。

### P6.0 并行开发分组

| 并行组 | 包含任务 | 依赖 | 可并行角色 | 并行说明 |
| --- | --- | --- | --- | --- |
| P6-G0 成本与质量统计 | P6.A.1~P6.A.3 | P4/P5 有真实事件和调用日志 | 后端/前端 | 成本、质量汇总和运营仪表盘可按已有日志增量实现 |
| P6-G1 Skill/Prompt/Agent 治理 | P6.B.1~P6.B.4 | P3/P4 Skill 与 Agent 体系稳定 | 后端/架构 | 回归框架、SkillPackage、Agent 退役、权限审计属于治理主线 |
| P6-G2 配额与预警 | P6.C.1~P6.C.3 | P6-G0 成本口径确定 | 全栈 | WorkspaceBudget、配额中间件和管理员配置页可并行开发 |
| P6-G3 治理回归测试 | P6.D.1 | P6-G0~G2 | 测试/全栈 | 覆盖统计准确性、配额拦截、Agent 退役和 Skill 回归 |

### P6.A 成本与质量仪表盘

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P6.A.1 | 成本统计服务：按 workspace/用户/模式统计模型调用次数、输入/输出 token 数、embedding token 数，写入 `CostDailySummary` 表 | 每日统计可查询 | 2d |
| P6.A.2 | 质量统计服务：按 workspace/项目统计平均评分趋势、高频缺失章节、高频边界外问题、问题关闭率，写入 `QualityWeeklySummary` 表 | 每周统计可查询 | 1.5d |
| P6.A.3 | 前端：运营仪表盘 — 用量（用户/项目/任务/模式分布）、效率（平均耗时/失败率/重试率）、成本（token/模型分布）、质量（评分趋势/高频问题） | 仪表盘可展示图表 | 3d |

### P6.B Skill/Prompt 回归与治理

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P6.B.1 | Skill 回归测试框架：每个 Skill 绑定样例文档 + 期望输出结构，升级前自动验证 | 回归框架可运行，输出对比结果 | 2d |
| P6.B.2 | `SkillPackage` 表：`name`、`version`、`description`、`capabilities_json`、`permission_requirements_json`、`status`(published/draft/deprecated) | 技能包可注册/启停/版本管理 | 1d |
| P6.B.3 | Agent 生命周期治理：AgentProfile 可退役（disabled → archived），退役前检查是否有活跃 AgentRun | 退役操作安全，无活跃运行 | 1d |
| P6.B.4 | 权限审计：定期输出 ResourceACL 和 AgentAuthorization 变更报告 | 报告可导出 | 1d |

### P6.C Workspace 配额与预警

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P6.C.1 | `WorkspaceBudget` 表：`workspace_id`、`monthly_token_limit`、`monthly_cost_limit`、`warning_threshold_pct`、`hard_limit_action`(notify/block) | 配额可配置 | 1d |
| P6.C.2 | 配额检查中间件：每次模型调用前查配额 → 超阈值发预警通知 → 超硬限制拒绝调用 | 配额拦截有效 | 1.5d |
| P6.C.3 | 前端：管理员配额设置页 — 配置月度限制、预警阈值、硬限制动作 | 配额可配置 | 1d |

### P6.D 测试

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| P6.D.1 | 自动化测试：成本统计、质量统计、Skill 回归、配额拦截、Agent 退役（8+ 条） | pytest 通过 | 2d |

---

## POC 阶段（P2/P3 前置，未开始）

> 在正式进入 P2/P3 前用 1-2 周完成三类 POC，POC 结果决定技术选型。

### POC.0 并行开发分组

| 并行组 | 包含任务 | 依赖 | 可并行角色 | 并行说明 |
| --- | --- | --- | --- | --- |
| POC-G0 样例集与评估口径 | POC-A.1 | 无 | 产品/后端/测试 | 先固定 PRD、规范、评审报告、真实问题和权限用例，避免各 POC 指标不可比 |
| POC-G1 检索库 POC | POC-A.2~POC-A.6 | POC-G0 | 后端 | SQLite FTS5、LanceDB、Milvus Lite、Chroma 同样例集对比，产出 Phase 2 向量库决策 |
| POC-G2 Agent POC | POC-B.1~POC-B.4 | POC-G0 可复用问题集 | 后端/架构 | 自建受限 ReAct 与 LangGraph 对比，产出 Phase 3 Agent 框架决策 |
| POC-G3 Embedding POC | POC-C.1~POC-C.3 | POC-G0 + POC-G1 检索脚手架 | 后端 | text-embedding-3-small 与 BGE-M3 对比，产出嵌入模型决策 |

### POC-A 检索 POC（✅ 已完成 — 最终选型：LanceDB 单引擎首选，FTS5 降级回退）

| ID | 任务 | 验收标准 | 工时估算 | 状态 |
| --- | --- | --- | --- | --- |
| POC-A.1 | 准备样例集：20 份历史 PRD + 5 份团队规范 + 5 份评审报告 + 30 个真实问题 + 10 个权限用例 | 样例集文件齐全，问题覆盖章节查找/风险定位/术语解释/跨文档对比/无答案 | 2d | ✅ 已完成 |
| POC-A.2 | SQLite FTS5 检索基准：切块 + FTS 索引 + 关键词查询 → 记录 top-5 命中率、延迟、权限过滤 | 基准数据可对比 | 1d | ✅ top-5 56.7%, 0.3ms |
| POC-A.3 | LanceDB POC：同样样例集 → 向量嵌入 + LanceDB 查询 → 记录命中率、延迟、备份恢复、runtime 目录兼容 | LanceDB 数据产出 | 2d | ✅ top-5 66.7%, 254ms |
| POC-A.4 | Milvus Lite POC：同样样例集 → 向量嵌入 + Milvus Lite 查询 → 记录命中率、延迟、中文召回、备份恢复、迁移到 Standalone 路径 | Milvus Lite 数据产出 | 2d | ✅ Runtime 复验 top-5 95.2%, 530ms（远期候选，不淘汰） |
| POC-A.5 | Chroma POC：同样样例集 → 向量嵌入 + Chroma 查询 → 记录命中率、延迟、维护体验 | Chroma 数据产出 | 1.5d | ✅ Runtime 复验 top-5 95.2%, 4.8ms（备选） |
| POC-A.6 | POC 对比报告：四方案 top-5 命中率、延迟、权限过滤、备份恢复、runtime 兼容、运维复杂度 → 选出 Phase 2 首选和备选 | 报告含决策结论 | 1d | ✅ LanceDB 单引擎首选，FTS5 降级回退（详见 `docs/3-design/检索引擎选型最终结论.md`） |

### POC-B Agent POC

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| POC-B.1 | 自建受限 ReAct 循环原型：AgentRun → AgentStep → ToolCall → 响应，最大 10 步、最大 3 次工具调用 | 循环可运行，步数限制有效 | 2d |
| POC-B.2 | LangGraph 状态机原型：同样任务 → 对比可暂停/恢复、多审批分支、持久执行 | LangGraph 原型可运行 | 2d |
| POC-B.3 | 安全评审：检查 ReAct 循环的步数限制、工具白名单、审批挂起、审计日志是否满足安全要求 | 安全评审结论记录 | 1d |
| POC-B.4 | POC 对比报告：自建 vs LangGraph 功能覆盖、依赖成本、安全可控性 → 决策 | 报告含决策结论 | 0.5d |

### POC-C Embedding POC

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| POC-C.1 | text-embedding-3-small 嵌入：样例集切块 → API 调用嵌入 → 向量检索 → 记录命中率、延迟、成本 | API embedding 数据产出 | 1d |
| POC-C.2 | BGE-M3 本地嵌入：同样切块 → 本地模型嵌入 → 向量检索 → 记录命中率、延迟、中文召回、算力需求 | 本地 embedding 数据产出 | 2d |
| POC-C.3 | POC 对比报告：两种方案命中率、延迟、成本、数据边界 → 决策 | 报告含决策结论 | 0.5d |

---

## V0.2.x 收尾与归位

> 原则：V0.2.x 收尾在已有三条主线（思考级别、Markdown/Mermaid、品牌配置），P4/P5 归位到 cowork 规划。

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| V0.A.1 | 归档原 P4"公共文件库"设计明细：V0.2.x 任务分解文档中 P4 段标注"已转入 cowork P0"，原明细保留但不开发 | 文档标注完成 | 0.5d |
| V0.A.2 | 归档原 P5"飞书导入"设计明细：标注"已转入后续连接器规划" | 文档标注完成 | 0.5d |
| V0.A.3 | V0.2.x 功能迭代任务分解文档状态收尾：P1-P3 ✅ 已完成，P4/P5 归档 | 文档与实际状态一致 | 0.5d |

---

## 团队评审准备

> 正式立项前需一次 60-90 分钟评审会。

| ID | 任务 | 验收标准 | 工时估算 |
| --- | --- | --- | ---: |
| RV.A.1 | 准备评审材料：产品定位确认、四个基础抽象、P0-P2 覆盖痛点、P3 安全边界、资源预算和试点范围 | 材料可分发 | 1d |
| RV.A.2 | 确认需要团队拍板的 8 个问题（资料库优先、空间 P1 必做、个人 Agent 不共享、MVP 粗权限、强行通过权限、向量库时机、LangGraph 时机、讲解优先级） | 8 个问题有明确结论 | — |
| RV.A.3 | 输出决策项和下一步负责人 | 会议纪要记录 | — |

---

## 试点成功标准

P0-P2 试点建议用 4 周验证：

| 标准 | 量化目标 |
| --- | --- |
| 默认团队空间真实使用 | 默认 workspace 有 ≥ 1 个非测试成员，所有注册用户默认归属该团队 |
| 至少 30 份资料进入团队资料库 | KnowledgeSource count ≥ 30 |
| 至少 10 次审查引用团队资料 | project_source_refs count ≥ 10 |
| AI 回复引用来源可被用户理解 | 用户反馈 helpful ≥ 70% |
| 无权限串用事件 | 跨空间检索返回 0 条越权结果 |
| 至少 3 个真实评审会使用 AI 初审结果或讲解材料 | ReviewRequest count ≥ 3 with participant feedback |
| 团队愿意继续把资料和评审结论沉淀进去 | 试点结束后续使用意愿确认 |
