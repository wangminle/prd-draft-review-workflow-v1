"""P3 Agent 功能自动化测试：AgentProfile、AgentRun、ToolCallTrace、MCP、Approval (P3.E.3)

使用 ASGI Transport 测试，无需启动服务器。
"""

import contextlib
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN_CREDS = {"username": "admin", "password": "admin@2026"}


@contextlib.asynccontextmanager
async def _override_db(client):
    """从 dependency_overrides 取一个测试 DB session，并确保生成器被关闭。

    PLN-001：`async for ... break` 不会在退出时 await aclose()，session 持有的
    aiosqlite 连接一直 checked-out，engine.dispose() 无法回收，loop 关闭后
    工作线程回写 Future 报 "Event loop is closed"。
    """
    from app.database import get_db as original_get_db
    app = client._transport.app  # type: ignore
    gen = app.dependency_overrides[original_get_db]()
    try:
        yield await gen.__anext__()
    finally:
        await gen.aclose()


@pytest_asyncio.fixture
async def client():
    """创建 ASGI 测试客户端，含 Agent 路由。"""
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


async def _auth_header(client):
    """获取 admin auth header。"""
    resp = await client.post("/api/auth/login", json=ADMIN_CREDS)
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json().get("access_token", resp.json().get("token"))
    return {"Authorization": f"Bearer {token}"}


async def _register_header(client, username: str):
    password = "pass12345"
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert resp.status_code in (200, 201), resp.text
    login = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ─── P3.A: AgentProfile CRUD ─────────────────────────────────

