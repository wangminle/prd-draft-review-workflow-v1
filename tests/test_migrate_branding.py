"""品牌迁移工具自动化测试 — 用 fixture 构造旧项目，验证扫描/生成/复制/安全。"""

import pytest
import shutil
import yaml
from pathlib import Path

from tools.migrate_branding import (
    scan_html,
    scan_css,
    scan_runtime,
    discover_assets,
    merge_findings,
    build_branding_yaml,
    build_scan_report,
    copy_assets,
    migrate,
    scan,
    plan,
    apply,
    _validate_asset_path_safe,
    _discover_static_dir,
    _check_write_path_allowed,
    classify_field,
    CONF_HIGH,
    CONF_MEDIUM,
    CONF_LOW,
    CAT_AUTO,
    CAT_CONFIRM,
    CAT_OUT_OF_SCOPE,
)


# ── Fixture: 模拟旧项目 ──


@pytest.fixture
def legacy_project(tmp_path):
    """构造一个包含品牌元素的旧项目目录结构。"""
    static_dir = tmp_path / "legacy" / "static"
    static_dir.mkdir(parents=True)

    # HTML
    html_content = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta name="theme-color" content="#1A73E8">
    <title>我的产品平台</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <link rel="stylesheet" href="/css/main.css">
</head>
<body>
    <div id="login-page" class="page">
        <div class="auth-brand">
            <div class="brand-mark"><svg viewBox="0 0 72 72"><rect width="72" height="72" rx="16" fill="#1A73E8"/></svg></div>
            <h1 class="brand-title">我的产品平台</h1>
            <p class="brand-desc">智能协作工作流平台</p>
        </div>
        <div class="auth-card">
            <div class="auth-login-notice">
                <p>💡 <strong>温馨提示：</strong></p>
                <p>1. 本网站正在试用体验。</p>
                <p>2. 感感兴趣的同学可以使用账号体验。</p>
            </div>
        </div>
    </div>
    <div id="user-page" class="page">
        <header class="topbar">
            <span class="topbar-title">我的产品平台</span>
            <button id="go-review" class="topbar-link">需求审查</button>
            <button id="go-admin" class="topbar-link">后台管理</button>
        </header>
    </div>
    <div id="review-page" class="page">
        <header class="topbar">
            <span class="topbar-title">需求审查</span>
        </header>
    </div>
</body>
</html>"""
    (static_dir / "index.html").write_text(html_content, encoding="utf-8")

    # CSS
    css_content = """/* Theme */
