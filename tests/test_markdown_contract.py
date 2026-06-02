"""P2.5 — Markdown & Mermaid 渲染修复前端契约测试"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "src/static/js/chat.js").read_text(encoding="utf-8")
REVIEW_JS = (ROOT / "src/static/js/review.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/static/css/main.css").read_text(encoding="utf-8")
VENDOR_NOTICE = (ROOT / "src/static/vendor/NOTICE.md").read_text(encoding="utf-8")


class TestVendorLocalization:
    def test_local_vendor_scripts_exist_in_html(self):
        assert "/vendor/purify.min.js" in HTML
        assert "/vendor/marked.min.js" in HTML
        assert "/vendor/mermaid.min.js" in HTML

    def test_no_cdn_script_references_in_html(self):
        assert "cdn.jsdelivr.net" not in HTML
        assert "unpkg.com" not in HTML
        assert "cdnjs.cloudflare.com" not in HTML

    def test_vendor_load_failure_onerror(self):
        assert "onerror" in HTML
        assert "DOMPurify load failed" in HTML
        assert "marked load failed" in HTML
        assert "mermaid load failed" in HTML

    def test_vendor_notice_exists(self):
        assert "DOMPurify" in VENDOR_NOTICE
        assert "marked" in VENDOR_NOTICE
        assert "mermaid" in VENDOR_NOTICE
        assert "License" in VENDOR_NOTICE

    def test_vendor_files_exist(self):
        assert (ROOT / "src/static/vendor/purify.min.js").exists()
        assert (ROOT / "src/static/vendor/marked.min.js").exists()
        assert (ROOT / "src/static/vendor/mermaid.min.js").exists()

    def test_vendor_files_are_valid_js(self):
        for f in ["purify.min.js", "marked.min.js", "mermaid.min.js"]:
            content = (ROOT / f"src/static/vendor/{f}").read_text(encoding="utf-8")
            assert content.strip().startswith("<!") is False, f"{f} appears to be HTML error page"

    def test_static_scripts_have_cache_busting_version(self):
        for script in [
            "/vendor/purify.min.js",
            "/vendor/marked.min.js",
            "/vendor/mermaid.min.js",
            "/js/chat.js",
            "/js/review.js",
        ]:
            assert f'{script}?v=' in HTML


class TestMarkdownRenderingSplit:
    def test_chat_has_render_markdown_with_libraries(self):
        assert "_renderMarkdownWithLibraries" in CHAT_JS
        assert "window.marked" in CHAT_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1]

    def test_chat_has_render_markdown_fallback(self):
        assert "_renderMarkdownFallback" in CHAT_JS
        fallback = CHAT_JS.split("_renderMarkdownFallback(text) {", 1)[1]
        assert "<h1>" in fallback
        assert "<h3>" in fallback
        assert "<strong>" in fallback
        assert "<code>" in fallback
        assert "<pre>" in fallback
        assert "mermaid-container" in fallback

    def test_chat_fallback_list_has_containers(self):
        assert "_wrapListItems" in CHAT_JS
        assert "'ul'" in CHAT_JS
        assert "'ol'" in CHAT_JS

    def test_chat_fallback_list_preserves_position(self):
        wrap_block = CHAT_JS.split("_wrapListItems(html, pattern, tag) {", 1)[1].split("_queueMermaidRender", 1)[0]
        assert "split('\\n')" in wrap_block
        assert "result" in wrap_block

    def test_review_has_render_markdown_with_libraries(self):
        assert "_renderMarkdownWithLibraries" in REVIEW_JS
        assert "window.marked" in REVIEW_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1]

    def test_review_has_render_markdown_fallback(self):
        assert "_renderMarkdownFallback" in REVIEW_JS
        fallback = REVIEW_JS.split("_renderMarkdownFallback(text) {", 1)[1]
        assert "<h1>" in fallback
        assert "<h3>" in fallback
        assert "<strong>" in fallback
        assert "<code>" in fallback
        assert "<pre>" in fallback
        assert "mermaid-container" in fallback

    def test_review_fallback_list_has_containers(self):
        assert "_wrapListItems" in REVIEW_JS
        assert "'ul'" in REVIEW_JS
        assert "'ol'" in REVIEW_JS

    def test_review_fallback_list_preserves_position(self):
        wrap_block = REVIEW_JS.split("_wrapListItems(html, pattern, tag) {", 1)[1].split("_escAttr(s)", 1)[0]
        assert "split('\\n')" in wrap_block
        assert "result" in wrap_block

    def test_chat_dompurify_allows_svg(self):
        lib_block = CHAT_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1].split("_renderMarkdownFallback(text) {", 1)[0]
        assert "USE_PROFILES" in lib_block
        assert "svg: true" in lib_block
        assert "svgFilters: true" in lib_block

    def test_review_dompurify_allows_svg(self):
        lib_block = REVIEW_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1].split("_renderMarkdownFallback(text) {", 1)[0]
        assert "USE_PROFILES" in lib_block
        assert "svg: true" in lib_block
        assert "svgFilters: true" in lib_block

    def test_chat_mermaid_container_in_library_render(self):
        lib_block = CHAT_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1].split("_renderMarkdownFallback(text) {", 1)[0]
        assert "mermaid-container" in lib_block
        assert "mermaid-source" in lib_block

    def test_chat_mermaid_container_in_fallback_render(self):
        fallback = CHAT_JS.split("_renderMarkdownFallback(text) {", 1)[1].split("_queueMermaidRender", 1)[0]
        assert "mermaid-container" in fallback
        assert "mermaid-source" in fallback

    def test_review_mermaid_container_in_library_render(self):
        lib_block = REVIEW_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1].split("_renderMarkdownFallback(text) {", 1)[0]
        assert "mermaid-container" in lib_block
        assert "mermaid-source" in lib_block

    def test_review_mermaid_container_in_fallback_render(self):
        fallback = REVIEW_JS.split("_renderMarkdownFallback(text) {", 1)[1].split("_escAttr(s)", 1)[0]
        assert "mermaid-container" in fallback
        assert "mermaid-source" in fallback


class TestMermaidRenderTiming:
    def test_chat_queue_mermaid_is_noop_during_streaming(self):
        assert "_queueMermaidRender(scope = document)" in CHAT_JS
        queue_block = CHAT_JS.split("_queueMermaidRender(scope = document) {", 1)[1].split("_schedulePostStreamMermaid", 1)[0]
        assert "// During streaming, don't render Mermaid" in queue_block

    def test_chat_schedule_post_stream_mermaid_debounce(self):
        assert "_schedulePostStreamMermaid(scope, delay = 2000)" in CHAT_JS
        assert "_mermaidDebounceTimer" in CHAT_JS

    def test_chat_render_mermaid_on_stream_end(self):
        assert "_renderMermaidOnStreamEnd(scope)" in CHAT_JS
        assert "this._renderMermaidCharts(scope)" in CHAT_JS.split("_renderMermaidOnStreamEnd(scope) {", 1)[1]

    def test_chat_stream_loop_uses_schedule_not_queue(self):
        stream_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
        assert "_schedulePostStreamMermaid" in stream_block
        assert "_queueMermaidRender" not in stream_block

    def test_chat_stream_done_triggers_immediate_render(self):
        stream_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
        assert "_renderMermaidOnStreamEnd" in stream_block

    def test_chat_post_stream_loop_render_mermaid(self):
        assert "_renderMermaidOnStreamEnd(contentEl)" in CHAT_JS

    def test_mermaid_start_on_load_false(self):
        assert "startOnLoad: false" in CHAT_JS
        assert "startOnLoad: false" in REVIEW_JS

    def test_history_append_message_renders_mermaid_immediately(self):
        append_block = CHAT_JS.split("_appendMessage(role, content) {", 1)[1].split("_renderMarkdown(text)", 1)[0]
        assert "_renderMermaidOnStreamEnd" in append_block
        assert "_queueMermaidRender" not in append_block


class TestMermaidErrorHandling:
    def test_chat_mermaid_library_render_preserves_source_node(self):
        lib_block = CHAT_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1].split("_renderMarkdownFallback(text) {", 1)[0]
        assert "mermaid-source" in lib_block
        assert "data-mermaid=" not in lib_block

    def test_review_mermaid_library_render_preserves_source_node(self):
        lib_block = REVIEW_JS.split("_renderMarkdownWithLibraries(text) {", 1)[1].split("_renderMarkdownFallback(text) {", 1)[0]
        assert "mermaid-source" in lib_block
        assert "data-mermaid=" not in lib_block

    def test_chat_mermaid_parse_before_render(self):
        mermaid_block = CHAT_JS.split("async _renderMermaidCharts(scope = document) {", 1)[1].split("_scrollBottom()", 1)[0]
        assert "mermaid.parse(code)" in mermaid_block
        assert "this._getMermaidSource(el)" in mermaid_block

    def test_review_mermaid_parse_before_render(self):
        mermaid_block = REVIEW_JS.split("async _renderMermaidCharts() {", 1)[1].split("_renderDraft(report)", 1)[0]
        assert "mermaid.parse(code)" in mermaid_block
        assert "this._getMermaidSource(el)" in mermaid_block

    def test_chat_mermaid_error_preserves_source(self):
        mermaid_block = CHAT_JS.split("async _renderMermaidCharts(scope = document) {", 1)[1].split("_scrollBottom()", 1)[0]
        assert "mermaid-error" in mermaid_block
        assert "mermaid-source-details" in mermaid_block
        assert "mermaid-source-code" in mermaid_block
        assert "查看源码" in mermaid_block

    def test_review_mermaid_error_preserves_source(self):
        mermaid_block = REVIEW_JS.split("async _renderMermaidCharts() {", 1)[1].split("_renderDraft(report)", 1)[0]
        assert "mermaid-error" in mermaid_block
        assert "mermaid-source-details" in mermaid_block
        assert "mermaid-source-code" in mermaid_block
        assert "查看源码" in mermaid_block

    def test_chat_mermaid_missing_library_marks_charts_failed(self):
        mermaid_block = CHAT_JS.split("async _renderMermaidCharts(scope = document) {", 1)[1].split("_scrollBottom()", 1)[0]
        missing_block = mermaid_block.split("if (!window.mermaid)", 1)[1].split("const charts", 1)[0]
        assert "this._markMermaidChartsFailed" in missing_block
        assert "return" in missing_block

    def test_review_mermaid_missing_library_marks_charts_failed(self):
        mermaid_block = REVIEW_JS.split("async _renderMermaidCharts() {", 1)[1].split("_renderDraft(report)", 1)[0]
        missing_block = mermaid_block.split("if (!window.mermaid)", 1)[1].split("const charts", 1)[0]
        assert "this._markMermaidChartsFailed" in missing_block
        assert "return" in missing_block

    def test_chat_mermaid_normalizes_unquoted_node_labels_before_parse(self):
        mermaid_block = CHAT_JS.split("async _renderMermaidCharts(scope = document) {", 1)[1].split("_scrollBottom()", 1)[0]
        assert "_normalizeMermaidCode(rawCode)" in mermaid_block
        assert "_normalizeMermaidCode(code)" in CHAT_JS
        normalize_block = CHAT_JS.split("_normalizeMermaidCode(code) {", 1)[1].split("_scrollBottom()", 1)[0]
        assert '["${this._escapeMermaidLabel(label)}"]' in normalize_block
        assert '{"${this._escapeMermaidLabel(label)}"}' in normalize_block

    def test_review_mermaid_normalizes_unquoted_node_labels_before_parse(self):
        mermaid_block = REVIEW_JS.split("async _renderMermaidCharts() {", 1)[1].split("_renderDraft(report)", 1)[0]
        assert "_normalizeMermaidCode(rawCode)" in mermaid_block
        assert "_normalizeMermaidCode(code)" in REVIEW_JS
        normalize_block = REVIEW_JS.split("_normalizeMermaidCode(code) {", 1)[1].split("_renderDraft(report)", 1)[0]
        assert '["${this._escapeMermaidLabel(label)}"]' in normalize_block
        assert '{"${this._escapeMermaidLabel(label)}"}' in normalize_block


class TestMermaidStyles:
    def test_loading_animation_css(self):
        assert ".mermaid-chart:has(.mermaid-source)::before" in CSS
        assert ".mermaid-source" in CSS
        assert "mermaid-spin" in CSS
        assert "@keyframes mermaid-spin" in CSS

    def test_error_state_css(self):
        assert ".mermaid-error" in CSS
        assert ".mermaid-source-details" in CSS
        assert ".mermaid-source-code" in CSS

    def test_fallback_heading_styles_exist(self):
        assert ".msg-text h1" in CSS or ".msg-text h2" in CSS or ".msg-text h3" in CSS
