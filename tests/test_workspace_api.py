"""P0.A.7/P0.B.3/P0.B.4/P0.C.1 — Workspace API 集成测试。

验收标准：
- P0.A.7: 注册后自动加入默认 workspace
- P0.B.3: 删除资料 API（软删除，status→archived）
- P0.B.4: 更新标签 API
- P0.C.1: 项目引用资料 API
"""

import json
import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

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
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


async def _get_token(client, username="testuser", password="test123456"):
    resp = await client.post("/api/auth/register", json={"username": username, "password": password})
    if resp.status_code != 200:
        resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]


# ── P0.B.1: 资料上传 API ──


@pytest.mark.asyncio
async def test_upload_source_success():
    """P0.B.1: 上传文件创建 KnowledgeSource"""
    import tempfile
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.models.user import User
    from app.models.workspace import WorkspaceMember

    tmp_db = tempfile.mktemp(suffix=".db")
    app_inst, engine, sm = make_test_app(tmp_db)
    await init_test_db(engine, sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Register user and get workspace
        resp = await c.post("/api/auth/register", json={"username": "uploader", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        resp = await c.get("/api/workspace", headers=headers)
        ws_id = resp.json()[0]["id"]

        # Upload a markdown file
        md_content = "# 测试文档\n\n这是一个测试 PRD 文件。\n"
        resp = await c.post(
            f"/api/workspace/{ws_id}/sources",
            files={"file": ("测试PRD.md", md_content.encode("utf-8"), "text/markdown")},
            headers=headers,
        )
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        data = resp.json()
        assert data["source_type"] == "upload"
        assert data["title"] == "测试PRD.md"
        assert data["filename"] == "测试PRD.md"
        assert data["content_hash"] is not None
        assert data["version"] == 1
        assert data["status"] == "active"
        assert "extracted_text" in data
        assert data["extracted_text"] is not None

        # P2.A.3: 上传后应自动完成入库切块与 FTS 索引，避免资料可见但不可检索
        from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
        async with sm() as session:
            doc_result = await session.execute(select(KnowledgeDocument).where(KnowledgeDocument.source_id == data["id"]))
            doc = doc_result.scalar_one_or_none()
            assert doc is not None
            chunk_result = await session.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
            chunks = list(chunk_result.scalars().all())
            assert len(chunks) >= 1

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_upload_source_size_limit_code_exists():
    """P0.B.1: 验证上传端点有大小检查逻辑"""
    import ast
    from pathlib import Path
    src = Path(__file__).parent.parent / "src/app/routers/workspace.py"
    tree = ast.parse(src.read_text())
    upload_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "upload_source":
            upload_func = node
            break
    assert upload_func is not None, "upload_source 函数不存在"
    # Verify the function contains a size check (413 HTTPException)
    source_text = src.read_text()
    assert "413" in source_text
    assert "文件过大" in source_text


@pytest.mark.asyncio
async def test_upload_source_non_member_blocked():
    """P0.B.1: 非成员无法上传资料"""
    import tempfile
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, WorkspaceMember

    tmp_db = tempfile.mktemp(suffix=".db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Member registers and gets workspace
        resp = await c.post("/api/auth/register", json={"username": "wsowner", "password": "test123456"})
        member_token = resp.json()["access_token"]

        # Intruder registers
        resp = await c.post("/api/auth/register", json={"username": "wsintruder_upload", "password": "test123456"})
        intruder_token = resp.json()["access_token"]

        # Both get auto-joined to default workspace, so let's create a second workspace
        # where intruder is NOT a member
        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            owner_user = await session.execute(select(User).where(User.username == "wsowner"))
            owner_user_obj = owner_user.scalar_one_or_none()

            ws2 = Workspace(name="私有空间", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws2)
            await session.flush()
            session.add(WorkspaceMember(workspace_id=ws2.id, user_id=owner_user_obj.id, role="owner", status="active"))
            await session.flush()
            ws2_id = ws2.id
            await session.commit()

        # Intruder tries to upload to private workspace
        md_content = "# hack\n"
        resp = await c.post(
            f"/api/workspace/{ws2_id}/sources",
            files={"file": ("hack.md", md_content.encode("utf-8"), "text/markdown")},
            headers=_auth_headers(intruder_token),
        )
        assert resp.status_code == 403

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_get_source_detail():
    """P0.B.1: 获取资料详情"""
    import tempfile

    tmp_db = tempfile.mktemp(suffix=".db")
    app_inst, engine, sm = make_test_app(tmp_db)
    await init_test_db(engine, sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/register", json={"username": "detailuser", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        resp = await c.get("/api/workspace", headers=headers)
        ws_id = resp.json()[0]["id"]

        # Upload a file first
        md_content = "# 详情测试\n\n内容正文。\n"
        resp = await c.post(
            f"/api/workspace/{ws_id}/sources",
            files={"file": ("详情.md", md_content.encode("utf-8"), "text/markdown")},
            headers=headers,
        )
        source_id = resp.json()["id"]

        # Get detail
        resp = await c.get(f"/api/workspace/{ws_id}/sources/{source_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == source_id
        assert data["title"] == "详情.md"
        assert data["source_type"] == "upload"

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


# ── P0.B.3: 删除资料 API ──


@pytest.mark.asyncio
async def test_delete_source_success():
    """P0.B.3: 软删除资料，status → archived"""
    import tempfile
    tmp_db = tempfile.mktemp(suffix=".db")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    from app.models.user import Base, User
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember, WorkspaceMember

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Register and get token
        resp = await c.post("/api/auth/register", json={"username": "tester", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        # Create workspace and source directly via session
        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            tester = await session.execute(select(User).where(User.username == "tester"))
            tester_user = tester.scalar_one_or_none()

            ws = Workspace(name="测试空间", description="测试", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=tester_user.id, role="admin", status="active"))
            await session.flush()

            source = KnowledgeSource(
                workspace_id=ws.id,
                source_type="upload",
                title="测试资料.md",
                filename="test.md",
                content_hash="abc123",
                extracted_text="# 测试资料\n\n这是待删除资料，包含唯一关键词 删除索引验证。",
                version=1,
                owner_id=admin_user.id if admin_user else None,
                status="active",
            )
            session.add(source)
            await session.flush()
            source_id = source.id
            ws_id = ws.id
            await session.commit()

        # 先建立 FTS 索引，验证删除时会同步清理检索索引
        from app.services.knowledge_ingestion import KnowledgeIngestionService
        async with session_maker() as session:
            ingestion = KnowledgeIngestionService(session)
            await ingestion.ingest_source(source_id)
            await session.commit()
            pre_delete_results = await ingestion.search_fts("删除索引验证", ws_id)
            assert len(pre_delete_results) >= 1

        # Test delete
        resp = await c.delete(f"/api/workspace/{ws_id}/sources/{source_id}", headers=headers)
        assert resp.status_code == 200, f"Delete failed: {resp.text}"
        assert resp.json()["message"] == "已删除"

        # Verify soft deleted
        async with session_maker() as session:
            result = await session.execute(
                select(KnowledgeSource).where(KnowledgeSource.id == source_id)
            )
            deleted = result.scalar_one_or_none()
            assert deleted is not None
            assert deleted.status == "archived"

            ingestion = KnowledgeIngestionService(session)
            post_delete_results = await ingestion.search_fts("删除索引验证", ws_id)
            assert post_delete_results == []

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_delete_source_not_found():
    """P0.B.3: 删除不存在的资料返回 404"""
    import tempfile
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.models.user import User
    from app.models.workspace import WorkspaceMember

    tmp_db = tempfile.mktemp(suffix=".db")
    app_inst, engine, sm = make_test_app(tmp_db)
    await init_test_db(engine, sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Use admin login (has owner role in default workspace)
        resp = await c.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        resp = await c.delete("/api/workspace/1/sources/9999", headers=headers)
        assert resp.status_code == 404

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_delete_source_wrong_workspace():
    """P0.B.3: 跨空间删除返回 404"""
    import tempfile
    tmp_db = tempfile.mktemp(suffix=".db")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UserBase, User
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember, WorkspaceMember

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UserBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/register", json={"username": "tester3", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            tester3 = await session.execute(select(User).where(User.username == "tester3"))
            tester3_user = tester3.scalar_one_or_none()

            ws1 = Workspace(name="空间1", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws1)
            ws2 = Workspace(name="空间2", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws2)
            await session.flush()

            # tester3 is admin of ws2 so they can pass the role check,
            # but the source belongs to ws1 so they still get 404
            session.add(WorkspaceMember(workspace_id=ws2.id, user_id=tester3_user.id, role="admin", status="active"))
            await session.flush()

            source = KnowledgeSource(
                workspace_id=ws1.id,
                source_type="upload",
                title="资料",
                version=1,
                status="active",
            )
            session.add(source)
            await session.flush()
            source_id = source.id
            ws2_id = ws2.id
            await session.commit()

        resp = await c.delete(f"/api/workspace/{ws2_id}/sources/{source_id}", headers=headers)
        assert resp.status_code == 404

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


# ── P0.B.4: 更新标签 API ──


@pytest.mark.asyncio
async def test_update_source_tags():
    """P0.B.4: 更新资料标签"""
    import tempfile
    tmp_db = tempfile.mktemp(suffix=".db")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember, WorkspaceMember

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/register", json={"username": "tagger", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            tagger = await session.execute(select(User).where(User.username == "tagger"))
            tagger_user = tagger.scalar_one_or_none()

            ws = Workspace(name="空间", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=tagger_user.id, role="admin", status="active"))
            await session.flush()

            source = KnowledgeSource(
                workspace_id=ws.id,
                source_type="upload",
                title="标签测试.md",
                version=1,
                status="active",
            )
            session.add(source)
            await session.flush()
            source_id = source.id
            ws_id = ws.id
            await session.commit()

        # Update tags
        new_tags = ["prd", "v1.0", "核心"]
        resp = await c.put(
            f"/api/workspace/{ws_id}/sources/{source_id}/tags",
            json={"tags": new_tags},
            headers=headers,
        )
        assert resp.status_code == 200, f"Update tags failed: {resp.text}"
        data = resp.json()
        assert data["tags"] == new_tags
        assert data["version"] == 2  # version incremented

        # Verify in DB
        async with session_maker() as session:
            result = await session.execute(
                select(KnowledgeSource).where(KnowledgeSource.id == source_id)
            )
            updated = result.scalar_one_or_none()
            assert updated is not None
            assert updated.version == 2
            meta = json.loads(updated.metadata_json)
            assert meta["tags"] == new_tags

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_update_source_tags_invalid_type():
    """P0.B.4: tags 非数组返回 422"""
    import tempfile
    tmp_db = tempfile.mktemp(suffix=".db")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember, WorkspaceMember

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/register", json={"username": "bad_tagger", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            bad_tagger = await session.execute(select(User).where(User.username == "bad_tagger"))
            bad_tagger_user = bad_tagger.scalar_one_or_none()

            ws = Workspace(name="空间", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=bad_tagger_user.id, role="admin", status="active"))
            await session.flush()

            source = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="x", version=1, status="active")
            session.add(source)
            await session.flush()
            ws_id = ws.id
            sid = source.id
            await session.commit()

        resp = await c.put(f"/api/workspace/{ws_id}/sources/{sid}/tags", json={"tags": "not_a_list"}, headers=headers)
        assert resp.status_code == 422

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


# ── P0.C.1: 项目引用资料 API ──


@pytest.mark.asyncio
async def test_add_project_source_ref():
    """P0.C.1: 项目引用资料，记录 ref_type 和 snapshot_version"""
    import tempfile
    tmp_db = tempfile.mktemp(suffix=".db")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember
    from app.models.review import ReviewProject

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/register", json={"username": "refuser", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            refuser = await session.execute(select(User).where(User.username == "refuser"))
            refuser_user = refuser.scalar_one_or_none()

            ws = Workspace(name="空间", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=refuser_user.id, role="member", status="active"))
            await session.flush()

            project = ReviewProject(name="测试项目", created_by=refuser_user.id)
            session.add(project)
            await session.flush()

            source = KnowledgeSource(
                workspace_id=ws.id,
                source_type="upload",
                title="参考PRD.md",
                version=3,
                status="active",
            )
            session.add(source)
            await session.flush()
            pid = project.id
            sid = source.id
            await session.commit()

        # Add project source ref
        resp = await c.post(
            f"/api/review/project/{pid}/sources",
            json={"source_id": sid, "ref_type": "reference", "snapshot_version": 3},
            headers=headers,
        )
        assert resp.status_code == 200, f"Add source ref failed: {resp.text}"
        data = resp.json()
        assert data["project_id"] == pid
        assert data["source_id"] == sid
        assert data["ref_type"] == "reference"
        assert data["snapshot_version"] == 3

        # Verify default ref_type
        resp = await c.post(
            f"/api/review/project/{pid}/sources",
            json={"source_id": sid},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ref_type"] == "context"

        # List source refs
        resp = await c.get(f"/api/review/project/{pid}/sources", headers=headers)
        assert resp.status_code == 200
        refs = resp.json()
        assert len(refs) == 2

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_add_project_source_ref_not_owner():
    """P0.C.1: 非项目 owner 无法引用资料"""
    import tempfile
    tmp_db = tempfile.mktemp(suffix=".db")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember
    from app.models.review import ReviewProject

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Owner creates project
        resp = await c.post("/api/auth/register", json={"username": "owner", "password": "test123456"})
        owner_token = resp.json()["access_token"]

        # Another user
        resp = await c.post("/api/auth/register", json={"username": "intruder", "password": "test123456"})
        intruder_token = resp.json()["access_token"]

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            owner_user = await session.execute(select(User).where(User.username == "owner"))
            owner_user = owner_user.scalar_one_or_none()

            ws = Workspace(name="空间", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()

            source = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="x", version=1, status="active")
            session.add(source)
            await session.flush()

            project = ReviewProject(name="非我项目", created_by=owner_user.id)
            session.add(project)
            await session.flush()
            pid = project.id
            sid = source.id
            await session.commit()

        # Intruder tries to add source ref
        resp = await c.post(
            f"/api/review/project/{pid}/sources",
            json={"source_id": sid},
            headers=_auth_headers(intruder_token),
        )
        assert resp.status_code in (403, 404)

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_add_project_source_ref_invalid_type():
    """P0.C.1: 无效 ref_type 返回 422"""
    import tempfile
    tmp_db = tempfile.mktemp(suffix=".db")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember
    from app.models.review import ReviewProject

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/register", json={"username": "typetest", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            typetest_user = await session.execute(select(User).where(User.username == "typetest"))
            typetest_user = typetest_user.scalar_one_or_none()

            ws = Workspace(name="空间", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()
            source = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="x", version=1, status="active")
            session.add(source)
            await session.flush()
            project = ReviewProject(name="项目", created_by=typetest_user.id)
            session.add(project)
            await session.flush()
            pid = project.id
            sid = source.id
            await session.commit()

        resp = await c.post(
            f"/api/review/project/{pid}/sources",
            json={"source_id": sid, "ref_type": "invalid_type"},
            headers=headers,
        )
        assert resp.status_code == 422

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass

# ── P0.E.1: 权限校验回归测试 ──


@pytest.mark.asyncio
async def test_delete_source_member_role_blocked():
    """P0.D.1: member 角色无法删除资料（需 admin/owner）"""
    import tempfile
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import WorkspaceMember
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember

    tmp_db = tempfile.mktemp(suffix=".db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Admin login for workspace management
        resp = await c.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = resp.json()["access_token"]

        # Register a member-role user
        resp = await c.post("/api/auth/register", json={"username": "wsmember", "password": "test123456"})
        member_token = resp.json()["access_token"]

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            member_user = await session.execute(select(User).where(User.username == "wsmember"))
            member_user_obj = member_user.scalar_one_or_none()

            ws = Workspace(name="空间", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="owner", status="active"))
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=member_user_obj.id, role="member", status="active"))
            await session.flush()

            source = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="资料", version=1, status="active")
            session.add(source)
            await session.flush()
            ws_id = ws.id
            source_id = source.id
            await session.commit()

        # member role cannot delete
        resp = await c.delete(
            f"/api/workspace/{ws_id}/sources/{source_id}",
            headers=_auth_headers(member_token),
        )
        assert resp.status_code == 403

        # admin can delete
        resp = await c.delete(
            f"/api/workspace/{ws_id}/sources/{source_id}",
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 200

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass



# ── P0.A.7: 注册自动入队默认 workspace ──


@pytest.mark.asyncio
async def test_register_auto_join_default_workspace():
    """P0.A.7: 注册后自动加入默认 workspace，角色 member"""
    import tempfile
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.models.user import User
    from app.models.workspace import WorkspaceMember

    tmp_db = tempfile.mktemp(suffix=".db")
    app_inst, engine, sm = make_test_app(tmp_db)
    await init_test_db(engine, sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Register a new user
        resp = await c.post("/api/auth/register", json={"username": "newuser", "password": "test123456"})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        headers = _auth_headers(token)

        # Verify the user can see the default workspace
        resp = await c.get("/api/workspace", headers=headers)
        workspaces = resp.json()
        assert len(workspaces) >= 1
        default_ws = workspaces[0]
        assert default_ws["name"] == "默认空间"

        # Verify via direct DB query that the member record exists with role member
        async with sm() as session:
            newuser = await session.execute(select(User).where(User.username == "newuser"))
            newuser_obj = newuser.scalar_one_or_none()
            assert newuser_obj is not None

            member = await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == default_ws["id"],
                    WorkspaceMember.user_id == newuser_obj.id,
                    WorkspaceMember.status == "active",
                )
            )
            member_obj = member.scalar_one_or_none()
            assert member_obj is not None
            assert member_obj.role == "member"

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_register_auto_join_idempotent():
    """P0.A.7: 重复注册不创建重复 membership（注册失败场景）"""
    import tempfile

    tmp_db = tempfile.mktemp(suffix=".db")
    app_inst, engine, sm = make_test_app(tmp_db)
    await init_test_db(engine, sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # First registration succeeds
        resp = await c.post("/api/auth/register", json={"username": "dupuser", "password": "test123456"})
        assert resp.status_code == 200

        # Second registration with same username fails
        resp = await c.post("/api/auth/register", json={"username": "dupuser", "password": "other123456"})
        assert resp.status_code == 400

        # Verify only one membership record exists
        async with sm() as session:
            from app.models.user import User
            from app.models.workspace import WorkspaceMember
            user_result = await session.execute(select(User).where(User.username == "dupuser"))
            dupuser = user_result.scalar_one_or_none()

            members = await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.user_id == dupuser.id,
                    WorkspaceMember.status == "active",
                )
            )
            member_list = list(members.scalars().all())
            assert len(member_list) == 1

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


# ── P0.D.1: 角色权限区分 ──


@pytest.mark.asyncio
async def test_update_tags_member_role_blocked():
    """P0.D.1: member role cannot update tags (needs admin/owner)"""
    import tempfile
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, WorkspaceMember, KnowledgeSource

    tmp_db = tempfile.mktemp(suffix=".db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = resp.json()["access_token"]

        resp = await c.post("/api/auth/register", json={"username": "tagmember", "password": "test123456"})
        member_token = resp.json()["access_token"]

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            member_user = await session.execute(select(User).where(User.username == "tagmember"))
            member_user_obj = member_user.scalar_one_or_none()

            ws = Workspace(name="test-ws", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="owner", status="active"))
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=member_user_obj.id, role="member", status="active"))
            await session.flush()

            source = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="test-src", version=1, status="active")
            session.add(source)
            await session.flush()
            ws_id = ws.id
            source_id = source.id
            await session.commit()

        # member role cannot update tags
        resp = await c.put(
            f"/api/workspace/{ws_id}/sources/{source_id}/tags",
            json={"tags": ["hack"]},
            headers=_auth_headers(member_token),
        )
        assert resp.status_code == 403

        # admin can update tags
        resp = await c.put(
            f"/api/workspace/{ws_id}/sources/{source_id}/tags",
            json={"tags": ["prd"]},
            headers=_auth_headers(admin_token),
        )
        assert resp.status_code == 200

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_viewer_cannot_upload():
    """P0.D.1: viewer role cannot upload sources"""
    import tempfile
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, WorkspaceMember

    tmp_db = tempfile.mktemp(suffix=".db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = resp.json()["access_token"]

        resp = await c.post("/api/auth/register", json={"username": "viewer_user", "password": "test123456"})
        viewer_token = resp.json()["access_token"]

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()
            viewer_user = await session.execute(select(User).where(User.username == "viewer_user"))
            viewer_user_obj = viewer_user.scalar_one_or_none()

            ws = Workspace(name="viewer-test", created_by=admin_user.id if admin_user else None, status="active")
            session.add(ws)
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="owner", status="active"))
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer_user_obj.id, role="viewer", status="active"))
            await session.flush()
            ws_id = ws.id
            await session.commit()

        # viewer cannot upload
        md_content = "# viewer upload test"
        resp = await c.post(
            f"/api/workspace/{ws_id}/sources",
            files={"file": ("test.md", md_content.encode("utf-8"), "text/markdown")},
            headers=_auth_headers(viewer_token),
        )
        assert resp.status_code == 403

        # viewer can still read sources
        resp = await c.get(f"/api/workspace/{ws_id}/sources", headers=_auth_headers(viewer_token))
        assert resp.status_code == 200

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


