from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "src/static/css/main.css").read_text(encoding="utf-8")


def test_chat_page_has_distinct_page_badge():
    user_page_block = HTML.split('<div id="user-page" class="page">', 1)[1].split('<!-- ===== 审查工作台页 ===== -->', 1)[0]
    assert '<span class="topbar-badge" style="background:var(--blue-6)">智能对话</span>' in user_page_block
    assert '<span class="topbar-title">AI产品需求初审</span>' in user_page_block
    assert ".topbar-badge" in CSS


def test_html_head_includes_workspace_favicon():
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' in HTML
    favicon = ROOT / 'src/static/favicon.svg'
    assert favicon.exists()
    svg = favicon.read_text(encoding='utf-8')
    assert 'fill="#005AAA"' in svg
    assert 'M8 7h2v5h8V7h2v14h-2v-6H10v6H8V7z' in svg


def test_login_page_contains_deployment_notice_banner():
    login_block = HTML.split('<div id="login-form-block">', 1)[1].split('<h2 class="auth-card-title">欢迎回来</h2>', 1)[0]
    assert 'class="auth-login-notice"' in login_block
    assert '💡 <strong>部署提示：</strong>' in login_block
    assert '首次启动时系统自动创建管理员账号' in login_block
    assert '.env' in login_block
    assert '#login-form-block {' in CSS
    assert 'position: relative;' in CSS
    assert '.auth-login-notice {' in CSS
    assert 'position: absolute;' in CSS
    assert 'top: -240px;' in CSS
    assert 'border-radius: 12px;' in CSS
    assert 'border: 1px solid var(--blue-2);' in CSS
    assert 'background: linear-gradient(135deg, var(--blue-1) 0%, rgba(46, 124, 192, 0.18) 100%);' in CSS
    assert 'box-shadow:' in CSS


def test_login_notice_has_low_height_responsive_fallback():
    assert '@media (max-height: 920px) {' in CSS
    assert '.auth-card {' in CSS
    assert 'padding-top: calc(140px - var(--auth-notice-lift));' in CSS
    assert '.auth-login-notice {' in CSS
    assert 'top: 24px;' in CSS
    assert 'left: 0;' in CSS
    assert 'right: 0;' in CSS
    assert 'max-height: calc(100vh - 48px);' in CSS
