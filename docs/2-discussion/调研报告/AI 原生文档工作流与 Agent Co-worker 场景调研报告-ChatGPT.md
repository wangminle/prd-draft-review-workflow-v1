# AI 原生文档工作流与 Agent Co-worker 场景调研报告

## 核心判断

这轮调研的结论很明确：**主流大厂并不是都用同一个名字去做 “Cowork / Workbuddy”，但几乎都已经在推出“会用工具、会跨应用、会理解组织上下文、可被治理”的 agent-based co-worker 体系**。Anthropic 直接用 **Claude Cowork** 命名，强调“给 Claude 一个目标，它会在你的电脑、本地文件和应用里自主完成交付”；Microsoft 强调 **Work IQ + Copilot Studio + Agent 365**，把重点放在“知道你、你的工作、你的公司”，以及 agents 的创建、发布和治理；Google 把重心放在 **Workspace Flows + Gems + Agentspace + A2A**，强调多步骤工作流自动化、Drive 上下文、以及跨 agent 互操作；Slack 把 **Slackbot** 定位成“理解你和你的工作空间的个人 AI agent”；Atlassian 用 **Rovo Search / Chat / Agents / Studio / Skills** 构成完整产品面；OpenAI 则通过 **ChatGPT Apps / Deep Research / Responses API** 把“搜索、知识库、工具调用、应用连接”打成一个通用 agent substrate。换句话说，市场已经从“会聊天的 Copilot”进入“可执行、可协作、可治理的工作代理”阶段。citeturn39search2turn38view3turn28search3turn38view2turn27search13turn28search22turn9search8turn39search1turn39search16turn39search11

对你们要做的产品方向，我的判断是：**这不是一个单点 agent 产品，而是一个“工作空间 + 知识层 + Agent 执行层 + Skills/MCP 连接层 + Explainability 产物层 + Review/Notification 治理层”的复合系统**。如果把“用户默认拥有自己的 agent”“个人空间与团队空间分层”“文档—讲解—评审链路一体化”这三件事同时做好，你们的目标体验是成立的；如果只做一个会写 PRD 的 agent，则很容易落回“高级聊天工具”，难以形成组织级工作流。这个判断与 Microsoft 的 Work IQ、Slackbot 的“knows you and your workspace”、Glean 的 personalized + permissions-aware assistant，以及 Google Workspace Flows 的 Drive 上下文工作流是一致的。citeturn28search3turn28search2turn28search5turn28search8turn38view2

在技术落地上，**不建议从零自研整个平台栈**。更稳妥的路线是：用成熟开源平台承接工作空间、知识库、流程与可视化配置；用 Pi 这类轻量 agent harness 承接“强操作性”的个人代理能力；用 Docling / MarkItDown / OCRmyPDF 补齐文档底座；用 MCP、Figma MCP、GitHub MCP、Playwright MCP 等补齐连接器与生产力外设；再用消息与审批机制把整个流程闭环。Dify、RAGFlow、AnythingLLM、FastGPT、Flowise、LangGraph、OpenAI Agents SDK、Pi 等项目已经把你们未来规划中的很多要素分别验证过了。citeturn14view3turn17view1turn17view0turn16view2turn16view0turn14view2turn21view0turn19view0turn33view0turn33view1turn33view2

## 大厂产品图谱与宣传趋势

一个值得先澄清的事实是：**“Cowork / Workbuddy / AI teammate / agentic work” 在产品命名上并不统一，但宣传重心已经高度收敛**。主流宣传口径反复出现的关键词包括：  
**理解用户与组织上下文、跨应用操作、团队知识整合、可发布可管理的 agent、以及多 agent / 协作式执行**。citeturn39search2turn28search3turn38view2turn28search22turn9search8turn38view3

