# Issue #9 / #10 修复清单与 WBS

- 基线：`586dce5`（V0.3.18）
- 当前本地版本：`0.3.19`；文档核对日期：2026-11-10。基线版本用于追溯原报告，不表示当前部署版本。
- 来源：GitHub Issue #9（46 条确认）、#10（53 条确认）及两轮独立复核评论
- 归并原则：按根因去重；已被复核评论判定为误报或不可达的条目单独标注，不进入修复范围
- 状态：`待修` / `修复中` / `已修` / `已验证` / `不修（说明）`

## 一、问题清单（去重后）

| ID | 严重度 | 位置 | 问题 | 来源 | 状态 |
| --- | --- | --- | --- | --- | --- |
| SEC-01 | 高 | `src/app/database.py` | 管理员初始密码先提交后写文件，写失败会永久锁死账号 | #9/#10 H1 | 已修 |
| SEC-02 | 中 | `src/app/routers/admin.py` | `create_model` 未复用 `_get_jwt_secret()` 强度校验 | #10 H2 | 已修 |
| SEC-03 | 高 | `src/app/routers/review.py` | 写操作复用 `read` 权限，viewer 创建者可改/删项目 | #9/#10 H3 | 已修 |
| SEC-04 | 高 | `src/app/routers/review.py` | quick 完成状态覆盖并发取消 | #9/#10 H4 | 已修 |
| SEC-05 | 高 | `src/app/routers/review_request.py` | 审批人未校验活跃成员/不得为发起人 | #9/#10 H5 | 已修 |
| SEC-06 | 高 | `src/app/routers/review_request.py` | 指定审批人被停用后仍可决策 | #10 H6 | 已修 |
| SEC-07 | 高 | `src/app/routers/review_request.py` | 添加参与者接受任意用户 ID | #9/#10 H7 | 已修 |
| SEC-08 | 高 | `src/app/services/knowledge_ingestion.py` | FTS 在 `user_id=None` 时不过滤 private | #9/#10 H8 | 已修 |
| SEC-09 | 高 | `src/app/services/object_access.py` | 发起人/创建者绕过活跃成员校验 | #9/#10 H9 | 已修 |
| SEC-10 | 高 | `src/app/services/pi_agent_bridge.py` | Pi 子进程继承全部服务端环境变量 | #9/#10 H10 | 已修 |
| SEC-11 | 高 | `src/app/services/pi_agent_bridge.py` | 无管理员时回退申请人为审批人 | #9/#10 H11 | 已修 |
| SEC-12 | 高 | `src/static/js/review.js` | Mermaid `loose` + 未净化 SVG 写入 innerHTML | #9/#10 H12 | 已修 |
| SEC-13 | 高 | `update.sh` | 代码目录非原子替换 | #9/#10 H13 | 已修 |
| SEC-14 | 高 | `update.sh` | 启动失败未回滚 | #9/#10 H14 | 已修 |
| SEC-15 | 中 | `src/app/routers/agent.py` | 管理员可自批高风险工具 | #9 | 已修 |
| SEC-16 | 中 | `src/app/routers/notification.py` | 评论解决未校验写权限 | #9 | 已修 |
| SEC-17 | 中 | `src/app/routers/review.py` | legacy 项目跳过预算硬限 | #9 | 已修 |
| SEC-18 | 中 | `src/app/routers/workspace.py` | 其他成员可重新入库他人私有资料 | #9 | 已修 |
| SEC-19 | 中 | `src/app/services/mcp_adapter.py` | MCP 无策略默认放行 + 并发连接泄漏 | #10 | 已修 |
| SEC-20 | 中 | `src/app/middleware/auth.py` | 每个请求都写 `last_active` 并提交 | #9 | 已修 |
| SEC-21 | 中 | `src/app/services/retry.py` | 日志写入失败导致成功响应被重试 | #9 | 已修 |
| CON-01 | 中 | `src/app/repositories/artifact_repository.py` | 产物确认/更新并发竞态 | #9 | 已修 |
| CON-02 | 中 | `src/app/repositories/review_context_repository.py` | 上下文版本激活竞态 | #10 | 已修 |
| CON-03 | 中 | `src/app/routers/review.py` | 取消与完成 TOCTOU | #10 | 已修 |
| CON-04 | 中 | `src/app/routers/review.py` | 管线启动覆盖已取消状态 | #9/#10 | 已修 |
| CON-05 | 中 | `src/app/services/agent_application_service.py` | Agent 正常结束未置完成态 | #9 | 已修 |
| CON-06 | 中 | `src/app/database.py` | 默认空间迁移嵌套 session 导致锁 | #10 | 已修 |
| CON-07 | 中 | `src/app/routers/review.py` | 删除项目先删文件后提交 | #9 | 已修 |
| CON-08 | 中 | `src/app/routers/review.py` `upload.py` `workspace.py` | 上传先全量读入内存 | #9 | 已修 |
| CON-09 | 中 | `src/app/services/pi_agent_bridge.py` | 异步事件流用同步 select/readline 阻塞事件循环 | #9/#10 | 已修 |
| FS-01 | 中 | `src/app/database.py` | 初始密码文件未拒绝符号链接 | #10 | 已修 |
| FS-02 | 中 | `src/app/storage/review_file_storage.py` | 存储路径未限制可信根 | #10 | 已修 |
| FS-03 | 中 | `src/app/env_file.py` | 复制 `.env` 不收紧权限 | #10 | 已修 |
| FS-04 | 中 | `start.sh` | JWT_SECRET 经 argv 泄漏 | #9/#10 | 已修 |
| FS-05 | 中 | `update.sh` | 备份失败被 `\|\| true` 隐藏 | #10 | 已修 |
| FS-06 | 中 | `update.sh` | 回滚不清理新增文件 / 先删配置后复制 | #9/#10 | 已修 |
| FS-07 | 中 | `update.sh` | 更新包校验不拒绝符号链接条目 | #9/#10 | 已修 |
| SK-01 | 中 | `skills/prd-per-analysis/scripts/batch_analyze.py` | `doc_id` 路径穿越 | #10 | 已修 |
| SK-02 | 中 | `skills/prd-per-analysis/scripts/batch_analyze.py` | 子进程无超时 | #10 | 已修 |
| SK-03 | 中 | `skills/docx-to-markdown/scripts/convert_docx.py` | 输出文件/图片未拒绝符号链接 | #10 | 已修 |
| SK-04 | 中 | `skills/docx-to-markdown/scripts/convert_docx.py` | Markdown 链接保留危险 scheme / 实体解码输出原始 HTML | #10 | 已修 |
| SK-05 | 中 | `skills/report-generator/scripts/mermaid_builder.py` | Mermaid 转义顺序错误 | #10 | 已修 |
| SK-06 | 中 | `skills/requirement-insights/scripts/insights.py` | Mermaid 标签未转义 | #10 | 已修 |
| SK-07 | 中 | `skills/report-generator/scripts/generate.py` | PDF 标题未转义 XML | #9 | 已修 |
| SK-08 | 中 | `tools/migrate_branding.py` | 资产路径未拒绝危险 scheme / 复制跟随符号链接 | #10 | 已修 |
| FE-01 | 中 | `src/static/js/chat.js` | Mermaid `loose` | #9/#10 | 已修 |
| FE-02 | 中 | `src/static/js/review.js` | 未知维度键、状态类名、优先级类名未转义 | #10 | 已修 |
| FE-03 | 中 | `src/static/js/review.js` | Mermaid 标签未转义 | #10 | 已修 |
| FE-04 | 中 | `src/static/js/review.js` | 切换项目未停旧监听 / 停轮询后重启 / 旧报告覆盖 | #9/#10 | 已修 |
| FE-05 | 中 | `src/static/js/admin.js` | 模型配置加载失败仍可提交空表单 | #9 | 已修 |
| FE-06 | 中 | `src/static/js/admin.js` | 拖拽排序后按钮绑定旧索引 | #9 | 已修 |
| FE-07 | 低/中 | `src/static/js/admin.js` `chat.js` | 掩码、模型名、Skill ID 内联 onclick 未安全输出 | #9/#10 | 已修 |
| MISC-01 | 低 | `src/app/routers/review.py` | 进度订阅表留下空集合 | #9 | 已修 |
| MISC-02 | 低 | `src/app/services/pi_agent_bridge.py` | `read` 审计风险级别为 low，与高风险门控不一致 | #10 | 已修 |
| SEC-22 | 中 | `src/app/repositories/pi_agent_config_repository.py` | 首次配置并发冲突 `rollback()` 整个调用方事务 | #9 低 | 已修 |
| SEC-23 | 低 | `src/app/services/cost_stats_service.py` / `embedding_service.py` | embedding token 未写入日志与统计 | #9 低 | 已修 |
| SEC-24 | 中 | `src/app/routers/review.py` | 项目资料引用未校验私有资料 owner | #9/#10 复核 | 已修 |
| SEC-25 | 中 | `src/app/storage/chat_file_storage.py` / `chat.py` / `chat_application_service.py` | 聊天附件 file_id 未校验归属，可跨用户注入/读取提取文本 | #9/#10 复核 | 已修 |
| SEC-26 | 中 | `src/app/routers/review.py` / `review_request.py` | viewer 可取消任务；停用发起人可列表/新建/重提 | #9/#10 复核 | 已修 |
| FE-08 | 中 | `src/static/js/review.js` | 父模式取消/失败后子模式仍显示 running | #9 低 / #10 复核 | 已修 |
| FS-08 | 中 | `src/app/storage/review_file_storage.py` | 读取/转换仍接受数据库中的根外路径 | #10 复核 | 已修 |
| MISC-03 | 中 | `src/app/config.py` / `migrate_branding.py:673` / `admin.js:561` / `review.js:1312` / `knowledge_file_storage.py:71` | 复核判定误报或不可达 | #10 复核 | 不修（补转义/边界加固的项已并入 FE-07、FS-02） |

