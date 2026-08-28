"""BUG-128/129 子路径前缀部署修复的契约测试。

覆盖：
- 前端 API._base 前缀推导机制存在，且无残留根绝对路径直接 fetch
- notification.js / auth.js 经 API._url 拼接
- 后端 branding 资产 URL 相对化、ROOT_PATH 支持、APP_VERSION 单源、
  NoCacheMiddleware 先剥离 root_path 再判断
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_JS = (ROOT / "src/static/js/api.js").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "src/static/js/auth.js").read_text(encoding="utf-8")
NOTIFICATION_JS = (ROOT / "src/static/js/notification.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
MAIN_PY = (ROOT / "src/main.py").read_text(encoding="utf-8")


def test_api_base_derives_from_injected_var_or_script_path():
    assert "window.__BASE_PATH__" in API_JS
    assert "document.currentScript" in API_JS
    assert "_url(path)" in API_JS


def test_no_bare_absolute_fetch_in_api_js():
    """api.js 中不允许再有绕过 _base/_url 的根绝对路径 fetch。"""
    bare = re.findall(r"fetch\((['`])/api/", API_JS)
    assert bare == [], f"残留根绝对路径 fetch: {bare}"


def test_eventsource_uses_base_prefix():
    assert "EventSource(`${url}?ticket=" in API_JS
    assert "this._url(`/api/review/projects/" in API_JS


def test_notification_and_branding_use_api_url():
    assert "API._url('/api/auth/sse-ticket')" in NOTIFICATION_JS
    assert "API._url(`/api/notifications/stream" in NOTIFICATION_JS
    assert "API._url('/api/app/branding')" in AUTH_JS


def test_branding_asset_url_is_relative():
    """branding 接口返回相对路径，子路径前缀下由浏览器相对页面解析。"""
    assert 'f"assets/branding/{val}"' in MAIN_PY
    assert 'f"/assets/branding/{val}"' not in MAIN_PY


def test_fastapi_supports_root_path_and_version_single_source():
    assert 'ROOT_PATH = os.environ.get("ROOT_PATH", "")' in MAIN_PY
    assert "root_path=ROOT_PATH" in MAIN_PY
    # 版本号唯一事实来源在根目录 VERSION 文件；main.py 从 app.version 导入
    assert "from app.version import APP_VERSION" in MAIN_PY
    assert '"version": APP_VERSION' in MAIN_PY
    assert "version=APP_VERSION" in MAIN_PY


def test_no_cache_middleware_strips_root_path():
    block = MAIN_PY.split("class NoCacheMiddleware", 1)[1].split("@asynccontextmanager", 1)[0]
    assert 'request.scope.get("root_path"' in block
    assert 'path.startswith("/api/")' in block


def test_index_html_scripts_cache_busted_for_prefix_fix():
    assert "?v=20260828-4" in INDEX_HTML
    assert "?v=20260828-3" not in INDEX_HTML
    assert "?v=20260828-1" not in INDEX_HTML
    assert "?v=20260827-1" not in INDEX_HTML
    assert "?v=20260731-1" not in INDEX_HTML
    assert "?v=20260611-1" not in INDEX_HTML
