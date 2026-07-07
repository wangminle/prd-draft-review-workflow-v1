"""Regression tests for BUG-108 / BUG-109 / BUG-110.

BUG-108: /api/workspace/{id}/sources 透传 owner_type=user&visibility=private，
         仓储层不绑定 owner_id，成员可枚举同空间他人私有资料元数据。
         修复：路由层拒绝 owner_type=user（个人资料走专门端点）。
BUG-109: budget_guard.get_monthly_token_usage 把 workspace_id IS NULL 的全局汇总行
         计入每个 workspace，导致 current_month_tokens 偏大、配额拦截误判。
         修复：只统计该 workspace 的专属行。
BUG-110: KnowledgeFileStorage.read_file/delete_file 在上传目录不存在时直接 iterdir，
         抛 FileNotFoundError，下载路径 500 而非 404。
         修复：先判断 root.exists()，缺失时返回 None/False。
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.review import CostDailySummary
from app.models.user import Base
from app.models.workspace import Workspace
from app.services.budget_guard import get_monthly_token_usage
from app.storage.knowledge_file_storage import KnowledgeFileStorage
from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def client_with_db():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_maker
    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _login_admin(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ─── BUG-108: 团队资料列表拒绝 owner_type=user ──────────────────────

@pytest.mark.asyncio
async def test_list_sources_rejects_owner_type_user(client_with_db):
    """owner_type=user 应被拒绝（防枚举同空间他人私有资料），即使 workspace 不存在也先 400。"""
    client, _ = client_with_db
    headers = await _login_admin(client)
    resp = await client.get(
        "/api/workspace/99999/sources?owner_type=user&visibility=private",
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "个人资料" in resp.text


@pytest.mark.asyncio
async def test_list_sources_allows_default_team_filter(client_with_db):
    """默认（不传 owner_type）不应被拒绝，回归确认合法路径不受影响。"""
    client, _ = client_with_db
    headers = await _login_admin(client)
    # workspace 不存在 → 404（在 owner_type 检查之后），不是 400
    resp = await client.get("/api/workspace/99999/sources", headers=headers)
    assert resp.status_code == 404, resp.text


# ─── BUG-109: 月度 token 用量不含 NULL workspace 行 ─────────────────

@pytest.mark.asyncio
async def test_monthly_token_usage_excludes_null_workspace_rows(db_session):
    """workspace_id IS NULL 的全局汇总行不应计入 per-workspace 用量。"""
    ws = Workspace(name="t109", status="active")
    db_session.add(ws)
    await db_session.flush()
    month = datetime.now().strftime("%Y-%m")
    db_session.add_all([
        CostDailySummary(
            workspace_id=ws.id, user_id=None, mode="chat",
            date=f"{month}-01", model_id="m",
            input_tokens=10, output_tokens=20, total_elapsed_ms=0,
        ),
        CostDailySummary(
            workspace_id=None, user_id=None, mode="chat",
            date=f"{month}-01", model_id="m",
            input_tokens=1, output_tokens=2, total_elapsed_ms=0,
        ),
    ])
    await db_session.flush()

    usage = await get_monthly_token_usage(db_session, ws.id)
    # 只算 workspace 专属行：10 + 20 = 30；不应包含 NULL 全局行 1 + 2
    assert usage == 30, f"应只算 workspace 专属行(30)，不含 NULL 全局行；实际 {usage}"


@pytest.mark.asyncio
async def test_monthly_token_usage_unassigned_workspace_zero(db_session):
    """查询不存在任何专属行的 workspace，返回 0（不被全局行污染）。"""
    ws = Workspace(name="t109b", status="active")
    db_session.add(ws)
    await db_session.flush()
    month = datetime.now().strftime("%Y-%m")
    db_session.add(CostDailySummary(
        workspace_id=None, user_id=None, mode="chat",
        date=f"{month}-01", model_id="m",
        input_tokens=100, output_tokens=200, total_elapsed_ms=0,
    ))
    await db_session.flush()

    usage = await get_monthly_token_usage(db_session, ws.id)
    assert usage == 0, f"无专属行的 workspace 应为 0；实际 {usage}"


# ─── BUG-110: 目录缺失不抛异常 ──────────────────────────────────────

def test_read_file_missing_dir_returns_none(tmp_path):
    """read_file 在上传目录不存在时返回 None（而非抛 FileNotFoundError）。"""
    st = KnowledgeFileStorage(str(tmp_path / "missing_dir"))
    assert st.read_file("abc") is None


def test_delete_file_missing_dir_returns_false(tmp_path):
    """delete_file 在上传目录不存在时返回 False（而非抛 FileNotFoundError）。"""
    st = KnowledgeFileStorage(str(tmp_path / "missing_dir"))
    assert st.delete_file("abc") is False


def test_read_delete_file_normal_path_still_works(tmp_path):
    """回归：目录存在 + 文件存在时，read/delete 行为不变。"""
    st = KnowledgeFileStorage(str(tmp_path / "kb"))
    stored = st.save_upload("note.txt", b"hello")
    content = st.read_file(stored.file_id)
    assert content == b"hello"
    assert st.delete_file(stored.file_id) is True
    assert st.read_file(stored.file_id) is None