| 厂商 | 当前产品形态 | 公开宣传特色 | 对你们场景的启发 |
|---|---|---|---|
| **Anthropic** | **Claude Cowork** + Integrations + Research | Claude Cowork 被定义为“给 Claude 一个目标，它会在你的电脑、本地文件和应用里自主完成交付”；Anthropic 还把 Integrations 与 Research 打通，强调可搜索网页、Google Workspace 与连接应用，并生成带引用的报告。citeturn39search2turn39search13turn39search14turn39search18 | **最接近“业务 co-worker”原型**：不是只回答问题，而是替你做事、产出结果。你们的“需求调研—起草—讲解—评审”链路和它的方向高度一致。 |
| **Microsoft** | **Microsoft 365 Copilot**、**Copilot Studio**、**Agent 365** | Microsoft 把 **Work IQ** 定义为让 Copilot “知道你、你的工作、你的公司”的智能层；Copilot Studio 主打“创建、定制、发布、管理 agents”，并把 **Agent 365** 定位为 agents 的 control plane。citeturn28search3turn28search19turn38view3 | **治理最强**：适合借鉴你们未来的 agent 生命周期管理、合规、安全、发布与审计设计。 |
| **Google** | **Workspace Flows**、**Gems**、**Agentspace**、**A2A** | Workspace Flows 可用 AI 自动化多步骤流程，并可引用 Drive 文件上下文、调用自定义 Gems；Agentspace 则主打 enterprise search 与 agent adoption；Google 还推动 **A2A** 让不同厂商和框架的 agents 协同。citeturn38view2turn27search13turn27search0turn27search7 | **工作流与互操作最强**：非常适合作为你们“多 agent 评审链路 + 跨系统协作”的架构参考。 |
| **OpenAI** | **ChatGPT Apps**、**Deep Research**、**Responses API**、**Agents SDK** | OpenAI 现在把“应用连接、深度研究、工具使用、文件搜索”连成体系：ChatGPT Apps 可代表用户访问第三方工具、搜索数据源、同步到 workspace knowledge base；Deep Research 可输出带文档化报告；Responses API 提供 web search、file search、computer use 等内建工具。citeturn39search1turn39search16turn39search5turn39search11turn39search0 | **通用 Agent substrate 最强**：很适合借鉴“研究型 agent + 知识库 + 工具执行”的底层能力组织方式。 |
| **Slack / Salesforce** | **Slackbot**、agent orchestration、Agentforce in Slack | Slack 直接把 Slackbot 定义成“你的 personal AI agent”，强调它会学习你的工作方式，并理解你和你的 workspace；另一条线则强调 “one conversation, every tool”，把 apps、agents、data 编排进同一对话界面。citeturn28search2turn28search10turn28search18turn28search22 | **会话即工作台**：对你们的“评审通知、审批接入、团队协作入口”非常有启发。 |
| **Atlassian** | **Rovo Search / Chat / Agents / Studio / Skills** | Atlassian 把 Rovo 定位为把组织知识转成行动的产品，覆盖 Search、Chat、Agents 和 Studio；官方披露 Rovo agents 已进入 240 万个业务工作流，并正在强化 Skills、memory 和实时协作。citeturn9search8turn9search4turn9search2turn9search9turn9search17 | **知识工作流融合最强**：你们要做的 PRD 评审流程，本质上很像“Confluence/Jira + agent + skills”的跨层产品。 |
| **钉钉** | **DEAP 企业 AI 平台**、**AI 助理**、**文档/白板/表格/脑图** | 钉钉公开强调 DEAP 是“一站式企业级 AI 解决方案”，支持 AI 资产管理、自定义能力与 AI 助理；其 AI 助理官方文档明确覆盖智能沟通、智能协同、自定义能力，并与文档、白板、表格、脑图等办公内容打通。citeturn11search0turn11search5turn11search8turn11search19turn11search28 | **国内办公套件落地方向很清晰**：如果你们面向中国企业市场，这条线值得持续跟踪。 |

从宣传趋势看，**大厂已经不再把“AI 助手”当作单点功能卖，而是在卖三件更重的东西**：  
其一是 **上下文**，也就是“懂你、懂团队、懂企业资源”；其二是 **执行力**，也就是“会搜索、会调用工具、会跨系统”；其三是 **治理**，也就是“可发布、可管理、可管权限、可审计”。这三件事同时出现，才是 agent-based co-worker 成熟的标志。citeturn28search3turn28search22turn27search13turn38view3turn39search1turn39search2

## 面向目标产品的能力模型与架构建议

对于你们提出的需求，我建议把整体产品拆成 **六层**：**用户代理层、工作空间层、知识层、执行层、连接层、治理层**。这不是抽象设计，而是对目前最有效产品形态的归纳：Microsoft 用 Work IQ 做用户/组织上下文，Google 用 Workspace Flows 把工作流与 Drive 上下文打通，Glean 用 permissions-aware personalization 和 context graph 建知识层，OpenAI 用 file search / apps / deep research 建执行层，GitHub 则在 MCP registry 与 allowlist 上补治理。citeturn28search3turn38view2turn28search5turn28search8turn39search0turn39search1turn25search2turn25search15

### 工作空间建议

你们至少需要三类工作空间：

| 工作空间 | 建议定位 | 建议权限模型 | 与 Agent 的关系 |
|---|---|---|---|
| **个人空间** | 调研草稿、私人偏好、个人记忆、个人工具授权、实验性 prompt/skills | 默认私有，可选择把产物“提交到团队空间” | **每个用户默认一个 personal agent**，其上下文包括用户画像、历史需求、偏好模板、个人知识。这个方向与 Slackbot“learns how you work”、Microsoft Work IQ“know you, your job, your company”、Glean personalized assistant 的逻辑一致。citeturn28search2turn28search3turn28search5turn28search21 |
| **团队空间** | 团队知识库、统一规范、模板、评审基线、共享 skills/MCP | 基于团队/角色/项目组授权；文档与数据按 ACL 继承 | 团队 agent 不应覆盖个人 agent，而应作为共享上下文层，类似 Glean 的 enterprise graph、Rovo 的组织知识层和 Workspace Flows 的 Drive 上下文。citeturn28search8turn9search8turn38view2 |
| **评审空间** | 为某个需求或版本冻结上下文，沉淀评审结论与风险 | 只读评审包 + 评论/审批权限 + 审计 | 评审阶段需要“冻结知识快照”，避免在 review 期间因知识库更新导致结论漂移；这个做法是对 enterprise governance 的工程化补充。GitHub/Copilot 的 MCP registry、allowlist 与 policy 机制说明：**运行时治理和访问边界必须独立存在**。citeturn25search0turn25search2turn25search4turn25search15 |

