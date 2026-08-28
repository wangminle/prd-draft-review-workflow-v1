#!/usr/bin/env python3
"""统一账号菜单真实浏览器验证工具（Playwright/Chromium）。

验证四个页面（聊天/评审/团队空间/管理后台）右上角为同一个账号菜单：
个人 Agent / 修改密码 / 退出登录，菜单项为 button、下拉可开合。

用法：
    python3 tools/verify_account_menu_browser.py            # 人读输出
    python3 tools/verify_account_menu_browser.py --json     # JSON 输出（供 pytest 断言）

环境依赖：pip install playwright && playwright install chromium
"""

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src/static/index.html"
STATIC = ROOT / "src/static"

# 各页面用户菜单触发器/下拉与 index.html 保持同步（页面容器只用于强制显示）
PAGES = [
    ("chat", "#user-page", "#user-display", "#user-menu-dropdown"),
    ("review", "#review-page", "#review-user-display", "#review-user-menu-dropdown"),
    ("workspace", "#workspace-page", "#workspace-user-display", "#workspace-user-menu-dropdown"),
    ("admin", "#admin-page", "#admin-user-display", "#admin-user-menu-dropdown"),
]

EXPECTED_ITEMS = ["个人 Agent", "修改密码", "退出登录"]


def build_harness() -> str:
    """file:// 直读真实 index.html；重写相对资源路径并给目标页加 .active 做纯 DOM 验证。"""
    html = INDEX.read_text(encoding="utf-8")
    # 资源是 ./ 相对路径，harness 在临时目录中需重写为绝对 file:// URL 才能加载真实 JS/CSS
    static_prefix = STATIC.as_uri() + "/"
    for attr in ("src", "href"):
        html = re.sub(
            rf'{attr}="\./([^"]+)"',
            rf'{attr}="{static_prefix}\1"',
            html,
        )
    # 同步加载脚本（默认 defer 在 file:// 下时序可控性差），登录门禁仅影响 display，不影响菜单 DOM
    html = html.replace(" defer", "")
    init = """
<script>
(function () {
  window.addEventListener('DOMContentLoaded', function () {
    // .page 默认 display:none，加 .active 即显示；登录门禁只影响 JS 初始跳转，不影响菜单 DOM
    var target = document.getElementById('user-page');
    if (target) { target.classList.add('active'); }
  });
})();
</script>
"""
    return html.replace("</head>", init + "</head>")


def run_checks(page) -> list:
    checks = []
    for name, page_sel, trigger_sel, dd_sel in PAGES:
        page.eval_on_selector(page_sel, "el => { el.classList.add('active'); }")
        page.wait_for_timeout(50)

        trigger = page.locator(trigger_sel)
        dd = page.locator(dd_sel)
        if trigger.count() == 0 or dd.count() == 0:
            checks.append({"page": name, "ok": False,
                           "error": f"触发器 {trigger_sel} 或下拉 {dd_sel} 不存在"})
            continue

        tag = page.eval_on_selector(trigger_sel, "el => el.tagName.toLowerCase()")
        if tag != "button":
            checks.append({"page": name, "ok": False, "error": f"触发器为 <{tag}> 而非 <button>"})
            continue

        items = page.eval_on_selector_all(
            f"{dd_sel} .user-menu-item", "els => els.map(e => e.textContent.trim())"
        )
        if items != EXPECTED_ITEMS:
            checks.append({"page": name, "ok": False,
                           "error": f"菜单项 {items} != {EXPECTED_ITEMS}"})
            continue

        hidden_before = dd.is_hidden()
        trigger.click()
        page.wait_for_timeout(100)
        opened = dd.is_visible()
        trigger.click()
        page.wait_for_timeout(100)
        closed = dd.is_hidden()
        if not (hidden_before and opened and closed):
            checks.append({"page": name, "ok": False,
                           "error": f"下拉开合异常 hidden_before={hidden_before} opened={opened} closed={closed}"})
            continue

        checks.append({"page": name, "ok": True, "detail": "触发器 button、3 项菜单、开合正常"})

        page.eval_on_selector(page_sel, "el => { el.classList.remove('active'); }")
    return checks


