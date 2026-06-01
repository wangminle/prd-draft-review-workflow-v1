from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_JS = (ROOT / "src/static/js/api.js").read_text(encoding="utf-8")


def test_api_request_error_message_includes_status_code():
    request_block = API_JS.split("async request(method, path, body)", 1)[1].split("/* 认证 */", 1)[0]
    assert "const err = await resp.json().catch(() => ({ detail: resp.statusText }));" in request_block
    assert "throw new Error(`${resp.status} ${err.detail || resp.statusText}`);" in request_block