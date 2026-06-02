"""CHK-006 代码审查问题修复验证测试

覆盖三个 P2 修复：
1. 删除不存在的上下文项应返回 404（而非误报成功）
2. FTS 搜索排序应使用 rank（FTS 相关性）而非 created_at
3. 逐篇分析缓存校验应检查固定 6 项 rule_key 而非仅检查 checks 长度
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "config.yaml"))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app


# ── Fixtures ──


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
    resp = await client.post(
        "/api/auth/register",
        json={"username": "chk006_tester", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ── P2-1: 删除不存在上下文项应返回 404 ──


@pytest.mark.asyncio
async def test_delete_nonexistent_context_item_returns_404(auth_client):
    """删除不存在的上下文项应返回 404，而非误报成功。"""
    from app.services.llm import StreamChunk

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="hi")
        yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 1})

    conv_id = None
    with patch("app.routers.chat.stream_chat", side_effect=mock_stream):
        async with auth_client.stream(
            "POST", "/api/chat", json={"message": "hello", "model_id": "deepseek"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    parsed = json.loads(line[6:])
                    if parsed.get("conversation_id"):
                        conv_id = parsed["conversation_id"]

    assert conv_id is not None

    resp = await auth_client.delete(
        f"/api/chat/conversations/{conv_id}/context/99999",
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_context_item_wrong_conversation_returns_404(auth_client):
    """删除不存在的会话中的上下文项应返回 404。"""
    resp = await auth_client.delete(
        "/api/chat/conversations/99999/context/1",
    )
    assert resp.status_code == 404


# ── P2-2: FTS 搜索排序使用 rank ──


def test_fts_search_uses_rank_ordering():
    """ConversationRepository.search_messages 的 SQL 应使用 ORDER BY rank。"""
    import inspect
    from app.repositories.conversation_repository import ConversationRepository

    source = inspect.getsource(ConversationRepository.search_messages)
    assert "ORDER BY rank" in source, (
        "search_messages SQL should use 'ORDER BY rank' for FTS relevance, "
        "not 'ORDER BY m.created_at DESC'"
    )
    assert "ORDER BY m.created_at DESC" not in source


# ── P2-3: 缓存校验需检查固定 rule_key 集合 ──


def _make_analysis(checks_json: list) -> SimpleNamespace:
    return SimpleNamespace(
        full_analysis=json.dumps({
            "expert_review": {
                "summary": "test",
                "checks": checks_json,
            }
        })
    )


def test_cache_validation_rejects_wrong_rule_keys():
    """即使有 6 条 checks，如果 rule_key 不匹配固定集合，应判定不完整。"""
    from app.repositories.review_task_repository import ReviewTaskRepository

    wrong_keys = _make_analysis([
        {"rule_key": "scope_realism"},
        {"rule_key": "boundary_completeness"},
        {"rule_key": "structured_entitlements"},
        {"rule_key": "user_facing_naming"},
        {"rule_key": "copy_consistency"},
        {"rule_key": "some_wrong_key"},
    ])
    assert ReviewTaskRepository._analysis_has_required_expert_review(wrong_keys) is False


def test_cache_validation_accepts_complete_rule_keys():
    """包含全部 6 个正确 rule_key 时应判定完整。"""
    from app.repositories.review_task_repository import ReviewTaskRepository

    correct = _make_analysis([
        {"rule_key": "scope_realism"},
        {"rule_key": "boundary_completeness"},
        {"rule_key": "structured_entitlements"},
        {"rule_key": "user_facing_naming"},
        {"rule_key": "copy_consistency"},
        {"rule_key": "phased_tech_plan"},
    ])
    assert ReviewTaskRepository._analysis_has_required_expert_review(correct) is True


def test_cache_validation_accepts_superset_of_rule_keys():
    """包含全部 6 个 rule_key 外加额外 key 也应判定完整。"""
    from app.repositories.review_task_repository import ReviewTaskRepository

    superset = _make_analysis([
        {"rule_key": "scope_realism"},
        {"rule_key": "boundary_completeness"},
        {"rule_key": "structured_entitlements"},
        {"rule_key": "user_facing_naming"},
        {"rule_key": "copy_consistency"},
        {"rule_key": "phased_tech_plan"},
        {"rule_key": "extra_future_rule"},
    ])
    assert ReviewTaskRepository._analysis_has_required_expert_review(superset) is True


def test_cache_validation_rejects_missing_rule_key():
    """缺少任一必需 rule_key 应判定不完整。"""
    from app.repositories.review_task_repository import ReviewTaskRepository

    missing_one = _make_analysis([
        {"rule_key": "scope_realism"},
        {"rule_key": "boundary_completeness"},
        {"rule_key": "structured_entitlements"},
        {"rule_key": "user_facing_naming"},
        {"rule_key": "copy_consistency"},
    ])
    assert ReviewTaskRepository._analysis_has_required_expert_review(missing_one) is False


# ── P2-4: 缓存校验需检查 summary 非空 ──


def _make_analysis_empty_summary(checks_json: list) -> SimpleNamespace:
    return SimpleNamespace(
        full_analysis=json.dumps({
            "expert_review": {
                "summary": "",
                "checks": checks_json,
            }
        })
    )


def test_cache_validation_rejects_empty_summary():
    """即使有完整 rule_key，summary 为空也应判定不完整。"""
    from app.repositories.review_task_repository import ReviewTaskRepository

    empty_summary = _make_analysis_empty_summary([
        {"rule_key": "scope_realism"},
        {"rule_key": "boundary_completeness"},
        {"rule_key": "structured_entitlements"},
        {"rule_key": "user_facing_naming"},
        {"rule_key": "copy_consistency"},
        {"rule_key": "phased_tech_plan"},
    ])
    assert ReviewTaskRepository._analysis_has_required_expert_review(empty_summary) is False


def test_cache_validation_rejects_whitespace_only_summary():
    """summary 只有空格也应判定不完整。"""
    from app.repositories.review_task_repository import ReviewTaskRepository

    ws_summary = SimpleNamespace(
        full_analysis=json.dumps({
            "expert_review": {
                "summary": "   ",
                "checks": [{"rule_key": "scope_realism"}],
            }
        })
    )
    assert ReviewTaskRepository._analysis_has_required_expert_review(ws_summary) is False


# ── P2-5: ReviewFileStorage upload_dir 配置注入 ──


def test_review_file_storage_default_upload_root():
    """未注入 upload_dir 时，默认回退到 runtime/data/review_uploads。"""
    from app.storage.review_file_storage import ReviewFileStorage
    from app.runtime_paths import runtime_path

    storage = ReviewFileStorage()
    default = storage._resolve_upload_root()
    assert default == str(runtime_path("data", "review_uploads"))


def test_review_file_storage_injected_upload_dir():
    """注入绝对路径时，_resolve_upload_root 直接返回该路径。"""
    from app.storage.review_file_storage import ReviewFileStorage

    custom_dir = "/tmp/custom_review_uploads"
    storage = ReviewFileStorage(upload_dir=custom_dir)
    assert storage._resolve_upload_root() == custom_dir


def test_review_file_storage_config_upload_dir(monkeypatch):
    """配置中有 review.upload.upload_dir 时，_resolve_upload_root 使用配置值。"""
    from app.storage.review_file_storage import ReviewFileStorage

    storage = ReviewFileStorage()

    monkeypatch.setattr("app.config.get_settings", lambda: {
        "review": {"upload": {"upload_dir": "/tmp/config_review_uploads"}},
    })
    assert storage._resolve_upload_root() == "/tmp/config_review_uploads"


def test_review_file_storage_relative_config_upload_dir(monkeypatch):
    """配置中 review.upload.upload_dir 为相对路径时，应转为 runtime 绝对路径。"""
    from app.storage.review_file_storage import ReviewFileStorage
    from app.runtime_paths import runtime_path

    storage = ReviewFileStorage()

    monkeypatch.setattr("app.config.get_settings", lambda: {
        "review": {"upload": {"upload_dir": "data/custom_uploads"}},
    })
    resolved = storage._resolve_upload_root()
    assert resolved == str(runtime_path("data", "custom_uploads"))
