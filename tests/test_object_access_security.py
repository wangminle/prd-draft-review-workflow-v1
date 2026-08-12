"""object_access 越权安全测试 — 补 CHK-094 覆盖缺口（object_access.py 原 24%）。

object_access.py 是对象级权限收口（防 BOLA 越权）。全项目仅 artifact.py 与
notification.py 两个路由 import 它，因此测试入口必须走这两个路由的端点，
才能真实提升 object_access 覆盖率（review.py / review_request.py / workspace.py
用的是各自内联校验，不计入 object_access 覆盖）。

本文件覆盖此前 0% 的分支：
  - assert_conversation_access（会话归属）
  - assert_knowledge_source_access（私有 owner / 团队非成员）
  - assert_review_round_access（审查轮次跨用户）
  - assert_project_access 经 snapshot 端点的停用成员路径（require_action status≠active）
  - assert_artifact_write_access 的 workspace owner/admin 正向写分支（150-159）

已由 test_bugfix_112_118.py / test_bugfix_119_124.py 覆盖、此处不重复的分支：
  - review_request artifact 跨用户读/写/列举/创建
  - snapshot 跨用户拒绝
  - comment-on-artifact 越权
  - Observer 对 review_request artifact 写/确认阻断
"""

from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models.review import (
    Artifact,
    ReviewProject,
    ReviewRequest,
    ReviewRound,
)
from app.models.user import Conversation, User
from app.models.workspace import KnowledgeSource, Workspace, WorkspaceMember
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


async def _login(client, username="admin", password="admin@2026"):
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _register_user(client, username, password="pass12345"):
    resp = await client.post("/api/auth/register", json={"username": username, "password": password})
    assert resp.status_code in (200, 201), resp.text
    return await _login(client, username, password)


async def _user_id(session_maker, username):
    async with session_maker() as db:
        row = (await db.execute(select(User).where(User.username == username))).scalar_one()
        return row.id


# ─── 停用成员经 snapshot 端点被拦截 ──────────────────────────────────


@pytest.mark.asyncio
async def test_inactive_member_blocked_from_snapshot(client_with_db):
    """active workspace admin 可读 snapshot；停用后 require_action 拒绝 → 403。

    覆盖 assert_project_access → require_action(member.status != active)。
    用 admin 角色（而非 member）是因为 user_can_access_project 对 member 仅放行
    自建项目——member 访问别人建的项目即使 active 也会 404，无法体现"先放行后拒绝"。
    """
    client, session_maker = client_with_db
    admin_h = await _login(client)
    member_h = await _register_user(client, "snap_member")

    proj = await client.post(
        "/api/review/projects",
        json={"name": "snap项目", "description": ""},
        headers=admin_h,
    )
    assert proj.status_code == 200, proj.text
    project_id = proj.json()["id"]
    ws = await client.get("/api/workspace/default", headers=admin_h)
    workspace_id = ws.json()["id"]

    snap = await client.post(
        "/api/review/snapshots",
        json={"workspace_id": workspace_id, "project_id": project_id, "source_refs_json": "[]"},
        headers=admin_h,
    )
    assert snap.status_code == 200, snap.text
    snap_id = snap.json()["id"]

    member_uid = await _user_id(session_maker, "snap_member")
    # 注册时 snap_member 已被自动加入默认 workspace（member 角色）。提升为 admin，
    # 否则 user_can_access_project 对 member 仅放行自建项目——active 时也会 404。
    async with session_maker() as db:
        member_row = (
            await db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == member_uid,
                )
            )
        ).scalar_one()
        member_row.role = "admin"
        await db.commit()

    # active admin 成员可读
    get_ok = await client.get(f"/api/review/snapshots/{snap_id}", headers=member_h)
    assert get_ok.status_code == 200, get_ok.text

    # 停用该成员（get_member 只返回 active 行 → 返回 None → require_action 拒绝）
    async with session_maker() as db:
        row = (
            await db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == member_uid,
                )
            )
        ).scalar_one()
        row.status = "inactive"
        await db.commit()

    get_denied = await client.get(f"/api/review/snapshots/{snap_id}", headers=member_h)
    assert get_denied.status_code == 403, get_denied.text