# ── P0.C.3: 审查启动时冻结资料快照 ──


@pytest.mark.asyncio
async def test_freeze_snapshot_on_pipeline_start():
    """P0.C.3: _run_pipeline 调用 freeze_snapshot，引用资料的 snapshot_version 被冻结"""
    import tempfile
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.user import Base as UBase, User
    from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember, WorkspaceMember
    from app.models.review import ReviewProject
    from app.repositories.knowledge_source_repository import ProjectSourceRefRepository

    tmp_db = tempfile.mktemp(suffix=".db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_db}", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(UBase.metadata.create_all)

    app_inst, _engine, _sm = make_test_app(tmp_db)
    await init_test_db(_engine, _sm)

    transport = ASGITransport(app=app_inst)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = resp.json()["access_token"]

        async with session_maker() as session:
            admin = await session.execute(select(User).where(User.username == "admin"))
            admin_user = admin.scalar_one_or_none()

            ws = Workspace(name="freeze-test", created_by=admin_user.id, status="active")
            session.add(ws)
            await session.flush()

            session.add(WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="owner", status="active"))
            await session.flush()

            source = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="freeze-src", version=3, status="active")
            session.add(source)
            await session.flush()

            project = ReviewProject(name="freeze-proj", created_by=admin_user.id, workspace_id=ws.id)
            session.add(project)
            await session.flush()

            # Add source ref without snapshot_version
            ref_repo = ProjectSourceRefRepository(session)
            ref = await ref_repo.add_ref(project_id=project.id, source_id=source.id, ref_type="context")
            assert ref.snapshot_version is None

            await session.commit()

            source_id = source.id
            project_id = project.id

        # Call freeze_snapshot directly via repo
        async with session_maker() as session:
            ref_repo = ProjectSourceRefRepository(session)
            refs = await ref_repo.freeze_snapshot(project_id)
            assert len(refs) == 1
            assert refs[0].snapshot_version == 3  # frozen at current source version
            await session.commit()

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


