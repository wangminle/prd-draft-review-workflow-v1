# 面向需求文档流转的 Cloud Co-worker 全球调研报告

## 执行摘要

从你给出的远期设想和附件资料看，你们真正要做的并不是“再加一个更聪明的聊天框”，而是把当前的需求审查工具，演进成一个**以团队空间为边界、以知识与上下文为底座、以 Agent 对话和审查流程为入口、以消息协作为回路的内部 Cloud co-worker**。这一路线和你们附件中的判断高度一致，而且与当前全球主流产品方向也一致：Notion 已经把产品叙事提升到“24/7 AI team”，并把 Enterprise Search 指向 Slack、Google Drive、GitHub 等多应用检索；Microsoft 365 Copilot 也在用“数据 + 上下文 + 技能/工具”的 Work IQ 统一 Chat、Search 和 Agents。换句话说，你们想做的不是孤立能力，而是一个“工作流中的 AI 同事”。fileciteturn0file0 citeturn28view0turn28view1turn28view2turn28view4

如果只给一个总判断，我的结论是：**方向正确，且不需要推倒重来；最优路径是“业务域先行、平台能力后置、Agent 受限演进、知识与权限先打底”。** 你们附件已经明确现有系统具备 `ReviewProject`、`ReviewContext`、`ReviewTask`、`SkillRunner`、`Conversation`、`Message`、`ContextItem`、`ModelConfig`、Prompt/Skill 管理、审计日志和 `runtime/` 运行时隔离等基座，因此下一步最有价值的不是重做通用平台，而是把这些能力抽象升级为 `Space / Knowledge / Agent / Workflow + Collaboration`。这一路径既吻合你们内部判断，也和 Onyx、AnythingLLM、RAGFlow、LangGraph 这类被验证过的开源形态相匹配。fileciteturn0file0 citeturn43view4turn46view3turn45view2turn36view1turn36view2

本次调研里，**最值得你们重点吸收的不是某一个单体项目，而是一组“组合式参考系”**。产品形态上，最接近你们目标的是 **Onyx + AnythingLLM + Rowboat**：Onyx 强在企业知识连接、RBAC 和审计；AnythingLLM 强在 workspace-first、多用户、Agent、MCP 与资料引用；Rowboat 强在“账号即上下文”的 coworker 心智、长时工作记忆和真实产物生成。知识能力上，**RAGFlow** 对文档解析、切块可视化、可追溯引用最有参考价值。编排能力上，**LangGraph** 最适合后续多阶段、可中断、可恢复、有人在环的审查流程。工具标准上，**MCP + Framelink Figma MCP** 已经把“搜索/数据源/设计稿/外部系统接入”变成了可组合的标准接口。产物层上，**reveal.js / Remotion / Motion Canvas** 已经覆盖了 HTML/SVG 演示稿到视频渲染的成熟链路。citeturn43view4turn46view3turn34view0turn45view2turn36view1turn29view0turn30view2turn33view0turn31view0turn31view1

因此，建议你们短中期优先级固定为三条：**先做团队空间与知识底座，再做受限 Agent 对话与账号 Agent，最后把审查平台升级成“AI 初审 + 人工确认 + 讲解产物 + 评论通知 + 归档沉淀”的协作流程。** 这比先冲“万能 Agent 平台”更稳，也更贴近你们真实业务。fileciteturn0file0

## 业务目标的重新定义

你们的业务主线应该被重新定义为：**围绕需求文档流转的协作式 cowork 平台**，而不是聊天产品、低代码 Agent 平台或独立知识库。附件已经把边界写得很清楚：输入是需求文档、历史版本、业务规则、评审上下文和会议材料；输出不是“答案”本身，而是 AI 初审记录、人工确认记录、HTML/SVG 快速讲解、评审会包和最终归档知识。这个定义非常关键，因为它决定了系统设计要围绕“责任、权限、证据、状态和交付物”展开，而不是围绕“大模型能不能回答更多问题”展开。fileciteturn0file0

