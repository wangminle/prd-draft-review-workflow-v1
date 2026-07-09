"""P4.A: 协作审查数据模型与 API 自动化测试。"""

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN_CREDS = {"username": "admin", "password": "admin@2026"}


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


async def _auth_header(client):
    resp = await client.post("/api/auth/login", json=ADMIN_CREDS)
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _register_user_id(client, username: str) -> int:
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "test123456"},
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me_resp = await client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200, me_resp.text
    return me_resp.json()["id"]


async def _create_project(client, headers):
    """创建一个审查项目用于测试。"""
    resp = await client.post(
        "/api/review/projects",
        json={"name": "P4测试项目", "description": "P4协作审查测试"},
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()["id"]


# ─── P4.A.1: ReviewRequest 表 ─────────────────────────────────
# 字段验证已移至 test_database.py（ReviewRequest/ReviewRound/ReviewParticipant）


# ─── P4.A.4: ReviewInitiationService (API) ────────────────────


async def test_create_review_request(client):
    """P4.A.4: 发起协作审查请求"""
    headers = await _auth_header(client)
    project_id = await _create_project(client, headers)

    resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "goal": "协作审查测试", "approver_ids": [1]},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == project_id
    assert data["status"] == "pending_approval"
    assert data["current_round"] == 1


async def test_create_review_request_nonexistent_project(client):
    """P4.A.4: 不存在的项目返回 404"""
    headers = await _auth_header(client)
    resp = await client.post(
        "/api/review/requests",
        json={"project_id": 99999, "approver_ids": [1]},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_list_review_requests_by_project(client):
    """按项目列出审查请求"""
    headers = await _auth_header(client)
    project_id = await _create_project(client, headers)

    # 创建请求
    await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [1]},
        headers=headers,
    )

    resp = await client.get(
        f"/api/review/requests?project_id={project_id}",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


# ─── P4.A.5: Round 提交与驳回 ─────────────────────────────────


async def test_decide_round_approved(client):
    """P4.A.5: 审查员通过审查"""
    headers = await _auth_header(client)
    project_id = await _create_project(client, headers)

    # 创建请求
    create_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [1]},
        headers=headers,
    )
    request_id = create_resp.json()["id"]

    # 获取轮次
    rounds_resp = await client.get(
        f"/api/review/requests/{request_id}/rounds",
        headers=headers,
    )
    rounds = rounds_resp.json()
    assert len(rounds) >= 1
    round_id = rounds[0]["id"]

    # 通过
    decide_resp = await client.post(
        f"/api/review/rounds/{round_id}/decide",
        json={"decision": "approved", "comment": "LGTM"},
        headers=headers,
    )
    assert decide_resp.status_code == 200
    assert decide_resp.json()["decision"] == "approved"


async def test_decide_round_rejected_and_resubmit(client):
    """P4.A.5: 驳回后重新提交"""
    headers = await _auth_header(client)
    project_id = await _create_project(client, headers)

    # 创建请求
    create_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [1]},
        headers=headers,
    )
    request_id = create_resp.json()["id"]

    # 获取轮次并驳回
    rounds_resp = await client.get(
        f"/api/review/requests/{request_id}/rounds",
        headers=headers,
    )
    round_id = rounds_resp.json()[0]["id"]

    await client.post(
        f"/api/review/rounds/{round_id}/decide",
        json={"decision": "rejected", "comment": "需要修改"},
        headers=headers,
    )

    # 重新提交
    resubmit_resp = await client.post(
        f"/api/review/requests/{request_id}/resubmit",
        headers=headers,
    )
    assert resubmit_resp.status_code == 200
    assert resubmit_resp.json()["current_round"] == 2
    assert resubmit_resp.json()["status"] == "pending_approval"


async def test_resubmit_only_for_rejected(client):
    """只有被驳回的请求可以重新提交"""
    headers = await _auth_header(client)
    project_id = await _create_project(client, headers)

    create_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [1]},
        headers=headers,
    )
    request_id = create_resp.json()["id"]

    # 非 rejected 状态重新提交应失败
    resp = await client.post(
        f"/api/review/requests/{request_id}/resubmit",
        headers=headers,
    )
    assert resp.status_code == 400


# ─── P4.A.2: ReviewParticipant ────────────────────────────────


async def test_participants_list(client):
    """P4.A.2: 列出审查参与者"""
    headers = await _auth_header(client)
    approver_id = await _register_user_id(client, "review_participant_approver")
    project_id = await _create_project(client, headers)

    create_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id]},
        headers=headers,
    )
    request_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/review/requests/{request_id}/participants",
        headers=headers,
    )
    assert resp.status_code == 200
    participants = resp.json()
    assert len(participants) >= 2  # Reviewer + Approver
    roles = {p["role"] for p in participants}
    assert "Reviewer" in roles
    assert "Approver" in roles
    user_ids = {p["user_id"] for p in participants}
    assert 1 in user_ids
    assert approver_id in user_ids
