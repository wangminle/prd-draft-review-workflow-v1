"""P3.5 — 品牌与本地个性化配置自动化测试"""

import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "src/static/css/main.css").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "src/static/js/auth.js").read_text(encoding="utf-8")

from app.services.branding_config import (
    DEFAULT_BRANDING,
    get_branding_config,
    _merge_branding,
    _validate_asset_path,
    _load_runtime_branding,
    resolve_branding_asset,
    ensure_branding_dirs,
)


# ── P3.1 配置结构与默认值 ──


class TestDefaultBranding:
    def test_default_has_required_fields(self):
        required = ("app_title", "app_version", "login_title", "login_subtitle", "topbar_title",
                     "review_workspace_label", "admin_label", "login_notice")
        for key in required:
            assert key in DEFAULT_BRANDING
        for key in ("app_title", "app_version", "login_title", "login_subtitle", "topbar_title",
                    "review_workspace_label", "admin_label"):
            assert DEFAULT_BRANDING[key]

    def test_default_theme_has_three_colors(self):
        theme = DEFAULT_BRANDING["theme"]
        assert "primary" in theme
        assert "primary_hover" in theme
        assert "accent" in theme

    def test_default_logos_are_empty(self):
        assert DEFAULT_BRANDING["login_logo"] == ""
        assert DEFAULT_BRANDING["topbar_logo"] == ""
        assert DEFAULT_BRANDING["favicon"] == ""


# ── P3.1 路径安全 ──


class TestAssetPathValidation:
    def test_simple_filename_passes(self):
        assert _validate_asset_path("logo.png") == "logo.png"

    def test_relative_subdir_passes(self):
        assert _validate_asset_path("icons/logo.svg") == "icons/logo.svg"

    def test_absolute_path_rejected(self):
        assert _validate_asset_path("/etc/passwd") is None

    def test_parent_traversal_rejected(self):
        assert _validate_asset_path("../../etc/passwd") is None

    def test_dotdot_in_path_rejected(self):
        assert _validate_asset_path("sub/../../etc/passwd") is None

    def test_external_url_rejected(self):
        assert _validate_asset_path("https://evil.com/logo.png") is None

    def test_http_url_rejected(self):
        assert _validate_asset_path("http://evil.com/logo.png") is None

    def test_protocol_relative_url_rejected(self):
        assert _validate_asset_path("//evil.com/logo.png") is None

    def test_empty_string_returns_none(self):
        assert _validate_asset_path("") is None


# ── P3.1 配置合并 ──


class TestMergeBranding:
    def test_simple_string_override(self):
        result = _merge_branding(DEFAULT_BRANDING, {"app_title": "MyApp"})
        assert result["app_title"] == "MyApp"

    def test_empty_override_does_not_replace(self):
        result = _merge_branding(DEFAULT_BRANDING, {"app_title": ""})
        assert result["app_title"] == DEFAULT_BRANDING["app_title"]

    def test_theme_color_override(self):
        result = _merge_branding(DEFAULT_BRANDING, {"theme": {"primary": "#FF0000"}})
        assert result["theme"]["primary"] == "#FF0000"
        assert result["theme"]["primary_hover"] == DEFAULT_BRANDING["theme"]["primary_hover"]

    def test_invalid_asset_path_not_merged(self):
        result = _merge_branding(DEFAULT_BRANDING, {"login_logo": "/etc/passwd"})
        assert result["login_logo"] == ""

    def test_app_version_override(self):
        result = _merge_branding(DEFAULT_BRANDING, {"app_version": "1.0.0"})
        assert result["app_version"] == "1.0.0"

    def test_valid_asset_path_merged(self):
        result = _merge_branding(DEFAULT_BRANDING, {"login_logo": "logo.png"})
        assert result["login_logo"] == "logo.png"

    def test_invalid_asset_path_preserves_valid_base(self):
        """BUG-023 regression: invalid override should not clear valid base value."""
        base = dict(DEFAULT_BRANDING)
        base["login_logo"] = "logo.png"
        result = _merge_branding(base, {"login_logo": "https://evil.com/logo.png"})
        assert result["login_logo"] == "logo.png"  # preserved, not cleared


