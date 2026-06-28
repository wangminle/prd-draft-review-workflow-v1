"""测试管理后台 Prompt 模板 CRUD API。"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "config.yaml"))

from tests.conftest import init_test_db, make_test_app


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


@pytest_asyncio.fixture
async def admin_headers(client):
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def user_headers(client):
    await client.post("/api/auth/register", json={"username": "prompt_user", "password": "test123456"})
    resp = await client.post("/api/auth/login", json={"username": "prompt_user", "password": "test123456"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_can_create_prompt_template(client, admin_headers, user_headers):
    resp = await client.post(
        "/api/admin/prompts",
        headers=admin_headers,
        json={
            "name": "pytest_prompt_create",
            "description": "pytest create prompt",
            "system_prompt": "你是pytest创建模板",
            "user_prompt_template": "请处理：{content}",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    resp = await client.get("/api/admin/prompts", headers=admin_headers)
    assert resp.status_code == 200
    prompts = resp.json()
    created = next((p for p in prompts if p["name"] == "pytest_prompt_create"), None)
    assert created is not None

    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "你是pytest创建模板"
        yield StreamChunk(delta="ok")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with client.stream(
            "POST",
            "/api/chat",
            headers=user_headers,
            json={"message": "测试内容", "model_id": "deepseek", "prompt_template": "pytest_prompt_create"},
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass


@pytest.mark.asyncio
async def test_admin_can_update_prompt_template(client, admin_headers, user_headers):
    create_resp = await client.post(
        "/api/admin/prompts",
        headers=admin_headers,
        json={
            "name": "pytest_prompt_update",
            "description": "pytest update prompt",
            "system_prompt": "旧system prompt",
            "user_prompt_template": "旧模板：{content}",
        },
    )
    assert create_resp.status_code == 200
    prompt_id = create_resp.json()["id"]

    resp = await client.put(
        f"/api/admin/prompts/{prompt_id}",
        headers=admin_headers,
        json={
            "name": "pytest_prompt_update",
            "description": "updated prompt",
            "system_prompt": "新system prompt",
            "user_prompt_template": "新模板：{content}",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    resp = await client.get("/api/admin/prompts", headers=admin_headers)
    assert resp.status_code == 200
    updated = next((p for p in resp.json() if p["id"] == prompt_id), None)
    assert updated is not None
    assert updated["system_prompt"] == "新system prompt"
    assert updated["user_prompt_template"] == "新模板：{content}"

    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        assert messages[0]["content"] == "新system prompt"
        assert messages[-1]["content"] == "新模板：测试内容"
        yield StreamChunk(delta="ok")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with client.stream(
            "POST",
            "/api/chat",
            headers=user_headers,
            json={"message": "测试内容", "model_id": "deepseek", "prompt_template": "pytest_prompt_update"},
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass


@pytest.mark.asyncio
async def test_admin_can_delete_prompt_template(client, admin_headers):
    create_resp = await client.post(
        "/api/admin/prompts",
        headers=admin_headers,
        json={
            "name": "pytest_prompt_delete",
            "description": "pytest delete prompt",
            "system_prompt": "待删除模板",
            "user_prompt_template": "删除模板：{content}",
        },
    )
    assert create_resp.status_code == 200
    prompt_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/admin/prompts/{prompt_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    resp = await client.get("/api/admin/prompts", headers=admin_headers)
    assert resp.status_code == 200
    assert all(p["id"] != prompt_id for p in resp.json())


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_prompt_templates(client, user_headers):
    create_resp = await client.post(
        "/api/admin/prompts",
        headers=user_headers,
        json={
            "name": "forbidden_prompt_create",
            "description": "forbidden create",
            "system_prompt": "forbidden",
            "user_prompt_template": "{content}",
        },
    )
    assert create_resp.status_code == 403

    update_resp = await client.put(
        "/api/admin/prompts/1",
        headers=user_headers,
        json={"system_prompt": "forbidden update"},
    )
    assert update_resp.status_code == 403

    delete_resp = await client.delete("/api/admin/prompts/1", headers=user_headers)
    assert delete_resp.status_code == 403