这里最关键的一点不是“有没有 workspace”，而是**不要把个人记忆、团队知识、评审快照混成一个库**。如果混在一起，最容易出现三类问题：一是权限穿透，二是引用污染，三是最终 reviewer 看到的依据与 agent 当时检索到的依据不一致。Glean 的 permissions-aware assistant、Slackbot 的 workspace-aware 上下文、以及 OpenAI Apps 同步到 workspace knowledge base 的设计，都在提醒同一件事：**知识访问一定要以用户/团队/应用边界来做，而不是以“统一向量库”来做**。citeturn28search5turn28search22turn39search1

### 知识库与 RAG 建议

你们的团队知识库不应该只有“向量检索”一种形态，而应该是 **文档解析 + 权限过滤 + 混合检索 + 版本引用** 的组合。OpenAI 的 file search 明确强调 semantic + keyword search；Glean 的 context graph 与 permissions-aware personalization 证明，仅靠 embedding 对企业知识工作是不够的；RAGFlow、Docling、MarkItDown 这类开源项目则证明，复杂文档场景下，解析质量决定了后续检索质量。citeturn39search0turn28search8turn28search5turn17view1turn33view0turn33view1

因此，我更推荐你们的知识层按下面的顺序建设：

| 能力 | 建议做法 | 依据 |
|---|---|---|
| **文档解析** | 对 PDF、Office、图片、邮件、网页统一转成 Markdown/HTML/JSON 三种中间格式；复杂表格、布局、公式优先走 Docling，高兼容快速接入可走 MarkItDown。citeturn33view0turn33view1turn34view0turn34view1 | 复杂文档与 PRD、竞品资料、扫描版合同/报告都强相关。 |
| **OCR** | 扫描件先 OCR 再入库；对纯视觉文档可补充 OCR-free 路线。OCRmyPDF 适合生产可搜索 PDF，Docling 与 Donut 适合更复杂的视觉文档理解。citeturn33view2turn33view0turn33view3turn34view2 | “扫描版素材无法被高质量检索”是企业知识库常见失败点。 |
| **混合检索** | keyword + semantic + structured metadata + ACL filter；重要知识对象增加 graph edges，如“人—项目—文档—决策—工单”。citeturn39search0turn28search8turn28search16 | 这种设计比单纯向量检索更接近真实企业语义。 |
| **引用与可追溯** | 每个回答必须保留 source span、版本号、检索时间与 workspace scope。citeturn39search16turn39search18 | 后续评审、审计、复盘都会依赖它。 |

这里的一个关键产品判断是：**你们并不是只需要“知识问答”**。你们需要的是：  
“研究时能检索、写作时能引用、评审时能冻结、回看时能追溯”。这与消费级 chat 完全不同，更接近企业 AI 平台而不是单点助手。citeturn39search16turn28search5turn25search2

## 以 Pi Agent 为例的基础能力补全

Pi 的优点很鲜明：它是一个非常轻的 **agent harness**。官方 README 把它拆成 `pi-coding-agent`、`pi-agent-core` 和 `pi-ai` 三层：前者是交互式 agent CLI，核心层提供 tool calling 与 state management，底层统一多模型 API。Pi 还明确支持 extensions、skills，以及 Slack/chat automation 的扩展方向。citeturn19view0turn30search7turn31search3

但也要很清楚地说：**Pi 现在更像一个“强操作型个人代理 runtime”，不是现成的企业文档协作平台**。它内置的工具主要是 `read`、`bash`、`edit`、`write`、`grep`、`find`、`ls`；skills 是按需加载的能力包；extensions 可以覆盖内置工具、加日志、做访问控制或转发到远程系统；官方还明确提示 Pi **没有内置权限系统**，要靠 containerization/sandbox 补边界。换句话说，Pi 的架构很适合做“个人 agent 内核”，但并不足以直接承接你们要做的工作空间、知识治理与组织评审系统。citeturn30search6turn30search7turn30search12turn19view0

### 对 Pi 类框架的能力清单建议

如果以 Pi Agent 为样板来做你们的平台，我建议把基础能力补齐到下面这张表的级别：