# ── P3.1 Runtime 配置加载 ──


class TestRuntimeBrandingLoad:
    def test_missing_yaml_returns_none(self, tmp_path):
        with patch("app.services.branding_config.runtime_path",
                   return_value=tmp_path / "config" / "ui-branding.yaml"):
            assert _load_runtime_branding() is None

    def test_valid_yaml_loads(self, tmp_path):
        yaml_path = tmp_path / "config" / "ui-branding.yaml"
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(yaml.dump({"app_title": "CustomApp"}), encoding="utf-8")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _load_runtime_branding()
            assert result is not None
            assert result["app_title"] == "CustomApp"

    def test_invalid_yaml_returns_none(self, tmp_path):
        yaml_path = tmp_path / "config" / "ui-branding.yaml"
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text("not: a\nlist: here\n- item", encoding="utf-8")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            # yaml.safe_load returns a dict for this, it won't be None
            result = _load_runtime_branding()
            # just verify it doesn't crash


# ── P3.2 BrandingConfigService ──


class TestGetBrandingConfig:
    def test_defaults_only_when_no_overrides(self):
        with patch("app.services.branding_config._load_runtime_branding", return_value=None), \
             patch("app.services.branding_config._load_config_yaml_branding", return_value=None):
            config = get_branding_config()
            assert config["app_title"] == DEFAULT_BRANDING["app_title"]

    def test_runtime_overrides_default(self, tmp_path):
        yaml_content = {"app_title": "RuntimeApp", "theme": {"primary": "#AABBCC"}}
        with patch("app.services.branding_config._load_runtime_branding", return_value=yaml_content), \
             patch("app.services.branding_config._load_config_yaml_branding", return_value=None):
            config = get_branding_config()
            assert config["app_title"] == "RuntimeApp"
            assert config["theme"]["primary"] == "#AABBCC"

    def test_config_yaml_overrides_default(self):
        config_yaml = {"app_title": "ConfigApp"}
        with patch("app.services.branding_config._load_runtime_branding", return_value=None), \
             patch("app.services.branding_config._load_config_yaml_branding", return_value=config_yaml):
            config = get_branding_config()
            assert config["app_title"] == "ConfigApp"

    def test_runtime_overrides_config_yaml(self):
        config_yaml = {"app_title": "ConfigApp"}
        runtime_yaml = {"app_title": "RuntimeApp"}
        with patch("app.services.branding_config._load_runtime_branding", return_value=runtime_yaml), \
             patch("app.services.branding_config._load_config_yaml_branding", return_value=config_yaml):
            config = get_branding_config()
            assert config["app_title"] == "RuntimeApp"


# ── P3.2 API 集成测试 ──


class TestBrandingAPI:
    @pytest.mark.asyncio
    async def test_get_branding_returns_config(self):
        from httpx import AsyncClient, ASGITransport
        from main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/app/branding")
            assert resp.status_code == 200
            data = resp.json()
            assert "app_title" in data
            assert "app_version" in data
            assert "theme" in data
            assert "primary" in data["theme"]

    @pytest.mark.asyncio
    async def test_branding_asset_rejects_traversal(self):
        from httpx import AsyncClient, ASGITransport
        from main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/assets/branding/../etc/passwd")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_branding_asset_rejects_dot_prefix(self):
        from httpx import AsyncClient, ASGITransport
        from main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/assets/branding/.hidden")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_branding_asset_404_for_missing_file(self):
        from httpx import AsyncClient, ASGITransport
        from main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/assets/branding/nonexistent.png")
            assert resp.status_code == 404


# ── P3.3 前端契约测试 ──


