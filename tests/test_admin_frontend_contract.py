from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "src/static/js/app.js").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "src/static/js/auth.js").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "src/static/js/admin.js").read_text(encoding="utf-8")
API_JS = (ROOT / "src/static/js/api.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")


def test_admin_back_button_uses_chat_origin():
    bind_navigation_block = APP_JS.split("// Go to admin (from chat page topbar)", 1)[1].split("// Back to chat from review", 1)[0]
    assert "this._adminFromPage = 'chat';" in bind_navigation_block
    assert "const from = this._adminFromPage || 'review';" in bind_navigation_block
    assert "this._navigateTo(from);" in bind_navigation_block


def test_admin_back_button_uses_review_origin():
    review_to_admin_block = APP_JS.split("const goAdminFromReviewBtn = document.getElementById('go-admin-from-review');", 1)[1].split("// Go to review workspace", 1)[0]
    assert "this._adminFromPage = 'review';" in review_to_admin_block
    assert "Review.destroy();" in review_to_admin_block

    back_from_admin_block = APP_JS.split("// Back from admin — return to the page we came from, default to review", 1)[1].split("// Back to chat from review", 1)[0]
    assert "const from = this._adminFromPage || 'review';" in back_from_admin_block
    assert "this._adminFromPage = null;" in back_from_admin_block
    assert "this._navigateTo(from);" in back_from_admin_block


def test_leaving_chat_cleans_up_chat_state_before_navigation():
    chat_to_admin_block = APP_JS.split("// Go to admin (from chat page topbar)", 1)[1].split("// Back from admin — return to the page we came from, default to review", 1)[0]
    assert "Chat.destroy();" in chat_to_admin_block

    chat_to_review_block = APP_JS.split("// Go to review workspace", 1)[1].split("// Add user button", 1)[0]
    assert "Chat.destroy();" in chat_to_review_block


def test_password_modal_requires_confirmation_input():
    show_change_password_block = AUTH_JS.split("showChangePassword()", 1)[1].split("async savePassword()", 1)[0]
    assert "<label>确认新密码</label>" in show_change_password_block
    assert "id=\"confirm-password\"" in show_change_password_block
    assert "placeholder=\"再次输入新密码\"" in show_change_password_block


def test_save_password_rejects_mismatched_confirmation():
    save_password_block = AUTH_JS.split("async savePassword()", 1)[1]
    assert "const confirmPwd = document.getElementById('confirm-password').value;" in save_password_block
    assert "if (!oldPwd || !newPwd || !confirmPwd) {" in save_password_block
    assert "if (newPwd !== confirmPwd) {" in save_password_block
    assert "errEl.textContent = '两次输入的新密码不一致';" in save_password_block


def test_admin_has_skills_management_tab():
    assert 'data-tab="skills"' in INDEX_HTML
    assert 'id="tab-skills"' in INDEX_HTML
    assert 'id="skill-table-body"' in INDEX_HTML
    assert "Skills 管理" in INDEX_HTML

    tab_map_block = ADMIN_JS.split("const tabMap = {", 1)[1].split("};", 1)[0]
    assert "skills: 'loadSkills'" in tab_map_block
    assert "async loadSkills()" in ADMIN_JS
    assert "editSkillUpdateUrl" in ADMIN_JS
    assert "saveSkillUpdateUrl" in ADMIN_JS

    assert "getAdminSkills(" in API_JS
    assert "updateAdminSkill(skillId, data)" in API_JS
    assert "toggleAdminSkill" in API_JS  # P4.Pre.6


def test_admin_stats_tab_is_first_and_default():
    nav_block = INDEX_HTML.split('<nav class="admin-nav">', 1)[1].split('</nav>', 1)[0]
    panels_block = INDEX_HTML.split('<main class="admin-content">', 1)[1].split('</main>', 1)[0]

    assert nav_block.find('data-tab="stats"') < nav_block.find('data-tab="users"')
    assert panels_block.find('id="tab-stats"') < panels_block.find('id="tab-users"')
    assert 'id="tab-stats" class="admin-panel active"' in INDEX_HTML
    assert 'id="tab-users" class="admin-panel"' in INDEX_HTML

    init_block = ADMIN_JS.split("init() {", 1)[1].split("_loadActiveTab(tab)", 1)[0]
    assert "localStorage.getItem('admin-active-tab') || 'stats'" in init_block
    assert "const activeTab =" in init_block
    assert "this._loadActiveTab(activeTab);" in init_block


def test_admin_stats_renders_recent_7_day_visits():
    assert "最近7天访问记录" in INDEX_HTML
    assert 'id="recent-visits-body"' in INDEX_HTML

    load_stats_block = ADMIN_JS.split("async loadStats() {", 1)[1].split("/* ── 评审风格Prompt管理 ── */", 1)[0]
    assert "s.recent_visits" in load_stats_block
    assert "_renderRecentVisits" in load_stats_block
    assert "访问时间" in INDEX_HTML
    assert "访问路径" in INDEX_HTML