## 二、WBS

| WBS | 工作包 | 覆盖 ID | 验收 |
| --- | --- | --- | --- |
| 1.1 | 管理员初始化与密钥一致性 | SEC-01、SEC-02、FS-01 | 密码文件写失败时管理员行回滚；模型创建走统一密钥校验 |
| 1.2 | 审查项目写权限与预算 | SEC-03、SEC-17 | viewer 创建者无法写/删；legacy 项目同样校验预算 |
| 1.3 | 协作审查审批链 | SEC-05、SEC-06、SEC-07、SEC-09 | 非成员/发起人/停用审批人被拒；参与者添加校验成员 |
| 1.4 | 检索可见性 | SEC-08 | 工作区 FTS 必须带 user_id，`None` 仅返回 team |
| 1.5 | Agent 进程与审批 | SEC-10、SEC-11、SEC-15、CON-09、MISC-02 | 子进程无服务端秘密；不得自批；事件流不阻塞 |
| 2.1 | 取消/完成/启动一致性 | SEC-04、CON-03、CON-04 | 取消终态不被覆盖；启动不复活 cancelled |
| 2.2 | 仓储并发 | CON-01、CON-02 | 条件更新；激活串行化 |
| 2.3 | 迁移与删除顺序 | CON-06、CON-07 | 无嵌套写锁；提交后再删文件 |
| 2.4 | 上传与请求开销 | CON-08、SEC-20、SEC-21 | 分块限流；last_active 节流；日志失败不重试 |
| 3.1 | 环境与文件权限 | FS-02、FS-03、FS-04、SK-03 | `.env` 0600；JWT 由 Python 辅助程序读取已导出的环境变量，不经 argv；输出拒绝符号链接 |
| 3.2 | 更新脚本 | SEC-13、SEC-14、FS-05、FS-06、FS-07 | 暂存替换；备份失败中止；启动失败回滚；拒绝链接条目 |
| 3.3 | Skill 路径与输出 | SK-01、SK-02、SK-05、SK-06、SK-07、SK-08 | 路径净化；超时；转义顺序正确 |
| 4.1 | 前端 XSS | SEC-12、FE-01、FE-02、FE-03、FE-07 | strict + DOMPurify；所有拼 HTML 的值转义 |
| 4.2 | 前端状态 | FE-04、FE-05、FE-06 | 切换项目/销毁后无旧回调；加载失败不提交 |
| 5.1 | 回归测试与文档 | 全部 | 新增定向测试；全量 pytest；`node --check`；更新 task-list |

