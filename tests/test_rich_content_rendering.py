"""Issue #5/#6/#7 富内容渲染回归测试。

- #5: requirement-insights 三个子步骤 per-prompt schema（已在 test_bug171/test_schema_coverage_contract 覆盖，
  这里补充端到端契约：schema_loader.load 按 prompt 名命中三份新 schema）
- #6: KaTeX 本地化渲染契约
- #7: 隔离式 SVG 预览安全契约
另含可选的真实浏览器（Playwright/Chromium）功能验证，环境缺失时自动跳过。
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/static"
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CHAT_JS = (STATIC / "js/chat.js").read_text(encoding="utf-8")
REVIEW_JS = (STATIC / "js/review.js").read_text(encoding="utf-8")
RICH_JS = (STATIC / "js/rich-content.js").read_text(encoding="utf-8")


# ── Issue #5: per-prompt schema 加载链路 ──


def _load_schema_loader():
    import sys

    sys.path.insert(0, str(ROOT))
    from src.app.services.skill_schema import SkillSchemaLoader

    return SkillSchemaLoader(str(ROOT / "skills"))


def test_issue5_insight_substep_schemas_loaded_by_prompt_name():
    loader = _load_schema_loader()
    for prompt_name in ("evolution-match", "feature-extraction", "gap-assessment"):
        schema = loader.load("requirement-insights", prompt_name)
        assert schema, f"per-prompt schema missing for {prompt_name}"
        assert schema.get("required"), f"{prompt_name} schema must declare required fields"


def test_issue5_top_level_schema_still_required_for_report():
    top = (ROOT / "skills/requirement-insights/templates/output-schema.json").read_text(encoding="utf-8")
    assert '"project_name"' in top
    assert '"output_type"' in top


# ── Issue #6: KaTeX 本地化 ──


def test_katex_vendor_files_present():
    katex_dir = STATIC / "vendor/katex"
    assert (katex_dir / "katex.min.js").exists()
    assert (katex_dir / "katex.min.css").exists()
    assert (katex_dir / "contrib/auto-render.min.js").exists()
    assert (katex_dir / "contrib/mhchem.min.js").exists()
    assert (katex_dir / "fonts/KaTeX_Main-Regular.woff2").exists()
    assert (katex_dir / "LICENSE").exists()


def test_index_html_references_katex_and_rich_content():
    assert './vendor/katex/katex.min.css' in INDEX_HTML
    assert './vendor/katex/katex.min.js' in INDEX_HTML
    assert './vendor/katex/contrib/auto-render.min.js' in INDEX_HTML
    assert './vendor/katex/contrib/mhchem.min.js' in INDEX_HTML
    assert './js/rich-content.js' in INDEX_HTML
    # rich-content 必须先于 chat/review 加载
    assert INDEX_HTML.index("rich-content.js") < INDEX_HTML.index("chat.js")
    assert INDEX_HTML.index("rich-content.js") < INDEX_HTML.index("review.js")


def test_rich_content_math_configuration():
    # 定界符：块级 $$、\[，行内 \(；第一版不启用单 $
    assert "{ left: '$$', right: '$$', display: true }" in RICH_JS
    assert "{ left: '\\\\[', right: '\\\\]', display: true }" in RICH_JS
    assert "{ left: '\\\\(', right: '\\\\)', display: false }" in RICH_JS
    single_dollar = "{ left: '$', right: '$', display: false }"
    assert single_dollar not in RICH_JS
    # pre/code 不参与公式渲染
    assert "'pre', 'code'" in RICH_JS or "ignoredTags" in RICH_JS
    assert "throwOnError: false" in RICH_JS


def test_renderers_call_protect_math_before_marked_parse():
    for js, name in ((CHAT_JS, "chat.js"), (REVIEW_JS, "review.js")):
        protect_pos = js.index("RichContent.protectMath(text)")
        parse_pos = js.index("window.marked.parse(text)")
        sanitize_pos = js.index("DOMPurify.sanitize(window.marked.parse(text)")
        assert 0 < protect_pos < sanitize_pos < parse_pos, (
            f"{name} must protect math, then DOMPurify.sanitize(marked.parse(...))"
        )


def test_dom_purify_profile_tightened_to_html_only():
    for js, name in ((CHAT_JS, "chat.js"), (REVIEW_JS, "review.js")):
        assert "USE_PROFILES: { html: true }" in js, f"{name} main profile must be HTML-only"
        assert "USE_PROFILES: { html: true, svg: true" not in js, (
            f"{name} must not open the SVG profile for arbitrary markdown"
        )


# ── Issue #7: 隔离式 SVG 预览 ──


def test_renderer_code_has_svg_placeholder_branch():
    for js, name in ((CHAT_JS, "chat.js"), (REVIEW_JS, "review.js")):
        assert "lang === 'svg'" in js or "lang.toLowerCase() === 'svg'" in js, name
        assert 'class="svg-container"' in js, name
        assert 'pre class="svg-source"' in js, name
        assert "svg-toggle-btn" in js, name


def test_svg_sanitizer_rejects_dangerous_content():
    forbidden_tags = ["script", "style", "foreignObject", "image", "use", "a"]
    for tag in forbidden_tags:
        assert f"'{tag}'" in RICH_JS, f"FORBID_TAGS must include {tag}"
    for attr in ("href", "xlink:href", "style"):
        assert f"'{attr}'" in RICH_JS, f"FORBID_ATTR must include {attr}"
    # 单一 svg 根校验 + parsererror 检查
    assert "parsererror" in RICH_JS
    assert "nodeName.toLowerCase() !== 'svg'" in RICH_JS


def test_svg_preview_uses_blob_url_isolation():
    assert "createObjectURL" in RICH_JS
    assert "revokeObjectURL" in RICH_JS
    assert "image/svg+xml" in RICH_JS
    assert '<img class="svg-preview-img"' not in CHAT_JS.split("_renderMarkdownWithLibraries")[0]
    assert "addEventListener('beforeunload'" in RICH_JS


def test_blob_url_revoked_on_scope_replacement():
    # chat 会话切换 & review 报告重渲染前必须回收 Blob URL
    assert "RichContent.revoke(container)" in CHAT_JS
    assert "RichContent.revoke(contentEl)" in REVIEW_JS


# ── 真实浏览器功能验证（Playwright/Chromium 可用时执行，独立子进程避免事件循环冲突） ──

BROWSER_TOOL = ROOT / "tools/verify_rich_content_browser.py"


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not BROWSER_TOOL.exists(), reason="browser verify tool missing")
@pytest.mark.skipif(not _playwright_available(), reason="Playwright not installed")
def test_browser_rich_content_end_to_end():
    """Chat/Review 两入口：公式定界符、mhchem、code 隔离、坏公式降级、SVG 预览/切换/安全拒绝。"""
    import json
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(BROWSER_TOOL), "--json"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"browser verification failed:\n{proc.stdout}\n{proc.stderr}"
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    checks = {c["name"]: c["passed"] for c in report["checks"]}
    required = [
        "math_block_display",
        "math_inline_paren",
        "math_bracket_display",
        "mhchem_formula",
        "latex_in_code_untouched",
        "bad_formula_degrades",
        "svg_valid_preview_blob",
        "svg_toggle_source_preview",
        "svg_script_rejected",
        "svg_onload_attr_rejected",
        "svg_foreign_object_rejected",
        "svg_style_tag_rejected",
        "svg_javascript_href_rejected",
        "svg_external_image_rejected",
        "svg_multi_root_rejected",
        "svg_not_svg_rejected",
        "inline_raw_svg_stripped",
        "plain_code_intact",
        "mermaid_container_preserved",
        "chat_review_consistent",
    ]
    missing = [name for name in required if name not in checks]
    failed = [name for name in required if not checks.get(name)]
    assert not missing, f"missing checks: {missing}"
    assert not failed, f"failed browser checks: {failed}"