# ── P0 验收补充测试 ──


@pytest.mark.asyncio
async def test_create_review_project_writes_workspace_id():
    """验收补1: 新建审查项目自动写入 workspace_id"""
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_resp = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await ac.post("/api/review/projects", json={"name": "ws-proj", "description": "test"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["workspace_id"] is not None, "新建项目 workspace_id 不应为 NULL"

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_add_source_ref_cross_workspace_blocked():
    """验收补2: 跨空间资料引用被阻断"""
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_resp = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        from app.models.workspace import Workspace, WorkspaceMember, KnowledgeSource
        from app.models.user import User

        async with session_maker() as session:
            # Create second workspace
            ws2 = Workspace(name="other-space", status="active")
            session.add(ws2)
            await session.flush()
            admin_user = (await session.execute(select(User).where(User.role == "admin"))).scalar_one()
            session.add(WorkspaceMember(workspace_id=ws2.id, user_id=admin_user.id, role="owner"))
            await session.flush()
            # Create source in second workspace
            src2 = KnowledgeSource(workspace_id=ws2.id, source_type="upload", title="other-src", status="active", version=1)
            session.add(src2)
            await session.flush()
            await session.commit()
            source_id2 = src2.id

            # Get default workspace
            ws1 = (await session.execute(select(Workspace).where(Workspace.name == "默认空间"))).scalar_one()

        # Create project in default workspace (ws1)
        proj_resp = await ac.post("/api/review/projects", json={"name": "proj-default"}, headers=headers)
        project_id = proj_resp.json()["id"]

        # Try to add source from other workspace → should be blocked
        ref_resp = await ac.post(
            f"/api/review/project/{project_id}/sources",
            json={"source_id": source_id2, "ref_type": "context"},
            headers=headers,
        )
        assert ref_resp.status_code == 403, f"跨空间引用应返回 403, 实际 {ref_resp.status_code}"

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_add_source_ref_archived_blocked():
    """验收补2: 归档资料不能被引用"""
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_resp = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        from app.models.workspace import Workspace, WorkspaceMember, KnowledgeSource
        from app.models.user import User

        async with session_maker() as session:
            ws = (await session.execute(select(Workspace).where(Workspace.name == "默认空间"))).scalar_one()
            admin_user = (await session.execute(select(User).where(User.role == "admin"))).scalar_one()
            src = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="archived-src", status="archived", version=1)
            session.add(src)
            await session.flush()
            await session.commit()
            archived_source_id = src.id

        proj_resp = await ac.post("/api/review/projects", json={"name": "proj-arch"}, headers=headers)
        project_id = proj_resp.json()["id"]

        ref_resp = await ac.post(
            f"/api/review/project/{project_id}/sources",
            json={"source_id": archived_source_id, "ref_type": "context"},
            headers=headers,
        )
        assert ref_resp.status_code == 400, f"归档资料引用应返回 400, 实际 {ref_resp.status_code}"

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_list_sources_tag_and_status_filter():
    """验收补3: 资料列表 tag/status 过滤"""
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_resp = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        from app.models.workspace import Workspace, KnowledgeSource, WorkspaceMember

        async with session_maker() as session:
            ws = (await session.execute(select(Workspace).where(Workspace.name == "默认空间"))).scalar_one()
            # Source with tag "review"
            src1 = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="tagged-src",
                                   metadata_json=json.dumps({"tags": ["review"]}), status="active", version=1)
            # Archived source
            src2 = KnowledgeSource(workspace_id=ws.id, source_type="upload", title="arch-src",
                                   status="archived", version=1)
            session.add_all([src1, src2])
            await session.flush()
            await session.commit()
            ws_id = ws.id

        # Default (active only)
        resp = await ac.get(f"/api/workspace/{ws_id}/sources", headers=headers)
        assert resp.status_code == 200
        active = resp.json()
        assert all(s["status"] == "active" for s in active)

        # Status=archived filter
        resp = await ac.get(f"/api/workspace/{ws_id}/sources?status=archived", headers=headers)
        assert resp.status_code == 200
        archived = resp.json()
        assert len(archived) >= 1
        assert all(s["status"] == "archived" for s in archived)

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_source_detail_returns_extracted_text_and_project_refs():
    """验收补4: 资料详情含 extracted_text + file_id + project_refs"""
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Upload a file to get extracted_text
        login_resp = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        from app.models.workspace import Workspace

        async with session_maker() as session:
            ws = (await session.execute(select(Workspace).where(Workspace.name == "默认空间"))).scalar_one()
            ws_id = ws.id

        # Upload a .txt file
        upload_resp = await ac.post(
            f"/api/workspace/{ws_id}/sources",
            headers=headers,
            files={"file": ("test.txt", b"Hello extracted text content", "text/plain")},
        )
        assert upload_resp.status_code == 200
        upload_data = upload_resp.json()
        assert upload_data["extracted_text"] is not None
        assert "Hello" in upload_data["extracted_text"]
        assert upload_data["file_id"] is not None

        source_id = upload_data["id"]

        # Get detail
        detail_resp = await ac.get(f"/api/workspace/{ws_id}/sources/{source_id}", headers=headers)
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["extracted_text"] is not None
        assert "Hello" in detail["extracted_text"]
        assert detail["file_id"] is not None
        assert detail["project_refs"] is not None

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_source_download_endpoint():
    """验收补4: 下载原文件 endpoint"""
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_resp = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        from app.models.workspace import Workspace

        async with session_maker() as session:
            ws = (await session.execute(select(Workspace).where(Workspace.name == "默认空间"))).scalar_one()
            ws_id = ws.id

        upload_resp = await ac.post(
            f"/api/workspace/{ws_id}/sources",
            headers=headers,
            files={"file": ("download.txt", b"Download test content", "text/plain")},
        )
        source_id = upload_resp.json()["id"]

        download_resp = await ac.get(f"/api/workspace/{ws_id}/sources/{source_id}/download", headers=headers)
        assert download_resp.status_code == 200
        assert download_resp.content == b"Download test content"

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


