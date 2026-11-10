"""Issue #9 / #10 修复回归测试。

覆盖审批链、权限可见性、上传、进程环境、前端输出与更新脚本的关键不变量。
"""

import os
import tempfile
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.conftest import init_test_db, make_test_app

ADMIN_CREDS = {"username": "admin", "password": "admin@2026"}


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


async def _login_admin(client):
    resp = await client.post("/api/auth/login", json=ADMIN_CREDS)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _register(client, prefix="approver"):
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "test123456"},
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return me.json()["id"], headers


async def _create_project(client, headers):
    resp = await client.post(
        "/api/review/projects",
        json={"name": f"issue910-{uuid.uuid4().hex[:6]}", "description": ""},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio(loop_scope="session")
async def test_fts_without_user_returns_only_team_sources(client_with_db):
    client, session_maker = client_with_db
    owner_id, _ = await _register(client, "fts_owner")

    from app.repositories.knowledge_source_repository import KnowledgeSourceRepository
    from app.repositories.workspace_repository import WorkspaceRepository
    from app.services.knowledge_ingestion import KnowledgeIngestionService

    async with session_maker() as session:
        ws = await WorkspaceRepository(session).get_default()
        repo = KnowledgeSourceRepository(session)
        team = await repo.create(
            source_type="upload", title="team", workspace_id=ws.id,
            visibility="team", extracted_text="公开团队资料内容，包含公开关键字",
        )
        private = await repo.create(
            source_type="upload", title="private", workspace_id=ws.id,
            owner_type="user", visibility="private", owner_id=owner_id,
            extracted_text="机密个人资料内容，包含机密关键字",
        )
        ingestion = KnowledgeIngestionService(session)
        await ingestion.ingest_source(team.id)
        await ingestion.ingest_source(private.id)

        anonymous = await ingestion.search_fts("机密关键字", ws.id, user_id=None)
        assert anonymous == [] or all(r["source_id"] == team.id for r in anonymous)

        owned = await ingestion.search_fts("机密关键字", ws.id, user_id=owner_id)
        assert any(r["source_id"] == private.id for r in owned)
        await session.rollback()


@pytest.mark.asyncio(loop_scope="session")
async def test_mcp_policy_without_explicit_rule_is_denied(client_with_db):
    client, session_maker = client_with_db
    from app.models.user import MCPServerConfig
    from app.services.mcp_adapter import MCPAdapterManager

    async with session_maker() as session:
        server = MCPServerConfig(name="test", server_type="stdio", endpoint_ref="noop")
        session.add(server)
        await session.flush()
        decision = await MCPAdapterManager().check_policy(
            session, server.id, "dangerous_tool", user_role="member",
        )
        await session.rollback()

    assert decision["allowed"] is False
    assert decision["requires_approval"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_viewer_cannot_delete_project(client_with_db):
    client, session_maker = client_with_db
    user_id, headers = await _register(client, "viewer_owner")
    project_id = await _create_project(client, headers)

    from app.models.workspace import WorkspaceMember

    async with session_maker() as session:
        member = (
            await session.execute(
                select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
            )
        ).scalar_one()
        member.role = "viewer"
        await session.commit()

    # 只读仍可用
    assert (await client.get(f"/api/review/projects/{project_id}", headers=headers)).status_code == 200
    # 写操作必须被拒绝
    resp = await client.delete(f"/api/review/projects/{project_id}", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_initiator_cannot_be_approver(client_with_db):
    client, _ = client_with_db
    headers = await _login_admin(client)
    project_id = await _create_project(client, headers)

    resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [1]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "发起人" in resp.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_add_participant_rejects_unknown_user(client_with_db):
    client, _ = client_with_db
    headers = await _login_admin(client)
    project_id = await _create_project(client, headers)
    approver_id, _ = await _register(client)

    req = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id]},
        headers=headers,
    )
    assert req.status_code == 200, req.text

    resp = await client.post(
        f"/api/review/requests/{req.json()['id']}/participants",
        params={"user_id": 999999, "role": "Observer"},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_inactive_approver_cannot_decide(client_with_db):
    client, session_maker = client_with_db
    headers = await _login_admin(client)
    project_id = await _create_project(client, headers)
    approver_id, approver_headers = await _register(client)

    req = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id]},
        headers=headers,
    )
    assert req.status_code == 200, req.text
    request_id = req.json()["id"]
    rounds = await client.get(f"/api/review/requests/{request_id}/rounds", headers=headers)
    round_id = rounds.json()[0]["id"]

    from app.models.workspace import WorkspaceMember

    async with session_maker() as session:
        member = (
            await session.execute(
                select(WorkspaceMember).where(WorkspaceMember.user_id == approver_id)
            )
        ).scalar_one()
        member.status = "inactive"
        member.role = "viewer"
        await session.commit()

    resp = await client.post(
        f"/api/review/rounds/{round_id}/decide",
        json={"decision": "approved", "comment": "should fail"},
        headers=approver_headers,
    )
    assert resp.status_code == 403


def test_review_delete_only_within_trusted_roots(tmp_path, monkeypatch):
    from app.storage import review_file_storage

    runtime_root = tmp_path / "runtime"
    upload_root = runtime_root / "data" / "review_uploads"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    def fake_runtime_path(*parts):
        return runtime_root.joinpath(*parts)

    monkeypatch.setattr(review_file_storage, "runtime_path", fake_runtime_path)
    storage = review_file_storage.ReviewFileStorage(upload_dir=str(upload_root))
    import asyncio

    asyncio.run(storage.delete_document_files(0, file_path=str(outside)))
    assert outside.exists(), "删除路径越界时不得删除 runtime 外文件"


def test_agent_env_is_minimal():
    from app.services import pi_agent_bridge

    source = __import__("inspect").getsource(pi_agent_bridge)
    assert "_AGENT_ENV_ALLOWLIST" in source
    assert "dict(os.environ)" not in source


def test_frontend_mermaid_is_strict_and_sanitized():
    from pathlib import Path

    root = Path(__file__).parent.parent / "src/static/js"
    for name in ("review.js", "chat.js"):
        text = (root / name).read_text(encoding="utf-8")
        assert "securityLevel: 'loose'" not in text
        assert "securityLevel: 'strict'" in text
        assert "_sanitizeMermaidSvg" in text
        assert "DOMPurify.sanitize" in text


def test_update_script_has_atomic_replace_and_start_rollback():
    from pathlib import Path

    text = (Path(__file__).parent.parent / "update.sh").read_text(encoding="utf-8")
    assert "暂存新版本代码" in text
    assert "原子替换代码目录" in text
    assert 'if ! "$PROJECT_DIR/start.sh" start' in text
    assert "符号链接或特殊文件条目" in text


def test_database_writes_admin_secret_before_commit():
    from pathlib import Path

    text = (Path(__file__).parent.parent / "src/app/database.py").read_text(encoding="utf-8")
    start = text.index("session.add(admin)")
    end = text.index("if generated:\n                logger.warning", start)
    block = text[start:end]
    assert "_write_admin_initial_secret(initial)" in block
    assert "await session.commit()" in block
    assert block.index("_write_admin_initial_secret") < block.index("await session.commit()")


