"""BUG-111 — index.html 静态资源须用相对路径，以便 LWA 别名/子路径下正确加载。"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")

# 根绝对路径静态资源（别名下会打到网关根而非应用）
_ABS_STATIC_REF = re.compile(
    r"""(?:href|src)=["']/(?:css|js|vendor|favicon)[^"']*["']"""
)


def test_index_html_has_no_root_absolute_static_asset_refs():
    matches = _ABS_STATIC_REF.findall(HTML)
    assert matches == [], (
        "index.html 不得使用根绝对路径引用静态资源（LWA 别名下会 404）: "
        + ", ".join(matches)
    )


def test_index_html_uses_relative_static_asset_refs():
    assert 'href="./favicon.svg"' in HTML
    assert 'href="./css/main.css"' in HTML
    for name in (
        "purify.min.js",
        "marked.min.js",
        "mermaid.min.js",
    ):
        assert f'src="./vendor/{name}?v=' in HTML
    for name in (
        "api.js",
        "auth.js",
        "notification.js",
        "chat.js",
        "admin.js",
        "review.js",
        "workspace.js",
        "app.js",
    ):
        assert f'src="./js/{name}?v=' in HTML