def run_agent_settings_regressions(page) -> list:
    """验证个人 Agent 弹窗不会因部分加载失败或隐藏字段而误覆盖配置。"""
    checks = []

    def install_stubs(profile: dict, auth_fails: bool = False):
        page.evaluate(
            """({profile, authFails}) => {
                window.__agentSavedPayload = null;
                API.getAgentProfile = async () => profile;
                API.listAgentAuthorizations = async () => {
                    if (authFails) throw new Error('authorization unavailable');
                    return [];
                };
                API.listAgentRuns = async () => [];
                API.listPendingApprovals = async () => [];
                API.getWorkspaces = async () => [];
                API.updateAgentProfile = async (payload) => {
                    window.__agentSavedPayload = payload;
                    return payload;
                };
            }""",
            {"profile": profile, "authFails": auth_fails},
        )

    install_stubs(
        {
            "name": "Workspace Agent",
            "status": "active",
            "default_scope_type": "workspace",
            "allowed_tools": ["rag_search"],
            "system_policy": "policy",
        },
        auth_fails=True,
    )
    page.evaluate("App._showAgentSettingsModal()")
    page.wait_for_timeout(100)
    save_count = page.locator("#agent-settings-save").count()
    error_text = page.locator("#modal-content").inner_text()
    checks.append({
        "page": "agent-settings-critical-load",
        "ok": save_count == 0 and "加载" in error_text and "失败" in error_text,
        "detail": f"save_count={save_count}, text={error_text[:80]!r}",
    })
    fail_close = page.locator("#agent-settings-fail-close")
    if fail_close.count():
        fail_close.click()
    else:
        page.evaluate("document.getElementById('modal-overlay').style.display='none'")

    install_stubs(
        {
            "name": "Tool Agent",
            "status": "active",
            "default_scope_type": "personal",
            "allowed_tools": ["search", "rag_search", "custom_plugin"],
            "system_policy": "policy",
        }
    )
    page.evaluate("App._showAgentSettingsModal()")
    page.wait_for_selector("#agent-settings-save")
    rag_checkbox = page.locator("#agent-tool-rag_search")
    rag_checked = rag_checkbox.is_checked()
    rag_checkbox.uncheck()
    page.locator("#agent-settings-save").click()
    page.wait_for_function("window.__agentSavedPayload !== null")
    saved_tools = page.evaluate("window.__agentSavedPayload.allowed_tools")
    checks.append({
        "page": "agent-settings-preserve-tools",
        "ok": rag_checked and saved_tools == ["custom_plugin", "search"],
        "detail": f"rag_checked={rag_checked}, saved_tools={saved_tools!r}",
    })

    install_stubs(
        {
            "name": "Policy Agent",
            "status": "active",
            "default_scope_type": "personal",
            "allowed_tools": ["rag_search"],
            "system_policy": "需要清空",
        }
    )
    page.evaluate("App._showAgentSettingsModal()")
    page.wait_for_selector("#agent-settings-save")
    page.locator("#agent-system-policy").fill("")
    page.locator("#agent-settings-save").click()
    page.wait_for_function("window.__agentSavedPayload !== null")
    saved_policy = page.evaluate("window.__agentSavedPayload.system_policy")
    checks.append({
        "page": "agent-settings-clear-policy",
        "ok": saved_policy == "",
        "detail": f"saved_policy={saved_policy!r}",
    })

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON 输出（供 pytest 断言）")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright 未安装", file=sys.stderr)
        return 0

    checks = []
    errors = []
    with tempfile.TemporaryDirectory() as td:
        harness = Path(td) / "harness.html"
        harness.write_bytes(build_harness().encode("utf-8"))
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"file://{harness}")
            page.wait_for_load_state("load")
            page.wait_for_timeout(300)
            checks = run_checks(page)
            checks.extend(run_agent_settings_regressions(page))
            browser.close()

    if errors:
        checks.append({"page": "global", "ok": False, "error": f"JS 错误: {errors[:3]}"})
    ok = all(c["ok"] for c in checks) and bool(checks)

    if args.json:
        print(json.dumps({"ok": ok, "passed": sum(1 for c in checks if c["ok"]),
                          "total": len(checks), "checks": checks}, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            status = "PASS" if c["ok"] else "FAIL"
            print(f"[{status}] {c['page']}: {c.get('detail') or c.get('error')}")
        print(f"\n{'=' * 40}\n总体: {'通过' if ok else '失败'} ({sum(1 for c in checks if c['ok'])}/{len(checks)})")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