class TestAgentProfile:
    async def test_get_profile_returns_default(self, client):
        """获取 Agent Profile — 用户注册后自动创建默认 Profile"""
        headers = await _auth_header(client)
        resp = await client.get("/api/agent/profile", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner_type"] == "user"
        assert data["name"] == "My Agent"
        assert data["status"] == "active"

    async def test_update_profile_name(self, client):
        """更新 Agent 名称"""
        headers = await _auth_header(client)
        resp = await client.put(
            "/api/agent/profile",
            json={"name": "Test Agent"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Agent"
        assert resp.json()["version"] >= 2

    async def test_update_profile_tools(self, client):
        """更新 Agent 允许的工具列表"""
        headers = await _auth_header(client)
        resp = await client.put(
            "/api/agent/profile",
            json={"allowed_tools": ["search", "rag_search"]},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["allowed_tools"] == ["search", "rag_search"]

    async def test_update_profile_system_policy(self, client):
        """更新 Agent System Policy"""
        headers = await _auth_header(client)
        resp = await client.put(
            "/api/agent/profile",
            json={"system_policy": "你是一个帮助用户完成需求评审的 Agent。"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert "需求评审" in resp.json()["system_policy"]

    async def test_update_profile_invalid_status_rejected(self, client):
        """无效 status 值应返回 400"""
        headers = await _auth_header(client)
        resp = await client.put(
            "/api/agent/profile",
            json={"status": "invalid_status"},
            headers=headers,
        )
        assert resp.status_code == 400

    async def test_disable_and_reenable_profile(self, client):
        """禁用再启用 Agent Profile"""
        headers = await _auth_header(client)
        # Disable
        resp = await client.put(
            "/api/agent/profile",
            json={"status": "disabled"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"
        # Re-enable
        resp = await client.put(
            "/api/agent/profile",
            json={"status": "active"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"


# ─── P3.A.2: AgentAuthorization ──────────────────────────────

class TestAgentAuthorization:
    async def test_list_authorizations_empty(self, client):
        """初始授权列表为空"""
        headers = await _auth_header(client)
        resp = await client.get("/api/agent/profile/authorizations", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_and_revoke_authorization(self, client):
        """创建并撤销授权"""
        headers = await _auth_header(client)
        # Create
        resp = await client.post(
            "/api/agent/profile/authorizations",
            json={"scope_type": "workspace", "scope_id": 1, "permissions": ["read", "search"]},
            headers=headers,
        )
        assert resp.status_code == 200
        auth_id = resp.json()["id"]
        assert resp.json()["scope_type"] == "workspace"
        # Revoke
        resp = await client.delete(
            f"/api/agent/profile/authorizations/{auth_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    async def test_non_member_cannot_authorize_workspace(self, client):
        """用户不能仅凭猜测的 workspace ID 给自己的 Agent 越权授权。"""
        from app.models.user import AgentProfile, User
        from app.models.workspace import Workspace
        from sqlalchemy import select

        headers = await _register_header(client, "agent_outsider")
        async with _override_db(client) as db:
            secret = Workspace(
                name="机密空间",
                status="active",
                is_default=False,
                created_by=1,
            )
            db.add(secret)
            await db.commit()
            await db.refresh(secret)
            secret_id = secret.id

        resp = await client.post(
            "/api/agent/profile/authorizations",
            json={
                "scope_type": "workspace",
                "scope_id": secret_id,
                "permissions": ["read", "search"],
            },
            headers=headers,
        )
        assert resp.status_code == 403, resp.text

        async with _override_db(client) as db:
            user = (
                await db.execute(select(User).where(User.username == "agent_outsider"))
            ).scalar_one()
            profile = (
                await db.execute(
                    select(AgentProfile).where(
                        AgentProfile.owner_type == "user",
                        AgentProfile.owner_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            assert profile is None, "越权授权请求不得留下空 Agent 配置"

    async def test_archived_workspace_cannot_be_authorized(self, client):
        """即使是成员，也不能为已归档空间创建新授权。"""
        from app.models.user import User
        from app.models.workspace import Workspace, WorkspaceMember
        from sqlalchemy import select

        headers = await _register_header(client, "agent_archived_member")
        async with _override_db(client) as db:
            user = (
                await db.execute(select(User).where(User.username == "agent_archived_member"))
            ).scalar_one()
            archived = Workspace(
                name="已归档空间",
                status="archived",
                is_default=False,
                created_by=1,
            )
            db.add(archived)
            await db.flush()
            db.add(WorkspaceMember(
                workspace_id=archived.id,
                user_id=user.id,
                role="member",
                status="active",
            ))
            await db.commit()
            archived_id = archived.id

        resp = await client.post(
            "/api/agent/profile/authorizations",
            json={
                "scope_type": "workspace",
                "scope_id": archived_id,
                "permissions": ["read", "search"],
            },
            headers=headers,
        )
        assert resp.status_code == 404, resp.text

    async def test_authorization_validates_permissions_and_persists_expiry(self, client):
        """授权权限必须是受支持枚举，ISO 过期时间必须实际保存。"""
        headers = await _register_header(client, "agent_auth_contract")
        default_ws = (await client.get("/api/workspace/default", headers=headers)).json()

        invalid = await client.post(
            "/api/agent/profile/authorizations",
            json={
                "scope_type": "workspace",
                "scope_id": default_ws["id"],
                "permissions": ["read", "download_everything"],
            },
            headers=headers,
        )
        assert invalid.status_code == 400, invalid.text

        created = await client.post(
            "/api/agent/profile/authorizations",
            json={
                "scope_type": "workspace",
                "scope_id": default_ws["id"],
                "permissions": ["read", "search"],
                "expires_at": "2030-01-01T00:00:00Z",
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        assert created.json()["expires_at"] == "2030-01-01T08:00:00"

    @pytest.mark.parametrize(
        ("permissions", "expire_after_creation", "username"),
        [
            ([], False, "agent_empty_permissions"),
            (["write"], False, "agent_write_only"),
            (["read", "search"], True, "agent_expired_auth"),
        ],
    )
    async def test_rag_rejects_insufficient_or_expired_authorization(
        self,
        client,
        permissions,
        expire_after_creation,
        username,
    ):
        """检索必须同时具有 read/search 权限，且授权仍在有效期内。"""
        from datetime import timedelta

        from app.models.user import AgentAuthorization
        from app.utils import now_cn
        from sqlalchemy import select

        headers = await _register_header(client, username)
        default_ws = (await client.get("/api/workspace/default", headers=headers)).json()
        auth_resp = await client.post(
            "/api/agent/profile/authorizations",
            json={
                "scope_type": "workspace",
                "scope_id": default_ws["id"],
                "permissions": permissions,
            },
            headers=headers,
        )
        assert auth_resp.status_code == 200, auth_resp.text
        run_resp = await client.post(
            "/api/agent/runs",
            json={"goal": "验证授权约束"},
            headers=headers,
        )
        assert run_resp.status_code == 200, run_resp.text

        if expire_after_creation:
            async with _override_db(client) as db:
                auth = (
                    await db.execute(
                        select(AgentAuthorization).where(
                            AgentAuthorization.id == auth_resp.json()["id"]
                        )
                    )
                ).scalar_one()
                auth.expires_at = now_cn() - timedelta(seconds=1)
                await db.commit()

        fake_response = SimpleNamespace(
            query="test",
            results=[],
            total=0,
            fallback_reason=None,
        )
        with (
            patch("app.services.pi_agent_bridge.get_run_token", return_value="run-token"),
            patch(
                "app.services.retrieval_service.RetrievalService.retrieve",
                new=AsyncMock(return_value=fake_response),
            ) as retrieve,
        ):
            resp = await client.post(
                f"/api/agent/runs/{run_resp.json()['id']}/rag",
                json={
                    "query": "机密资料",
                    "workspace_id": default_ws["id"],
                    "scope": "workspace",
                },
                headers={"X-Agent-Run-Token": "run-token"},
            )

        assert resp.status_code == 403, resp.text
        retrieve.assert_not_awaited()

    async def test_removed_member_old_authorization_cannot_rag(self, client):
        """成员被移出 workspace 后，旧 Agent 授权必须立即失效。"""
        from app.models.user import User
        from app.models.workspace import WorkspaceMember
        from sqlalchemy import select

        headers = await _register_header(client, "agent_removed_member")
        default_ws = (await client.get("/api/workspace/default", headers=headers)).json()

        auth_resp = await client.post(
            "/api/agent/profile/authorizations",
            json={
                "scope_type": "workspace",
                "scope_id": default_ws["id"],
                "permissions": ["read", "search"],
            },
            headers=headers,
        )
        assert auth_resp.status_code == 200, auth_resp.text
        run_resp = await client.post(
            "/api/agent/runs",
            json={"goal": "验证失效授权"},
            headers=headers,
        )
        assert run_resp.status_code == 200, run_resp.text
        run_id = run_resp.json()["id"]

        async with _override_db(client) as db:
            user = (
                await db.execute(select(User).where(User.username == "agent_removed_member"))
            ).scalar_one()
            member = (
                await db.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == default_ws["id"],
                        WorkspaceMember.user_id == user.id,
                    )
                )
            ).scalar_one()
            member.status = "removed"
            await db.commit()

        fake_response = SimpleNamespace(
            query="test",
            results=[],
            total=0,
            fallback_reason=None,
        )
        with (
            patch("app.services.pi_agent_bridge.get_run_token", return_value="run-token"),
            patch(
                "app.services.retrieval_service.RetrievalService.retrieve",
                new=AsyncMock(return_value=fake_response),
            ) as retrieve,
        ):
            resp = await client.post(
                f"/api/agent/runs/{run_id}/rag",
                json={
                    "query": "机密资料",
                    "workspace_id": default_ws["id"],
                    "scope": "workspace",
                },
                headers={"X-Agent-Run-Token": "run-token"},
            )

        assert resp.status_code == 403, resp.text
        retrieve.assert_not_awaited()


# ─── P3.B: AgentRun 状态流转 ─────────────────────────────────

class TestAgentRun:
    async def test_create_run(self, client):
        """创建 Agent Run"""
        headers = await _auth_header(client)
        resp = await client.post(
            "/api/agent/runs",
            json={"goal": "帮我分析这个需求文档的完整性"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["goal"] == "帮我分析这个需求文档的完整性"
        assert data["status"] == "planning"

    async def test_list_runs(self, client):
        """列出 Agent Runs"""
        headers = await _auth_header(client)
        resp = await client.get("/api/agent/runs", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_run_detail(self, client):
        """获取 Run 详情（含 steps 和 traces）"""
        headers = await _auth_header(client)
        # Create a run first
        create_resp = await client.post(
            "/api/agent/runs",
            json={"goal": "测试 run 详情"},
            headers=headers,
        )
        run_id = create_resp.json()["id"]
        resp = await client.get(f"/api/agent/runs/{run_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == run_id
        assert "steps" in data
        assert "traces" in data

    async def test_disabled_agent_cannot_create_run(self, client):
        """禁用 Agent 后无法创建 Run"""
        headers = await _auth_header(client)
        # Disable agent
        await client.put(
            "/api/agent/profile",
            json={"status": "disabled"},
            headers=headers,
        )
        resp = await client.post(
            "/api/agent/runs",
            json={"goal": "应该失败"},
            headers=headers,
        )
        assert resp.status_code == 400
        # Re-enable
        await client.put(
            "/api/agent/profile",
            json={"status": "active"},
            headers=headers,
        )


# ─── P3.C: MCP Server / Policy ──────────────────────────────

class TestMCPConfig:
    async def test_create_and_list_mcp_server(self, client):
        """创建并列出 MCP Server"""
        headers = await _auth_header(client)
        resp = await client.post(
            "/api/agent/mcp/servers",
            json={"name": "Figma MCP", "server_type": "sse", "endpoint_ref": "http://localhost:3000"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Figma MCP"
        # List
        resp = await client.get("/api/agent/mcp/servers", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_create_mcp_tool_policy(self, client):
        """创建 MCP 工具策略"""
        headers = await _auth_header(client)
        # Create server
        server_resp = await client.post(
            "/api/agent/mcp/servers",
            json={"name": "Test MCP", "server_type": "stdio", "endpoint_ref": "test-command"},
            headers=headers,
        )
        server_id = server_resp.json()["id"]
        # Create policy
        resp = await client.post(
            f"/api/agent/mcp/servers/{server_id}/policies",
            json={"tool_name": "write_file", "requires_approval": True, "risk_level": "high"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["requires_approval"] is True
        assert resp.json()["risk_level"] == "high"


# ─── P3.D: Approval ─────────────────────────────────────────

class TestApproval:
    async def test_list_approvals_empty(self, client):
        """初始审批列表为空"""
        headers = await _auth_header(client)
        resp = await client.get("/api/agent/approvals", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_approval_requires_approver_id(self, client):
        """P4.Pre.4: AgentApprovalRepository.create 必须传 approver_id"""
        from app.models.user import AgentRun
        from app.repositories.agent_repository import AgentApprovalRepository

        # 通过 API 获取 profile（自动创建）
        headers = await _auth_header(client)
        profile_resp = await client.get("/api/agent/profile", headers=headers)
        assert profile_resp.status_code == 200
        profile_id = profile_resp.json()["id"]

        # 通过 dependency_overrides 获取测试数据库 session
        async with _override_db(client) as db:
            run = AgentRun(agent_id=profile_id, user_id=1, goal="test")
            db.add(run)
            await db.commit()
            await db.refresh(run)

            # 创建审批请求——approver_id 是必填参数
            approval_repo = AgentApprovalRepository(db)
            approval = await approval_repo.create(
                run_id=run.id,
                requester_id=1,
                approver_id=1,
                action_type="tool_call:bash",
            )
            assert approval.approver_id == 1
            assert approval.status == "pending"

    async def test_list_pending_filters_by_approver(self, client):
        """P4.Pre.4: 待审批列表按 approver_id 过滤，不同审批人只看自己的"""
        from app.models.user import AgentRun, User
        from app.repositories.agent_repository import AgentApprovalRepository
        from app.services.auth import hash_password

        headers = await _auth_header(client)
        profile_resp = await client.get("/api/agent/profile", headers=headers)
        profile_id = profile_resp.json()["id"]

        async with _override_db(client) as db:
            # 第二审批人必须真实存在（外键约束）
            approver2 = User(username="approver2", password_hash=hash_password("test123456"), role="user")
            db.add(approver2)
            await db.flush()

            run = AgentRun(agent_id=profile_id, user_id=1, goal="test2")
            db.add(run)
            await db.commit()
            await db.refresh(run)
            await db.refresh(approver2)

            approval_repo = AgentApprovalRepository(db)
            # 创建两个审批请求，分别给不同审批人
            await approval_repo.create(
                run_id=run.id, requester_id=1, approver_id=1,
                action_type="tool_call:bash",
            )
            await approval_repo.create(
                run_id=run.id, requester_id=1, approver_id=approver2.id,
                action_type="tool_call:write",
            )

            # 审批人 1 只看到 1 条
            pending_1 = await approval_repo.list_pending(approver_id=1)
            assert len(pending_1) == 1
            assert pending_1[0].approver_id == 1

            # 审批人 2 只看到 1 条
            pending_2 = await approval_repo.list_pending(approver_id=approver2.id)
            assert len(pending_2) == 1
            assert pending_2[0].approver_id == approver2.id

    async def test_api_approvals_returns_only_mine(self, client):
        """P4.Pre.4: GET /api/agent/approvals 只返回当前用户作为审批人的请求"""
        headers = await _auth_header(client)
        resp = await client.get("/api/agent/approvals", headers=headers)
        assert resp.status_code == 200
        # admin 用户 (id=1) 没有被指派为审批人的待审批请求
        data = resp.json()
        assert isinstance(data, list)
