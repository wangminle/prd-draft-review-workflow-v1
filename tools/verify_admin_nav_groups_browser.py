#!/usr/bin/env python3
"""管理后台侧栏分组导航真实浏览器验证（Playwright/Chromium）。

加载真实的 index.html + main.css，验证：
1. 展开态：三个分组标题可见，分组头与组内首个 tab 的归属关系正确；
2. 收起态（.collapsed）：分组标题退化为 1px 分隔线（高度归零、不可见文字）；
3. 窄屏（≤1100px 视口）：与收起态一致的图标栏表现（含 tab 文字隐藏）；
4. 点击委托不受分组头影响：点击任一分组头不切换 tab，
   点击「Pi Agent 配置」正常切换 active；
5. 分组头对读屏可见（无 aria-hidden）。

用法：
    python3 tools/verify_admin_nav_groups_browser.py            # 人读输出
    python3 tools/verify_admin_nav_groups_browser.py --json     # JSON 输出
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/static"

# 分组头 → 组内首个 tab 的 data-tab 键
GROUP_FIRST_TAB = [
    ("运营概览", "stats"),
    ("团队与内容", "users"),
    ("AI 能力 · 全局", "models"),
]


def run_checks() -> dict:
    from playwright.sync_api import sync_playwright

    results = []

    def check(name: str, ok: bool, detail: str = ""):
        results.append({"name": name, "ok": bool(ok), "detail": detail})

    # file:// 直载无登录态：默认页（聊天）带 active，会与管理页同时渲染、互相挤占布局。
    # 统一先清空所有页面 active，再单独激活管理页，测的是纯管理页布局。
    # 另外 file:// 下 branding fetch 失败会让 _alignSidebarToDivider 算出宽度 0 的
    # 内联样式，一并清掉，还原纯 CSS 布局（生产环境走 http:// 无此问题）。
    ACTIVATE_ADMIN = (
        "document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));"
        "document.getElementById('admin-page').classList.add('active');"
        "const __sb = document.querySelector('.admin-sidebar');"
        "if (__sb) __sb.style.width = '';"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"file://{STATIC}/index.html")
            page.evaluate(ACTIVATE_ADMIN)
            page.wait_for_selector(".admin-nav-group", state="attached")

            # ── 1. 展开态：分组标题可见且归属正确 ──
            groups = page.locator(".admin-nav-group")
            check("展开态分组数量为3", groups.count() == 3, f"实际 {groups.count()}")

            labels = [groups.nth(i).inner_text() for i in range(groups.count())]
            for label, first_tab in GROUP_FIRST_TAB:
                check(
                    f"分组「{label}」存在",
                    label in labels,
                    f"实际标签 {labels}",
                )

            # 分组头不得用 aria-hidden 隐藏（读屏用户需要听到分组区分，BUG-178）
            hidden_count = page.locator(".admin-nav-group[aria-hidden='true']").count()
            check("分组头对读屏可见（无 aria-hidden）", hidden_count == 0, f"aria-hidden 数 {hidden_count}")

            for label, first_tab in GROUP_FIRST_TAB:
                group_box = page.locator(
                    f".admin-nav-group:has-text('{label}')"
                ).first.bounding_box()
                tab_box = page.locator(
                    f'.admin-nav-item[data-tab="{first_tab}"]'
                ).first.bounding_box()
                ok = (
                    group_box is not None
                    and tab_box is not None
                    and tab_box["y"] > group_box["y"]
                    and tab_box["y"] - group_box["y"] < 60
                )
                check(
                    f"「{label}」组头位于 {first_tab} 上方且紧邻",
                    ok,
                    f"group_y={group_box and group_box['y']}, tab_y={tab_box and tab_box['y']}",
                )

            # ── 2. 点击委托：点分组头不切 tab，点 pi-agent 正常切 ──
            active_before = page.locator(".admin-nav-item.active").first.get_attribute(
                "data-tab"
            )
            page.locator(".admin-nav-group").first.click(force=True)
            active_after_group = page.locator(".admin-nav-item.active").first.get_attribute(
                "data-tab"
            )
            check(
                "点击分组头不改变 active tab",
                active_before == active_after_group,
                f"前={active_before} 后={active_after_group}",
            )

            page.locator('.admin-nav-item[data-tab="pi-agent"]').click()
            active_pi = page.locator(".admin-nav-item.active").first.get_attribute("data-tab")
            check("点击 Pi Agent 配置正常切换", active_pi == "pi-agent", f"实际 {active_pi}")

            # ── 3. 收起态：分组标题退化为 1px 分分隔线 ──
            page.locator(".admin-sidebar .sidebar-toggle-btn").click()
            page.wait_for_timeout(300)
            sep = page.locator(".admin-nav-group").first
            sep_box = sep.bounding_box()
            sep_text = sep.inner_text()
            check(
                "收起态分组头高度≈1px（分隔线）",
                sep_box is not None and sep_box["height"] <= 2,
                f"高度 {sep_box and sep_box['height']}px",
            )
            check(
                "收起态分组头文字不可见",
                sep_text.strip() == "" or sep.evaluate("el => el.clientHeight < 2"),
                f"text={sep_text!r}",
            )

            # 收起态下点击 tab 仍正常
            page.locator('.admin-nav-item[data-tab="skills"]').click(force=True)
            active_skills = page.locator(".admin-nav-item.active").first.get_attribute(
                "data-tab"
            )
            check("收起态点击 Skills 正常切换", active_skills == "skills", f"实际 {active_skills}")

            # ── 4. 窄屏（≤1100px）：图标栏 + 分隔线 ──
            page2 = browser.new_page(viewport={"width": 1000, "height": 900})
            page2.goto(f"file://{STATIC}/index.html")
            page2.evaluate(ACTIVATE_ADMIN)
            page2.wait_for_selector(".admin-nav-group", state="attached")
            # 窄屏侧栏宽度有 transition 动画：禁用过渡 + 强制 reflow，取静止后的尺寸
            page2.add_style_tag(
                content=".admin-sidebar, .admin-nav-item, .admin-nav-group { transition: none !important; }"
            )
            # 模拟真实 resize 后的延迟对齐逻辑；该逻辑不得以内联宽度覆盖窄屏媒体规则。
            page2.evaluate("App._alignSidebarToDivider()")
            page2.wait_for_timeout(200)
            narrow_box = page2.locator(".admin-nav-group").first.bounding_box()
            check(
                "窄屏分组头高度≈1px（分隔线）",
                narrow_box is not None and narrow_box["height"] <= 2,
                f"高度 {narrow_box and narrow_box['height']}px",
            )
            sidebar_w = page2.locator(".admin-sidebar").first.bounding_box()
            check(
                "窄屏侧栏收窄为图标栏（≤60px）",
                sidebar_w is not None and sidebar_w["width"] <= 60,
                f"宽度 {sidebar_w and sidebar_w['width']}px",
            )
            # 窄屏下 tab 文字必须隐藏（依赖标签包在 <span> 里命中 .admin-nav-item span 规则，BUG-179）
            label_hidden = page2.locator(
                '.admin-nav-item[data-tab="stats"] span'
            ).is_hidden()
            check("窄屏 tab 文字隐藏（span 生效）", label_hidden, f"hidden={label_hidden}")
        finally:
            browser.close()

    failed = [r for r in results if not r["ok"]]
    return {
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "checks": results,
        "ok": not failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="输出 JSON（供 pytest 断言）")
    args = parser.parse_args()

    report = run_checks()

    if args.json:
        # 单行紧凑 JSON：pytest 子进程按最后一行解析，多行会截断
        print(json.dumps(report, ensure_ascii=False))
    else:
        for c in report["checks"]:
            mark = "✓" if c["ok"] else "✗"
            print(f"{mark} {c['name']}" + (f"  ({c['detail']})" if c["detail"] else ""))
        print(f"\n{report['passed']} passed, {report['failed']} failed")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
