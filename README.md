# PRD Draft Review Workflow V1

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

<a id="中文"></a>

## 中文

面向团队协作的需求评审工作流平台，重点解决 PRD 从上传、拆解、逐篇分析、系统评审到报告生成的全流程闭环问题。项目采用内网可部署架构，强调可追溯、可配置、可扩展，以及运行时数据与源码分离。

### 架构设计

系统当前采用四层协作结构：

- 接入层：FastAPI 提供认证、对话、上传、历史、管理、需求评审等 API，原生 JavaScript SPA 提供统一前端界面。
- 应用编排层：以 ChatApplicationService、ReviewPipelinePersistenceService 和 Review 路由为核心，负责模型选择、上下文装配、任务追踪、报告落库和流程协调。
- 领域与持久化层：通过 repositories、storage、log_writers 分离数据库读写、文件存储和审计日志职责，降低路由层耦合。
- AI 工作流层：SkillRunner 以 Skill-as-a-Service 方式编排 6 个专业技能，负责文档转换、分类、逐篇分析、系统评审、洞察汇总和报告生成。

```mermaid
flowchart LR
		U[评审用户] --> SPA[前端 SPA]
		A[管理员] --> SPA
		SPA --> API[FastAPI 路由层]
		API --> APP[应用服务与流程编排]
		APP --> REPO[Repository 持久化层]
		APP --> STORE[Storage 文件层]
		APP --> LOG[审计与会话日志]
		APP --> RUNNER[SkillRunner]
		RUNNER --> SKILLS[6 个评审技能]
		REPO --> DB[(SQLite)]
		STORE --> RT[runtime/data]
		LOG --> RL[runtime/logs]
		SKILLS --> RR[runtime/results]
```

### 为需求评审设计的工作流

这是当前系统最核心的能力。围绕“需求评审”而不是“单次问答”来设计，现有流程主要包括：

1. 文档接入：用户在评审项目中上传 DOCX，系统将原文件和 Markdown 转换结果写入 runtime 目录。
2. 项目化组织：每次评审以项目为单位管理文档、上下文、Prompt 和任务记录，便于多轮迭代复用。
3. 预分类与版本线索：通过 prd-overview-classify 技能对文档做概览分类，并为后续演进分析准备版本链信息。
4. 逐篇多维分析：通过 prd-per-analysis 对单篇需求文档做结构化分析，输出可落库、可追踪的维度结果。
5. 系统级交叉评审：通过 system-review 汇总多文档结果，形成业务价值、架构、竞品、产品策略、技术演进、PM 评估、行动计划等系统视角结论。
6. 洞察与报告生成：通过 requirement-insights 和 report-generator 汇总演进洞察、差距分析、评审报告和 PRD 草稿。

当前评审模式覆盖：

- `quick`：快速单文档评审。
- `review`：标准需求评审流程。
- `pm`：偏 PM 能力评估视角。
- `insight`：在标准评审基础上增加演进与缺口洞察。
- `full`：完整分析链路。
- `draft`：基于评审结果生成 PRD 草稿。

### 功能要点

- 项目化评审：按项目管理需求文档、上下文版本、评审任务和报告输出。
- OpenAI 兼容模型接入：支持多模型配置、启停、排序、API Key 加密存储，以及思考级别相关配置。
- 流程可追踪：评审任务具备状态、步骤详情、结果落库和日志记录能力，便于排查和复盘。
- 上下文注入与 Prompt 配置：支持评审上下文管理、通用 Prompt 模板和需求评审 Prompt 分离管理。
- 实时任务体验：评审流程支持流式进度反馈，适合长流程 AI 审查任务。
- 内网部署友好：SQLite + runtime 目录隔离，部署简单，便于迁移和备份。

### 后台管理功能

当前后台管理聚焦“把工作流跑稳”和“让模型配置可控”，主要包括：

- 用户管理：创建、禁用、删除普通用户或管理员账号。
- 模型管理：维护模型列表、显示顺序、启停状态、API Key、思考级别配置，并支持连通性测试与测速。
- Prompt 管理：维护通用 Prompt 模板和评审专用 Prompt。
- 技能管理：查看当前技能配置，并维护技能更新地址等元信息。
- 统计与审计：查看系统统计数据和最近访问记录，辅助运营与排障。

### 技术实现概览

- 后端：FastAPI、SQLAlchemy Async、SQLite。
- 前端：Vanilla JS SPA + CSS。
- 认证：JWT + bcrypt。
- LLM 接入：OpenAI-compatible API。
- 文档处理：python-docx、mammoth。

