# Skill-as-a-Service：局域网内人机协同工具开发范式

> 版本：V1.1
> 日期：2026年5月19日
> 基于：需求评审与文档审查类工具实践总结

---

## 一、定位与背景

部门内部有一类工具需求，特点是：

- 业务流程相对固定，例如需求审查、文档转换、资料归档、报告生成；
- 流程中包含 LLM 判断环节，例如分类、缺口分析、体系化 Review、PRD 草稿生成；
- 使用者既可能是人，通过 Web UI 操作，也可能是 Agent，通过 API 调用；
- 工具部署在局域网内，业务数据、文件、运行日志和用户权限需要本地可控；
- LLM 后端需要可替换，可使用外部 API，也应保留未来接入内网模型服务的能力。

传统方案有两个极端：

| 方案 | 优点 | 问题 |
|------|------|------|
| 全部硬编码到后端 | 稳定、可控、易部署 | Prompt、步骤、输出结构难复用，需求变化时改动成本高 |
| 全部交给 Agent 自主执行 | 灵活、适合开放式问题 | 确定性差，难做权限、审计、重试、进度和结果契约 |

本项目沉淀出的范式是：

> 把可复用能力封装成 Skills，把稳定流程固化到 Skill Runner，把开放式任务留给未来的 Pi Agent。人和 Agent 共用同一套服务接口、权限边界和能力池。

---

## 二、核心架构

```
┌─────────────────────────────────────────────────────┐
│                    用户（人 / Agent）                │
│                   UI 操作 / API 调用                 │
└──────────────┬──────────────────────┬────────────────┘
               │                      │
        固定工作流路径           自主编排路径（规划中）
               │                      │
       ┌───────▼───────┐      ┌──────▼──────┐
       │  Skill Runner │      │  Pi Agent   │
       │ 确定性编排适配器 │      │ 自主规划执行层 │
       └───────┬───────┘      └──────┬──────┘
               │                      │
               └──────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │      Skills 工具池     │
              │ 独立开发、独立测试、    │
              │ 通过文件格式契约耦合    │
              └───────────────────────┘
```

### 2.1 三层分工

| 层 | 负责什么 | 不负责什么 | 当前状态 |
|---|----------|------------|----------|
| **Skills** | 单一能力封装：`SKILL.md`、Prompt、脚本、输出 Schema、参考资料 | 不绑定具体 Web 服务，不直接依赖流水线上下文 | 已落地 |
| **Skill Runner** | 确定性编排：加载 Prompt、组装输入、调用 LLM、校验 Schema、修复输出、重试、上下文注入、上下文裁剪、产出状态事件 | 不做开放式规划，不自己决定下一步业务目标 | 已落地 |
| **Pi Agent** | 自主编排：理解用户意图、选择 Skills、决定顺序、必要时追问、动态调整 | 不替代成熟固定流程 | 规划中 |

需要注意：Runner 不是“不做判断”，而是**不做开放式规划**。它仍然需要做工程性判断，例如选择模式对应步骤、截断上下文、修复 Schema、处理重试、合并结果。

### 2.2 确定性边界

当一个工作流满足以下条件时，应交给 Skill Runner：

- 步骤序列已经稳定；
- 输入输出字段已经收敛；
- 失败重试策略明确；
- 进度、状态和报告需要稳定展示；
- 用户希望“一键执行”，而不是每次重新规划。

当任务具备以下特征时，更适合交给 Pi Agent：

- 用户问题是开放式的；
- 步骤顺序不能提前确定；
- 需要先判断是否检索历史、是否对比版本、是否追问用户；
- 需要从多个 Skills 中动态组合能力；
- 结果更像“分析建议”，而不是固定报告。

---

## 三、Skill 的开发契约

每个 Skill 是一个可独立运行、可独立测试、可被人和 Agent 理解的能力包。

```
skills/<name>/
├── SKILL.md           # 能力声明，给 Agent 读
├── prompts/           # Prompt 模板，给 LLM 读
├── scripts/           # 可执行脚本，给系统调
├── templates/         # 输出 Schema 或配置模板，给 Runner 校验
├── references/        # 参考说明，给人读
└── requirements.txt   # Skill 自身依赖
```

### 3.1 硬约束

