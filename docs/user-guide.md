# 用户使用手册 / User Guide

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

<a id="中文"></a>

## 中文

本手册面向**普通用户**(非管理员),介绍如何使用「需求评审工作流平台」的全部功能。平台为部门内网部署,核心能力是:上传 Word 需求文档(DOCX) → AI 自动评审 → 生成结构化报告与 PRD 草稿。你可以把它理解为一个"会读需求文档、会评审、还能帮你写下一版 PRD 的 AI 同事"。

> 如果你需要参与**多轮协作审查**(发起审批、Reviewer/Approver 流转、产物确认),请参阅 [协作评审手册](collaboration-review.md),本手册不展开。

---

### 目录

1. [快速上手](#1-快速上手)
2. [需求评审工作流(核心)](#2-需求评审工作流核心)
3. [消费评审结果](#3-消费评审结果)
4. [知识库](#4-知识库)
5. [Agent 对话](#5-agent-对话)
6. [账号管理](#6-账号管理)
7. [常见问题](#7-常见问题)

---

### 1. 快速上手

登录后,你会看到几个主要功能区:

- **需求评审**:上传文档、运行 AI 评审、查看报告的主战场。
- **知识库**:管理团队共享资料和个人私有资料。
- **Agent 对话**:与 AI Agent 自主对话,处理灵活任务。
- **账号设置**:修改个人密码。

整个平台围绕"**项目**"组织工作:每次评审都以一个项目为单位,管理你上传的文档、评审上下文、任务记录和生成的报告。

---

### 2. 需求评审工作流(核心)

这是平台最重要的能力,也是本手册的重点。整个流程可以概括为五步:**创建评审项目 → 上传 DOCX → 选择要评审的文档 → 选择评审模式 → 运行并查看报告**。

#### 2.1 创建评审项目

1. 进入"需求评审"页面,点击"新建项目"。
2. 填写项目名称(例如"智能联动需求集 V3")。
3. (可选)填写项目说明、评审背景,这些上下文会被 AI 用到。
4. 创建后进入项目详情页。

> **为什么用项目?** 一次评审往往涉及多篇文档、多次迭代。用项目组织,你的文档、上下文版本、任务记录和报告都会被管理起来,后续迭代能复用历史结果。

#### 2.2 上传文档

1. 在项目内点击"上传文档"。
2. 选择 `.docx` 格式的 Word 文档。
3. **限制**:仅支持 `.docx` 格式,单文件最大 **50MB**。
4. 上传后系统会自动把 Word 转成 Markdown(含图片提取、嵌入 Excel 转表格),为后续评审做准备。

可以一次上传多篇文档,也可以分批补充。

#### 2.3 选择要评审的文档

- 大多数模式(快速审查、需求深度分析等)针对**单篇文档**,你需要先选中一篇文档。
- **批量整体评估**(`full`)模式会自动覆盖项目内的**全部文档**,无需单独选中。

#### 2.4 选择评审模式(重点)

平台提供 **6 种评审模式**,每种回答不同的问题。先想清楚你要解决什么,再选模式:

| 模式 | 前端标签 | 它回答的问题 | 触发的 Skills | 预计耗时 |
|------|---------|-------------|--------------|---------|
| `quick` | 快速审查 | 这篇需求有什么问题? | 预处理 → 分类 → 逐篇分析 | ~120 秒 |
| `review` | 需求深度分析 | 需求集的体系性如何? | 预处理 → 分类 → 逐篇分析 → 体系Review → 报告生成 | ~300 秒 |
| `pm` | PM发展建议 | PM 的能力如何提升? | 预处理 → 分类 → 逐篇分析 → 体系Review → 报告生成 | ~240 秒 |
| `insight` | 挖掘下一阶段需求 | 下一步该写什么需求? | 预处理 → 分类 → 逐篇分析 → 体系Review → 需求洞察 → 报告生成 | ~480 秒 |
| `full` | 批量整体评估 | 全貌如何? | 预处理 → 分类 → 逐篇分析 → 体系Review → 需求洞察 → 报告生成 | ~600 秒 |
| `draft` | 基于历史生成PRD | 最高优先级的缺口怎么写? | 预处理 → 分类 → 逐篇分析 → 体系Review → 需求洞察 → PRD草稿生成 → 报告生成 | ~300 秒 |

**怎么选?** 简单决策建议:

- 只想快速看一篇文档的问题 → **快速审查**(`quick`)
- 想做一次正经的需求评审 → **需求深度分析**(`review`)
- 想评估产品经理的写作/思考能力 → **PM发展建议**(`pm`)
- 想知道接下来该补什么需求 → **挖掘下一阶段需求**(`insight`)
- 想看整个需求集的全貌 → **批量整体评估**(`full`)
- 想直接生成下一版 PRD 草稿 → **基于历史生成PRD**(`draft`)

#### 2.5 6 种模式详细说明

##### 快速审查 (quick)

最轻量的模式。只对单篇文档做"核心问题、分类、边界、边界外问题、解决追踪、要点提取"6 个维度的逐篇分析,并给出质量评分。适合快速判断一篇需求文档写得怎么样,大约 2 分钟出结果。

##### 需求深度分析 (review)

在快速审查基础上,增加**体系 Review**:从 7 个维度(业务价值、架构、竞争、产品策略、技术演进、PM 评估、行动计划)对需求集做系统性评审,并生成完整报告。这是最常用的"正式评审"模式。

##### PM 发展建议 (pm)

聚焦**产品经理能力评估**。同样会跑逐篇分析和体系 Review,但报告重点输出 PM 评分卡和发展建议,帮助 PM 看清自己写需求时的问题和提升方向。

##### 挖掘下一阶段需求 (insight)

在体系 Review 基础上,进一步做**需求洞察**:追踪边界外问题在各版本间是否被收敛,构建功能覆盖矩阵找出缺口,给出"下一步该写什么"的方向建议。适合规划下一阶段需求时使用。

##### 批量整体评估 (full)

对项目内**全部文档**跑完整链路(逐篇分析 + 体系 Review + 需求洞察 + 报告),给出整个需求集的全貌。耗时最长(约 10 分钟),适合季度盘点、整体盘点这类场景。

##### 基于历史生成 PRD (draft)

跑完整分析链路后,额外执行 **PRD 草稿生成**:找出最高优先级的需求缺口,直接生成一份可参考的 PRD 草稿。适合"我已经评审完了,现在想快速起一个新需求草稿"的场景。

#### 2.6 模式的递进关系与缓存复用(重要)

这是平台一个很省时的设计:**6 种模式是递进的**,而且**已完成的步骤结果会被缓存复用**。

- 模式的递进链路:`quick` < `review`/`pm` < `insight`/`full` < `draft`
- **举例**:你先跑了 `quick`(完成 预处理→分类→逐篇分析),之后再跑 `review`,系统只会执行后续步骤(体系 Review → 报告生成),前面三步直接复用缓存,**不再重复跑**。
- **再举例**:先跑了 `review`,再跑 `draft`,只需补"需求洞察 + PRD 草稿生成"两步。
- 一旦某个 Skill 被触发,它就**执行完整流程**(例如体系 Review 永远跑完整 7 个维度,不会因为是复用而打折扣)。

**实际收益**:按从轻到重的顺序逐步深入,可以显著缩短后续模式的等待时间。

#### 2.7 运行评审

1. 选好文档和模式后,点击"开始评审"。
2. 页面会显示**流式进度**:当前在哪一步(预处理/分类/逐篇分析/体系 Review/...)、整体进度百分比。若模型瞬时失败,页面会弹出 toast 提示正在重试(不写入通知列表),无需刷新。
3. 长任务支持**任务状态追踪**:你可以离开页面,稍后从历史记录里回到这个任务查看结果。
4. 任务完成后,自动跳转到结果页。

> 提示:部分模式耗时较长(批量整体评估约 10 分钟),建议利用缓存复用:先用快速审查跑一遍单篇,再升级到更深模式。

> 注:若管理员禁用了必需 Skill,点击"开始评审"会提示 409 错误(「必需 Skill 已被禁用」),需联系管理员在 Skill 管理中重新启用;若需求洞察 Skill 被禁用,深度分析类模式(`insight`/`full`/`draft`)会自动跳过洞察步骤降级运行,并在任务结果中标注警告(`completed_with_warnings`)。

---

### 3. 消费评审结果

评审跑完后,结果会分几个板块呈现,你可以**查看**和**下载**:

#### 3.1 逐篇分析结果

- **6 维度结构化分析**:核心问题、分类、边界(做什么/不做什么)、边界外问题、解决追踪(后续版本是否解决)、要点提取。
- **质量评分**:对文档质量的量化打分,可落库可追踪。
- 每篇文档都有独立的分析卡片,便于横向对比。

#### 3.2 体系评审

- **7 维度系统视角结论**:业务价值、架构、竞争、产品策略、技术演进、PM 评估、行动计划。
- **PM 评分卡**:对产品经理能力的评分与点评。

#### 3.3 演进洞察

- **演进链 Mermaid 图**:可视化需求跨版本的演进关系。
- **功能覆盖矩阵**:哪些功能被覆盖、哪些是缺口。
- **缺口列表**:明确标出待补的需求缺口。

#### 3.4 报告与 PRD 草稿

- **Markdown / PDF 报告**:结构化评审报告,可下载存档。在线查看时支持 Mermaid 图、KaTeX 数学公式(含 `\ce{}` 化学式)以及隔离式 SVG 预览(可切换源码/图形;含脚本等危险内容的 SVG 会被拒绝)。
- **PRD 草稿**:基于最高优先级缺口生成的 PRD 草稿(由 `draft` 模式产出),可作为新需求的起点。

所有结果都支持查看、下载,并保留任务状态与运行历史,方便复盘和追溯。

---

### 4. 知识库

知识库用于沉淀团队和个人的文档资料,既能在评审中被引用,也能被 Agent 对话检索。

#### 4.1 团队空间 (Team)

- **共享协作**:团队成员共享上传、检索、下载资料。
- **角色权限**:四层角色,权限从高到低为 **owner(拥有者) → admin(管理员) → member(成员) → viewer(只读)**,不同角色能做的操作不同(如上传、管理、仅查看)。
- 项目可引用团队资料,引用时会自动冻结一个版本快照,保证可追溯。

#### 4.2 个人空间 (Mine)

- 存放**个人私有资料**,只有你自己可见。
- 页面顶部可在 **Team / Mine** 之间切换。

#### 4.3 检索机制

- 上传资料后,系统会在后台**异步向量化**(由 Embedding Worker 处理),支持**向量检索**。
- 个人空间额外提供 **FTS(全文检索)兜底**,确保即使向量化未完成也能检索到内容。

---

### 5. Agent 对话

当评审模式满足不了灵活需求时,可以使用 Agent 对话。

- **发起自主对话**:基于 Pi Agent,你可以让 AI 自主调用工具完成多步骤任务(例如"帮我对比这两篇需求文档的差异并总结风险")。
- **@文档定向注入**:在对话中可以使用 **@文档** 引用特定文档,把它的内容作为上下文注入,让回答更有针对性。
- **运行历史**:每次 Agent 对话都会记录运行历史(目标、步骤、工具调用、状态),便于回看和复盘。

> 说明:Agent 的可用工具受管理员配置的授权范围限制,高风险操作可能需要人工审批,这是平台的安全设计,正常使用不受影响。

---

### 6. 账号管理

#### 修改密码

1. 进入"账号设置"或个人中心。
2. 输入当前密码和新密码。
3. 提交后密码立即生效(对应接口 `PUT /api/auth/password`)。

---

### 7. 常见问题

**Q:上传文档支持哪些格式?支持多大?**
A:仅支持 `.docx`,单文件最大 50MB。PDF、TXT 等其他格式需要先转成 DOCX。

**Q:为什么我跑了快速审查,再跑需求深度分析,等待时间很短?**
A:因为模式是递进的,前面的步骤(预处理、分类、逐篇分析)结果会被缓存复用,系统只执行新增步骤。详见 [2.6 节](#26-模式的递进关系与缓存复用重要)。

**Q:批量整体评估和需求深度分析有什么区别?**
A:`review` 针对单篇或少量文档做深度分析;`full` 自动覆盖项目内全部文档,跑完整链路(含需求洞察),给出全貌。

**Q:生成的 PRD 草稿可以直接用吗?**
A:草稿基于历史分析生成,质量较高但仍建议作为**起点**进行人工修订,确认边界、参数和优先级后再正式使用。

**Q:评审结果会丢失吗?**
A:不会。所有结果都会落库并保留任务状态与历史,你可以随时回到任务记录查看和下载。

**Q:团队空间和个人空间的资料别人能看到吗?**
A:团队空间按角色权限共享;个人空间仅你可见。

**Q:对话或报告里的公式、化学式、SVG 会渲染吗?**
A:会。`$$…$$`、`\[…\]`、`\(...\)` 用 KaTeX 渲染,`\ce{}` 化学式同样支持;单个 `$` 不会当公式,以免金额被误伤。SVG 代码块会隔离预览,可切换查看源码;恶意 SVG 会被拒绝。

---

<a id="english"></a>

## English

This guide is for **regular users** (not administrators). It covers how to use every feature of the Requirement Review Workflow Platform. The platform is deployed on the department intranet. Its core capability is: upload Word requirement documents (DOCX) → AI auto-review → generate structured reports and PRD drafts. Think of it as an "AI colleague that can read requirement documents, review them, and even help you write the next PRD."

> If you need to participate in **multi-round collaborative review** (initiating approvals, Reviewer/Approver flows, artifact confirmation), please refer to the [Collaborative Review Guide](collaboration-review.md). This guide does not cover that flow.

---

### Contents

1. [Quick Start](#1-quick-start)
2. [Requirement Review Workflow (Core)](#2-requirement-review-workflow-core)
3. [Consuming Review Results](#3-consuming-review-results)
4. [Knowledge Base](#4-knowledge-base)
5. [Agent Chat](#5-agent-chat)
6. [Account Management](#6-account-management)
7. [FAQ](#7-faq)

---

### 1. Quick Start

After logging in, you will see several main areas:

- **Requirement Review**: The main workspace for uploading documents, running AI reviews, and viewing reports.
- **Knowledge Base**: Manage team-shared and personal materials.
- **Agent Chat**: Have autonomous conversations with an AI Agent for flexible tasks.
- **Account Settings**: Change your personal password.

The whole platform is organized around "**projects**": each review is managed as a project that holds your uploaded documents, review context, task records, and generated reports.

---

### 2. Requirement Review Workflow (Core)

This is the most important capability of the platform and the focus of this guide. The flow has five steps: **Create a review project → Upload DOCX → Select the document(s) to review → Choose a review mode → Run and view the report**.

#### 2.1 Create a Review Project

1. Go to the "Requirement Review" page and click "New Project."
2. Enter a project name (e.g., "Smart Linkage Requirements V3").
3. (Optional) Fill in the project description and review background — this context will be used by the AI.
4. After creation, you enter the project detail page.

> **Why projects?** A single review often involves multiple documents and iterations. Organizing by project keeps your documents, context versions, task records, and reports together, so later iterations can reuse previous results.

#### 2.2 Upload Documents

1. Click "Upload Document" inside the project.
2. Select a Word document in `.docx` format.
3. **Limits**: Only `.docx` is supported, with a maximum file size of **50MB** per file.
4. After upload, the system automatically converts Word to Markdown (including image extraction and embedded Excel → table conversion) to prepare for review.

You can upload multiple documents at once or add them in batches.

#### 2.3 Select the Document(s) to Review

- Most modes (Quick Review, Deep Analysis, etc.) target a **single document** — you need to select one first.
- **Batch Overall Assessment** (`full`) automatically covers **all documents** in the project, so no single selection is needed.

#### 2.4 Choose a Review Mode (Key Step)

The platform offers **6 review modes**, each answering a different question. Decide what you want to solve first, then pick a mode:

| Mode | UI Label | Question It Answers | Skills Triggered | Est. Time |
|------|----------|---------------------|------------------|-----------|
| `quick` | Quick Review | What's wrong with this requirement? | Preprocess → Classify → Per-analysis | ~120s |
| `review` | Deep Analysis | How systematic is the requirement set? | Preprocess → Classify → Per-analysis → System Review → Report | ~300s |
| `pm` | PM Development | How can the PM improve? | Preprocess → Classify → Per-analysis → System Review → Report | ~240s |
| `insight` | Next-Stage Requirements | What should we write next? | Preprocess → Classify → Per-analysis → System Review → Insights → Report | ~480s |
| `full` | Batch Overall Assessment | What's the big picture? | Preprocess → Classify → Per-analysis → System Review → Insights → Report | ~600s |
| `draft` | Generate PRD from History | How to fill the top-priority gap? | Preprocess → Classify → Per-analysis → System Review → Insights → PRD Draft → Report | ~300s |

**How to choose?** Quick guide:

- Just want a quick check of one document → **Quick Review** (`quick`)
- Want a proper requirement review → **Deep Analysis** (`review`)
- Want to evaluate the PM's writing/thinking → **PM Development** (`pm`)
- Want to know what to build next → **Next-Stage Requirements** (`insight`)
- Want the full picture of the whole set → **Batch Overall Assessment** (`full`)
- Want to directly generate a next PRD draft → **Generate PRD from History** (`draft`)

#### 2.5 The 6 Modes in Detail

##### Quick Review (quick)

The lightest mode. It performs a per-document analysis across 6 dimensions (core problem, category, boundary, boundary-external issues, resolution tracking, key points) and gives a quality score. Good for a fast judgment of how a requirement document is written. Results in about 2 minutes.

##### Deep Analysis (review)

Builds on Quick Review by adding a **System Review**: a systematic assessment across 7 dimensions (business value, architecture, competition, product strategy, tech evolution, PM assessment, action plan), with a full report. This is the most common "formal review" mode.

##### PM Development (pm)

Focuses on **product-manager capability assessment**. Also runs per-analysis and System Review, but the report emphasizes a PM scorecard and development suggestions, helping PMs see the problems in their requirements and how to improve.

##### Next-Stage Requirements (insight)

Builds on System Review with **requirement insights**: tracks whether boundary-external issues are resolved across versions, builds a feature coverage matrix to find gaps, and suggests "what to write next." Useful when planning the next phase.

##### Batch Overall Assessment (full)

Runs the full pipeline (per-analysis + System Review + insights + report) across **all documents** in the project, giving the big picture of the whole requirement set. The longest mode (about 10 minutes), suited for quarterly or overall inventories.

##### Generate PRD from History (draft)

After running the full analysis pipeline, it additionally runs **PRD draft generation**: finds the highest-priority requirement gap and produces a reference PRD draft. Good for "I've finished the review, now I want to start a new requirement draft quickly."

#### 2.6 Mode Progression and Cache Reuse (Important)

The platform has a time-saving design: **the 6 modes are progressive**, and **results of completed steps are cached and reused**.

- The progression chain: `quick` < `review`/`pm` < `insight`/`full` < `draft`
- **Example**: If you first run `quick` (completing preprocess → classify → per-analysis) and then run `review`, the system only executes the later steps (System Review → report). The first three steps are reused from cache and **not run again**.
- **Another example**: After running `review`, running `draft` only adds "insights + PRD draft generation."
- Once a Skill is triggered, it **runs the complete flow** (e.g., System Review always runs all 7 dimensions — reuse never means a watered-down result).

**Practical benefit**: Going from light to heavy modes progressively can significantly shorten the wait for subsequent modes.

#### 2.7 Run a Review

1. After selecting the document(s) and mode, click "Start Review."
2. The page shows **streaming progress**: the current step (preprocess / classify / per-analysis / System Review / ...) and overall percentage. If the model fails transiently, an in-page toast says it is retrying (not stored in the notification inbox); no refresh needed.
3. Long tasks support **task status tracking**: you can leave the page and come back to the task later from the history.
4. When done, it auto-navigates to the results page.

> Tip: Some modes take a while (Batch Overall Assessment is about 10 minutes). Take advantage of cache reuse: run Quick Review on a single document first, then upgrade to a deeper mode.

> Note: If an admin has disabled a required skill, clicking "Start Review" fails with a 409 error ("required skill disabled") — contact your admin to re-enable it in Skill Management. If the requirement-insights skill is disabled, deep-analysis modes (`insight`/`full`/`draft`) automatically skip the insights step and run degraded, with a warning flagged in the task results (`completed_with_warnings`).

---

### 3. Consuming Review Results

After a review completes, results are presented in several sections, all of which you can **view** and **download**:

#### 3.1 Per-Document Analysis

- **6-dimension structured analysis**: core problem, category, boundary (what it does / doesn't do), boundary-external issues, resolution tracking (resolved in later versions?), key points.
- **Quality score**: a quantitative score for document quality, persistable and traceable.
- Each document has its own analysis card for easy comparison.

#### 3.2 System Review

- **7-dimension system-level conclusions**: business value, architecture, competition, product strategy, tech evolution, PM assessment, action plan.
- **PM scorecard**: scores and comments on the product manager's capabilities.

#### 3.3 Evolution Insights

- **Evolution-chain Mermaid diagram**: visualizes how requirements evolve across versions.
- **Feature coverage matrix**: which features are covered and which are gaps.
- **Gap list**: clearly marks the requirement gaps to fill.

#### 3.4 Reports and PRD Drafts

- **Markdown / PDF reports**: structured review reports, downloadable for archiving. Online viewing renders Mermaid diagrams, KaTeX math (including `\ce{}` chemistry), and sandboxed SVG previews (source/graphic toggle; SVGs with scripts or other dangerous content are rejected).
- **PRD draft**: generated from the highest-priority gap (produced by `draft` mode), usable as a starting point for a new requirement.

All results support viewing and downloading, and retain task status and run history for easy review and traceability.

---

### 4. Knowledge Base

The knowledge base stores team and personal materials. It can be referenced during reviews and retrieved by Agent chat.

#### 4.1 Team Space (Team)

- **Shared collaboration**: team members share uploading, retrieval, and downloading of materials.
- **Role permissions**: four roles, from highest to lowest — **owner → admin → member → viewer** — with different allowed actions (e.g., upload, manage, view-only).
- Projects can reference team materials; a version snapshot is automatically frozen at reference time for traceability.

#### 4.2 Personal Space (Mine)

- Stores **personal private materials**, visible only to you.
- A toggle at the top lets you switch between **Team / Mine**.

#### 4.3 Retrieval

- After upload, the system **asynchronously vectorizes** materials in the background (via the Embedding Worker), enabling **vector retrieval**.
- The personal space additionally provides an **FTS (full-text search) fallback**, ensuring content is retrievable even before vectorization completes.

---

### 5. Agent Chat

When review modes can't meet a flexible need, use Agent chat.

- **Start an autonomous conversation**: based on Pi Agent, you can let the AI autonomously call tools to complete multi-step tasks (e.g., "Compare these two requirement documents and summarize the risks").
- **@document targeted injection**: in a conversation, you can use **@document** to reference a specific document and inject its content as context, making answers more targeted.
- **Run history**: every Agent conversation is recorded (goal, steps, tool calls, status) for easy review.

> Note: the Agent's available tools are limited by the administrator-configured authorization scope, and high-risk operations may require manual approval. This is a platform security design and does not affect normal use.

---

### 6. Account Management

#### Change Password

1. Go to "Account Settings" or your profile.
2. Enter your current password and a new password.
3. Submit, and the new password takes effect immediately (endpoint: `PUT /api/auth/password`).

---

### 7. FAQ

**Q: What formats are supported for upload, and how large?**
A: Only `.docx`, up to 50MB per file. Other formats (PDF, TXT, etc.) must be converted to DOCX first.

**Q: Why does running Deep Analysis after Quick Review take so little time?**
A: Because modes are progressive: earlier steps (preprocess, classify, per-analysis) are cached and reused, so the system only runs the new steps. See [Section 2.6](#26-mode-progression-and-cache-reuse-important).

**Q: What's the difference between Batch Overall Assessment and Deep Analysis?**
A: `review` does deep analysis on a single or few documents; `full` automatically covers all documents in the project and runs the full pipeline (including insights) for the big picture.

**Q: Can I use the generated PRD draft directly?**
A: The draft is generated from historical analysis and is high quality, but we recommend using it as a **starting point** and revising it manually — confirm boundaries, parameters, and priorities before formal use.

**Q: Will review results be lost?**
A: No. All results are persisted with task status and history; you can return to the task records anytime to view and download them.

**Q: Can others see materials in the team space vs. personal space?**
A: Team-space materials are shared by role permission; personal-space materials are visible only to you.

**Q: Are formulas, chemistry, and SVG rendered in chat and reports?**
A: Yes. `$$…$$`, `\[…\]`, and `\(...\)` are rendered with KaTeX, including `\ce{}` chemistry. A single `$` is not treated as math, so currency amounts are not mangled. SVG code blocks get a sandboxed preview with a source/graphic toggle; malicious SVGs are rejected.
