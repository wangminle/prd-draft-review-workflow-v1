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
    _validate_asset_path_safe,
    _discover_static_dir,
    CONF_HIGH,
    CONF_MEDIUM,
    CONF_LOW,
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

    def test_existing_branding_assets(self, tmp_path):
        runtime = tmp_path / "runtime"
        branding_dir = runtime / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "logo.png").write_bytes(b'\x89PNG' + b'\x00' * 50)
        (branding_dir / "favicon.ico").write_bytes(b'\x00\x00\x01\x00' + b'\x00' * 50)
        findings = scan_runtime(runtime)
        assert "favicon_file" in findings
        assert findings["favicon_file"][0] == "favicon.ico"


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
        assert config["theme"]["accent"] == "#23C343"


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
        # discover_assets finds logo.png → should be in login_logo and topbar_logo
        assert data.get("login_logo") == "logo.png" or data.get("topbar_logo") == "logo.png"

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
        copied = copy_assets(static_dir, runtime_dir, target_dir, merged, {})

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
        discovered = {"logo_file": (logos_dir / "brand-logo.png", CONF_MEDIUM)}
        copied = copy_assets(static_dir, runtime_dir, target_dir, {}, discovered)

        assert "brand-logo.png" in copied
        # Logo goes to branding root (uses src_path.name, not nested path)
        assert (target_dir / "assets" / "branding" / "brand-logo.png").exists()