## 三、复核补漏（BUG-210～218）与验收映射

| BUG | 复核问题 | 修复落点 | 验收证据 |
| --- | --- | --- | --- |
| BUG-210 | 首次启动 JWT 写入空值 | `start.sh` 改为从已导出的 `JWT_SECRET` 环境变量读取，不再依赖被 heredoc 占用的 stdin | `test_start_sh_persists_generated_jwt_secret`：真实执行函数后 `.env` 中密钥长度 64 |
| BUG-211 | 更新中途失败留混合版本；回滚配置替换失败仍误报成功；.env 恢复直接 cp 留部分文件；备份失败旧服务停机 | `update.sh` 两阶段事务替换（旧目录/文件全部入 txn，新内容失败则整体还原）；`restore_backup` 任一失败返回非零并整体还原已处理条目、保留恢复副本目录，config/assets 先移走再替换；恢复 .env 改用临时文件原子移动；备份失败且旧服务已停时恢复启动现有服务 | `test_update_copy_failure_restores_old_tree`、`test_update_rollback_config_failure_returns_error_and_keeps_config`、`test_update_err_trap_triggers_rollback_after_backup`、`test_update_restore_extract_failure_keeps_code`、`test_create_backup_tolerates_missing_optional_managed_files`、`test_update_restore_midway_failure_restores_all_items_and_keeps_recovery_copies`、`test_update_sh_restore_env_uses_temp_file_and_service_recovered` |
| BUG-212 | viewer 取消、停用发起人列表/新建/重提、私有评论 resolve、聊天附件、项目资料引用、停用审批人重提、Observer 评论、停用创建者讲解准备 | 取消改 `write`；列表逐条 `_can_access_request`；创建/重提校验发起人及候选审批人活跃；`create_comment`/resolve 统一走 `assert_object_write_access` 且显式拦截 Observer；讲解准备模式校验创建者活跃成员资格；附件 file_id 编入 `u<id>_` 前缀；项目引用直接拒绝私有或个人资料；协作审查轮次拒绝发起人自批 | `test_viewer_cannot_cancel_review`、`test_inactive_initiator_cannot_list_create_or_resubmit`、`test_private_source_comment_resolve_rejects_other_writer`、`test_chat_attachment_owner_check`、`test_legacy_self_approval_is_rejected`、`test_viewer_initiator_cannot_resolve_review_comment`、`test_legacy_private_project_source_ref_not_injected`、`test_resubmit_deactivated_approver_and_observer_comment_and_inactive_presentation` |
| BUG-213 | 非 quick 管线覆盖 cancelled；上下文锁提前释放 | 所有终态走 `_commit_terminal_status`（SQL 条件 `status != cancelled`）；上下文锁覆盖“读旧版本→合并→插入→commit” | `test_terminal_status_does_not_overwrite_cancelled_with_autoflush`；`test_router_persistence_scan` 提交点白名单同步 31 |
| BUG-214 | 重入库回滚丢旧向量；补偿失败仍召回 failed；并发跳过破坏 done 状态；已归档资料被在途 worker 复活召回；终态写入 TOCTOU 覆盖新切块/破坏状态 | 旧 chunk 向量延迟到 commit 后按 `(chunk_id, text)` 清理；worker 写入前后联合校验 `(text, embedding_status, source.status=='active')`，跳过时不重置已 `done` 切块；检索与 FTS 同步校验 `source.status == 'active'`；embedding 调用写 JSONL 并在聚合中计入 `embedding_tokens`；新增 `update_embedding_status_conditional` 在单条 SQL 中校验 `(id, text, document_id, 来源 active, expected_status/disallowed_statuses)`；成功不覆盖新切块，异常不回标 done 为 failed；补偿按批次 `write_token` 限定删除归属（见第六节） | `test_embedding_worker_stale_skip_keeps_done_and_archived_source_not_recalled`、`test_cost_stats_explicit_chat_mode_not_misclassified`、`test_embedding_worker_conditional_update_avoids_stale_overwrite`；知识库定向测试通过 |
| BUG-215 | Pi 非零退出或嵌套错误仍 completed；流式 `assistantMessageEvent.delta` 未转发；Pi 配置冲突回滚整笔事务 | 未收到 `agent_end` 一律 failed 并记录 exit code；`agent_end` 解析顶层及 `messages[-1]` / assistant 消息的 `stopReason=error` 与 `errorMessage`；`message_update` 兼容提取 `assistantMessageEvent.delta`；进程退出后继续读尾部缓冲；SQLite `get_or_create` 改 `INSERT OR IGNORE` | `test_pi_agent_end_error_and_blank_line_handling`、`test_pi_reads_tail_events_after_process_exit`、`test_pi_sdk_nested_agent_end_error_and_assistant_message_event_delta` |
| BUG-216 | 晚到 SSE 覆盖、旧报告错误覆盖、模型空表单、父取消子 running、Mermaid 文字丢失/引号失败、运行中任务切换跨项目状态污染 | SSE 返回后再次校验代次/项目；报告 catch 增加 stale 校验；模型保存按钮加载前禁用；失败/取消仅清理 running/pending 子模式；Mermaid `htmlLabels:false`、引号改单引号；`_showResult` 运行中任务异步返回后在成功和异常路径均校验 resultToken/stateVersion/project/task 匹配 | 前端契约测试 + `node --check` + Chrome 实测（节点/边文字保留、引号标签可渲染、javascript: 链接被移除）；同项目 SSE seq / 弹窗 token / 角标优先级 / YAML frontmatter 剥离 / 倒序 history 保留子模式 completed / 轮询绑定 listenSeq；`test_review_js_show_result_running_task_checks_stale_state` |
| BUG-217 | DOCX 编码危险链接/原始 HTML/临时哨兵符号链接；审查读取根外路径 | unescape 后再次中和危险 Markdown/移除原始标签；哨兵临时文件 `O_NOFOLLOW`；`_resolve_stored_file_path` 恢复可信根校验 | docx 安全/资源隔离/回退定向测试通过；`test_html_to_markdown_keeps_comparisons_and_blocks_encoded_js` |
| BUG-218 | 评论删除未校验对象写权限；团队资料私有判断 `and` 导致漏网；快照未校验请求归属与实际空间；物料确认通知向停用成员推送；项目引用资料添加私有但管线不注入 | `delete_comment` 接入 `assert_object_write_access` 拦截停用成员/Observer；`_assert_team_source_readable` 改用 `or`；`create_snapshot` 校验 `request_id` 归属当前项目并使用项目实际空间；`confirm_artifact` 通知过滤已停用成员；`add_project_source_ref` 拒绝私有资料引用 | `test_deactivated_or_observer_author_cannot_delete_comment`、`test_private_source_variant_readable_assertion`、`test_create_snapshot_validates_request_and_workspace`、`test_confirm_artifact_excludes_inactive_workspace_participants`、`test_add_project_source_ref_rejects_private_source` |

