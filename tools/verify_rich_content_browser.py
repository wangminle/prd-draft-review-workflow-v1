#!/usr/bin/env python3
"""Issue #6/#7 富内容渲染真实浏览器验证工具（Playwright/Chromium）。

加载项目真实的 vendor 库与前端 JS，模拟 Chat / Review 两个入口的完整渲染链路：
marked 解析 → DOMPurify 清洗 → DOM 插入 → RichContent.enhance。

用法：
    python3 tools/verify_rich_content_browser.py            # 人读输出
    python3 tools/verify_rich_content_browser.py --json     # JSON 输出（供 pytest 断言）

环境依赖：pip install playwright && playwright install chromium
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/static"

HARNESS_BODY = """
<div id="out-chat"></div>
<div id="out-review"></div>
<script>
window.renderTo = function (targetId, md) {
  const target = document.getElementById(targetId);
  target.innerHTML = window.RichContent.protectMath ? '' : '';
  if (targetId === 'out-chat') {
    target.innerHTML = window.Chat._renderMarkdown(md);
  } else {
    target.innerHTML = window.Review._renderMarkdown(md);
  }
  window.RichContent.enhance(target);
  return target;
};
</script>
"""


def build_harness() -> Path:
    scripts = [
        "vendor/purify.min.js",
        "vendor/marked.min.js",
        "vendor/katex/katex.min.js",
        "vendor/katex/contrib/auto-render.min.js",
        "vendor/katex/contrib/mhchem.min.js",
        "js/rich-content.js",
        "js/chat.js",
        "js/review.js",
    ]
    links = ['<link rel="stylesheet" href="file://%s">' % (STATIC / "vendor/katex/katex.min.css")]
    links += ['<script src="file://%s"></script>' % (STATIC / s) for s in scripts]
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        + "".join(links)
        + "</head><body>"
        + HARNESS_BODY
        + "</body></html>"
    )
    fd, path = tempfile.mkstemp(suffix=".html", prefix="rich-content-harness-", dir=tempfile.gettempdir())
    with __import__("os").fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(html)
    return Path(path)


def check(name, passed, detail=""):
    return {"name": name, "passed": bool(passed), "detail": str(detail)[:300]}


def run(args_json=False):
    from playwright.sync_api import sync_playwright

    harness = build_harness()
    checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(harness.as_uri())
        page.wait_for_load_state("networkidle")

        # 前端脚本必须全部加载成功（含 rich-content / KaTeX）
        checks.append(check(
            "libs_loaded",
            page.evaluate("!!(window.Chat && window.Review && window.RichContent && window.katex "
                          "&& window.renderMathInElement && window.DOMPurify && window.marked)"),
            "Chat/Review/RichContent/KaTeX/auto-render/DOMPurify/marked must all load",
        ))

        # ── #6 数学公式 ──
        MATH_BLOCK = "$$\nE = mc^2\n$$"
        MATH_INLINE = r"\(p = mv\)"
        MATH_BRACKET = "\n\\[\nMnO_4^- + 8H^+ + 5e^- \\rightarrow Mn^{2+} + 4H_2O\n\\]\n"
        MHCEM_MD = "$$\\ce{2H2 + O2 -> 2H2O}$$"

        for case_name, md, min_katex in (
            ("math_block_display", MATH_BLOCK, 1),
            ("math_inline_paren", f"行内 {MATH_INLINE} 文本", 1),
            ("math_bracket_display", f"前文{MATH_BRACKET}后文", 1),
            ("mhchem_formula", f"方程式 {MHCEM_MD} 结束", 1),
        ):
            per_entry_ok = []
            details = {}
            for entry in ("chat", "review"):
                out_id = f"out-{entry}"
                res = page.evaluate(
                    """(args) => {
                        const [outId, md] = args;
                        const el = window.renderTo(outId, md);
                        return {
                            katex: el.querySelectorAll('.katex').length,
                            slots: el.querySelectorAll('.math-slot[data-lat]').length,
                            errs: el.querySelectorAll('.math-error').length,
                            text: el.textContent,
                        };
                    }""",
                    [out_id, md],
                )
                ok = res["katex"] >= min_katex and res["slots"] == 0 and res["errs"] == 0
                per_entry_ok.append(ok)
                details[entry] = res
            checks.append(check(case_name, all(per_entry_ok), json.dumps(details, ensure_ascii=False)))

        # code fence 内的 LaTeX 不渲染（Chat/Review 各验一次）
        code_results = page.evaluate(
            """(args) => {
                return args.map(pair => {
                    const [outId, md] = pair;
                    const el = window.renderTo(outId, md);
                    return {
                        katexInsidePre: el.querySelectorAll('pre .katex').length,
                        sourceKept: el.textContent.includes('E=mc^2'),
                    };
                });
            }""",
            [
                [entry, "代码：\n\n```text\n\\[ E=mc^2 \\]\n```\n"] for entry in ("out-chat", "out-review")
            ],
        )
        checks.append(check(
            "latex_in_code_untouched",
            all(r["katexInsidePre"] == 0 and r["sourceKept"] for r in code_results),
            str(code_results),
        ))

        # 错误公式不影响整条消息
        BAD_MD = "前文正常。$$\\frac{不完整 缺右括号$$ 后文也正常。"
        bad = page.evaluate(
            """(args) => {
                const el = window.renderTo(args[0], args[1]);
                return { intact: el.textContent.includes('后文也正常') && el.textContent.includes('前文正常') };
            }""",
            ["out-chat", BAD_MD],
        )
        checks.append(check("bad_formula_degrades", bad["intact"], str(bad)))

        # ── #7 SVG 预览 ──
        VALID_SVG_MD = (
            "```svg\n<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 60 30\">"
            "<circle cx=\"20\" cy=\"15\" r=\"10\" fill=\"#3b82f6\"/></svg>\n```"
        )
        svg_state = page.evaluate(
            """(args) => {
                const [outId, md] = args;
                const el = window.renderTo(outId, md);
                const c = el.querySelector('.svg-container');
                if (!c) return { noContainer: true };
                const img = c.querySelector('.svg-preview-img');
                const btn = c.querySelector('.svg-toggle-btn');
                const before = { hidden: img.hidden, blobSrc: (img.src || '').startsWith('blob:') };
                btn.click();
                const shownSource = c.classList.contains('show-source');
                const labelAfterClick = btn.textContent;
                btn.click();
                return {
                    before, shownSource, labelAfterClick,
                    backToPreview: !c.classList.contains('show-source'),
                    labelFinal: btn.textContent,
                    errorShown: !c.querySelector('.svg-error').hidden,
                    enhanced: c.getAttribute('data-svg-enhanced') === '1',
                };
            }""",
            ["out-chat", VALID_SVG_MD],
        )
        checks.append(check("svg_valid_preview_blob", not svg_state.get("noContainer")
                            and svg_state.get("before", {}).get("blobSrc") is True
                            and svg_state.get("before", {}).get("hidden") is False, str(svg_state)))
        checks.append(check("svg_toggle_source_preview",
                            svg_state.get("shownSource") is True and svg_state.get("backToPreview") is True
                            and "图形" in svg_state.get("labelAfterClick", "")
                            and "源码" in svg_state.get("labelFinal", ""), str(svg_state)))

        EVIL_CASES = {
            "script": "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script><circle r='5'/></svg>",
            "onload_attr": "<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'><circle r='5'/></svg>",
            "foreign_object": "<svg xmlns='http://www.w3.org/2000/svg'><foreignObject><body>x</body></foreignObject></svg>",
            "style_tag": "<svg xmlns='http://www.w3.org/2000/svg'><style>circle{fill:red}</style></svg>",
            "javascript_href": "<svg xmlns='http://www.w3.org/2000/svg'><a xlink:href='javascript:alert(1)'><circle r='5'/></a></svg>",
            "external_image": "<svg xmlns='http://www.w3.org/2000/svg'><image href='https://evil.example/x.png'/></svg>",
            "multi_root": "<svg xmlns='http://www.w3.org/2000/svg'><circle r='5'/></svg>plain text outside",
            "not_svg": "just some text, not an svg at all",
        }
        for case_name, payload in EVIL_CASES.items():
            state = page.evaluate(
                """(args) => {
                    const [outId, md] = args;
                    const el = window.renderTo(outId, md);
                    const c = el.querySelector('.svg-container:last-of-type') ||
                              [...el.querySelectorAll('.svg-container')].pop();
                    if (!c) return { noContainer: true };
                    const img = c.querySelector('.svg-preview-img');
                    const err = c.querySelector('.svg-error');
                    return {
                        errVisible: !!(err && !err.hidden),
                        hasBlobSrc: !!(img && img.src && img.src.startsWith('blob:') && !img.hidden),
                        scriptInDom: !!c.querySelector('script'),
                        onunloadAttr: c.innerHTML.toLowerCase().includes('onload'),
                        fellBackToSource: c.classList.contains('show-source'),
                    };
                }""",
                ["out-chat", f"```svg\n{payload}\n```"],
            )
            safe = (
                not state.get("noContainer")
                and state["hasBlobSrc"] is False
                and state["scriptInDom"] is False
                and (state["errVisible"] or state["fellBackToSource"])
            )
            checks.append(check(f"svg_{case_name}_rejected", safe, str(state)))

        # 内联原始 SVG HTML 应被 HTML-only profile 清除
        inline = page.evaluate(
            """(outId) => {
                const el = document.getElementById(outId);
                el.innerHTML = window.DOMPurify.sanitize(window.marked.parse("<svg onload='alert(1)'></svg>**强调**文本"), { USE_PROFILES: { html: true } });
                return el.innerHTML.toLowerCase();
            }""",
            "out-chat",
        )
        checks.append(check("inline_raw_svg_stripped", "<svg" not in inline.split("svg-source")[0], inline[:200]))

        # 普通代码块与 Mermaid 不回退
        mm = page.evaluate(
            """() => {
                const chatEl = window.renderTo('out-chat', '```mermaid\\ngraph TD; A-->B;\\n```\\n\\n```js\\nconst x = 1;\\n```');
                const reviewEl = window.renderTo('out-review', '```mermaid\\ngraph TD; A-->B;\\n```\\n\\n```js\\nconst x = 1;\\n```');
                return {
                    chatMermaid: !!chatEl.querySelector('.mermaid-container .mermaid-source'),
                    chatCode: chatEl.textContent.includes('const x = 1;'),
                    reviewMermaid: !!reviewEl.querySelector('.mermaid-container .mermaid-source'),
                    reviewCopyBtn: !!reviewEl.querySelector('.code-copy-btn'),
                };
            }"""
        )
        checks.append(check("mermaid_container_preserved", mm["chatMermaid"] and mm["reviewMermaid"], str(mm)))
        checks.append(check("plain_code_intact", mm["chatCode"] and mm["reviewCopyBtn"], str(mm)))
        checks.append(check("chat_review_consistent",
                            mm["chatMermaid"] == mm["reviewMermaid"] and mm["chatCode"] == mm["reviewCopyBtn"], str(mm)))

        checks.append(check("no_page_errors", len(errors) == 0, "; ".join(errors)[:300]))
        browser.close()

    harness.unlink(missing_ok=True)

    failed = [c for c in checks if not c["passed"]]
    report = {"total": len(checks), "failed": len(failed), "checks": checks}
    if args_json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for c in checks:
            mark = "PASS" if c["passed"] else "FAIL"
            print(f"[{mark}] {c['name']}" + (f" — {c['detail']}" if not c["passed"] else ""))
        print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="args_json")
    ns = parser.parse_args()
    sys.exit(run(args_json=ns.args_json))
