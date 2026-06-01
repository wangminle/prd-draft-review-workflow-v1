"""测试上下文面板核心链路 — 会话级上下文持久化、URL 文本注入、会话隔离"""

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "config.yaml"))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app


def _write_minimal_docx(path: Path, text: str) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", xml)


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
        json={"username": "ctx_tester", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ── P0 Bug 1: 上下文按会话持久化 & 切换加载 ──


@pytest.mark.asyncio
async def test_context_items_persisted_per_conversation(auth_client):
    """不同对话的上下文项应独立持久化，切换时加载各自的上下文。"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    # 创建第一个对话并添加上下文
    conv1_id = None
    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"message": "对话1消息", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv1_id = parsed["conversation_id"]

    assert conv1_id is not None

    # 在对话1添加两个上下文项
    resp = await auth_client.post(
        f"/api/chat/conversations/{conv1_id}/context",
        json={"context_type": "historical_doc", "title": "历史文档A", "enabled": True},
    )
    assert resp.status_code == 200
    ctx1_item_id = resp.json()["id"]

    resp = await auth_client.post(
        f"/api/chat/conversations/{conv1_id}/context",
        json={"context_type": "manual_rule", "title": "规则1", "manual_text": "请检查验收口径", "enabled": True},
    )
    assert resp.status_code == 200
    ctx1_rule_id = resp.json()["id"]

    # 创建第二个对话
    conv2_id = None
    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"message": "对话2消息", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv2_id = parsed["conversation_id"]

    assert conv2_id is not None

    # 在对话2添加不同上下文项
    resp = await auth_client.post(
        f"/api/chat/conversations/{conv2_id}/context",
        json={"context_type": "rule_doc", "title": "规则文档B", "enabled": True},
    )
    assert resp.status_code == 200

    # 验证对话1只有自己的上下文项
    resp = await auth_client.get(f"/api/chat/conversations/{conv1_id}/context")
    assert resp.status_code == 200
    conv1_items = resp.json()
    assert len(conv1_items) == 2
    assert any(i["title"] == "历史文档A" for i in conv1_items)
    assert any(i["manual_text"] == "请检查验收口径" for i in conv1_items)

    # 验证对话2只有自己的上下文项（没有对话1的数据）
    resp = await auth_client.get(f"/api/chat/conversations/{conv2_id}/context")
    assert resp.status_code == 200
    conv2_items = resp.json()
    assert len(conv2_items) == 1
    assert conv2_items[0]["title"] == "规则文档B"
    assert not any(i["title"] == "历史文档A" for i in conv2_items)


@pytest.mark.asyncio
async def test_context_items_toggle_enabled(auth_client):
    """上下文项 enabled 状态变更应持久化。"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST", "/api/chat", json={"message": "test", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv_id = parsed["conversation_id"]

    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={"context_type": "manual_rule", "title": "测试规则", "manual_text": "请关注边界", "enabled": True},
    )
    assert resp.status_code == 200
    item_id = resp.json()["id"]

    # Toggle to disabled
    resp = await auth_client.put(
        f"/api/chat/conversations/{conv_id}/context/{item_id}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # Verify persisted state
    resp = await auth_client.get(f"/api/chat/conversations/{conv_id}/context")
    assert resp.status_code == 200
    item = next(i for i in resp.json() if i["id"] == item_id)
    assert item["enabled"] is False


# ── P0 Bug 2: URL 文本注入 LLM 上下文 ──


@pytest.mark.asyncio
async def test_url_texts_injected_into_llm_context(auth_client):
    """url_texts 中的提取内容应注入 LLM prompt，不仅是 URL 字符串。"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        user_message = next(m for m in reversed(messages) if m["role"] == "user")
        # Verify URL content (not just URL string) appears in context
        assert "URL内容关键信息" in user_message["content"]
        yield StreamChunk(delta="已读取URL")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={
                "message": "请总结URL资料",
                "model_id": "deepseek",
                "urls": ["https://example.com/article"],
                "url_texts": {"https://example.com/article": "URL内容关键信息：产品需求和验收标准"},
            },
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break


@pytest.mark.asyncio
async def test_url_without_text_still_sent_as_string(auth_client):
    """没有 url_texts 时，URL 仍以字符串形式发送。"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        user_message = next(m for m in reversed(messages) if m["role"] == "user")
        assert "https://example.com/page" in user_message["content"]
        yield StreamChunk(delta="回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={
                "message": "请看这个链接",
                "model_id": "deepseek",
                "urls": ["https://example.com/page"],
            },
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break


@pytest.mark.asyncio
async def test_context_item_url_with_extracted_text_injected(auth_client):
    """持久化的 URL 上下文项带 extracted_text 时，应注入内容而非仅 URL。"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="首轮")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST", "/api/chat", json={"message": "创建会话", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv_id = parsed["conversation_id"]

    # Add URL context item with extracted text
    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={
            "context_type": "historical_doc",
            "title": "产品规范URL",
            "url": "https://internal/wiki/spec",
            "extracted_text": "产品规范关键要点：需求必须包含目标用户和验收口径",
            "enabled": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["extracted_text"] == "产品规范关键要点：需求必须包含目标用户和验收口径"

    # Send follow-up — verify extracted_text is in LLM context
    async def follow_up_stream(model_id, messages, **kwargs):
        user_message = next(m for m in messages if m["role"] == "user")
        assert "产品规范关键要点" in user_message["content"]
        assert "https://internal/wiki/spec" in user_message["content"]
        yield StreamChunk(delta="后续回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=follow_up_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"conversation_id": conv_id, "message": "继续分析", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break


# ── P0 Bug 2: 持久化上下文自动注入 ── (已在 test_chat_integration.py 有类似测试，此处补充)


@pytest.mark.asyncio
async def test_disabled_context_item_not_injected(auth_client, tmp_path, monkeypatch):
    """enabled=False 的持久化上下文项不应注入 LLM。"""
    from app.services.llm import StreamChunk

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    saved_name = "disabled-doc.txt"
    (upload_dir / saved_name).write_text("被禁用的文档内容", encoding="utf-8")

    from app.routers import chat as chat_router
    original_get_settings = chat_router.get_settings

    def fake_get_settings():
        settings = original_get_settings()
        cloned = dict(settings)
        upload_cfg = dict(cloned.get("upload", {}))
        upload_cfg["upload_dir"] = str(upload_dir)
        cloned["upload"] = upload_cfg
        return cloned

    monkeypatch.setattr(chat_router, "get_settings", fake_get_settings)

    async def bootstrap_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="首轮回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=bootstrap_stream):
        async with auth_client.stream(
            "POST", "/api/chat", json={"message": "创建会话", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv_id = parsed["conversation_id"]

    # Add context item but disabled
    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={"context_type": "historical_doc", "title": "禁用文档", "file_id": saved_name, "enabled": False},
    )
    assert resp.status_code == 200

    async def follow_up_stream(model_id, messages, **kwargs):
        user_message = next(m for m in messages if m["role"] == "user")
        # Disabled item should NOT appear in context
        assert "被禁用的文档内容" not in user_message["content"]
        yield StreamChunk(delta="后续回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=follow_up_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"conversation_id": conv_id, "message": "继续", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break


# ── 上下文项 CRUD 完整链路 ──


@pytest.mark.asyncio
async def test_context_item_delete_removes_from_llm_context(auth_client, tmp_path, monkeypatch):
    """删除上下文项后，后续轮次不应再注入该文档内容。"""
    from app.services.llm import StreamChunk

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    saved_name = "to-delete-doc.txt"
    (upload_dir / saved_name).write_text("即将删除的文档内容", encoding="utf-8")

    from app.routers import chat as chat_router
    original_get_settings = chat_router.get_settings

    def fake_get_settings():
        settings = original_get_settings()
        cloned = dict(settings)
        upload_cfg = dict(cloned.get("upload", {}))
        upload_cfg["upload_dir"] = str(upload_dir)
        cloned["upload"] = upload_cfg
        return cloned

    monkeypatch.setattr(chat_router, "get_settings", fake_get_settings)

    async def bootstrap_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="首轮")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=bootstrap_stream):
        async with auth_client.stream(
            "POST", "/api/chat", json={"message": "test", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv_id = parsed["conversation_id"]

    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={"context_type": "temporary", "title": "临时文档", "file_id": saved_name, "enabled": True},
    )
    assert resp.status_code == 200
    item_id = resp.json()["id"]

    # Delete the context item
    resp = await auth_client.delete(
        f"/api/chat/conversations/{conv_id}/context/{item_id}",
    )
    assert resp.status_code == 200

    async def follow_up_stream(model_id, messages, **kwargs):
        user_message = next(m for m in messages if m["role"] == "user")
        assert "即将删除的文档内容" not in user_message["content"]
        yield StreamChunk(delta="后续回复")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=follow_up_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"conversation_id": conv_id, "message": "继续", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break


async def test_mention_context_item_ids_limit_persisted_doc_injection(auth_client, tmp_path, monkeypatch):
    """当请求带 mention_context_item_ids 时，仅注入被 @ 的持久化文档。"""
    from app.services.llm import StreamChunk

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    doc_a = "mention-a.txt"
    doc_b = "mention-b.txt"
    (upload_dir / doc_a).write_text("文档A核心信息", encoding="utf-8")
    (upload_dir / doc_b).write_text("文档B核心信息", encoding="utf-8")

    from app.routers import chat as chat_router

    original_get_settings = chat_router.get_settings

    def fake_get_settings():
        settings = original_get_settings()
        cloned = dict(settings)
        upload_cfg = dict(cloned.get("upload", {}))
        upload_cfg["upload_dir"] = str(upload_dir)
        cloned["upload"] = upload_cfg
        return cloned

    monkeypatch.setattr(chat_router, "get_settings", fake_get_settings)

    async def bootstrap_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="首轮")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=bootstrap_stream):
        async with auth_client.stream(
            "POST", "/api/chat", json={"message": "创建会话", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv_id = parsed["conversation_id"]

    assert conv_id is not None

    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={"context_type": "historical_doc", "title": "文档A", "file_id": doc_a, "enabled": True},
    )
    assert resp.status_code == 200
    item_a_id = resp.json()["id"]

    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={"context_type": "historical_doc", "title": "文档B", "file_id": doc_b, "enabled": True},
    )
    assert resp.status_code == 200

    async def follow_up_stream(model_id, messages, **kwargs):
        user_message = next(m for m in messages if m["role"] == "user")
        assert "文档A核心信息" in user_message["content"]
        assert "文档B核心信息" not in user_message["content"]
        yield StreamChunk(delta="后续")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=follow_up_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={
                "conversation_id": conv_id,
                "message": "请只参考 @文档A",
                "model_id": "deepseek",
                "mention_context_item_ids": [item_a_id],
            },
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break


@pytest.mark.asyncio
async def test_docx_context_item_injects_extracted_text_not_zip_payload(auth_client, tmp_path, monkeypatch):
    """DOCX 上下文项应注入 Word 正文，不能把 OOXML 压缩包内容当文本传给模型。"""
    from app.services.llm import StreamChunk

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    saved_name = "context-doc.docx"
    _write_minimal_docx(upload_dir / saved_name, "DOCX正文里的关键业务逻辑")

    from app.routers import chat as chat_router
    original_get_settings = chat_router.get_settings

    def fake_get_settings():
        settings = original_get_settings()
        cloned = dict(settings)
        upload_cfg = dict(cloned.get("upload", {}))
        upload_cfg["upload_dir"] = str(upload_dir)
        cloned["upload"] = upload_cfg
        return cloned

    monkeypatch.setattr(chat_router, "get_settings", fake_get_settings)

    async def bootstrap_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="首轮")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=bootstrap_stream):
        async with auth_client.stream(
            "POST", "/api/chat", json={"message": "创建会话", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv_id = parsed["conversation_id"]

    resp = await auth_client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={"context_type": "historical_doc", "title": "Word文档", "file_id": saved_name, "enabled": True},
    )
    assert resp.status_code == 200

    observed_user_prompt = ""

    async def follow_up_stream(model_id, messages, **kwargs):
        nonlocal observed_user_prompt
        user_message = next(m for m in reversed(messages) if m["role"] == "user")
        observed_user_prompt = user_message["content"]
        yield StreamChunk(delta="后续")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    with patch("app.routers.chat.stream_chat", side_effect=follow_up_stream):
        async with auth_client.stream(
            "POST",
            "/api/chat",
            json={"conversation_id": conv_id, "message": "继续", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == "data: [DONE]":
                    break

    assert "DOCX正文里的关键业务逻辑" in observed_user_prompt
    assert "[Content_Types].xml" not in observed_user_prompt
