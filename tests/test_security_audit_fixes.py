"""安全审计修复回归：存储型 XSS、Agent 执行门控、上传资源限制、默认口令、授权唯一性。"""

from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.models.review import WorkspaceBudget
from app.models.user import AgentRun, Base, User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.auth import hash_password, verify_password
from app.services.file_text import extract_text_from_bytes
from tests.conftest import init_test_db, make_test_app

WORKSPACE_JS = (ROOT / "src/static/js/workspace.js").read_text(encoding="utf-8")
UPLOAD_PY = (ROOT / "src/app/routers/upload.py").read_text(encoding="utf-8")
AGENT_PY = (ROOT / "src/app/routers/agent.py").read_text(encoding="utf-8")


# ── 存储型 XSS ──────────────────────────────────────────────────────────────


def test_workspace_js_has_attr_escaper():
    assert "    _esc(str)" in WORKSPACE_JS or "    _esc(str) {" in WORKSPACE_JS
    assert "_escAttr(str)" in WORKSPACE_JS


def test_workspace_js_does_not_interpolate_dompurify_into_attributes():
    """DOMPurify.sanitize 不能用于双引号 HTML 属性：引号可逃逸成 onfocus/autofocus。"""
    attr_uses = re.findall(
        r'(?:data-source-title|data-username|title)=["\']\$\{DOMPurify\.sanitize',
        WORKSPACE_JS,
    )
    assert attr_uses == [], f"DOMPurify 仍被拼进属性: {attr_uses}"
    assert 'data-source-title="${this._escAttr(' in WORKSPACE_JS
    assert 'data-username="${this._escAttr(' in WORKSPACE_JS


def test_workspace_js_escapes_user_visible_text():
    assert "${this._esc(s.title)}" in WORKSPACE_JS
    assert "${this._esc(m.username" in WORKSPACE_JS


# ── DOCX zip bomb ───────────────────────────────────────────────────────────


def _minimal_docx_xml(text: str = "Hello") -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{ns}">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
        f"</w:document>"
    ).encode("utf-8")


def _docx_bytes(document_xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("[Content_Types].xml", b"<Types/>")
    return buf.getvalue()


def test_normal_docx_text_still_extracted():
    content = _docx_bytes(_minimal_docx_xml("安全抽取"))
    assert extract_text_from_bytes(content, "ok.docx") == "安全抽取"


def test_docx_zip_bomb_document_xml_rejected():
    """高压缩比的合法 XML 不得靠解压后再解析；应在读入前按压缩比拒绝。"""
    bomb = _docx_bytes(_minimal_docx_xml("A" * 300_000))
    assert extract_text_from_bytes(bomb, "bomb.docx") is None


# ── URL 抓取内存上限 ────────────────────────────────────────────────────────


def test_url_fetch_streams_and_caps_body():
    assert "aiter_bytes" in UPLOAD_PY
    assert "_MAX_URL_BODY_BYTES" in UPLOAD_PY
    submit_block = UPLOAD_PY.split("async def submit_url", 1)[1].split("def _html_to_text", 1)[0]
    assert "resp.text" not in submit_block


# ── 默认管理员口令 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_admin_does_not_use_well_known_password(tmp_path, monkeypatch, caplog):
    import app.database as database_module
    from app.database import DEFAULT_ADMIN_PASSWORD

    db_path = tmp_path / "bootstrap_random_admin.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.delenv("ADMIN_INITIAL_PASSWORD", raising=False)
    monkeypatch.delenv("ALLOW_DEFAULT_ADMIN_PASSWORD", raising=False)
    # BUG-194：隔离随机初始密码一次性文件的写入位置
    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path))

    with caplog.at_level("WARNING"):
        await database_module._ensure_default_admin()

    async with session_maker() as session:
        admin = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()

    assert verify_password(DEFAULT_ADMIN_PASSWORD, admin.password_hash) is False
    assert any("管理员账号已创建" in r.message for r in caplog.records)
    await engine.dispose()


@pytest.mark.asyncio
async def test_existing_default_password_blocks_startup(tmp_path, monkeypatch):
    import app.database as database_module
    from app.database import DEFAULT_ADMIN_PASSWORD

    db_path = tmp_path / "bootstrap_block_default.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(User(username="admin", password_hash=hash_password(DEFAULT_ADMIN_PASSWORD), role="admin"))
        await session.commit()

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.delenv("ALLOW_DEFAULT_ADMIN_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="默认"):
        await database_module._ensure_default_admin()

    await engine.dispose()


@pytest.mark.asyncio
async def test_allow_flag_permits_existing_default_password(tmp_path, monkeypatch, caplog):
    import app.database as database_module
    from app.database import DEFAULT_ADMIN_PASSWORD

    db_path = tmp_path / "bootstrap_allow_default.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(User(username="admin", password_hash=hash_password(DEFAULT_ADMIN_PASSWORD), role="admin"))
        await session.commit()

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.setenv("ALLOW_DEFAULT_ADMIN_PASSWORD", "1")

    with caplog.at_level("WARNING"):
        await database_module._ensure_default_admin()

    assert any("默认预设口令" in r.message or "弱口令" in r.message for r in caplog.records)
    await engine.dispose()


# ── Agent 执行门控 / 授权 ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def agent_client():
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


async def _admin_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_disabled_agent_cannot_execute_existing_run(agent_client):
    client, _ = agent_client
    headers = await _admin_headers(client)
    created = await client.post("/api/agent/runs", json={"goal": "已创建后再禁用"}, headers=headers)
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]
    await client.put("/api/agent/profile", json={"status": "disabled"}, headers=headers)

    with patch("app.services.agent_application_service.PiAgentBridge") as bridge_cls:
        bridge_cls.return_value.start = AsyncMock(return_value=True)
        resp = await client.post(f"/api/agent/runs/{run_id}/execute", headers=headers)

    assert resp.status_code == 400, resp.text
    assert "disabled" in resp.text.lower() or "禁用" in resp.text
    bridge_cls.assert_not_called()