| # | 约束 | 原因 |
|---|------|------|
| 1 | 独立可运行，不 import 其他 Skill 的业务代码 | 降低耦合，便于单独测试和迁移 |
| 2 | 通过文件格式契约串联，上游输出必须能成为下游输入 | 让 Runner 可以稳定编排 |
| 3 | Skill 不绑定项目上下文，项目上下文由 Runner 注入 | 保持 Skill 通用性 |
| 4 | Prompt 中的业务约束要显式，不依赖隐式代码逻辑 | 便于审查和迭代 |
| 5 | 输出尽量结构化，优先 JSON Schema，再补 Markdown 报告 | 便于 UI 展示、测试和二次加工 |
| 6 | 失败要可诊断，脚本输出和异常信息使用中文 | 团队排查成本更低 |

### 3.2 语言规范

| 部分 | 语言 | 原因 |
|------|------|------|
| `SKILL.md` | 英文 | 给 Agent 看，触发更稳定 |
| Prompts | 中文 | 面向中文业务场景，表达更准确 |
| Scripts 输出 | 中文 | 团队阅读友好 |
| Scripts 代码、变量名、注释 | 英文 | 代码规范稳定 |
| JSON/YAML key | 英文 | key 是程序接口 |
| JSON/YAML value | 中文或业务原文 | value 是业务语义 |

---

## 四、Runner 的运行时契约

Skill Runner 是本范式的工程核心。它把“LLM 能力”变成“可治理的工程步骤”。

### 4.1 输入契约

Runner 接收的输入应包括：

- `mode`：执行模式，例如 `quick`、`review`、`pm`、`insight`、`full`、`draft`；
- `docs`：本次处理的文档列表，包含 `doc_id`、`filename`、`md_content`、`category`、`version` 等字段；
- `context`：项目级 ReviewContext，例如分类覆盖、必需章节、评分量规、业务规范、专业指导意见；
- `model_cfg`：模型配置，例如 `api_base`、`api_key`、`llm_model`、`max_tokens`；
- `historical_docs`：可选，draft 模式下用于 PRD 草稿生成的历史文档上下文。

### 4.2 输出契约

Runner 每一步输出应统一成类似 `SkillStepResult` 的结构：

| 字段 | 含义 |
|------|------|
| `status` | `success`、`partial`、`error` |
| `data` | 结构化 JSON 输出 |
| `markdown` | 可选，报告类 Markdown 输出 |
| `diagnostics` | Schema 错误、修复记录、重试信息 |
| `artifacts` | 可选，图表、文件路径、覆盖矩阵等副产物 |
| `schema_valid` | Schema 校验是否原始通过 |

### 4.3 状态契约

流水线状态应集中保存在 `PipelineState` 中，避免散落在多个临时变量里：

| 状态字段 | 用途 |
|----------|------|
| `docs` | 文档及其 Markdown 内容 |
| `classify` | 分类、版本链、依赖关系 |
| `analyses` | 逐篇分析结果 |
| `review_dimensions` | 体系 Review 各维度结果 |
| `insights` | 演进追踪、功能提取、缺口分析 |
| `report` | 最终报告或草稿 |
| `extra` | 模式特有扩展，例如 historical_docs、prd_draft |

### 4.4 事件契约

面向 UI 和 Agent 的进度输出应使用统一事件模型：

| 事件 | 用途 |
|------|------|
| `pipeline_start` | 流水线开始 |
| `step_start` | 单步开始 |
| `step_update` | 单步进度、重试、部分结果 |
| `step_end` | 单步结束 |
| `pipeline_end` | 流水线完成或失败 |

当前 Web 应用通过 REST 启动任务，通过 SSE 订阅进度。后续 Agent 调用也应复用同一套事件语义。

### 4.5 上下文治理

Runner 必须负责上下文治理，而不是把所有文档原文直接塞给 LLM：

- 去除 base64 图片等高噪声内容；
- 根据步骤裁剪上下文，例如分类只需要标题和摘要，逐篇分析需要正文，体系 Review 需要摘要；
- 将 ReviewContext 显式注入 system prompt；
- 对历史文档做截断和摘要，避免 draft 模式上下文失控；
- 保留 `diagnostics`，让失败原因可追踪。

---

## 五、服务层统一接入

人和 Agent 应共用同一个 API 入口、同一个权限系统、同一个任务状态模型。

```
人操作 ──→ UI (SPA) ──→ REST API + SSE ──→ Runner / Pi
Agent  ──────────────→ REST API + SSE ──→ Runner / Pi
```

### 5.1 技术栈选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 后端 | FastAPI + SQLite | 轻量、异步、单机零运维 |
| 前端 | 原生 SPA | 无构建依赖，适合局域网快速部署 |
| 通信 | REST + SSE | REST 管理资源和任务，SSE 输出进度 |
| 部署 | macOS launchd | 开机自启，便于内网工具常驻 |
| LLM | OpenAI-compatible adapter | 通过配置接入任意兼容模型，示例：DeepSeek、Qwen、GLM 或未来内网模型 |

