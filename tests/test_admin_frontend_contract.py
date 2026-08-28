import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "src/static/js/app.js").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "src/static/js/auth.js").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "src/static/js/admin.js").read_text(encoding="utf-8")
API_JS = (ROOT / "src/static/js/api.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
CSS_MAIN = (ROOT / "src/static/css/main.css").read_text(encoding="utf-8")


def _extract_css_block(css: str, marker: str) -> str:
    """截取 marker 起始处的完整花括号配对块（含嵌套规则）。"""
    start = css.find(marker)
    assert start >= 0, f"CSS 缺少 {marker}"
    depth = 0
    for i in range(start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start:i + 1]
    return css[start:]


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


def test_admin_nav_groups_tab_items_by_scope():
    """管理后台侧栏只保留系统级分组：运营概览 / 团队与内容 / AI 能力·全局。

    个人 Agent 从侧栏移除，改由全页统一账号菜单进入。
    """
    nav_block = INDEX_HTML.split('<nav class="admin-nav">', 1)[1].split('</nav>', 1)[0]

    groups = ["运营概览", "团队与内容", "AI 能力 · 全局"]
    positions = [nav_block.find(f">{label}</div>") for label in groups]
    assert all(pos >= 0 for pos in positions), "三个系统级分组头必须齐备"
    assert positions == sorted(positions), "分组头按既定顺序排列"
    assert "Agent · 个人" not in nav_block
    assert 'data-tab="agent"' not in nav_block

    # 每个分组头是纯视觉 div，不是可点击 tab（不带 data-tab，避免被点击委托捕获）；
    # 不得用 aria-hidden 隐藏分组语义（BUG-178：读屏用户需要听到分组区分）
    assert '<div class="admin-nav-group">' in nav_block
    assert 'admin-nav-group" aria-hidden' not in nav_block

    # 窄屏规则 `.admin-nav-item span { display: none }` 依赖标签文字包在 <span> 里，
    # 否则 ≤1100px 图标栏下文字不会被隐藏（BUG-179）
    nav_labels = ["系统统计", "治理与运营", "用户管理", "预置对话Prompt", "评审风格Prompt",
                  "模型配置", "Skills 管理", "Pi Agent 配置"]
    for label in nav_labels:
        assert f"<span>{label}</span>" in nav_block, f"导航标签未包 <span>: {label}"

    # 分组归属：组头必须紧邻其组内第一个 tab 之前
    group_first_tabs = {
        "运营概览": 'data-tab="stats"',
        "团队与内容": 'data-tab="users"',
        "AI 能力 · 全局": 'data-tab="models"',
    }
    for label, tab_key in group_first_tabs.items():
        group_pos = nav_block.find(f">{label}</div>")
        tab_pos = nav_block.find(tab_key)
        assert group_pos < tab_pos, f"分组头「{label}」应位于 {tab_key} 之前"

    # 系统级引擎配置留在「AI 能力 · 全局」；个人 Agent 不在侧栏
    assert nav_block.find("AI 能力 · 全局") < nav_block.find('data-tab="pi-agent"')

    # 收起态与窄屏态：分组标题退化为细分隔线，规则齐备
    assert ".admin-sidebar.collapsed .admin-nav-group" in CSS_MAIN
    media_block = _extract_css_block(CSS_MAIN, "@media (max-width: 1100px)")
    assert ".admin-nav-group" in media_block


def test_admin_nav_groups_do_not_interfere_with_tab_logic():
    """分组头不得引入可点击行为，tab 切换仍走 .admin-nav-item 委托。"""
    nav_block = INDEX_HTML.split('<nav class="admin-nav">', 1)[1].split('</nav>', 1)[0]

    # 分组头不带 data-tab / button，天然被 closest('.admin-nav-item') 忽略
    assert "admin-nav-group\" data-tab" not in nav_block
    assert "<button" not in nav_block.split('class="admin-nav-group"', 1)[1].split("</div>", 1)[0]

    # admin.js 的 tab 逻辑保持原样：委托选择器 + localStorage 记忆
    click_block = ADMIN_JS.split("document.addEventListener('click'", 1)[1]
    assert "closest('.admin-nav-item')" in click_block
    assert "localStorage.setItem('admin-active-tab'" in ADMIN_JS


def test_admin_nav_scrolls_in_short_viewports():
    """分组标题抬高了导航总高：矮视口下导航必须内部滚动，不得被 .app-layout 的 overflow:hidden 裁剪。"""
    block = _extract_css_block(CSS_MAIN, ".admin-nav {")
    assert "overflow-y: auto" in block, "导航需纵向滚动"
    assert "min-height: 0" in block, "flex 子项需 min-height:0 才能收缩出滚动空间"
    assert "flex: 1 1 auto" in block, "导航占据剩余高度，底部折叠按钮保持固定"


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


def test_model_config_fields_avoid_login_password_manager():
    """模型配置表单不触发浏览器登录密码管理弹框。

    浏览器将「LLM 模型名」文本框 + API Key 密码框启发式识别为登录表单，
    弹出保存用户名/密码提示。修复：API Key 密码框使用 autocomplete="new-password"，
    模型名等文本框加专用 name 标识 + autocomplete="off" 打破用户名识别。
    """
    # 新建/编辑模型弹窗：API Key 密码框声明 new-password（对密码框 off 无效）
    assert 'id="modal-new-api-key" name="model-config-api-key"' in ADMIN_JS
    assert 'id="modal-new-api-key" name="model-config-api-key" placeholder="输入该模型的 API Key" autocomplete="new-password"' in ADMIN_JS
    assert 'id="modal-api-key" name="model-config-api-key"' in ADMIN_JS
    assert 'id="modal-api-key" name="model-config-api-key" placeholder="输入新的 API Key（留空不修改）" autocomplete="new-password"' in ADMIN_JS

    # LLM 模型名/模型 ID/显示名称/API Base 文本框：专用 name + autocomplete="off"
    for needle in (
        'id="modal-new-model-id" name="model-config-id" autocomplete="off"',
        'id="modal-new-model-name" name="model-config-display-name" autocomplete="off"',
        'id="modal-new-api-base" name="model-config-api-base" autocomplete="off"',
        'id="modal-new-llm-model" name="model-config-llm-model" autocomplete="off"',
        'id="modal-model-name" name="model-config-display-name" autocomplete="off"',
        'id="modal-api-base" name="model-config-api-base" autocomplete="off"',
        'id="modal-llm-model" name="model-config-llm-model" autocomplete="off"',
    ):
        assert needle in ADMIN_JS, f"缺少专用标识的模型配置输入框: {needle}"


def test_pi_agent_and_user_passwords_use_new_password():
    """Pi Agent API Key 与用户管理密码框同样避免登录密码管理器误判。"""
    for needle in (
        'id="pi-llm-api-key" name="pi-llm-api-key"',
        'id="pi-search-api-key" name="pi-search-api-key"',
        'id="pi-vision-api-key" name="pi-vision-api-key"',
        'id="modal-password" name="user-reset-password"',
        'id="modal-new-password" name="user-initial-password"',
        'id="pi-llm-model" name="pi-llm-model-name" autocomplete="off"',
        'id="pi-vision-model" name="pi-vision-model-name" autocomplete="off"',
    ):
        assert needle in ADMIN_JS, f"缺少专用标识: {needle}"

    # admin.js 中不应残留 autocomplete="off" 的密码框（对密码字段无效，须用 new-password）
    import re
    bare = re.findall(r'type="password"[^>]*autocomplete="off"', ADMIN_JS)
    assert not bare, f"admin.js 密码框仍使用无效的 autocomplete=off: {bare}"


def test_login_form_keeps_standard_password_manager_semantics():
    """登录页保持标准 username/current-password 语义，浏览器密码管理器正常工作。"""
    assert 'id="login-username"' in INDEX_HTML
    assert 'autocomplete="username"' in INDEX_HTML
    assert 'id="login-password"' in INDEX_HTML
    assert 'autocomplete="current-password"' in INDEX_HTML
    # 登录表单不得使用 new-password（会禁用已保存密码的自动填充）
    login_form_block = INDEX_HTML.split('id="login-form"', 1)[1].split("</form>", 1)[0]
    assert 'autocomplete="new-password"' not in login_form_block


# ── 真实浏览器验证（Playwright/Chromium 可用时执行，独立子进程避免事件循环冲突） ──

NAV_BROWSER_TOOL = ROOT / "tools/verify_admin_nav_groups_browser.py"


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _chromium_binary_available() -> bool:
    """仅装了 playwright 包但没下载 Chromium 二进制时，浏览器用例应 skip 而非失败（BUG-180）。"""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.mark.skipif(not NAV_BROWSER_TOOL.exists(), reason="browser verify tool missing")
@pytest.mark.skipif(not _playwright_available(), reason="Playwright not installed")
def test_browser_admin_nav_groups_end_to_end():
    """管理侧栏分组：展开态分组归属、点击委托不受分组头影响、收起/窄屏分隔线。"""
    import subprocess
    import sys

    if not _chromium_binary_available():
        pytest.skip("Playwright Chromium binary not installed")

    proc = subprocess.run(
        [sys.executable, str(NAV_BROWSER_TOOL), "--json"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"browser verification failed:\n{proc.stdout}\n{proc.stderr}"
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["ok"] is True, f"浏览器验证未全部通过: {report['checks']}"
    assert report["passed"] >= 14, f"检查项数量异常: {report['passed']}"