沿着这个定义，你们的远期产品其实有四个连续业务回路。第一是**团队空间回路**：团队资料导入、版本化、标签化、显式引用、快照留痕。第二是**Agent 对话回路**：人对团队 Agent、个人 Agent、审查 Agent 发起任务，系统展示检索范围、工具调用、引用依据和待确认动作。第三是**账号与消息回路**：别人可以和“我的账号对应的 Agent”对话，但涉及承诺、回复、评论与决策时，必须回流到我的 Inbox/通知里，让我明确确认。第四是**审查协作回路**：发起审查、AI 初审、发起人采纳/驳回/强行通过、生成讲解产物、通知评审成员、人工评审会、归档为团队知识。这个四环结构，和你们附件里的 `Space / Knowledge / Agent / Workflow + Collaboration` 四大抽象是一一对应的。fileciteturn0file0

这里还有一个术语层面的提醒：你提到的“简单 IAG”在公开 AI 语境里并不是一个稳定的企业产品通用术语；学术上，IAG 至少可以指 *Induction-Augmented Generation* 这样的推理增强框架。结合你们上下文，我更建议工程上先把它落成**轻量显式检索 + 引用回答 + 必要时再叠加归纳推理层**，也就是先做可解释的 RAG/检索闭环，再讨论更复杂的 IAG 语义。这里是工程性判断，而不是术语上的绝对等价。citeturn24academia6 fileciteturn0file0

在权限哲学上，你们附件提出的三条原则应该保留，而且我认为必须上升为架构红线：**个人知识默认私有；团队资料必须在检索前做 ACL 过滤；关键流程动作必须绑定具体人。** 这和 Onyx 面向组织的 RBAC/审计、AnythingLLM 的多用户与 workspace 记忆、以及 MCP 对工具审批和活动日志的强调，是同方向的。fileciteturn0file0 citeturn43view4turn46view3turn29view1

## GitHub 对标项目的核心结论

截至 2026 年 6 月 4 日，本报告纳入主体分析的 GitHub 样本都**远高于 600 stars**，而且大多数已经进入 1 万星以上区间，具备比较明确的社区验证价值。下面不是“把项目罗列一遍”，而是按你们业务场景做筛选后的结果。citeturn43view4turn46view3turn34view0turn45view0turn36view0turn27view3turn38view0turn40view0 fileciteturn0file0

| 类别 | 项目 | 关键事实 | 对你们的价值判断 |
|---|---|---|---|
| 产品北极星 | **Onyx** | 约 30k stars；标准版包含向量+关键词索引、后台 job/worker，同步知识连接；企业版强调共享 chats/agents、SSO、RBAC、查询历史与审计。citeturn43view4 | **最适合作为“团队空间 + 企业知识 + 权限 + 审计”的样板。** 你们如果只学一个“企业内部 AI 助手”的组织形态，优先学它。 |
| 产品北极星 | **AnythingLLM** | 约 61k stars；workspace-first、内置 agents、多用户支持、工作区记忆、MCP 兼容、资料引用、可在 workspace 内运行 agent。citeturn32view0turn46view3turn46view4 | **最适合作为“团队空间 + 个人/团队 Agent + 资料对话”的样板。** 它比纯聊天 UI 更接近你们的“账号 Agent / 团队 Agent”设想。 |
| 产品北极星 | **Rowboat** | 约 14.9k stars；直接自称 open-source AI coworker；把工作沉淀成可检查、可编辑的 Markdown 知识图谱；支持 MCP 外部工具与 PDF slides 等产物。citeturn34view0 | **最适合作为“账号即上下文”的产品心智参考。** 你们要做的“每个账号都可对话、账号代表该人需求上下文”与它非常接近。 |
| 知识底座 | **RAGFlow** | 约 81.9k stars；强调 deep document understanding、template-based chunking、grounded citations、异构文档支持、多路召回与重排。citeturn45view0turn45view2turn45view4 | **最适合作为“团队资料库导入 + 可解释检索 + 引用回答”的参考实现。** 尤其适合需求文档、PPT、扫描件与复杂长文档场景。 |
| 编排参考 | **Dify** | 数十万 stars，附件记录的 GitHub API 统计为 143,756；平台同时提供 visual workflow、RAG pipeline、agents、LLMOps 与 APIs。fileciteturn0file0 citeturn44view2turn44view3turn44view4 | **适合借鉴平台装配与可观测性，不适合直接当你们的主产品内核。** 你们不是做通用 AI 平台，而是做需求审查 cowork。 |
| 编排参考 | **LangGraph** | 约 33.8k stars；定位为长运行、状态化 agent 编排框架；内建持久化 checkpoint，可支撑 HITL、memory、fault-tolerance、tool approval。citeturn36view0turn36view1turn36view2turn36view3 | **非常适合你们后续“AI 初审—人工确认—继续执行”的多阶段流程。** 但只在跨天、可恢复、多审批真正出现后再引入。 |
| 运维/自动化参考 | **n8n** | 约 191k stars；400+ integrations、原生 AI 能力、可自托管，强调代码与可视化兼容。citeturn27view3 | **适合作为后台触发/通知/外部集成参考，不适合早期主界面。** 如果一上来把产品做成流程画布，业务重心会被带偏。 |
| 协议标准 | **MCP Servers** | 约 86.7k stars；README 明确说这些是 reference implementations，不是 production-ready；MCP 的 building blocks 是 Tools、Resources、Prompts。citeturn38view0turn38view1turn38view2turn29view0turn29view1turn29view2turn29view3 | **MCP 应该成为你们的工具层标准，而不是直接上官方参考服务。** 生产中必须做二次封装、审批与审计。 |
| 设计接入 | **Framelink Figma MCP** | 约 15k stars；直接把 Figma 设计数据暴露给 AI coding agents，官方文档强调其效果比单纯截图更接近 pixel-perfect。citeturn30view0turn30view2turn30view3 | **你们提出的“通过 MCP 连 Figma / SVG 原型能力”是有非常现实的开源抓手的。** |
| 协作文档参考 | **Docmost / AppFlowy** | Docmost 约 20.5k stars，突出 spaces、permissions、groups、comments、page history；AppFlowy 约 71.5k stars，强调 projects、wikis、teams together with AI。citeturn26view1turn26view2turn26view3 | **如果你们后面要把团队空间、评论、多人协作做得更完整，这两类项目值得借 UI/交互与信息架构。** |
| 不建议作为长期主赌注 | **AutoGen / CrewAI** | AutoGen 约 58.7k stars，但官方已标注 maintenance mode，并建议新用户转向 Microsoft Agent Framework；CrewAI 约 52.8k stars，强在多 Agent 自动化与 flows。citeturn37view1turn37view0 | **它们更像“Agent 框架生态”，不是你们这个产品的业务内核。** AutoGen 尤其不适合作为长期基础设施押注。 |

