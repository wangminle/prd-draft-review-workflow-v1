"""BUG-196/BUG-197 回归测试

BUG-196 [P1] 改密/管理员重置密码后旧 JWT 仍可访问接口、签发 SSE 票据。
  修复：users.auth_version 会话版本号，JWT 携带 av 声明，中间件比对；
  用户改密与管理员重置密码均递增 auth_version，旧 JWT 一律 401。

BUG-197 [P2] bcrypt 上限 72 字节，73 位英文或 25 位中文密码导致 500。
  修复：schema 层校验 UTF-8 字节长度（422），hash_password 防御性 ValueError，
  verify_password 对超长输入返回 False（登录按凭据错误 401 处理）。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from tests.conftest import init_test_db, make_test_app

LONG_ASCII_PASSWORD = "a" * 73          # 73 字节，超 bcrypt 72 字节上限
LONG_CHINESE_PASSWORD = "汉" * 25        # 75 字节 UTF-8
VALID_PASSWORD = "test123456"
NEW_PASSWORD = "newpass789"


@pytest_asyncio.fixture
async def client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


async def _register(client, username="alice", password=VALID_PASSWORD):
    resp = await client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _admin_token(client):
    resp = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin@2026"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ─── BUG-196：会话撤销 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_old_jwt_rejected_after_password_change(client):
    """改密后旧 JWT 访问 /me 与签发 SSE 票据均 401（复现路径的反向断言）"""
    token = await _register(client)

    resp = await client.get("/api/auth/me", headers=_auth(token))
    assert resp.status_code == 200

    resp = await client.put(
        "/api/auth/password",
        json={"old_password": VALID_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text

    # 旧 JWT 访问业务接口 → 401
    resp = await client.get("/api/auth/me", headers=_auth(token))
    assert resp.status_code == 401

    # 旧 JWT 申请 SSE 票据 → 401
    resp = await client.post("/api/auth/sse-ticket", headers=_auth(token))
    assert resp.status_code == 401

    # 旧密码登录 → 401；新密码登录 → 200 且新 token 可用
    resp = await client.post(
        "/api/auth/login", json={"username": "alice", "password": VALID_PASSWORD}
    )
    assert resp.status_code == 401
    resp = await client.post(
        "/api/auth/login", json={"username": "alice", "password": NEW_PASSWORD}
    )
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]
    resp = await client.get("/api/auth/me", headers=_auth(new_token))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_old_jwt_rejected_after_admin_reset(client):
    """管理员重置密码后，目标用户旧 JWT 立即失效"""
    token = await _register(client)
    admin = await _admin_token(client)

    me = await client.get("/api/auth/me", headers=_auth(token))
    user_id = me.json()["id"]

    resp = await client.put(
        f"/api/admin/users/{user_id}",
        json={"password": "adminreset123"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/auth/me", headers=_auth(token))
    assert resp.status_code == 401
    resp = await client.post("/api/auth/sse-ticket", headers=_auth(token))
    assert resp.status_code == 401

    # 新密码可登录
    resp = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "adminreset123"}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_token_without_auth_version_claim_rejected(client):
    """升级前签发的旧格式 JWT（无 av 声明）一律视为失效，强制重新登录"""
    await _register(client)
    from jose import jwt as jose_jwt

    from app.config import get_settings

    settings = get_settings()
    legacy = jose_jwt.encode(
        {"sub": "2", "role": "user", "exp": 9999999999},
        settings["auth"]["secret_key"],
        algorithm=settings["auth"]["algorithm"],
    )
    resp = await client.get("/api/auth/me", headers=_auth(legacy))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_other_user_token_unaffected_by_password_change(client):
    """一个用户改密不影响其他用户的会话"""
    token_a = await _register(client, username="alice")
    token_b = await _register(client, username="bob")

    resp = await client.put(
        "/api/auth/password",
        json={"old_password": VALID_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_auth(token_a),
    )
    assert resp.status_code == 200

    resp = await client.get("/api/auth/me", headers=_auth(token_b))
    assert resp.status_code == 200
    assert resp.json()["username"] == "bob"


@pytest.mark.asyncio
async def test_auth_version_bumped_in_db(client):
    """改密与管理员重置均递增 users.auth_version"""
    token = await _register(client)

    await client.put(
        "/api/auth/password",
        json={"old_password": VALID_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_auth(token),
    )
    # 通过重新登录拿到的 token 解出 av=2
    resp = await client.post(
        "/api/auth/login", json={"username": "alice", "password": NEW_PASSWORD}
    )
    new_token = resp.json()["access_token"]
    from app.services.auth import decode_token

    assert decode_token(new_token)["av"] == 2

    admin = await _admin_token(client)
    me = await client.get("/api/auth/me", headers=_auth(new_token))
    await client.put(
        f"/api/admin/users/{me.json()['id']}",
        json={"password": "resetpass999"},
        headers=_auth(admin),
    )
    resp = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "resetpass999"}
    )
    assert decode_token(resp.json()["access_token"])["av"] == 3


# ─── BUG-197：bcrypt 72 字节上限 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_register_long_ascii_password_returns_422(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "longascii", "password": LONG_ASCII_PASSWORD},
    )
    assert resp.status_code == 422, resp.text
    assert "72" in resp.text


@pytest.mark.asyncio
async def test_register_long_chinese_password_returns_422(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "longzh", "password": LONG_CHINESE_PASSWORD},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_change_password_to_long_returns_422(client):
    token = await _register(client)
    resp = await client.put(
        "/api/auth/password",
        json={"old_password": VALID_PASSWORD, "new_password": LONG_ASCII_PASSWORD},
        headers=_auth(token),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_login_with_long_password_returns_401_not_500(client):
    """已有账号以超长密码登录：按凭据错误 401 处理，不抛 500"""
    await _register(client)
    resp = await client.post(
        "/api/auth/login", json={"username": "alice", "password": LONG_ASCII_PASSWORD}
    )
    assert resp.status_code == 401, resp.text
    resp = await client.post(
        "/api/auth/login", json={"username": "alice", "password": LONG_CHINESE_PASSWORD}
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_change_password_with_long_old_password_returns_400_not_500(client):
    token = await _register(client)
    resp = await client.put(
        "/api/auth/password",
        json={"old_password": LONG_ASCII_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.text  # 原密码错误


@pytest.mark.asyncio
async def test_admin_create_user_long_password_returns_422(client):
    admin = await _admin_token(client)
    resp = await client.post(
        "/api/admin/users",
        json={"username": "longpwd", "password": LONG_ASCII_PASSWORD, "role": "user"},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_admin_reset_long_password_returns_422(client):
    token = await _register(client)
    me = await client.get("/api/auth/me", headers=_auth(token))
    admin = await _admin_token(client)
    resp = await client.put(
        f"/api/admin/users/{me.json()['id']}",
        json={"password": LONG_CHINESE_PASSWORD},
        headers=_auth(admin),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_boundary_72_byte_password_accepted(client):
    """恰好 72 字节的密码可用（边界值不应误杀）"""
    pwd = "a" * 72
    resp = await client.post(
        "/api/auth/register", json={"username": "edge72", "password": pwd}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/api/auth/login", json={"username": "edge72", "password": pwd}
    )
    assert resp.status_code == 200


# ─── 服务层防御 ────────────────────────────────────────────────────────


def test_hash_password_raises_on_over_72_bytes():
    from app.services.auth import hash_password

    with pytest.raises(ValueError, match="72"):
        hash_password(LONG_ASCII_PASSWORD)
    with pytest.raises(ValueError, match="72"):
        hash_password(LONG_CHINESE_PASSWORD)


def test_verify_password_returns_false_on_over_72_bytes():
    from app.services.auth import hash_password, verify_password

    hashed = hash_password(VALID_PASSWORD)
    assert verify_password(LONG_ASCII_PASSWORD, hashed) is False
    assert verify_password(LONG_CHINESE_PASSWORD, hashed) is False
    assert verify_password(VALID_PASSWORD, hashed) is True


def test_token_contains_auth_version_claim():
    from app.services.auth import create_access_token, decode_token

    token = create_access_token(user_id=1, role="user", auth_version=7)
    assert decode_token(token)["av"] == 7
    # 兼容旧调用：默认 av=1
    assert decode_token(create_access_token(user_id=1, role="user"))["av"] == 1


# ─── 前端契约 ──────────────────────────────────────────────────────────


def test_frontend_password_byte_precheck_and_relogin():
    """auth.js 改密前端：72 字节预检 + 成功后注销并重载到登录页"""
    auth_js = (ROOT / "src" / "static" / "js" / "auth.js").read_text(encoding="utf-8")
    assert "new TextEncoder().encode(newPwd).length > 72" in auth_js
    assert "所有登录状态已失效" in auth_js
    assert "this.logout();" in auth_js
    assert "location.reload();" in auth_js


def test_frontend_api_error_detail_array_unwrapped():
    """api.js：422 数组型 detail 提取 msg 拼接，不再显示 [object Object]"""
    api_js = (ROOT / "src" / "static" / "js" / "api.js").read_text(encoding="utf-8")
    assert "_errorDetail(err, fallback)" in api_js
    assert "Array.isArray(detail)" in api_js
    assert api_js.count("this._errorDetail(err,") >= 10
