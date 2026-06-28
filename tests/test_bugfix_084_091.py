"""BUG-084~091 回归测试。"""

import os
import tempfile
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models.review import CostDailySummary, WorkspaceBudget
from app.models.workspace import KnowledgeSource, Workspace
from tests.conftest import init_test_db, make_test_app

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN_CREDS = {"username": "admin", "password": "admin123"}


@pytest_asyncio.fixture
async def client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_maker
    # Windows 下必须先关闭 engine 连接池，否则文件被占用无法删除
    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


async def _auth(client, username="admin", password="admin123"):
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _register(client, username, password="testpass123"):
    await client.post("/api/auth/register", json={"username": username, "password": password})
    return await _auth(client, username, password)


async def _create_project(client, headers, name="测试项目"):
    resp = await client.post(
        "/api/review/projects",
        json={"name": name, "description": "desc"},
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()["id"]


async def test_create_review_request_requires_approver(client):
    c, _ = client
    headers = await _auth(c)
    project_id = await _create_project(c, headers)

    resp = await c.post(
        "/api/review/requests",
        json={"project_id": project_id, "goal": "无审批人"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_create_review_request_with_approver_succeeds(client):
    c, _ = client
    headers = await _auth(c)
    project_id = await _create_project(c, headers)

    resp = await c.post(
        "/api/review/requests",
        json={"project_id": project_id, "goal": "有审批人", "approver_ids": [1]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_approval"


async def test_workspace_admin_can_access_member_project_detail(client):
    c, _ = client
    member_h = await _register(c, "bug085_member")
    admin_h = await _auth(c)

    project_id = await _create_project(c, member_h, "成员项目")

    resp = await c.get(f"/api/review/projects/{project_id}", headers=admin_h)
    assert resp.status_code == 200
    assert resp.json()["id"] == project_id


async def test_private_source_not_readable_via_workspace_api(client):
    c, sm = client
    owner_h = await _register(c, "bug086_owner")
    other_h = await _register(c, "bug086_other")

    me_resp = await c.get("/api/auth/me", headers=owner_h)
    owner_id = me_resp.json()["id"]
    ws_id = None
    source_id = None

    async with sm() as db:
        ws = (await db.execute(select(Workspace).limit(1))).scalar_one()
        ws_id = ws.id
        source = KnowledgeSource(
            workspace_id=ws.id,
            source_type="upload",
            title="私有资料",
            owner_type="user",
            owner_id=owner_id,
            visibility="private",
            status="active",
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        source_id = source.id

    resp = await c.get(
        f"/api/workspace/{ws_id}/sources/{source_id}",
        headers=other_h,
    )
    assert resp.status_code == 404


async def test_fts_excludes_other_users_private_source(client):
    from app.services.knowledge_ingestion import KnowledgeIngestionService

    c, sm = client
    async with sm() as db:
        ws = (await db.execute(select(Workspace).limit(1))).scalar_one()
        private = KnowledgeSource(
            workspace_id=ws.id,
            source_type="upload",
            title="secret",
            owner_type="user",
            owner_id=99,
            visibility="private",
            status="active",
            extracted_text="机密关键词内容测试",
        )
        team = KnowledgeSource(
            workspace_id=ws.id,
            source_type="upload",
            title="team doc",
            owner_type="workspace",
            owner_id=1,
            visibility="team",
            status="active",
            extracted_text="团队公开关键词内容测试",
        )
        db.add_all([private, team])
        await db.commit()
        await db.refresh(private)
        await db.refresh(team)

        svc = KnowledgeIngestionService(db)
        await svc.ingest_source(private.id)
        await svc.ingest_source(team.id)

        results = await svc.search_fts("关键词内容", ws.id, limit=10, user_id=1)
        source_ids = {r["source_id"] for r in results}
        assert team.id in source_ids
        assert private.id not in source_ids


async def test_agent_decide_approval_requires_assigned_approver(client):
    from app.models.user import AgentApprovalRequest, AgentProfile, AgentRun

    c, sm = client
    admin_h = await _auth(c)
    other_h = await _register(c, "bug087_other")

    approval_id = None
    async with sm() as db:
        profile = (await db.execute(select(AgentProfile).limit(1))).scalar_one_or_none()
        if profile is None:
            profile = AgentProfile(owner_type="user", owner_id=1, name="Test Agent", status="active")
            db.add(profile)
            await db.flush()
        run = AgentRun(agent_id=profile.id, user_id=1, goal="g", status="planning")
        db.add(run)
        await db.flush()
        approval = AgentApprovalRequest(
            run_id=run.id,
            requester_id=1,
            approver_id=1,
            action_type="tool_call",
            status="pending",
        )
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        approval_id = approval.id

    resp = await c.post(
        f"/api/agent/approvals/{approval_id}/decide",
        json={"decision": "approved"},
        headers=other_h,
    )
    assert resp.status_code == 403


async def test_revoke_authorization_requires_owner(client):
    c, _ = client
    owner_h = await _auth(c)
    other_h = await _register(c, "bug088_other")

    create_resp = await c.post(
        "/api/agent/profile/authorizations",
        json={"scope_type": "workspace", "permissions": ["read"]},
        headers=owner_h,
    )
    assert create_resp.status_code == 200
    auth_id = create_resp.json()["id"]

    resp = await c.delete(f"/api/agent/profile/authorizations/{auth_id}", headers=other_h)
    assert resp.status_code == 404


async def test_budget_block_rejects_chat(client):
    c, sm = client
    headers = await _auth(c)

    async with sm() as db:
        ws = (await db.execute(select(Workspace).limit(1))).scalar_one()
        db.add(WorkspaceBudget(
            workspace_id=ws.id,
            monthly_token_limit=100,
            hard_limit_action="block",
        ))
        month = datetime.now().strftime("%Y-%m")
        db.add(CostDailySummary(
            workspace_id=ws.id,
            user_id=1,
            mode="chat",
            date=f"{month}-01",
            model_id="test-model",
            call_count=1,
            input_tokens=80,
            output_tokens=30,
        ))
        await db.commit()

    resp = await c.post(
        "/api/chat",
        json={"message": "hello", "model_id": "deepseek"},
        headers=headers,
    )
    assert resp.status_code == 429


async def test_notifications_page_params_map_to_limit_offset(client):
    c, _ = client
    headers = await _auth(c)
    resp = await c.get("/api/notifications?page=2&page_size=10", headers=headers)
    assert resp.status_code == 200
    assert "items" in resp.json()