把这张表再压缩成一句话：**你们最该学习的是 Onyx 的组织化知识与权限、AnythingLLM 的 workspace/agent 形态、Rowboat 的账号 coworker 心智、RAGFlow 的文档与引用能力、LangGraph 的状态机与人工中断、MCP 的工具协议化。** 这些组合起来，才是你们业务最像的“经典项目集”。citeturn43view4turn46view4turn34view0turn45view2turn36view2turn29view0

## 对你们最有帮助的架构模式

### 团队空间必须成为一等对象

外部项目已经反复证明，只把文档塞进一个“公共知识库”是不够的；真正可用的是**带边界的 workspace / team space**。Onyx 把知识同步、共享 chats/agents、RBAC 和审计放在组织边界里；AnythingLLM 把 Agents、记忆和文档都放在 workspace 语义里；Docmost 也把 spaces、permissions、comments、page history 做成一体。你们附件里提出的 `Workspace / WorkspaceMember / ResourceACL / RolePolicy` 方向是正确的，而且应该提前到 P0/P1，而不是等 Agent 做完再补。否则后面所有知识、消息和审查都会返工。fileciteturn0file0 citeturn43view4turn46view3turn26view1

### 知识系统应采用“原文—切块—索引—快照—引用”的严格链路

RAGFlow 的价值不在“它是个 RAG 产品”，而在于它把**深度文档理解、解释性切块、Grounded Citations、多源文档兼容、重排与可视化介入**做成了完整链路；LanceDB 则证明本地嵌入式方案也可以同时支持向量检索、全文搜索和 SQL；BGE-M3 又进一步证明，中文和多语言场景里，**dense + sparse + multi-vector + rerank** 的组合是合理方向。对你们来说，这意味着团队资料库不要一上来就神秘化成“自动懂一切”，而应该显式保留：原文、chunk、引用来源、快照版本、ACL 过滤和“模型推断/引用依据”的区分。citeturn45view2turn40view1turn40view2turn41view0 fileciteturn0file0

### 个人 Agent 与团队 Agent 应该分开建模

