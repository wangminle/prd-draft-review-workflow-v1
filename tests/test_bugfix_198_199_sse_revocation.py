"""BUG-198/BUG-199 回归测试

BUG-198 [P1] 改密/重置前签发的 SSE 票据仍可用、已建立的 SSE 长连接继续推送。
  修复：票据绑定签发时的 auth_version，消费时与 users.auth_version 比对；
  通知流/审查进度流的生成器循环内周期性校验会话版本，失配即推送
  session_revoked 并收口。

BUG-199 [P1] auth_version 读后加一存在并发丢失更新。
  修复：UserRepository.update/update_password 改为原子 UPDATE
  （auth_version = auth_version + 1），用户改密路径同样走该原子方法。
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from tests.conftest import init_test_db, make_test_app

VALID_PASSWORD = "test123456"
NEW_PASSWORD = "newpass789"


@pytest_asyncio.fixture
async def app_env():
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


async def _register(client, username="carol", password=VALID_PASSWORD):
    resp = await client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _get_ticket(client, token):
    resp = await client.post("/api/auth/sse-ticket", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["ticket"]


# ─── BUG-198：票据会话版本绑定 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_ticket_rejected_by_notification_stream(app_env):
    """改密前签发的票据，改密后连接通知流应 401（复核复现路径）"""
    client, _ = app_env
    token = await _register(client)
    ticket = await _get_ticket(client, token)

    resp = await client.put(
        "/api/auth/password",
        json={"old_password": VALID_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    resp = await client.get(f"/api/notifications/stream?ticket={ticket}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stale_ticket_rejected_by_review_stream(app_env):
    """改密前签发的票据，改密后连接审查进度流应 401（在校验项目归属之前）"""
    client, _ = app_env
    token = await _register(client)
    ticket = await _get_ticket(client, token)

    await client.put(
        "/api/auth/password",
        json={"old_password": VALID_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_auth(token),
    )

    resp = await client.get(f"/api/review/projects/1/reviews/1?ticket={ticket}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_fresh_ticket_still_accepted_after_password_change(app_env):
    """改密后重新登录签发的新票据可正常建立通知流（直接驱动生成器，产出心跳）。

    注：httpx ASGITransport 会缓冲至应用结束，无法增量读 SSE 流，
    因此流式行为用直接调用端点函数、迭代 body_iterator 的方式验证。
    """
    client, session_maker = app_env
    token = await _register(client)
    await client.put(
        "/api/auth/password",
        json={"old_password": VALID_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_auth(token),
    )
    resp = await client.post(
        "/api/auth/login", json={"username": "carol", "password": NEW_PASSWORD}
    )
    new_token = resp.json()["access_token"]
    ticket = await _get_ticket(client, new_token)

    from app.routers.notification import notification_stream

    async with session_maker() as db:
        resp = await notification_stream(ticket=ticket, db=db)
        agen = resp.body_iterator
        first = await asyncio.wait_for(agen.__anext__(), timeout=5)
        assert "heartbeat" in first
        await agen.aclose()


@pytest.mark.asyncio
async def test_established_notification_stream_closes_after_password_change(app_env):
    """已建立的通知流：改密后下一心跳周期收到 session_revoked 并收口（复核复现路径）"""
    client, session_maker = app_env
    token = await _register(client)
    ticket = await _get_ticket(client, token)
    me = await client.get("/api/auth/me", headers=_auth(token))
    uid = me.json()["id"]

    from app.repositories.user_repository import UserRepository
    from app.routers.notification import notification_stream
    from app.services.auth import hash_password

    async with session_maker() as db:
        resp = await notification_stream(ticket=ticket, db=db)
        agen = resp.body_iterator
        first = await asyncio.wait_for(agen.__anext__(), timeout=5)
        assert "heartbeat" in first

        # 另一会话改密并提交（auth_version 1→2）
        async with session_maker() as s2:
            await UserRepository(s2).update_password(uid, hash_password(NEW_PASSWORD))
            await s2.commit()

        # 下一循环（5s 心跳后）校验会话版本 → session_revoked → 收口
        second = await asyncio.wait_for(agen.__anext__(), timeout=15)
        assert "session_revoked" in second
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(agen.__anext__(), timeout=15)


@pytest.mark.asyncio
async def test_established_review_stream_stops_after_password_reset(app_env):
    """审查进度流：改密后队列里的后续任务事件不再推送，改发 session_revoked 并收口"""
    client, session_maker = app_env
    token = await _register(client)
    me = await client.get("/api/auth/me", headers=_auth(token))
    uid = me.json()["id"]

    resp = await client.post(
        "/api/review/projects", json={"name": "SSE 撤销项目", "description": ""},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    project_id = resp.json()["id"]

    from app.models.review import ReviewTask

    async with session_maker() as session:
        task = ReviewTask(
            project_id=project_id, mode="review", status="running",
            current_step=0, total_docs=1, completed_docs=0,
            context_version=1, model_id="deepseek",
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    from app.routers import review as review_router

    # 注册任务为活跃管线（订阅制：键存在表示管线活跃，值为各连接独立队列）
    review_router.progress_queues[task_id] = set()

    ticket = await _get_ticket(client, token)

    from app.repositories.user_repository import UserRepository
    from app.services.auth import hash_password

    try:
        async with session_maker() as db:
            resp = await review_router.review_progress_sse(
                project_id, task_id, ticket=ticket, db=db
            )
            agen = resp.body_iterator

            # 改密前的正常事件可推送
            await review_router._publish_progress(task_id, {"task_status": "running", "current_step": 1})
            first = await asyncio.wait_for(agen.__anext__(), timeout=5)
            assert "running" in first

            # 另一会话重置密码并提交（auth_version 1→2）
            async with session_maker() as s2:
                await UserRepository(s2).update_password(uid, hash_password(NEW_PASSWORD))
                await s2.commit()

            # 后续任务事件不再推送，改发 session_revoked 并收口
            await review_router._publish_progress(task_id, {"task_status": "running", "current_step": 2})
            second = await asyncio.wait_for(agen.__anext__(), timeout=5)
            assert "session_revoked" in second
            assert "current_step" not in second
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(agen.__anext__(), timeout=5)
    finally:
        review_router.progress_queues.pop(task_id, None)


def test_ticket_store_binds_auth_version():
    """票据存储：consume 返回 user_id + auth_version；旧格式票据版本按 0"""
    from datetime import datetime, timedelta, timezone

    from app.services import auth

    store = auth._sse_ticket_store
    store._tickets.clear()

    ticket = auth.issue_sse_ticket(7, auth_version=5)
    payload = auth.consume_sse_ticket(ticket)
    assert payload == {"user_id": 7, "auth_version": 5}

    # 一次性：再消费返回 None
    assert auth.consume_sse_ticket(ticket) is None

    # 旧格式票据（无 auth_version 字段）按 0 处理，无法通过版本校验
    store._tickets["legacy"] = {
        "user_id": 7,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
    }
    payload = auth.consume_sse_ticket("legacy")
    assert payload == {"user_id": 7, "auth_version": 0}
    store._tickets.clear()


# ─── BUG-199：原子递增，无并发丢失更新 ─────────────────────────────────


@pytest.mark.asyncio
async def test_interleaved_password_resets_increment_atomically(app_env):
    """复核复现场景：B 先读 v1 → A 重置提交 v2 → B 再重置提交。

    旧实现（ORM 读后写）B 会写回 v2 导致丢失递增；原子 UPDATE 下最终必须为 v3，
    且 A 阶段签发的 v2 Token 在 B 提交后立即失效。
    """
    from app.repositories.user_repository import UserRepository
    from app.services.auth import create_access_token, hash_password

    client, session_maker = app_env
    token = await _register(client)
    me = await client.get("/api/auth/me", headers=_auth(token))
    uid = me.json()["id"]

    async with session_maker() as sa, session_maker() as sb:
        repo_a, repo_b = UserRepository(sa), UserRepository(sb)

        # B 先读取（会话 B 身份映射缓存 auth_version=1，复现竞态前提）
        user_b = await repo_b.get_by_id(uid)
        assert user_b.auth_version == 1

        # A 重置并提交 → v2，并模拟签发 v2 Token
        await repo_a.update_password(uid, hash_password("reset-a-123456"))
        await sa.commit()
        token_v2 = create_access_token(uid, "user", 2)

        # B 释放读事务快照（长事务不持有快照，聚焦检验写入路径的原子性）
        await sb.rollback()
        # B 基于过期缓存对象的读后写在旧实现下会写回 2；原子 UPDATE 应为 3
        await repo_b.update_password(uid, hash_password("reset-b-123456"))
        await sb.commit()

    async with session_maker() as s:
        final = await UserRepository(s).get_by_id(uid)
        assert final.auth_version == 3

    # A 阶段签发的 v2 Token 已失效
    resp = await client.get("/api/auth/me", headers=_auth(token_v2))
    assert resp.status_code == 401

    # 最新密码可登录，签发的 Token 为 v3
    resp = await client.post(
        "/api/auth/login", json={"username": "carol", "password": "reset-b-123456"}
    )
    assert resp.status_code == 200, resp.text
    from app.services.auth import decode_token

    assert decode_token(resp.json()["access_token"])["av"] == 3


@pytest.mark.asyncio
async def test_admin_update_without_password_does_not_bump_version(app_env):
    """管理员仅改角色/启用状态不触碰密码时，不得递增会话版本"""
    client, session_maker = app_env
    token = await _register(client)
    me = await client.get("/api/auth/me", headers=_auth(token))
    uid = me.json()["id"]

    resp = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin@2026"}
    )
    admin = resp.json()["access_token"]

    resp = await client.put(
        f"/api/admin/users/{uid}", json={"role": "admin"}, headers=_auth(admin)
    )
    assert resp.status_code == 200

    from app.repositories.user_repository import UserRepository

    async with session_maker() as s:
        user = await UserRepository(s).get_by_id(uid)
        assert user.auth_version == 1

    # 原 Token 仍可用
    resp = await client.get("/api/auth/me", headers=_auth(token))
    assert resp.status_code == 200


# ─── 前端契约 ──────────────────────────────────────────────────────────


def test_frontend_handles_session_revoked_events():
    """review.js / notification.js 均处理 session_revoked：关流、清 Token、回登录页"""
    review_js = (ROOT / "src" / "static" / "js" / "review.js").read_text(encoding="utf-8")
    notif_js = (ROOT / "src" / "static" / "js" / "notification.js").read_text(encoding="utf-8")

    assert "data.task_status === 'session_revoked'" in review_js
    assert "msg.type === 'session_revoked'" in notif_js
    for js in (review_js, notif_js):
        assert "API.clearToken();" in js
        assert "location.reload()" in js
    # review.js onerror 终态清单包含 session_revoked，避免误回退轮询
    assert "'session_revoked'].includes(info.status)" in review_js


def test_backend_stream_loops_check_session_alive():
    """两条 SSE 流生成器循环内均周期校验会话版本"""
    review_py = (ROOT / "src" / "app" / "routers" / "review.py").read_text(encoding="utf-8")
    notif_py = (ROOT / "src" / "app" / "routers" / "notification.py").read_text(encoding="utf-8")
    assert review_py.count("is_session_alive(db, user_id_from_ticket, ticket_auth_version)") >= 2
    assert "is_session_alive(db, user_id, auth_version)" in notif_py
    assert "validate_sse_ticket" in review_py
    assert "validate_sse_ticket" in notif_py


# ─── BUG-200：在途改密不得覆盖管理员重置 ──────────────────────────────


@pytest.mark.asyncio
async def test_inflight_password_change_rejected_after_admin_reset(app_env):
    """复核复现路径：改密请求通过旧密码校验后暂停（会话 A 缓存 av=1 的用户对象），
    管理员重置提交（av→2）；在途请求恢复后以 expected_auth_version=1 写入，
    命中 0 行被拒——管理员设置的新密码保持有效，在途请求指定的密码不可登录。
    """
    client, session_maker = app_env
    token = await _register(client)
    me = await client.get("/api/auth/me", headers=_auth(token))
    uid = me.json()["id"]

    from app.repositories.user_repository import (
        SessionVersionConflictError,
        UserRepository,
    )
    from app.services.auth import hash_password, verify_password

    async with session_maker() as sa:
        repo_a = UserRepository(sa)
        user = await repo_a.get_by_id(uid)
        assert user.auth_version == 1
        # 在途请求的旧密码校验已通过（此处暂停，管理员插入重置）
        assert verify_password(VALID_PASSWORD, user.password_hash)

        async with session_maker() as sb:
            await UserRepository(sb).update_password(uid, hash_password("admin-reset-123"))
            await sb.commit()

        # 在途请求恢复：版本条件不匹配，拒绝写入
        with pytest.raises(SessionVersionConflictError):
            await repo_a.update_password(
                uid, hash_password("inflight-new-123"), expected_auth_version=1
            )
        await sa.rollback()

    # 管理员重置的密码可登录；在途请求指定的密码不可登录
    resp = await client.post(
        "/api/auth/login", json={"username": "carol", "password": "admin-reset-123"}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/api/auth/login", json={"username": "carol", "password": "inflight-new-123"}
    )
    assert resp.status_code == 401

    # 版本只被管理员重置推进了一次
    async with session_maker() as s:
        final = await UserRepository(s).get_by_id(uid)
        assert final.auth_version == 2


@pytest.mark.asyncio
async def test_password_change_with_current_version_succeeds(app_env):
    """正常路径：expected_auth_version 与当前版本一致时改密成功并递增到 2"""
    client, session_maker = app_env
    token = await _register(client)
    me = await client.get("/api/auth/me", headers=_auth(token))
    uid = me.json()["id"]

    from app.repositories.user_repository import UserRepository
    from app.services.auth import hash_password, verify_password

    async with session_maker() as s:
        repo = UserRepository(s)
        user = await repo.update_password(
            uid, hash_password(NEW_PASSWORD), expected_auth_version=1
        )
        await s.commit()
        assert user.auth_version == 2
        assert verify_password(NEW_PASSWORD, user.password_hash)


def test_change_password_route_carries_expected_version():
    """契约：用户改密路由携带认证时 auth_version 作为写入条件，冲突返回 409 并审计"""
    src = (ROOT / "src" / "app" / "routers" / "auth.py").read_text(encoding="utf-8")
    assert "expected_auth_version=user.auth_version or 1" in src
    assert "SessionVersionConflictError" in src
    assert "status_code=409" in src
    assert "auth_version_conflict" in src


# ─── BUG-202：冲突回滚后审计不得触发 MissingGreenlet ──────────────────


@pytest.mark.asyncio
async def test_inflight_password_change_conflict_returns_409_and_audits(app_env, monkeypatch):
    """BUG-202 复核复现路径（HTTP 层）：改密通过旧密码校验后被挂起，管理员重置
    抢先提交（av 1→2），在途改密恢复后命中版本冲突——必须返回 409 + 中文提示，
    且 auth_version_conflict 审计正常落盘；rollback 后不得再访问已过期 ORM
    属性（修复前此处抛 MissingGreenlet，409 变 500 且审计丢失）。
    """
    client, session_maker = app_env
    token = await _register(client)
    me = await client.get("/api/auth/me", headers=_auth(token))
    uid = me.json()["id"]

    from app.repositories import user_repository as user_repo_mod
    from app.services.auth import hash_password

    original = user_repo_mod.UserRepository.update_password
    injected = False

    async def racing_update_password(self, user_id, password_hash, *, expected_auth_version=None):
        nonlocal injected
        if not injected:
            injected = True
            # 在途改密挂起期间，管理员重置经独立会话抢先提交
            async with session_maker() as s:
                await user_repo_mod.UserRepository(s).update_password(
                    user_id, hash_password("admin-reset-123")
                )
                await s.commit()
        return await original(
            self, user_id, password_hash, expected_auth_version=expected_auth_version
        )

    monkeypatch.setattr(
        user_repo_mod.UserRepository, "update_password", racing_update_password
    )

    # 真实审计写入 audit.jsonl（含 _actor_to_dict 读取 actor 属性）；
    # 以文件偏移量只采集本次请求新增的日志行
    import json as _json

    from app.logging_config import get_logs_dir

    audit_file = get_logs_dir() / "audit.jsonl"
    offset = audit_file.stat().st_size if audit_file.exists() else 0

    resp = await client.put(
        "/api/auth/password",
        json={"old_password": VALID_PASSWORD, "new_password": "inflight-new-123"},
        headers=_auth(token),
    )
    assert resp.status_code == 409, resp.text
    assert "密码已在其他操作中被重置" in resp.json()["detail"]

    new_entries = []
    with open(audit_file, encoding="utf-8") as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if line:
                new_entries.append(_json.loads(line))

    conflicts = [
        e
        for e in new_entries
        if e["action"] == "auth.password_change"
        and e.get("detail", {}).get("reason") == "auth_version_conflict"
    ]
    assert len(conflicts) == 1
    entry = conflicts[0]
    assert entry["result"] == "failed"
    assert entry["level"] == "warning"
    assert entry["actor"]["user_id"] == uid
    assert entry["actor"]["username"] == "carol"

    # 管理员重置的密码可登录；在途请求指定的密码不可登录
    resp = await client.post(
        "/api/auth/login", json={"username": "carol", "password": "admin-reset-123"}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/api/auth/login", json={"username": "carol", "password": "inflight-new-123"}
    )
    assert resp.status_code == 401


# ─── BUG-201：撤销连接不得吞掉其他连接的终态事件 ────────────────────────


@pytest.mark.asyncio
async def test_revoked_connection_does_not_consume_terminal_event(app_env):
    """复核复现路径：旧（改密前建立）与新（改密后重新登录建立）连接同时等待，
    发布 completed 终态后——旧连接只收到 session_revoked，新连接必须收到 completed。
    共享队列实现下旧连接会取走并丢弃 completed，新连接永远等不到。
    """
    client, session_maker = app_env
    token = await _register(client)
    me = await client.get("/api/auth/me", headers=_auth(token))
    uid = me.json()["id"]

    resp = await client.post(
        "/api/review/projects", json={"name": "BUG-201 项目", "description": ""},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    project_id = resp.json()["id"]

    from app.models.review import ReviewTask

    async with session_maker() as session:
        task = ReviewTask(
            project_id=project_id, mode="review", status="running",
            current_step=0, total_docs=1, completed_docs=0,
            context_version=1, model_id="deepseek",
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    from app.repositories.user_repository import UserRepository
    from app.routers import review as review_router
    from app.services.auth import hash_password

    review_router.progress_queues[task_id] = set()
    try:
        # 旧连接（改密前签发，av=1）
        ticket_old = await _get_ticket(client, token)
        async with session_maker() as db1:
            resp1 = await review_router.review_progress_sse(
                project_id, task_id, ticket=ticket_old, db=db1
            )
            gen1 = resp1.body_iterator

            # 改密（另一会话提交，av 1→2）
            async with session_maker() as s2:
                await UserRepository(s2).update_password(uid, hash_password(NEW_PASSWORD))
                await s2.commit()

            # 重新登录，建立新连接（av=2）
            resp = await client.post(
                "/api/auth/login", json={"username": "carol", "password": NEW_PASSWORD}
            )
            new_token = resp.json()["access_token"]
            ticket_new = await _get_ticket(client, new_token)
            async with session_maker() as db2:
                resp2 = await review_router.review_progress_sse(
                    project_id, task_id, ticket=ticket_new, db=db2
                )
                gen2 = resp2.body_iterator

                # 管线发布终态
                await review_router._publish_progress(
                    task_id, {"task_status": "completed", "current_step": 5}
                )

                # 旧连接：session_revoked 并收口，且不含 completed 内容
                old_msg = await asyncio.wait_for(gen1.__anext__(), timeout=5)
                assert "session_revoked" in old_msg
                assert "completed" not in old_msg
                with pytest.raises(StopAsyncIteration):
                    await asyncio.wait_for(gen1.__anext__(), timeout=5)

                # 新连接：收到 completed 终态并正常收口
                new_msg = await asyncio.wait_for(gen2.__anext__(), timeout=5)
                assert '"task_status": "completed"' in new_msg
                with pytest.raises(StopAsyncIteration):
                    await asyncio.wait_for(gen2.__anext__(), timeout=5)
    finally:
        review_router.progress_queues.pop(task_id, None)


@pytest.mark.asyncio
async def test_terminal_task_returns_snapshot_without_subscription(app_env):
    """终态任务：即使管线注册键仍存在（窗口竞态），也直接回 DB 快照并收口"""
    client, session_maker = app_env
    token = await _register(client)

    resp = await client.post(
        "/api/review/projects", json={"name": "BUG-201 终态项目", "description": ""},
        headers=_auth(token),
    )
    project_id = resp.json()["id"]

    from app.models.review import ReviewTask

    async with session_maker() as session:
        task = ReviewTask(
            project_id=project_id, mode="review", status="completed",
            current_step=5, total_docs=1, completed_docs=1,
            context_version=1, model_id="deepseek",
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    from app.routers import review as review_router

    # 模拟「键尚未注销但任务已终态」的竞态窗口
    review_router.progress_queues[task_id] = set()
    try:
        ticket = await _get_ticket(client, token)
        async with session_maker() as db:
            resp = await review_router.review_progress_sse(
                project_id, task_id, ticket=ticket, db=db
            )
            chunks = [chunk async for chunk in resp.body_iterator]
            assert len(chunks) == 1
            assert '"task_status": "completed"' in chunks[0]
        # 快照路径不得残留订阅
        assert not review_router.progress_queues.get(task_id)
    finally:
        review_router.progress_queues.pop(task_id, None)


def test_review_progress_pubsub_structure():
    """契约：审查进度为发布/订阅结构，管线路径不再有共享队列消费"""
    src = (ROOT / "src" / "app" / "routers" / "review.py").read_text(encoding="utf-8")
    assert "progress_queues: dict[int, set[asyncio.Queue]] = {}" in src
    assert "_subscribe_progress" in src
    assert "_unsubscribe_progress" in src
    assert "_publish_progress" in src
    assert "class _ProgressPublisher" in src
    # 管线不再按「队列存在与否」决定是否发布
    assert "queue = progress_queues.get(task_id)" not in src
    assert "_early_queue" not in src