| 能力域 | Pi 当前状态 | 你们场景下的建议补齐 |
|---|---|---|
| **本地文件读写与命令执行** | 已具备，内置 `read/bash/edit/write/grep/find/ls`。citeturn30search6turn19view0 | 保留，但必须加沙箱、审计和路径/工具 allowlist。 |
| **文档读写转换生成** | 不是强项。Pi 更像操作 runtime，而非文档解析栈。citeturn19view0 | 接入 **MarkItDown** 做高兼容 Markdown 转换，接入 **Docling** 做高保真 PDF/Office/表格/布局理解。MarkItDown 当前 GitHub 显示约 **143k stars**，Docling 约 **60.9k stars**。citeturn34view1turn33view1turn34view0turn33view0 |
| **OCR** | 非核心内建能力。citeturn19view0 | 扫描件建议接 **OCRmyPDF**；复杂视觉文档可补 **Donut** 或 Docling OCR 能力。OCRmyPDF 约 **33.8k stars**，Donut 约 **6.9k stars**。citeturn33view2turn34view2 |
| **搜索** | Pi 文档并未把企业级 web/deep search 作为核心卖点。citeturn19view0turn30search5 | 研究型流程要同时具备 **公网深搜**、**知识库检索**、**结构化系统查询**。可接 OpenAI web/file search，或用 RAGFlow / Dify / FastGPT 承接 KB 检索，再通过 MCP 接外部系统。citeturn39search11turn39search0turn17view1turn14view3turn16view2 |
| **浏览器执行** | 非内建核心。citeturn19view0 | 竞品调研、原型抓取、在线数据核验建议接 **browser-use** 或 **Playwright MCP**。browser-use 约 **97.1k stars**，Playwright MCP 约 **33.4k stars**。citeturn37view0turn37view1 |
| **Skills / Extensions** | Pi 这部分设计很好，skills 是按需加载的 capability package，extensions 则提供生命周期与工具扩展。citeturn30search7turn19view0turn31search14 | 可以直接借鉴 Pi 的 skills/extension 机制，把“需求调研、竞品分析、PRD 审校、讲解生成”做成独立 skills。 |
| **权限与隔离** | 官方明确说没有 built-in permission system，需要 containerize or sandbox。citeturn19view0 | 这条必须做强，不然后续连接 GitHub、Figma、知识库、消息系统时风险过高。 |
| **聊天渠道与持久会话** | Pi-chat 已验证“每个连接频道一个持久 workspace + memory + skills”的模式。citeturn31search3 | 这正好能映射到你们的“一个用户默认一个 agent”的产品设定。 |

因此，对你们来说，**Pi 适合做“用户默认 agent”的执行内核或 power-user mode，不适合直接承担平台全部职责**。更合理的组合是：**Pi 做 runtime；RAGFlow / FastGPT / Dify / AnythingLLM 做 workspace、KB 与流程壳；Docling / MarkItDown / OCRmyPDF 做文档底座；MCP 做连接与治理。** 这条路线比“把一切塞进 Pi”工程风险低很多。citeturn19view0turn17view1turn16view2turn14view3turn17view0turn33view0turn33view1turn33view2turn22view1

## GitHub 经典开源项目拆解与借鉴价值

下面这部分只保留 **GitHub star 超过 600**、且对你们场景真正有帮助的项目。结论先说：**没有一个单一项目已经完整等于你们的远期产品，但“平台壳 + agent 编排 + 文档栈 + MCP/技能治理 + 浏览器执行”这五块，在开源世界已经分别非常成熟。**

### 平台壳与工作空间层

| 项目 | GitHub stars | 已验证能力 | 对你们的直接价值 |
|---|---:|---|---|
| **Dify** | **144k** | 官方定位是 production-ready 的 agentic workflow 平台，支持 agents、50+ 内建工具、监控与 BaaS/API。citeturn14view3 | 很适合做你们的**平台控制台**、流程编排、应用发布和基础运维层。 |
| **AnythingLLM** | **61k** | 官方主打 workspace-centric、multi-user、memory、scheduled tasks、内置 agents、文档管线。citeturn17view0 | 对“**个人空间 / 团队空间 / 知识库**”模型特别有参考价值。 |
| **FastGPT** | **28.3k** | 官方定位是 AI Agent building platform，强调 data processing、RAG retrieval、Flow 可视化编排，并在 topic 中已包含 MCP。citeturn16view2 | 适合中国团队、中文业务场景，以及你们的“知识库 + workflow + agent”组合需求。 |
| **RAGFlow** | **81.9k** | 官方强调 context engine、agent templates、深度文档理解、与 Confluence/S3/Notion/Discord/GDrive 等同步，且已支持 Docling、可编排 ingestion pipeline、memory。citeturn17view1turn16view3 | 如果你们要把**复杂文档理解**当成核心，RAGFlow 是极强参考。 |
| **Flowise** | **53.3k** | 官方强调可视化构建 AI agents，且单仓库中拆出了 `server`、`ui`、`components`、`api-documentation` 等模块。citeturn16view0 | 对你们的“**低代码流程配置** + 团队技能编排”非常有借鉴意义。 |