你们提出“每个账号都能够对话；账号代表其需求的全部内容”，这个方向非常像 Rowboat 的做法：它把人的邮件、会议、笔记和计划沉淀成一个长期存在、可检查的工作记忆，并据此生成 deck、brief 等真实产物。AnythingLLM 也给出了“workspace memory + custom AI agents + multi-user permissioning”的成熟样板。我的建议是：**个人 Agent 代表人的上下文，但不代表人的最终承诺；团队 Agent 代表团队规范和公共资料；审查 Agent 代表某次 ReviewRequest 的流程状态。** 三类 Agent 共享一套运行时，但必须有不同的授权边界。citeturn34view0turn46view3turn46view4 fileciteturn0file0

### Agent 运行时应先做受限 loop，再考虑状态图框架

LangGraph 的设计非常契合你们未来的审查协作：它把 agent 拆成 nodes/state/transitions，用 checkpoint 保存每一步，天然支持中断、审批、恢复、memory 和工具审批。这个能力很适合“AI 初审 -> 发起人确认 -> 再继续 -> 通知评审 -> 归档”的长流程。问题在于，你们现在还没有跨天、多审批、多分支的真实负载，如果此时直接引入 LangGraph，成本不一定划算。最稳的路线仍然是你们附件里提到的：**先实现 `AgentRun -> AgentStep -> ToolCall` 的最小可审计闭环；数据模型按 LangGraph 类状态机预留；当复杂度超过阈值，再切换到或接入 LangGraph。** 这不是“排斥框架”，而是避免过早平台化。fileciteturn0file0 citeturn36view1turn36view2turn36view4

### 工具层应采用 MCP 思路，但生产上必须二次封装

MCP 的核心价值，不是“某个 server 能不能直接跑”，而是它把能力拆成了**Tools / Resources / Prompts** 三类标准接口：Tools 负责执行动作，Resources 负责提供上下文，Prompts 负责提供结构化任务模板。对你们来说，这正好对应：`SkillRunner/ArtifactGenerator/Search` 更像 Tools，`内部知识库/团队资料/审查快照` 更像 Resources，`发起审查/生成讲解/会议包` 更像 Prompts。与此同时，MCP 官方 reference servers 的 README 明确提醒它们是教育型参考实现，不应直接视为 production-ready；生产里必须自己加审批、权限和日志。citeturn29view0turn29view1turn29view2turn29view3turn38view1turn38view2

### 讲解产物不应手写一次性 HTML，而应独立成产物管线

你们提出“根据发起人描述，生成 HTML 版、带 SVG 动画的快速讲解视频”，这件事非常值得做，而且已经有成熟开源抓手。**reveal.js** 非常适合生成可交互的 HTML 幻灯与 Auto-Animate；**Remotion** 适合用代码和组件生成可预览、可渲染的视频；**Motion Canvas** 适合对复杂 SVG/场景动画做更程序化的表达；而 Framelink Figma MCP 则能把设计稿的结构数据而不是“截图”暴露给 AI。综合看，最稳的方案不是“直接让大模型一把梭写 HTML”，而是：**先生成结构化讲解 DSL/JSON，再由 reveal.js 渲染 HTML/SVG；如果需要视频，再由 Remotion 或 Motion Canvas 渲染成 MP4。** 这样可控、可重跑、可审计。citeturn33view0turn31view0turn31view1turn30view2turn30view3

## 与现有代码和架构的衔接方案

附件最重要的价值之一，是它证明你们已经不是从零开始。当前系统已经有审查域对象、Chat 与 Message 域、SkillRunner、Prompt/Skill 管理、模型配置、审计与 `runtime/` 数据隔离，所以**正确动作是“升维抽象”，不是“重写产品”**。我认同附件中的判断：短期继续沿用 FastAPI + SQLite + 原生 SPA + `runtime/` 目录模型，先把 service / repository / storage / runner 层补齐，再决定是否引入更重的 worker 或前端框架。fileciteturn0file0