## 四、原报告条目索引

| 原报告 | 原条目 | WBS / BUG |
| --- | --- | --- |
| #9 高 1–8 | 管理员初始化、写权限、取消覆盖、审批人/参与者、成员撤权、Pi 环境、Pi 阻塞 | SEC-01、SEC-03、SEC-04、SEC-05、SEC-07、SEC-09、SEC-10、CON-09 |
| #9 中·权限 9 条 | last_active 写库、管理员 Agent 自批、评论 resolve、legacy 预算、停用审批人、私有重入库、chat file_id、向量/DB 不一致、无管理员自批 | SEC-20、SEC-15、SEC-16、SEC-17、SEC-06、SEC-18、SEC-25、BUG-214、SEC-11 |
| #9 中·事务并发 15 条 | 产物竞态、上传内存、删除顺序、启动覆盖、Agent 终态、重入库、向量 upsert、MCP 连接、日志重试、admin 加载、项目切换、失败传播、更新备份/替换/回滚 | CON-01、CON-08、CON-07、CON-04、CON-05、BUG-214、BUG-214、SEC-19、SEC-21、FE-05、FE-04、FE-08、FS-05、SEC-13、FS-06 |
| #9 中·文件/输入/Mermaid 6 条 | 上传内存、拖拽索引、Mermaid、PDF 标题、insights 标签、review Mermaid | CON-08、FE-06、SEC-12/FE-01、SK-07、SK-06、SEC-12 |
| #9 低 7 条 | Pi 配置回滚、空订阅集合、embedding token、Skill ID XSS、模型名 XSS、JWT argv、归档符号链接 | SEC-22、MISC-01、SEC-23、FE-07、FE-07、FS-04、FS-07 |
| #10 高 1–14 | 与 #9 高重叠：初始化、密钥、写权限、取消、审批链、FTS、成员撤权、Pi 环境/自批、Mermaid、更新脚本 | SEC-01～SEC-14 |
| #10 中·路径 11 条 | docx 图片/Markdown 符号链接、batch doc_id、system-review/review 与 pm 路径、runtime 配置、密码文件符号链接、review 存储删除/读取、branding、update 归档 | SK-03、SK-03、SK-01、system-review/review.py 普通 `.md` 只读加固、system-review/pm_assess.py 普通 `.md` 只读加固、MISC-03（config.py 误报）、FS-01、FS-02、FS-08、SK-08、FS-07 |
| #10 中·XSS 8 条 | admin 掩码、chat Mermaid、状态类名、维度键、优先级、Mermaid 标签、docx href/实体 | FE-07、FE-01、FE-02、FE-02、FE-02、FE-03、SK-04、SK-04（掩码/状态类名为加固项） |
| #10 中·状态 8 条 | 迁移嵌套 session、上下文激活、取消完成、启动覆盖、Pi 阻塞、项目切换、轮询重启、旧报告 | CON-06、CON-02、SEC-04/CON-03、CON-04、CON-09、FE-04、FE-04、FE-04 |
| #10 中·权限/密钥 5 条 | 管理员自批、MCP 默认放行、knowledge file_id、env 权限、JWT argv | SEC-15、SEC-19、MISC-03（误报）、FS-03、FS-04 |
| #10 中·子进程/更新/Mermaid 6 条 | batch 超时、branding scheme、备份失败、回滚残留、Mermaid 转义、insights 标签 | SK-02、SK-08、FS-05、FS-06、SK-05、SK-06 |
| #10 低 1 条 | read 风险等级 | MISC-02 |