这类平台项目共同证明了一件事：**工作空间、知识库、流程编排、运营面板，本质上应该是一个独立平台层，而不是嵌在 agent runtime 里。** 这也是为什么我不建议把 Pi 或纯代码 agent framework 直接当成完整产品底座。citeturn17view0turn14view3turn16view2turn17view1turn16view0

### Agent 编排与执行层

| 项目 | GitHub stars | 已验证能力 | 对你们的直接价值 |
|---|---:|---|---|
| **LangGraph** | **33.8k** | 官方定位是 stateful、long-running agents 的低层编排框架，强调 durable execution、human-in-the-loop、memory、production deployment。citeturn14view2 | 很适合做**需求评审工作流**、长链路 agent run、以及可恢复的多步骤执行。 |
| **CrewAI** | **52.8k** | 官方把 Crews 与 Flows 分开，前者强调 autonomous collaboration，后者强调 event-driven control。citeturn13view0turn14view0 | 这很像你们需要的“**多角色产品经理团队 + 审批流**”模型。 |
| **OpenAI Agents SDK Python** | **26.9k** | 官方提供 agents、handoffs、MCP、sandbox agents、guardrails、sessions、HITL、tracing。citeturn21view0 | 很适合作为**研究 agent / 生成 agent / 审核 agent** 的统一执行底座。 |
| **OpenAI Agents SDK JS** | **3.2k** | 与 Python 版相同思路，强化 JS/TS 场景与 voice agents。citeturn22view0 | 如果你们前后端都偏 TypeScript，这条会更顺手。 |
| **Pi** | **59.4k** | 轻量 agent harness、tool calling + state management、统一多模型 API、extensions、skills、pi-chat。citeturn19view0 | 很适合做**默认用户代理**和 power-user 执行器。 |
| **AutoGen** | **58.7k** | 历史上很重要的 multi-agent 框架，但官方已经明确写明 **Maintenance Mode**，并建议新用户转向 Microsoft Agent Framework。citeturn13view1turn14view1 | **适合作为设计参考，不建议作为新项目主干。** |

如果只谈“代码架构成熟度”，**LangGraph + OpenAI Agents SDK** 代表了更现代、面向生产的 agent orchestration 方向；**Pi** 代表了“轻量、强执行、强 hackability”的个人代理方向；**CrewAI** 代表了“多角色 agent 团队”的表达方式；而 **AutoGen** 更像历史节点，不宜再做 greenfield 主底座。citeturn14view2turn21view0turn19view0turn13view0turn14view1

### 能力层、文档层与连接层

| 项目 | GitHub stars | 已验证能力 | 对你们的直接价值 |
|---|---:|---|---|
| **modelcontextprotocol/servers** | **86.7k** | MCP reference servers + MCP Registry。citeturn22view1turn21view2 | 连接外部工具与数据源的事实标准。 |
| **modelcontextprotocol/modelcontextprotocol** | **8.3k** | MCP protocol spec 与官方文档。citeturn22view2turn21view3 | 你们的 skills / tool / resource / prompt 协议层建议以它为基础。 |
| **GitHub MCP Server** | **30.4k** | 官方支持 repos、issues、PR、Actions、Projects，并支持 `toolsets` / `tools` 级配置。citeturn22view3turn21view4 | 这是**“MCP 如何被真正治理”**的最佳公开样板之一。 |
| **Playwright MCP** | **33.4k** | 通过结构化 accessibility snapshots 做浏览器自动化，适合探索式或长流程自动化。citeturn37view1turn36view1 | 适合“竞品调研、页面验真、演示录制、原型联动”。 |
| **browser-use** | **97.1k** | 面向 AI agents 的浏览器执行，支持 custom tools、CLI、skills、cloud/browser 分层。citeturn37view0turn36view0 | 对“深搜 + 网页操作 + 竞品分析”特别有用。 |
| **Docling** | **60.9k** | 多文档格式、高级 PDF 理解、Markdown/HTML/JSON 导出、OCR、本地执行、集成 LangChain/LlamaIndex/CrewAI/Haystack，并可通过 MCP 连接 agent。citeturn33view0turn34view0 | 适合作为你们**文档底座**。 |
| **MarkItDown** | **143k** | PDF、PPT、Word、Excel、图片 OCR、音频等统一转 Markdown。citeturn33view1turn34view1 | 适合作为**快速兼容转换层**。 |
| **OCRmyPDF** | **33.8k** | 扫描 PDF OCR、可搜索 PDF/A、保持布局、支持多语言。citeturn33view2 | 适合作为**扫描资料入库前处理**。 |

这一组项目说明，你们完全不必把“文档解析、OCR、连接器、浏览器操控”从零做起。**真正应自研的，是工作流业务逻辑、上下文模型、评审机制和 explainability 产品体验。** citeturn33view0turn33view1turn33view2turn22view1turn22view3turn37view0turn37view1

## Skills、MCP、AI 讲解、用户代理与消息机制

