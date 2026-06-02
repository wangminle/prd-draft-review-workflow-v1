# 任务跟踪列表

记录本项目所有任务：代码 bug、bug 转需求、新增需求、需求调整、功能开发、代码审查、测试数据、文档维护、配置运维等。

> 说明：本文件是当前项目的任务清单。所有新增事项、状态变更和完成记录都应同步写入本文件。
> 字段说明：动作字段只允许以下 8 个固定枚举：修复、开发、优化、调整、规划、检查、文档、运维。
> 归并规则：审计、复核、核查、审查、验证、评估统一记为“检查”；重构、清理统一记为“优化”；方案、梳理统一记为“规划”；记录类文档事项统一记为“文档”。

## 代码 Bug

| ID | 动作 | 问题描述 | 发现日期 | 状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| BUG-001 | 修复 | 对照外部任务清单发现当前代码缺少 BUG-111~114 的部分修复：新对话未清理附件/URL、会话 ID 类型不一致导致高亮丢失、预分类缺少 prompt 级 schema、前端内联 onclick 依赖对象未挂到 window | 2026-06-01 | 已修复 | `chat.js` 新增 `_clearAttachments()` 调用并改为字符串 ID 比较；`SkillSchemaLoader` 支持 prompt 级 schema 与递归校验/修复；`auth.js`/`chat.js`/`admin.js`/`review.js` 暴露全局对象；新增 `tests/test_skill_schema.py`、`tests/test_frontend_inline_handlers.py` 并扩展聊天前端契约测试；全量 `python3 -m pytest` 355 通过 |
| BUG-002 | 修复 | CHK-006 审查发现的三个 P2 回退：① 删除不存在上下文项误报成功（应返回 404）② FTS 搜索排序从相关性 rank 回退为时间倒序 ③ 逐篇分析缓存校验从固定 6 项 rule_key 放宽为 checks 长度 ≥ 6 | 2026-06-01 | 已修复 | `context_item_repository.py` delete_item 返回 bool + chat.py 404 判断；`conversation_repository.py` ORDER BY rank 恢复；`review_task_repository.py` 引入 `_REQUIRED_EXPERT_REVIEW_RULE_KEYS` frozenset 做集合校验；`.gitignore` 改用 `**/__pycache__/` + `*.py[cod]`；新增 `tests/test_code_review_fixes.py`(7)；全量回归 381 passed |
| BUG-003 | 修复 | CHK-008 审查发现的四个问题：① expert_review summary 非空校验缺失 ② review 文件删除仍在 router（os.remove 直接调用）③ 持久化扫描漏扫 os.remove/os.unlink ④ ChatApplicationService 未落地 | 2026-06-01 | 已修复 | `review_task_repository.py` 补充 summary 非空校验；`review_file_storage.py` 新增 delete_document_files 承接文件删除；`test_router_persistence_scan.py` 新增 os_remove/os_unlink 扫描模式；`chat_application_service.py` 创建 + chat.py 重构委派 prepare_chat_session；全量回归 388 passed |
| BUG-004 | 修复 | CHK-009 审查发现 ReviewFileStorage 固定使用 runtime_path("data", "review_uploads")，忽略 review.upload.upload_dir 配置 | 2026-06-02 | 已修复 | `review_file_storage.py` 新增 __init__(upload_dir)、_resolve_config_dir、_resolve_upload_root，优先注入路径→配置值→默认回退；save_uploaded_docx 和 delete_project_files 改用 _resolve_upload_root()；新增 `tests/test_code_review_fixes.py`(4)；全量回归 392 passed |

## 调整事项

| ID | 动作 | 事项 | 完成日期 | 状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| ADJ-001 | 调整 | `.gitignore` 补充 Python 构建产物和前端依赖排除规则 | 2026-06-01 | 已完成 | 新增 `*.egg-info/`、`*.egg`、`*.whl`、`node_modules/`；验证 git 追踪中无缓存、临时或安装包文件 |

## 检查事项

