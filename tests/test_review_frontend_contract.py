from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
API_JS = (ROOT / "src/static/js/api.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "src/static/js/app.js").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "src/static/js/auth.js").read_text(encoding="utf-8")
REVIEW_JS = (ROOT / "src/static/js/review.js").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "src/static/js/chat.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/static/css/main.css").read_text(encoding="utf-8")


def test_authenticated_default_page_is_review_workspace():
    logged_in_block = APP_JS.split("if (loggedIn) {", 1)[1].split("} else {", 1)[0]
    assert "_navigateTo" in logged_in_block
    assert "review" in logged_in_block
    assert "_showReviewPage" in APP_JS
    assert "await Auth.login(username, password);" in APP_JS
    login_success_block = APP_JS.split("await Auth.login(username, password);", 1)[1].split("} catch", 1)[0]
    assert "this._showReviewPage();" in login_success_block


def test_review_page_uses_column_layout():
    assert "#user-page, #admin-page, #review-page" in CSS


def test_review_sidebar_section_titles_are_lifted_without_reflowing_content():
    assert ">项目列表<" in HTML
    assert ">审查项目<" not in HTML
    assert ".review-sidebar-section > .sidebar-header" in CSS
    assert "transform: translateY(calc(-1 * var(--review-section-title-lift)))" in CSS
    assert "--review-section-title-lift: 11px" in CSS
    assert "--review-section-title-lift: 14px" in CSS
    assert "--review-section-title-lift: 12px" in CSS


def test_review_actions_require_single_selected_document():
    assert "selectedDocumentId" in REVIEW_JS
    assert "this.selectedDocumentId = id;" in REVIEW_JS
    assert "document_ids: mode === 'full' ? undefined : [this.selectedDocumentId]" in REVIEW_JS
    assert "_syncActionAvailability()" in REVIEW_JS


def test_disabled_action_cards_have_overlay_style():
    assert ".action-card.is-disabled::after" in CSS
    assert "rgba(128, 128, 128, 0.2)" in CSS
    assert ".doc-item.selected" in CSS


def test_review_workspace_exposes_user_managed_reference_materials():
    assert "history-upload-input" in HTML
    assert "project-specs-input" in HTML
    assert "professional-guidance-input" in HTML
    assert "团队指导意见" in HTML
    assert "uploadHistoricalDocs" in API_JS
    assert "uploadHistoricalDocs(files)" in REVIEW_JS
    assert "saveResourceContext('specifications')" in REVIEW_JS
    assert "saveResourceContext('professional_guidance')" in REVIEW_JS
    assert ".review-resource-panel" in CSS


def test_review_model_selector_lives_in_review_topbar():
    review_topbar = HTML.split('<div id="review-page" class="page">', 1)[1].split('<div class="app-layout">', 1)[0]
    assert '<div class="topbar-selects review-topbar-selects">' in review_topbar
    assert 'id="review-model-select"' in review_topbar
    assert 'class="select-mini"' in review_topbar
    assert 'aria-label="选择审查模型"' in review_topbar
    assert 'id="review-model-status"' in review_topbar

    review_workspace = HTML.split('<div id="review-workspace" class="review-workspace"', 1)[1].split('<div class="action-grid"', 1)[0]
    assert 'model-selector-bar' not in review_workspace


def test_review_workspace_header_shows_selected_document_title():
    review_workspace = HTML.split('<div id="review-workspace" class="review-workspace"', 1)[1].split('<div class="action-grid"', 1)[0]
    assert 'workspace-doc-titlebar' in review_workspace
    assert 'id="workspace-selected-doc-title"' in review_workspace
    assert '选择左侧文档后开始审查' in review_workspace

    assert "_syncSelectedDocTitle()" in REVIEW_JS
    select_doc_block = REVIEW_JS.split("selectDocument(id)", 1)[1].split("_navigateOnDocSwitch", 1)[0]
    assert "this._syncSelectedDocTitle();" in select_doc_block
    assert ".workspace-doc-titlebar" in CSS
    assert ".workspace-selected-doc-title" in CSS


def test_review_workspace_separates_project_context_and_current_document_sections():
    assert '>项目上下文<' in HTML
    assert '>当前文档<' in HTML
    assert 'data-context-tab="history"' in HTML
    assert 'data-context-tab="specs"' in HTML
    assert 'data-context-tab="guidance"' in HTML
    assert 'data-context-panel="history"' in HTML
    assert 'data-context-panel="specs"' in HTML
    assert 'data-context-panel="guidance"' in HTML


def test_review_context_prefills_default_team_review_rules():
    assert "DEFAULT_TEAM_REVIEW_GUIDANCE" in REVIEW_JS
    assert "需求范围要写实" in REVIEW_JS
    set_context_block = REVIEW_JS.split("_setContextInputs(data)", 1)[1].split("_setResourceControlsEnabled", 1)[0]
    assert "const guidance = data.professional_guidance || this.DEFAULT_TEAM_REVIEW_GUIDANCE;" in set_context_block
    assert "guidance.join('\\n')" in set_context_block


