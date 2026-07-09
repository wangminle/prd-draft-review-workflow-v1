"""Regression tests for BUG-099 through BUG-104."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.review import (
    CostDailySummary,
    ReviewParticipant,
    ReviewTask,
)
from app.models.user import (
    Base,
    MCPServerConfig,
    MCPToolPolicy,
    Notification,
)
from app.models.workspace import Workspace, WorkspaceMember
from app.services.cost_stats_service import CostStatsService
from app.services.mcp_adapter import MCPAdapterManager
from app.services.notification_service import (
    NotificationEvent,
    NotificationService,
    clear_channel,
    get_notification_channel,
)
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


async def _register(client: AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "test123456"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _login_admin(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin@2026"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_sse_ticket(client: AsyncClient, headers: dict) -> str:
    resp = await client.post("/api/auth/sse-ticket", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["ticket"]


async def _create_project(client: AsyncClient, headers: dict, name: str = "bugfix project") -> int:
    resp = await client.post(
        "/api/review/projects",
        json={"name": name, "description": ""},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_review_progress_sse_allows_workspace_owner_for_member_project(client_with_db):
    client, session_maker = client_with_db
    member_headers = await _register(client, "bug099_project_creator")
    admin_headers = await _login_admin(client)
    project_id = await _create_project(client, member_headers, "BUG-099 SSE project")

    async with session_maker() as session:
        task = ReviewTask(
            project_id=project_id,
            mode="quick",
            status="pending",
            current_step=0,
            total_docs=0,
            completed_docs=0,
            context_version=1,
            model_id="deepseek",
            step_statuses="{}",
            step_details="{}",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        review_id = task.id

    ticket = await _create_sse_ticket(client, admin_headers)
    resp = await client.get(
        f"/api/review/projects/{project_id}/reviews/{review_id}?ticket={ticket}",
    )

    assert resp.status_code == 200
    assert '"task_status": "pending"' in resp.text


@pytest.mark.asyncio
async def test_chat_stream_logs_llm_session_with_real_usage(client_with_db, tmp_path):
    client, _ = client_with_db
    headers = await _register(client, "bug100_chat_user")
    from app.services.llm import StreamChunk

    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    async def mock_stream(model_id, messages, **kwargs):
        yield StreamChunk(delta="", reasoning_content="thinking")
        yield StreamChunk(delta="hello")
        yield StreamChunk(delta=" world")
        yield StreamChunk(
            delta="",
            finish_reason="stop",
            usage={
                "prompt_tokens": 4,
                "completion_tokens": 5,
                "total_tokens": 9,
                "elapsed_seconds": 1.25,
            },
        )

    final_event = None
    with patch("app.routers.chat.stream_chat", side_effect=mock_stream), patch(
        "app.logging_config.get_logs_dir",
        return_value=log_dir,
    ):
        async with client.stream(
            "POST",
            "/api/chat",
            json={"message": "hi", "model_id": "deepseek"},
            headers=headers,
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                parsed = json.loads(data_str)
                if parsed.get("done"):
                    final_event = parsed

    assert final_event is not None
    assert final_event["token_count"] == 9

    log_path = log_dir / "llm_sessions.jsonl"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["response"] == "hello world"
    assert records[0]["usage"] == {
        "prompt_tokens": 4,
        "completion_tokens": 5,
        "total_tokens": 9,
        "elapsed_seconds": 1.25,
    }
    assert records[0]["elapsed_ms"] == 1250
    assert records[0]["reasoning_content"] == "thinking"


@pytest.mark.asyncio
async def test_mcp_policy_parse_failure_denies_tool(db_session):
    server = MCPServerConfig(
        name="broken-policy-server",
        server_type="stdio",
        endpoint_ref="node server.js",
    )
    db_session.add(server)
    await db_session.flush()
    db_session.add(
        MCPToolPolicy(
            server_id=server.id,
            tool_name="dangerous_tool",
            allowed_roles_json='["owner"',
            requires_approval=False,
            risk_level="high",
        )
    )
    await db_session.flush()

    result = await MCPAdapterManager().check_policy(
        db_session,
        server.id,
        "dangerous_tool",
        user_role="member",
    )

    assert result["allowed"] is False
    assert result["risk_level"] == "high"


def test_notification_channels_are_per_connection_and_clear_only_one():
    from app.services import notification_service

    notification_service._notification_channels.clear()
    channel_one = get_notification_channel(7)
    channel_two = get_notification_channel(7)

    assert channel_one is not channel_two

    clear_channel(7, channel_one)
    svc = object.__new__(NotificationService)
    svc._push_event(
        7,
        NotificationEvent(
            type="new_notification",
            notification_id=1,
            data={"title": "still connected"},
        ),
    )

    assert channel_one == []
    assert len(channel_two) == 1
    assert json.loads(channel_two[0])["data"]["title"] == "still connected"

    clear_channel(7, channel_two)
    assert 7 not in notification_service._notification_channels


@pytest.mark.asyncio
async def test_resubmit_notification_failure_does_not_commit_partial_notification(
    client_with_db,
    monkeypatch,
):
    client, session_maker = client_with_db
    headers = await _login_admin(client)
    project_id = await _create_project(client, headers, "BUG-103 project")

    create_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [1], "goal": "resubmit"},
        headers=headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    request_id = create_resp.json()["id"]

    rounds_resp = await client.get(f"/api/review/requests/{request_id}/rounds", headers=headers)
    round_id = rounds_resp.json()[0]["id"]
    reject_resp = await client.post(
        f"/api/review/rounds/{round_id}/decide",
        json={"decision": "rejected", "comment": "needs changes"},
        headers=headers,
    )
    assert reject_resp.status_code == 200, reject_resp.text

    async with session_maker() as session:
        before_count = await session.scalar(
            select(func.count()).where(Notification.object_id == request_id)
        )

    async def failing_notify(self, **kwargs):
        from app.repositories.notification_repository import NotificationRepository

        await NotificationRepository(self._db).create(
            recipient_id=kwargs["approver_ids"][0],
            actor_id=kwargs["initiator_id"],
            object_type="review_request",
            object_id=kwargs["request_id"],
            type="review_request_created",
            title="partial notification",
            body="should rollback",
        )
        raise RuntimeError("notification backend failed")

    monkeypatch.setattr(
        "app.services.notification_service.NotificationService.notify_review_request_created",
        failing_notify,
    )

    resubmit_resp = await client.post(f"/api/review/requests/{request_id}/resubmit", headers=headers)
    assert resubmit_resp.status_code == 200, resubmit_resp.text
    assert resubmit_resp.json()["status"] == "pending_approval"
    assert resubmit_resp.json()["current_round"] == 2

    async with session_maker() as session:
        after_count = await session.scalar(
            select(func.count()).where(Notification.object_id == request_id)
        )

    assert after_count == before_count


@pytest.mark.asyncio
async def test_create_review_request_deduplicates_initiator_when_also_approver(client_with_db):
    client, session_maker = client_with_db
    headers = await _login_admin(client)
    project_id = await _create_project(client, headers, "BUG-104 project")

    resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [1], "goal": "dedupe"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    request_id = resp.json()["id"]

    async with session_maker() as session:
        result = await session.execute(
            select(ReviewParticipant).where(ReviewParticipant.request_id == request_id)
        )
        participants = list(result.scalars().all())

    user_ids = [p.user_id for p in participants]
    assert user_ids.count(1) == 1
    assert len(user_ids) == len(set(user_ids))


@pytest.mark.asyncio
async def test_cost_aggregate_upsert_keeps_workspace_specific_rows_separate(
    db_session,
    tmp_path,
    monkeypatch,
):
    workspace = Workspace(name="team", is_default=True, status="active")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=1, role="owner"))
    db_session.add(
        CostDailySummary(
            workspace_id=workspace.id,
            user_id=None,
            mode="chat",
            date="2026-07-07",
            model_id="deepseek-chat",
            call_count=99,
            input_tokens=990,
            output_tokens=990,
        )
    )
    await db_session.flush()

    runtime_root = tmp_path / "runtime"
    logs_dir = runtime_root / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "llm_sessions.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-07-07T09:00:00",
                "model": "deepseek-chat",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                "elapsed_ms": 1234,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RUNTIME_ROOT", str(runtime_root))

    rows = await CostStatsService(db_session).aggregate_daily("2026-07-07")

    assert rows == 1
    result = await db_session.execute(
        select(CostDailySummary).where(
            CostDailySummary.date == "2026-07-07",
            CostDailySummary.model_id == "deepseek-chat",
            CostDailySummary.mode == "chat",
        )
    )
    summaries = list(result.scalars().all())
    assert len(summaries) == 2

    global_summary = next(s for s in summaries if s.workspace_id is None)
    workspace_summary = next(s for s in summaries if s.workspace_id == workspace.id)
    assert global_summary.call_count == 1
    assert global_summary.input_tokens == 10
    assert global_summary.output_tokens == 20
    assert global_summary.total_elapsed_ms == 1234
    assert workspace_summary.call_count == 99
    assert workspace_summary.input_tokens == 990
