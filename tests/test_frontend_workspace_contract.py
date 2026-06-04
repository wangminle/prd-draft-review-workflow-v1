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