def test_review_workspace_binds_project_context_tabs():
    assert "_bindContextTabs()" in REVIEW_JS
    bind_context_tabs_block = REVIEW_JS.split("_bindContextTabs() {", 1)[1].split("_bindActionCards()", 1)[0]
    assert "querySelectorAll('.context-tab')" in bind_context_tabs_block
    assert "dataset.contextTab" in bind_context_tabs_block
    assert ".context-tab" in CSS
    assert ".context-tab.active" in CSS
    assert ".review-resource-section.active" in CSS


def test_review_workspace_uses_compact_action_grid():
    assert 'class="action-grid"' in HTML
    assert '.action-grid {' in CSS
    action_grid_block = CSS.split('.action-grid {', 1)[1].split('}', 1)[0]
    assert 'grid-template-columns: repeat(3' in action_grid_block


def test_project_context_panel_keeps_stable_height_across_tabs():
    resource_panel_block = CSS.split('.review-resource-panel {', 1)[1].split('}', 1)[0]
    assert 'min-height' in resource_panel_block


def test_current_document_section_has_gray_divider():
    current_doc_block = CSS.split('.workspace-current-doc {', 1)[1].split('}', 1)[0]
    assert 'border-top: 2px solid' in current_doc_block
    assert 'padding-top' in current_doc_block


def test_pm_assessment_tab_uses_same_data_from_all_entry_modes():
    assert "this._normalizePmAssessment(report.system_review?.pm_growth)" in REVIEW_JS
    assert "const candidatePm =" in REVIEW_JS
    assert "if (candidatePm && !this._normalizePmAssessment(merged.pm_assessment))" in REVIEW_JS
    assert "_unwrapPmAssessment(value)" in REVIEW_JS
    assert "current.pm_scores" in REVIEW_JS
    assert "current.dimensions?.pm_assessment" in REVIEW_JS
    assert "value.highlights?.length" in REVIEW_JS


def test_frontend_emits_structured_audit_actions():
    log_block = API_JS.split("/* 前端日志 */", 1)[1]
    assert "Authorization" in log_block
    assert "action" in log_block
    assert "frontend.navigation" in APP_JS
    assert "project.select" in REVIEW_JS
    assert "document.select" in REVIEW_JS
    assert "review.mode_click" in REVIEW_JS
    assert "result.tab_click" in REVIEW_JS


def test_sse_progress_uses_ephemeral_ticket_instead_of_main_jwt_query():
    progress_block = API_JS.split("getReviewProgress(projectId, reviewId)", 1)[1].split("async getReviewTaskStatus", 1)[0]
    assert "/api/auth/sse-ticket" in progress_block
    assert "await fetch('/api/auth/sse-ticket'" in progress_block
    assert "?token=${encodeURIComponent(token)}" not in progress_block
    assert "new EventSource(`${url}?ticket=${encodeURIComponent(data.ticket)}`)" in progress_block

    listen_progress_block = REVIEW_JS.split("async _listenProgress(taskId)", 1)[1].split("async _refreshRunningResult()", 1)[0]
    assert "this.eventSource = await API.getReviewProgress(this.currentProjectId, taskId);" in listen_progress_block


def test_review_state_is_reset_when_switching_authenticated_users():
    assert "resetState()" in REVIEW_JS
    assert "currentProjectId = null" in REVIEW_JS
    assert "clear('doc-list')" in REVIEW_JS
    assert "clear('historical-doc-list')" in REVIEW_JS
    assert "_resetSessionState()" in APP_JS
    assert "await Auth.login(username, password);" in APP_JS
    login_success_block = APP_JS.split("await Auth.login(username, password);", 1)[1].split("} catch", 1)[0]
    assert "this._resetSessionState();" in login_success_block
    register_success_block = APP_JS.split("await Auth.register(username, password);", 1)[1].split("} catch", 1)[0]
    assert "this._resetSessionState();" in register_success_block


def test_review_async_loads_ignore_stale_user_session_after_reset():
    assert "_stateVersion" in REVIEW_JS
    assert "_nextStateVersion()" in REVIEW_JS
    assert "_isStaleState(stateVersion)" in REVIEW_JS
    assert "const stateVersion = this._stateVersion;" in REVIEW_JS
    assert "if (this._isStaleState(stateVersion)) return;" in REVIEW_JS

    load_projects_block = REVIEW_JS.split("async loadProjects()", 1)[1].split("async selectProject", 1)[0]
    assert "const stateVersion = this._stateVersion;" in load_projects_block
    assert "if (this._isStaleState(stateVersion)) return;" in load_projects_block

    load_project_detail_block = REVIEW_JS.split("async loadProjectDetail(id)", 1)[1].split("_renderDocList", 1)[0]
    assert "const stateVersion = this._stateVersion;" in load_project_detail_block
    assert "this._isStaleState(stateVersion) || this.currentProjectId !== id" in load_project_detail_block


