"""P0.D.3 + P0.E.4 前端契约测试。

验收标准：
- P0.D.3: 资料库 Tab 存在、上传按钮存在、引用选择器存在、权限受限操作不显示
- P0.E.4: 一级导航存在"团队空间"；页面初始渲染不影响其他页面；普通 member 可访问资料库
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "src/static/css/main.css").read_text(encoding="utf-8")
WORKSPACE_JS = (ROOT / "src/static/js/workspace.js").read_text(encoding="utf-8")
REVIEW_JS = (ROOT / "src/static/js/review.js").read_text(encoding="utf-8")
API_JS = (ROOT / "src/static/js/api.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "src/static/js/app.js").read_text(encoding="utf-8")


# ── P0.D.3: 资料库 Tab 契约 ──


def test_workspace_sources_tab_exists():
    assert 'id="ws-tab-sources"' in HTML, "资料库 Tab panel 不存在"
    assert 'panel-title">资料库' in HTML, "资料库标题不存在"


def test_workspace_upload_button_exists():
    assert 'id="ws-upload-btn"' in HTML, "上传资料按钮不存在"


def test_workspace_source_detail_panel_exists():
    assert 'id="ws-source-detail"' in HTML, "资料详情面板不存在"


def test_workspace_source_list_exists():
    assert 'id="ws-sources-list"' in HTML, "资料列表容器不存在"


def test_source_picker_modal_exists():
    assert 'id="source-picker-overlay"' in HTML, "资料选择器模态框不存在"
    assert 'id="source-picker-list"' in HTML, "资料选择器列表不存在"
    assert 'id="source-picker-confirm"' in HTML, "资料选择器确认按钮不存在"
    assert 'id="source-picker-cancel"' in HTML, "资料选择器取消按钮不存在"


def test_source_picker_ref_in_review_context():
    assert 'id="add-source-ref-btn"' in HTML, "审查项目页引用资料按钮不存在"


def test_workspace_js_has_sources_methods():
    assert '_loadSources' in WORKSPACE_JS, "Workspace._loadSources 方法不存在"
    assert '_renderSourceTable' in WORKSPACE_JS, "Workspace._renderSourceTable 方法不存在"
    assert '_deleteSource' in WORKSPACE_JS, "Workspace._deleteSource 方法不存在"
    assert '_showSourceDetail' in WORKSPACE_JS, "Workspace._showSourceDetail 方法不存在"
    assert '_handleUpload' in WORKSPACE_JS, "Workspace._handleUpload 方法不存在"


def test_review_js_has_source_picker_methods():
    assert '_bindSourcePicker' in REVIEW_JS, "Review._bindSourcePicker 方法不存在"
    assert '_openSourcePicker' in REVIEW_JS, "Review._openSourcePicker 方法不存在"
    assert '_confirmSourcePicker' in REVIEW_JS, "Review._confirmSourcePicker 方法不存在"


def test_api_js_has_workspace_methods():
    assert 'getWorkspaces' in API_JS, "API.getWorkspaces 方法不存在"
    assert 'getWorkspaceSources' in API_JS, "API.getWorkspaceSources 方法不存在"
    assert 'deleteWorkspaceSource' in API_JS, "API.deleteWorkspaceSource 方法不存在"
    assert 'updateSourceTags' in API_JS, "API.updateSourceTags 方法不存在"
    assert 'downloadWorkspaceSource' in API_JS, "API.downloadWorkspaceSource 方法不存在"
    assert 'addProjectSourceRef' in API_JS, "API.addProjectSourceRef 方法不存在"
    assert 'listProjectSourceRefs' in API_JS, "API.listProjectSourceRefs 方法不存在"


def test_workspace_download_uses_authenticated_api():
    assert 'data-action="download-source"' in WORKSPACE_JS, "资料详情下载按钮应通过 JS 事件触发"
    assert 'API.downloadWorkspaceSource' in WORKSPACE_JS, "资料详情下载应使用带鉴权的 API 封装"
    assert 'href="/api/workspace/${this._workspaceId}/sources/${source.id}/download"' not in WORKSPACE_JS, (
        "资料详情不能使用裸链接下载，否则无法携带 Bearer 鉴权"
    )


def test_workspace_css_styles():
    assert '.workspace-sidebar' in CSS, "workspace-sidebar 样式不存在"
    assert '.workspace-nav-item' in CSS, "workspace-nav-item 样式不存在"
    assert '.workspace-content' in CSS, "workspace-content 样式不存在"
    assert '.workspace-panel' in CSS, "workspace-panel 样式不存在"
    assert '.ws-source-row' in CSS or '.ws-sources-table' in CSS, "资料行样式不存在"
    assert '.ws-status-chip' in CSS, "状态标签样式不存在"
    assert '.ws-source-detail' in CSS, "资料详情样式不存在"


# ── P0.E.4: 导航与页面契约 ──


def test_workspace_page_exists():
    assert 'id="workspace-page"' in HTML, "workspace-page 页面不存在"


def test_workspace_topbar_exists():
    assert 'id="workspace-user-display"' in HTML, "workspace 顶栏用户名不存在"
    assert 'id="workspace-logout-btn"' in HTML, "workspace 退出按钮不存在"


def test_workspace_navigation_links_exist():
    assert 'id="go-workspace"' in HTML or 'id="go-workspace"' in HTML, "从对话页到团队空间的导航不存在"
    assert 'id="go-workspace-from-review"' in HTML, "从审查页到团队空间的导航不存在"
    assert 'id="go-workspace-from-admin"' in HTML, "从管理后台到团队空间的导航不存在"
    assert 'id="go-chat-from-workspace"' in HTML, "从团队空间到对话页的导航不存在"
    assert 'id="go-review-from-workspace"' in HTML, "从团队空间到审查页的导航不存在"
    assert 'id="go-admin-from-workspace"' in HTML, "从团队空间到管理后台的导航不存在"


def test_workspace_navigation_in_app_js():
    assert '_showWorkspacePage' in APP_JS, "App._showWorkspacePage 方法不存在"
    assert "workspace: '_showWorkspacePage'" in APP_JS, "workspace 路由映射不存在"


def test_workspace_js_script_tag_exists():
    assert 'workspace.js' in HTML, "workspace.js script 标签不存在"


def test_workspace_tab_navigation():
    assert 'data-ws-tab="sources"' in HTML, "资料库 Tab 导航项不存在"
    assert 'data-ws-tab="members"' in HTML, "成员 Tab 导航项不存在"


# ── P1.A.3: 成员管理 UI 契约 ──


def test_api_js_has_member_management_methods():
    assert 'getDefaultWorkspace' in API_JS, "API.getDefaultWorkspace 方法不存在"
    assert 'getDefaultWorkspaceMembers' in API_JS, "API.getDefaultWorkspaceMembers 方法不存在"
    assert 'updateDefaultWorkspaceMember' in API_JS, "API.updateDefaultWorkspaceMember 方法不存在"
    assert 'updateDefaultWorkspace' in API_JS, "API.updateDefaultWorkspace 方法不存在"


def test_workspace_js_has_member_management_methods():
    assert '_renderMemberTable' in WORKSPACE_JS, "Workspace._renderMemberTable 方法不存在"
    assert '_changeMemberRole' in WORKSPACE_JS, "Workspace._changeMemberRole 方法不存在"
    assert '_toggleMemberStatus' in WORKSPACE_JS, "Workspace._toggleMemberStatus 方法不存在"
    assert '_confirmMemberAction' in WORKSPACE_JS, "Workspace._confirmMemberAction 方法不存在"
    assert '_canManage' in WORKSPACE_JS, "Workspace._canManage 属性不存在"


def test_workspace_js_member_actions_in_click_handler():
    assert 'deactivate-member' in WORKSPACE_JS, "停用成员点击事件委托不存在"
    assert 'reactivate-member' in WORKSPACE_JS, "恢复成员点击事件委托不存在"
    assert 'change-role' in WORKSPACE_JS, "角色变更 change 事件委托不存在"


def test_workspace_member_role_select_exists():
    assert 'ws-role-select' in WORKSPACE_JS, "角色选择下拉框类名不存在"


def test_workspace_member_css_styles():
    assert '.ws-members-table' in CSS, "成员表格样式不存在"
    assert '.ws-role-select' in CSS, "角色选择下拉框样式不存在"
    assert '.ws-status-active' in CSS, "活跃状态样式不存在"
    assert '.ws-status-inactive' in CSS, "停用状态样式不存在"


# ── BUG-037: review.py _verify_project_owner 对 legacy 项目做 workspace 校验 ──


def test_verify_project_owner_checks_workspace_for_legacy_projects():
    """BUG-037: review.py 中 _verify_project_owner 不再跳过 workspace_id=None 的项目"""
    REVIEW_PY = (ROOT / "src/app/routers/review.py").read_text(encoding="utf-8")
    # 确认不再有 `if project.workspace_id is not None` 条件跳过 workspace 校验
    # 新逻辑是：workspace_id=None 时回退到默认 workspace
    assert 'if workspace_id is None' in REVIEW_PY, \
        "_verify_project_owner 应处理 workspace_id=None 的 legacy 项目"
    assert 'default_ws = await ws_repo.get_default()' in REVIEW_PY, \
        "_verify_project_owner 应回退到默认 workspace"
    assert 'require_action' in REVIEW_PY, \
        "_verify_project_owner 应使用 require_action 统一校验"


def test_list_projects_filters_legacy_projects():
    """BUG-037: list_projects 对 legacy 项目也做可见性过滤"""
    REVIEW_PY = (ROOT / "src/app/routers/review.py").read_text(encoding="utf-8")
    assert 'legacy_visible' in REVIEW_PY, \
        "list_projects 应计算 legacy 项目可见性"
    assert 'p.workspace_id is None and not legacy_visible' in REVIEW_PY, \
        "list_projects 应过滤不可见的 legacy 项目"


# ── BUG-038: 停用成员在成员列表可见 ──


def test_default_members_api_uses_list_members_all():
    """BUG-038: GET /api/workspace/default/members 使用 list_members_all 返回含 inactive"""
    WORKSPACE_PY = (ROOT / "src/app/routers/workspace.py").read_text(encoding="utf-8")
    assert 'list_members_all' in WORKSPACE_PY, \
        "默认团队成员列表应使用 list_members_all（含 inactive）"
    # list_members 不再被默认团队成员列表使用
    lines = WORKSPACE_PY.split('\n')
    for i, line in enumerate(lines):
        if 'list_default_members' in line and 'async def' in line:
            # 在 list_default_members 函数体中不应有 list_members（不含 all）
            func_body_start = i + 1
            for j in range(func_body_start, min(func_body_start + 15, len(lines))):
                if 'await repo.list_members(' in lines[j] and 'list_members_all' not in lines[j]:
                    pytest.fail(f"list_default_members 不应使用 list_members (line {j}), 应使用 list_members_all")


def test_workspace_js_reactivate_member_branch_exists():
    """BUG-038: workspace.js 有恢复按钮渲染分支"""
    assert 'reactivate-member' in WORKSPACE_JS, "恢复按钮事件委托不存在"
    assert 'm.status === \'active\'' in WORKSPACE_JS, "状态条件分支不存在"
    assert '停用' in WORKSPACE_JS, "停用按钮不存在"
    assert '恢复' in WORKSPACE_JS, "恢复按钮不存在"


# ── BUG-039: PUT /api/workspace/default 支持 status 更新 ──


def test_workspace_put_default_handles_status():
    """BUG-039: workspace.py PUT /workspace/default 处理 status 字段"""
    WORKSPACE_PY = (ROOT / "src/app/routers/workspace.py").read_text(encoding="utf-8")
    assert 'new_status' in WORKSPACE_PY, \
        "PUT /workspace/default 应提取 status 字段"
    assert 'valid_statuses = ("active", "archived")' in WORKSPACE_PY, \
        "PUT /workspace/default 应校验 status 值范围"
    assert 'ws.status = new_status' in WORKSPACE_PY, \
        "PUT /workspace/default 应将 status 落库"


# ── BUG-040: 成员角色下拉包含 owner + 角色变更确认弹窗 ──


def test_workspace_js_role_dropdown_includes_owner():
    """BUG-040: workspace.js 角色下拉选项包含 owner"""
    assert "const roles = ['owner', 'admin', 'member', 'viewer']" in WORKSPACE_JS, \
        "角色下拉选项应包含 owner/admin/member/viewer"


def test_workspace_js_role_change_has_confirmation():
    """BUG-040: workspace.js 角色变更需确认弹窗"""
    assert '_confirmMemberAction' in WORKSPACE_JS, "角色变更确认方法不存在"
    assert '_confirmRoleChange' in WORKSPACE_JS, "owner 降级二次确认方法不存在"
    assert 'isDowngrade' in WORKSPACE_JS, "降级判断逻辑不存在"
    assert '确认降级角色' in WORKSPACE_JS, "降级确认弹窗标题不存在"