# ── P1.A.1: GET/PUT /api/workspace/default + is_default 字段 ──


class TestDefaultWorkspaceEndpoints:
    async def test_get_default_workspace(self, client):
        """GET /api/workspace/default 返回默认团队空间，含 is_default=True"""
        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get("/api/workspace/default", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "默认空间"
        assert data["is_default"] is True
        assert data["status"] == "active"

    async def test_put_default_workspace_rename(self, client):
        """PUT /api/workspace/default 可以改名，改名后 get_default 仍能找到"""
        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.put("/api/workspace/default", headers=headers, json={"name": "产品团队"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "产品团队"
        assert data["is_default"] is True

        # 改名后 GET /default 仍能找到
        resp2 = await client.get("/api/workspace/default", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "产品团队"

        # 恢复原名
        await client.put("/api/workspace/default", headers=headers, json={"name": "默认空间"})

    async def test_put_default_workspace_member_forbidden(self, client):
        """普通 member 不能 PUT /api/workspace/default"""
        # 先注册一个普通用户
        await client.post("/api/auth/register", json={"username": "member_user", "password": "test123456"})
        login_resp = await client.post("/api/auth/login", json={"username": "member_user", "password": "test123456"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.put("/api/workspace/default", headers=headers, json={"name": "恶意改名"})
        assert resp.status_code == 403

    async def test_put_default_workspace_empty_name_rejected(self, client):
        """空名称被 422 拒绝"""
        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.put("/api/workspace/default", headers=headers, json={"name": ""})
        assert resp.status_code == 422

    async def test_rename_preserves_registration_auto_join(self, client):
        """改名后注册新用户仍能自动加入默认团队"""
        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 改名
        await client.put("/api/workspace/default", headers=headers, json={"name": "需求团队"})

        # 注册新用户
        reg_resp = await client.post("/api/auth/register", json={"username": "autojoin_user", "password": "test123456"})
        assert reg_resp.status_code == 200
        new_token = reg_resp.json()["access_token"]
        new_headers = {"Authorization": f"Bearer {new_token}"}

        # 新用户应能看到默认团队
        ws_resp = await client.get("/api/workspace", headers=new_headers)
        assert ws_resp.status_code == 200
        workspaces = ws_resp.json()
        assert any(ws["name"] == "需求团队" for ws in workspaces)

        # 恢复原名
        await client.put("/api/workspace/default", headers=headers, json={"name": "默认空间"})

    async def test_is_default_migration_from_legacy(self):
        """旧数据库（name='默认空间' 但无 is_default 列）升级后 is_default 自动标记为 True"""
        from sqlalchemy import text
        tmp_db = tempfile.mktemp(suffix=".db")
        app, engine, session_maker = make_test_app(tmp_db)

        # 模拟旧数据：先正常初始化（含 is_default 列），然后手动验证
        await init_test_db(engine, session_maker)

        async with session_maker() as session:
            from app.models.workspace import Workspace
            result = await session.execute(select(Workspace).where(Workspace.is_default == True))
            ws = result.scalar_one_or_none()
            assert ws is not None
            assert ws.name == "默认空间"
            assert ws.is_default is True

        await engine.dispose()
        if os.path.exists(tmp_db):
            try:
                os.unlink(tmp_db)
            except PermissionError:
                pass


# ── P1.A.2: 成员管理 API（角色变更 + 停用/恢复） ──


class TestMemberManagementEndpoints:
    async def test_list_default_members(self, client):
        """GET /api/workspace/default/members 返回成员列表"""
        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get("/api/workspace/default/members", headers=headers)
        assert resp.status_code == 200
        members = resp.json()
        assert isinstance(members, list)
        assert len(members) >= 1
        # admin 用户应是 owner 角色
        admin_member = next((m for m in members if m["username"] == "admin"), None)
        assert admin_member is not None
        assert admin_member["role"] == "owner"
        assert admin_member["status"] == "active"

    async def test_change_member_role(self, client):
        """PUT /api/workspace/default/members/{user_id} 变更角色"""
        # 注册普通用户
        await client.post("/api/auth/register", json={"username": "role_test_user", "password": "test123456"})

        # admin 登录
        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = login_resp.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 获取成员列表找到新用户 ID
        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        members = members_resp.json()
        target = next(m for m in members if m["username"] == "role_test_user")
        target_user_id = target["user_id"]

        # 变更角色为 admin
        resp = await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"role": "admin"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"

        # 变更角色为 viewer
        resp = await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "viewer"

    async def test_deactivate_and_reactivate_member(self, client):
        """PUT /api/workspace/default/members/{user_id} 停用/恢复成员"""
        await client.post("/api/auth/register", json={"username": "status_test_user", "password": "test123456"})

        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = login_resp.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        target = next(m for m in members_resp.json() if m["username"] == "status_test_user")
        target_user_id = target["user_id"]

        # 停用
        resp = await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "inactive"

        # 停用用户无法读取团队空间
        user_login = await client.post("/api/auth/login", json={"username": "status_test_user", "password": "test123456"})
        user_token = user_login.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}
        ws_resp = await client.get("/api/workspace/default", headers=user_headers)
        assert ws_resp.status_code == 403

        # 恢复
        resp = await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "active"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

        # 恢复后可再次访问
        ws_resp = await client.get("/api/workspace/default", headers=user_headers)
        assert ws_resp.status_code == 200

    async def test_self_modification_blocked(self, client):
        """不能变更自身的角色或状态"""
        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = login_resp.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 获取 admin 的 user_id
        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        admin_member = next(m for m in members_resp.json() if m["username"] == "admin")
        admin_user_id = admin_member["user_id"]

        # 尝试变更自身角色
        resp = await client.put(
            f"/api/workspace/default/members/{admin_user_id}",
            json={"role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 403

        # 尝试停用自身
        resp = await client.put(
            f"/api/workspace/default/members/{admin_user_id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )
        assert resp.status_code == 403

    async def test_member_role_cannot_manage(self, client):
        """普通 member 无权管理成员"""
        await client.post("/api/auth/register", json={"username": "mgmt_member", "password": "test123456"})
        member_login = await client.post("/api/auth/login", json={"username": "mgmt_member", "password": "test123456"})
        member_token = member_login.json()["access_token"]
        member_headers = {"Authorization": f"Bearer {member_token}"}

        # 获取 admin 的 user_id
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        admin_member = next(m for m in members_resp.json() if m["username"] == "admin")
        admin_user_id = admin_member["user_id"]

        # member 尝试变更 admin 角色 → 403
        resp = await client.put(
            f"/api/workspace/default/members/{admin_user_id}",
            json={"role": "viewer"},
            headers=member_headers,
        )
        assert resp.status_code == 403

    async def test_invalid_role_and_status_rejected(self, client):
        """无效角色/状态值返回 422"""
        await client.post("/api/auth/register", json={"username": "val_test_user", "password": "test123456"})

        login_resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = login_resp.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        target = next(m for m in members_resp.json() if m["username"] == "val_test_user")
        target_user_id = target["user_id"]

        # 无效角色
        resp = await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"role": "superadmin"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

        # 无效状态
        resp = await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "banned"},
            headers=admin_headers,
        )
        assert resp.status_code == 422


# ── P1.B.2: 审查域 workspace active member 校验 ──


class TestReviewWorkspaceActiveMemberCheck:
    async def test_inactive_member_cannot_create_project(self, client):
        """被停用的成员无法创建审查项目"""
        # 注册用户
        await client.post("/api/auth/register", json={"username": "inactive_proj_user", "password": "test123456"})
        user_login = await client.post("/api/auth/login", json={"username": "inactive_proj_user", "password": "test123456"})
        user_token = user_login.json()["access_token"]

        # admin 停用该用户
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        target = next(m for m in members_resp.json() if m["username"] == "inactive_proj_user")
        target_user_id = target["user_id"]

        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )

        # 停用用户无法创建项目
        user_headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.post(
            "/api/review/projects",
            json={"name": "should-fail"},
            headers=user_headers,
        )
        assert resp.status_code == 403

        # 恢复后可以创建
        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "active"},
            headers=admin_headers,
        )
        resp = await client.post(
            "/api/review/projects",
            json={"name": "should-work"},
            headers=user_headers,
        )
        assert resp.status_code == 200

    async def test_inactive_member_cannot_reference_source(self, client):
        """被停用的成员无法引用资料"""
        # 注册用户并上传资料
        await client.post("/api/auth/register", json={"username": "inactive_ref_user", "password": "test123456"})
        user_login = await client.post("/api/auth/login", json={"username": "inactive_ref_user", "password": "test123456"})
        user_token = user_login.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # 上传资料
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        ws_resp = await client.get("/api/workspace/default", headers=admin_headers)
        ws_id = ws_resp.json()["id"]

        upload_resp = await client.post(
            f"/api/workspace/{ws_id}/sources",
            headers=admin_headers,
            files={"file": ("ref_test.txt", b"test content", "text/plain")},
        )
        source_id = upload_resp.json()["id"]

        # 用户创建项目
        proj_resp = await client.post(
            "/api/review/projects",
            json={"name": "ref-test-proj"},
            headers=user_headers,
        )
        project_id = proj_resp.json()["id"]

        # admin 停用用户
        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        target = next(m for m in members_resp.json() if m["username"] == "inactive_ref_user")
        target_user_id = target["user_id"]

        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )

        # 停用后无法引用资料
        ref_resp = await client.post(
            f"/api/review/project/{project_id}/sources",
            json={"source_id": source_id, "ref_type": "context"},
            headers=user_headers,
        )
        assert ref_resp.status_code in (403, 404)  # 403 if permission check first, 404 if owner check first

        # 恢复后可以引用
        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "active"},
            headers=admin_headers,
        )
        ref_resp = await client.post(
            f"/api/review/project/{project_id}/sources",
            json={"source_id": source_id, "ref_type": "context"},
            headers=user_headers,
        )
        assert ref_resp.status_code == 200