## 五、明确不修（复核已否定）

- `src/app/config.py:48`：配置路径不是用户上传路径校验器，且支持绝对存储路径。
- `tools/migrate_branding.py:673`：只遍历受控 branding 目录，未发现任意源/目标路径。
- `src/static/js/admin.js:561`：掩码固定格式，无法承载可执行载荷（仍做转义卫生加固）。
- `src/static/js/review.js:1312`：`d.status` 来自服务端固定枚举（仍做类名白名单）。
- `src/app/storage/knowledge_file_storage.py:71`：外部下载先按 source 鉴权，file_id 由服务端生成。
- `src/app/services/pi_agent_bridge.py:432`：实际门控已把 `read` 纳入高风险（仅审计级别修正）。

## 六、CHK-129 后续修复验收

CHK-130 已于 2026-11-10 记录本轮源码修复验收：全量 **1880 passed / 19 skipped / 0 failed**，另有 2 个子测试通过；ruff、相关 JavaScript/Bash 语法及差异格式检查通过。这是该次本地验收记录，后续文档检查不改写历史测试结果。

| BUG | 修复 | 验收证据 | 状态 |
| --- | --- | --- | --- |
| BUG-214 | 按单条条件更新结果收集拒绝项，补偿排除当前 active/done 身份，并使用每批唯一 `write_token` 限定删除归属。旧 LanceDB 索引首次写入时补充空 token 列，保留原有数据及调用接口。 | `tests/test_embedding_compensation_regressions.py` 5 项，覆盖部分批次拒绝、同正文新任务完成、旧索引升级、新写入归属及异常补偿。原始 SQLite/LanceDB 两种误删脚本均通过。 | 已验证 |
| BUG-219 | `KnowledgeSourceRepository.get_by_id` 预加载 owner，避免共享资料详情序列化触发异步懒加载。 | `tests/test_knowledge_source_access_regressions.py` 4 项共享详情 HTTP 回归，覆盖 member/viewer/owner/admin。 | 已验证 |
| BUG-220 | 团队资料列表对私有或个人记录在分页前按当前用户 owner_id 过滤，缺失用户上下文时返回空列表。 | 同文件 4 项存量 workspace/private HTTP 回归，覆盖合法所有者、他人隔离及分页。 | 已验证 |
