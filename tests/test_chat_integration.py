"""测试 Chat 集成 — SSE 流式对话 + 消息持久化"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "config.yaml"))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    if os.path.exists(tmp_db):
        os.unlink(tmp_db)


@pytest_asyncio.fixture
async def auth_client(client):
    """已认证的客户端"""
    resp = await client.post(
        "/api/auth/register",
        json={"username": "chat_tester", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.mark.asyncio
async def test_models_endpoint(auth_client):
    """获取模型列表"""
    resp = await auth_client.get("/api/chat/models")
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) >= 3
    # DeepSeek should be enabled
    deepseek = next(m for m in models if m["id"] == "deepseek")
    assert deepseek["enabled"] is True


@pytest.mark.asyncio
async def test_prompts_endpoint(auth_client):
    """获取提示词模板列表"""
    resp = await auth_client.get("/api/chat/prompts")
    assert resp.status_code == 200
    prompts = resp.json()
    assert len(prompts) >= 4  # default, code_review, translator, summarizer


@pytest.mark.asyncio
async def test_chat_invalid_model(auth_client):
    """使用无效模型应返回 400"""
    resp = await auth_client.post(
        "/api/chat",
        json={"message": "你好", "model_id": "nonexistent"},
    )
    assert resp.status_code == 400
    assert "模型不存在" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_chat_disabled_model(auth_client):
    """使用禁用模型应返回 400"""
    resp = await auth_client.post(
        "/api/chat",
        json={"message": "你好", "model_id": "qwen"},
    )
    assert resp.status_code == 400
    assert "已禁用" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_chat_stream_with_mock_llm(auth_client):
    """使用 mock LLM 测试 SSE 流式对话"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        """模拟 LLM 流式输出"""
        yield StreamChunk(delta="你好！")
        yield StreamChunk(delta="我是")
        yield StreamChunk(delta="智能助手。")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 3, "elapsed_seconds": 0.5})

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"message": "你好", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            content = ""
            conv_id = None
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    parsed = json.loads(data_str)
                    if parsed.get("content"):
                        content += parsed["content"]
                    if parsed.get("conversation_id"):
                        conv_id = parsed["conversation_id"]

            assert content == "你好！我是智能助手。"
            assert conv_id is not None


@pytest.mark.asyncio
async def test_chat_creates_conversation(auth_client):
    """发送消息应创建新对话"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="回复内容")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"message": "测试消息", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            # Read all SSE data
            async for line in resp.aiter_lines():
                pass

    # Check conversation was created in history
    resp = await auth_client.get("/api/history/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_chat_with_prompt_template(auth_client):
    """使用提示词模板发送消息"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        # Verify system prompt was injected
        assert any(m["role"] == "system" for m in messages)
        yield StreamChunk(delta="翻译结果")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"message": "Hello", "model_id": "deepseek", "prompt_template": "translator"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                pass


@pytest.mark.asyncio
async def test_chat_injects_uploaded_string_file_ids_into_llm_context(auth_client, tmp_path, monkeypatch):
    """上传返回的字符串 file_id 应能被读取并注入 LLM prompt。"""
    from app.services.llm import StreamChunk

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    saved_name = "abc123.txt"
    (upload_dir / saved_name).write_text("这是上传文档里的关键上下文", encoding="utf-8")

    from app.config import get_settings as original_get_settings

    def fake_get_settings():
        settings = original_get_settings()
        cloned = dict(settings)
        upload_cfg = dict(cloned.get("upload", {}))
        upload_cfg["upload_dir"] = str(upload_dir)
        cloned["upload"] = upload_cfg
        return cloned

    monkeypatch.setattr("app.config.get_settings", fake_get_settings)

    async def mock_stream(model_id, messages, **kwargs):
        user_message = next(m for m in messages if m["role"] == "user")
        assert "这是上传文档里的关键上下文" in user_message["content"]
        yield StreamChunk(delta="已读取文档")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    monkeypatch.setattr("app.config.get_settings", fake_get_settings)

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={
                "message": "请总结上传资料",
                "model_id": "deepseek",
                "file_ids": [saved_name],
            },
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break


@pytest.mark.asyncio
async def test_chat_injects_persisted_context_items_on_follow_up(auth_client, tmp_path, monkeypatch):
    """已持久化的会话上下文应在后续轮次自动注入 LLM prompt。"""
    from app.services.llm import StreamChunk

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    saved_name = "persisted-doc.txt"
    (upload_dir / saved_name).write_text("持久化文档中的产品背景", encoding="utf-8")

    from app.config import get_settings as original_get_settings

    def fake_get_settings():
        settings = original_get_settings()
        cloned = dict(settings)
        upload_cfg = dict(cloned.get("upload", {}))
        upload_cfg["upload_dir"] = str(upload_dir)
        cloned["upload"] = upload_cfg
        return cloned

    monkeypatch.setattr("app.config.get_settings", fake_get_settings)

    async def bootstrap_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="首轮回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=bootstrap_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"message": "创建会话", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                parsed = json.loads(data_str)
                if parsed.get("conversation_id"):
                    conv_id = parsed["conversation_id"]

    assert conv_id is not None

    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={
            "context_type": "rule_doc",
            "title": "持久化参考文档",
            "file_id": saved_name,
            "enabled": True,
        },
    )
    assert resp.status_code == 200

    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={
            "context_type": "manual_rule",
            "title": "验收口径",
            "manual_text": "请重点检查验收口径",
            "enabled": True,
        },
    )
    assert resp.status_code == 200

    async def follow_up_stream(model_id, messages, **kwargs):
        user_message = next(m for m in messages if m["role"] == "user")
        assert "持久化文档中的产品背景" in user_message["content"]
        assert "请重点检查验收口径" in user_message["content"]
        yield StreamChunk(delta="后续回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=follow_up_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={
                "conversation_id": conv_id,
                "message": "继续分析",
                "model_id": "deepseek",
            },
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break


@pytest.mark.asyncio
async def test_chat_persists_messages(auth_client):
    """对话消息应持久化到数据库"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="AI回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"message": "用户消息", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str != "[DONE]":
                        parsed = json.loads(data_str)
                        if parsed.get("conversation_id"):
                            conv_id = parsed["conversation_id"]

    # Load conversation and verify messages
    assert conv_id is not None
    resp = await auth_client.get(f"/api/history/conversations/{conv_id}")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert len(messages) >= 2
    assert any(m["role"] == "user" and "用户消息" in m["content"] for m in messages)
    assert any(m["role"] == "assistant" and "AI回复" in m["content"] for m in messages)


@pytest.mark.asyncio
async def test_chat_saves_assistant_reply_once_when_stream_finishes_twice(auth_client):
    """流式结束事件重复到达时，同一条 AI 回复只能入库一次。"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="唯一AI回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"message": "用户消息", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str != "[DONE]":
                        parsed = json.loads(data_str)
                        if parsed.get("conversation_id"):
                            conv_id = parsed["conversation_id"]

    assert conv_id is not None
    resp = await auth_client.get(f"/api/history/conversations/{conv_id}")
    assert resp.status_code == 200
    assistants = [
        m for m in resp.json()["messages"]
        if m["role"] == "assistant" and m["content"] == "唯一AI回复"
    ]
    assert len(assistants) == 1


@pytest.mark.asyncio
async def test_chat_requires_auth(client):
    """未认证用户发送消息应返回 401"""
    resp = await client.post(
        "/api/chat",
        json={"message": "你好", "model_id": "deepseek"},
    )
    assert resp.status_code == 401