def test_failed_review_also_switches_to_result_page():
    listen_progress_block = REVIEW_JS.split("_listenProgress(taskId)", 1)[1].split("async _refreshRunningResult()", 1)[0]
    assert "['completed', 'completed_with_warnings', 'failed', 'cancelled'].includes(data.task_status)" in listen_progress_block
    assert "this._showResult({ preserveActiveTab: true });" in listen_progress_block

    poll_progress_block = REVIEW_JS.split("async _pollProgress(taskId)", 1)[1].split("_updateProgress(data) {", 1)[0]
    assert "['completed', 'completed_with_warnings', 'failed', 'cancelled'].includes(data.task_status)" in poll_progress_block
    assert "this._showResult({ preserveActiveTab: true });" in poll_progress_block


def test_failed_review_is_included_in_tasks_with_results():
    load_review_history_block = REVIEW_JS.split("async _loadReviewHistory(projectId, stateVersion = this._stateVersion)", 1)[1].split("_isDocModeCompleted", 1)[0]
    assert "const tasksWithResults = (tasks || []).filter(t => ['completed', 'completed_with_warnings', 'cancelled', 'failed'].includes(t.status));" in load_review_history_block
    assert "this._reviewDocMap[key] = { taskId: task.task_id, status: task.status };" in load_review_history_block


def test_batch_system_review_tasks_do_not_populate_single_doc_history():
    load_review_history_block = REVIEW_JS.split("async _loadReviewHistory(projectId, stateVersion = this._stateVersion)", 1)[1].split("_isDocModeCompleted", 1)[0]
    assert "const sharedResultModes = new Set(['review', 'insight', 'draft', 'pm']);" in load_review_history_block
    assert "if (task.mode === 'full') return;" in load_review_history_block
    assert "if (sharedResultModes.has(task.mode) && task.total_docs !== 1) return;" in load_review_history_block


def test_full_action_card_click_does_not_require_selected_document():
    bind_action_cards_block = REVIEW_JS.split("_bindActionCards()", 1)[1].split("async startReview(mode)", 1)[0]
    assert "const mode = card.dataset.mode;" in bind_action_cards_block
    assert "if (mode !== 'full' && !this.selectedDocumentId) return;" in bind_action_cards_block


def test_failed_review_has_interrupted_label_and_title():
    reviewed_block = REVIEW_JS.split("_isDocModeReviewed(docId, mode)", 1)[1].split("_updateActionCardStatus", 1)[0]
    assert "if (entry.status === 'failed') return { ...entry, label: '未完成' };" in reviewed_block

    result_title_block = REVIEW_JS.split("_syncResultTitle() {", 1)[1].split("_updateResultActions() {", 1)[0]
    assert "reviewed && reviewed.status === 'failed'" in result_title_block
    assert "（审查中断）" in result_title_block


def test_review_doc_status_maps_classified_and_analysis_failed():
    compute_status_block = REVIEW_JS.split("_computeDocStatus(doc)", 1)[1].split("selectDocument(id)", 1)[0]
    assert "if (dbStatus === 'classified') {" in compute_status_block
    assert "return { statusClass: 'classified', statusLabel: '已分类' };" in compute_status_block
    assert "if (dbStatus === 'analysis_failed') {" in compute_status_block
    assert "return { statusClass: 'failed', statusLabel: '分析失败' };" in compute_status_block

    status_label_block = REVIEW_JS.split("_statusLabel(s)", 1)[1].split("/* ── 文档上传 ── */", 1)[0]
    assert "classified: '已分类'" in status_label_block
    assert "analysis_failed: '分析失败'" in status_label_block


def test_load_review_history_triggers_doc_list_rerender():
    load_review_history_block = REVIEW_JS.split("async _loadReviewHistory(projectId, stateVersion = this._stateVersion)", 1)[1].split("_isDocModeCompleted", 1)[0]
    assert "if (this._docsCache.length) {" in load_review_history_block
    assert "this._renderDocList(this._docsCache);" in load_review_history_block


def test_start_review_reuses_existing_completed_result():
    start_review_block = REVIEW_JS.split("async startReview(mode)", 1)[1].split("async reReview()", 1)[0]
    assert "const existing = this._isDocModeReviewed(this.selectedDocumentId, mode);" in start_review_block
    assert "this.currentTaskId = existing.taskId;" in start_review_block
    assert "this._showResult();" in start_review_block
    assert start_review_block.index("this._showResult();") < start_review_block.index("const resp = await API.startReview(this.currentProjectId, {")


def test_start_review_embeds_progress_inside_result_panel_instead_of_switching_page():
    start_review_block = REVIEW_JS.split("async startReview(mode)", 1)[1].split("async reReview()", 1)[0]
    assert "this._showProgress(mode);" not in start_review_block
    assert "this._showResult({" in start_review_block
    assert "_renderEmbeddedProgress(" in REVIEW_JS

    show_result_block = REVIEW_JS.split("async _showResult(options = {}) {", 1)[1].split("async _aggregateDocReports", 1)[0]
    assert "this._renderEmbeddedProgress(" in show_result_block


