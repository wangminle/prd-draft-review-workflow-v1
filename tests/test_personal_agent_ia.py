"""个人 Agent 信息架构：系统级配置 vs 我的配置。

验收：
- 聊天/评审/团队空间/管理后台右上角同一账号菜单
- 个人 Agent 对所有登录用户开放（含授权管理），不放在管理后台侧栏
- 默认访问范围文案为「我的资料 / 已授权的团队资料」，无授权时禁用并提示
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "src/static/js/app.js").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "src/static/js/admin.js").read_text(encoding="utf-8")
NOTIF_JS = (ROOT / "src/static/js/notification.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/static/css/main.css").read_text(encoding="utf-8")
USER_GUIDE = (ROOT / "docs/user-guide.md").read_text(encoding="utf-8")
ADMIN_GUIDE = (ROOT / "docs/admin-guide.md").read_text(encoding="utf-8")
MENU_BROWSER_TOOL = ROOT / "tools/verify_account_menu_browser.py"

PAGES = ("chat", "review", "workspace", "admin")
TRIGGERS = (
    "user-display",
    "review-user-display",
    "workspace-user-display",
    "admin-user-display",
)
DROPDOWNS = (
    "user-menu-dropdown",
    "review-user-menu-dropdown",
    "workspace-user-menu-dropdown",
    "admin-user-menu-dropdown",
)


def _admin_nav() -> str:
    return HTML.split('<nav class="admin-nav">', 1)[1].split("</nav>", 1)[0]


def test_four_pages_share_identical_account_menu():
    for trigger, dropdown, source in zip(TRIGGERS, DROPDOWNS, PAGES):
        assert f'id="{trigger}"' in HTML
        assert f'id="{dropdown}"' in HTML
        block = HTML.split(f'id="{dropdown}"', 1)[1].split("</div>", 1)[0]
        assert 'data-user-menu-action="agent-settings"' in block
        assert ">个人 Agent<" in block
        assert 'data-user-menu-action="change-password"' in block
        assert ">修改密码<" in block
        assert 'data-user-menu-action="logout"' in block
        assert f'data-logout-source="{source}"' in block
        assert ">退出登录<" in block


def test_account_menu_triggers_are_buttons_with_menu_semantics():
    for trigger in TRIGGERS:
        assert f'<button type="button" class="topbar-user" id="{trigger}"' in HTML
        assert "aria-haspopup=" in HTML.split(f'id="{trigger}"', 1)[0][-80:] + HTML.split(
            f'id="{trigger}"', 1
        )[1][:200]


def test_admin_sidebar_has_no_personal_agent_entry():
    nav = _admin_nav()
    assert "Agent · 个人" not in nav
    assert 'data-tab="agent"' not in nav
    assert "我的 Agent" not in nav
    assert "Pi Agent 配置" in nav
    assert 'data-tab="pi-agent"' in nav
    assert 'id="tab-agent"' not in HTML
    assert 'id="tab-pi-agent"' in HTML


def test_admin_nav_keeps_three_system_groups_only():
    nav = _admin_nav()
    groups = ["运营概览", "团队与内容", "AI 能力 · 全局"]
    positions = [nav.find(f">{label}</div>") for label in groups]
    assert all(pos >= 0 for pos in positions)
    assert positions == sorted(positions)
    assert nav.count('class="admin-nav-group"') == 3


def test_personal_agent_modal_owns_scope_and_authorizations():
    modal = APP_JS.split("async _showAgentSettingsModal", 1)[1].split(
        "_resetSessionState", 1
    )[0]
    assert "仅影响当前账号" in modal
    assert "我的资料" in modal
    assert "已授权的团队资料" in modal
    assert "当前已授权团队空间" in modal
    assert "暂无授权" in modal
    assert "请先在「我的 Agent」页面" not in modal
    assert "createAgentAuthorization" in modal
    assert "revokeAgentAuthorization" in modal
    assert "default_scope_type" in modal
    assert "listPendingApprovals" in modal


def test_personal_agent_entry_is_shared_not_admin_tab():
    assert "_bindUserMenu('workspace-user-display'" in APP_JS
    assert "this._showAgentSettingsModal()" in APP_JS
    assert "agent: 'loadAgentSettings'" not in ADMIN_JS
    assert "localStorage.setItem('admin-active-tab', 'agent')" not in ADMIN_JS


def test_agent_approval_notification_opens_personal_agent_modal():
    jump = NOTIF_JS.split("objectType === 'agent_approval'", 1)[1].split(
        "} else if", 1
    )[0]
    assert "App._showAgentSettingsModal" in jump
    assert "Admin._showAgentApprovals" not in jump
    assert "App._showAdminPage" not in jump


def test_personal_agent_modal_has_wide_layout_rule():
    assert ".modal-box.agent-settings-modal" in CSS


def test_user_guide_documents_account_menu_personal_agent():
    assert "个人 Agent" in USER_GUIDE
    assert "已授权的团队资料" in USER_GUIDE
    assert "右上角" in USER_GUIDE


def test_admin_guide_separates_system_agent_from_personal_agent():
    assert "Pi Agent" in ADMIN_GUIDE
    assert "个人 Agent" in ADMIN_GUIDE
    assert "已授权的团队资料" in ADMIN_GUIDE
    assert "仅影响当前账号" in ADMIN_GUIDE


# ── 真实浏览器端到端验证（Playwright/Chromium 可用时执行，独立子进程避免事件循环冲突） ──


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _chromium_binary_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.mark.skipif(not MENU_BROWSER_TOOL.exists(), reason="browser verify tool missing")
@pytest.mark.skipif(not _playwright_available(), reason="Playwright not installed")
def test_browser_account_menu_end_to_end():
    """真实浏览器：四页账号菜单及个人 Agent 配置防误覆盖回归。"""
    if not _chromium_binary_available():
        pytest.skip("Playwright Chromium binary not installed")

    proc = subprocess.run(
        [sys.executable, str(MENU_BROWSER_TOOL), "--json"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"browser verification failed:\n{proc.stdout}\n{proc.stderr}"
    report = json.loads(proc.stdout)
    assert report["ok"] is True, f"浏览器验证未全部通过: {report['checks']}"
    assert report["passed"] == 7, f"应覆盖四页菜单和三个配置回归场景: {report}"