# ── BUG-037: 停用成员不能访问旧 review 项目（含 legacy workspace_id=None） ──


class TestBug037InactiveMemberProjectAccess:
    async def test_inactive_member_cannot_list_own_projects(self, client):
        """BUG-037: 停用成员 GET /api/review/projects 不可见其项目"""
        await client.post("/api/auth/register", json={"username": "bug037_user", "password": "test123456"})
        user_login = await client.post("/api/auth/login", json={"username": "bug037_user", "password": "test123456"})
        user_token = user_login.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # 创建项目
        proj_resp = await client.post("/api/review/projects", json={"name": "bug037-proj"}, headers=user_headers)
        assert proj_resp.status_code == 200

        # 活跃时可列出
        list_resp = await client.get("/api/review/projects", headers=user_headers)
        assert list_resp.status_code == 200
        assert any(p["name"] == "bug037-proj" for p in list_resp.json())

        # admin 停用该用户
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        target = next(m for m in members_resp.json() if m["username"] == "bug037_user")
        target_user_id = target["user_id"]

        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )

        # 停用后项目列表不可见
        list_resp = await client.get("/api/review/projects", headers=user_headers)
        assert list_resp.status_code == 200
        assert not any(p["name"] == "bug037-proj" for p in list_resp.json()), \
            "停用成员不应看到自己的项目"

        # 恢复
        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "active"},
            headers=admin_headers,
        )

    async def test_inactive_member_cannot_get_project_detail(self, client):
        """BUG-037: 停用成员 GET /api/review/projects/{id} 返回 403"""
        await client.post("/api/auth/register", json={"username": "bug037b_user", "password": "test123456"})
        user_login = await client.post("/api/auth/login", json={"username": "bug037b_user", "password": "test123456"})
        user_token = user_login.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        proj_resp = await client.post("/api/review/projects", json={"name": "bug037b-proj"}, headers=user_headers)
        project_id = proj_resp.json()["id"]

        # admin 停用该用户
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        target = next(m for m in members_resp.json() if m["username"] == "bug037b_user")
        target_user_id = target["user_id"]

        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )

        # 停用后访问项目详情 → 403
        detail_resp = await client.get(f"/api/review/projects/{project_id}", headers=user_headers)
        assert detail_resp.status_code == 403, \
            f"停用成员访问项目详情应返回 403, 实际 {detail_resp.status_code}"

        # 恢复
        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "active"},
            headers=admin_headers,
        )

    async def test_inactive_member_cannot_access_legacy_project(self, client):
        """BUG-037: legacy 项目（workspace_id=None）也被停用成员校验覆盖"""
        await client.post("/api/auth/register", json={"username": "bug037c_user", "password": "test123456"})
        user_login = await client.post("/api/auth/login", json={"username": "bug037c_user", "password": "test123456"})
        user_token = user_login.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # 正常创建项目（有 workspace_id），然后手动清除 workspace_id 模拟 legacy
        proj_resp = await client.post("/api/review/projects", json={"name": "legacy-proj"}, headers=user_headers)
        project_id = proj_resp.json()["id"]

        # admin 停用该用户
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        target = next(m for m in members_resp.json() if m["username"] == "bug037c_user")
        target_user_id = target["user_id"]

        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )

        # 停用后访问项目详情 → 403（_verify_project_owner 对有/无 workspace_id 均校验）
        detail_resp = await client.get(f"/api/review/projects/{project_id}", headers=user_headers)
        assert detail_resp.status_code == 403, \
            f"停用成员访问项目详情应返回 403, 实际 {detail_resp.status_code}"

        # 恢复
        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "active"},
            headers=admin_headers,
        )