def test_result_tab_switch_uses_running_task_for_selected_doc_mode():
    assert "_findDocModeTask(docId, mode, statuses = null)" in REVIEW_JS
    assert "this._findDocModeTask(docId, preferredMode, ['running', 'pending'])" in REVIEW_JS

    bind_result_actions_block = REVIEW_JS.split("_bindResultActions() {", 1)[1].split("_syncResultTitle() {", 1)[0]
    assert "const runningTask = this._findDocModeTask(this.selectedDocumentId, tabMode, ['running', 'pending']);" in bind_result_actions_block
    assert "await this._showResult({ activeTab: tab.dataset.tab, preserveActiveTab: true });" in bind_result_actions_block


def test_action_card_shows_completed_badge_for_existing_mode():
    action_card_status_block = REVIEW_JS.split("_updateActionCardStatus()", 1)[1].split("_statusLabel(s)", 1)[0]
    assert "const reviewed = this._isDocModeReviewed(docId, mode);" in action_card_status_block
    assert "badge.textContent = reviewed.label;" in action_card_status_block
    assert "badge.classList.toggle('badge-cancelled', reviewed.status === 'cancelled');" in action_card_status_block


def test_draft_mode_pipeline_steps_include_system_review():
    draft_mode_block = REVIEW_JS.split("draft:", 1)[1].split("pm:", 1)[0]
    assert "label: '基于历史生成PRD'" in draft_mode_block
    assert "steps: ['预处理', '分类', '逐篇分析', '体系Review', '需求洞察', 'PRD草稿生成', '报告生成']" in draft_mode_block


def test_start_review_shows_progress_instead_of_running_result():
    start_review_block = REVIEW_JS.split("async startReview(mode)", 1)[1].split("async reReview()", 1)[0]
    assert "await this._showResult({ activeTab: (this.MODE_MAP[mode] || this.MODE_MAP.quick).defaultTab, preserveActiveTab: true });" in start_review_block
    assert "this._listenProgress(resp.task_id);" in start_review_block
    assert "_showResultForRunning" not in start_review_block


def test_start_review_ignores_duplicate_clicks_while_running():
    start_review_block = REVIEW_JS.split("async startReview(mode)", 1)[1].split("async reReview()", 1)[0]
    assert "if (this._isReviewRunning) return;" in start_review_block
    assert "this._isReviewRunning = true;" in start_review_block
    assert "this._isReviewRunning = false;" in start_review_block
    assert start_review_block.index("if (this._isReviewRunning) return;") < start_review_block.index("const resp = await API.startReview")
    assert start_review_block.index("this._isReviewRunning = true;") < start_review_block.index("const resp = await API.startReview")


def test_rereview_shows_progress_instead_of_running_result():
    rereview_block = REVIEW_JS.split("async reReview()", 1)[1].split("/* ── 进度跟踪 ── */", 1)[0]
    assert "await this._showResult({ activeTab: (this.MODE_MAP[mode] || this.MODE_MAP.quick).defaultTab, preserveActiveTab: true });" in rereview_block
    assert "this._listenProgress(resp.task_id);" in rereview_block
    assert "_showResultForRunning" not in rereview_block


def test_rereview_ignores_duplicate_clicks_while_running():
    rereview_block = REVIEW_JS.split("async reReview()", 1)[1].split("/* ── 进度跟踪 ── */", 1)[0]
    assert "if (this._isReviewRunning) return;" in rereview_block
    assert rereview_block.index("if (this._isReviewRunning) return;") < rereview_block.index("const resp = await API.startReview")


def test_progress_updates_require_step_indicator_dom():
    show_progress_block = REVIEW_JS.split("_showProgress(mode, taskInfo)", 1)[1].split("_listenProgress(taskId)", 1)[0]
    assert "id=\"step-ind-${i}\"" in show_progress_block
    assert "id=\"step-detail-${i}\"" in show_progress_block
    assert "id=\"step-time-${i}\"" in show_progress_block

    update_progress_block = REVIEW_JS.split("_updateProgress(data)", 1)[1].split("_showResult(taskId = this.currentTaskId)", 1)[0]
    assert "document.getElementById(`step-ind-${i}`)" in update_progress_block
    assert "document.getElementById(`step-detail-${i}`)" in update_progress_block


def test_progress_panel_shows_skill_names_beside_steps():
    show_progress_block = REVIEW_JS.split("_showProgress(mode, taskInfo)", 1)[1].split("async _listenProgress(taskId)", 1)[0]
    assert "class=\"step-skill\"" in show_progress_block
    assert "modeConfig.skills?.[i]" in show_progress_block

    assert "docx-to-markdown" in REVIEW_JS
    assert "prd-overview-classify" in REVIEW_JS
    assert "prd-per-analysis" in REVIEW_JS
    assert "system-review" in REVIEW_JS
    assert "requirement-insights" in REVIEW_JS
    assert "report-generator" in REVIEW_JS
    assert ".step-skill" in CSS


