"""BUG-219/220：共享资料详情与存量私有资料列表的 HTTP 回归。"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.workspace import KnowledgeSource
from app.repositories.workspace_repository import WorkspaceRepository
from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def source_client(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path / "runtime"))
    app, engine, session_maker = make_test_app(str(tmp_path / "sources.db"))
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session_maker
    finally:
        await engine.dispose()


async def _register(client, username):
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "source-test-password"},
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    response = await client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"], headers


async def _set_workspace_role(session_maker, user_id, role):
    async with session_maker() as session:
        repo = WorkspaceRepository(session)
        workspace = await repo.get_default()
        member = await repo.get_member(workspace.id, user_id)
        member.role = role
        await session.commit()
        return workspace.id


@pytest.mark.parametrize("reader_role", ["member", "viewer", "owner", "admin"])
async def test_shared_source_detail_loads_uploader_for_other_member(source_client, reader_role):
    client, session_maker = source_client
    _, uploader_headers = await _register(client, "source_uploader")
    reader_id, reader_headers = await _register(client, "source_reader")
    workspace_id = await _set_workspace_role(session_maker, reader_id, reader_role)
    source_url = f"/api/workspace/{workspace_id}/sources"

    uploaded = await client.post(
        source_url,
        files={"file": ("shared.txt", b"shared source body", "text/plain")},
        headers=uploader_headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    source_id = uploaded.json()["id"]

    detail = await client.get(f"{source_url}/{source_id}", headers=reader_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["owner_name"] == "source_uploader"
    assert detail.json()["extracted_text"] == "shared source body"

    uploader_detail = await client.get(f"{source_url}/{source_id}", headers=uploader_headers)
    assert uploader_detail.status_code == 200, uploader_detail.text
    listed = await client.get(source_url, headers=reader_headers)
    assert listed.status_code == 200, listed.text
    assert [source["id"] for source in listed.json()] == [source_id]


@pytest.mark.parametrize("reader_role", ["member", "viewer", "owner", "admin"])
async def test_legacy_private_source_list_filters_owner_before_pagination(source_client, reader_role):
    client, session_maker = source_client
    other_id, _ = await _register(client, "private_other")
    reader_id, reader_headers = await _register(client, "private_reader")
    workspace_id = await _set_workspace_role(session_maker, reader_id, reader_role)
    source_url = f"/api/workspace/{workspace_id}/sources"
    owned_ids = []
    hidden_ids = []
    async with session_maker() as session:
        newest = datetime(2026, 1, 1)
        for index in range(3):
            for position, owner_id in enumerate((other_id, reader_id)):
                source = KnowledgeSource(
                    workspace_id=workspace_id,
                    owner_type="workspace",
                    visibility="private",
                    owner_id=owner_id,
                    source_type="upload",
                    title=f"private-{owner_id}-{index}",
                    filename=f"private-{owner_id}-{index}.txt",
                    updated_at=newest - timedelta(minutes=index * 2 + position),
                )
                session.add(source)
                await session.flush()
                if owner_id == reader_id:
                    owned_ids.append(source.id)
                else:
                    hidden_ids.append(source.id)
        await session.commit()

    for offset, expected_id in enumerate(owned_ids):
        page = await client.get(
            source_url,
            params={"visibility": "private", "offset": offset, "limit": 1},
            headers=reader_headers,
        )
        assert page.status_code == 200, page.text
        assert [source["id"] for source in page.json()] == [expected_id]

    listed = await client.get(source_url, params={"visibility": "private"}, headers=reader_headers)
    assert listed.status_code == 200, listed.text
    assert [source["id"] for source in listed.json()] == owned_ids
    assert (await client.get(f"{source_url}/{hidden_ids[0]}", headers=reader_headers)).status_code == 404
    owned_detail = await client.get(f"{source_url}/{owned_ids[0]}", headers=reader_headers)
    assert owned_detail.status_code == 200, owned_detail.text
    assert owned_detail.json()["owner_name"] == "private_reader"
    default_list = await client.get(source_url, headers=reader_headers)
    assert default_list.status_code == 200, default_list.text
    assert default_list.json() == []
