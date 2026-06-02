from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH_JS = (ROOT / "src/static/js/auth.js").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "src/static/js/chat.js").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "src/static/js/admin.js").read_text(encoding="utf-8")
REVIEW_JS = (ROOT / "src/static/js/review.js").read_text(encoding="utf-8")


def test_auth_object_is_exposed_for_inline_handlers():
    assert "window.Auth = Auth;" in AUTH_JS


def test_chat_object_is_exposed_for_inline_handlers():
    assert "window.Chat = Chat;" in CHAT_JS


def test_admin_object_is_exposed_for_inline_handlers():
    assert "window.Admin = Admin;" in ADMIN_JS


def test_review_object_is_exposed_for_inline_handlers():
    assert "window.Review = Review;" in REVIEW_JS