@pytest.mark.asyncio(loop_scope="session")
async def test_viewer_cannot_cancel_review(client_with_db):
    client, session_maker = client_with_db
    user_id, headers = await _register(client, "viewer_cancel")
    project_id = await _create_project(client, headers)

    from app.models.review import ReviewTask
    from app.models.workspace import WorkspaceMember

    async with session_maker() as session:
        session.add(ReviewTask(project_id=project_id, mode="quick", status="running", created_by=user_id))
        await session.flush()
        task_id = (await session.execute(
            select(ReviewTask).where(ReviewTask.project_id == project_id)
        )).scalar_one().id
        member = (await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
        )).scalar_one()
        member.role = "viewer"
        await session.commit()

    resp = await client.post(f"/api/review/projects/{project_id}/reviews/{task_id}/cancel", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_inactive_initiator_cannot_list_create_or_resubmit(client_with_db):
    client, session_maker = client_with_db
    initiator_id, headers = await _register(client, "inactive_initiator")
    approver_id, _ = await _register(client, "inactive_approver")
    project_id = await _create_project(client, headers)

    req = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id]},
        headers=headers,
    )
    assert req.status_code == 200, req.text
    request_id = req.json()["id"]

    from app.models.review import ReviewRequest
    from app.models.workspace import WorkspaceMember

    async with session_maker() as session:
        member = (await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == initiator_id)
        )).scalar_one()
        member.status = "inactive"
        review_req = await session.get(ReviewRequest, request_id)
        review_req.status = "rejected"
        await session.commit()

    listed = await client.get("/api/review/requests", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == []

    created = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id]},
        headers=headers,
    )
    assert created.status_code == 403

    resubmitted = await client.post(f"/api/review/requests/{request_id}/resubmit", headers=headers)
    assert resubmitted.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_private_source_comment_resolve_rejects_other_writer(client_with_db):
    client, session_maker = client_with_db
    owner_id, owner_headers = await _register(client, "private_owner")
    writer_id, writer_headers = await _register(client, "private_writer")

    from app.models.workspace import KnowledgeSource
    from app.repositories.workspace_repository import WorkspaceRepository

    async with session_maker() as session:
        ws = await WorkspaceRepository(session).get_default()
        source = KnowledgeSource(
            workspace_id=ws.id, owner_type="user", visibility="private",
            owner_id=owner_id, source_type="upload", title="private",
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    created = await client.post(
        "/api/notifications/comments",
        json={"object_type": "knowledge_source", "object_id": source_id, "body": "secret"},
        headers=owner_headers,
    )
    assert created.status_code == 200, created.text
    comment_id = created.json()["id"]

    read = await client.get(
        f"/api/notifications/comments?object_type=knowledge_source&object_id={source_id}",
        headers=writer_headers,
    )
    assert read.status_code == 404

    resolved = await client.put(
        f"/api/notifications/comments/{comment_id}/resolve",
        json={"resolution": "resolved"},
        headers=writer_headers,
    )
    assert resolved.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_chat_attachment_owner_check(tmp_path):
    from app.storage.chat_file_storage import ChatFileStorage

    storage = ChatFileStorage(upload_dir=str(tmp_path / "uploads"))
    stored = await storage.save_upload(filename="a.txt", content=b"secret", owner_id=7)
    assert stored.file_id.startswith("u7_")
    assert storage.read_text_for_user(stored.file_id, 7) == "secret"
    assert storage.read_text_for_user(stored.file_id, 8) is None


def _write_update_functions(tmp_path):
    from pathlib import Path
    root = Path(__file__).parent.parent
    text = (root / "update.sh").read_text(encoding="utf-8")
    funcs = text.split('log "========== 版本更新开始 =========="', 1)[0]
    path = tmp_path / "update_functions.sh"
    path.write_text(funcs, encoding="utf-8")
    return path


def test_update_copy_failure_restores_old_tree(tmp_path):
    import subprocess

    funcs = _write_update_functions(tmp_path)
    project = tmp_path / "project"
    extracted = tmp_path / "extracted"
    (project / "src").mkdir(parents=True)
    (project / "src" / "marker.txt").write_text("old", encoding="utf-8")
    (project / "VERSION").write_text("0.0.1", encoding="utf-8")
    (extracted / "src").mkdir(parents=True)
    (extracted / "src" / "marker.txt").write_text("new", encoding="utf-8")
    (extracted / "VERSION").write_text("0.0.2", encoding="utf-8")

    harness = f'''
set -u
log() {{ echo "[UPDATE] $1"; }}
warn() {{ echo "[WARN] $1"; }}
fail() {{ echo "[FAIL] $1"; }}
source "{funcs}"
PROJECT_DIR="{project}"
RUNTIME_DIR="{project}/runtime"
BACKUP_DIR="{project}/runtime/update_backups"
NEW_VERSION="0.0.2"
mv() {{
  if [ "$2" = "$PROJECT_DIR/src" ] && case "$1" in */.update-stage.*/src) true;; *) false;; esac; then
    return 1
  fi
  command mv "$@"
}}
if copy_versioned_files "{extracted}"; then
  echo "unexpected-success"; exit 10
fi
[ "$(cat "$PROJECT_DIR/src/marker.txt")" = "old" ] || exit 11
[ "$(cat "$PROJECT_DIR/VERSION")" = "0.0.1" ] || exit 12
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_update_rollback_config_failure_returns_error_and_keeps_config(tmp_path):
    import subprocess

    funcs = _write_update_functions(tmp_path)
    project = tmp_path / "project"
    runtime = project / "runtime"
    backup = runtime / "backup"
    (project / "src").mkdir(parents=True)
    (project / "src" / "marker.txt").write_text("current", encoding="utf-8")
    (runtime / "config").mkdir(parents=True)
    (runtime / "config" / "keep.yaml").write_text("current", encoding="utf-8")
    (backup / "runtime_config").mkdir(parents=True)
    (backup / "runtime_config" / "keep.yaml").write_text("backup", encoding="utf-8")
    (project / "start.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (project / "start.sh").chmod(0o755)
    subprocess.run(["tar", "-czf", str(backup / "code.tar.gz"), "-C", str(project), "src"], check=True)

    harness = f'''
set -u
log() {{ echo "[UPDATE] $1"; }}
warn() {{ echo "[WARN] $1"; }}
fail() {{ echo "[FAIL] $1"; }}
source "{funcs}"
PROJECT_DIR="{project}"
RUNTIME_DIR="{runtime}"
BACKUP_DIR="{runtime}/backups"
CURRENT_BACKUP_DIR="{backup}"
ROLLBACK_ON_FAILURE=true
SKIP_BACKUP=false
NEW_VERSION="0.0.2"
mv_failed=0
mv() {{
  if [ "$2" = "$RUNTIME_DIR/config" ] && [ "$mv_failed" = 0 ]; then
    mv_failed=1
    return 1
  fi
  command mv "$@"
}}
if restore_backup; then
  echo "unexpected-success"; exit 10
fi
[ "$(cat "$RUNTIME_DIR/config/keep.yaml")" = "current" ] || exit 11
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_start_sh_persists_generated_jwt_secret(tmp_path):
    import subprocess
    from pathlib import Path

    root = Path(__file__).parent.parent
    text = (root / "start.sh").read_text(encoding="utf-8")
    start = text.index("ensure_persistent_jwt_secret()")
    end = text.index("\n}\n", start) + 3
    func = text[start:end]
    (tmp_path / "src").symlink_to(root / "src", target_is_directory=True)
    funcfile = tmp_path / "jwt_func.sh"
    funcfile.write_text(func, encoding="utf-8")
    harness = tmp_path / "jwt_harness.sh"
    harness.write_text(
        f'PROJECT_DIR="{tmp_path}"\n'
        f'source "{funcfile}"\n'
        "JWT_SECRET=\"\"\n"
        "ensure_persistent_jwt_secret\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(harness)],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(root / "src")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    secret = next(line.split("=", 1)[1] for line in env_text.splitlines() if line.startswith("JWT_SECRET="))
    assert len(secret) == 64


def test_update_restore_extract_failure_keeps_code(tmp_path):
    import subprocess

    funcs = _write_update_functions(tmp_path)
    project = tmp_path / "project"
    runtime = project / "runtime"
    backup = runtime / "backup"
    (project / "src").mkdir(parents=True)
    (project / "src" / "marker.txt").write_text("current", encoding="utf-8")
    (project / "start.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (project / "start.sh").chmod(0o755)
    backup.mkdir(parents=True)
    (backup / "code.tar.gz").write_bytes(b"not a tar")

    harness = f'''
log() {{ echo "$1"; }}; warn() {{ :; }}; fail() {{ echo "FAIL $1"; }}
source "{funcs}"
PROJECT_DIR="{project}"; RUNTIME_DIR="{runtime}"; BACKUP_DIR="{runtime}/backups"
CURRENT_BACKUP_DIR="{backup}"; ROLLBACK_ON_FAILURE=true; SKIP_BACKUP=false
if restore_backup; then exit 10; fi
[ "$(cat "$PROJECT_DIR/src/marker.txt")" = "current" ] || exit 11
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio(loop_scope="session")
async def test_legacy_self_approval_is_rejected(client_with_db):
    client, session_maker = client_with_db
    headers = await _login_admin(client)
    from app.models.user import AgentApprovalRequest, AgentProfile, AgentRun

    async with session_maker() as session:
        profile = AgentProfile(owner_type="user", owner_id=1, name="legacy")
        session.add(profile)
        await session.flush()
        run = AgentRun(agent_id=profile.id, user_id=1, goal="g", status="running")
        session.add(run)
        await session.flush()
        approval = AgentApprovalRequest(
            run_id=run.id, requester_id=1, approver_id=1,
            action_type="write", status="pending",
        )
        session.add(approval)
        await session.commit()
        approval_id = approval.id

    resp = await client.post(
        f"/api/agent/approvals/{approval_id}/decide",
        json={"decision": "approved"},
        headers=headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_viewer_initiator_cannot_resolve_review_comment(client_with_db):
    client, session_maker = client_with_db
    user_id, headers = await _register(client, "viewer_comment")
    project_id = await _create_project(client, headers)
    approver_id, _ = await _register(client, "viewer_comment_approver")

    req = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id]},
        headers=headers,
    )
    request_id = req.json()["id"]
    comment = await client.post(
        "/api/notifications/comments",
        json={"object_type": "review_request", "object_id": request_id, "body": "x"},
        headers=headers,
    )
    comment_id = comment.json()["id"]

    from app.models.workspace import WorkspaceMember

    async with session_maker() as session:
        member = (await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
        )).scalar_one()
        member.role = "viewer"
        await session.commit()

    resp = await client.put(
        f"/api/notifications/comments/{comment_id}/resolve",
        json={"resolution": "resolved"},
        headers=headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_legacy_private_project_source_ref_not_injected(client_with_db):
    client, session_maker = client_with_db
    owner_id, headers = await _register(client, "legacy_private_ref")
    project_id = await _create_project(client, headers)

    from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
    from app.models.workspace import KnowledgeSource, ProjectSourceRef
    from app.repositories.workspace_repository import WorkspaceRepository
    from app.routers.review import _load_project_knowledge_context

    async with session_maker() as session:
        ws = await WorkspaceRepository(session).get_default()
        source = KnowledgeSource(
            workspace_id=ws.id, owner_type="user", visibility="private",
            owner_id=owner_id, source_type="upload", title="legacy",
        )
        session.add(source)
        await session.flush()
        doc = KnowledgeDocument(source_id=source.id, filename="x.md", version=1)
        session.add(doc)
        await session.flush()
        session.add(KnowledgeChunk(
            document_id=doc.id, chunk_no=1, text="私有正文不应注入",
            visibility="private", embedding_status="done",
        ))
        session.add(ProjectSourceRef(project_id=project_id, source_id=source.id, ref_type="context"))
        await session.commit()

        assert await _load_project_knowledge_context(session, project_id) is None


def test_html_to_markdown_keeps_comparisons_and_blocks_encoded_js():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).parent.parent / "skills/docx-to-markdown/scripts/convert_docx.py"
    spec = importlib.util.spec_from_file_location("convert_docx_issue910", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    text = mod.html_to_markdown("a &lt; b and c &gt; d")
    assert "a < b and c > d" in text

    link = mod.html_to_markdown('<a href="javascript&#58;alert(1)">click</a>')
    assert "click" in link
    assert "javascript" not in link.lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_terminal_status_does_not_overwrite_cancelled_with_autoflush(client_with_db):
    client, session_maker = client_with_db
    headers = await _login_admin(client)
    project_id = await _create_project(client, headers)

    from sqlalchemy import update
    from app.models.review import ReviewTask
    from app.routers.review import _commit_terminal_status

    async with session_maker() as session:
        task = ReviewTask(project_id=project_id, mode="full", status="running")
        session.add(task)
        await session.commit()
        task_id = task.id

        loaded = await session.get(ReviewTask, task_id)
        loaded.status = "failed"
        loaded.completed_at = __import__("app.utils", fromlist=["now_cn"]).now_cn()
        await session.execute(
            update(ReviewTask).where(ReviewTask.id == task_id).values(status="cancelled")
        )
        assert await _commit_terminal_status(session, loaded) is False
        await session.refresh(loaded)
        assert loaded.status == "cancelled"


@pytest.mark.asyncio(loop_scope="session")
async def test_pi_agent_end_error_and_blank_line_handling():
    import json
    from types import SimpleNamespace
    from app.services import pi_agent_bridge as bridge_mod

    class FakeProc:
        def poll(self):
            return None

    def make_bridge(lines):
        bridge = bridge_mod.PiAgentBridge()
        bridge._proc = FakeProc()
        bridge._run = SimpleNamespace(
            id=1, user_id=1, goal="g", total_steps=0, total_tool_calls=0,
        )
        statuses = []

        class Repo:
            async def update_status(self, run, status, error_message=None):
                statuses.append((status, error_message))

        bridge._run_repo = Repo()
        bridge._read_stderr = lambda: ""
        seq = iter(lines)

        def fake_line(timeout):
            try:
                return next(seq)
            except StopIteration:
                return bridge_mod._STDOUT_EOF

        bridge._read_stdout_line = fake_line
        return bridge, statuses

    # 空行不能被当作 EOF；其后的成功 agent_end 应把 run 置 completed。
    bridge, statuses = make_bridge([
        "",
        json.dumps({"type": "agent_end", "success": True}),
    ])
    events = [e async for e in bridge.stream_events(timeout=5)]
    assert statuses[-1][0] == "completed"
    assert any(e.get("type") == "agent_end" for e in events)

    # 携带提供商错误的 agent_end 必须 failed。
    bridge, statuses = make_bridge([
        json.dumps({"type": "agent_end", "error": "provider exploded"}),
    ])
    events = [e async for e in bridge.stream_events(timeout=5)]
    assert statuses[-1][0] == "failed"
    assert "provider exploded" in (statuses[-1][1] or "")
    assert events[-1].get("error")


def test_update_err_trap_triggers_rollback_after_backup(tmp_path):
    import subprocess

    funcs = _write_update_functions(tmp_path)
    harness = f'''
log() {{ echo "$1"; }}; warn() {{ :; }}; fail() {{ echo "FAIL $1"; }}
source "{funcs}"
UPDATE_STARTED=true
restore_backup() {{ echo "ROLLBACK-CALLED"; return 0; }}
wait_for_health() {{ return 0; }}
get_running_version() {{ echo "old"; }}
fail_in_function() {{ false; }}
fail_in_function
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, errors="replace")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "ROLLBACK-CALLED" in result.stdout


@pytest.mark.asyncio(loop_scope="session")
async def test_member_approver_can_resolve_comment(client_with_db):
    client, _ = client_with_db
    admin_headers = await _login_admin(client)
    project_id = await _create_project(client, admin_headers)
    approver_id, approver_headers = await _register(client, "member_approver")

    req = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id]},
        headers=admin_headers,
    )
    request_id = req.json()["id"]
    comment = await client.post(
        "/api/notifications/comments",
        json={"object_type": "review_request", "object_id": request_id, "body": "x"},
        headers=admin_headers,
    )
    resp = await client.put(
        f"/api/notifications/comments/{comment.json()['id']}/resolve",
        json={"resolution": "resolved"},
        headers=approver_headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio(loop_scope="session")
async def test_legacy_initiator_self_round_decision_rejected(client_with_db):
    client, session_maker = client_with_db
    headers = await _login_admin(client)
    project_id = await _create_project(client, headers)
    approver_id, _ = await _register(client, "legacy_round_approver")

    req = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id]},
        headers=headers,
    )
    request_id = req.json()["id"]
    rounds = await client.get(f"/api/review/requests/{request_id}/rounds", headers=headers)
    round_id = rounds.json()[0]["id"]

    from app.models.review import ReviewRound

    async with session_maker() as session:
        rnd = await session.get(ReviewRound, round_id)
        rnd.approver_id = 1
        await session.commit()

    resp = await client.post(
        f"/api/review/rounds/{round_id}/decide",
        json={"decision": "approved"},
        headers=headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_pi_reads_tail_events_after_process_exit():
    import json
    from types import SimpleNamespace
    from app.services import pi_agent_bridge as bridge_mod

    class DeadProc:
        def poll(self):
            return 7

    bridge = bridge_mod.PiAgentBridge()
    bridge._proc = DeadProc()
    bridge._run = SimpleNamespace(id=1, user_id=1, goal="g", total_steps=0, total_tool_calls=0)
    statuses = []

    class Repo:
        async def update_status(self, run, status, error_message=None):
            statuses.append(status)

    bridge._run_repo = Repo()
    bridge._read_stderr = lambda: ""
    seq = iter([json.dumps({"type": "turn_start"}), json.dumps({"type": "agent_end", "success": True})])

    def fake_line(timeout):
        try:
            return next(seq)
        except StopIteration:
            return bridge_mod._STDOUT_EOF

    bridge._read_stdout_line = fake_line
    _ = [e async for e in bridge.stream_events(timeout=5)]
    assert statuses[-1] == "completed"


def test_create_backup_tolerates_missing_optional_managed_files(tmp_path):
    import subprocess

    funcs = _write_update_functions(tmp_path)
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "marker.txt").write_text("x", encoding="utf-8")
    (project / "VERSION").write_text("1", encoding="utf-8")
    harness = f'''
log() {{ echo "$1"; }}; warn() {{ :; }}; fail() {{ echo "FAIL $1"; }}
source "{funcs}"
PROJECT_DIR="{project}"; RUNTIME_DIR="{project}/runtime"; BACKUP_DIR="{project}/runtime/backups"
CURRENT_BACKUP_DIR=""; SKIP_BACKUP=false
create_backup "1" || exit 10
[ -f "$CURRENT_BACKUP_DIR/code.tar.gz" ] || exit 11
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio(loop_scope="session")
async def test_cost_stats_explicit_chat_mode_not_misclassified(client_with_db, tmp_path, monkeypatch):
    _, session_maker = client_with_db
    runtime = tmp_path / "runtime"
    logs = runtime / "logs"
    logs.mkdir(parents=True)
    (logs / "llm_sessions.jsonl").write_text(
        '{"timestamp":"2026-11-09T10:00:00","model":"my-embedding-chat",'
        '"usage":{"prompt_tokens":10,"completion_tokens":20},"mode":"chat"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("RUNTIME_ROOT", str(runtime))

    from app.models.review import CostDailySummary
    from app.services.cost_stats_service import CostStatsService

    async with session_maker() as session:
        await CostStatsService(session).aggregate_daily("2026-11-09")
        row = (await session.execute(
            select(CostDailySummary).where(CostDailySummary.model_id == "my-embedding-chat")
        )).scalar_one()
        assert row.mode == "chat"
        assert row.input_tokens == 10
        assert row.output_tokens == 20
        assert row.embedding_tokens == 0


def test_update_restore_midway_failure_restores_all_items_and_keeps_recovery_copies(tmp_path):
    import subprocess

    funcs = _write_update_functions(tmp_path)
    project = tmp_path / "project"
    runtime = project / "runtime"
    backup = runtime / "backup"
    backup_tree = tmp_path / "backup_tree"

    (project / "src").mkdir(parents=True)
    (project / "src" / "marker.txt").write_text("current-src", encoding="utf-8")
    (project / "tools").mkdir(parents=True)
    (project / "tools" / "tool.txt").write_text("current-tools", encoding="utf-8")
    (project / "VERSION").write_text("0.0.2", encoding="utf-8")
    (project / "start.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (project / "start.sh").chmod(0o755)

    (backup_tree / "src").mkdir(parents=True)
    (backup_tree / "src" / "marker.txt").write_text("backup-src", encoding="utf-8")
    (backup_tree / "tools").mkdir(parents=True)
    (backup_tree / "tools" / "tool.txt").write_text("backup-tools", encoding="utf-8")
    (backup_tree / "VERSION").write_text("0.0.1", encoding="utf-8")
    backup.mkdir(parents=True)
    subprocess.run(
        ["tar", "-czf", str(backup / "code.tar.gz"), "-C", str(backup_tree), "src", "tools", "VERSION"],
        check=True,
    )

    harness = f'''