:root {
    --blue-6: #1A73E8;
    --blue-5: #4285F4;
    --blue-7: #1557B0;
    --color-brand: var(--blue-6);
    --color-brand-hover: var(--blue-5);
    --color-brand-active: var(--blue-7);
    --green-6: #23C343;
}
.auth-container {
    background: linear-gradient(135deg, #0D47A1 0%, #1A73E8 50%, #4285F4 100%);
}"""
    css_dir = static_dir / "css"
    css_dir.mkdir()
    (css_dir / "main.css").write_text(css_content, encoding="utf-8")

    # Favicon SVG
    favicon_svg = '<svg viewBox="0 0 28 28"><rect width="28" height="28" rx="6" fill="#1A73E8"/></svg>'
    (static_dir / "favicon.svg").write_text(favicon_svg, encoding="utf-8")

    # Logo PNG (simulated)
    (static_dir / "logo.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

    # Runtime
    runtime_dir = tmp_path / "legacy" / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "assets" / "branding").mkdir(parents=True)

    return {
        "project_dir": tmp_path / "legacy",
        "static_dir": static_dir,
        "runtime_dir": runtime_dir,
        "tmp_path": tmp_path,
    }


@pytest.fixture
def legacy_project_with_runtime_config(legacy_project):
    """旧项目 runtime 里已有 ui-branding.yaml。"""
    runtime_dir = legacy_project["runtime_dir"]
    config_dir = runtime_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    yaml_content = {
        "app_title": "已有平台",
        "login_title": "已有平台",
        "topbar_title": "已有平台",
        "theme": {
            "primary": "#FF0000",
            "primary_hover": "#FF4444",
        },
        "favicon": "favicon.svg",
    }
    (config_dir / "ui-branding.yaml").write_text(
        yaml.dump(yaml_content, allow_unicode=True), encoding="utf-8"
    )
    return legacy_project


# ── HTML 扫描测试 ──


class TestScanHtml:
    def test_extracts_title(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert findings["app_title"][0] == "我的产品平台"
        assert findings["app_title"][1] == CONF_HIGH

    def test_extracts_login_title(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert findings["login_title"][0] == "我的产品平台"
        assert findings["login_title"][1] == CONF_HIGH

    def test_extracts_login_subtitle(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert findings["login_subtitle"][0] == "智能协作工作流平台"

    def test_extracts_login_notice(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert "温馨提示" in findings["login_notice"][0]
        assert findings["login_notice"][1] == CONF_MEDIUM

    def test_extracts_topbar_title(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert findings["topbar_title"][0] == "我的产品平台"

    def test_extracts_review_label(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert findings["review_workspace_label"][0] == "需求审查"

    def test_extracts_admin_label(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert findings["admin_label"][0] == "后台管理"

    def test_extracts_favicon_href(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert findings["favicon_file"][0] == "/favicon.svg"

    def test_extracts_theme_color_meta(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        assert findings["theme_primary_meta"][0] == "#1A73E8"

    def test_missing_html_returns_empty(self, tmp_path):
        findings = scan_html(tmp_path / "nonexistent.html")
        assert findings == {}


# ── CSS 扫描测试 ──


class TestScanCss:
    def test_extracts_primary_via_var(self, legacy_project):
        findings = scan_css(legacy_project["static_dir"] / "css" / "main.css")
        assert findings["theme_primary"][0] == "#1A73E8"
        assert findings["theme_primary"][1] == CONF_HIGH

    def test_extracts_primary_hover_via_var(self, legacy_project):
        findings = scan_css(legacy_project["static_dir"] / "css" / "main.css")
        assert findings["theme_primary_hover"][0] == "#4285F4"

    def test_detects_gradient(self, legacy_project):
        findings = scan_css(legacy_project["static_dir"] / "css" / "main.css")
        assert "login_gradient_colors" in findings
        assert findings["login_gradient_colors"][1] == CONF_LOW

    def test_missing_css_returns_empty(self, tmp_path):
        findings = scan_css(tmp_path / "nonexistent.css")
        assert findings == {}


# ── Runtime 扫描测试 ──


class TestScanRuntime:
    def test_empty_runtime_returns_empty(self, tmp_path):
        findings = scan_runtime(tmp_path / "empty_runtime")
        assert findings == {}

    def test_existing_yaml_overrides(self, legacy_project_with_runtime_config):
        findings = scan_runtime(legacy_project_with_runtime_config["runtime_dir"])
        assert findings["app_title"][0] == "已有平台"
        assert findings["app_title"][1] == CONF_HIGH
        assert findings["theme_primary"][0] == "#FF0000"

    def test_legacy_login_notice_text_maps_to_login_notice(self, tmp_path):
        runtime = tmp_path / "runtime"
        config_dir = runtime / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "ui-branding.yaml").write_text(
            yaml.dump({"login_notice_text": "旧版登录提示"}, allow_unicode=True),
            encoding="utf-8",
        )

        findings = scan_runtime(runtime)

        assert findings["login_notice"] == ("旧版登录提示", CONF_HIGH)

    def test_existing_branding_assets(self, tmp_path):
        runtime = tmp_path / "runtime"
        branding_dir = runtime / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "logo.png").write_bytes(b'\x89PNG' + b'\x00' * 50)
        (branding_dir / "favicon.ico").write_bytes(b'\x00\x00\x01\x00' + b'\x00' * 50)
        findings = scan_runtime(runtime)
        assert "favicon_file" in findings
        assert findings["favicon_file"][0] == "favicon.ico"

    def test_generic_logo_maps_to_login_not_topbar(self, tmp_path):
        """BUG-032 regression: 通用 logo 应映射到 login_logo_file，而非 topbar_logo_file。"""
        runtime = tmp_path / "runtime"
        branding_dir = runtime / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "logo.png").write_bytes(b'\x89PNG' + b'\x00' * 50)
        findings = scan_runtime(runtime)
        assert "login_logo_file" in findings
        assert findings["login_logo_file"][0] == "logo.png"
        # 通用 logo 作为 topbar 回退，置信度应为 LOW
        assert "topbar_logo_file" in findings
        assert findings["topbar_logo_file"][0] == "logo.png"
        assert findings["topbar_logo_file"][1] == CONF_LOW

    def test_topbar_explicit_name_maps_to_topbar_only(self, tmp_path):
        """显式 topbar 命名只映射到 topbar_logo_file。"""
        runtime = tmp_path / "runtime"
        branding_dir = runtime / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "topbar-logo.svg").write_bytes(b"<svg/>")
        findings = scan_runtime(runtime)
        assert "topbar_logo_file" in findings
        assert findings["topbar_logo_file"][0] == "topbar-logo.svg"
        # 不应映射到 login_logo_file
        assert "login_logo_file" not in findings

    def test_login_brand_explicit_name_maps_to_login_only(self, tmp_path):
        """显式 login/brand 命名只映射到 login_logo_file。"""
        runtime = tmp_path / "runtime"
        branding_dir = runtime / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "brand-logo.png").write_bytes(b'\x89PNG' + b'\x00' * 50)
        findings = scan_runtime(runtime)
        assert "login_logo_file" in findings
        assert findings["login_logo_file"][0] == "brand-logo.png"
        # 不应映射到 topbar_logo_file
        assert "topbar_logo_file" not in findings

    def test_mixed_logos_mapped_correctly(self, tmp_path):
        """login logo 和 topbar logo 同时存在时，各自映射到对应字段。"""
        runtime = tmp_path / "runtime"
        branding_dir = runtime / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "brand-logo.png").write_bytes(b'\x89PNG' + b'\x00' * 50)
        (branding_dir / "topbar-logo.svg").write_bytes(b"<svg/>")
        findings = scan_runtime(runtime)
        assert findings["login_logo_file"][0] == "brand-logo.png"
        assert findings["topbar_logo_file"][0] == "topbar-logo.svg"


# ── 合并测试 ──


class TestMergeFindings:
    def test_runtime_overrides_code(self):
        code = {"app_title": ("CodeTitle", CONF_HIGH)}
        css = {}
        runtime = {"app_title": ("RuntimeTitle", CONF_HIGH)}
        merged = merge_findings(code, css, runtime)
        assert merged["app_title"][0] == "RuntimeTitle"

    def test_code_overrides_css(self):
        code = {"theme_primary": ("#CodeHex", CONF_HIGH)}
        css = {"theme_primary": ("#CSSHex", CONF_HIGH)}
        runtime = {}
        merged = merge_findings(code, css, runtime)
        assert merged["theme_primary"][0] == "#CodeHex"

    def test_high_conf_overrides_low(self):
        code = {"app_title": ("LowTitle", CONF_LOW)}
        runtime = {"app_title": ("HighTitle", CONF_HIGH)}
        merged = merge_findings(code, {}, runtime)
        assert merged["app_title"][0] == "HighTitle"


# ── YAML 生成测试 ──


class TestBuildBrandingYaml:
    def test_generates_complete_config(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        css = scan_css(legacy_project["static_dir"] / "css" / "main.css")
        merged = merge_findings(findings, css, {})
        config = build_branding_yaml(merged)
        assert config["app_title"] == "我的产品平台"
        assert config["login_subtitle"] == "智能协作工作流平台"
        assert config["theme"]["primary"] == "#1A73E8"

    def test_empty_findings_generates_defaults(self):
        config = build_branding_yaml({})
        assert "theme" in config
        # 新版 build_branding_yaml 默认值为空字符串，accent 不再硬编码
        assert config["theme"]["accent"] == ""


# ── 报告生成测试 ──


class TestBuildScanReport:
    def test_report_contains_table(self, legacy_project):
        findings = scan_html(legacy_project["static_dir"] / "index.html")
        css = scan_css(legacy_project["static_dir"] / "css" / "main.css")
        merged = merge_findings(findings, css, {})
        config = build_branding_yaml(merged)
        report = build_scan_report(merged, config)
        assert "扫描报告" in report
        assert "| 字段 |" in report
        assert "我的产品平台" in report


# ── 完整迁移流程测试 ──


class TestMigrateFlow:
    def test_full_migrate_creates_yaml_and_report(self, legacy_project):
        target = legacy_project["tmp_path"] / "target_runtime"
        result = migrate(
            legacy_code_dir=legacy_project["static_dir"],
            legacy_runtime_dir=legacy_project["runtime_dir"],
            target_runtime_dir=target,
        )
        yaml_path = Path(result["yaml_path"])
        assert yaml_path.exists()
        report_path = Path(result["report_path"])
        assert report_path.exists()

        # YAML 内容正确
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["app_title"] == "我的产品平台"
        assert data["theme"]["primary"] == "#1A73E8"

    def test_migrate_skips_existing_yaml_without_force(self, legacy_project):
        target = legacy_project["tmp_path"] / "target_runtime"
        config_dir = target / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "ui-branding.yaml").write_text("app_title: ExistingConfig\n", encoding="utf-8")

        result = migrate(
            legacy_code_dir=legacy_project["static_dir"],
            legacy_runtime_dir=legacy_project["runtime_dir"],
            target_runtime_dir=target,
            force=False,
        )
        # YAML 不被覆盖
        data = yaml.safe_load((target / "config" / "ui-branding.yaml").read_text(encoding="utf-8"))
        assert data["app_title"] == "ExistingConfig"

    def test_migrate_overwrites_with_force(self, legacy_project):
        target = legacy_project["tmp_path"] / "target_runtime"
        config_dir = target / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "ui-branding.yaml").write_text("app_title: Old\n", encoding="utf-8")

        result = migrate(
            legacy_code_dir=legacy_project["static_dir"],
            legacy_runtime_dir=legacy_project["runtime_dir"],
            target_runtime_dir=target,
            force=True,
        )
        data = yaml.safe_load((target / "config" / "ui-branding.yaml").read_text(encoding="utf-8"))
        assert data["app_title"] == "我的产品平台"

    def test_migrate_copies_favicon(self, legacy_project):
        target = legacy_project["tmp_path"] / "target_runtime"
        result = migrate(
            legacy_code_dir=legacy_project["static_dir"],
            legacy_runtime_dir=legacy_project["runtime_dir"],
            target_runtime_dir=target,
        )
        branding_dir = target / "assets" / "branding"
        assert branding_dir.exists()
        # favicon.svg should be copied
        assert (branding_dir / "favicon.svg").exists()

    def test_migrate_copies_logo(self, legacy_project):
        target = legacy_project["tmp_path"] / "target_runtime"
        result = migrate(
            legacy_code_dir=legacy_project["static_dir"],
            legacy_runtime_dir=legacy_project["runtime_dir"],
            target_runtime_dir=target,
        )
        branding_dir = target / "assets" / "branding"
        assert (branding_dir / "logo.png").exists()

    def test_migrate_writes_discovered_logo_to_yaml(self, legacy_project):
        """BUG-026 regression: discovered logo should appear in yaml config."""
        target = legacy_project["tmp_path"] / "target_runtime"
        result = migrate(
            legacy_code_dir=legacy_project["static_dir"],
            legacy_runtime_dir=legacy_project["runtime_dir"],
            target_runtime_dir=target,
        )
        data = yaml.safe_load(Path(result["yaml_path"]).read_text(encoding="utf-8"))
        # discover_assets finds generic logo.png → default to login_logo only
        assert data.get("login_logo") == "logo.png"
        assert not data.get("topbar_logo")

    def test_runtime_yaml_takes_priority(self, legacy_project_with_runtime_config):
        target = legacy_project_with_runtime_config["tmp_path"] / "target_runtime"
        result = migrate(
            legacy_code_dir=legacy_project_with_runtime_config["static_dir"],
            legacy_runtime_dir=legacy_project_with_runtime_config["runtime_dir"],
            target_runtime_dir=target,
            force=True,
        )
        data = yaml.safe_load(Path(result["yaml_path"]).read_text(encoding="utf-8"))
        # runtime 已有配置 "已有平台"，优先于代码扫描的 "我的产品平台"
        assert data["app_title"] == "已有平台"
        assert data["theme"]["primary"] == "#FF0000"

    def test_no_dangerous_paths_in_yaml(self, legacy_project):
        target = legacy_project["tmp_path"] / "target_runtime"
        result = migrate(
            legacy_code_dir=legacy_project["static_dir"],
            legacy_runtime_dir=legacy_project["runtime_dir"],
            target_runtime_dir=target,
        )
        data = yaml.safe_load(Path(result["yaml_path"]).read_text(encoding="utf-8"))
        for key in ("favicon", "login_logo", "topbar_logo"):
            val = data.get(key, "")
            if val:
                assert not val.startswith("/")
                assert not val.startswith("http")
                assert ".." not in val


# ── BUG-016: 资产路径安全回归 ──


class TestAssetPathSafeValidation:
    def test_external_url_rejected(self):
        assert _validate_asset_path_safe("https://example.com/favicon.svg") is None

    def test_http_url_rejected(self):
        assert _validate_asset_path_safe("http://cdn.example.com/logo.png") is None

    def test_protocol_relative_url_rejected(self):
        assert _validate_asset_path_safe("//cdn.example.com/logo.png") is None

    def test_url_slash_prefix_accepted_after_strip(self):
        # /favicon.svg 是 HTML 中常见格式，lstrip 后为单段文件名
        assert _validate_asset_path_safe("/favicon.svg") == "favicon.svg"

    def test_multi_segment_absolute_path_rejected(self):
        """BUG-018 regression: /etc/passwd → etc/passwd must be rejected."""
        assert _validate_asset_path_safe("/etc/passwd") is None

    def test_multi_segment_leading_slash_rejected(self):
        """BUG-018 regression: /icons/logo.svg still has / after strip → reject."""
        assert _validate_asset_path_safe("/icons/logo.svg") is None

    def test_parent_traversal_rejected(self):
        assert _validate_asset_path_safe("../../secret.svg") is None

    def test_dotdot_in_subpath_rejected(self):
        assert _validate_asset_path_safe("sub/../../secret.svg") is None

    def test_simple_filename_passes(self):
        assert _validate_asset_path_safe("favicon.svg") == "favicon.svg"

    def test_relative_subdir_passes(self):
        assert _validate_asset_path_safe("icons/logo.png") == "icons/logo.png"

    def test_leading_slash_stripped(self):
        assert _validate_asset_path_safe("/favicon.svg") == "favicon.svg"

    def test_empty_string_returns_none(self):
        assert _validate_asset_path_safe("") is None


class TestBuildBrandingYamlPathSafety:
    def test_external_url_favicon_rejected(self):
        """BUG-016 regression: https:// favicon must not appear in yaml."""
        merged = {"favicon_file": ("https://example.com/favicon.svg", CONF_HIGH)}
        config = build_branding_yaml(merged)
        assert config["favicon"] == ""

    def test_traversal_logo_rejected(self):
        """BUG-016 regression: .. traversal path must not appear in yaml."""
        merged = {"login_logo_file": ("../secret.svg", CONF_HIGH)}
        config = build_branding_yaml(merged)
        assert config["login_logo"] == ""

    def test_traversal_path_rejected(self):
        """BUG-016 regression: .. traversal must not appear in yaml."""
        merged = {"topbar_logo_file": ("../../secret.svg", CONF_HIGH)}
        config = build_branding_yaml(merged)
        assert config["topbar_logo"] == ""

    def test_valid_filename_accepted(self):
        merged = {"favicon_file": ("favicon.svg", CONF_HIGH)}
        config = build_branding_yaml(merged)
        assert config["favicon"] == "favicon.svg"

    def test_leading_slash_still_accepted_after_strip(self):
        merged = {"favicon_file": ("/favicon.svg", CONF_HIGH)}
        config = build_branding_yaml(merged)
        assert config["favicon"] == "favicon.svg"

    def test_multi_segment_absolute_path_rejected_in_yaml(self):
        """BUG-018 regression: /etc/passwd must not appear in yaml."""
        merged = {"favicon_file": ("/etc/passwd", CONF_HIGH)}
        config = build_branding_yaml(merged)
        assert config["favicon"] == ""

    def test_multi_segment_leading_slash_rejected_in_yaml(self):
        """BUG-018 regression: /icons/logo.svg must not appear in yaml."""
        merged = {"login_logo_file": ("/icons/logo.svg", CONF_HIGH)}
        config = build_branding_yaml(merged)
        assert config["login_logo"] == ""


class TestCopyAssetsPathSafety:
    def test_external_url_favicon_not_copied(self, legacy_project):
        """BUG-016 regression: copy_assets must not try to fetch external URLs."""
        merged = {"favicon_file": ("https://example.com/favicon.svg", CONF_HIGH)}
        target = legacy_project["tmp_path"] / "target"
        copied = copy_assets(
            legacy_project["project_dir"],
            legacy_project["static_dir"],
            legacy_project["runtime_dir"],
            target,
            merged,
            {},
        )
        # No favicon copied from external URL
        assert "favicon.svg" not in copied

    def test_traversal_asset_not_copied(self, legacy_project):
        """BUG-016 regression: .. path must not write outside branding dir."""
        merged = {"favicon_file": ("../../etc/passwd", CONF_HIGH)}
        target = legacy_project["tmp_path"] / "target"
        copied = copy_assets(
            legacy_project["project_dir"],
            legacy_project["static_dir"],
            legacy_project["runtime_dir"],
            target,
            merged,
            {},
        )
        assert len(copied) == 0
        # Nothing written outside branding dir
        assert not (target / "etc").exists()


# ── BUG-017: 输入目录自动发现 ──


class TestDiscoverStaticDir:
    def test_direct_static_dir(self, legacy_project):
        result = _discover_static_dir(legacy_project["static_dir"])
        assert result == legacy_project["static_dir"]

    def test_project_root_auto_discover(self, legacy_project):
        """BUG-017 regression: 传项目根目录应自动找到 src/static。"""
        # 构造项目根目录结构
        root = legacy_project["tmp_path"] / "old_project"
        src_static = root / "src" / "static"
        src_static.mkdir(parents=True)
        (src_static / "index.html").write_text("<html><title>OldProject</title></html>", encoding="utf-8")
        result = _discover_static_dir(root)
        assert result == src_static

    def test_project_root_with_static_dir(self, tmp_path):
        """BUG-017 regression: 传项目根目录且 static/ 下有 index.html。"""
        root = tmp_path / "project2"
        static = root / "static"
        static.mkdir(parents=True)
        (static / "index.html").write_text("<html><title>Proj2</title></html>", encoding="utf-8")
        result = _discover_static_dir(root)
        assert result == static

    def test_project_root_with_no_static_returns_root(self, tmp_path):
        """无前端文件时回退到传入目录。"""
        root = tmp_path / "bare_project"
        root.mkdir()
        result = _discover_static_dir(root)
        assert result == root

    def test_full_migrate_from_project_root(self, legacy_project):
        """BUG-017 regression: migrate() 接受项目根目录并自动发现 static。"""
        # 把 legacy static 放到 old_project/src/static/ 下
        root = legacy_project["tmp_path"] / "old_project"
        src_static = root / "src" / "static"
        src_static.mkdir(parents=True, exist_ok=True)
        # 复制文件到 src/static
        for f in legacy_project["static_dir"].iterdir():
            if f.is_file():
                shutil.copy2(f, src_static / f.name)
        css_src = legacy_project["static_dir"] / "css"
        css_dest = src_static / "css"
        css_dest.mkdir(exist_ok=True)
        for f in css_src.iterdir():
            if f.is_file():
                shutil.copy2(f, css_dest / f.name)

        target = legacy_project["tmp_path"] / "target_runtime"
        result = migrate(
            legacy_code_dir=root,  # 传项目根目录
            legacy_runtime_dir=legacy_project["runtime_dir"],
            target_runtime_dir=target,
        )
        data = yaml.safe_load(Path(result["yaml_path"]).read_text(encoding="utf-8"))
        assert data["app_title"] == "我的产品平台"


# ── BUG-019: 嵌套资产路径 mkdir ──


class TestCopyAssetsNestedPath:
    def test_nested_favicon_creates_parent_dirs(self, tmp_path):
        """BUG-019 regression: icons/favicon.svg 需要先创建 icons/ 子目录。"""
        static_dir = tmp_path / "static"
        icons_dir = static_dir / "icons"
        icons_dir.mkdir(parents=True)
        (icons_dir / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")

        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()

        target_dir = tmp_path / "target"
        merged = {"favicon_file": ("icons/favicon.svg", CONF_HIGH)}
        copied = copy_assets(tmp_path, static_dir, runtime_dir, target_dir, merged, {})

        assert "icons/favicon.svg" in copied
        assert (target_dir / "assets" / "branding" / "icons" / "favicon.svg").exists()

    def test_nested_logo_creates_parent_dirs(self, tmp_path):
        """BUG-019 regression: nested logo path needs parent dirs created."""
        static_dir = tmp_path / "static"
        logos_dir = static_dir / "logos"
        logos_dir.mkdir(parents=True)
        (logos_dir / "brand-logo.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 50)

        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()

        target_dir = tmp_path / "target"
        merged = {"login_logo_file": ("brand-logo.png", CONF_MEDIUM)}
        discovered = {"logo_file": (logos_dir / "brand-logo.png", CONF_MEDIUM)}
        copied = copy_assets(tmp_path, static_dir, runtime_dir, target_dir, merged, discovered)

        assert "brand-logo.png" in copied
        # Logo goes to branding root (uses src_path.name, not nested path)
        assert (target_dir / "assets" / "branding" / "brand-logo.png").exists()


# ── P3.6 三级分类 ──


class TestFieldClassification:
    def test_standard_fields_are_auto(self):
        assert classify_field("app_title") == CAT_AUTO
        assert classify_field("login_title") == CAT_AUTO
        assert classify_field("topbar_title") == CAT_AUTO
        assert classify_field("theme_primary") == CAT_AUTO
        assert classify_field("favicon_file") == CAT_AUTO
        assert classify_field("login_logo_file") == CAT_AUTO

    def test_uncertain_fields_are_confirm(self):
        assert classify_field("theme_primary_svg") == CAT_CONFIRM
        assert classify_field("login_gradient_colors") == CAT_CONFIRM
        assert classify_field("logo_file") == CAT_CONFIRM

    def test_unknown_fields_are_out_of_scope(self):
        assert classify_field("asset_candidate") == CAT_OUT_OF_SCOPE
        assert classify_field("random_unknown_field") == CAT_OUT_OF_SCOPE

    def test_build_branding_yaml_only_includes_auto_fields(self):
        merged = {
            "app_title": ("测试标题", CONF_HIGH),
            "theme_primary_svg": ("#ABCDEF", CONF_MEDIUM),  # confirm — 不写入
            "asset_candidate": ("random.png", CONF_LOW),  # out_of_scope — 不写入
        }
        config = build_branding_yaml(merged)
        assert config["app_title"] == "测试标题"
        # confirm 字段不能自动写入，必须留在报告中人工确认
        assert config["theme"]["primary"] == ""
        # out_of_scope 不映射到任何标准字段
        assert config["login_logo"] == ""
        assert config["topbar_logo"] == ""


# ── P3.6 scan/plan/apply 模式 ──


class TestScanMode:
    def test_scan_does_not_write_files(self, legacy_project):
        result = scan(
            legacy_project["project_dir"],
            legacy_project["runtime_dir"],
        )
        assert "merged_findings" in result
        assert "classified" in result
        # scan 不应创建任何文件
        target_config = legacy_project["tmp_path"] / "target" / "config" / "ui-branding.yaml"
        assert not target_config.exists()

    def test_scan_classifies_all_fields(self, legacy_project):
        result = scan(
            legacy_project["project_dir"],
            legacy_project["runtime_dir"],
        )
        classified = result["classified"]
        for key, info in classified.items():
            assert info["category"] in (CAT_AUTO, CAT_CONFIRM, CAT_OUT_OF_SCOPE)


class TestPlanMode:
    def test_plan_writes_report_but_not_yaml(self, legacy_project):
        target_dir = legacy_project["tmp_path"] / "target"
        result = plan(
            legacy_project["project_dir"],
            legacy_project["runtime_dir"],
            target_dir,
        )
        # plan 只写扫描报告，不写 yaml
        report_path = target_dir / "config" / "ui-branding.scan-report.md"
        assert report_path.exists()
        yaml_path = target_dir / "config" / "ui-branding.yaml"
        assert not yaml_path.exists()

    def test_plan_report_contains_classification(self, legacy_project):
        target_dir = legacy_project["tmp_path"] / "target"
        plan(
            legacy_project["project_dir"],
            legacy_project["runtime_dir"],
            target_dir,
        )
        report = (target_dir / "config" / "ui-branding.scan-report.md").read_text(encoding="utf-8")
        assert "auto" in report
        assert "confirm" in report or "需人工确认" in report
        assert "out_of_scope" in report or "超出范围" in report


class TestApplyMode:
    def test_apply_writes_yaml_and_assets(self, legacy_project):
        target_dir = legacy_project["tmp_path"] / "target"
        result = apply(
            legacy_project["project_dir"],
            legacy_project["runtime_dir"],
            target_dir,
        )
        yaml_path = target_dir / "config" / "ui-branding.yaml"
        assert yaml_path.exists()
        report_path = target_dir / "config" / "ui-branding.scan-report.md"
        assert report_path.exists()

    def test_apply_skip_existing_yaml_without_force(self, legacy_project):
        target_dir = legacy_project["tmp_path"] / "target"
        # 先手动创建 yaml
        config_dir = target_dir / "config"
        config_dir.mkdir(parents=True)
        yaml_file = config_dir / "ui-branding.yaml"
        yaml_file.write_text("app_title: existing\n", encoding="utf-8")

        result = apply(
            legacy_project["project_dir"],
            legacy_project["runtime_dir"],
            target_dir,
        )
        # yaml 应保持原样
        content = yaml_file.read_text(encoding="utf-8")
        assert "existing" in content

    def test_apply_force_overwrites_existing_yaml(self, legacy_project):
        target_dir = legacy_project["tmp_path"] / "target"
        config_dir = target_dir / "config"
        config_dir.mkdir(parents=True)
        yaml_file = config_dir / "ui-branding.yaml"
        yaml_file.write_text("app_title: old\n", encoding="utf-8")

        result = apply(
            legacy_project["project_dir"],
            legacy_project["runtime_dir"],
            target_dir,
            force=True,
        )
        content = yaml_file.read_text(encoding="utf-8")
        assert "old" not in content

    def test_apply_does_not_write_low_confidence_project_root_logo(self, tmp_path):
        """assets/dist/public 扩展扫描结果为低置信，只进报告，不直接进入 apply。"""
        legacy_dir = tmp_path / "legacy"
        static_dir = legacy_dir / "src" / "static"
        static_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html><title>旧项目</title></html>", encoding="utf-8")

        assets_dir = legacy_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "ProjectLogo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        runtime_dir = tmp_path / "old_runtime"
        runtime_dir.mkdir()
        target_dir = tmp_path / "target"

        result = apply(legacy_dir, runtime_dir, target_dir)
        data = yaml.safe_load((target_dir / "config" / "ui-branding.yaml").read_text(encoding="utf-8"))

        assert "login_logo" not in data
        assert "topbar_logo" not in data
        assert "ProjectLogo.png" not in result["copied_assets"]
        assert not (target_dir / "assets" / "branding" / "ProjectLogo.png").exists()


# ── P3.6 写入路径白名单 ──


class TestWritePathWhitelist:
    def test_config_dir_allowed(self, tmp_path):
        target = tmp_path / "runtime"
        write_path = target / "config" / "ui-branding.yaml"
        assert _check_write_path_allowed(target, write_path) is True

    def test_branding_assets_dir_allowed(self, tmp_path):
        target = tmp_path / "runtime"
        write_path = target / "assets" / "branding" / "logo.png"
        assert _check_write_path_allowed(target, write_path) is True

    def test_data_dir_not_allowed(self, tmp_path):
        target = tmp_path / "runtime"
        write_path = target / "data" / "app.db"
        assert _check_write_path_allowed(target, write_path) is False

    def test_logs_dir_not_allowed(self, tmp_path):
        target = tmp_path / "runtime"
        write_path = target / "logs" / "app.log"
        assert _check_write_path_allowed(target, write_path) is False

    def test_uploads_dir_not_allowed(self, tmp_path):
        target = tmp_path / "runtime"
        write_path = target / "uploads" / "review_uploads" / "doc.docx"
        assert _check_write_path_allowed(target, write_path) is False


# ── P3.6 资产发现范围扩展 ──


class TestDiscoverAssetsExpanded:
    def test_logo_found_in_project_assets_dir(self, tmp_path):
        """BUG from deployment experiment: logo in project root assets/ dir should be discovered."""
        static_dir = tmp_path / "src" / "static"
        static_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        (assets_dir / "ProjectLogo.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 50)

        result = discover_assets(tmp_path, static_dir)
        assert "logo_file" in result
        assert result["logo_file"][0].name == "ProjectLogo.png"

    def test_logo_found_in_dist_dir(self, tmp_path):
        static_dir = tmp_path / "src" / "static"
        static_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "MyBrand.logo.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 50)

        result = discover_assets(tmp_path, static_dir)
        assert "logo_file" in result

    def test_no_duplicate_discovery_from_static_equals_project(self, tmp_path):
        """When static_dir parent has no assets/dist/public, discover_assets only searches static."""
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        result = discover_assets(tmp_path, static_dir)
        # No extra dirs searched since project has no assets/dist/public
        assert "logo_file" not in result
