"""Regression tests for BUG-106 (ghost SSE notification) and BUG-107 (duplicate participants).

BUG-106: NotificationService 在事务提交前就 _push_event，savepoint/事务回滚后
         SSE channel 仍残留指向已回滚 Notification 行的幽灵事件。
         修复：defer_push 缓冲 + flush_pending（commit 成功后）/ discard_pending（回滚时）。
BUG-107: ReviewParticipantRepository.list_by_request 返回全部行，存量重复
         (request_id, user_id) 行升级后仍重复展示；add_participant 只改首条。
         修复：list_by_request 按 user_id 去重；add_participant 收敛重复行。
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.review import ReviewParticipant
from app.models.user import Base, Notification
from app.repositories.review_request_repository import ReviewParticipantRepository
from app.services.notification_service import (
    NotificationEvent,
    NotificationService,
    clear_channel,
    get_notification_channel,
)
from tests.conftest import init_test_db, make_test_app


# ─── fixtures（与 test_bugfix_099_104 同模式）────────────────────────

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
        json={"username": "admin", "password": "admin@2026"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_project(client: AsyncClient, headers: dict, name: str = "bugfix project") -> int:
    resp = await client.post(
        "/api/review/projects",
        json={"name": name, "description": ""},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ─── BUG-106 单元测试：defer_push 机制 ──────────────────────────────

def test_defer_push_buffers_until_flush():
    """defer_push=True 时 _push_event 仅缓冲，flush_pending 才真正推送到 channel。"""
    recipient = 100001
    channel = get_notification_channel(recipient)
    try:
        svc = NotificationService(MagicMock(), defer_push=True)
        svc._push_event(recipient, NotificationEvent("new_notification", 1, {"id": 1}))
        assert len(channel) == 0, "缓冲阶段不应推送到 SSE channel"
        assert len(svc._pending) == 1
        svc.flush_pending()
        assert len(channel) == 1, "flush 后应推送"
        assert len(svc._pending) == 0
    finally:
        clear_channel(recipient, channel)


def test_defer_push_discard_prevents_ghost():
    """discard_pending 丢弃缓冲事件，即使后续 flush 也不产生幽灵 SSE 通知（BUG-106 核心）。"""
    recipient = 100002
    channel = get_notification_channel(recipient)
    try:
        svc = NotificationService(MagicMock(), defer_push=True)
        svc._push_event(recipient, NotificationEvent("new_notification", 2, {"id": 2}))
        assert len(svc._pending) == 1
        svc.discard_pending()  # 模拟 savepoint 回滚
        assert len(svc._pending) == 0
        assert len(channel) == 0, "discard 后不应残留幽灵事件"
        svc.flush_pending()  # 即使后续 flush 也无事件可推
        assert len(channel) == 0
    finally:
        clear_channel(recipient, channel)


def test_default_pushes_immediately_backward_compat():
    """默认（defer_push=False）立即推送，保持向后兼容。"""
    recipient = 100003
    channel = get_notification_channel(recipient)
    try:
        svc = NotificationService(MagicMock())  # 默认 defer_push=False
        svc._push_event(recipient, NotificationEvent("new_notification", 3, {"id": 3}))
        assert len(channel) == 1, "非 defer 模式应立即推送"
    finally:
        clear_channel(recipient, channel)


# ─── BUG-106 集成测试：resubmit savepoint 回滚无幽灵 ────────────────

@pytest.mark.asyncio
async def test_resubmit_savepoint_rollback_leaves_no_ghost_sse(client_with_db, monkeypatch):
    """resubmit 通知在 savepoint 内 create+push 后失败回滚，SSE channel 不残留幽灵事件。"""
    client, session_maker = client_with_db
    headers = await _login_admin(client)
    project_id = await _create_project(client, headers, "BUG-106 project")

    create_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [1], "goal": "ghost"},
        headers=headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    request_id = create_resp.json()["id"]

    round_id = (
        await client.get(f"/api/review/requests/{request_id}/rounds", headers=headers)
    ).json()[0]["id"]
    reject_resp = await client.post(
        f"/api/review/rounds/{round_id}/decide",
        json={"decision": "rejected", "comment": "rework"},
        headers=headers,
    )
    assert reject_resp.status_code == 200, reject_resp.text

    # 注册 approver(user 1) 的 SSE channel，并清空历史合法通知建立 baseline
    approver_channel = get_notification_channel(1)
    try:
        approver_channel.clear()  # 清掉 create/reject 的合法通知，建立干净 baseline

        async def failing_after_push(self, **kwargs):
            # 模拟真实 notify：create DB 行 + push 事件成功，但随后失败
            from app.repositories.notification_repository import NotificationRepository
            for ap in kwargs["approver_ids"]:
                n = await NotificationRepository(self._db).create(
                    recipient_id=ap,
                    actor_id=kwargs["initiator_id"],
                    object_type="review_request",
                    object_id=kwargs["request_id"],
                    type="review_request_created",
                    title="ghost",
                    body="should not appear",
                )
                self._push_event(ap, NotificationEvent(
                    type="new_notification", notification_id=n.id, data={"id": n.id}
                ))
            raise RuntimeError("after push failed")

        monkeypatch.setattr(
            "app.services.notification_service.NotificationService.notify_review_request_created",
            failing_after_push,
        )

        # resubmit 前的 baseline（含 create + reject 的合法通知）
        async with session_maker() as session:
            before = await session.scalar(
                select(func.count()).where(Notification.object_id == request_id)
            )

        resubmit_resp = await client.post(
            f"/api/review/requests/{request_id}/resubmit", headers=headers
        )
        assert resubmit_resp.status_code == 200, resubmit_resp.text

        # savepoint 回滚：resubmit 的 notification 不应新增（before == after）
        async with session_maker() as session:
            after = await session.scalar(
                select(func.count()).where(Notification.object_id == request_id)
            )
        assert after == before, "savepoint 回滚后不应新增 notification"

        # SSE channel 无幽灵（discard_pending 在 savepoint 失败时丢弃了缓冲事件）
        assert len(approver_channel) == 0, "savepoint 回滚后不应残留幽灵 SSE 事件"
    finally:
        clear_channel(1, approver_channel)


# ─── BUG-107 测试：重复参与者去重 + 收敛 ────────────────────────────

@pytest.mark.asyncio
async def test_list_participants_dedupes_legacy_duplicate_rows(db_session):
    """list_by_request 对存量重复 (request_id, user_id) 行按 user_id 去重，保留最高角色。"""
    request_id, user_id = 200001, 200002
    db_session.add(ReviewParticipant(
        request_id=request_id, user_id=user_id, role="Reviewer", status="active",
    ))
    db_session.add(ReviewParticipant(
        request_id=request_id, user_id=user_id, role="Approver", status="active",
    ))
    await db_session.flush()

    repo = ReviewParticipantRepository(db_session)
    participants = await repo.list_by_request(request_id)
    hits = [p for p in participants if p.user_id == user_id]
    assert len(hits) == 1, "存量重复行应去重为 1 条"
    assert hits[0].role == "Approver", "应保留角色优先级最高的"


@pytest.mark.asyncio
async def test_add_participant_converges_legacy_duplicates(db_session):
    """add_participant 收敛存量重复行：删除多余行、保留单条并升级到最高角色（不降级）。"""
    request_id, user_id = 200003, 200004
    db_session.add(ReviewParticipant(
        request_id=request_id, user_id=user_id, role="Reviewer", status="active",
    ))
    db_session.add(ReviewParticipant(
        request_id=request_id, user_id=user_id, role="Reviewer", status="active",
    ))
    await db_session.flush()

    repo = ReviewParticipantRepository(db_session)
    await repo.add_participant(request_id=request_id, user_id=user_id, role="Approver")

    rows = (await db_session.execute(
        select(ReviewParticipant).where(
            ReviewParticipant.request_id == request_id,
            ReviewParticipant.user_id == user_id,
        ).order_by(ReviewParticipant.id)
    )).scalars().all()
    assert len(rows) == 1, "add_participant 应将重复行收敛为 1 条"
    assert rows[0].role == "Approver", "应升级为 Approver（不降级已有最高角色）"