### Skills 与 MCP 的发布、配置、管理

你们问“有没有新的、好用的、完整的方案”，我的回答是：**有，但不是一个单品，而是一套正在收敛的组合范式。**

这套范式可以概括成：

**协议层（MCP / A2A） → 注册层（Registry） → 策略层（Allowlist / Toolsets） → 运行层（Remote MCP / OAuth / Sandbox） → 审计层（Tracing / Logs / Analytics）**

这条路线现在已经有多个公开样板：

- **MCP** 已经有官方 spec 与 reference servers；  
- **GitHub MCP Registry** 已经把 registry、组织/企业级 policy、allowlist enforcement 做出来了；  
- **GitHub MCP Server** 还演示了 `toolsets` 与 `tools` 的分层发布方式；  
- **Cloudflare** 已经把 **remote MCP server** 做成可托管基础设施；  
- **Smithery** 把 registry + CLI + skills/MCP 安装管理做成了产品；  
- **Google A2A** 则补上了“agent 与 agent 怎么互相发现、授权、协同”的标准化层。citeturn22view2turn22view1turn25search2turn25search0turn25search4turn25search15turn22view3turn26search3turn26search19turn26search5turn26search0turn27search0turn27search7

对你们而言，**最实用的落地模型**不是“给每个 agent 随便装工具”，而是：

| 层级 | 建议做法 |
|---|---|
| **组织级** | 维护内部 MCP registry，只允许经过审查的 server 被发现与安装；借鉴 GitHub registry + allowlist 模式。citeturn25search2turn25search0turn25search15 |
| **团队级** | 以 team workspace 为单位绑定 skills 包与 MCP server 组合；对外部工具只开放该团队需要的 toolsets。GitHub MCP Server 的 toolsets 机制非常适合作为样板。citeturn21view4turn22view3 |
| **个人级** | 个人 agent 可以订阅额外 skills，但必须受组织 allowlist 与审批策略约束。Pi 的 skill standard 和 `allowed-tools` 约束说明，skills 本身也应有元数据与边界声明。citeturn31search16turn30search7 |
| **跨 agent 协作** | 对“研究 agent → 讲解 agent → 评审 agent”的链路，建议把 MCP 当作 tool/data 标准，把 A2A 当作 agent-to-agent 协作标准。citeturn27search0turn27search7turn22view2 |

如果让我给出一句最短建议，那就是：**你们应该自建“内部 Skills/MCP 控制面”，而不是只做一个安装列表。** 这个控制面至少要管理五类对象：server manifest、toolset policy、workspace binding、credential scope、run audit。GitHub、Cloudflare、Pi skill standard 这三条线已经把这些关键动作分别跑通了。citeturn25search2turn22view3turn26search19turn31search16

### AI 讲解、Mermaid、SVG、HTML 动效与原型连接

你们特别强调“AI 讲解”功能，这一点我认为非常重要，因为它会把“会写文档”升级成“会讲解需求”。这块现在也已经有成熟积木可用：

- **Mermaid** 已经是成熟的文本化图表工具，GitHub 原生支持 Mermaid 代码块渲染；  
- **SVG** 在现代浏览器里有完整的图形与动画能力；  
- **Motion** 提供 production-grade 的 HTML / SVG 动画能力；  
- **Figma MCP Server** 已经是官方能力，能把 Figma 里的组件、变量、布局、FigJam 内容和 Make 资源提供给 agent，也支持把原生 Figma 内容写回画布，甚至能把 live web interfaces 发回 Figma 作为可编辑图层；  
- **Playwright MCP** 或 Playwright CLI/skills 可以把“讲解网页”自动回放或自动验真。citeturn24search2turn24search5turn24search7turn24search23turn24search8turn23search3turn23search4turn23search11turn23search19turn23search14turn23search17

这意味着你们完全可以把“AI 讲解”做成一个标准产物链：

**PRD Markdown → Mermaid 结构图 → SVG 讲解图 → HTML 动画讲解页 → Figma/网页预览 → Review Package**

其中技术上最稳的路径是：

1. 先把 PRD 结构化成 Markdown/JSON；  
2. 用模板把结构节点转成 Mermaid；  
3. 对关键流程图转 SVG；  
4. 用 Motion 做 HTML/SVG 动画讲解页；  
5. 如果需要设计协作，再通过 Figma MCP 把网页版讲解或关键画面送回设计系统。citeturn24search10turn24search6turn24search7turn24search8turn23search19

这里我给一个很明确的产品建议：**AI 讲解不要做成“额外功能”，而要做成“评审前置物”**。也就是说，负责人在看到长文档之前，先收到一个 60–180 秒的可交互讲解包，然后再下钻看源文档、问题评估、引用依据、风险项。这会显著提高需求评审效率，也更符合 Slack/Teams/Chat 这类“先看卡片、后下钻”的工作方式。这个判断与 Slack 的 agentic work 入口、Google Workspace Vids/Flows 的方向，以及 Figma MCP 的设计-开发联动趋势一致。citeturn28search22turn28search18turn38view2turn23search11