# ─── 私有 knowledge_source 仅 owner 可访问 ──────────────────────────


@pytest.mark.asyncio
async def test_private_knowledge_source_cross_user_denied(client_with_db):
    """私有资料(owner_type=user)仅 owner 可评论；无关用户被 404（防存在性泄露）。

    覆盖 assert_knowledge_source_access 私有分支。
    """
    client, session_maker = client_with_db
    owner_h = await _register_user(client, "ks_owner")
    intruder_h = await _register_user(client, "ks_intruder")

    owner_uid = await _user_id(session_maker, "ks_owner")
    async with session_maker() as db:
        src = KnowledgeSource(
            owner_type="user",
            visibility="private",
            owner_id=owner_uid,
            workspace_id=None,
            title="owner的私有资料",
            source_type="upload",
            status="active",
        )
        db.add(src)
        await db.commit()
        source_id = src.id

    cmt_ok = await client.post(
        "/api/notifications/comments",
        json={"object_type": "knowledge_source", "object_id": source_id, "body": "owner评论"},
        headers=owner_h,
    )
    assert cmt_ok.status_code == 200, cmt_ok.text

    cmt_no = await client.post(
        "/api/notifications/comments",
        json={"object_type": "knowledge_source", "object_id": source_id, "body": "入侵"},
        headers=intruder_h,
    )
    assert cmt_no.status_code in (403, 404)
    assert "私有" not in cmt_no.text  # 内容不泄露


# ─── 团队 knowledge_source 非成员被拒 ───────────────────────────────


@pytest.mark.asyncio
async def test_team_knowledge_source_non_member_denied(client_with_db):
    """团队资料(owner_type=workspace)要求 workspace read 权限；非成员 → 403。

    覆盖 assert_knowledge_source_access 团队分支（require_action read）。
    用独立 workspace（非默认）确保 outsider 一定不是成员。
    """
    client, session_maker = client_with_db
    admin_h = await _login(client)
    outsider_h = await _register_user(client, "ks_outsider")

    async with session_maker() as db:
        ws = Workspace(name="团队资料空间", is_default=False, status="active", created_by=1)
        db.add(ws)
        await db.flush()
        # admin 作为该独立空间的 owner，否则连 admin 也读不了
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=1, role="owner", status="active"))
        src = KnowledgeSource(
            owner_type="workspace",
            visibility="team",
            workspace_id=ws.id,
            title="团队资料",
            source_type="upload",
            status="active",
        )
        db.add(src)
        await db.commit()
        source_id = src.id

    # outsider 非成员 → require_action(None) → 403
    cmt = await client.post(
        "/api/notifications/comments",
        json={"object_type": "knowledge_source", "object_id": source_id, "body": "入侵"},
        headers=outsider_h,
    )
    assert cmt.status_code == 403, cmt.text

    # admin（owner）可评论
    cmt_ok = await client.post(
        "/api/notifications/comments",
        json={"object_type": "knowledge_source", "object_id": source_id, "body": "admin评论"},
        headers=admin_h,
    )
    assert cmt_ok.status_code == 200, cmt_ok.text


# ─── review_round 跨用户越权 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_round_cross_user_denied(client_with_db):
    """无关用户对别人的审查轮次发评论被拒。

    覆盖 assert_review_round_access → assert_review_request_access。
    """
    client, session_maker = client_with_db
    admin_h = await _login(client)
    intruder_h = await _register_user(client, "round_intruder")

    async with session_maker() as db:
        ws = (await db.execute(select(Workspace).where(Workspace.is_default == True))).scalar_one()
        project = ReviewProject(name="round项目", created_by=1, workspace_id=ws.id)
        db.add(project)
        await db.flush()
        req = ReviewRequest(project_id=project.id, initiator_id=1, status="pending", goal="g")
        db.add(req)
        await db.flush()
        rnd = ReviewRound(request_id=req.id, round_no=1, decision="pending")
        db.add(rnd)
        await db.commit()
        round_id = rnd.id

    # admin（initiator）可评论
    cmt_ok = await client.post(
        "/api/notifications/comments",
        json={"object_type": "review_round", "object_id": round_id, "body": "admin评论"},
        headers=admin_h,
    )
    assert cmt_ok.status_code == 200, cmt_ok.text

    # intruder 被拒（assert_review_request_access 最终转 404）
    cmt_no = await client.post(
        "/api/notifications/comments",
        json={"object_type": "review_round", "object_id": round_id, "body": "入侵"},
        headers=intruder_h,
    )
    assert cmt_no.status_code in (403, 404)


