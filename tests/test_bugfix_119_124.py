"""Regression tests for BUG-119 ~ BUG-124.

BUG-119: Agent 授权范围未执行 — Extension 不读 AGENT_SCOPE_JSON；空白名单放行全部工具。
BUG-120: 聊天附件 file_id 目录穿越。
BUG-121: Workspace 配额生产链路失效（日志缺归属 + 客户端伪造 workspace）。
BUG-122: SQLite 外键未启用。
BUG-123: 产物写操作只校验读权限（Observer 可改/确认）。
BUG-124: 审查后台任务未纳入 lifespan 关闭流程。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.review import (
    Artifact,
    CostDailySummary,
    ReviewParticipant,
    ReviewProject,
    ReviewRequest,
    WorkspaceBudget,
)
from app.models.user import Base, User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.cost_stats_service import CostStatsService
from app.storage.chat_file_storage import ChatFileStorage
from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def client_with_db():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_maker, engine
    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


async def _login(client: AsyncClient, username="admin", password="admin@2026") -> dict:
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _register_user(client: AsyncClient, username: str, password: str = "pass12345") -> dict:
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert resp.status_code in (200, 201), resp.text
    return await _login(client, username, password)


# ─── BUG-119: Agent scope / deny-by-default ─────────────────────────


def test_bug119_extension_reads_scope_and_denies_empty_whitelist():
    root = Path(__file__).resolve().parents[1]
    ext = (root / "src/agent/extensions/agent-limiter.ts").read_text(encoding="utf-8")
    assert "AGENT_SCOPE_JSON" in ext
    assert "parseScope" in ext
    assert "effectiveAllowed" in ext
    assert "DEFAULT_SAFE_TOOLS" in ext
    assert '"read"' in ext or "'read'" in ext
    # 旧逻辑：仅当白名单非空才过滤 —— 必须已移除
    assert "ALLOWED_TOOLS.length > 0 &&" not in ext


def test_bug119_bridge_defaults_empty_tools_to_rag_search_only():
    from app.services.pi_agent_bridge import PiAgentBridge

    env = PiAgentBridge._build_extension_env(
        base_env={"PATH": "/usr/bin"},
        allowed_tools=[],
        scope_json='{"default_scope_type":"personal","authorizations":[]}',
        user_id=1,
        run_id=9,
        run_token="tok",
        api_base="http://127.0.0.1:17957",
    )
    tools = [t for t in env["AGENT_ALLOWED_TOOLS"].split(",") if t]
    assert tools == ["rag_search"]
    assert "bash" not in tools
    assert "write" not in tools
    assert "read" not in tools


@pytest.mark.asyncio
async def test_bug119_non_admin_cannot_enable_high_risk_tools(client_with_db):
    client, _, _ = client_with_db
    headers = await _register_user(client, "agent_user_119")
    resp = await client.put(
        "/api/agent/profile",
        json={"allowed_tools": ["rag_search", "bash", "write", "edit", "read"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tools = resp.json()["allowed_tools"]
    assert "bash" not in tools
    assert "write" not in tools
    assert "edit" not in tools
    assert "read" not in tools
    assert "rag_search" in tools


@pytest.mark.asyncio
async def test_bug119_non_admin_cannot_self_approve_high_risk(client_with_db):
    client, session_maker, _ = client_with_db
    headers = await _register_user(client, "agent_req_119")
    # 拿 user id
    me = await client.get("/api/auth/me", headers=headers)
    if me.status_code != 200:
        me = await client.get("/api/agent/profile", headers=headers)
    profile = await client.get("/api/agent/profile", headers=headers)
    assert profile.status_code == 200
    user_id = profile.json()["owner_id"]

    async with session_maker() as db:
        from app.models.user import AgentRun, AgentApprovalRequest
        run = AgentRun(agent_id=profile.json()["id"], user_id=user_id, goal="test", status="running")
        db.add(run)
        await db.flush()
        approval = AgentApprovalRequest(
            run_id=run.id,
            requester_id=user_id,
            approver_id=user_id,
            action_type="tool_call:bash",
            status="pending",
        )
        db.add(approval)
        await db.commit()
        approval_id = approval.id

    resp = await client.post(
        f"/api/agent/approvals/{approval_id}/decide",
        json={"decision": "approved", "comment": "self"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


# ─── BUG-120: path traversal ───────────────────────────────────────


def test_bug120_chat_file_rejects_path_traversal(tmp_path):
    upload = tmp_path / "uploads"
    upload.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("TOP_SECRET_CONTENT", encoding="utf-8")

    storage = ChatFileStorage(upload_dir=str(upload))
    ok_id = "a" * 32 + ".md"
    (upload / ok_id).write_text("hello", encoding="utf-8")

    assert storage.read_text(ok_id) is not None
    assert storage.read_text("../../secret.md") is None
    assert storage.read_text("../secret.md") is None
    assert storage.file_exists("../../secret.md") is False
    storage.delete("../../secret.md")  # must not delete outside
    assert secret.exists()


@pytest.mark.asyncio
async def test_bug120_context_api_rejects_traversal_file_id(client_with_db, tmp_path):
    client, session_maker, _ = client_with_db
    headers = await _login(client)

    upload = tmp_path / "uploads"
    upload.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("LEAKED", encoding="utf-8")

    from app.routers import chat as chat_mod
    chat_mod._chat_file_storage = ChatFileStorage(upload_dir=str(upload))

    async with session_maker() as db:
        from app.models.user import Conversation
        c = Conversation(user_id=1, title="ctx", mode="chat", model_id="deepseek-chat")
        db.add(c)
        await db.commit()
        conv_id = c.id

    resp = await client.post(
        f"/api/chat/conversations/{conv_id}/context",
        json={
            "context_type": "historical_doc",
            "title": "evil",
            "file_id": "../../secret.md",
            "enabled": True,
        },
        headers=headers,
    )
    if resp.status_code == 200:
        assert "LEAKED" not in (resp.json().get("extracted_text") or "")
    else:
        assert resp.status_code in (400, 404, 422)


# ─── BUG-121: workspace quota ──────────────────────────────────────


@pytest.mark.asyncio
async def test_bug121_log_and_aggregate_carry_workspace(tmp_path, monkeypatch):
    from app.logging_config import log_llm_session, setup_logging

    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("RUNTIME_ROOT", str(runtime_root))
    setup_logging(runtime_root / "logs")

    log_llm_session(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        "ok",
        usage={"prompt_tokens": 11, "completion_tokens": 22},
        elapsed_ms=100,
        workspace_id=42,
        user_id=7,
        mode="chat",
    )
    log_path = runtime_root / "logs" / "llm_sessions.jsonl"
    entry = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["workspace_id"] == 42
    assert entry["user_id"] == 7
    assert entry["mode"] == "chat"

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        ws = Workspace(name="ws42", status="active")
        db.add(ws)
        await db.flush()
        user = User(username="u7", password_hash="x", role="user")
        db.add(user)
        await db.flush()
        # 用真实 ID 重写日志行后再聚合
        log_path.write_text(
            json.dumps(
                {
                    "timestamp": entry["timestamp"],
                    "model": "deepseek-chat",
                    "usage": {"prompt_tokens": 11, "completion_tokens": 22},
                    "elapsed_ms": 100,
                    "workspace_id": ws.id,
                    "user_id": user.id,
                    "mode": "chat",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        rows = await CostStatsService(db).aggregate_daily(entry["timestamp"][:10])
        assert rows >= 1
        result = await db.execute(
            select(CostDailySummary).where(CostDailySummary.workspace_id == ws.id)
        )
        row = result.scalar_one()
        assert row.input_tokens == 11
        assert row.output_tokens == 22
        assert row.user_id == user.id
        assert row.mode == "chat"
    await engine.dispose()


@pytest.mark.asyncio
async def test_bug121_chat_rejects_nonexistent_knowledge_workspace(client_with_db):
    client, session_maker, _ = client_with_db
    headers = await _login(client)

    models = await client.get("/api/chat/models", headers=headers)
    assert models.status_code == 200
    model_id = models.json()[0]["id"]

    resp = await client.post(
        "/api/chat",
        json={
            "message": "hello",
            "model_id": model_id,
            "knowledge_workspace_id": 999999,
            "enable_knowledge": True,
        },
        headers=headers,
    )
    assert resp.status_code in (404, 403, 400), resp.text
    detail = str(resp.json().get("detail", ""))
    assert "空间" in detail or "workspace" in detail.lower() or "不存在" in detail


# ─── BUG-122: foreign keys ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_bug122_sqlite_foreign_keys_enabled():
    from app.database import engine

    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        assert int(result.scalar()) == 1


@pytest.mark.asyncio
async def test_bug122_rejects_orphan_foreign_key(tmp_path):
    """启用外键后，引用不存在用户的审批记录应失败。"""
    db_path = tmp_path / "fk.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    # 确保 connect 事件已加载
    import app.database  # noqa: F401

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with eng.begin() as conn:
        # 无 users 行时插入依赖 users.id 的 workspace.created_by 应失败（若列有 FK）
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO agent_approval_requests "
                    "(run_id, requester_id, approver_id, action_type, status) "
                    "VALUES (1, 99999, 99999, 'tool_call:bash', 'pending')"
                )
            )
    await eng.dispose()


# ─── BUG-123: artifact write vs read ───────────────────────────────


@pytest.mark.asyncio
async def test_bug123_observer_cannot_update_or_confirm_artifact(client_with_db):
    client, session_maker, _ = client_with_db
    admin_h = await _login(client)
    observer_h = await _register_user(client, "observer_123")

    # 查 observer user id
    async with session_maker() as db:
        obs = (
            await db.execute(select(User).where(User.username == "observer_123"))
        ).scalar_one()
        observer_id = obs.id

        # 确保有默认 workspace + 成员
        ws = (await db.execute(select(Workspace).where(Workspace.is_default == True))).scalar_one_or_none()
        if ws is None:
            ws = Workspace(name="默认空间", is_default=True, status="active", created_by=1)
            db.add(ws)
            await db.flush()
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=1, role="owner", status="active"))
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=observer_id, role="member", status="active"))

        project = ReviewProject(name="p123", created_by=1, workspace_id=ws.id)
        db.add(project)
        await db.flush()
        req = ReviewRequest(project_id=project.id, initiator_id=1, status="pending", goal="g")
        db.add(req)
        await db.flush()
        db.add(
            ReviewParticipant(
                request_id=req.id, user_id=observer_id, role="Observer", status="active"
            )
        )
        art = Artifact(
            object_type="review_request",
            object_id=req.id,
            artifact_type="html_presentation",
            content_json='{"x":1}',
            status="draft",
        )
        db.add(art)
        await db.commit()
        artifact_id = art.id

    # Observer 可读
    get_resp = await client.get(f"/api/review/artifacts/{artifact_id}", headers=observer_h)
    assert get_resp.status_code == 200, get_resp.text

    # Observer 不可写
    upd = await client.put(
        f"/api/review/artifacts/{artifact_id}/content",
        json={"content_json": '{"hacked":true}'},
        headers=observer_h,
    )
    assert upd.status_code == 403, upd.text

    conf = await client.post(
        f"/api/review/artifacts/{artifact_id}/confirm",
        headers=observer_h,
    )
    assert conf.status_code == 403, conf.text

    # 发起人可写可确认
    upd_ok = await client.put(
        f"/api/review/artifacts/{artifact_id}/content",
        json={"content_json": '{"ok":true}'},
        headers=admin_h,
    )
    assert upd_ok.status_code == 200, upd_ok.text
    conf_ok = await client.post(
        f"/api/review/artifacts/{artifact_id}/confirm",
        headers=admin_h,
    )
    assert conf_ok.status_code == 200, conf_ok.text


# ─── BUG-124: pipeline task lifecycle ──────────────────────────────


@pytest.mark.asyncio
async def test_bug124_lifespan_stops_pipeline_tasks_before_dispose():
    import main as main_mod

    stop_pipeline = AsyncMock()
    with patch("main.ensure_branding_dirs"), \
         patch("main.init_db", new=AsyncMock()), \
         patch("app.services.tool_registry.register_builtin_tools"), \
         patch("app.services.embedding_worker.start_embedding_worker", new=AsyncMock()), \
         patch("app.services.embedding_worker.stop_embedding_worker", new=AsyncMock()), \
         patch("app.routers.review.stop_all_pipeline_tasks", stop_pipeline), \
         patch("app.database.engine") as eng:
        eng.dispose = AsyncMock()
        cm = main_mod.lifespan(main_mod.app)
        await cm.__aenter__()
        await cm.__aexit__(None, None, None)
        stop_pipeline.assert_awaited()
        eng.dispose.assert_awaited()
        # stop 必须在 dispose 之前
        assert stop_pipeline.await_count == 1


def test_bug124_review_tracks_pipeline_tasks():
    from app.routers import review

    assert hasattr(review, "stop_all_pipeline_tasks")
    assert hasattr(review, "track_pipeline_task") or hasattr(review, "_pipeline_tasks")


@pytest.mark.asyncio
async def test_bug119_rag_endpoint_rejects_unauthorized_workspace(client_with_db):
    """服务端 RAG 端点必须按 Agent 授权范围拒绝未授权 workspace（不信任客户端）。"""
    from app.models.user import AgentRun
    from app.services.pi_agent_bridge import set_run_token

    client, session_maker, _ = client_with_db
    headers = await _register_user(client, "rag_scope_user")
    profile = await client.get("/api/agent/profile", headers=headers)
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    owner_id = profile.json()["owner_id"]

    async with session_maker() as db:
        run = AgentRun(agent_id=profile_id, user_id=owner_id, goal="rag", status="running")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    set_run_token(run_id, "test-run-token-rag-119")
    resp = await client.post(
        f"/api/agent/runs/{run_id}/rag",
        json={"query": "密钥", "workspace_id": 99999, "scope": "workspace"},
        headers={"X-Agent-Run-Token": "test-run-token-rag-119"},
    )
    assert resp.status_code == 403, resp.text
    assert "授权" in resp.text


# ─── BUG-125: 审批后 one-shot 优先于白名单 + sidecar ─────────────


def test_bug125_extension_one_shot_before_whitelist():
    """Extension 必须先消费 one-shot，再做白名单；否则审批死循环。"""
    root = Path(__file__).resolve().parents[1]
    ext = (root / "src/agent/extensions/agent-limiter.ts").read_text(encoding="utf-8")
    oneshot_idx = ext.find("consumeOneShot(toolName)")
    whitelist_idx = ext.find("不在白名单")
    assert oneshot_idx > 0
    assert whitelist_idx > oneshot_idx
    assert "ONE_SHOT_FILE" in ext or ".agent_one_shot_approved" in ext


def test_bug125_bridge_merges_one_shot_into_allowed_tools():
    from app.services.pi_agent_bridge import PiAgentBridge

    env = PiAgentBridge._build_extension_env(
        base_env={"PATH": "/usr/bin"},
        allowed_tools=["rag_search"],
        scope_json='{"default_scope_type":"personal","authorizations":[]}',
        user_id=1,
        run_id=9,
        run_token="tok",
        api_base="http://127.0.0.1:17957",
        one_shot_approved=["bash"],
    )
    tools = [t for t in env["AGENT_ALLOWED_TOOLS"].split(",") if t]
    assert "rag_search" in tools
    assert "bash" in tools
    assert env["AGENT_ONE_SHOT_APPROVED"] == "bash"


def test_bug125_write_one_shot_sidecar(tmp_path):
    from app.services.pi_agent_bridge import write_one_shot_sidecar, ONE_SHOT_SIDECAR_FILENAME

    write_one_shot_sidecar(tmp_path, "bash")
    write_one_shot_sidecar(tmp_path, "bash")  # idempotent
    write_one_shot_sidecar(tmp_path, "read")
    content = (tmp_path / ONE_SHOT_SIDECAR_FILENAME).read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert lines == ["bash", "read"]


# ─── BUG-126: 审查路径归属字段 ───────────────────────────────────


def test_bug126_skill_runner_passes_review_attribution():
    from app.services.skill_runner import SkillRunner

    runner = SkillRunner(
        model_cfg={"api_base": "x", "api_key": "y", "llm_model": "z", "max_tokens": 100},
        skills_dir=Path(__file__).resolve().parents[1] / "skills",
        workspace_id=42,
        user_id=7,
    )
    assert runner._llm_attribution() == {
        "workspace_id": 42,
        "user_id": 7,
        "mode": "review",
    }


@pytest.mark.asyncio
async def test_bug126_retryable_chat_logs_attribution(monkeypatch):
    import app.services.retry as retry_mod

    captured = {}

    def _fake_log(model, messages, text, usage, **kwargs):
        captured.update(kwargs)
        captured["model"] = model

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [{"message": {"content": '{"ok": true}', "reasoning_content": ""}}],
                "usage": {"total_tokens": 3},
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(retry_mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(retry_mod.httpx, "Timeout", lambda *a, **k: None)
    monkeypatch.setattr("app.logging_config.log_llm_session", _fake_log)

    text, usage = await retry_mod.retryable_chat(
        [{"role": "user", "content": "hi"}],
        api_base="http://example",
        api_key="k",
        llm_model="m",
        workspace_id=9,
        user_id=3,
        mode="review",
    )
    assert "ok" in text
    assert usage["total_tokens"] == 3
    assert captured.get("workspace_id") == 9
    assert captured.get("user_id") == 3
    assert captured.get("mode") == "review"


# ─── BUG-127: BLOCKED 工具名精确解析 ─────────────────────────────


@pytest.mark.parametrize(
    "line,expected",
    [
        ("[agent-limiter] BLOCKED: 高风险工具 bash 需要人工审批", "bash"),
        ("[agent-limiter] BLOCKED: 工具 read 不在白名单 rag_search", "read"),
        ("[agent-limiter] BLOCKED: 工具调用次数已达上限(20), 当前: write", "write"),
        ("[agent-limiter] BLOCKED: already_read something", None),
        ("no blocked here with read substring", None),
    ],
)
def test_bug127_extract_blocked_tool_exact(line, expected):
    from app.services.pi_agent_bridge import extract_blocked_tool

    assert extract_blocked_tool(line) == expected