set -u
log() {{ echo "[UPDATE] $1"; }}
warn() {{ echo "[WARN] $1"; }}
fail() {{ echo "[FAIL] $1"; }}
source "{funcs}"
PROJECT_DIR="{project}"
RUNTIME_DIR="{runtime}"
BACKUP_DIR="{runtime}/backups"
CURRENT_BACKUP_DIR="{backup}"
ROLLBACK_ON_FAILURE=true
SKIP_BACKUP=false
mv() {{
  if [ "$1" = "$PROJECT_DIR/tools" ] && case "$2" in */.restore-txn.*/old-tools) true;; *) false;; esac; then
    return 1
  fi
  command mv "$@"
}}
if restore_backup; then
  echo "unexpected-success"; exit 10
fi
[ "$(cat "$PROJECT_DIR/src/marker.txt")" = "current-src" ] || exit 11
[ "$(cat "$PROJECT_DIR/tools/tool.txt")" = "current-tools" ] || exit 12
[ "$(cat "$PROJECT_DIR/VERSION")" = "0.0.2" ] || exit 13
txn_found=0
for d in "$PROJECT_DIR"/.restore-txn.*; do
  if [ -f "$d/old-src/marker.txt" ] && [ "$(cat "$d/old-src/marker.txt")" = "current-src" ]; then
    txn_found=1
  fi