### 用户默认拥有一个 Agent 与数字孪生式设计

你们提出“每个 workspace 的使用者默认有一个 agent，它在需求层面代表用户自己”——我认为这不是异想天开，而是**主流办公 AI 正在接近的方向**。不过，当前更准确的说法不是“成熟的数字孪生”，而是 **user-scoped work agent**。

最接近你们设想的公开样板有四类：

- **Microsoft Work IQ**：官方直接说它让 Copilot “知道你、你的工作、你的公司”。citeturn28search3turn28search19  
- **Slackbot**：官方定义它是个人 AI agent，理解你和你的 workspace，并帮助准备会议、分析报告、生成项目简报。citeturn28search2turn28search6turn28search10  
- **Glean Assistant + Context Graph / Enterprise Graph**：官方强调 personalized、permissions-aware assistant，以及把人、文档、项目、流程、事件连接起来的 context graph / enterprise graph。citeturn28search5turn28search8turn28search9turn28search12turn28search21  
- **Pi-chat / persistent workspace 模式**：虽然它不是企业产品，但它已经验证了“每个对话通道绑定一个持久 workspace、memory、skills”这种技术范式。citeturn31search3

所以，我的建议是：**你们可以把“默认个人 agent”作为产品的一等公民，但不要在第一阶段就把它包装成‘数字孪生’。** 更稳妥的表述与实现方式应该是：

- 它代表的是 **用户授权范围内的工作上下文**；  
- 它有 **个人偏好、历史产物、常用模板、个人知识与工具绑定**；  
- 它能在团队工作流里代你起草、解释、补充与追问；  
- 但关键提交、对外发布、跨系统写操作仍应走审批与显式确认。citeturn28search3turn28search10turn28search21turn25search15turn39search21

### 消息提醒机制是否成熟

是的，**消息提醒与状态编排这块是成熟的，不是难点**。真正的难点不在“能不能发通知”，而在“哪些状态需要通知、通知的卡片结构是什么、如何避免打扰、如何和审批闭环”。

从公开能力看：

- **Slack** 有 incoming webhooks、`chat.postMessage`、`chat.postEphemeral`、App Home 和 Events API；  
- **Teams** 有 Adaptive Cards / proactive notification；  
- **Google Chat** 有 webhook、cards 和交互事件；  
- **Google Workspace / Gmail / Drive / Calendar** 还有 push notification / Pub/Sub 的资源变更机制。citeturn29search0turn29search6turn29search18turn29search21turn29search3turn29search1turn29search4turn29search10turn29search2turn29search8turn29search14turn29search11turn29search17turn29search20

因此建议你们把消息层设计成 **事件总线 + 多通道路由**：

| 事件类型 | 首选通道 | 说明 |
|---|---|---|
| **研究完成** | 站内 Inbox + Slack/Teams/Chat 卡片 | 给用户一个“研究摘要 + 关键引用 + 下一步建议”。 |
| **评审发起** | 团队群卡片 + 给 reviewer 的 direct notification | 必须带“AI 动画讲解入口 + 风险评估摘要 + 截止时间”。 |
| **需要人工确认的写操作** | Direct message + 审批卡片 | 例如发布到正式规范库、同步到 Jira/Figma/GitHub 等。 |
| **风险预警 / SLA 超期** | 群通知 + 负责人直达 | 例如需求长期卡在某个评审节点。 |
| **定稿完成** | 团队公告 + 系统回写通知 | 同步后续研发/设计系统。 |

这套机制在工程上很成熟，关键是**通知对象、提醒级别、卡片字段和反骚扰策略**要产品化做出来，而不要停留在“发个 webhook 文本”。Slack Block Kit、Teams Adaptive Cards、Google Chat cards 都支持足够丰富的结构化通知。citeturn29search9turn29search10turn29search8

## 面向 AI 产品经理团队的目标工作流蓝图

结合上面的调研，我认为你们最终要做的，不是一个“AI 写文档工具”，而是一个 **AI 产品经理团队操作系统**。其核心体验可以压缩成下面这条链路：

| 阶段 | 参与者 | Agent 动作 | 关键产物 |
|---|---|---|---|
| **研究 intake** | 产品经理 + 个人 agent | 拉取历史需求、团队规范、个人偏好、竞品名单，生成调研计划 | 研究任务卡、数据源清单 |
| **深度调研** | 产品经理 + 研究 agent | 公网深搜、团队知识库检索、外部系统取数、竞品结构化摘录 | 竞品分析包、问题树、证据引用 |
| **初稿生成** | 起草 agent | 生成 PRD 初稿、用户故事、验收标准、风险点 | Markdown/HTML 版 PRD 初稿 |
| **协同评审** | 团队 agent / reviewer agent | 按模板做一致性检查、风险评估、规范校验、歧义追问 | Review comments、评分卡、修订建议 |
| **自我讲解** | Explain agent | 读取 PRD + 评审上下文，生成 Mermaid、SVG、HTML 动画讲解页，必要时联动 Figma | 演示页、讲解脚本、视觉摘要 |
| **初审定稿** | 高级负责人 + 审核 agent | 先看 AI 讲解，再看风险评估与原文，进行审批、追问或退回 | 定稿意见、审批结果 |
| **发布与同步** | 发布 agent | 将定稿同步到规范库、项目系统、设计系统、消息系统 | 定稿版本、变更记录、通知包 |

