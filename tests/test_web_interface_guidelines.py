"""Automated tests for Web Interface Guidelines fixes (A11Y-001~006, CSS-001~007, JS-001~003).
Validates that the static files contain the required accessibility, CSS quality, and JS quality attributes."""

import re
import pathlib

STATIC = pathlib.Path(__file__).resolve().parent.parent / "src" / "static"
HTML = STATIC / "index.html"
CSS = STATIC / "css" / "main.css"
APP_JS = STATIC / "js" / "app.js"
ADMIN_JS = STATIC / "js" / "admin.js"


def _read(path):
    return path.read_text(encoding="utf-8")


# ─── A11Y-001: aria-label / label on input elements ───

def test_a11y_001_login_inputs_have_aria_label():
    html = _read(HTML)
    assert 'aria-label="用户名"' in html, "login-username missing aria-label"
    assert 'aria-label="密码"' in html, "login-password missing aria-label"


def test_a11y_001_register_inputs_have_aria_label():
    html = _read(HTML)
    # The register form inputs also have aria-labels
    assert html.count('aria-label="用户名"') >= 2, "register username missing aria-label"
    assert html.count('aria-label="密码"') >= 2, "register password missing aria-label"


def test_a11y_001_search_input_has_aria_label():
    html = _read(HTML)
    assert 'aria-label="搜索对话"' in html, "conv-search missing aria-label"


def test_a11y_001_select_elements_have_aria_label():
    html = _read(HTML)
    assert 'aria-label="选择模型"' in html
    assert 'aria-label="选择提示词"' in html
    assert 'aria-label="选择审查模型"' in html


def test_a11y_001_textareas_have_aria_label():
    html = _read(HTML)
    assert 'aria-label="输入消息"' in html
    assert 'aria-label="需求规范"' in html
    assert 'aria-label="团队指导意见"' in html


def test_a11y_001_file_inputs_have_aria_label():
    html = _read(HTML)
    assert 'aria-label="上传文件"' in html
    assert 'aria-label="上传历史文档"' in html
    assert 'aria-label="上传规则文档"' in html
    assert 'aria-label="上传临时资料"' in html


# ─── A11Y-002: aria-label on icon-only buttons ───

def test_a11y_002_sidebar_toggle_has_aria_label():
    html = _read(HTML)
    assert html.count('aria-label="收起侧栏"') >= 3, "sidebar toggle buttons missing aria-label"


def test_a11y_002_send_btn_has_aria_label():
    html = _read(HTML)
    assert 'aria-label="发送"' in html, "send-btn missing aria-label"


def test_a11y_002_context_drawer_btn_has_aria_label():
    html = _read(HTML)
    assert 'aria-label="上下文面板"' in html, "context-drawer-btn missing aria-label"


def test_a11y_002_drawer_close_has_aria_label():
    html = _read(HTML)
    assert 'aria-label="关闭上下文面板"' in html


def test_a11y_002_tool_btns_have_aria_label():
    html = _read(HTML)
    assert 'aria-label="上传文件"' in html
    assert 'aria-label="添加链接"' in html


# ─── A11Y-003: aria-live on error containers ───

def test_a11y_003_login_error_has_aria_live():
    html = _read(HTML)
    assert 'aria-live="polite"' in html, "login-error missing aria-live"
    assert html.count('aria-live="polite"') >= 2, "both login and register errors need aria-live"


# ─── A11Y-004: aria-hidden on decorative SVGs ───

def test_a11y_004_brand_dot_svgs_have_aria_hidden():
    html = _read(HTML)
    assert html.count('aria-hidden="true"') >= 8, "decorative SVGs missing aria-hidden"


def test_a11y_004_welcome_icon_svg_has_aria_hidden():
    html = _read(HTML)
    # welcome icon SVG should have aria-hidden
    welcome_pattern = r'<svg[^>]*width="48"[^>]*aria-hidden="true"'
    assert re.search(welcome_pattern, html), "welcome icon SVG missing aria-hidden"


# ─── A11Y-005: <a href="#"> changed to <button> ───

def test_a11y_005_no_href_hash_links():
    html = _read(HTML)
    assert 'href="#"' not in html, "residual <a href=\"#\"> found — should be <button>"


def test_a11y_005_topbar_links_are_buttons():
    html = _read(HTML)
    assert '<button id="go-review"' in html
    assert '<button id="logout-btn"' in html
    assert '<button id="back-to-chat-from-review"' in html
    assert '<button id="review-logout-btn"' in html
    assert '<button id="back-to-chat"' in html
    assert '<button id="admin-logout-btn"' in html


