# 管理员手册 / Admin Guide

<p align="center">
	<a href="#中文"><strong>中文</strong></a>
	<span> | </span>
	<a href="#english"><strong>English</strong></a>
</p>

---

本手册面向 **系统管理员(admin)** 角色，讲解「AI 需求评审工作流平台」管理后台的每一项功能、解决的管理问题与最佳实践。配置项的完整定义见 [configuration.md](./configuration.md),安全模型细节见 [security.md](./security.md),端点签名与请求/响应体见 [api-reference.md](./api-reference.md)。

---

<a id="中文"></a>

## 中文

### 目录

- [1. 角色与权限模型](#1-角色与权限模型)
- [2. 管理员初始化与登录](#2-管理员初始化与登录)
- [3. 用户管理](#3-用户管理)
- [4. 模型管理](#4-模型管理)
- [5. Prompt 管理](#5-prompt-管理)
- [6. Skill 管理](#6-skill-管理)
- [7. 治理与运营(重点)](#7-治理与运营重点)
  - [7.1 成本统计](#71-成本统计)
  - [7.2 质量统计](#72-质量统计)
  - [7.3 工作空间预算与告警](#73-工作空间预算与告警)
  - [7.4 Agent 生命周期治理](#74-agent-生命周期治理)
  - [7.5 权限审计日志](#75-权限审计日志)
- [8. Agent 管理](#8-agent-管理)
- [9. Pi Agent 能力模块](#9-pi-agent-能力模块)
- [10. 品牌定制](#10-品牌定制)
- [11. 系统统计与排障](#11-系统统计与排障)
- [12. 安全清单](#12-安全清单)

---

### 1. 角色与权限模型

系统内置两种角色,二者权限差异显著:

| 角色 | 可访问范围 | 典型用途 |
| --- | --- | --- |
| `user` | 业务功能(对话、需求评审、知识库)、个人 Agent 设置 | 日常评审、协作 |
| `admin` | 上述全部 **+ `/api/admin/*` + `/api/governance/*` + 全局 Agent/MCP/品牌配置** | 平台运维、治理 |

关键事实:

- 所有 `/api/admin` 与 `/api/governance` 端点在入口处都调用 `_require_admin(user)`,非 admin 一律返回 `403 需要管理员权限`。
- 注册接口(`/api/auth/register`)创建的新用户**固定为 `role="user"`**,注册**不再**自动提权为管理员,任何人无法通过自助注册获取 admin 身份。
- 默认管理员账号 `admin` 受保护,不可通过 API 删除(返回 `400 不能删除默认管理员`)。

> 安全提示:管理员账号拥有读取脱敏 API Key、修改预算硬限、审批高风险工具等高敏感操作权限,请严格控制授予范围,并定期复核权限审计日志(见 [7.5](#75-权限审计日志))。

---

### 2. 管理员初始化与登录

平台在首次启动时会**自动确保**默认管理员账号存在,初始密码来源如下(优先级从高到低):

| 来源 | 说明 |
| --- | --- |
| 环境变量 `ADMIN_INITIAL_PASSWORD` | **推荐**。启动时读取,创建/覆盖 admin 密码。 |
| 代码默认口令 `admin@2026` | 未设置环境变量时使用,启动日志会打印 `[SECURITY]` 警告,要求尽快修改。 |

启动时的安全检测:

- 若检测到 admin 仍在使用默认口令 `admin@2026` 或历史弱口令 `admin123`,日志会持续输出 `[SECURITY]` 警告,提示立即修改。

**生产环境上线步骤(强烈建议):**

1. **关闭公开注册**:在 `src/config.yaml` 中将 `auth.allow_public_registration` 设为 `false`(默认为 `true`)。这样可防止未授权人员通过自助注册抢占账号,首个管理员应通过**离线方式**(如运维线下交付、LDAP 对接)初始化。
2. **设置强初始密码**:通过 `ADMIN_INITIAL_PASSWORD` 环境变量注入强密码后启动。
3. **首次登录即改密**:登录后立即通过「修改密码」功能重置,避免环境变量泄露风险。

```bash
# 示例:启动前注入强密码并关闭公开注册
export ADMIN_INITIAL_PASSWORD='<你的强随机口令>'
# 在 src/config.yaml 中:auth.allow_public_registration: false
./start.sh
```

---

### 3. 用户管理

接口前缀 `/api/admin/users`,管理员可对账号进行全生命周期管理。

| 操作 | 方法与端点 | 说明 |
| --- | --- | --- |
| 列出全部用户 | `GET /users` | 返回 id、username、role、is_active、创建时间、最近活跃时间 |
| 创建用户 | `POST /users` | 用户名 2–50 字符,密码 6–128 字符,角色 `user` 或 `admin` |
| 更新用户 | `PUT /users/{user_id}` | 可改角色、启用/禁用(`is_active`)、重置密码 |
| 删除用户 | `DELETE /users/{user_id}` | 默认 `admin` 账号不可删除 |

常用管理动作:

- **入职开号**:管理员统一创建账号,避免公开注册引入未知身份。
- **权限收回/停用**:将 `is_active` 设为 `false`,该用户登录被拒(`403 用户已被禁用`)。
- **临时授权**:为某成员临时授予 `admin` 角色,事后及时降级。

> 注意:用户名唯一;`role` 字段被正则限制为 `user|admin`,无法注入非法角色。

---

### 4. 模型管理

接口前缀 `/api/admin/models`。这里管理的是「通用对话/评审模型」,即用户在前端选择框看到的模型列表。默认模型由 `src/config.yaml` 的 `defaults.model` 指定(当前为 `deepseek`)。

| 操作 | 方法与端点 | 说明 |
| --- | --- | --- |
| 列出模型 | `GET /models` | API Key **脱敏显示**(如 `sk-****...ab12`),绝不回显明文 |
| 创建模型 | `POST /models` | provider 默认 `openai_compatible`,含 api_base、llm_model、max_tokens(最大输出,1–100000)、context_window(上下文窗口,0=不压缩)、temperature、thinking 等字段 |
| 更新配置 | `PUT /models/{model_id}` | 改名称、base、参数、enabled、thinking 系列字段 |
| 删除模型 | `DELETE /models/{model_id}` | 内置模型走逻辑删除(tombstone),用户自建走物理删除 |
| 调整排序 | `PUT /models/order` | 传入完整 `model_ids` 列表,影响**前端模型列表展示顺序**(把常用模型置顶) |
| 配置 API Key | `PUT /models/{model_id}/api-key` | **加密存储**(基于 JWT secret),返回脱敏串 |
| 测试连接 | `POST /models/{model_id}/test-connection` | 验证 base/key/model 可达,回写 `last_test_status`/`last_test_time` |
| 测速 | `POST /models/{model_id}/speed-test` | 实测端到端延迟,回写 `last_test_latency_ms` |

**启停**:通过 `enabled` 字段控制。禁用的模型不会出现在用户可选列表中,也不会被评审流水线调用。

**thinking 设置(部分模型支持):**

| 字段 | 取值 | 含义 |
| --- | --- | --- |
| `thinking_supported` | bool | 该模型是否支持推理/思考模式 |
| `thinking_adapter` | `none` / `openai_reasoning` / `deepseek_reasoner` / `qwen_thinking` / `custom_json` | 适配不同厂商的思考协议 |
| `thinking_level` | `off` / `low` / `high` | 思考强度 |
| `thinking_payload` | string | 自定义透传 payload(高级用法) |

**管理建议:**

- 上线新模型前,先 **test-connection** 再 **speed-test**,确认延迟可接受后再 `enabled=true`。
- API Key 加密存储,但**密钥强度取决于 JWT secret**。请确保 `JWT_SECRET` 为高强度随机值(详见 [security.md](./security.md))。
- 排序:把团队主力模型(如默认 `deepseek`)置顶,降低用户选择成本。

---

### 5. Prompt 管理

接口前缀 `/api/admin/prompts`。通用 Prompt 与评审 Prompt **分开管理**,均支持创建、更新、删除。

| 操作 | 方法与端点 | 说明 |
| --- | --- | --- |
| 列出 | `GET /prompts` | 含 name、description、system_prompt、user_prompt_template、is_builtin |
| 创建 | `POST /prompts` | 新建自定义模板(`is_builtin=false`) |
| 更新 | `PUT /prompts/{prompt_id}` | 改 system_prompt / user_prompt_template 等 |
| 删除 | `DELETE /prompts/{prompt_id}` | **内置模板不可删除**(返回 `400 不能删除内置模板`) |

字段说明:

- `system_prompt`:注入到 LLM 的系统提示词,定义助手人设与行为约束。
- `user_prompt_template`:**用户级模板**,支持占位符,用于将用户输入包装成结构化请求。

**管理建议:** 评审类 Prompt 变更影响所有评审结果质量,建议在测试环境验证后再推到生产;保留内置模板作为回退基线。

---

### 6. Skill 管理

接口分两组:`/api/admin/skills`(元数据维护)与 `/api/governance/skills`(治理状态流转)。

系统内置 **6 个评审技能**,构成完整的需求评审流水线:

| Skill | 作用 |
| --- | --- |
| `docx-to-markdown` | 将上传的 docx 需求文档解析为 Markdown |
| `prd-overview-classify` | 需求总览与分类 |
| `prd-per-analysis` | 逐条需求深度分析 |
| `system-review` | 系统级评审(架构/可行性) |
| `requirement-insights` | 需求洞察提炼 |
| `report-generator` | 生成评审报告 |

管理操作:

| 操作 | 方法与端点 | 说明 |
| --- | --- | --- |
| 查看/更新元数据 | `GET /skills`、`PUT /skills/{skill_id}` | 维护 `update_url`(技能更新源)等 |
| 启停(admin) | `PUT /skills/{skill_id}/toggle` | `status` ∈ {`active`,`inactive`} |
| 状态流转(governance) | `PUT /governance/skills/{skill_db_id}/status` | `status` ∈ {`active`,`inactive`,`published`,`draft`,`deprecated`} |

**禁用后果(评审启动前置门控):**

- 禁用必需 Skill(`prd-overview-classify`/`prd-per-analysis`/`system-review`/`report-generator`)任一后,用户发起评审会被 **409 拒绝**(「必需 Skill 已被禁用,无法发起审查…」),需重新启用后才能发起。
- 禁用 `requirement-insights` 后,`insight`/`full`/`draft` 模式的评审会**跳过需求洞察步骤降级运行**,任务终态为 `completed_with_warnings`;降级记录见任务 `step_details` 的 `planned_degraded_steps`(创建时)与 `degraded_steps`(执行时)。

**回归测试框架(保障技能迭代质量):**

技能迭代有回归风险。项目内置 `tests/test_skill_regression.py` **参数化回归测试框架**:每个 Skill 绑定样例文档与期望输出结构,升级前自动验证,避免改动一个 Skill 导致整条评审流水线退化。

```bash
# 升级或修改 Skill 后运行回归测试
pytest tests/test_skill_regression.py -v
```

**管理建议:** 任何 Skill 改动后,务必先跑回归测试;`deprecated` 状态用于灰度下线,先标记再择期移除。

---

### 7. 治理与运营(重点)

接口前缀 `/api/governance`。这是管理后台**价值最高的部分**,回答平台运营的核心问题:花了多少钱、质量如何、预算是否超支、谁改了什么权限。所有端点均要求 admin。

#### 7.1 成本统计

由 `CostStatsService` 提供。底层依赖 LLM 会话日志(`llm_sessions.jsonl`),每条记录携带可信归属字段:`workspace_id`、`user_id`、`mode`,并按 **(workspace, user, mode, model)** 四元组聚合。

| 端点 | 用途 |
| --- | --- |
| `GET /governance/cost/daily?start_date=&end_date=` | 每日成本(支持每日/每周/自定义范围) |
| `GET /governance/cost/total` | 全局汇总 |
| `POST /governance/cost/aggregate?date_str=` | 手动触发某日聚合(补数/重算) |

**业务价值:** 回答「哪个团队/哪个人/哪种调用模式(chat vs review vs agent)消耗了预算」,支撑成本分摊与模型选型决策。`mode` 在日志缺失时由 model 名推断(review/agent/pi-agent 等)。

#### 7.2 质量统计

由 `QualityStatsService` 提供,基于 `DocAnalysis` 的质量评分(`quality_score`),按**周**聚合与趋势查询。

| 端点 | 用途 |
| --- | --- |
| `GET /governance/quality/weekly?start_week=&end_week=` | 每周质量统计与趋势 |

**业务价值:** 质量评分趋势可反映 Prompt/Skill 调整是否带来评审质量提升或退化,是除了成本之外衡量平台 ROI 的另一关键指标。

#### 7.3 工作空间预算与告警

`WorkspaceBudget` + `BudgetGuard` 提供**硬限执行**能力,真正把「预算」从报表变成可执行的约束。

| 端点 | 用途 |
| --- | --- |
| `GET /governance/budget/{workspace_id}` | 查询配额与当月已用 token |
| `PUT /governance/budget/{workspace_id}` | 设置配额 |

预算字段:

| 字段 | 含义 |
| --- | --- |
| `monthly_token_limit` | 月度 token 上限 |
| `monthly_cost_limit` | 月度成本上限 |
| `warning_threshold_pct` | 预警阈值(默认 80%) |
| `hard_limit_action` | `notify`(仅告警) 或 `block`(硬封) |

**硬限执行逻辑(`budget_guard.py`):** 当 `hard_limit_action=block` 且当月用量达到上限时,`ensure_workspace_llm_allowed` 会**在 LLM/Agent 调用前拦截**,返回 `429 团队本月 token 配额已用尽`,从源头止血。

**防绕过:** 聊天(`/api/chat`)与审查启动(`POST /api/review/projects/{project_id}/reviews`)在调用 LLM 前都会:

1. 校验调用者对该 `workspace_id` 的成员资格(`require_action(member, "read")`),**拒绝伪造 workspace_id 绕过配额**;
2. 调用 `ensure_workspace_llm_allowed` 执行硬限。

即使用户尝试传入他人 workspace_id,也会因成员校验失败而被拒。审查管线会触发数十次 LLM 调用,因此审查入口同样受硬限约束。

**管理建议:** 对预算敏感的团队,默认用 `notify` 观察,稳定后对高消耗团队切到 `block`;阈值先设 80% 留缓冲。

#### 7.4 Agent 生命周期治理

Agent Profile 有状态流转,治理页负责**归档与退役**:

| 端点 | 用途 |
| --- | --- |
| `GET /governance/agents?status=` | 列出 Agent Profile(按状态过滤) |
| `PUT /governance/agent/{agent_id}/archive` | 退役(`disabled` → `archived`) |

**退役约束(安全):**

- 只有 `disabled` 状态的 Agent 才能退役;
- 退役前在**行锁内**再次检查是否存在 `planning`/`running` 状态的活跃运行,避免 TOCTOU 竞态导致在途任务被归档。

**业务价值:** 防止废弃 Agent 残留授权、造成权限盲区与历史运行难以追溯。

#### 7.5 权限审计日志

| 端点 | 用途 |
| --- | --- |
| `GET /governance/permissions/audit` | 汇总 Workspace 角色变更 + Agent 授权变更 |

返回:

- `workspace_members`:各 workspace 成员的 user_id / workspace_id / role / status;
- `agent_authorizations`:各 Agent 的 scope_type / granted_by / permissions。

**业务价值:** 回答「谁给谁授予了什么权限、谁被加进了哪个团队、Agent 被授予了哪些数据访问范围」,是合规审计与权限回收的核心依据。建议定期导出复核。

---

### 8. Agent 管理

Agent 管理涉及 `/api/agent/*` 与全局 MCP 配置。管理员负责配置 Agent 身份、系统策略、授权范围、可用工具,并处理高风险工具的审批。

#### 8.1 Agent Profile 与授权范围

| 概念 | 说明 |
| --- | --- |
| Agent Profile | 定义身份(name)、系统策略(system_policy)、可用工具白名单、默认授权范围 |
| 授权(Authorization) | 授予 Agent 在某个 scope(workspace/project/personal)的权限(read/write/search/execute) |
| `default_scope_type` | `personal`(仅个人资料)或 `workspace`(团队空间) |

**工具白名单(deny-by-default):** `allowed_tools` 为空列表时,**仅保留 `rag_search`**,默认最小权限。

#### 8.2 高风险工具(安全重点)

以下工具属于高风险,**普通用户不可自行启用**,必须由管理员配置,且调用时需**独立审批人**:

| 高风险工具 | 风险 |
| --- | --- |
| `bash` | 任意命令执行 |
| `write` | 写入/覆盖文件 |
| `edit` | 修改文件内容 |
| `read` | 读取敏感文件 |

防护机制(代码强制):

1. 非管理员更新 `allowed_tools` 时,系统**自动剔除**上述高风险工具;若剔除后为空,回落到 `["rag_search"]`。
2. 高风险工具调用产生审批请求时,**申请人不得自行审批**,必须由另一名(指定)审批人决策,否则返回 `403 高风险工具不可由申请人自行审批`。

#### 8.3 工具调用审批

| 端点 | 用途 |
| --- | --- |
| `GET /api/agent/approvals` | 查看待审批请求(仅返回当前用户作为审批人的) |
| `POST /api/agent/approvals/{request_id}/decide` | 审批决策(`approved`/`rejected`) |

审批通过后,系统通过 `grant_one_shot_approval` 发放**一次性放行**并恢复挂起的执行。

#### 8.4 运行历史

| 端点 | 用途 |
| --- | --- |
| `GET /api/agent/runs` | 列出当前用户的运行历史(状态、步数、工具调用次数、耗时) |
| `GET /api/agent/runs/{run_id}` | 运行详情(含 steps、traces) |

#### 8.5 MCP 外部工具服务

| 端点 | 权限要求 |
| --- | --- |
| `GET/POST /api/agent/mcp/servers` | 全局配置需 admin;workspace 级需该空间 `manage` 权限 |
| `GET/POST /api/agent/mcp/servers/{server_id}/policies` | 工具级策略:`allowed_roles`、`requires_approval`、`risk_level` |

管理员可定义每个 MCP 工具的 `risk_level` 与是否 `requires_approval`,统一管控外部工具风险敞口。

**管理建议:** Agent 工具遵循最小授权原则;高风险工具仅在确有需要时为特定 Agent 开启,并指定可靠的独立审批人。

---

### 9. Pi Agent 能力模块

接口前缀 `/api/pi-agent`。Pi Agent 是独立于通用模型配置的**能力模块**,管理员集中管理其 LLM / 搜索 / 视觉三类能力及 Extension、Skills 安装。

| 能力域 | 可配置项 |
| --- | --- |
| LLM | provider、api_base、model、max_tokens、temperature、加密 API Key |
| 搜索(Search) | 是否启用、provider、api_base、max_results、加密 API Key |
| 视觉(Vision) | 是否启用、provider、api_base、model、加密 API Key |
| Extension | extension_path、max_tool_calls(1–50)、blocked_tools |
| Skills | install_dir、registry_url、installed_list |
| 通用 | system_prompt、enabled |

常用操作:

| 操作 | 方法与端点 | 说明 |
| --- | --- | --- |
| 查看/更新配置 | `GET/PUT /pi-agent/config` | 仅传入字段被更新 |
| 配置 LLM Key | `PUT /pi-agent/config/llm-api-key` | 加密存储 |
| 配置 Search/Vision Key | `PUT /pi-agent/config/search-api-key`、`/vision-api-key` | 传空值可清除 |
| 测试连接 | `POST /pi-agent/config/test-connection` | 仅支持 OpenAI 兼容协议 provider;可选请求体 `api_key`/`llm_provider`/`llm_api_base`/`llm_model` 用于先测后存 |
| 测速 | `POST /pi-agent/config/speed-test` | 同上限制与可选请求体 |

> 注意:连接测试/测速**仅支持 OpenAI 兼容协议**的 provider(如 deepseek/openai/openai_compatible);其他 provider(如 Anthropic)会返回明确的「不支持」状态,而非误导性错误。表单里新填的 Key 可在**保存前**测试:临时值只在本次请求内存中使用,不落库、不更新 `last_test_status`、不写日志;响应含 `config_saved=false` 时,成功文案为「连接成功 ✓（当前配置尚未保存）」。未传字段回退数据库已保存配置。

---

### 10. 品牌定制

品牌通过运行时配置文件管理,详见 [configuration.md](./configuration.md)。

**配置文件:** `runtime/config/ui-branding.yaml`(可由 `runtime/config/ui-branding.example.yaml` 复制而来)。

**优先级:** `runtime/config/ui-branding.yaml` > `src/config.yaml` 的 `ui_branding` 段 > 代码默认值。

可定制项:app_title、login_title/login_subtitle/login_notice、topbar_title、主题色(primary/primary_hover/accent)、logo/favicon(资产放 `runtime/assets/branding/`,只填文件名,**禁止绝对路径、`..` 穿越或外部 URL**)。

**管理后台品牌页**提供模板导出与配置指引;**品牌迁移工具**用于批量调整:

```bash
python3 tools/migrate_branding.py
```

---

### 11. 系统统计与排障

| 端点 | 用途 |
| --- | --- |
| `GET /api/admin/stats` | 系统统计:用户数、会话数、消息数 + 最近 7 天访问记录(最多 50 条) |

`recent_visits` 包含 timestamp、username、action、method、path、client_ip、result,用于**轻量运维与排障**(如排查「谁在什么时候调了哪个接口、成功还是失败」)。

> 该统计基于审计日志读取,不涉及敏感明文,适合日常巡检。

---

### 12. 安全清单

上线前/定期复核的安全要点:

- [ ] `allow_public_registration` 生产环境设为 `false`,管理员离线初始化。
- [ ] 通过 `ADMIN_INITIAL_PASSWORD` 注入强密码,首次登录即改密;确认日志无 `[SECURITY]` 弱口令警告。
- [ ] `JWT_SECRET` 为高强度随机值(API Key、SSE 票据加密均依赖它)。
- [ ] 模型 API Key 已配置且 `test-connection` 通过;非必要模型 `enabled=false`。
- [ ] 高风险工具(bash/write/edit/read)未对普通用户开放,审批人配置到位。
- [ ] 高消耗 workspace 预算 `hard_limit_action=block`,阈值合理。
- [ ] 定期导出 `/governance/permissions/audit` 复核权限授予。
- [ ] 退役 Agent 已 `archived`,无残留授权。

更多安全模型细节(鉴权、加密、SSRF 防护等)见 [security.md](./security.md)。

---

<a id="english"></a>

## English

### Table of Contents

- [1. Roles & Permission Model](#1-roles--permission-model)
- [2. Admin Initialization & Login](#2-admin-initialization--login)
- [3. User Management](#3-user-management)
- [4. Model Management](#4-model-management)
- [5. Prompt Management](#5-prompt-management)
- [6. Skill Management](#6-skill-management)
- [7. Governance & Operations (Key)](#7-governance--operations-key)
  - [7.1 Cost Statistics](#71-cost-statistics)
  - [7.2 Quality Statistics](#72-quality-statistics)
  - [7.3 Workspace Budget & Alerts](#73-workspace-budget--alerts)
  - [7.4 Agent Lifecycle Governance](#74-agent-lifecycle-governance)
  - [7.5 Permission Audit Log](#75-permission-audit-log)
- [8. Agent Management](#8-agent-management)
- [9. Pi Agent Capability Module](#9-pi-agent-capability-module)
- [10. Branding](#10-branding)
- [11. System Stats & Troubleshooting](#11-system-stats--troubleshooting)
- [12. Security Checklist](#12-security-checklist)

---

### 1. Roles & Permission Model

The system ships with two roles with very different capabilities:

| Role | Access | Typical use |
| --- | --- | --- |
| `user` | Business features (chat, requirement review, knowledge base), personal Agent settings | Daily review, collaboration |
| `admin` | All of the above **+ `/api/admin/*` + `/api/governance/*` + global Agent/MCP/branding config** | Platform ops, governance |

Key facts:

- Every `/api/admin` and `/api/governance` endpoint calls `_require_admin(user)` at the entry point; non-admins always get `403 admin permission required`.
- The registration endpoint (`/api/auth/register`) creates new users **with a fixed `role="user"`**. Registration **no longer** auto-promotes to admin — nobody can obtain admin privileges via self-registration.
- The default `admin` account is protected and **cannot be deleted** via the API (returns `400 cannot delete default admin`).

> Security note: The admin account can read masked API Keys, modify hard budget limits, and approve high-risk tools. Grant it sparingly and periodically review the permission audit log (see [7.5](#75-permission-audit-log)).

---

### 2. Admin Initialization & Login

On first start, the platform **automatically ensures** the default admin account exists. The initial password is resolved as follows (highest priority first):

| Source | Description |
| --- | --- |
| Env var `ADMIN_INITIAL_PASSWORD` | **Recommended.** Read at startup to create/override the admin password. |
| Code default `admin@2026` | Used when the env var is unset; startup logs print a `[SECURITY]` warning urging an immediate change. |

Startup security checks:

- If admin is still using the default `admin@2026` or legacy weak `admin123`, logs keep emitting `[SECURITY]` warnings prompting an immediate password change.

**Recommended production onboarding:**

1. **Disable public registration**: set `auth.allow_public_registration` to `false` in `src/config.yaml` (defaults to `true`). This prevents unauthorized people from grabbing accounts via self-registration; the first admin should be initialized **offline** (e.g., ops handoff, LDAP integration).
2. **Set a strong initial password**: inject it via the `ADMIN_INITIAL_PASSWORD` env var before startup.
3. **Change password on first login**: reset immediately after login to avoid env-var leakage risk.

```bash
# Example: inject a strong password and disable public registration before startup
export ADMIN_INITIAL_PASSWORD='<your-strong-random-password>'
# In src/config.yaml: auth.allow_public_registration: false
./start.sh
```

---

### 3. User Management

Prefix `/api/admin/users`. Admins manage the full account lifecycle.

| Action | Method & Endpoint | Notes |
| --- | --- | --- |
| List all users | `GET /users` | Returns id, username, role, is_active, created/last-active timestamps |
| Create user | `POST /users` | Username 2–50 chars, password 6–128 chars, role `user` or `admin` |
| Update user | `PUT /users/{user_id}` | Change role, enable/disable (`is_active`), reset password |
| Delete user | `DELETE /users/{user_id}` | The default `admin` account cannot be deleted |

Common actions:

- **Onboarding**: admins create accounts centrally instead of relying on public registration.
- **Offboarding/disable**: set `is_active=false`; login is then rejected (`403 user disabled`).
- **Temporary grant**: temporarily elevate a member to `admin` and demote afterwards.

> Note: usernames are unique; `role` is constrained by regex to `user|admin` — no rogue roles can be injected.

---

### 4. Model Management

Prefix `/api/admin/models`. This manages the "general chat/review models" shown in the frontend selector. The default model is defined by `defaults.model` in `src/config.yaml` (currently `deepseek`).

| Action | Method & Endpoint | Notes |
| --- | --- | --- |
| List models | `GET /models` | API Key shown **masked** (e.g., `sk-****...ab12`); plaintext is never returned |
| Create model | `POST /models` | provider defaults to `openai_compatible`; includes api_base, llm_model, max_tokens (max output, 1–100000), context_window (context window; 0 = no compression), temperature, thinking, etc. |
| Update config | `PUT /models/{model_id}` | Change name, base, params, enabled, thinking fields |
| Delete model | `DELETE /models/{model_id}` | Built-in models are soft-deleted (tombstone); user-created ones are physically deleted |
| Reorder | `PUT /models/order` | Send the full `model_ids` list; controls **frontend display order** (pin frequently used models on top) |
| Set API Key | `PUT /models/{model_id}/api-key` | **Encrypted at rest** (based on JWT secret); returns a masked string |
| Test connection | `POST /models/{model_id}/test-connection` | Verifies base/key/model reachability; persists `last_test_status`/`last_test_time` |
| Speed test | `POST /models/{model_id}/speed-test` | Measures end-to-end latency; persists `last_test_latency_ms` |

**Enable/disable**: controlled by the `enabled` field. Disabled models disappear from the user-facing selector and are never invoked by the review pipeline.

**Thinking settings (model-dependent):**

| Field | Values | Meaning |
| --- | --- | --- |
| `thinking_supported` | bool | Whether the model supports reasoning/thinking mode |
| `thinking_adapter` | `none` / `openai_reasoning` / `deepseek_reasoner` / `qwen_thinking` / `custom_json` | Adapts to vendor-specific thinking protocols |
| `thinking_level` | `off` / `low` / `high` | Thinking intensity |
| `thinking_payload` | string | Custom passthrough payload (advanced) |

**Recommendations:**

- Before enabling a new model, run **test-connection** then **speed-test**; only set `enabled=true` once latency is acceptable.
- API Keys are encrypted, but **strength depends on the JWT secret**. Ensure `JWT_SECRET` is a high-entropy random value (see [security.md](./security.md)).
- Reorder: pin the team's primary model (e.g., the default `deepseek`) on top to reduce selection friction.

---

### 5. Prompt Management

Prefix `/api/admin/prompts`. General and review Prompts are **managed separately**; both support create/update/delete.

| Action | Method & Endpoint | Notes |
| --- | --- | --- |
| List | `GET /prompts` | Includes name, description, system_prompt, user_prompt_template, is_builtin |
| Create | `POST /prompts` | Creates a custom template (`is_builtin=false`) |
| Update | `PUT /prompts/{prompt_id}` | Change system_prompt / user_prompt_template, etc. |
| Delete | `DELETE /prompts/{prompt_id}` | **Built-in templates cannot be deleted** (returns `400 cannot delete builtin template`) |

Field notes:

- `system_prompt`: injected into the LLM as the system prompt, defining persona and behavior constraints.
- `user_prompt_template`: a **user-level template** supporting placeholders to wrap user input into structured requests.

**Recommendation:** Review Prompt changes affect every review outcome. Validate in a test environment before promoting to production; keep built-in templates as a fallback baseline.

---

### 6. Skill Management

Two endpoint groups: `/api/admin/skills` (metadata maintenance) and `/api/governance/skills` (governance state transitions).

The system ships **6 built-in review skills** forming the complete requirement-review pipeline:

| Skill | Purpose |
| --- | --- |
| `docx-to-markdown` | Parse uploaded docx requirement docs into Markdown |
| `prd-overview-classify` | Requirement overview & classification |
| `prd-per-analysis` | Per-requirement deep analysis |
| `system-review` | System-level review (architecture/feasibility) |
| `requirement-insights` | Requirement insight extraction |
| `report-generator` | Generate the review report |

Management actions:

| Action | Method & Endpoint | Notes |
| --- | --- | --- |
| View/update metadata | `GET /skills`, `PUT /skills/{skill_id}` | Maintain `update_url` (skill update source), etc. |
| Toggle (admin) | `PUT /skills/{skill_id}/toggle` | `status` ∈ {`active`,`inactive`} |
| State transition (governance) | `PUT /governance/skills/{skill_db_id}/status` | `status` ∈ {`active`,`inactive`,`published`,`draft`,`deprecated`} |

**Consequences of disabling (review-start gate):**

- Disabling any required skill (`prd-overview-classify`/`prd-per-analysis`/`system-review`/`report-generator`) makes review starts fail with **409** ("required skill(s) disabled ..."); it must be re-enabled before reviews can start.
- Disabling `requirement-insights` makes `insight`/`full`/`draft` reviews **skip the requirement-insights step and run degraded**, with a final status of `completed_with_warnings`; the degradation record is in the task's `step_details` — `planned_degraded_steps` (at creation) and `degraded_steps` (at execution).

**Regression test framework (safeguarding skill iteration quality):**

Skill iteration carries regression risk. The project ships `tests/test_skill_regression.py`, a **parameterized regression framework**: each Skill is bound to sample docs and expected output structures, auto-verified before any upgrade to prevent a single Skill change from degrading the whole review pipeline.

```bash
# Run regression tests after upgrading or modifying any Skill
pytest tests/test_skill_regression.py -v
```

**Recommendation:** Always run regression tests after any Skill change. Use the `deprecated` state for gradual sunset — mark first, remove later.

---

### 7. Governance & Operations (Key)

Prefix `/api/governance`. This is the **highest-value** part of the admin console, answering the core ops questions: how much was spent, what's the quality, are budgets exceeded, and who changed which permissions. All endpoints require admin.

#### 7.1 Cost Statistics

Provided by `CostStatsService`. Backed by LLM session logs (`llm_sessions.jsonl`); each entry carries trusted attribution fields — `workspace_id`, `user_id`, `mode` — and is aggregated by the **(workspace, user, mode, model)** tuple.

| Endpoint | Purpose |
| --- | --- |
| `GET /governance/cost/daily?start_date=&end_date=` | Daily cost (daily/weekly/custom range supported) |
| `GET /governance/cost/total` | Global totals |
| `POST /governance/cost/aggregate?date_str=` | Manually trigger aggregation for a given day (backfill/recompute) |

**Business value:** Answers "which team/person/call mode (chat vs review vs agent) consumed the budget," supporting cost allocation and model-selection decisions. When `mode` is missing in the log, it is inferred from the model name (review/agent/pi-agent, etc.).

#### 7.2 Quality Statistics

Provided by `QualityStatsService`, based on `DocAnalysis` quality scores (`quality_score`), aggregated **weekly** with trend queries.

| Endpoint | Purpose |
| --- | --- |
| `GET /governance/quality/weekly?start_week=&end_week=` | Weekly quality stats and trends |

**Business value:** Quality-score trends reveal whether Prompt/Skill adjustments improved or degraded review quality — a key ROI indicator alongside cost.

#### 7.3 Workspace Budget & Alerts

`WorkspaceBudget` + `BudgetGuard` provide **hard-limit enforcement**, turning "budget" from a report into an actionable constraint.

| Endpoint | Purpose |
| --- | --- |
| `GET /governance/budget/{workspace_id}` | Query quota and month-to-date token usage |
| `PUT /governance/budget/{workspace_id}` | Set quota |

Budget fields:

| Field | Meaning |
| --- | --- |
| `monthly_token_limit` | Monthly token cap |
| `monthly_cost_limit` | Monthly cost cap |
| `warning_threshold_pct` | Alert threshold (default 80%) |
| `hard_limit_action` | `notify` (alert only) or `block` (hard cutoff) |

**Hard-limit logic (`budget_guard.py`):** when `hard_limit_action=block` and month-to-date usage reaches the limit, `ensure_workspace_llm_allowed` **intercepts before** any LLM/Agent call, returning `429 monthly token quota exhausted`, stopping the bleed at the source.

**Anti-bypass:** Before calling the LLM, chat (`/api/chat`) and review start (`POST /api/review/projects/{project_id}/reviews`) both:

1. Verifies the caller's membership of the target `workspace_id` (`require_action(member, "read")`), **rejecting forged workspace_id to bypass quota**;
2. Calls `ensure_workspace_llm_allowed` to enforce the hard limit.

Even if a user tries to pass someone else's workspace_id, the membership check fails and the request is rejected. The review pipeline triggers dozens of LLM calls, so the review entry point is also under the hard limit.

**Recommendation:** For budget-sensitive teams, start with `notify` to observe, then switch high-consumption teams to `block`; set the threshold at 80% to leave a buffer.

#### 7.4 Agent Lifecycle Governance

Agent Profiles have state transitions; the governance page handles **archive & retirement**:

| Endpoint | Purpose |
| --- | --- |
| `GET /governance/agents?status=` | List Agent Profiles (filter by status) |
| `PUT /governance/agent/{agent_id}/archive` | Retire (`disabled` → `archived`) |

**Retirement constraints (safety):**

- Only `disabled` Agents can be retired;
- Before retiring, active runs in `planning`/`running` state are re-checked **inside a row lock** to avoid TOCTOU races archiving an in-flight task.

**Business value:** Prevents decommissioned Agents from leaving residual authorizations — a blind spot for permissions and historical-run traceability.

#### 7.5 Permission Audit Log

| Endpoint | Purpose |
| --- | --- |
| `GET /governance/permissions/audit` | Summarizes Workspace role changes + Agent authorization changes |

Returns:

- `workspace_members`: each workspace member's user_id / workspace_id / role / status;
- `agent_authorizations`: each Agent's scope_type / granted_by / permissions.

**Business value:** Answers "who granted what to whom, who was added to which team, and what data scopes an Agent was granted" — the core evidence for compliance audits and permission revocation. Export and review periodically.

---

### 8. Agent Management

Agent management spans `/api/agent/*` and global MCP config. Admins configure Agent identity, system policy, authorization scope, and available tools, and handle high-risk tool approvals.

#### 8.1 Agent Profile & Authorization Scope

| Concept | Description |
| --- | --- |
| Agent Profile | Defines identity (name), system policy (system_policy), tool allowlist, default authorization scope |
| Authorization | Grants an Agent permissions (read/write/search/execute) on a scope (workspace/project/personal) |
| `default_scope_type` | `personal` (own files only) or `workspace` (team space) |

**Tool allowlist (deny-by-default):** when `allowed_tools` is an empty list, **only `rag_search` is retained** — least privilege by default.

#### 8.2 High-Risk Tools (Security Focus)

The following tools are high-risk; **ordinary users cannot enable them themselves**. They must be configured by an admin, and each invocation requires an **independent approver**:

| High-risk tool | Risk |
| --- | --- |
| `bash` | Arbitrary command execution |
| `write` | Write/overwrite files |
| `edit` | Modify file contents |
| `read` | Read sensitive files |

Enforced safeguards (in code):

1. When a non-admin updates `allowed_tools`, the system **automatically strips** the high-risk tools above; if the result is empty, it falls back to `["rag_search"]`.
2. When a high-risk tool call generates an approval request, **the requester cannot self-approve** — another designated approver must decide, otherwise `403 high-risk tools cannot be self-approved` is returned.

#### 8.3 Tool-Call Approvals

| Endpoint | Purpose |
| --- | --- |
| `GET /api/agent/approvals` | View pending approvals (only those where the current user is the approver) |
| `POST /api/agent/approvals/{request_id}/decide` | Decision (`approved`/`rejected`) |

On approval, the system issues a **one-shot pass** via `grant_one_shot_approval` and resumes the suspended execution.

#### 8.4 Run History

| Endpoint | Purpose |
| --- | --- |
| `GET /api/agent/runs` | List the current user's run history (status, steps, tool-call count, duration) |
| `GET /api/agent/runs/{run_id}` | Run detail (steps, traces) |

#### 8.5 MCP External Tool Services

| Endpoint | Permission |
| --- | --- |
| `GET/POST /api/agent/mcp/servers` | Global config requires admin; workspace-level requires `manage` permission on that space |
| `GET/POST /api/agent/mcp/servers/{server_id}/policies` | Per-tool policy: `allowed_roles`, `requires_approval`, `risk_level` |

Admins can define each MCP tool's `risk_level` and whether it `requires_approval`, centrally controlling the external-tool risk surface.

**Recommendation:** Follow least privilege for Agent tools; enable high-risk tools only for specific Agents when truly needed, and designate reliable independent approvers.

---

### 9. Pi Agent Capability Module

Prefix `/api/pi-agent`. Pi Agent is a capability module **independent** of the general model config; admins centrally manage its LLM / search / vision capabilities plus Extension and Skills installation.

| Capability | Configurable fields |
| --- | --- |
| LLM | provider, api_base, model, max_tokens, temperature, encrypted API Key |
| Search | enabled, provider, api_base, max_results, encrypted API Key |
| Vision | enabled, provider, api_base, model, encrypted API Key |
| Extension | extension_path, max_tool_calls (1–50), blocked_tools |
| Skills | install_dir, registry_url, installed_list |
| General | system_prompt, enabled |

Common actions:

| Action | Method & Endpoint | Notes |
| --- | --- | --- |
| View/update config | `GET/PUT /pi-agent/config` | Only supplied fields are updated |
| Set LLM Key | `PUT /pi-agent/config/llm-api-key` | Encrypted at rest |
| Set Search/Vision Key | `PUT /pi-agent/config/search-api-key`, `/vision-api-key` | Pass empty to clear |
| Test connection | `POST /pi-agent/config/test-connection` | Only OpenAI-compatible providers supported; optional body `api_key`/`llm_provider`/`llm_api_base`/`llm_model` for test-before-save |
| Speed test | `POST /pi-agent/config/speed-test` | Same limitation and optional body |

> Note: connection/speed tests **only support OpenAI-compatible** providers (e.g., deepseek/openai/openai_compatible). Other providers (e.g., Anthropic) return a clear "unsupported" status instead of a misleading error. Newly typed keys can be tested **before save**: temporary values stay in-memory for this request only — they are not persisted, do not update `last_test_status`, and are not logged. When the response has `config_saved=false`, success copy is "connected ✓ (current config not saved yet)". Omitted fields fall back to the saved database config.

---

### 10. Branding

Branding is managed via a runtime config file; see [configuration.md](./configuration.md) for details.

**Config file:** `runtime/config/ui-branding.yaml` (copy from `runtime/config/ui-branding.example.yaml`).

**Priority:** `runtime/config/ui-branding.yaml` > the `ui_branding` section of `src/config.yaml` > code defaults.

Customizable items: app_title, login_title/login_subtitle/login_notice, topbar_title, theme colors (primary/primary_hover/accent), logo/favicon (assets go in `runtime/assets/branding/`; specify only filenames — **absolute paths, `..` traversal, and external URLs are forbidden**).

The **admin branding page** offers template export and configuration guidance; the **branding migration tool** is used for batch adjustments:

```bash
python3 tools/migrate_branding.py
```

---

### 11. System Stats & Troubleshooting

| Endpoint | Purpose |
| --- | --- |
| `GET /api/admin/stats` | System stats: user count, conversation count, message count + the last 7 days of access records (up to 50) |

`recent_visits` includes timestamp, username, action, method, path, client_ip, result — useful for **lightweight ops and troubleshooting** (e.g., "who called which endpoint when, and did it succeed").

> These stats are read from audit logs and contain no sensitive plaintext — suitable for routine inspection.

---

### 12. Security Checklist

Review before go-live and periodically:

- [ ] `allow_public_registration` set to `false` in production; first admin initialized offline.
- [ ] Strong password injected via `ADMIN_INITIAL_PASSWORD`; changed on first login; no `[SECURITY]` weak-password warnings in logs.
- [ ] `JWT_SECRET` is a high-entropy random value (API Key and SSE-ticket encryption depend on it).
- [ ] Model API Keys configured and `test-connection` passes; unnecessary models `enabled=false`.
- [ ] High-risk tools (bash/write/edit/read) not exposed to ordinary users; approvers configured.
- [ ] High-consumption workspaces have `hard_limit_action=block` with a sensible threshold.
- [ ] Periodically export `/governance/permissions/audit` to review granted permissions.
- [ ] Decommissioned Agents are `archived` with no residual authorizations.

For more on the security model (auth, encryption, SSRF protection, etc.), see [security.md](./security.md).