@pytest.mark.asyncio
async def test_execute_enforces_workspace_budget(agent_client):
    client, session_maker = agent_client
    headers = await _admin_headers(client)
    created = await client.post("/api/agent/runs", json={"goal": "超配额"}, headers=headers)
    run_id = created.json()["id"]

    async with session_maker() as db:
        ws = (await db.execute(select(Workspace).where(Workspace.is_default.is_(True)))).scalar_one_or_none()
        if ws is None:
            ws = Workspace(name="默认空间", is_default=True, status="active")
            db.add(ws)
            await db.flush()
        db.add(WorkspaceBudget(
            workspace_id=ws.id,
            monthly_token_limit=0,
            hard_limit_action="block",
        ))
        await db.commit()

    with patch("app.services.agent_application_service.PiAgentBridge") as bridge_cls:
        bridge_cls.return_value.start = AsyncMock(return_value=True)
        resp = await client.post(f"/api/agent/runs/{run_id}/execute", headers=headers)

    assert resp.status_code == 429, resp.text
    bridge_cls.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_execute_claims_run_once(agent_client):
    client, session_maker = agent_client
    headers = await _admin_headers(client)
    created = await client.post("/api/agent/runs", json={"goal": "并发抢占"}, headers=headers)
    run_id = created.json()["id"]

    from app.repositories.agent_repository import AgentRunRepository

    async with session_maker() as db:
        repo = AgentRunRepository(db)
        first = await repo.try_claim_for_execution(run_id)
        second = await repo.try_claim_for_execution(run_id)
        assert first is not None
        assert first.status == "running"
        assert second is None


@pytest.mark.asyncio
async def test_duplicate_agent_authorization_rejected(agent_client):
    client, session_maker = agent_client
    headers = await _admin_headers(client)
    await client.get("/api/agent/profile", headers=headers)

    async with session_maker() as db:
        ws = Workspace(name="授权空间", is_default=False, status="active")
        db.add(ws)
        await db.flush()
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=admin.id, role="owner", status="active"))
        await db.commit()
        ws_id = ws.id

    payload = {
        "scope_type": "workspace",
        "scope_id": ws_id,
        "permissions": ["read", "search"],
    }
    first = await client.post("/api/agent/profile/authorizations", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    second = await client.post("/api/agent/profile/authorizations", json=payload, headers=headers)
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_rag_without_workspace_id_uses_authorized_workspace_not_default(agent_client):
    """未传 workspace_id 时不得回退未授权的全局默认空间。"""
    from app.services.pi_agent_bridge import set_run_token

    client, session_maker = agent_client
    headers = await _admin_headers(client)
    profile = await client.get("/api/agent/profile", headers=headers)
    profile_id = profile.json()["id"]
    owner_id = profile.json()["owner_id"]

    async with session_maker() as db:
        default_ws = Workspace(name="默认空间", is_default=True, status="active")
        other = Workspace(name="已授权空间", is_default=False, status="active")
        db.add_all([default_ws, other])
        await db.flush()
        db.add(WorkspaceMember(workspace_id=other.id, user_id=owner_id, role="member", status="active"))
        run = AgentRun(agent_id=profile_id, user_id=owner_id, goal="rag", status="running")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await db.refresh(other)
        run_id = run.id
        other_id = other.id

    auth = await client.post(
        "/api/agent/profile/authorizations",
        json={"scope_type": "workspace", "scope_id": other_id, "permissions": ["read", "search"]},
        headers=headers,
    )
    assert auth.status_code == 200, auth.text

    set_run_token(run_id, "tok-rag-no-default")
    resp = await client.post(
        f"/api/agent/runs/{run_id}/rag",
        json={"query": "资料", "scope": "workspace"},
        headers={"X-Agent-Run-Token": "tok-rag-no-default"},
    )
    assert resp.status_code == 200, resp.text


def test_execute_and_stream_share_prepare_gate():
    """同步 /execute 与 /stream 必须走同一套状态/启用/预算/抢占门控。"""
    assert "prepare_and_claim_run" in AGENT_PY
    exec_block = AGENT_PY.split("async def execute_agent_run", 1)[1].split("async def stream_agent_run", 1)[0]
    stream_block = AGENT_PY.split("async def stream_agent_run", 1)[1].split("# ─── Tool Registry", 1)[0]
    assert "prepare_and_claim_run" in exec_block
    assert "prepare_and_claim_run" in stream_block
    assert "ensure_workspace_llm_allowed" in exec_block or "prepare_and_claim_run" in exec_block