def test_a11y_005_auth_switch_are_buttons():
    html = _read(HTML)
    assert '<button id="show-register"' in html
    assert '<button id="show-login"' in html


def test_a11y_005_context_edit_is_button():
    html = _read(HTML)
    assert '<button class="context-edit"' in html


# ─── A11Y-006: beforeunload for auth forms ───

def test_a11y_006_beforeunload_in_app_js():
    js = _read(APP_JS)
    assert 'beforeunload' in js, "beforeunload handler not found in app.js"


# ─── CSS-001: no transition: all ───

def test_css_001_no_transition_all():
    css = _read(CSS)
    assert 'transition: all' not in css, "residual 'transition: all' found in CSS"


# ─── CSS-002: prefers-reduced-motion ───

def test_css_002_has_prefers_reduced_motion():
    css = _read(CSS)
    assert 'prefers-reduced-motion' in css, "prefers-reduced-motion media query not found"


# ─── CSS-003: tabular-nums ───

def test_css_003_stat_value_has_tabular_nums():
    css = _read(CSS)
    assert 'font-variant-numeric: tabular-nums' in css, "tabular-nums not found in CSS"


# ─── CSS-004: text-wrap: balance ───

def test_css_004_headings_have_text_wrap_balance():
    css = _read(CSS)
    assert 'text-wrap: balance' in css, "text-wrap: balance not found in CSS"


# ─── CSS-005: touch-action: manipulation ───

def test_css_005_btn_has_touch_action():
    css = _read(CSS)
    assert 'touch-action: manipulation' in css, "touch-action: manipulation not found in CSS"


# ─── CSS-006: overscroll-behavior: contain ───

def test_css_006_modal_has_overscroll_behavior():
    css = _read(CSS)
    assert 'overscroll-behavior: contain' in css, "overscroll-behavior: contain not found in CSS"


# ─── CSS-007: theme-color meta tag ───

def test_css_007_theme_color_meta():
    html = _read(HTML)
    assert 'name="theme-color"' in html and 'content="#005AAA"' in html, "theme-color meta tag not found"
    assert 'id="theme-color-meta"' in html, "theme-color meta must have id for branding override"


# ─── JS-001: Intl.DateTimeFormat ───

def test_js_001_intl_datetime_format():
    js = _read(ADMIN_JS)
    assert 'Intl.DateTimeFormat' in js, "Intl.DateTimeFormat not found in admin.js"


def test_js_001_no_slice_date_format():
    js = _read(ADMIN_JS)
    assert '.slice(0, 10)' not in js, "residual .slice(0,10) date format found"


# ─── JS-002: aria-live on toast ───

def test_js_002_toast_has_aria_live():
    js = _read(APP_JS)
    assert 'aria-live' in js, "aria-live not set on toast element in app.js"
    assert "'status'" in js, "role=status not set on toast element in app.js"


# ─── JS-003: sidebar width aligns to divider via JS ───

def test_js_003_sidebar_aligns_to_divider():
    """Sidebar width should dynamically align to the divider line via _alignSidebarToDivider."""
    js = _read(APP_JS)
    assert '_alignSidebarToDivider' in js, "_alignSidebarToDivider function must be present in app.js"
    assert "secondDivider" in js, "divider-based width calculation must be present"


def test_js_003_resize_handler_for_sidebar():
    """Resize handler should re-align sidebar widths when window is resized."""
    js = _read(APP_JS)
    assert '_resizeTimer' in js, "resize timer for sidebar alignment must be present"


# ─── 合入: 前端 API 契约 + JS 全局对象暴露 ──────────────────────────
# 原 test_frontend_api_contract.py / test_frontend_inline_handlers.py / test_app_frontend_contract.py

API_JS = STATIC / "js" / "api.js"
AUTH_JS = STATIC / "js" / "auth.js"
CHAT_JS = STATIC / "js" / "chat.js"
REVIEW_JS = STATIC / "js" / "review.js"


def test_api_request_error_message_includes_status_code():
    """API.request 方法应在错误消息中包含 HTTP status code"""
    js = _read(API_JS)
    request_block = js.split("async request(method, path, body)", 1)[1].split("/* 认证 */", 1)[0]
    assert "const err = await resp.json().catch(() => ({ detail: resp.statusText }));" in request_block
    assert "throw new Error(`${resp.status} ${err.detail || resp.statusText}`);" in request_block


