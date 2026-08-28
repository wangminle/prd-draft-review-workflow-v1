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
MAIN_CSS = (STATIC / "css/main.css").read_text(encoding="utf-8")


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


# ── BUG-175：渐变 SVG 黑底修复（style 归一化 + 白色衬底） ──


def test_svg_style_attrs_normalized_before_purify():
    """模型写 style="stop-color:..." 时，清洗前必须归一化为表示属性，防黑底。"""
    assert "_normalizeSvgStyles" in RICH_JS
    assert "'stop-color': true" in RICH_JS
    # 归一化必须发生在 DOMPurify.sanitize 之前（先保真、后清洗）
    norm_pos = RICH_JS.index("this._normalizeSvgStyles(text)")
    purify_pos = RICH_JS.index("purify.sanitize(normalizable")
    assert 0 < norm_pos < purify_pos
    # 安全姿态不变：style 属性最终仍被 FORBID_ATTR 拒绝
    assert "FORBID_ATTR: ['style', 'href', 'xlink:href']" in RICH_JS


def test_svg_style_fast_path_tolerates_whitespace_and_case():
    """style 与等号间的空白（style = / 制表符）是合法 XML，快路径不得跳过归一化。"""
    assert r"/\bstyle\s*=/i" in RICH_JS
    assert "indexOf('style=')" not in RICH_JS


def test_svg_style_value_rules_are_per_property_whitelist():
    """取值校验必须是按属性的整串白名单，杜绝 CSS 转义/注释/外链绕过。"""
    assert "_validStyleValue" in RICH_JS
    # 全局拒绝反斜杠（CSS 转义 u\\72l）与 CSS 注释
    assert "includes('\\\\')" in RICH_JS
    assert "includes('/*')" in RICH_JS
    # 颜色类仅放行纯色/本地片段引用（可带引号、可带纯色 fallback），
    # 由 _validSvgUrlAttrValue 统一校验（二轮复审后颜色分支复用该函数）
    assert "this._validSvgUrlAttrValue(v)" in RICH_JS
    # 片段引用字符集锚定：# + 字母数字/_:.-（防 url(#id) 中混入路径/协议）
    assert "url\\(\\s*(['\"]?)([^)'\"]*)\\1\\s*(#[^)'\"]*)?\\s*\\)" in RICH_JS
    # 非白名单属性默认拒绝
    assert "default:\n                return false;" in RICH_JS


def test_svg_img_reserves_intrinsic_dimensions():
    """Blob 加载前 <img> 必须按 SVG viewBox/width/height 预留宽高，避免 CLS。"""
    assert "_svgIntrinsicSize" in RICH_JS
    assert "setAttribute('width'" in RICH_JS
    assert "setAttribute('height'" in RICH_JS


def test_svg_fixture_is_sanitizer_friendly():
    """仓库常青示例图（BUG-175 修正版）必须天然通过清洗：纯表示属性 + 纯色回退。"""
    fixture = (ROOT / "tests/fixtures/chemcmp-oxidation-v2.svg").read_text(encoding="utf-8")
    assert fixture.lstrip().startswith("<svg")
    # 全部用表示属性，清洗后不丢颜色；无 style 属性依赖
    assert "style=" not in fixture
    assert 'stop-color="#fafafa"' in fixture
    assert 'stop-color="#fdeaea"' in fixture
    # url() 后跟纯色回退，defs 不可用时不变黑
    assert "url(#chemcmp-light-bg-v2) #f5f6f8" in fixture
    # 化学勘误：⁹⁹Tc/⁹⁹ᵐTc 区分，惰性电子对表述已删除
    assert "⁹⁹ᵐTc" in fixture
    assert "惰性电子对" not in fixture


def test_svg_preview_white_backing():
    """图形视图 .svg-body 必须自带白色衬底。"""
    body_block = MAIN_CSS.split(".svg-body", 1)[1][:400]
    assert "background: #fff" in body_block


# ── BUG-175 二轮复审：URL 白名单绕过 / 极端尺寸 DoS / 渐变 fallback 误删 ──


def test_svg_native_url_attrs_sanitized_after_purify():
    """原生表示属性（fill/filter/marker-*）的外链与 data: url() 必须在 DOMPurify 后统一拦截。"""
    assert "_sanitizeSvgUrlAttrs" in RICH_JS
    assert "_SVG_URL_ATTRS" in RICH_JS
    for attr_name in ("'fill'", "'stroke'", "'filter'", "'clip-path'", "'mask'", "'marker-end'"):
        assert attr_name in RICH_JS, f"URL 属性清单必须包含 {attr_name}"
    # 拦截必须发生在 sanitizeSvg 内、序列化前（清洗后 DOM 遍历，而非仅 style 路径）
    assert "this._sanitizeSvgUrlAttrs(svgRoot)" in RICH_JS
    # 非本地片段引用（外链/data:）一律删除属性
    assert "_validSvgUrlAttrValue" in RICH_JS


def test_svg_intrinsic_size_bounds_against_layout_dos():
    """极端 viewBox（如 0 0 1 100000000）必须被边长/面积/宽高比上限拦截，CSS 兜底 max-height。"""
    assert "_SVG_SIZE_MAX" in RICH_JS
    assert "_SVG_AREA_MAX" in RICH_JS
    assert "_SVG_RATIO_MAX" in RICH_JS
    assert "withinLimits" in RICH_JS
    # CSS 兜底：预览图展示高度受视口约束
    img_block = MAIN_CSS.split(".svg-preview-img", 1)[1][:500]
    assert "max-height: 60vh" in img_block


def test_svg_gradient_fallback_and_quoted_ref_preserved():
    """url(#id) #fff 与 url('#id') 是常见安全渐变写法，白名单必须放行而非误删。"""
    # 颜色分支复用统一取值校验（片段引用 + 可选纯色 fallback）
    assert "this._validSvgUrlAttrValue(v)" in RICH_JS
    # 带引号片段引用放行：url('#g') 形态的正则分支
    assert "rawRef.startsWith('#')" in RICH_JS
    # fallback 部分按纯色校验
    assert "_isPlainColorValue" in RICH_JS


def test_cache_version_bumped_for_url_sanitizer_fix():
    """缓存版本必须升级到 20260828-2，确保部署实例拿到新的 rich-content.js/main.css。"""
    assert "?v=20260828-2" in INDEX_HTML
    assert "?v=20260828-1" not in INDEX_HTML


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
        "svg_style_gradient_normalized",
        "svg_style_spaced_eq_normalized",
        "svg_style_evasion_urls_rejected",
        "svg_native_attr_url_rejected",
        "svg_extreme_viewbox_bounded",
        "svg_gradient_fallback_kept",
        "svg_fixture_chemcmp_pipeline_ok",
        "svg_img_dimensions_reserved",
        "svg_preview_white_backing",
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