### 5.2 API 边界

API 设计应区分资源、任务和结果：

| 类别 | 示例 | 说明 |
|------|------|------|
| 资源 API | 项目、文档、上下文、模型配置 | 管理输入材料和运行配置 |
| 任务 API | 创建审查任务、取消任务、查询任务状态 | 异步执行入口 |
| 结果 API | 获取逐篇分析、体系 Review、报告、Markdown 导出 | 稳定输出契约 |
| 事件 API | SSE 进度订阅 | UI 和 Agent 都可消费 |

关键原则：

- URL 中的 `project_id` 必须和任务、文档、结果的真实归属一致；
- Agent 调用不应绕过认证、权限和审计；
- UI 内部接口如果未来要给 Agent 使用，需要明确稳定性等级；
- 任务 ID 是异步执行句柄，不能把长任务绑定在一次 HTTP 请求里。

---

## 六、实践映射：需求审查平台

### 6.1 已落地能力

当前项目已经落地：

- 文档上传、DOCX 转 Markdown；
- 需求审查项目管理；
- ReviewContext 管理和 Prompt 注入；
- 需求文档分类、版本链识别；
- 逐篇 9 维度分析；
- 体系化 7 维度 Review；
- PM 发展建议；
- 需求洞察；
- 基于历史文档生成 PRD 草稿；
- 报告生成、Markdown 导出；
- REST + SSE 的异步任务接口；
- SkillRunner 的 Prompt 加载、Schema 校验、重试、上下文裁剪。

### 6.2 实际流水线

```
Step 1: 文档预处理
    docx-to-markdown
    ↓
Step 2: 概览与分类
    prd-overview-classify / classify
    prd-overview-classify / version-chain
    ↓
Step 3: 逐篇9维度分析
    prd-per-analysis / per-doc-analysis
    ↓
Step 4: 体系化Review或PM评估
    system-review / business-value
    system-review / architecture
    system-review / competition
    system-review / product-strategy
    system-review / tech-evolution
    system-review / pm-assessment
    system-review / action-plan
    ↓
Step 5: 需求洞察或PRD草稿
    requirement-insights / evolution-match
    requirement-insights / feature-extraction
    requirement-insights / gap-assessment
    或 report-generator / prd_draft
    ↓
Step 6: 报告生成
    report-generator / report-polish
```

### 6.3 模式与编排者

| 场景 | 编排者 | 原因 |
|------|--------|------|
| 单篇快速审查 | Skill Runner | 步骤短、结果固定、可直接返回 |
| Review需求 | Skill Runner | 分类、逐篇分析、体系 Review、报告生成均已稳定 |
| PM发展建议 | Skill Runner | PM 评估维度固定，可复用同一套文档输入 |
| 挖掘下一阶段需求 | Skill Runner | 当前已形成固定洞察子步骤 |
| 基于历史生成 PRD | Skill Runner | 历史文档作为上下文，输出结构固定 |
| “帮我看看这个需求跟历史有没有冲突” | Pi Agent（规划中） | 需要判断检索范围、对比方式和是否追问 |
| “这个 PRD 写得怎么样，给我点建议” | Pi Agent（规划中） | 开放式问题，可能只调用部分 Skills |

---

## 七、安全与治理

局域网工具不等于低安全要求。相反，内网工具通常承载真实业务文档和模型密钥，必须把治理规则写入范式。

### 7.1 认证与权限

- 所有业务 API 默认需要 JWT；
- 管理模型、用户、Prompt 等操作必须要求管理员权限；
- 审查任务、文档、报告必须校验项目归属；
- 普通用户可维护项目上下文，但不能管理全局模型和用户。

### 7.2 密钥治理

- `JWT_SECRET` 必须显式配置，不能默认为空；
- API Key 必须加密存储；
- 加密密钥应从 `JWT_SECRET` 派生；
- 启动脚本应检查关键环境变量；
- 日志中不能输出明文 API Key。

### 7.3 默认账号治理

默认管理员账号只适合本地初始化，不适合长期部署。推荐策略：

- 首次启动要求设置管理员密码；
- 或启动后强制修改默认密码；
- 或检测默认密码存在时在 UI 和日志中给出阻断级告警。

### 7.4 文件治理