done
[ "$txn_found" = 1 ] || exit 14
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio(loop_scope="session")
async def test_embedding_worker_stale_skip_keeps_done_and_archived_source_not_recalled(client_with_db, tmp_path, monkeypatch):
    client, session_maker = client_with_db
    admin_headers = await _login_admin(client)

    from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
    from app.models.workspace import KnowledgeSource
    from app.repositories.workspace_repository import WorkspaceRepository
    from app.services import embedding_worker, knowledge_vector_service
    from app.services.embedding_worker import process_pending_embeddings
    from app.services.knowledge_vector_service import KnowledgeVectorService, VectorChunk
    from app.services.retrieval_service import RetrievalService

    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path / "runtime"))
    real_vector_svc = KnowledgeVectorService()
    monkeypatch.setattr(embedding_worker, "get_knowledge_vector_service", lambda: real_vector_svc)
    monkeypatch.setattr(knowledge_vector_service, "get_knowledge_vector_service", lambda: real_vector_svc)

    async with session_maker() as session:
        ws = await WorkspaceRepository(session).get_default()
        ws_id = ws.id
        src = KnowledgeSource(
            workspace_id=ws_id, owner_type="workspace", visibility="team",
            source_type="upload", title="interleave", status="active",
        )
        session.add(src)
        await session.flush()
        doc = KnowledgeDocument(source_id=src.id, filename="a.md", version=1)
        session.add(doc)
        await session.flush()
        chunk = KnowledgeChunk(
            document_id=doc.id, chunk_no=1, text="old chunk text",
            visibility="team", embedding_status="pending",
        )
        session.add(chunk)
        await session.commit()
        chunk_id = chunk.id
        source_id = src.id

    dim = 1536
    new_vec = [0.25] * dim
    old_vec = [0.75] * dim

    # 1. 模拟旧 worker 在 embed_batch 期间，新入库 + 新 worker 已将该 chunk 更新为新正文、写入真实 LanceDB 并置 done
    class InterleavingEmbedder:
        async def embed_batch(self, texts):
            async with session_maker() as other_db:
                c = await other_db.get(KnowledgeChunk, chunk_id)
                c.text = "new chunk text"
                c.embedding_status = "done"
                await other_db.commit()
            await real_vector_svc.upsert(
                [
                    VectorChunk(
                        chunk_id=chunk_id,
                        source_id=source_id,
                        workspace_id=ws_id,
                        title="interleave",
                        section=None,
                        text="new chunk text",
                        owner_id=1,
                        visibility="team",
                    )
                ],
                [new_vec],
            )
            return [old_vec for _ in texts]

    async with session_maker() as worker_db:
        written = await process_pending_embeddings(
            worker_db, embedding_service=InterleavingEmbedder()
        )
        assert written == 0

    async with session_maker() as check_db:
        refreshed = await check_db.get(KnowledgeChunk, chunk_id)
        assert refreshed.text == "new chunk text"
        assert refreshed.embedding_status == "done"

    # 2. 模拟资料 DELETE 返回 200（归档）后，在途 worker 完成 embed_batch；不能复活向量或被检索召回
    async with session_maker() as setup_db:
        c = await setup_db.get(KnowledgeChunk, chunk_id)
        c.embedding_status = "pending"
        await setup_db.commit()

    class ArchivingEmbedder:
        async def embed_batch(self, texts):
            del_resp = await client.delete(
                f"/api/workspace/{ws_id}/sources/{source_id}",
                headers=admin_headers,
            )
            assert del_resp.status_code == 200, del_resp.text
            return [new_vec for _ in texts]

        async def embed_query(self, query):
            return new_vec

    async with session_maker() as worker_db2:
        written2 = await process_pending_embeddings(
            worker_db2, embedding_service=ArchivingEmbedder()
        )
        assert written2 == 0

    # 即便外部残留向量仍在 LanceDB 中，RetrievalService 也必须按 source.status=='active' 过滤
    await real_vector_svc.upsert(
        [
            VectorChunk(
                chunk_id=chunk_id,
                source_id=source_id,
                workspace_id=ws_id,
                title="interleave",
                section=None,
                text="archived text should not be recalled",
                owner_id=1,
                visibility="team",
            )
        ],
        [new_vec],
    )
    async with session_maker() as force_done_db:
        c = await force_done_db.get(KnowledgeChunk, chunk_id)
        c.embedding_status = "done"
        await force_done_db.commit()

    async with session_maker() as retrieve_db:
        retrieval = RetrievalService(
            vector_service=real_vector_svc,
            embedding_service=ArchivingEmbedder(),
            db_session=retrieve_db,
        )
        resp = await retrieval.retrieve("chunk", workspace_id=ws_id, user_id=1)
        assert resp.results == []