def test_js_global_objects_exposed_for_inline_handlers():
    """各 JS 模块的全局对象应暴露到 window 上供 inline 事件处理器使用"""
    assert "window.Auth = Auth;" in _read(AUTH_JS)
    assert "window.Chat = Chat;" in _read(CHAT_JS)
    assert "window.Admin = Admin;" in _read(ADMIN_JS)
    assert "window.Review = Review;" in _read(REVIEW_JS)


def test_chat_page_has_distinct_page_badge():
    """对话页面应有独立页面徽标"""
    html = _read(HTML)
    css = _read(CSS)
    user_page_block = html.split('<div id="user-page" class="page">', 1)[1].split('<!-- ===== 审查工作台页 ===== -->', 1)[0]
    assert 'class="topbar-badge"' in user_page_block
    assert '智能对话' in user_page_block
    assert 'data-branding="topbar-title"' in user_page_block
    assert ".topbar-badge" in css


def test_all_topbars_use_same_product_title_and_show_version():
    """所有页面 topbar 应使用同一产品标题并显示版本号"""
    html = _read(HTML)
    css = _read(CSS)
    auth_js = _read(AUTH_JS)
    assert 'data-branding="review-title"' not in html
    assert html.count('data-branding="topbar-title"') == 4  # chat + review + workspace + admin
    assert html.count('data-branding="app-version"') == 4
    assert '.topbar-brand-text {' in css
    assert '.topbar-version {' in css
    assert "app-version" in auth_js
    assert "c.app_version" in auth_js


def test_html_head_includes_workspace_favicon():
    """HTML head 应包含工作区 favicon"""
    html = _read(HTML)
    assert 'id="favicon-link"' in html
    assert '/favicon.svg' in html
    favicon = STATIC / 'favicon.svg'
    assert favicon.exists()
    svg = favicon.read_text(encoding='utf-8')
    assert 'fill="#005AAA"' in svg
    assert 'M8 7h2v5h8V7h2v14h-2v-6H10v6H8V7z' in svg


def test_login_page_contains_deployment_notice_banner():
    """登录页面应包含部署提示通知栏"""
    html = _read(HTML)
    css = _read(CSS)
    login_block = html.split('<div id="login-form-block">', 1)[1].split('<h2 class="auth-card-title">欢迎回来</h2>', 1)[0]
    assert 'class="auth-login-notice"' in login_block
    assert '💡 <strong>部署提示：</strong>' in login_block
    assert '首次启动时系统自动创建管理员账号' in login_block
    assert '.env' in login_block
    assert '#login-form-block {' in css
    assert 'position: relative;' in css
    assert '.auth-login-notice {' in css
    assert 'position: absolute;' in css
    assert 'top: -240px;' in css
    assert 'border-radius: 12px;' in css
    assert 'border: 1px solid var(--blue-2);' in css
    assert 'background: linear-gradient(135deg, var(--blue-1) 0%, rgba(46, 124, 192, 0.18) 100%);' in css
    assert 'box-shadow:' in css


def test_login_notice_can_be_overridden_by_branding_config():
    """登录通知栏应支持品牌配置覆盖"""
    html = _read(HTML)
    auth_js = _read(AUTH_JS)
    login_block = html.split('<div id="login-form-block">', 1)[1].split('<h2 class="auth-card-title">欢迎回来</h2>', 1)[0]
    assert 'data-branding="login-notice"' in login_block
    assert "c.login_notice" in auth_js
    assert "renderLoginNotice" in auth_js
    assert "document.createElement('p')" in auth_js
    assert "textContent" in auth_js


def test_login_notice_has_low_height_responsive_fallback():
    """登录通知栏应有低高度响应式回退"""
    css = _read(CSS)
    assert '@media (max-height: 920px) {' in css
    assert '.auth-card {' in css
    assert 'padding-top: calc(140px - var(--auth-notice-lift));' in css
    assert '.auth-login-notice {' in css
    assert 'top: 24px;' in css
    assert 'left: 0;' in css
    assert 'right: 0;' in css
    assert 'max-height: calc(100vh - 48px);' in css


# ─── P4.D.5: 通知铃铛 + Inbox 前端契约 ──────────────────────────────

NOTIF_JS = STATIC / "js" / "notification.js"