def test_single_doc_per_analysis_avoids_repeating_document_title_in_card_header():
    per_analysis_block = REVIEW_JS.split("_renderPerAnalysis(report)", 1)[1].split("toggleAnalysisCard(idx)", 1)[0]
    assert "const isSingleDocView = filtered.length === 1;" in per_analysis_block
    assert "const cardTitle = isSingleDocView ? '分析结果' : (a.filename || a.doc_id || '');" in per_analysis_block
    assert "<span class=\"doc-analysis-title\">${this._esc(cardTitle)}</span>" in per_analysis_block


def test_render_bullet_list_parses_json_array_strings():
    render_bullet_list_block = REVIEW_JS.split("_renderBulletList(text)", 1)[1].split("_renderSystemReview(report)", 1)[0]
    assert "if (str.startsWith('[')) {" in render_bullet_list_block
    assert "const parsed = JSON.parse(str);" in render_bullet_list_block
    assert "if (Array.isArray(parsed) && parsed.length) {" in render_bullet_list_block


def test_per_analysis_renders_expert_review_dimension_separately():
    assert "_renderExpertReview(expertReview)" in REVIEW_JS
    assert "_expertReviewStatusMeta(status)" in REVIEW_JS
    assert "专家意见评审结论" in REVIEW_JS
    assert "整体结论" in REVIEW_JS
    assert "六项规则核查" in REVIEW_JS
    assert "a.expert_review" in REVIEW_JS


def test_per_analysis_renders_expert_review_at_bottom():
    per_analysis_block = REVIEW_JS.split("_renderPerAnalysis(report)", 1)[1].split("toggleAnalysisCard(idx)", 1)[0]
    assert per_analysis_block.index("规范合规") < per_analysis_block.index("${this._renderExpertReview(a.expert_review)}")


def test_re_review_forces_fresh_backend_analysis():
    re_review_block = REVIEW_JS.split("async reReview()", 1)[1].split("/* ── 进度跟踪 ── */", 1)[0]

    assert "force_reanalysis: true" in re_review_block


def test_markdown_code_blocks_render_copy_button():
    markdown_block = REVIEW_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1].split("_renderMarkdownFallback(text) {", 1)[0]
    assert "const renderer = new window.marked.Renderer();" in markdown_block
    assert "renderer.code = (code, infostring) => {" in markdown_block
    assert "code-block-wrapper" in markdown_block
    assert "code-block-header" in markdown_block
    assert "code-copy-btn" in markdown_block
    assert "data-code=" in markdown_block
    assert ".code-block-wrapper" in CSS
    assert ".code-block-header" in CSS
    assert ".code-copy-btn" in CSS


def test_markdown_copy_button_handler_is_bound():
    bind_result_actions_block = REVIEW_JS.split("_bindResultActions()", 1)[1].split("_syncResultTitle() {", 1)[0]
    assert "document.getElementById('result-content').addEventListener('click', (e) => {" in bind_result_actions_block
    assert "const btn = e.target.closest('.code-copy-btn');" in bind_result_actions_block
    assert "const code = btn.dataset.code;" in bind_result_actions_block
    assert "navigator.clipboard.writeText(code)" in bind_result_actions_block
    assert "document.execCommand('copy');" in bind_result_actions_block
    assert "btn.textContent = '已复制';" in bind_result_actions_block


def test_result_tab_click_syncs_current_mode_before_rereview():
    bind_result_actions_block = REVIEW_JS.split("_bindResultActions()", 1)[1].split("_syncResultTitle() {", 1)[0]
    assert "const TAB_MODE_MAP = {" in bind_result_actions_block
    assert "const tabMode = TAB_MODE_MAP[tab.dataset.tab];" in bind_result_actions_block
    assert "if (tabMode) {" in bind_result_actions_block
    assert "this.currentMode = tabMode;" in bind_result_actions_block
    assert "this.reReview();" in bind_result_actions_block


def test_overview_tab_does_not_force_full_entry_selection():
    bind_result_actions_block = REVIEW_JS.split("_bindResultActions()", 1)[1].split("_syncResultTitle() {", 1)[0]
    assert "'overview': 'full'" not in bind_result_actions_block


def test_result_tab_click_syncs_action_card_selection_and_doc_task():
    bind_result_actions_block = REVIEW_JS.split("_bindResultActions()", 1)[1].split("_syncResultTitle() {", 1)[0]
    assert "this._syncActionCardSelection(tabMode);" in bind_result_actions_block
    assert "const targetTask = this._resolveResultTask(this.selectedDocumentId, tabMode);" in bind_result_actions_block
    assert "if (targetTask?.taskId && targetTask.taskId !== this.currentTaskId) {" in bind_result_actions_block
    assert "await this._showResult({ activeTab: tab.dataset.tab, preserveActiveTab: true });" in bind_result_actions_block


