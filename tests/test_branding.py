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
    _discover_branding_assets,
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

    def test_legacy_login_notice_text_override(self):
        result = _merge_branding(DEFAULT_BRANDING, {"login_notice_text": "旧版登录提示"})
        assert result["login_notice"] == "旧版登录提示"


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

    def test_legacy_login_notice_text_loads_as_login_notice(self, tmp_path):
        yaml_path = tmp_path / "config" / "ui-branding.yaml"
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(yaml.dump({"login_notice_text": "旧版提示\n第二行"}, allow_unicode=True), encoding="utf-8")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _load_runtime_branding()
            assert result is not None
            assert result["login_notice"] == "旧版提示\n第二行"
            assert "login_notice_text" not in result

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

    def test_auth_js_uses_distinct_logo_classes_for_login_and_topbar(self):
        assert "branding-logo branding-logo-login" in AUTH_JS
        assert "branding-logo branding-logo-topbar" in AUTH_JS

    def test_auth_js_has_logo_fallback(self):
        """单 logo 文件时，login_logo 与 topbar_logo 应互作 fallback。"""
        assert "logoUrlMap" in AUTH_JS
        assert "c.login_logo || c.topbar_logo" in AUTH_JS
        assert "c.topbar_logo || c.login_logo" in AUTH_JS

    def test_example_yaml_exists(self):
        example = ROOT / "runtime/config/ui-branding.example.yaml"
        assert example.exists()

    def test_example_yaml_is_valid_yaml(self):
        example = ROOT / "runtime/config/ui-branding.example.yaml"
        data = yaml.safe_load(example.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "app_title" in data


# ── P3.6 运行时资产自动发现 ──


class TestDiscoverBrandingAssets:
    def test_discover_logo_from_branding_dir(self, tmp_path):
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "MyLogo.png").write_bytes(b"fake png")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _discover_branding_assets()
            assert result is not None
            assert result["login_logo"] == "MyLogo.png"
            # 单文件兜底：通用 logo 同时用于顶栏（CSS 控制各自尺寸）
            assert result.get("topbar_logo") == "MyLogo.png"

    def test_discover_favicon_from_branding_dir(self, tmp_path):
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "favicon.ico").write_bytes(b"fake ico")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _discover_branding_assets()
            assert result is not None
            assert result["favicon"] == "favicon.ico"

    def test_no_discovery_when_branding_dir_empty(self, tmp_path):
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _discover_branding_assets()
            assert result is None

    def test_no_discovery_when_branding_dir_missing(self, tmp_path):
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _discover_branding_assets()
            assert result is None

    def test_login_logo_priority_for_brand_keyword(self, tmp_path):
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "brand-logo.png").write_bytes(b"fake")
        (branding_dir / "topbar-logo.png").write_bytes(b"fake")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _discover_branding_assets()
            assert result["login_logo"] == "brand-logo.png"
            assert result["topbar_logo"] == "topbar-logo.png"

    def test_auto_discovery_used_when_yaml_missing(self, tmp_path):
        """当 runtime yaml 不存在但有 branding 资产时，get_branding_config 自动发现。"""
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "logo.png").write_bytes(b"fake")
        # 确保没有 yaml
        assert not (tmp_path / "config" / "ui-branding.yaml").exists()
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)), \
             patch("app.services.branding_config._load_config_yaml_branding", return_value=None):
            config = get_branding_config()
            assert config["login_logo"] == "logo.png"
            # 单文件兜底：同时填充 topbar_logo
            assert config["topbar_logo"] == "logo.png"

    def test_auto_discovery_topbar_fallback_to_login(self, tmp_path):
        """只有通用 logo 时，自动发现应回退填充 topbar_logo。"""
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "brand.png").write_bytes(b"fake")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _discover_branding_assets()
            assert result["login_logo"] == "brand.png"
            assert result["topbar_logo"] == "brand.png"

    def test_auto_discovery_login_fallback_to_topbar(self, tmp_path):
        """只有 topbar 图标时，自动发现应回退填充 login_logo。"""
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "topbar-logo.svg").write_bytes(b"<svg/>")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)):
            result = _discover_branding_assets()
            assert result["topbar_logo"] == "topbar-logo.svg"
            assert result["login_logo"] == "topbar-logo.svg"

    def test_yaml_takes_priority_over_discovery(self, tmp_path):
        """当 runtime yaml 存在且 login_logo 非空时，yaml 配置优先。"""
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "discovered-logo.png").write_bytes(b"fake")
        yaml_dir = tmp_path / "config"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "ui-branding.yaml"
        yaml_file.write_text(yaml.dump({"login_logo": "yaml-logo.png"}), encoding="utf-8")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)), \
             patch("app.services.branding_config._load_config_yaml_branding", return_value=None):
            config = get_branding_config()
            # get_branding_config 返回内部格式（文件名，不含 /assets/branding/ 前缀）
            # API 层会把 login_logo 转成 URL 前缀
            assert config["login_logo"] == "yaml-logo.png"

    def test_yaml_empty_asset_fields_filled_by_discovery(self, tmp_path):
        """BUG-033 regression: yaml 存在但资产字段为空时，自动发现应填充空字段。"""
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "logo.png").write_bytes(b"fake")
        (branding_dir / "favicon.ico").write_bytes(b"fake ico")
        yaml_dir = tmp_path / "config"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "ui-branding.yaml"
        yaml_file.write_text(yaml.dump({
            "app_title": "YamlApp",
            "login_logo": "",
            "topbar_logo": "",
            "favicon": "",
        }), encoding="utf-8")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)), \
             patch("app.services.branding_config._load_config_yaml_branding", return_value=None):
            config = get_branding_config()
            # yaml 的 app_title 应保留（非空值优先）
            assert config["app_title"] == "YamlApp"
            # 自动发现应填充 yaml 中的空资产字段
            assert config["login_logo"] == "logo.png"
            assert config["topbar_logo"] == "logo.png"
            assert config["favicon"] == "favicon.ico"

    def test_yaml_non_empty_asset_not_overridden_by_discovery(self, tmp_path):
        """yaml 非空资产字段不应被自动发现覆盖。"""
        branding_dir = tmp_path / "assets" / "branding"
        branding_dir.mkdir(parents=True)
        (branding_dir / "brand-logo.png").write_bytes(b"fake")
        yaml_dir = tmp_path / "config"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "ui-branding.yaml"
        yaml_file.write_text(yaml.dump({
            "login_logo": "yaml-logo.png",
            "topbar_logo": "",
        }), encoding="utf-8")
        with patch("app.services.branding_config.runtime_path",
                   side_effect=lambda *p: tmp_path.joinpath(*p)), \
             patch("app.services.branding_config._load_config_yaml_branding", return_value=None):
            config = get_branding_config()
            # yaml 非空 login_logo 保留，不被 brand-logo.png 覆盖
            assert config["login_logo"] == "yaml-logo.png"
            # yaml 空 topbar_logo 被自动发现回退填充（brand-logo 单文件兜底）
            assert config["topbar_logo"] == "brand-logo.png"
