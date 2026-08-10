"""子路径部署 base path 注入测试

校验后端 _render_index 在子路径/根路径两种部署下，均向 index.html 注入正确的
window.__BASE_PATH__，使前端 api.js 的 _base 能显式拿到部署前缀（而非依赖
document.currentScript 的脆弱推导）。同时校验前端静态字符串的一致性。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
API_JS = (ROOT / "src/static/js/api.js").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "src/static/js/auth.js").read_text(encoding="utf-8")

from main import _render_index


# ── _render_index 纯函数：注入正确性 ──


def test_render_index_injects_subpath():
    html = _render_index("/prd-review")
    assert "<script>window.__BASE_PATH__='/prd-review';</script></head>" in html


def test_render_index_injects_empty_for_root():
    """根路径部署注入空串，前端 _base 得到 ''，行为与改造前一致。"""
    html = _render_index("")
    assert "<script>window.__BASE_PATH__='';</script></head>" in html


def test_render_index_normalizes_trailing_slash():
    html = _render_index("/prd-review/")
    assert "window.__BASE_PATH__='/prd-review';" in html
    # 不应出现双斜杠
    assert "//prd-review" not in html.split("window.__BASE_PATH__")[1].split("</script>")[0]


def test_render_index_normalizes_leading_slash_and_strips():
    """带空格或多余斜杠的输入也应归一化为单个前导斜杠。"""
    html = _render_index("  /prd-review/  ")
    assert "window.__BASE_PATH__='/prd-review';" in html


def test_render_index_preserves_rest_of_html():
    """注入仅替换第一处 </head>，其余 HTML 结构保持不变。"""
    html = _render_index("/prd-review")
    # 注入脚本只出现一次
    assert html.count("window.__BASE_PATH__") == 1
    # </head> 仍存在且只出现一次
    assert html.count("</head>") == 1
    # body 与脚本引用保持完整
    assert "<body>" in html
    assert "js/api.js" in html


# ── 前端 api.js：_base 优先读取注入值的契约 ──


def test_api_js_reads_injected_base_path():
    """api.js 的 _base 必须优先取 window.__BASE_PATH__（显式注入主路径）。"""
    assert "window.__BASE_PATH__" in API_JS


def test_api_js_no_hardcoded_absolute_api_urls():
    """前端不应出现 location.origin + '/api' 这类写死绝对地址的拼接。"""
    assert "location.origin" not in API_JS
    assert "location.host + " not in API_JS


# ── 前端 auth.js：branding 资产 URL 走 _url 前缀 ──


def test_auth_js_branding_urls_use_url_prefix():
    """logo/favicon 资产路径必须经 API._url 拼接部署前缀，不能裸赋相对路径。"""
    # favicon href 走 _url
    assert "API._url('/' + c.favicon)" in AUTH_JS
    # logo img src 走 _url
    assert "API._url('/' + url)" in AUTH_JS