def test_review_js_exposes_result_task_resolution_helpers():
    assert "_syncActionCardSelection(mode) {" in REVIEW_JS
    assert "_resolveResultTask(docId, preferredMode = this.currentMode) {" in REVIEW_JS
    assert "_findLatestTaskForDocument(docId, statuses = null) {" in REVIEW_JS
    assert "return this._findLatestTaskForDocument(docId, ['running', 'pending']) || this._findLatestTaskForDocument(docId);" in REVIEW_JS


def test_action_card_selection_helper_can_clear_selection():
    helper_block = REVIEW_JS.split("_syncActionCardSelection(mode) {", 1)[1].split("_findLatestTaskForDocument(docId) {", 1)[0]
    assert "card.classList.toggle('selected', mode && card.dataset.mode === mode);" in helper_block


def test_show_result_can_preserve_active_result_tab():
    assert "async _showResult(options = {}) {" in REVIEW_JS
    show_result_block = REVIEW_JS.split("async _showResult(options = {}) {", 1)[1].split("async _aggregateDocReports", 1)[0]
    assert "const { activeTab = null, preserveActiveTab = false } = options;" in show_result_block
    assert "if (activeTab) {" in show_result_block
    assert "} else if (!preserveActiveTab) {" in show_result_block
    assert "this._setActiveResultTab(activeTab);" in show_result_block


def test_doc_switch_prefers_any_available_result_and_opens_overview():
    switch_block = REVIEW_JS.split("_navigateOnDocSwitch() {", 1)[1].split("_currentResultContainsDocument(docId) {", 1)[0]
    assert "const fallback = this._resolveResultTask(docId, mode);" in switch_block
    assert "} else if (fallback?.taskId) {" in switch_block
    assert "this._syncActionCardSelection(null);" in switch_block
    assert "this.currentTaskId = fallback.taskId;" in switch_block
    assert "this._showResult({ activeTab: 'overview' });" in switch_block


def test_doc_switch_from_workspace_can_open_overview_without_selected_entry():
    switch_block = REVIEW_JS.split("_navigateOnDocSwitch() {", 1)[1].split("_currentResultContainsDocument(docId) {", 1)[0]
    assert "const hasVisibleResult = this._shellState !== 'no-result';" in switch_block
    assert "if (!hasVisibleResult && !fallback?.taskId) {" in switch_block
    assert "if (!hasVisibleResult) {" in switch_block
    assert "this._showResult({ activeTab: 'overview' });" in switch_block


def test_insight_tab_filters_schema_noise_fields():
    insight_block = REVIEW_JS.split("_renderInsight(report) {", 1)[1].split("_renderDraft(report) {", 1)[0]
    assert "const evMatches = (insights.evolution?.matches || []).filter(m => m && typeof m === 'object');" in insight_block
    assert "const featureDims = (insights.features?.feature_dimensions || []).filter(f => f && typeof f === 'object');" in insight_block
    assert "const gapItems = (insights.gap?.gap_assessments || []).filter(g => g && typeof g === 'object');" in insight_block
    assert "project_name" not in insight_block
    assert "output_type" not in insight_block
    assert "_schema_valid" not in insight_block


def test_insight_tab_renders_evolution_feature_and_gap_sections():
    insight_block = REVIEW_JS.split("_renderInsight(report) {", 1)[1].split("_renderDraft(report) {", 1)[0]
    assert "insight-evo-list" in insight_block
    assert "insight-feature-grid" in insight_block
    assert "insight-gap-list" in insight_block
    assert "演进追踪" in insight_block
    assert "功能全景" in insight_block
    assert "缺口与重叠分析" in insight_block


def test_auth_init_keeps_token_on_network_failure():
    assert "const token = API.getToken();" in AUTH_JS
    assert "this.currentUser = await API.getMe();" in AUTH_JS
    assert "if (e.message && (e.message.includes('401') || e.message.includes('403'))) {" in AUTH_JS
    assert "API.clearToken();" in AUTH_JS
    assert "this.currentUser = { id: 0, username: '用户', role: 'user' };" in AUTH_JS
    assert "return true;" in AUTH_JS.split("this.currentUser = { id: 0, username: '用户', role: 'user' };", 1)[1]


def test_last_page_is_restored_after_refresh():
    init_block = APP_JS.split("async init()", 1)[1].split("_showLoading()", 1)[0]
    assert "const loggedIn = await Auth.init();" in APP_JS
    assert "const lastPage = sessionStorage.getItem('lastPage') || 'review';" in APP_JS
    assert "this._navigateTo(lastPage);" in APP_JS


def test_login_page_is_not_active_before_auth_bootstrap():
    login_page_line = [line for line in HTML.splitlines() if 'id="login-page"' in line][0]
    assert 'class="page"' in login_page_line
    assert 'active' not in login_page_line


def test_app_shows_loading_before_auth_resolution():
    init_block = APP_JS.split("async init()", 1)[1].split("_showLoading() {", 1)[0]
    assert "this._showLoading();" in init_block
    assert "const loggedIn = await Auth.init();" in init_block
    assert init_block.index("this._showLoading();") < init_block.index("const loggedIn = await Auth.init();")
    assert "loader.id = 'app-loader';" in APP_JS
    assert "loader.textContent = '加载中…';" in APP_JS