def test_user_table_has_last_active_column_and_balanced_spacing():
    users_panel = INDEX_HTML.split('<div id="tab-users" class="admin-panel">', 1)[1].split('<!-- 预置对话Prompt -->', 1)[0]
    assert '<th>用户名</th><th>角色</th><th>状态</th><th>创建时间</th><th>最近访问时间</th><th style="width:168px">操作</th>' in users_panel

    load_users_block = ADMIN_JS.split('async loadUsers() {', 1)[1].split('editUser(id, username, role, isActive) {', 1)[0]
    assert 'u.last_active_at' in load_users_block
    assert 'class="user-time-cell"' in load_users_block
    assert 'class="user-actions-cell"' in load_users_block
    assert 'colspan="6"' in load_users_block

    css = (ROOT / 'src/static/css/main.css').read_text(encoding='utf-8')
    assert '.user-time-cell {' in css
    assert '.user-actions-cell {' in css


def test_model_table_has_separate_connection_and_action_headers():
    models_panel = INDEX_HTML.split('<div id="tab-models" class="admin-panel">', 1)[1].split('<!-- Skills 管理 -->', 1)[0]
    assert '<th>模型</th><th>API Base</th><th>API Key</th><th>状态</th><th style="width:190px">连接</th><th style="width:250px">操作</th>' in models_panel


def test_model_table_renders_inline_connection_status_and_right_shifted_actions():
    load_models_block = ADMIN_JS.split('async loadModels() {', 1)[1].split('createModel() {', 1)[0]
    assert 'class="model-connection-cell"' in load_models_block
    assert 'class="model-actions-cell"' in load_models_block
    assert 'class="model-actions"' in load_models_block
    assert 'data-role="model-connection-status"' in load_models_block
    assert "document.getElementById('admin-model-status')" not in load_models_block


def test_model_speed_test_updates_current_row_connection_status_instead_of_topbar():
    test_block = ADMIN_JS.split('async testAndSpeed(modelId, evt) {', 1)[1].split('async deleteModel(modelId) {', 1)[0]
    assert 'const row = document.querySelector(`tr[data-model-id="${this._escAttr(modelId)}"]`);' in test_block
    assert 'const connectionCell = row?.querySelector(\'[data-role="model-connection-status"]\');' in test_block
    assert "连接测试中..." in test_block
    assert "测速中..." in test_block
    assert "延迟 ${speedResult.latency_ms}ms" in test_block
    assert "document.getElementById('admin-model-status')" not in test_block


def test_model_table_has_unified_header_and_action_spacing_styles():
    assert '.model-actions {' in (ROOT / 'src/static/css/main.css').read_text(encoding='utf-8')
    assert '.model-actions-cell {' in (ROOT / 'src/static/css/main.css').read_text(encoding='utf-8')
    assert '.model-connection-cell {' in (ROOT / 'src/static/css/main.css').read_text(encoding='utf-8')
    css = (ROOT / 'src/static/css/main.css').read_text(encoding='utf-8')
    model_actions_block = css.split('.model-actions {', 1)[1].split('}', 1)[0]
    assert 'margin-left: 50px' in model_actions_block
    table_head_block = css.split('.table thead th {', 1)[1].split('}', 1)[0]
    assert 'background: var(--color-bg-white)' in table_head_block


def test_model_modal_has_footer_cancel_and_top_right_close():
    show_modal_block = ADMIN_JS.split('showModal(html) {', 1)[1].split('closeModal() {', 1)[0]
    assert 'class="modal-close-btn"' in show_modal_block
    assert 'aria-label="关闭弹窗"' in show_modal_block
    assert "[data-action=\"modal-close\"]" in show_modal_block

    create_model_block = ADMIN_JS.split('createModel() {', 1)[1].split('async saveNewModel()', 1)[0]
    edit_model_block = ADMIN_JS.split('editModel(modelId) {', 1)[1].split('async saveModel(modelId) {', 1)[0]
    assert 'Admin.closeModal()">取消</button>' in create_model_block
    assert 'Admin.closeModal()">取消</button>' in edit_model_block


def test_model_modal_api_key_fields_use_sensitive_input_with_toggle():
    create_model_block = ADMIN_JS.split('createModel() {', 1)[1].split('async saveNewModel()', 1)[0]
    edit_model_block = ADMIN_JS.split('editModel(modelId) {', 1)[1].split('async saveModel(modelId) {', 1)[0]
    assert 'type="password" id="modal-new-api-key"' in create_model_block
    assert 'type="password" id="modal-api-key"' in edit_model_block
    assert 'class="sensitive-input"' in create_model_block
    assert 'class="sensitive-toggle-btn"' in create_model_block
    assert '_bindSensitiveInputToggle(' in ADMIN_JS


