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
    assert '<meta name="theme-color" content="#005AAA">' in html, "theme-color meta tag not found"


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


# ─── JS-003: getBoundingClientRect in rAF ───

def test_js_003_align_sidebar_uses_request_animation_frame():
    js = _read(APP_JS)
    assert 'requestAnimationFrame' in js, "requestAnimationFrame not used in _alignSidebarToDivider"


def test_js_003_resize_handler_is_debounced():
    js = _read(APP_JS)
    assert '_resizeTimer' in js, "resize handler not debounced in app.js"