这个链路并不是纸上谈兵。它本质上是在把已经在不同产品中验证的模式重新组合：  
研究与知识引用来自 OpenAI Deep Research / file search、Claude Research/Integrations、RAGFlow 与 Glean；  
个人与组织上下文来自 Work IQ、Slackbot、Glean context graph；  
多步骤流程与 agent 编排来自 Google Workspace Flows、LangGraph、CrewAI、Dify；  
连接与治理来自 MCP、GitHub MCP Registry、Figma MCP Server、Playwright MCP；  
讲解产物来自 Mermaid、SVG、HTML animation。citeturn39search16turn39search0turn39search18turn17view1turn28search8turn28search3turn28search10turn38view2turn14view2turn13view0turn14view3turn22view2turn25search2turn23search19turn37view1turn24search2turn24search8

### 推荐的产品与架构落地路线

我建议你们按三阶段推进，而不是一次性追求“全自动数字 PM 团队”。

**近期阶段**  
先做成一个能跑起来的“研究—起草—协同评审”闭环。  
最推荐的组合是：**Dify / FastGPT / RAGFlow** 三选一承接平台壳与知识层；**Pi** 或 **OpenAI Agents SDK** 承接个人 agent runtime；**Docling + MarkItDown + OCRmyPDF** 承接文档栈；**Slack/Teams/Google Chat** 承接通知。这样最快能验证团队是否真的愿意在同一个平台里从调研走到评审。citeturn14view3turn16view2turn17view1turn19view0turn21view0turn33view0turn33view1turn33view2turn29search0turn29search1turn29search2

**中期阶段**  
在验证日常使用后，再把“每个用户默认一个 agent”“个人空间与团队空间双层”“Explain agent 生成讲解包”“Figma/网页联动”“MCP registry 与 allowlist”做上来。这个阶段的目标不是更炫，而是让平台真正具备组织执行力。citeturn28search21turn23search19turn25search2turn25search15

**远期阶段**  
最后再做“多 agent 互相协作”与“用户代理更像数字分身”的能力，主要依赖 **A2A + context graph + 更强的审批/审计与代理分析**。我建议把这部分作为长期竞争壁垒，而不是第一期必达目标。citeturn27search0turn27search7turn28search8turn39search21

### 最后的产品建议

如果只让我给一条最实用的路线图建议，那就是：

**不要把“写 PRD”当核心能力，把“让需求在组织中被理解、被质询、被讲解、被定稿”当核心能力。**

你们真正的差异化，不会来自“agent 能不能写一份像样的文档”，而会来自以下四件事是否被同时完成：

1. **每个用户都有默认 agent，但权限清晰、上下文可控**；  
2. **个人空间、团队空间、评审空间三层分离**；  
3. **文档与讲解是同一条产物链，而不是两个系统**；  
4. **skills / MCP / 审批 / 消息提醒形成统一治理面**。  

这四件事一旦打通，你们做的就不再是“AI 文档工具”，而是一个真正的 **agent-native 产品需求工作平台**。这个方向，和当前大厂与开源社区正在验证的方向是同向的。citeturn39search2turn28search3turn38view2turn28search22turn9search8turn22view2turn25search2turn17view1turn14view3

## 开放问题与局限

本轮调研已经可以支持产品方向与架构判断，但仍有几处需要后续在立项前再做一次专项确认：

- **墨刀等国内原型工具的官方 MCP 能力**：本次公开资料中，Figma MCP 的公开成熟度非常高，但我没有在这轮资料里拿到同等清晰、同等官方的墨刀 MCP 证据，因此当前更推荐把 **Figma 作为一等集成目标**，把其他原型工具放在二阶段通过 API 或浏览器适配。  
- **厂商产品包装变化很快**：尤其是 Anthropic、OpenAI、Google、Microsoft 的 agent 产品在 2025–2026 年变化频率很高，正式采购前应再复核一次当前 plan、权限边界与企业功能可用性。Anthropic、Google、OpenAI 的公开说明与 release notes 都体现出这一点。citeturn39search14turn38view0turn39search16  
- **“数字孪生”更像长期愿景而非现成品类**：当前市场上更成熟的是“代表用户的授权代理”，而不是全自动替身。Slackbot、Work IQ、Glean context graph 都非常接近你们设想，但还没有一个公开产品完全等于“需求层面的数字孪生 PM”。citeturn28search10turn28search3turn28search8