@pytest.mark.asyncio(loop_scope="session")
async def test_pi_sdk_nested_agent_end_error_and_assistant_message_event_delta():
    import json
    from types import SimpleNamespace
    from app.services import pi_agent_bridge as bridge_mod

    class FakeProc:
        def poll(self):
            return None

    def make_bridge(lines):
        bridge = bridge_mod.PiAgentBridge()
        bridge._proc = FakeProc()
        bridge._run = SimpleNamespace(
            id=1, user_id=1, goal="g", total_steps=0, total_tool_calls=0,
        )
        statuses = []

        class Repo:
            async def update_status(self, run, status, error_message=None):
                statuses.append((status, error_message))

        bridge._run_repo = Repo()
        bridge._read_stderr = lambda: ""
        seq = iter(lines)

        def fake_line(timeout):
            try:
                return next(seq)
            except StopIteration:
                return bridge_mod._STDOUT_EOF

        bridge._read_stdout_line = fake_line
        return bridge, statuses

    # 1. 成功流：转发 assistantMessageEvent.delta
    bridge, statuses = make_bridge([
        json.dumps({"type": "turn_start"}),
        json.dumps({
            "type": "message_update",
            "usage": {"input": 1, "output": 2},
            "assistantMessageEvent": {
                "type": "text_delta",
                "contentIndex": 0,
                "delta": "Hello from Pi SDK",
            },
        }),
        json.dumps({
            "type": "agent_end",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": [{"type": "text", "text": "Hello from Pi SDK"}], "stopReason": "stop"},
            ],
        }),
    ])
    events = [e async for e in bridge.stream_events(timeout=5)]
    assert statuses[-1][0] == "completed"
    msg_updates = [e for e in events if e.get("type") == "message_update"]
    assert len(msg_updates) == 1
    assert msg_updates[0]["text"] == "Hello from Pi SDK"

    # 2. 失败流：错误位于 agent_end.messages[-1].stopReason="error"
    bridge, statuses = make_bridge([
        json.dumps({"type": "turn_start"}),
        json.dumps({
            "type": "agent_end",
            "messages": [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": [],
                    "stopReason": "error",
                    "errorMessage": "synthetic provider failure",
                },
            ],
        }),
    ])
    events = [e async for e in bridge.stream_events(timeout=5)]
    assert statuses[-1][0] == "failed"
    assert "synthetic provider failure" in (statuses[-1][1] or "")
    assert events[-1].get("type") == "agent_end"
    assert "synthetic provider failure" in (events[-1].get("error") or "")