def test_review_shell_container_exists_in_html():
    assert 'class="review-shell no-result"' in HTML
    assert 'id="review-shell"' in HTML


def test_review_shell_has_work_panel_and_result_panel():
    assert 'class="review-work-panel"' in HTML
    assert 'class="review-result-panel"' in HTML
    assert 'class="review-work-panel-body"' in HTML
    assert 'class="review-result-panel-body"' in HTML


def test_review_work_panel_contains_empty_and_workspace():
    work_panel_block = HTML.split('class="review-work-panel"', 1)[1].split('class="review-result-panel"', 1)[0]
    assert 'id="review-empty"' in work_panel_block
    assert 'id="review-workspace"' in work_panel_block


def test_review_result_panel_contains_progress_and_result():
    result_panel_block = HTML.split('class="review-result-panel"', 1)[1].split('</section>', 1)[0]
    assert 'id="review-progress"' in result_panel_block
    assert 'id="review-result"' in result_panel_block


def test_review_shell_css_grid_rules():
    assert ".review-shell" in CSS
    assert "grid-template-columns" in CSS.split(".review-shell {", 1)[1].split("}", 1)[0]
    assert ".review-shell.has-result" in CSS
    assert ".review-shell.no-result .review-result-panel" in CSS
    # Animation approach: visibility:hidden + max-width:0 instead of display:none
    no_result_block = CSS.split(".review-shell.no-result .review-result-panel", 1)[1].split("}", 1)[0]
    assert "visibility: hidden" in no_result_block
    assert "max-width: 0" in no_result_block


def test_review_shell_has_1279px_responsive_breakpoint():
    assert "@media (max-width: 1279px)" in CSS
    # There are multiple 1279px blocks (chat + review); find the one with review-shell
    blocks = CSS.split("@media (max-width: 1279px)")
    review_block = [b for b in blocks if "review-shell" in b.split("}", 1)[0]][0]
    assert "review-shell" in review_block


def test_review_js_set_shell_state_manages_classes():
    assert "_setShellState" in REVIEW_JS
    assert "shell.classList.remove('no-result', 'has-result')" in REVIEW_JS
    assert "shell.classList.add(state)" in REVIEW_JS


def test_review_js_show_progress_keeps_workspace_visible():
    progress_block = REVIEW_JS.split("_showProgress(mode, taskInfo)", 1)[1].split("_renderEmbeddedProgress(mode, taskInfo = null)", 1)[0]
    assert "this._renderEmbeddedProgress(mode, taskInfo);" in progress_block

    embedded_progress_block = REVIEW_JS.split("_renderEmbeddedProgress(mode, taskInfo = null)", 1)[1].split("async _listenProgress(taskId)", 1)[0]
    assert "id=\"progress-task-title\"" in embedded_progress_block
    assert "id=\"pipeline-steps\"" in embedded_progress_block
    assert "id=\"progress-docs\"" in embedded_progress_block


def test_review_js_show_result_keeps_workspace_visible():
    result_block = REVIEW_JS.split("async _showResult(options = {})", 1)[1].split("// All 6 tabs", 1)[0]
    assert "review-workspace" in result_block
    workspace_line = [l for l in result_block.splitlines() if "review-workspace" in l][0]
    assert "style.display = ''" in workspace_line


def test_review_shell_css_includes_transition_animation():
    shell_block = CSS.split(".review-shell {", 1)[1].split("}", 1)[0]
    assert "transition" in shell_block
    assert "grid-template-columns" in shell_block
    assert "0.25s" in shell_block
    # Standalone .review-result-panel has transition on opacity+transform
    standalone_panel = CSS.split(".review-result-panel {\n")
    # Find the one with border-left (the standalone definition, not the nested one)
    panel_block = [b for b in standalone_panel if "border-left" in b.split("}", 1)[0]][0]
    panel_def = panel_block.split("}", 1)[0]
    assert "transition" in panel_def
    assert "opacity" in panel_def


def test_review_navigate_on_doc_switch_shows_empty_state_not_collapse():
    switch_block = REVIEW_JS.split("_navigateOnDocSwitch()", 1)[1].split("_showResult()", 1)[1].split("}", 1)[0]
    assert "_showResultEmptyState" in REVIEW_JS
    # When doc has no history, show empty state in result panel (not collapse to two-column)
    else_block = REVIEW_JS.split("新文档没有当前模式的历史", 1)[1].split("}", 1)[0]
    assert "_showResultEmptyState" in else_block


def test_review_navigate_on_doc_switch_reuses_loaded_batch_result_for_new_doc():
    switch_block = REVIEW_JS.split("_navigateOnDocSwitch() {", 1)[1].split("_currentResultContainsDocument(docId) {", 1)[0]
    assert "const currentResultHasDoc = this._currentResultContainsDocument(docId);" in switch_block
    assert "} else if (currentResultHasDoc) {" in switch_block
    assert "this._showResult();" in switch_block

    helper_block = REVIEW_JS.split("_currentResultContainsDocument(docId) {", 1)[1].split("_showWorkspace()", 1)[0]
    assert "this._lastReport?.analyses" in helper_block
    assert "analyses.some(a => a.document_id === docId)" in helper_block