- 上传目录按项目隔离；
- 删除项目时同步清理原始文件、转换文件和任务产物；
- 文件名用于展示，存盘名应避免冲突；
- 历史文档和当前需求文档应通过 `document_type` 区分；
- 文档内容进入 LLM 前必须经过裁剪和噪声清理。

---

## 八、测试与质量门槛

Skill-as-a-Service 的质量不只靠人工试用，需要形成分层测试。

| 层级 | 测试重点 |
|------|----------|
| Skill 单测 | Prompt 文件存在、Schema 存在、脚本可独立运行 |
| Runner 单测 | 输入构造、上下文注入、Schema 校验与修复、重试逻辑 |
| API 契约测试 | 请求字段、响应字段、权限、错误码、任务归属 |
| 前端契约测试 | UI 依赖的 API 字段、默认页面、按钮状态、报告 tab |
| 样本文档回归 | 用固定 DOCX 样本验证分类、分析、报告质量 |
| 部署冒烟 | 启动脚本、健康检查、登录、上传、启动任务、SSE 进度 |

建议每新增一个 Skill，至少补齐：

- 1 个最小输入样例；
- 1 个典型输出样例；
- 1 个 Schema 校验用例；
- 1 个 Runner 集成用例。

---

## 九、跨项目复用模板

以后如果要用这套范式开发新的内网工具，可以按以下步骤复制。

### 9.1 判断是否适合

适合：

- 有稳定业务流程；
- 流程中包含 LLM 判断或文档生成；
- 需要 Web UI 和 Agent API 共用；
- 需要保留中间结果、进度、报告和审计；
- 未来可能扩展为多模式工具。

不适合：

- 一次性脚本；
- 纯 CRUD 管理系统；
- 强实时、高并发、强事务系统；
- 没有可复用 Prompt 或 Schema 的临时分析任务。

### 9.2 新项目落地步骤

1. 画出业务流程，区分固定流程和开放式任务；
2. 把固定流程拆成 Skills；
3. 为每个 Skill 定义输入字段、输出 Schema、Prompt 和测试样例；
4. 编写 Runner，把 Skills 串成确定性 pipeline；
5. 设计 `PipelineState`，明确中间结果如何传递；
6. 设计 REST API 和 SSE 事件；
7. 做最小 UI 工作台；
8. 加认证、权限、密钥和文件治理；
9. 用样本文档跑端到端回归；
10. 再评估哪些开放式场景需要 Pi Agent。

### 9.3 最小目录结构

```
project/
├── src/
│   ├── app/
│   │   ├── routers/
│   │   ├── services/
│   │   │   ├── skill_runner.py
│   │   │   ├── skill_prompts.py
│   │   │   ├── skill_schema.py
│   │   │   └── skill_prune.py
│   │   └── models/
│   ├── static/
│   └── config.yaml
├── skills/
│   └── <skill-name>/
├── tests/
├── runtime/
└── docs/
```

---

## 十、从 Runner 到 Pi Agent 的演进路径

当前项目已经完成 Phase 1 和 Phase 2 的主体落地，Phase 3 仍是规划方向。

```
Phase 1: Skills 开发
    每个 Skill 独立开发、独立测试
    ↓
Phase 2: Skill Runner 确定性编排
    固定 pipeline + Schema 校验 + 重试 + 上下文治理 + REST/SSE
    ↓
Phase 3: Pi Agent 自主编排（规划中）
    理解意图 → 动态选择 Skills → 动态调整步骤 → 必要时追问用户
    底层 Skills 和 API 契约尽量复用
```

### 10.1 Pi Agent 不应替代 Runner

Pi Agent 的价值不是把稳定流程重新做一遍，而是覆盖 Runner 不擅长的部分：

- 用户目标不清晰，需要澄清；
- 任务步骤不固定；
- 需要在多个项目、历史文档、上下文之间做动态检索；
- 用户想要的是建议、解释或探索，不是固定报告；
- 需要按中间发现临时改变分析路径。

### 10.2 Pi Agent 接入前置条件

接入 Pi Agent 前，应先补齐：

- Skills 元数据注册表；
- API 权限和审计；
- 稳定的任务事件协议；
- 可被 Agent 调用的资源查询 API；
- 样本文档和 golden output；
- 明确的 Agent 操作边界，例如哪些 API 可读、哪些 API 可写、哪些必须用户确认。

---

## 十一、一句话总结

> Skills 是原子能力，Runner 是确定性管道，Pi Agent 是开放式编排层。先把稳定流程工程化，再把不确定任务交给 Agent；人和 Agent 共用同一套能力池、API、权限和运行时契约。