class TestFrontendBrandingContract:
    def test_html_has_data_branding_login_title(self):
        assert 'data-branding="login-title"' in HTML

    def test_html_has_data_branding_login_subtitle(self):
        assert 'data-branding="login-subtitle"' in HTML

    def test_html_has_data_branding_login_notice(self):
        assert 'data-branding="login-notice"' in HTML

    def test_html_has_data_branding_login_logo(self):
        assert 'data-branding="login-logo"' in HTML

    def test_html_has_data_branding_topbar_logo(self):
        assert HTML.count('data-branding="topbar-logo"') >= 3

    def test_html_has_data_branding_review_workspace_label(self):
        assert 'data-branding="review-workspace-label"' in HTML

    def test_html_has_data_branding_topbar_title(self):
        assert 'data-branding="topbar-title"' in HTML

    def test_review_page_topbar_title_uses_topbar_branding(self):
        # Review page topbar title should use topbar-title (same as chat/admin)
        assert HTML.count('data-branding="topbar-title"') >= 3

    def test_html_has_data_branding_version(self):
        assert 'data-branding="app-version"' in HTML

    def test_html_has_data_branding_admin_label(self):
        assert 'data-branding="admin-label"' in HTML

    def test_html_has_data_branding_admin_badge(self):
        assert 'data-branding="admin-badge"' in HTML

    def test_html_has_id_page_title(self):
        assert 'id="page-title"' in HTML

    def test_html_has_id_favicon_link(self):
        assert 'id="favicon-link"' in HTML

    def test_html_has_id_theme_color_meta(self):
        assert 'id="theme-color-meta"' in HTML

    def test_css_has_color_brand_variable(self):
        assert "--color-brand:" in CSS

    def test_css_has_color_brand_hover_variable(self):
        assert "--color-brand-hover:" in CSS

    def test_css_has_topbar_version_style(self):
        assert ".topbar-version" in CSS

    def test_css_has_topbar_brand_text_style(self):
        assert ".topbar-brand-text" in CSS

    def test_auth_js_has_branding_object(self):
        assert "const Branding = {" in AUTH_JS

    def test_auth_js_has_branding_load(self):
        assert "async load()" in AUTH_JS

    def test_auth_js_has_branding_apply(self):
        assert "apply()" in AUTH_JS

    def test_auth_js_applies_theme_colors(self):
        assert "root.style.setProperty" in AUTH_JS
        assert "--color-brand" in AUTH_JS
        assert "--blue-6" in AUTH_JS

    def test_auth_js_applies_page_title(self):
        assert "document.title" in AUTH_JS

    def test_auth_js_applies_favicon(self):
        assert "favicon-link" in AUTH_JS

    def test_auth_js_applies_login_notice(self):
        assert "c.login_notice" in AUTH_JS
        assert "renderLoginNotice" in AUTH_JS
        assert "document.createElement('p')" in AUTH_JS
        assert "textContent" in AUTH_JS

    def test_auth_js_branding_on_window(self):
        assert "window.Branding = Branding;" in AUTH_JS

    def test_app_js_calls_branding_load(self):
        APP_JS = (ROOT / "src/static/js/app.js").read_text(encoding="utf-8")
        assert "Branding.load()" in APP_JS

    def test_auth_js_has_version_branding(self):
        assert "'app-version'" in AUTH_JS
        assert "c.app_version" in AUTH_JS
        # BUG-027 regression: version display must preserve "Ver." prefix
        assert "'Ver. '" in AUTH_JS

    def test_auth_js_has_review_workspace_label_mapping(self):
        """BUG-025 regression: review_workspace_label must be in textMap."""
        assert "'review-workspace-label'" in AUTH_JS
        assert "c.review_workspace_label" in AUTH_JS

    def test_example_yaml_exists(self):
        example = ROOT / "runtime/config/ui-branding.example.yaml"
        assert example.exists()

    def test_example_yaml_is_valid_yaml(self):
        example = ROOT / "runtime/config/ui-branding.example.yaml"
        data = yaml.safe_load(example.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "app_title" in data
        assert "theme" in data