def test_review_result_header_and_tabs_have_sticky_css():
    result_header_block = CSS.split(".result-header {", 1)[1].split("}", 1)[0]
    assert "position: sticky" in result_header_block
    assert "z-index" in result_header_block
    result_tabs_block = CSS.split(".result-tabs {", 1)[1].split("}", 1)[0]
    assert "position: sticky" in result_tabs_block


def test_review_result_header_uses_two_rows_with_truncated_title():
    result_header_block = CSS.split(".result-header {", 1)[1].split("}", 1)[0]
    assert "display: grid" in result_header_block
    assert "grid-template-columns: minmax(0, 1fr)" in result_header_block

    result_title_block = CSS.split(".result-title {", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap" in result_title_block
    assert "overflow: hidden" in result_title_block
    assert "text-overflow: ellipsis" in result_title_block

    result_actions_block = CSS.split(".result-actions {", 1)[1].split("}", 1)[0]
    assert "justify-self: start" in result_actions_block


def test_review_workspace_doc_titlebar_has_sticky_css():
    titlebar_block = CSS.split(".workspace-doc-titlebar {", 1)[1].split("}", 1)[0]
    assert "position: sticky" in titlebar_block


def test_chat_shell_grid_container_in_html():
    assert 'id="chat-shell"' in HTML
    assert 'class="chat-shell"' in HTML


def test_chat_context_panel_in_html():
    assert 'class="chat-context-panel"' in HTML
    assert 'id="chat-context-panel"' in HTML
    assert 'id="chat-context-body"' in HTML


def test_chat_context_sections_in_html():
    assert 'data-type="historical_doc"' in HTML
    assert 'data-type="rule_doc"' in HTML
    assert 'data-type="temporary"' in HTML
    assert 'data-type="manual_rule"' in HTML


def test_chat_shell_css_grid_rules():
    assert ".chat-shell" in CSS
    shell_block = CSS.split(".chat-shell {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns" in shell_block
    assert "var(--sidebar-width)" in shell_block
    assert "var(--chat-context-width)" in shell_block


def test_chat_shell_children_stretch_to_full_height():
    shell_block = CSS.split(".chat-shell {", 1)[1].split("}", 1)[0]
    stretch_block = CSS.split(".chat-shell > .sidebar,", 1)[1].split("}", 1)[0]
    assert "flex: 1" in shell_block
    assert "min-height: 0" in shell_block
    assert "height: 100%" in shell_block
    assert "max-height: 100%" in shell_block
    assert "align-items: stretch" in shell_block
    assert "height: 100%" in stretch_block
    assert "align-self: stretch" in stretch_block


def test_user_page_uses_two_row_grid_for_full_height_chat_shell():
    user_page_block = CSS.split("#user-page.active {", 1)[1].split("}", 1)[0]
    assert "display: grid" in user_page_block
    assert "grid-template-rows: var(--topbar-height) minmax(0, 1fr)" in user_page_block
    assert "overflow: hidden" in user_page_block


def test_context_drawer_is_hidden_until_opened():
    assert 'id="context-drawer-overlay" class="context-drawer-overlay" hidden' in HTML
    assert 'id="context-drawer" class="context-drawer" hidden' in HTML
    toggle_block = CHAT_JS.split("    _toggleContextDrawer() {", 1)[1].split("    _closeContextDrawer() {", 1)[0]
    close_block = CHAT_JS.split("    _closeContextDrawer() {", 1)[1].split("    async _searchConversations", 1)[0]
    assert "drawer.hidden = false" in toggle_block
    assert "overlay.hidden = false" in toggle_block
    assert "drawer.hidden = true" in close_block
    assert "overlay.hidden = true" in close_block


def test_chat_context_panel_css_rules():
    assert ".chat-context-panel" in CSS
    assert ".chat-context-head" in CSS
    assert ".chat-context-body" in CSS
    assert ".context-section" in CSS
    assert ".context-item" in CSS


def test_chat_shell_has_1279px_responsive_breakpoint():
    assert "@media (max-width: 1279px)" in CSS
    blocks = CSS.split("@media (max-width: 1279px)")
    chat_block = [b for b in blocks if "chat-shell" in b.split("}", 1)[0]]
    assert len(chat_block) > 0


def test_chat_js_has_context_items_and_rules_state():
    assert "_contextItems" in CHAT_JS
    assert "_contextRules" in CHAT_JS
    assert "_renderContextPanel" in CHAT_JS
    assert "_bindContextEvents" in CHAT_JS


def test_chat_js_adds_context_to_send_payload():
    send_block = CHAT_JS.split("API.chatStream({", 1)[1].split("})", 1)[0]
    assert "contextFileIds" in send_block
    assert "contextRules" in send_block
