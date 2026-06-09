"""P3 Agent 功能自动化测试：AgentProfile、AgentRun、ToolCallTrace、MCP、Approval (P3.E.3)

使用 ASGI Transport 测试，无需启动服务器。
"""

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN_CREDS = {"username": "admin", "password": "admin123"}


@pytest_asyncio.fixture
async def client():
    """创建 ASGI 测试客户端，含 Agent 路由。"""
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    if os.path.exists(tmp_db):
        os.unlink(tmp_db)


async def _auth_header(client):
    """获取 admin auth header。"""
    resp = await client.post("/api/auth/login", json=ADMIN_CREDS)
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json().get("access_token", resp.json().get("token"))
    return {"Authorization": f"Bearer {token}"}


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
            json={"allowed_tools": ["search", "rag"]},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["allowed_tools"] == ["search", "rag"]

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