@pytest.mark.asyncio(loop_scope="session")
async def test_resubmit_deactivated_approver_and_observer_comment_and_inactive_presentation(client_with_db):
    client, session_maker = client_with_db
    creator_id, creator_headers = await _register(client, "pres_creator")
    approver_id, approver_headers = await _register(client, "resub_approver")
    observer_id, observer_headers = await _register(client, "req_observer")
    project_id = await _create_project(client, creator_headers)

    # 发起审查请求并添加 Observer
    req = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver_id], "goal": "机密审查目标正文"},
        headers=creator_headers,
    )
    assert req.status_code == 200, req.text
    request_id = req.json()["id"]

    add_obs = await client.post(
        f"/api/review/requests/{request_id}/participants",
        params={"user_id": observer_id, "role": "Observer"},
        headers=creator_headers,
    )
    assert add_obs.status_code == 200, add_obs.text

    # 1. Observer 不能创建评论
    obs_comment = await client.post(
        "/api/notifications/comments",
        json={"object_type": "review_request", "object_id": request_id, "body": "observer comment"},
        headers=observer_headers,
    )
    assert obs_comment.status_code == 403

    # 2. 审批人驳回后被停用，重新提交必须被拒绝且不发送新通知
    rounds = await client.get(f"/api/review/requests/{request_id}/rounds", headers=creator_headers)
    round_id = rounds.json()[0]["id"]
    dec = await client.post(
        f"/api/review/rounds/{round_id}/decide",
        json={"decision": "rejected", "comment": "need changes"},
        headers=approver_headers,
    )
    assert dec.status_code == 200, dec.text

    from app.models.user import Notification
    from app.models.workspace import WorkspaceMember

    async with session_maker() as session:
        before_notifs = (await session.execute(
            select(Notification).where(Notification.recipient_id == approver_id)
        )).scalars().all()
        before_count = len(before_notifs)

        member = (await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == approver_id)
        )).scalar_one()
        member.status = "inactive"
        await session.commit()

    resub = await client.post(
        f"/api/review/requests/{request_id}/resubmit",
        headers=creator_headers,
    )
    assert resub.status_code == 422

    async with session_maker() as session:
        after_notifs = (await session.execute(
            select(Notification).where(Notification.recipient_id == approver_id)
        )).scalars().all()
        assert len(after_notifs) == before_count

    # 3. 项目创建者被停用后，讲解准备模式不得读取其旧项目内容
    from app.services.chat_application_service import ChatApplicationService
    from app.storage.chat_file_storage import ChatFileStorage

    async with session_maker() as session:
        svc = ChatApplicationService(session, ChatFileStorage())
        active_ctx = await svc.build_presentation_context(project_id, user_id=creator_id)
        assert active_ctx is not None and "项目名称:" in active_ctx

        creator_member = (await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == creator_id)
        )).scalar_one()
        creator_member.status = "inactive"
        await session.commit()

        assert await svc.build_presentation_context(project_id, user_id=creator_id) is None
        assert await svc.build_presentation_context(project_id) is None


@pytest.mark.asyncio(loop_scope="session")
async def test_deactivated_or_observer_author_cannot_delete_comment(client_with_db):
    """作者被空间停用或被设为 Observer 后不能删除评论；活跃写作者可删除。"""
    client, session_maker = client_with_db
    from app.models.workspace import WorkspaceMember

    creator_id, creator_headers = await _register(client, "cmt_del_creator")
    member_id, member_headers = await _register(client, "cmt_del_member")
    project_id = await _create_project(client, creator_headers)
    req_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [member_id], "goal": "del comment test"},
        headers=creator_headers,
    )
    request_id = req_resp.json()["id"]

    # 1. 成员作为 Approver 发表评论
    cmt_resp = await client.post(
        "/api/notifications/comments",
        json={"object_type": "review_request", "object_id": request_id, "body": "Approver 评语"},
        headers=member_headers,
    )
    assert cmt_resp.status_code == 200
    comment_id = cmt_resp.json()["id"]

    # 2. 将该成员降为 Observer，删除应被拒绝（403）
    async with session_maker() as session:
        from app.models.review import ReviewParticipant
        p_row = (await session.execute(
            select(ReviewParticipant).where(
                ReviewParticipant.request_id == request_id,
                ReviewParticipant.user_id == member_id,
            )
        )).scalar_one()
        p_row.role = "Observer"
        await session.commit()

    del_obs = await client.delete(
        f"/api/notifications/comments/{comment_id}",
        headers=member_headers,
    )
    assert del_obs.status_code == 403

    # 3. 将该成员恢复为 Approver 但在 workspace 停用，删除应被拒绝（403/404）
    async with session_maker() as session:
        p_row = (await session.execute(
            select(ReviewParticipant).where(
                ReviewParticipant.request_id == request_id,
                ReviewParticipant.user_id == member_id,
            )
        )).scalar_one()
        p_row.role = "Approver"
        m_row = (await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == member_id)
        )).scalar_one()
        m_row.status = "inactive"
        await session.commit()

    del_inact = await client.delete(
        f"/api/notifications/comments/{comment_id}",
        headers=member_headers,
    )
    assert del_inact.status_code in (403, 404)

    # 4. 恢复活跃成员后，作者正常删除评论（200）
    async with session_maker() as session:
        m_row = (await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == member_id)
        )).scalar_one()
        m_row.status = "active"
        await session.commit()

    del_ok = await client.delete(
        f"/api/notifications/comments/{comment_id}",
        headers=member_headers,
    )
    assert del_ok.status_code == 200
    assert del_ok.json() == {"status": "ok"}


