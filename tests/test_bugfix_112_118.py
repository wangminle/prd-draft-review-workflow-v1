"""BUG-112~118 回归：对象级权限、JWT、MCP 鉴权、engine dispose、embedding/RAG 契约。"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

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


async def _auth_header(client, username="admin", password="admin@2026"):
    if username != "admin":
        resp = await client.post("/api/auth/register", json={"username": username, "password": password})
        assert resp.status_code in (200, 201, 400)  # 400 if already exists
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_project(client, headers, name="AuthZ项目"):
    resp = await client.post(
        "/api/review/projects",
        json={"name": name, "description": "object auth"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_request_with_artifact(client, headers, secret="owner-secret"):
    project_id = await _create_project(client, headers)
    me = await client.get("/api/auth/me", headers=headers)
    user_id = me.json()["id"]
    req_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [user_id], "goal": "权限测试"},
        headers=headers,
    )
    assert req_resp.status_code == 200, req_resp.text
    request_id = req_resp.json()["id"]
    art = await client.post(
        "/api/review/artifacts",
        json={
            "object_type": "review_request",
            "object_id": request_id,
            "artifact_type": "explanation_json",
            "content_json": secret,
        },
        headers=headers,
    )
    assert art.status_code == 200, art.text
    return project_id, request_id, art.json()["id"]


# ─── BUG-112: Artifact / Snapshot / Comment 对象级权限 ─────────────


async def test_bug112_user_b_cannot_read_or_tamper_user_a_artifact(client):
    """用户 B 不能读取/篡改用户 A 的产物。"""
    h_a = await _auth_header(client, "bug112_owner_a", "pass-a-12345")
    h_b = await _auth_header(client, "bug112_intruder_b", "pass-b-12345")

    _project_id, _request_id, artifact_id = await _create_request_with_artifact(
        client, h_a, secret="owner-secret"
    )

    get_b = await client.get(f"/api/review/artifacts/{artifact_id}", headers=h_b)
    assert get_b.status_code in (403, 404)

    put_b = await client.put(
        f"/api/review/artifacts/{artifact_id}/content",
        json={"content_json": "tampered"},
        headers=h_b,
    )
    assert put_b.status_code in (403, 404)

    get_a = await client.get(f"/api/review/artifacts/{artifact_id}", headers=h_a)
    assert get_a.status_code == 200
    assert get_a.json()["content_json"] == "owner-secret"


async def test_bug112_user_b_cannot_list_or_create_on_others_object(client):
    h_a = await _auth_header(client, "bug112_list_a", "pass-a-12345")
    h_b = await _auth_header(client, "bug112_list_b", "pass-b-12345")

    _project_id, request_id, _artifact_id = await _create_request_with_artifact(
        client, h_a, secret="secret-list"
    )

    listed = await client.get(
        f"/api/review/artifacts?object_type=review_request&object_id={request_id}",
        headers=h_b,
    )
    assert listed.status_code in (403, 404)

    create_b = await client.post(
        "/api/review/artifacts",
        json={
            "object_type": "review_request",
            "object_id": request_id,
            "artifact_type": "svg_summary",
            "content_json": "intruder",
        },
        headers=h_b,
    )
    assert create_b.status_code in (403, 404)


async def test_bug112_snapshot_requires_project_access(client):
    h_a = await _auth_header(client, "bug112_snap_a", "pass-a-12345")
    h_b = await _auth_header(client, "bug112_snap_b", "pass-b-12345")
    project_id = await _create_project(client, h_a, "Snap项目")

    ws = await client.get("/api/workspace/default", headers=h_a)
    assert ws.status_code == 200
    workspace_id = ws.json()["id"]

    snap = await client.post(
        "/api/review/snapshots",
        json={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "source_refs_json": "[]",
        },
        headers=h_a,
    )
    assert snap.status_code == 200, snap.text
    snap_id = snap.json()["id"]

    get_b = await client.get(f"/api/review/snapshots/{snap_id}", headers=h_b)
    assert get_b.status_code in (403, 404)

    create_b = await client.post(
        "/api/review/snapshots",
        json={"workspace_id": workspace_id, "project_id": project_id},
        headers=h_b,
    )
    assert create_b.status_code in (403, 404)


async def test_bug112_comment_requires_object_access(client):
    h_a = await _auth_header(client, "bug112_cmt_a", "pass-a-12345")
    h_b = await _auth_header(client, "bug112_cmt_b", "pass-b-12345")

    _project_id, _request_id, artifact_id = await _create_request_with_artifact(
        client, h_a, secret="{}"
    )

    cmt = await client.post(
        "/api/notifications/comments",
        json={"object_type": "artifact", "object_id": artifact_id, "body": "A的评论"},
        headers=h_a,
    )
    assert cmt.status_code == 200, cmt.text
    comment_id = cmt.json()["id"]

    list_b = await client.get(
        f"/api/notifications/comments?object_type=artifact&object_id={artifact_id}",
        headers=h_b,
    )
    assert list_b.status_code in (403, 404)

    create_b = await client.post(
        "/api/notifications/comments",
        json={"object_type": "artifact", "object_id": artifact_id, "body": "入侵评论"},
        headers=h_b,
    )
    assert create_b.status_code in (403, 404)

    resolve_b = await client.put(
        f"/api/notifications/comments/{comment_id}/resolve",
        json={"resolution": "resolved"},
        headers=h_b,
    )
    assert resolve_b.status_code in (403, 404)


# ─── BUG-116: JWT secret 校验 ───────────────────────────────────────


def test_bug116_rejects_example_jwt_secret():
    from app.services.jwt_secret import assert_jwt_secret_safe, INSECURE_JWT_SECRETS

    assert "change-this-to-a-random-secret-string" in INSECURE_JWT_SECRETS
    with pytest.raises(RuntimeError, match="公开示例|默认值|未配置|过短"):
        assert_jwt_secret_safe("change-this-to-a-random-secret-string")
    with pytest.raises(RuntimeError):
        assert_jwt_secret_safe("change-me-in-production")
    with pytest.raises(RuntimeError):
        assert_jwt_secret_safe("short")
    ok = assert_jwt_secret_safe("a" * 32)
    assert ok == "a" * 32


def test_bug116_env_example_has_no_usable_fixed_secret():
    root = os.path.dirname(os.path.dirname(__file__))
    example = open(os.path.join(root, ".env.example"), encoding="utf-8").read()
    assert "JWT_SECRET=change-this-to-a-random-secret-string" not in example
    assert "JWT_SECRET=change-me-in-production" not in example


# ─── BUG-117: MCP 配置鉴权 ──────────────────────────────────────────


async def test_bug117_ordinary_user_cannot_manage_global_mcp(client):
    h_user = await _auth_header(client, "bug117_user", "pass-u-12345")
    h_admin = await _auth_header(client)

    listed = await client.get("/api/agent/mcp/servers", headers=h_user)
    assert listed.status_code == 403

    created = await client.post(
        "/api/agent/mcp/servers",
        json={
            "name": "evil-stdio",
            "server_type": "stdio",
            "endpoint_ref": "python -c 'print(1)'",
        },
        headers=h_user,
    )
    assert created.status_code == 403

    admin_create = await client.post(
        "/api/agent/mcp/servers",
        json={
            "name": "ok-server",
            "server_type": "stdio",
            "endpoint_ref": "echo",
        },
        headers=h_admin,
    )
    assert admin_create.status_code == 200
    server_id = admin_create.json()["id"]

    policy_user = await client.post(
        f"/api/agent/mcp/servers/{server_id}/policies",
        json={"tool_name": "bash", "allowed_roles": ["member"], "requires_approval": False},
        headers=h_user,
    )
    assert policy_user.status_code == 403


# ─── BUG-113: allowed_tools 传入执行链 ───────────────────────────────


def test_bug113_bridge_injects_allowed_tools_into_env():
    from app.services.pi_agent_bridge import PiAgentBridge

    bridge = PiAgentBridge()
    env = bridge._build_extension_env(
        base_env={"PATH": "/usr/bin"},
        allowed_tools=["rag_search", "read"],
        scope_json='{"default":"personal"}',
        user_id=7,
        run_id=42,
        run_token="tok-abc",
        api_base="http://127.0.0.1:17957",
        one_shot_approved=["bash"],
    )
    assert env["AGENT_ALLOWED_TOOLS"] == "rag_search,read"
    assert env["AGENT_SCOPE_JSON"] == '{"default":"personal"}'
    assert env["AGENT_USER_ID"] == "7"
    assert env["AGENT_RUN_ID"] == "42"
    assert env["AGENT_RUN_TOKEN"] == "tok-abc"
    assert env["AGENT_API_BASE"] == "http://127.0.0.1:17957"
    assert env["AGENT_ONE_SHOT_APPROVED"] == "bash"


def test_bug113_extension_source_reads_whitelist_env():
    root = os.path.dirname(os.path.dirname(__file__))
    ext = open(
        os.path.join(root, "src/agent/extensions/agent-limiter.ts"),
        encoding="utf-8",
    ).read()
    assert "AGENT_ALLOWED_TOOLS" in ext
    assert "mock: true" not in ext
    assert "real_integration_needed" not in ext
    assert "AGENT_API_BASE" in ext
    assert "rag_search" in ext


def test_bug113_decide_approval_resumes_active_bridge():
    from app.services.pi_agent_bridge import (
        register_active_bridge,
        unregister_active_bridge,
        get_active_bridge,
        PiAgentBridge,
    )

    bridge = PiAgentBridge()
    register_active_bridge(99, bridge)
    assert get_active_bridge(99) is bridge
    unregister_active_bridge(99)
    assert get_active_bridge(99) is None


# ─── BUG-115: embedding worker + personal FTS ────────────────────────


@pytest.mark.asyncio
async def test_bug115_embedding_worker_processes_pending():
    from app.services.embedding_worker import process_pending_embeddings
    from app.services.knowledge_vector_service import VectorChunk

    chunk = MagicMock()
    chunk.id = 1
    chunk.text = "需求评审流程规范文档内容足够长"
    chunk.section = "intro"
    chunk.visibility = "private"
    chunk.document_id = 10

    doc = MagicMock()
    doc.id = 10
    doc.source_id = 5

    source = MagicMock()
    source.id = 5
    source.workspace_id = 1
    source.title = "规范"
    source.owner_id = 3
    source.visibility = "private"

    mock_session = AsyncMock()
    mock_chunk_repo = AsyncMock()
    mock_chunk_repo.list_pending_embedding.return_value = [chunk]
    mock_chunk_repo.update_embedding_status.return_value = 1

    mock_embed = AsyncMock()
    mock_embed.embed_batch.return_value = [[0.1] * 8]

    mock_vector = AsyncMock()
    mock_vector.upsert.return_value = 1

    with patch("app.services.embedding_worker.KnowledgeChunkRepository", return_value=mock_chunk_repo), \
         patch("app.services.embedding_worker.EmbeddingService", return_value=mock_embed), \
         patch("app.services.embedding_worker.get_knowledge_vector_service", return_value=mock_vector), \
         patch("app.services.embedding_worker._load_chunk_context", new=AsyncMock(return_value=(doc, source))):
        processed = await process_pending_embeddings(mock_session, batch_size=10)

    assert processed == 1
    mock_embed.embed_batch.assert_awaited()
    mock_vector.upsert.assert_awaited()
    args, _kwargs = mock_vector.upsert.await_args
    assert isinstance(args[0][0], VectorChunk)


def test_bug115_personal_fts_fallback_not_hard_disabled():
    import inspect
    from app.services.retrieval_service import RetrievalService

    src = inspect.getsource(RetrievalService._fallback_fts)
    assert "暂不支持 FTS5 降级" not in src
    assert "search_fts_personal" in src


# ─── BUG-118: lifespan dispose ───────────────────────────────────────


@pytest.mark.asyncio
async def test_bug118_lifespan_disposes_engine():
    from unittest.mock import AsyncMock, patch
    import main as main_mod

    with patch("main.ensure_branding_dirs"), \
         patch("main.init_db", new=AsyncMock()), \
         patch("app.services.tool_registry.register_builtin_tools"), \
         patch("app.services.embedding_worker.start_embedding_worker", new=AsyncMock()), \
         patch("app.services.embedding_worker.stop_embedding_worker", new=AsyncMock()), \
         patch("app.database.engine") as eng:
        eng.dispose = AsyncMock()
        cm = main_mod.lifespan(main_mod.app)
        await cm.__aenter__()
        await cm.__aexit__(None, None, None)
        eng.dispose.assert_awaited()