def test_p4d5_notification_bell_in_all_topbars():
    """P4.D.5: 4个页面的 topbar 都应有通知铃铛"""
    html = _read(HTML)
    assert 'id="notif-bell-chat"' in html
    assert 'id="notif-bell-review"' in html
    assert 'id="notif-bell-workspace"' in html
    assert 'id="notif-bell-admin"' in html


def test_p4d5_notification_bell_has_aria_label():
    """P4.D.5: 通知铃铛按钮应有 aria-label"""
    html = _read(HTML)
    assert html.count('aria-label="通知"') >= 4, "4个通知铃铛按钮应都有 aria-label"


def test_p4d5_notification_badge_in_all_topbars():
    """P4.D.5: 4个页面的 topbar 都应有未读数 badge"""
    html = _read(HTML)
    assert 'id="notif-badge-chat"' in html
    assert 'id="notif-badge-review"' in html
    assert 'id="notif-badge-workspace"' in html
    assert 'id="notif-badge-admin"' in html


def test_p4d5_notification_dropdown_in_all_topbars():
    """P4.D.5: 4个页面的 topbar 都应有通知下拉面板"""
    html = _read(HTML)
    assert 'id="notif-dropdown-chat"' in html
    assert 'id="notif-dropdown-review"' in html
    assert 'id="notif-dropdown-workspace"' in html
    assert 'id="notif-dropdown-admin"' in html


def test_p4d5_notification_tabs_in_dropdown():
    """P4.D.5: 通知下拉面板应有未读/已读/归档三个 tab"""
    html = _read(HTML)
    assert html.count('data-notif-tab="unread"') >= 4
    assert html.count('data-notif-tab="read"') >= 4
    assert html.count('data-notif-tab="archived"') >= 4


def test_p4d5_notification_js_module_exists():
    """P4.D.5: notification.js 模块文件应存在"""
    assert NOTIF_JS.exists(), "notification.js should exist"


def test_p4d5_notification_js_global_object():
    """P4.D.5: notification.js 应暴露 Notification 全局对象"""
    js = _read(NOTIF_JS)
    assert 'window.Notification = Notification;' in js


def test_p4d5_notification_js_sse_connect():
    """P4.D.5: notification.js 应有 SSE 连接逻辑"""
    js = _read(NOTIF_JS)
    assert 'EventSource' in js
    assert 'sse-ticket' in js
    assert '/api/notifications/stream' in js


def test_p4d5_notification_js_api_methods():
    """P4.D.5: notification.js 应调用 API 通知方法"""
    js = _read(NOTIF_JS)
    assert 'getUnreadNotificationCount' in js
    assert 'listNotifications' in js
    assert 'markNotificationRead' in js
    assert 'batchMarkNotificationsRead' in js
    assert 'archiveNotification' in js


def test_p4d5_notification_css_bell_styles():
    """P4.D.5: CSS 应包含通知铃铛样式"""
    css = _read(CSS)
    assert '.notification-bell-wrap' in css
    assert '.notification-bell-btn' in css
    assert '.notification-badge' in css
    assert '.notification-dropdown' in css
    assert '.notification-dropdown-head' in css
    assert '.notification-dropdown-tabs' in css
    assert '.notification-tab' in css
    assert '.notification-item' in css
    assert '.notification-item.unread' in css


def test_p4d5_notification_js_loaded_in_html():
    """P4.D.5: HTML 应加载 notification.js"""
    html = _read(HTML)
    assert 'notification.js' in html


def test_p4d5_app_js_initializes_notification():
    """P4.D.5: app.js 应在登录后初始化通知模块"""
    js = _read(APP_JS)
    assert 'Notification.init()' in js


# ─── P4.D.6: 评论组件前端契约 ──────────────────────────────────────


def test_p4d6_comment_section_in_html():
    """P4.D.6: 审查页应有评论组件 HTML"""
    html = _read(HTML)
    assert 'id="review-comment-section"' in html
    assert 'id="comment-input"' in html
    assert 'id="comment-submit-btn"' in html
    assert 'id="comment-list"' in html
    assert 'id="comment-count"' in html


def test_p4d6_comment_input_has_aria_label():
    """P4.D.6: 评论输入框应有 aria-label"""
    html = _read(HTML)
    assert 'aria-label="输入评论"' in html


def test_p4d6_comment_css_styles():
    """P4.D.6: CSS 应包含评论组件样式"""
    css = _read(CSS)
    assert '.review-comment-section' in css
    assert '.comment-input' in css
    assert '.comment-list' in css
    assert '.comment-item' in css
    assert '.comment-item.reply' in css
    assert '.comment-item-head' in css
    assert '.comment-item-body' in css
    assert '.mention-tag' in css