def test_sensitive_toggle_uses_svg_icons_and_no_blur_auto_hide():
    toggle_block = ADMIN_JS.split('_bindSensitiveInputToggle(inputId) {', 1)[1].split('async _persistModelOrder', 1)[0]
    assert 'EYE_OPEN' in toggle_block
    assert 'EYE_OFF' in toggle_block
    assert 'innerHTML = isHidden ? EYE_OFF : EYE_OPEN' in toggle_block
    assert "toggle.textContent" not in toggle_block
    assert "'可见'" not in toggle_block
    assert "'隐藏'" not in toggle_block
    assert "input.addEventListener('blur'" not in toggle_block
    assert "input.addEventListener('paste'" in toggle_block


def test_modal_overlay_click_does_not_close():
    show_modal_block = ADMIN_JS.split('showModal(html) {', 1)[1].split('closeModal() {', 1)[0]
    assert 'overlay.onclick' not in show_modal_block
    assert 'modal-close' in show_modal_block


def test_model_table_supports_drag_reorder_and_persisting_order():
    models_panel = INDEX_HTML.split('<div id="tab-models" class="admin-panel">', 1)[1].split('<!-- Skills 管理 -->', 1)[0]
    assert '拖动排序' in models_panel

    load_models_block = ADMIN_JS.split('async loadModels() {', 1)[1].split('createModel() {', 1)[0]
    assert 'draggable="true"' in load_models_block
    assert 'data-role="drag-handle"' in load_models_block
    assert 'class="model-drag-handle" data-role="drag-handle" draggable="true"' in load_models_block
    assert 'model-drag-dots' in load_models_block
    assert 'model-drag-dot' in load_models_block
    assert 'this._bindModelDragAndDrop(tbody, models);' in load_models_block
    assert 'async _persistModelOrder(modelIds) {' in ADMIN_JS
    assert "typeof API.reorderAdminModels === 'function'" in ADMIN_JS
    assert "API.request('PUT', '/api/admin/models/order', { model_ids: modelIds })" in ADMIN_JS
    assert 'setDragImage(' in ADMIN_JS
    assert '_removeModelDragPreview()' in ADMIN_JS
    assert "const handle = row.querySelector('[data-role=\"drag-handle\"]');" in ADMIN_JS
    assert 'reorderAdminModels(modelIds)' in API_JS

    css = (ROOT / 'src/static/css/main.css').read_text(encoding='utf-8')
    assert '.model-drag-handle {' in css
    assert '.model-drag-dots {' in css
    assert '.model-drag-dot {' in css
    assert '.model-drag-preview {' in css


def test_model_drag_reorder_shows_drop_indicator_line():
    assert 'is-drop-target-before' in ADMIN_JS
    assert 'is-drop-target-after' in ADMIN_JS
    assert '_clearModelDropIndicators' in ADMIN_JS

    css = (ROOT / 'src/static/css/main.css').read_text(encoding='utf-8')
    assert '#model-table-body tr.is-drop-target-before td' in css
    assert '#model-table-body tr.is-drop-target-after td' in css


def test_admin_topbar_right_items_are_vertically_aligned():
    css = (ROOT / 'src/static/css/main.css').read_text(encoding='utf-8')
    assert '.topbar-right .topbar-link,' in css
    assert '.topbar-right .topbar-user {' in css
    assert 'display: inline-flex;' in css
    assert 'align-items: center;' in css
    assert '.topbar-user-wrap {' in css


def test_admin_has_governance_tab():
    assert 'data-tab="governance"' in INDEX_HTML
    assert 'id="tab-governance"' in INDEX_HTML
    assert 'id="governance-area"' in INDEX_HTML
    assert 'id="gov-refresh-btn"' in INDEX_HTML
    assert '治理与运营' in INDEX_HTML

    tab_map_block = ADMIN_JS.split("const tabMap = {", 1)[1].split("};", 1)[0]
    assert "governance: 'loadGovernance'" in tab_map_block
    assert "async loadGovernance()" in ADMIN_JS
    assert "getGovernanceCostTotal()" in ADMIN_JS
    assert "listGovernanceAgents('disabled')" in ADMIN_JS
    assert "gov-refresh-btn" in ADMIN_JS
    assert "Admin.loadGovernance()" in ADMIN_JS

    assert "getGovernanceCostDaily(" in API_JS
    assert "getGovernanceBudget(workspaceId)" in API_JS
    assert "listGovernanceAgents(status" in API_JS
    assert "archiveGovernanceAgent(agentId)" in API_JS
    assert "getGovernancePermissionsAudit()" in API_JS