### 快速启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start.sh
```

默认端口为 17957。

### 目录说明

```text
src/main.py                 FastAPI 入口与静态站点挂载
src/app/routers/            API 路由层
src/app/services/           应用服务、SkillRunner、LLM 适配
src/app/repositories/       数据访问层
src/app/storage/            文档与运行时文件存储
src/app/log_writers/        审计、前端、LLM 会话日志
src/static/                 前端 SPA
skills/                     需求评审技能链
runtime/                    数据库、上传、转换、结果、日志
tests/                      自动化测试
```

### 数据与代码分离

所有数据库、上传文件、转换结果、日志和评审产物都写入 runtime 目录。该目录默认不纳入 git，便于：

- 避免运行时数据进入源码仓库。
- 在部署时独立挂载数据卷。
- 在开源或跨环境迁移时保护业务数据。

### License

Apache License 2.0。详见 [LICENSE](LICENSE)。

<a id="english"></a>

## English

An intranet-deployable PRD review workflow platform built for team collaboration. The system is designed around end-to-end requirement review rather than isolated chat sessions, covering document intake, decomposition, per-document analysis, system-level review, and report generation in one traceable pipeline.

### Architecture

The current codebase follows a four-layer design:

- Access layer: FastAPI exposes authentication, chat, upload, history, admin, and review APIs, while a vanilla JavaScript SPA provides the unified UI.
- Application orchestration layer: services and review pipeline orchestration handle model selection, context assembly, task tracking, and report persistence.
- Domain and persistence layer: repositories, storage modules, and log writers separate database access, file storage, and audit logging responsibilities.
- AI workflow layer: SkillRunner orchestrates six specialized skills in a Skill-as-a-Service pipeline.

```mermaid
flowchart LR
		U[Reviewer] --> SPA[Frontend SPA]
		A[Admin] --> SPA
		SPA --> API[FastAPI routes]
		API --> APP[Application services]
		APP --> REPO[Repository layer]
		APP --> STORE[Storage layer]
		APP --> LOG[Audit and session logs]
		APP --> RUNNER[SkillRunner]
		RUNNER --> SKILLS[6 review skills]
		REPO --> DB[(SQLite)]
		STORE --> RT[runtime/data]
		LOG --> RL[runtime/logs]
		SKILLS --> RR[runtime/results]
```

### Requirement Review Workflow

The workflow is the core of the product. It is designed to support structured requirement review from raw input to final deliverables:

1. Document intake: users upload DOCX files into a review project; the original file and converted Markdown are stored under runtime.
2. Project-based organization: documents, context, prompts, tasks, and reports are managed per review project.
3. Overview classification: the prd-overview-classify skill prepares document categorization and version-chain clues.
4. Per-document analysis: the prd-per-analysis skill produces structured, persistable analysis results for each requirement document.
5. System-level review: the system-review skill synthesizes cross-document findings across business value, architecture, competition, product strategy, tech evolution, PM assessment, and action plan dimensions.
6. Insights and reporting: requirement-insights and report-generator produce gap analysis, evolution insights, review reports, and PRD draft outputs.

Supported review modes:

- `quick`: fast single-document review.
- `review`: standard requirement review pipeline.
- `pm`: PM-oriented assessment mode.
- `insight`: standard review plus evolution and gap insights.
- `full`: complete workflow.
- `draft`: generate a PRD draft from review outputs.

### Feature Highlights

- Project-centric review management for documents, context versions, tasks, and reports.
- OpenAI-compatible multi-model integration with encrypted API key storage and configurable thinking settings.
- Traceable workflow execution with task status, step details, persisted outputs, and runtime logs.
- Separate management for general prompts and review-specific prompts.
- Streaming progress for long-running AI review tasks.
- Deployment-friendly runtime isolation using SQLite and a dedicated runtime directory.

### Admin Console

The admin console focuses on operational control of the workflow:

- User management for creating, disabling, and deleting user or admin accounts.
- Model management for ordering, enabling, configuring API keys, testing connectivity, measuring latency, and tuning thinking-related settings.
- Prompt management for general prompts and review prompts.
- Skill management for skill metadata such as update URLs.
- System stats and recent access records for lightweight operations and troubleshooting.

### Tech Stack

- Backend: FastAPI, SQLAlchemy Async, SQLite.
- Frontend: Vanilla JS SPA + CSS.
- Authentication: JWT + bcrypt.
- LLM integration: OpenAI-compatible APIs.
- Document processing: python-docx, mammoth.

### Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start.sh
```

The default server port is 17957.

### Project Map

```text
src/main.py                 FastAPI entry point and static site mount
src/app/routers/            API routes
src/app/services/           Application services, SkillRunner, LLM integration
src/app/repositories/       Persistence layer
src/app/storage/            Runtime file storage
src/app/log_writers/        Audit, frontend, and LLM session logs
src/static/                 Frontend SPA
skills/                     Review skill chain
runtime/                    Database, uploads, conversions, results, logs
tests/                      Automated tests
```

### Data and Code Separation

All databases, uploads, converted files, logs, and review artifacts live under the runtime directory, which is git-ignored by default. This keeps runtime data out of source control, simplifies deployment with mounted data volumes, and reduces the risk of leaking business data across environments.

### License

Apache License 2.0. See [LICENSE](LICENSE) for details.