| ID | 动作 | 事项 | 完成日期 | 状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| CHK-001 | 检查 | 项目运行方式检查 | 2026-06-01 | 已完成 | 确认项目为 FastAPI + SQLite + 原生 JS SPA；端口 17957；启动方式为 `./start.sh`，包含 start/stop/restart/status；依赖文件为 `requirements.txt`，尚未创建 `.venv` |
| CHK-002 | 检查 | 敏感信息排查 | 2026-06-01 | 已完成 | 全量搜索具体企业和个人信息；docs/、skills/、src/、tests/ 及 git 历史均未发现目标敏感词 |
| CHK-003 | 检查 | 运行时兼容性验证 | 2026-06-01 | 已完成 | 确认匿名化修改不破坏现有数据结构和运行逻辑；数据库 category/title 等字段为自由文本；SkillRunner 分类关键词动态注入；默认分类为空列表；此前全量回归 pytest 344 通过，两次验证均无破坏 |
| CHK-004 | 检查 | 外部任务清单 2026-05-31/2026-06-01 bug 记录差异检查 | 2026-06-01 | 已完成 | 已确认 2026-05-31 巡检提到的运行中任务后端去重、DOCX source hash 写入失败非致命化、登录页低高度响应式回退在当前代码已有实现或测试覆盖；随后修复 BUG-001 |
| CHK-005 | 检查 | 三份持久化与分层文档合理性检查 | 2026-06-01 | 已完成 | 阅读 `后端持久化接口草案.md`、`架构分层改造清单.md`、`运行时数据与持久化接口基线.md`；对照当前 models、runtime 路径、FTS、SSE ticket、JSONL 日志及 review/chat/upload/admin/auth router 耦合点；结论为主方向合理，但发现接口草案重复、相对链接不准、第一阶段优先级口径需收敛 |
| CHK-006 | 检查 | 未提交更改代码审查 | 2026-06-01 | 已完成 | 审查 staged、unstaged、untracked 当前改动；发现上下文项删除 404 语义回退、FTS 搜索排序回退、逐篇分析缓存校验放宽、未跟踪 `__pycache__` 文件等问题；本次为审查任务，未修改业务代码，未运行自动化测试 |
| CHK-007 | 检查 | CHK-006 修复结果复查 | 2026-06-01 | 已完成 | 复查上下文项删除、FTS rank 排序、逐篇分析缓存 rule_key 校验和 `.gitignore`；相关测试 `python3 -m pytest tests/test_code_review_fixes.py tests/test_review_backend_contract.py -q` 39 通过，全量 `python3 -m pytest -q` 384 通过；仍发现 expert_review summary 非空校验未完全保留、项目删除文件清理异常处理语义变化 |
| CHK-008 | 检查 | 架构分层 WBS 完成度与 bug 复查 | 2026-06-01 | 已完成 | 对照 `docs/3-design/架构分层改造清单.md` 复查 WBS 0~F；专项 `python3 -m pytest tests/test_router_persistence_scan.py tests/test_code_review_fixes.py tests/test_review_backend_contract.py -q` 47 通过，全量 `python3 -m pytest -q` 384 通过；发现 `ChatApplicationService` 未落地、Review 文件删除仍在 router、扫描测试漏扫 `os.remove()`、expert_review summary 非空校验缺失等问题 |
| CHK-009 | 检查 | 未提交更改代码审查 | 2026-06-02 | 已完成 | 审查 staged、unstaged、untracked 当前改动；重点覆盖 repository/storage/service 分层、chat/review/admin/auth 路由重构、prompt 级 schema、前端全局对象暴露和运行时数据隔离；发现 ReviewFileStorage 上传目录忽略 `review.upload.upload_dir` 配置的回归风险；相关测试 `python3 -m pytest tests/test_data_compat.py tests/test_review_backend_contract.py tests/test_chat_integration.py tests/test_context_panel.py tests/test_skill_schema.py tests/test_router_persistence_scan.py` 82 通过 |
| CHK-010 | 检查 | V0.2.5-Build0166-20260602 提交前变更汇总与 commit message 准备 | 2026-06-02 | 已完成 | 汇总所有未提交代码、测试、文档、配置和任务清单变更；输出不超过 200 字的 commit message；本次仅做提交前整理说明，未修改业务实现 |

## 测试数据

## 测试数据

| ID | 动作 | 事项 | 完成日期 | 状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| TD-001 | 调整 | 测试数据开源合规匿名化 | 2026-06-01 | 已完成 | `tests/test_review_backend_contract.py`、`tests/test_review_report_contract.py` 中将“有埋点”改为“有数据采集”，共 3 处 |

## 文档维护

| ID | 动作 | 事项 | 完成日期 | 状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| DOC-001 | 文档 | docs/ 文档开源合规匿名化 | 2026-06-01 | 已完成 | `3-design/需求审查工作流平台-需求说明书.md`、`2-archive/20260515-业务逻辑层整合技术方案.md`、`2-archive/三栏式UI界面设计指南.md`、`4-deployment/2026-05-22-ubuntu-nginx-systemd-security-plan.md`、`1-discussion/Skill-as-a-Service人机协同工具开发范式.md` 完成示例产品名、内部目录名、服务名和 LLM 选型口径泛化 |
| DOC-002 | 文档 | skills/ Prompt 与模板开源合规匿名化 | 2026-06-01 | 已完成 | 覆盖 `prd-overview-classify/`、`prd-per-analysis/`、`system-review/`、`requirement-insights/`、`report-generator/`；将具体业务词汇泛化为核心策略、智能联动、交互体验、功能预约、数据追踪、响应时延等中性表达 |
| DOC-003 | 文档 | 持久化与分层文档合并重构 | 2026-06-01 | 已完成 | 将三份文档收敛为"两份主文档 + 一个兼容入口"：`运行时数据与持久化接口基线.md` 升级为数据结构与持久化接口规约；`架构分层改造清单.md` 重写为 WBS 计划书；`后端持久化接口草案.md` 改为已合并说明；验证不再存在旧 `docs/...` 错误相对链接，接口草案重复标题已消除，三份文档行数收敛为 474/344/21 |
| DOC-004 | 文档 | 任务清单格式规范化 | 2026-06-01 | 已完成 | 将原来的日期分组 bullet list 改为与外部项目一致的分类表格结构；新增固定动作枚举、归并规则、ID 编号、状态字段和备注字段；按代码 Bug、调整事项、检查事项、测试数据、文档维护重新归类现有记录 |