更具体地说，我建议你们把现有系统演进成五个增量域，而不是推翻现有域。第一是**Workspace 域**，新增 `Workspace`、`WorkspaceMember`、`ResourceACL`、`RolePolicy`，把“团队空间/项目空间/个人空间/审查空间”统一到同一种边界模型里。第二是**Knowledge 域**，新增 `KnowledgeSource / KnowledgeDocument / KnowledgeChunk / RetrievalLog`，把导入、解析、索引、快照和引用做成显式链路。第三是**Agent 域**，新增 `AgentProfile / AgentAuthorization / AgentRun / AgentStep`，使个人 Agent、团队 Agent、审查 Agent 共用一套运行时。第四是**Collaboration 域**，新增 `Notification / Comment / Inbox`，把“有人和我的账号 Agent 沟通，我是否要回复/评论/确认”做成系统级回路。第五是**Review Workflow 域**，把当前 `ReviewTask` 升级为 `ReviewRequest + ReviewParticipant + ReviewStageExecution + Artifact`。这些对象和你们附件里的模型规划是完全一致的。fileciteturn0file0

在执行层，我建议继续把 **SkillRunner 保留为“确定性执行底座”**，不要让自由 Agent 接管稳定流程。外部经验也支持这个取舍：Dify、n8n、CrewAI 这类平台都证明了“模型规划”和“确定性工具/流程执行”必须分层，否则调试与治理成本会迅速变高；LangGraph 也强调把流程拆成明确的 nodes 和 state，而不是让一个无限自由的 agent 随意乱走。你们当前的 SkillRunner 与审查流水线，正好可以承担“可测试、可回归、可审计”的那一层。fileciteturn0file0 citeturn44view2turn27view3turn37view0turn36view4

在检索底座上，我不建议你们一上来就服务化上 Milvus/Qdrant。你们附件里“先 SQLite FTS5，再做 LanceDB / Milvus Lite / Chroma POC，规模上来后再服务化”的判断是对的，而且和外部项目的适配程度很高：LanceDB 本身就支持向量、全文和 SQL，本地运行友好；Milvus 和 Qdrant 更适合后续并发/规模/独立运维阶段；RAGFlow 的高质量检索链路并不要求一开始就上重型分布式数据库。对内网、单机、`runtime/` 目录隔离友好的阶段，**SQLite FTS5 + 显式引用 + 小规模嵌入式向量 POC** 是最稳的。fileciteturn0file0 citeturn40view1turn39view3turn39view5turn45view4

前端层面，也不建议现在就为“团队协作”焦虑到重写。你们真正需要新增的不是一个彻底重做的前端，而是四个高价值入口：**团队空间入口、显式检索与引用面板、Agent 运行轨迹面板、消息/通知 Inbox。** 这四个东西一旦出现，原本的聊天与审查页面就会从“单点功能页”变成“工作台”。如果后续评论线程、消息中心、任务视图复杂度明显上升，再考虑 React/Vue 并不迟。fileciteturn0file0

还有一个常被忽略但很现实的问题是许可证。你们附件已经提醒不要直接 Fork Dify、RAGFlow、Flowise 或 n8n 当主产品；从源码复用角度看，这也是对的。Dify 使用的是基于 Apache 2.0 但带附加条件的 Dify Open Source License；n8n 是 fair-code 体系；Open WebUI 当前代码库也包含需要保留品牌要求的许可段。换句话说，**你们应该主要借鉴架构、交互和模块边界，而不是深度嵌入这几套产品源码。** 反而像 MCP 适配层、LanceDB、reveal.js、Remotion 这类组件级能力，更适合被吸收。fileciteturn0file0 citeturn44view0turn27view3turn35view0turn33view0turn31view0

## 分阶段产品与技术路线

如果按你们当前节奏来排，我建议把路线压缩成四个对业务最关键的阶段，而且每个阶段都让业务能感知到价值，而不是先做一大堆“平台化基础设施”。fileciteturn0file0

### 近期阶段

近期应该把 0.2.x 相关遗留能力收束成一个清晰目标：**团队资料库 MVP + 团队空间雏形**。具体落地就是：上传团队文档、分类与标签、保存原文、建立版本 hash、允许项目或审查任务引用资料快照、在聊天/审查里显式选择资料、返回引用来源，并在最小成本下先用 `Workspace + member/admin` 两到三档角色把权限边界立住。外部经验表明，这是后面一切能力的地基；如果这里不先收口，后面的 Agent、消息和审查协作都只能建在“公共文档池”这种脆弱假设上。fileciteturn0file0 citeturn43view4turn46view3turn26view1

### 中期阶段