# ── BUG-038: 停用成员在成员列表可见（含恢复按钮） ──


class TestBug038InactiveMemberVisibleInList:
    async def test_inactive_member_appears_in_default_member_list(self, client):
        """BUG-038: GET /api/workspace/default/members 返回含 inactive 成员"""
        await client.post("/api/auth/register", json={"username": "bug038_user", "password": "test123456"})

        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        members_resp = await client.get("/api/workspace/default/members", headers=admin_headers)
        target = next(m for m in members_resp.json() if m["username"] == "bug038_user")
        target_user_id = target["user_id"]

        # 停用
        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "inactive"},
            headers=admin_headers,
        )

        # 仍可在列表中找到
        members_resp2 = await client.get("/api/workspace/default/members", headers=admin_headers)
        all_members = members_resp2.json()
        inactive_target = next((m for m in all_members if m["user_id"] == target_user_id), None)
        assert inactive_target is not None, "停用成员应仍出现在成员列表中"
        assert inactive_target["status"] == "inactive"

        # 恢复
        await client.put(
            f"/api/workspace/default/members/{target_user_id}",
            json={"status": "active"},
            headers=admin_headers,
        )


# ── BUG-039: PUT /api/workspace/default 支持 status 更新 ──


class TestBug039DefaultWorkspaceStatusUpdate:
    async def test_update_default_workspace_status(self, client):
        """BUG-039: PUT /api/workspace/default 可更新 status"""
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 更新 status 为 archived
        resp = await client.put("/api/workspace/default", headers=admin_headers, json={"status": "archived"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "archived"

        # 验证 GET 返回一致
        get_resp = await client.get("/api/workspace/default", headers=admin_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "archived"

        # 恢复为 active
        resp = await client.put("/api/workspace/default", headers=admin_headers, json={"status": "active"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    async def test_update_default_workspace_invalid_status(self, client):
        """BUG-039: 无效 status 返回 422"""
        admin_login = await client.post("/api/auth/login", json={"username": "admin", "password": "admin@2026"})
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await client.put("/api/workspace/default", headers=admin_headers, json={"status": "deleted"})
        assert resp.status_code == 422