@pytest.mark.asyncio(loop_scope="session")
async def test_private_source_variant_readable_assertion(client_with_db):
    """_assert_team_source_readable 对 visibility=private 但 owner_type!=user 也必须拒绝非 owner。"""
    client, session_maker = client_with_db
    from app.models.workspace import KnowledgeSource
    from app.repositories.workspace_repository import WorkspaceRepository

    owner_id, owner_headers = await _register(client, "src_owner_user")
    other_id, other_headers = await _register(client, "src_other_user")

    async with session_maker() as session:
        ws = await WorkspaceRepository(session).get_default()
        ws_id = ws.id
        source = KnowledgeSource(
            workspace_id=ws_id,
            owner_type="team",  # 异常组合：team + private
            visibility="private",
            owner_id=owner_id,
            source_type="upload",
            title="private_variant",
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        source_id = source.id

    # 另一个成员访问团队资料详情应 404
    resp = await client.get(
        f"/api/workspace/{ws_id}/sources/{source_id}",
        headers=other_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_create_snapshot_validates_request_and_workspace(client_with_db):
    """create_snapshot 拒绝不属于当前项目的 request_id，并自动对齐 workspace_id。"""
    client, session_maker = client_with_db
    owner_id, headers = await _register(client, "snap_val_owner")
    p1_id = await _create_project(client, headers)
    p2_id = await _create_project(client, headers)

    approver_id, approver_headers = await _register(client, "snap_val_appr")
    r2_resp = await client.post(
        "/api/review/requests",
        json={"project_id": p2_id, "approver_ids": [approver_id], "goal": "p2 req"},
        headers=headers,
    )
    r2_id = r2_resp.json()["id"]

    # 在 p1 下创建快照但关联属于 p2 的 request_id → 400
    snap_fail = await client.post(
        "/api/review/snapshots",
        json={
            "workspace_id": 99999,
            "project_id": p1_id,
            "request_id": r2_id,
        },
        headers=headers,
    )
    assert snap_fail.status_code == 400
    assert "不属于该项目" in snap_fail.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_add_project_source_ref_rejects_private_source(client_with_db):
    """add_project_source_ref 拒绝添加私有资料引用，避免管线无法注入产生矛盾。"""
    client, session_maker = client_with_db
    from app.models.workspace import KnowledgeSource
    from app.repositories.workspace_repository import WorkspaceRepository

    owner_id, headers = await _register(client, "src_ref_owner")
    project_id = await _create_project(client, headers)

    async with session_maker() as session:
        ws = await WorkspaceRepository(session).get_default()
        source = KnowledgeSource(
            workspace_id=ws.id,
            owner_type="user",
            visibility="private",
            owner_id=owner_id,
            source_type="upload",
            title="my_private_doc",
            status="active",
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        source_id = source.id

    add_resp = await client.post(
        f"/api/review/project/{project_id}/sources",
        json={"source_id": source_id, "ref_type": "context"},
        headers=headers,
    )
    assert add_resp.status_code == 400
    assert "私有资料不能作为项目共享资料引用" in add_resp.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_confirm_artifact_excludes_inactive_workspace_participants(client_with_db):
    """confirm_artifact 物料确认通知只推给空间内活跃成员，排除已停用的参与者。"""
    client, session_maker = client_with_db
    from app.models.user import Notification
    from app.models.workspace import WorkspaceMember

    initiator_id, initiator_headers = await _register(client, "art_notif_init")
    approver1_id, approver1_headers = await _register(client, "art_notif_app1")
    approver2_id, approver2_headers = await _register(client, "art_notif_app2")
    project_id = await _create_project(client, initiator_headers)

    req_resp = await client.post(
        "/api/review/requests",
        json={"project_id": project_id, "approver_ids": [approver1_id, approver2_id], "goal": "art confirm notif"},
        headers=initiator_headers,
    )
    request_id = req_resp.json()["id"]

    # 创建产物
    art_resp = await client.post(
        "/api/review/artifacts",
        json={
            "object_type": "review_request",
            "object_id": request_id,
            "artifact_type": "html_presentation",
            "content_json": "{}",
        },
        headers=initiator_headers,
    )
    artifact_id = art_resp.json()["id"]

    # 停用 approver2 的 workspace 成员身份
    async with session_maker() as session:
        m2 = (await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == approver2_id)
        )).scalar_one()
        m2.status = "inactive"
        await session.commit()

    # 确认物料
    conf_resp = await client.post(
        f"/api/review/artifacts/{artifact_id}/confirm",
        headers=initiator_headers,
    )
    assert conf_resp.status_code == 200

    # 验证通知：approver1（活跃）收到通知，approver2（已停用）未收到通知
    async with session_maker() as session:
        n1 = (await session.execute(
            select(Notification).where(
                Notification.recipient_id == approver1_id,
                Notification.type == "artifact_confirmed",
            )
        )).scalars().all()
        assert len(n1) == 1

        n2 = (await session.execute(
            select(Notification).where(
                Notification.recipient_id == approver2_id,
                Notification.type == "artifact_confirmed",
            )
        )).scalars().all()
        assert len(n2) == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_embedding_worker_conditional_update_avoids_stale_overwrite(client_with_db):
    """update_embedding_status_conditional 校验 text 与 expected_status，防止覆盖新切块或破坏已完成状态。"""
    _, session_maker = client_with_db
    from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
    from app.models.workspace import KnowledgeSource
    from app.repositories.knowledge_repository import KnowledgeChunkRepository
    from app.repositories.workspace_repository import WorkspaceRepository

    async with session_maker() as session:
        ws = await WorkspaceRepository(session).get_default()
        source = KnowledgeSource(
            workspace_id=ws.id,
            owner_type="team",
            visibility="team",
            source_type="upload",
            title="cond_test",
            status="active",
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        doc = KnowledgeDocument(source_id=source.id, version=1)
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

        c1 = KnowledgeChunk(
            document_id=doc.id, chunk_no=1, text="original_text",
            embedding_status="done",  # 已经被新 worker 写入完成
        )
        c2 = KnowledgeChunk(
            document_id=doc.id, chunk_no=2, text="new_replaced_text",  # 正文已变化
            embedding_status="processing",
        )
        session.add_all([c1, c2])
        await session.commit()
        await session.refresh(c1)
        await session.refresh(c2)

        repo = KnowledgeChunkRepository(session)

        # 1. 旧 worker 试图将已 done 的 c1 改为 failed，由于 disallowed_statuses=("done",) 无法更新
        res_fail = await repo.update_embedding_status_conditional(
            [(c1.id, "original_text")],
            "failed",
            disallowed_statuses=("done",),
        )
        assert res_fail == 0
        await session.refresh(c1)
        assert c1.embedding_status == "done"

        # 2. 旧 worker 试图用旧正文将 c2 改为 done，由于 text 不匹配无法更新
        res_done = await repo.update_embedding_status_conditional(
            [(c2.id, "old_stale_text")],
            "done",
            expected_status="processing",
        )
        assert res_done == 0
        await session.refresh(c2)
        assert c2.embedding_status == "processing"


def test_update_sh_restore_env_uses_temp_file_and_service_recovered(tmp_path):
    """update.sh 恢复 .env 使用原子写入，且准备阶段失败时不让服务保持停机。"""
    import subprocess

    funcs = _write_update_functions(tmp_path)
    project = tmp_path / "project"
    project.mkdir(parents=True)
    runtime = project / "runtime"
    runtime.mkdir(parents=True)
    backup_dir = runtime / "update_backups" / "backup_v1"
    backup_dir.mkdir(parents=True)

    # 写入旧备份 .env
    (backup_dir / "project.env").write_text("BACKUP_VAR=1\n", encoding="utf-8")
    (project / ".env").write_text("CURRENT_VAR=0\n", encoding="utf-8")

    harness = f'''
set -eu
log() {{ echo "[UPDATE] $1"; }}
warn() {{ echo "[WARN] $1"; }}
fail() {{ echo "[FAIL] $1"; }}
source "{funcs}"
PROJECT_DIR="{project}"
RUNTIME_DIR="{runtime}"
CURRENT_BACKUP_DIR="{backup_dir}"

# 验证恢复 .env 成功
restore_env_file() {{
  if [ -f "$CURRENT_BACKUP_DIR/project.env" ]; then
    local env_tmp
    env_tmp="$(mktemp "$PROJECT_DIR/.restore-env.XXXXXX")"
    if ! cp "$CURRENT_BACKUP_DIR/project.env" "$env_tmp" || ! mv "$env_tmp" "$PROJECT_DIR/.env"; then
      rm -f "$env_tmp"
      return 1
    fi
  fi
  return 0
}}

restore_env_file
'''
    subprocess.run(["bash", "-c", harness], check=True, text=True, capture_output=True)
    assert (project / ".env").read_text(encoding="utf-8") == "BACKUP_VAR=1\n"


def test_review_js_show_result_running_task_checks_stale_state():
    """review.js 在运行中任务状态查询返回后校验 stateVersion 与 project/task 一致性。"""
    from pathlib import Path

    review_js = Path("src/static/js/review.js").read_text(encoding="utf-8")
    # 断言包含在途状态请求返回后的 stale 校验
    assert "data = await API.getReviewTaskStatus(reportProjectId, reportTaskId);" in review_js
    assert "this._isStaleState(reportStateVersion)" in review_js
    assert "this.currentProjectId !== reportProjectId" in review_js
    assert "this.currentTaskId !== reportTaskId" in review_js
    assert "const resultToken = ++this._resultSeq;" in review_js
    assert "resultToken !== this._resultSeq" in review_js
    assert "replace(/^---\\s*\\n[\\s\\S]*?\\n---\\s*\\n?/" in review_js
    assert "isCoveredChild" in review_js
    poll_block = review_js.split("async _pollProgress(taskId)", 1)[1].split("_updateProgress(data)", 1)[0]
    assert "listenSeq" in poll_block






def test_restore_env_partial_copy_does_not_truncate_formal_file(tmp_path):
    import subprocess

    funcs = _write_update_functions(tmp_path)
    project = tmp_path / "project"
    runtime = project / "runtime"
    backup = runtime / "backup"
    (project / "src").mkdir(parents=True)
    (project / "src" / "marker.txt").write_text("current", encoding="utf-8")
    (project / ".env").write_text("ORIGINAL=1\n", encoding="utf-8")
    (project / "start.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (project / "start.sh").chmod(0o755)
    backup.mkdir(parents=True)
    (backup / "project.env").write_text("FULL=1\n", encoding="utf-8")
    subprocess.run(["tar", "-czf", str(backup / "code.tar.gz"), "-C", str(project), "src"], check=True)

    harness = f'''
log() {{ echo "$1"; }}; warn() {{ :; }}; fail() {{ echo "FAIL $1"; }}
source "{funcs}"
PROJECT_DIR="{project}"; RUNTIME_DIR="{runtime}"; BACKUP_DIR="{runtime}/backups"
CURRENT_BACKUP_DIR="{backup}"; ROLLBACK_ON_FAILURE=true; SKIP_BACKUP=false
cp() {{
  case "$2" in
    */.restore-env.*) printf 'PARTIAL' > "$2"; return 0;;
    *) command cp "$@";;
  esac
}}
if restore_backup; then exit 10; fi
[ "$(cat "$PROJECT_DIR/.env")" = "ORIGINAL=1" ] || exit 11
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr


def test_backup_failure_restarts_existing_service(tmp_path):
    import subprocess

    funcs = _write_update_functions(tmp_path)
    project = tmp_path / "project"
    project.mkdir(parents=True)
    marker = project / "started.txt"
    (project / "start.sh").write_text(f"#!/bin/sh\necho started > '{marker}'\nexit 0\n", encoding="utf-8")
    (project / "start.sh").chmod(0o755)
    harness = f'''
log() {{ echo "$1"; }}; warn() {{ :; }}; fail() {{ echo "FAIL $1"; }}
source "{funcs}"
PROJECT_DIR="{project}"
SERVICE_STOPPED=true
UPDATE_STARTED=false
fail_before_backup() {{ false; }}
fail_before_backup
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, errors="replace")
    assert result.returncode != 0
    assert marker.exists(), result.stdout + result.stderr


@pytest.mark.asyncio(loop_scope="session")
async def test_embedding_status_conditional_checks_document_identity_and_source_active(client_with_db):
    _, session_maker = client_with_db
    from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
    from app.models.workspace import KnowledgeSource
    from app.repositories.knowledge_repository import KnowledgeChunkRepository
    from app.repositories.workspace_repository import WorkspaceRepository

    async with session_maker() as session:
        ws = await WorkspaceRepository(session).get_default()
        source = KnowledgeSource(
            workspace_id=ws.id, owner_type="workspace", visibility="team",
            source_type="upload", title="atomic", status="active",
        )
        session.add(source)
        await session.flush()
        doc = KnowledgeDocument(source_id=source.id, version=1)
        session.add(doc)
        await session.flush()
        chunk = KnowledgeChunk(
            document_id=doc.id, chunk_no=1, text="same text",
            embedding_status="processing",
        )
        session.add(chunk)
        await session.commit()
        repo = KnowledgeChunkRepository(session)

        # 错误 document_id：旧 worker 不能更新新切块
        assert await repo.update_embedding_status_conditional(
            [(chunk.id, chunk.text, doc.id + 999)], "done", expected_status="processing",
        ) == 0
        # 正确身份可更新
        assert await repo.update_embedding_status_conditional(
            [(chunk.id, chunk.text, doc.id)], "done", expected_status="processing",
        ) == 1
        await session.refresh(chunk)
        assert chunk.embedding_status == "done"

        # 归档来源后，即使身份一致也不能再标 done
        source.status = "archived"
        chunk.embedding_status = "processing"
        await session.commit()
        assert await repo.update_embedding_status_conditional(
            [(chunk.id, chunk.text, doc.id)], "done", expected_status="processing",
        ) == 0