中期的重点不是“多智能体表演”，而是**受限 Agent 对话 + 内部检索 + 账号 Agent**。做法上建议保留你们在附件里的思路：先做 `AgentRun / AgentStep / ToolCall` 最小模型，先接 `Search / Retrieval / SkillRunner / ArtifactGenerator / MCP Adapter` 这几类工具，先明示工具调用与知识范围，先让用户可确认动作与资料边界，再逐渐补充个人 Agent 和团队 Agent。这个阶段最关键的，不是 Agent 回答得多像人，而是它是否能稳定地：查内部知识、调技能、生成任务、把需要人的动作回流成确认消息。AnythingLLM、Rowboat 和 MCP 的成熟模式都支持这个判断。fileciteturn0file0 citeturn46view3turn34view0turn29view1turn29view2

### 协作升级阶段

再下一阶段，才是你们最有差异化的地方：**审查平台重构为协作流程系统。** 这里推荐的状态机非常清晰：`发起审查 -> AI 初审 -> 结构化问题清单 -> 发起人确认/驳回/强行通过 -> 讲解产物生成 -> 通知评审成员 -> 评论补充 -> 人工评审会 -> 决议归档 -> 回写团队知识`。LangGraph 证明这种多状态、可恢复、可中断、有审批的流程在技术上非常成熟；RAGFlow 证明引用与证据链可以做得足够清晰；reveal.js / Remotion / Motion Canvas 证明“会前快速理解”的讲解产物不需要自己闭门造轮子。你们真正要做的是把这三者用业务对象串起来。fileciteturn0file0 citeturn36view2turn36view3turn45view2turn33view0turn31view0turn31view1

### 治理与规模化阶段

只有在前面三个阶段被真实团队持续使用之后，才值得进入治理与规模化：包括配额、预算、审计、质量趋势、Prompt/Skill 回归、workspace 成本仪表盘，以及是否把向量检索服务化到 Milvus/Qdrant。Onyx 的查询历史、RBAC、Analytics，n8n 的企业权限与集成规模，LangGraph 的 observability 思路，都说明这些功能很有价值；但它们必须建立在前面的真实业务闭环之上，否则只会造成平台空转。citeturn43view4turn27view3turn36view1 fileciteturn0file0

## 风险、限制与开放问题

最大的产品风险，不是技术做不出来，而是**过早平台化**。Dify、n8n、CrewAI、AutoGen 这类项目都很强，但它们强在“平台能力”或“Agent 框架能力”，不等于你们要把主产品做成那样。你们真正的北极星仍然是“需求审查和内部协作效率是否提升”，不是“是否有一张更酷的流程画布”。附件里“不做通用 AI 平台”的边界，我建议继续保持。fileciteturn0file0 citeturn44view2turn27view3turn37view0turn37view1

最大的技术风险，是**把知识、权限和记忆混成黑盒**。Rowboat 的一个很重要启发，是长期记忆最好是可检查、可编辑的，而不是不可追踪的隐藏状态；RAGFlow 的启发，是知识回答必须有 traceable citations；MCP 的启发，是外部工具必须有审批和活动日志。如果以后个人 Agent 可以“代表某人说话”，那它的上下文来源、授权范围、是否需要本人确认，都必须是明确可见的。citeturn34view0turn45view2turn29view1

从调研范围看，本报告已经覆盖了与你们业务最相关的一线开源样本和关键外部设计模式，但有两个限制需要明确。第一，我这次**没有直接审阅你们完整代码仓库**，所以对现有实现的判断主要基于你上传的规划文档，而不是逐文件代码审计。第二，star 数、项目功能与许可证都属于动态信息，本报告引用的是截至 2026 年 6 月 4 日可见的一手页面与文档，后续仍可能演化。fileciteturn0file0 citeturn43view4turn46view3turn45view0turn36view0turn27view3

最后，若要在立项会上把问题压缩成最关键的三个，我建议聚焦这三件事。第一，**你们是否接受“团队空间和权限先于 Agent”**；如果不接受，后面会持续返工。第二，**你们是否接受“个人 Agent 默认只读，不默认代表本人承诺”**；如果不接受，协作与审计风险会非常高。第三，**你们是否接受“讲解产物先做 HTML/SVG，再择机视频化”**；如果接受，P4 的交付难度会显著下降。以上三点在你们附件里已经有方向性答案，而外部调研基本都支持这些取舍。fileciteturn0file0 citeturn34view0turn29view1turn33view0turn31view0