## 功能开发

| ID | 动作 | 事项 | 完成日期 | 状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| DEV-001 | 开发 | WBS E.2 Admin 配置域分层：新增 ModelConfigRepository、PromptTemplateRepository、SkillConfigRepository、UserRepository；重构 admin.py router 全部持久化调用收口到 repository 层 | 2026-06-01 | 已完成 | admin.py db_add 从 2 降为 0；新增 `src/app/repositories/{model_config,prompt_template,skill_config,user}_repository.py`、`src/app/stores/sse_ticket_store.py` |
| DEV-002 | 开发 | WBS E.3 Auth 账户域分层：新增 SseTicketStore（包装 in-memory SSE ticket dict）、UserRepository 收口注册/改密/登录活跃时间更新；重构 auth.py router、services/auth.py、middleware/auth.py | 2026-06-01 | 已完成 | auth.py db_add 从 1 降为 0；services/auth.py SSE ticket 逻辑委派到 SseTicketStore；middleware/auth.py 用户查询委派到 UserRepository |
| DEV-003 | 检查 | 全量回归验证（排除 4 个预存失败） | 2026-06-01 | 已完成 | 373 passed, 4 deselected；预存失败为 test_docx_conversion_accepts_skill_string_return、test_legacy_runtime_file_path_resolves_to_workspace_runtime、test_parent_relative_runtime_file_path_resolves_to_workspace_runtime、test_source_hash_write_failure_is_non_fatal |
| DEV-004 | 开发 | WBS 0+A+B+C.1 基线保护与分层模板实现：数据兼容性测试、持久化扫描、ChatFileStorage、ConversationRepository、ContextItemRepository、AuditLogWriter/Reader、FrontendLogWriter、LlmSessionLogWriter、ReviewFileStorage | 2026-06-01 | 已完成 | 新增 `tests/test_data_compat.py`(14)、`tests/test_router_persistence_scan.py`(8)；新增 `src/app/storage/{chat_file_storage,review_file_storage}.py`、`src/app/log_writers/{audit_log_writer,audit_log_reader,frontend_log_writer,llm_session_log_writer}.py`、`src/app/repositories/{conversation_repository,context_item_repository}.py`；重构 upload/chat/history/auth/admin/review router 委派到 storage/repository/log_writer 层；修复 4 个契约测试（skill 路径、runtime_path monkeypatch、_write_source_hash 导入）；377 全量回归通过 |
| DEV-005 | 开发 | WBS D.1+E.1+D.2+F 审查 pipeline 分层收口：ReviewTaskRepository、ReviewProjectRepository、ReviewContextRepository、ReviewPromptRepository、ReviewPipelinePersistenceService；review.py db_add 从 9 降为 0，builtin_open 从 2 降为 0 | 2026-06-01 | 已完成 | 新增 `src/app/repositories/{review_task,review_project,review_context,review_prompt}_repository.py`、`src/app/services/review_pipeline_persistence.py`；重构 review.py 所有 Task/DocAnalysis/SystemReview/Project/Document/Context/Prompt 的 db.add 收口到 repository 层；pipeline MD 文件读取改用 ReviewFileStorage.read_markdown()；384 全量回归通过 |
| DEV-006 | 开发 | CHK-008 四项问题修复：summary 非空校验补回、文件删除委派到 ReviewFileStorage、扫描测试补扫 os.remove/os.unlink、ChatApplicationService 落地重构 chat.py | 2026-06-01 | 已完成 | BUG-003 修复：`review_task_repository.py` _analysis_has_required_expert_review 增加 summary 非空判断；`review_file_storage.py` delete_document_files 承接 os.remove 调用；`test_router_persistence_scan.py` 新增 os_remove/os_unlink 模式+白名单+测试方法；`chat_application_service.py` 新建+`chat.py` 重构将准备逻辑委派到 ChatApplicationService.prepare_chat_session，移除 _get_jwt_secret/_get_model_config/_truncate_context_text 死代码+清理未用导入；388 全量回归通过 |
| DEV-007 | 开发 | CHK-009 ReviewFileStorage upload_dir 配置注入：ReviewFileStorage 新增 __init__(upload_dir)、_resolve_config_dir、_resolve_upload_root，优先注入路径→配置值→默认回退 | 2026-06-02 | 已完成 | BUG-004 修复：`review_file_storage.py` 新增 __init__(upload_dir=None) + _resolve_config_dir + _resolve_upload_root（优先注入→review.upload.upload_dir 配置→runtime/data/review_uploads 默认回退）；save_uploaded_docx 和 delete_project_files 改用 _resolve_upload_root()；新增 `tests/test_code_review_fixes.py`(4) 覆盖默认/注入/配置/相对路径四种场景；392 全量回归通过 |