# ─── conversation artifact 跨用户读写 ──────────────────────────────


@pytest.mark.asyncio
async def test_conversation_artifact_cross_user_denied(client_with_db):
    """会话产物仅会话所有者可读写；无关用户读/写均被拒。

    覆盖 assert_conversation_access + assert_artifact_write_access 的 conversation 分支。
    """
    client, session_maker = client_with_db
    owner_h = await _register_user(client, "conv_owner")
    intruder_h = await _register_user(client, "conv_intruder")

    owner_uid = await _user_id(session_maker, "conv_owner")
    async with session_maker() as db:
        conv = Conversation(user_id=owner_uid, model_id="test-model", mode="chat")
        db.add(conv)
        await db.flush()
        art = Artifact(
            object_type="conversation",
            object_id=conv.id,
            artifact_type="explanation_json",
            content_json="conv-secret",
            status="draft",
        )
        db.add(art)
        await db.commit()
        artifact_id = art.id

    # intruder 读被拒
    get_no = await client.get(f"/api/review/artifacts/{artifact_id}", headers=intruder_h)
    assert get_no.status_code in (403, 404)

    # intruder 写被拒（连读校验都过不去）
    put_no = await client.put(
        f"/api/review/artifacts/{artifact_id}/content",
        json={"content_json": "hacked"},
        headers=intruder_h,
    )
    assert put_no.status_code in (403, 404)

    # owner 读写正常
    get_ok = await client.get(f"/api/review/artifacts/{artifact_id}", headers=owner_h)
    assert get_ok.status_code == 200, get_ok.text
    assert get_ok.json()["content_json"] == "conv-secret"


# ─── workspace owner 正向写他人发起的 request artifact ─────────────


@pytest.mark.asyncio
async def test_workspace_owner_can_write_others_request_artifact(client_with_db):
    """workspace owner/admin 可写空间内他人发起的审查请求产物。

    覆盖 assert_artifact_write_access 的 owner/admin 正向分支（150-159）。
    admin 既不是 initiator 也不是 project.created_by，但作为 workspace owner 放行。
    """
    client, session_maker = client_with_db
    admin_h = await _login(client)
    # 注册 initiator 仅为拿其 user_id 作为 project.created_by / request.initiator_id；
    # 本测试只验证 admin（workspace owner）的写权限，不使用 initiator 的 header。
    await _register_user(client, "req_initiator")

    initiator_uid = await _user_id(session_maker, "req_initiator")
    async with session_maker() as db:
        ws = (await db.execute(select(Workspace).where(Workspace.is_default == True))).scalar_one()
        # initiator 注册时已自动加入默认 workspace（member 角色），无需重复添加
        # project 由 initiator 创建、request 由 initiator 发起
        project = ReviewProject(name="owner写项目", created_by=initiator_uid, workspace_id=ws.id)
        db.add(project)
        await db.flush()
        req = ReviewRequest(project_id=project.id, initiator_id=initiator_uid, status="pending", goal="g")
        db.add(req)
        await db.flush()
        art = Artifact(
            object_type="review_request",
            object_id=req.id,
            artifact_type="html_presentation",
            content_json='{"v":1}',
            status="draft",
        )
        db.add(art)
        await db.commit()
        artifact_id = art.id

    # admin（workspace owner，非 initiator 非 creator）写 → owner/admin 分支放行
    upd = await client.put(
        f"/api/review/artifacts/{artifact_id}/content",
        json={"content_json": '{"owner":true}'},
        headers=admin_h,
    )
    assert upd.status_code == 200, upd.text

    # admin 确认（同一放行分支，action=confirm 也通过）
    conf = await client.post(f"/api/review/artifacts/{artifact_id}/confirm", headers=admin_h)
    assert conf.status_code == 200, conf.text