def test_p4d6_review_js_comment_methods():
    """P4.D.6: review.js 应有评论管理方法"""
    js = _read(REVIEW_JS)
    assert '_loadComments' in js
    assert '_renderComments' in js
    assert '_submitComment' in js
    assert '_replyToComment' in js


def test_p4d6_api_js_comment_methods():
    """P4.D.6: api.js 应有评论 API 方法"""
    js = _read(API_JS)
    assert 'createComment' in js
    assert 'listComments' in js
    assert 'deleteComment' in js
    assert '/api/notifications/comments' in js


# ─── P4.B.5: 讲解准备前端契约 ──────────────────────────────────────


def test_p4b5_presentation_entry_in_html():
    """P4.B.5: 审查结果区应有讲解准备入口"""
    html = _read(HTML)
    assert 'id="review-presentation-entry"' in html
    assert 'id="prepare-presentation-btn"' in html


def test_p4b5_presentation_css_styles():
    """P4.B.5: CSS 应包含讲解准备入口样式"""
    css = _read(CSS)
    assert '.review-presentation-entry' in css
    assert '.presentation-entry-icon' in css
    assert '.presentation-entry-title' in css
    assert '.presentation-entry-desc' in css


def test_p4b5_review_js_presentation_method():
    """P4.B.5: review.js 应有讲解准备启动方法"""
    js = _read(REVIEW_JS)
    assert '_startPresentation' in js


def test_p4b5_chat_js_presentation_mode():
    """P4.B.5: chat.js 应支持 presentation 模式对话创建"""
    js = _read(CHAT_JS)
    assert 'createConversationWithMode' in js
    assert '_presentationMode' in js


# ─── P4.B.2: 产物卡片前端契约 ──────────────────────────────────────


def test_p4b2_artifact_section_in_html():
    """P4.B.2: 审查结果区应有产物卡片区域"""
    html = _read(HTML)
    assert 'id="review-artifact-section"' in html
    assert 'id="review-artifact-list"' in html
    assert 'id="create-artifact-btn"' in html


def test_p4b2_artifact_css_styles():
    """P4.B.2: CSS 应包含产物卡片样式"""
    css = _read(CSS)
    assert '.review-artifact-section' in css
    assert '.artifact-card' in css
    assert '.artifact-card-icon' in css
    assert '.artifact-card-status.draft' in css
    assert '.artifact-card-status.confirmed' in css


def test_p4b2_review_js_artifact_methods():
    """P4.B.2: review.js 应有产物管理方法"""
    js = _read(REVIEW_JS)
    assert '_loadArtifacts' in js
    assert '_renderArtifactCards' in js
    assert '_showCreateArtifactDialog' in js


def test_p4b2_api_js_artifact_methods():
    """P4.B.2: api.js 应有产物 API 方法"""
    js = _read(API_JS)
    assert 'createArtifact' in js
    assert 'listArtifacts' in js
    assert 'confirmArtifact' in js
    assert 'unconfirmArtifact' in js


# ─── P4.A.4: 协作审查前端契约 ──────────────────────────────────────


def test_p4a4_collab_section_in_html():
    """P4.A.4: 审查结果区应有协作审查面板"""
    html = _read(HTML)
    assert 'id="review-collab-section"' in html
    assert 'id="initiate-collab-btn"' in html
    assert 'id="review-collab-list"' in html


def test_p4a4_collab_css_styles():
    """P4.A.4: CSS 应包含协作审查样式"""
    css = _read(CSS)
    assert '.review-collab-section' in css
    assert '.collab-request-card' in css
    assert '.collab-request-status.pending_approval' in css
    assert '.collab-request-status.approved' in css
    assert '.collab-request-status.rejected' in css


def test_p4a4_review_js_collab_methods():
    """P4.A.4: review.js 应有协作审查方法"""
    js = _read(REVIEW_JS)
    assert '_loadCollabRequests' in js
    assert '_renderCollabCards' in js
    assert '_showInitiateCollabDialog' in js
    assert '_createCollabSubmit' in js
    assert '_showCollabDetail' in js


def test_p4a4_api_js_review_request_methods():
    """P4.A.4: api.js 应有协作审查 API 方法"""
    js = _read(API_JS)
    assert 'createReviewRequest' in js
    assert 'listReviewRequests' in js
    assert 'resubmitReviewRequest' in js
    assert 'decideReviewRound' in js
