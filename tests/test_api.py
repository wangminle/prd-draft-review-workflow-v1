"""测试 API 路由（集成测试）+ HTTP 中间件"""

import json
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from main import app

from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    # 先初始化数据库，再创建客户端
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    if os.path.exists(tmp_db):
        os.unlink(tmp_db)


@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register_and_login(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "testuser", "password": "test123456"},
    )
    assert resp.status_code == 200, f"Register failed: {resp.text}"
    token_data = resp.json()
    assert "access_token" in token_data

    token = token_data["access_token"]

    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"

    resp = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "test123456"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_auth_required_endpoints(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401

    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid_token"},
    )
    assert resp.status_code == 401

    resp = await client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_models_endpoint(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "chat_user", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/chat/models", headers=headers)
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) > 0
    assert all("enabled" in item for item in models)


@pytest.mark.asyncio
async def test_review_context_defaults_include_team_review_rules(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "review_context_defaults", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/review/projects",
        json={"name": "默认上下文项目", "description": ""},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    project_id = resp.json()["id"]

    resp = await client.get(f"/api/review/projects/{project_id}/context", headers=headers)

    assert resp.status_code == 200, resp.text
    guidance = resp.json()["context_data"]["professional_guidance"]
    assert len(guidance) == 6
    assert guidance[0].startswith("需求范围要写实")
    assert guidance[-1].startswith("技术方案要分期但不能糊涂")


@pytest.mark.asyncio
async def test_chat_stream_endpoint(client):
    from unittest.mock import patch
    from app.services.llm import StreamChunk

    resp = await client.post(
        "/api/auth/register",
        json={"username": "stream_user", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="你好！我是智能助手。")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with client.stream(
            "POST",
            "/api/chat",
            json={"message": "你好", "model_id": "deepseek"},
            headers=headers,
        ) as resp:
            assert resp.status_code == 200
            content = ""
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    parsed = json.loads(data)
                    if parsed.get("content"):
                        content += parsed["content"]

            assert len(content) > 0
            assert "你好" in content


@pytest.mark.asyncio
async def test_history_conversations(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "history_user", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/history/conversations", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["conversations"] == []


@pytest.mark.asyncio
async def test_register_never_promotes_first_user_to_admin(client):
    from app.routers import auth as auth_router

    auth_settings = dict(auth_router._settings.get("auth", {}))
    auth_settings["allow_public_registration"] = True

    resp = await client.post(
        "/api/auth/register",
        json={"username": "first_user", "password": "test123456"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


@pytest.mark.asyncio
async def test_admin_users_list_includes_last_active_time(client):
    from app.models.user import User
    from app.utils import now_cn

    register_resp = await client.post(
        "/api/auth/register",
        json={"username": "active_user", "password": "test123456"},
    )
    assert register_resp.status_code == 200
    user_token = register_resp.json()["access_token"]

    me_resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert me_resp.status_code == 200

    admin_login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert admin_login_resp.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login_resp.json()['access_token']}"}

    users_resp = await client.get("/api/admin/users", headers=admin_headers)
    assert users_resp.status_code == 200
    users = users_resp.json()
    target = next(user for user in users if user["username"] == "active_user")

    assert target["last_active_at"] is not None

    # 再访问一次，最近访问时间应向后推进。
    await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    users_resp = await client.get("/api/admin/users", headers=admin_headers)
    assert users_resp.status_code == 200
    refreshed = next(user for user in users_resp.json() if user["username"] == "active_user")
    assert refreshed["last_active_at"] >= target["last_active_at"]


@pytest.mark.asyncio
async def test_register_can_be_disabled_for_closed_deployment(client, monkeypatch):
    from app.routers import auth as auth_router

    auth_settings = dict(auth_router._settings.get("auth", {}))
    auth_settings["allow_public_registration"] = False
    monkeypatch.setitem(auth_router._settings, "auth", auth_settings)

    resp = await client.post(
        "/api/auth/register",
        json={"username": "closed_user", "password": "test123456"},
    )

    assert resp.status_code == 403
    assert "未开放公开注册" in resp.json()["detail"]


# ─── HTTP 中间件（原 test_http_middleware.py）───────────────────────


@pytest.mark.asyncio
async def test_api_responses_disable_cache():
    """所有 API 响应应设置 Cache-Control: no-store"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
