"""需求审查用户数据隔离回归测试。"""

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def review_client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_maker
    if os.path.exists(tmp_db):
        os.unlink(tmp_db)


async def _register(client: AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "test123456"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_project(client: AsyncClient, headers: dict, name: str) -> int:
    resp = await client.post(
        "/api/review/projects",
        json={"name": name, "description": ""},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_sse_ticket(client: AsyncClient, headers: dict) -> str:
    resp = await client.post("/api/auth/sse-ticket", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["ticket"]


@pytest.mark.asyncio
async def test_review_projects_are_visible_only_to_owner(review_client):
    client, _ = review_client
    user_a = await _register(client, "review_owner_a")
    user_b = await _register(client, "review_owner_b")

    project_a = await _create_project(client, user_a, "A 的项目")
    project_b = await _create_project(client, user_b, "B 的项目")

    resp = await client.get("/api/review/projects", headers=user_a)
    assert resp.status_code == 200
    visible_ids = {p["id"] for p in resp.json()}
    assert project_a in visible_ids
    assert project_b not in visible_ids

    resp = await client.get(f"/api/review/projects/{project_b}", headers=user_a)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_review_task_id_cannot_be_reused_across_projects(review_client):
    client, session_maker = review_client
    user_a = await _register(client, "review_task_a")
    user_b = await _register(client, "review_task_b")

    project_a = await _create_project(client, user_a, "A 的项目")
    project_b = await _create_project(client, user_b, "B 的项目")

    from app.models.review import ReviewTask, SystemReview

    async with session_maker() as session:
        task_b = ReviewTask(
            project_id=project_b,
            mode="review",
            status="completed",
            current_step=5,
            total_docs=0,
            completed_docs=0,
            context_version=1,
            model_id="deepseek",
            step_statuses="{}",
            step_details='{"report_markdown":"# B 的私有报告"}',
        )
        session.add(task_b)
        await session.flush()
        session.add(SystemReview(
            task_id=task_b.id,
            project_id=project_b,
            business_value='{"summary":"B 的私有体系 Review"}',
        ))
        await session.commit()
        private_review_id = task_b.id

    protected_paths = [
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/status",
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/analyses",
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/system-review",
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/report",
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/report?format=markdown",
    ]

    for path in protected_paths:
        resp = await client.get(path, headers=user_a)
        assert resp.status_code == 404, path
        assert "B 的私有" not in resp.text

    # User A creates a valid SSE ticket, but tries to access User B's review_id
    # with User A's project_id — review_id doesn't belong to project_a, so 404
    ticket_a = await _create_sse_ticket(client, user_a)
    resp = await client.get(
        f"/api/review/projects/{project_a}/reviews/{private_review_id}?ticket={ticket_a}",
    )
    assert resp.status_code == 404
    assert "B 的私有" not in resp.text


@pytest.mark.asyncio
async def test_review_progress_requires_ephemeral_sse_ticket(review_client):
    client, session_maker = review_client
    user_headers = await _register(client, "review_sse_ticket_user")
    project_id = await _create_project(client, user_headers, "SSE 项目")

    from app.models.review import ReviewTask

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

    jwt_token = user_headers["Authorization"].removeprefix("Bearer ")
    resp = await client.get(
        f"/api/review/projects/{project_id}/reviews/{review_id}?token={jwt_token}"
    )
    assert resp.status_code == 401

    ticket = await _create_sse_ticket(client, user_headers)
    resp = await client.get(
        f"/api/review/projects/{project_id}/reviews/{review_id}?ticket={ticket}"
    )
    assert resp.status_code == 200
    assert '"task_status": "pending"' in resp.text

    resp = await client.get(
        f"/api/review/projects/{project_id}/reviews/{review_id}?ticket={ticket}"
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_project_delete_is_blocked_while_review_is_running(review_client):
    client, session_maker = review_client
    user_headers = await _register(client, "review_delete_guard_user")
    project_id = await _create_project(client, user_headers, "运行中项目")

    from app.models.review import ReviewTask

    async with session_maker() as session:
        task = ReviewTask(
            project_id=project_id,
            mode="review",
            status="running",
            current_step=2,
            total_docs=1,
            completed_docs=0,
            context_version=1,
            model_id="deepseek",
            step_statuses='{"0":"completed","1":"completed","2":"running"}',
            step_details="{}",
        )
        session.add(task)
        await session.commit()

    resp = await client.delete(f"/api/review/projects/{project_id}", headers=user_headers)

    assert resp.status_code == 409

    resp = await client.get(f"/api/review/projects/{project_id}", headers=user_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_project_report_count_includes_completed_with_warnings(review_client):
    client, session_maker = review_client
    user_headers = await _register(client, "review_report_count_user")
    project_id = await _create_project(client, user_headers, "报告计数项目")

    from app.models.review import ReviewTask

    async with session_maker() as session:
        session.add_all([
            ReviewTask(
                project_id=project_id,
                mode="quick",
                status="completed",
                current_step=2,
                total_docs=1,
                completed_docs=1,
                context_version=1,
                model_id="deepseek",
                step_statuses='{"0":"completed","1":"completed","2":"completed"}',
                step_details="{}",
            ),
            ReviewTask(
                project_id=project_id,
                mode="review",
                status="completed_with_warnings",
                current_step=4,
                total_docs=2,
                completed_docs=1,
                context_version=1,
                model_id="deepseek",
                step_statuses='{"0":"completed","1":"completed","2":"completed","3":"completed","4":"completed"}',
                step_details="{}",
            ),
        ])
        await session.commit()

    resp = await client.get("/api/review/projects", headers=user_headers)
    assert resp.status_code == 200
    project = next(item for item in resp.json() if item["id"] == project_id)
    assert project["report_count"] == 2

    resp = await client.get(f"/api/review/projects/{project_id}", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["report_count"] == 2


@pytest.mark.asyncio
async def test_review_detail_routes_reject_review_id_from_another_project_same_user(review_client):
    client, session_maker = review_client
    user_headers = await _register(client, "review_same_user_projects")

    project_a = await _create_project(client, user_headers, "同用户项目 A")
    project_b = await _create_project(client, user_headers, "同用户项目 B")

    from app.models.review import ReviewTask, SystemReview

    async with session_maker() as session:
        task_b = ReviewTask(
            project_id=project_b,
            mode="review",
            status="completed",
            current_step=5,
            total_docs=0,
            completed_docs=0,
            context_version=1,
            model_id="deepseek",
            step_statuses="{}",
            step_details='{"report_markdown":"# 同用户项目 B 的私有报告"}',
        )
        session.add(task_b)
        await session.flush()
        session.add(SystemReview(
            task_id=task_b.id,
            project_id=project_b,
            business_value='{"summary":"同用户项目 B 的私有体系 Review"}',
        ))
        await session.commit()
        private_review_id = task_b.id

    protected_paths = [
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/status",
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/analyses",
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/system-review",
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/report",
        f"/api/review/projects/{project_a}/reviews/{private_review_id}/report?format=markdown",
    ]

    for path in protected_paths:
        resp = await client.get(path, headers=user_headers)
        assert resp.status_code == 404, path
        assert "项目 B 的私有" not in resp.text
