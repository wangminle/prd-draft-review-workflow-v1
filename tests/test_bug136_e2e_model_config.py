"""BUG-136 回归测试：审查启动端到端 -- 不 mock `_get_model_config`。

问题回顾：
    V0.3.8 的 ruff 代码清理将 review.py 中的
        ModelConfig.deleted_by_user == False
    误改为
        not ModelConfig.deleted_by_user
    后者在 SQLAlchemy 中等价于 WHERE 0，导致查询永远返回空，
    所有审查请求报 "无可用的LLM模型配置"。

为什么之前的测试没发现：
    1. test_review_report_contract.py 中唯一的审查启动测试
       monkeypatch 了 _get_model_config，SQL 查询从未真正执行。
    2. test_crypto_and_models.py 走的是 admin -> Repository 路径，
       Repository 一直使用正确的 == False。
    3. 前端契约测试只匹配 JS 字符串，不涉及后端。

本测试的关键设计：
    - **不 mock `_get_model_config`**，让它执行真实的 SQLAlchemy 查询。
    - 在测试 DB 中插入带加密 API Key 的 ModelConfig。
    - 调用 `POST /api/review/projects/{id}/reviews` 端点。
    - 只 mock `_run_pipeline`（避免真实 LLM 调用），但在 mock 之前
      `_get_model_config` 已经执行完毕。
    - 如果查询写法有误（如 `not ModelConfig.deleted_by_user`），
      API 会返回 400 "无可用的LLM模型配置"，测试立即失败。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.conftest import init_test_db, make_test_app

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-tests-32chars!!")


@pytest_asyncio.fixture
async def e2e_client():
    """创建带真实数据库的测试客户端，不 mock 任何业务函数。"""
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_maker

    # 清理后台管线任务
    from app.routers import review
    for tid, task in list(review._pipeline_tasks.items()):
        task.cancel()
    review._pipeline_tasks.clear()

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


async def _register(client: AsyncClient, username: str) -> tuple[dict, int]:
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "test123456"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


async def _create_project(client: AsyncClient, headers: dict, name: str) -> int:
    resp = await client.post(
        "/api/review/projects",
        json={"name": name, "description": ""},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_document(session_maker, project_id: int) -> int:
    """在测试 DB 中插入一条审查文档（已转换状态）。"""
    from app.models.review import ReviewDocument

    async with session_maker() as session:
        doc = ReviewDocument(
            project_id=project_id,
            filename="测试需求文档.docx",
            status="converted",
            document_type="requirement",
            md_path="runtime/test/markdown/测试需求文档.md",
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        return doc.id


async def _seed_model_config(session_maker, *, model_id="test-e2e-model"):
    """插入一条 enabled=True、带有效加密 API Key 的 ModelConfig。"""
    from app.models.user import ModelConfig
    from app.services.crypto import encrypt_key

    jwt_secret = os.environ.get("JWT_SECRET", "test-jwt-secret-for-tests-32chars!!")
    encrypted_key = encrypt_key("sk-test-e2e-key", jwt_secret)

    async with session_maker() as session:
        # 先检查是否已存在（conftest init_test_db 可能已从 config.yaml seed）
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.model_id == model_id)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            # 确保它 enabled 且有 API key
            existing.enabled = True
            existing.deleted_by_user = False
            existing.encrypted_api_key = encrypted_key
            existing.api_base = "http://llm.test/v1"
            existing.llm_model = "test-model"
            existing.max_tokens = 4096
            await session.commit()
            return

        mc = ModelConfig(
            model_id=model_id,
            name="E2E测试模型",
            provider="openai_compatible",
            api_base="http://llm.test/v1",
            encrypted_api_key=encrypted_key,
            llm_model="test-model",
            max_tokens=4096,
            temperature=0.3,
            enabled=True,
            deleted_by_user=False,
            last_test_status="unknown",
        )
        session.add(mc)
        await session.commit()


async def _disable_all_other_models(session_maker, keep_model_id="test-e2e-model"):
    """禁用所有其他模型，确保测试隔离。"""
    from app.models.user import ModelConfig

    async with session_maker() as session:
        result = await session.execute(select(ModelConfig))
        for mc in result.scalars().all():
            if mc.model_id != keep_model_id:
                mc.enabled = False
                mc.deleted_by_user = True
        await session.commit()


class TestStartReviewE2EModelConfig:
    """端到端验证审查启动时 _get_model_config 的真实 SQL 查询。"""

    @pytest.mark.asyncio
    async def test_start_review_succeeds_with_valid_model_config(
        self, e2e_client, monkeypatch
    ):
        """有启用的 ModelConfig 时，审查启动应返回 task_id，不报 400。

        关键：不 mock _get_model_config，让它执行真实的 SQLAlchemy 查询。
        只 mock _run_pipeline 防止真实 LLM 调用。
        """
        client, session_maker = e2e_client
        headers, user_id = await _register(client, "e2e_model_user")
        project_id = await _create_project(client, headers, "E2E模型测试项目")
        await _seed_document(session_maker, project_id)
        await _seed_model_config(session_maker)
        await _disable_all_other_models(session_maker)

        # 只 mock _run_pipeline（避免真实 LLM 调用），不 mock _get_model_config
        from app.routers import review

        async def _noop_pipeline(*args, **kwargs):
            return None

        monkeypatch.setattr(review, "_run_pipeline", _noop_pipeline)

        resp = await client.post(
            f"/api/review/projects/{project_id}/reviews",
            json={"mode": "quick"},
            headers=headers,
        )

        # 如果 _get_model_config 的 SQL 查询有误（BUG-136），
        # 这里会返回 400 "无可用的LLM模型配置"
        assert resp.status_code == 200, (
            f"审查启动失败，status={resp.status_code}, body={resp.text}。"
            f"如果错误信息是 '无可用的LLM模型配置'，说明 _get_model_config "
            f"的 SQLAlchemy 查询有问题（如 not ModelConfig.deleted_by_user）。"
        )
        data = resp.json()
        assert "task_id" in data
        assert data["status"] in ("pending", "running")
        assert data["mode"] == "quick"

    @pytest.mark.asyncio
    async def test_start_review_fails_when_no_enabled_model(self, e2e_client, monkeypatch):
        """所有模型禁用时，审查启动应返回 400。"""
        client, session_maker = e2e_client
        headers, user_id = await _register(client, "e2e_no_model_user")
        project_id = await _create_project(client, headers, "无模型测试项目")
        await _seed_document(session_maker, project_id)

        # 禁用所有模型
        from app.models.user import ModelConfig

        async with session_maker() as session:
            result = await session.execute(select(ModelConfig))
            for mc in result.scalars().all():
                mc.enabled = False
                mc.deleted_by_user = True
            await session.commit()

        from app.routers import review

        async def _noop_pipeline(*args, **kwargs):
            return None

        monkeypatch.setattr(review, "_run_pipeline", _noop_pipeline)

        resp = await client.post(
            f"/api/review/projects/{project_id}/reviews",
            json={"mode": "quick"},
            headers=headers,
        )

        assert resp.status_code == 400, (
            f"期望 400（无可用模型），实际 {resp.status_code}: {resp.text}"
        )
        assert "模型" in resp.text or "model" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_start_review_with_explicit_model_id(self, e2e_client, monkeypatch):
        """指定 model_id 时，_get_model_config 按 model_id 查询也需正常工作。"""
        client, session_maker = e2e_client
        headers, user_id = await _register(client, "e2e_explicit_model_user")
        project_id = await _create_project(client, headers, "指定模型测试项目")
        await _seed_document(session_maker, project_id)
        await _seed_model_config(session_maker, model_id="test-explicit-model")
        await _disable_all_other_models(
            session_maker, keep_model_id="test-explicit-model"
        )

        from app.routers import review

        async def _noop_pipeline(*args, **kwargs):
            return None

        monkeypatch.setattr(review, "_run_pipeline", _noop_pipeline)

        resp = await client.post(
            f"/api/review/projects/{project_id}/reviews",
            json={"mode": "quick", "model_id": "test-explicit-model"},
            headers=headers,
        )

        assert resp.status_code == 200, (
            f"指定 model_id 审查启动失败: {resp.status_code} {resp.text}"
        )
        data = resp.json()
        assert "task_id" in data

    @pytest.mark.asyncio
    async def test_start_review_ignores_deleted_models(self, e2e_client, monkeypatch):
        """deleted_by_user=True 的模型不应被查到，即使 enabled=True。

        这是 BUG-136 的核心场景：如果用 `not ModelConfig.deleted_by_user`，
        Python not 作用于 Column 返回 False，.where(False) 等价于 WHERE 0，
        即使有 enabled && !deleted 的模型也查不到。
        """
        client, session_maker = e2e_client
        headers, user_id = await _register(client, "e2e_deleted_model_user")
        project_id = await _create_project(client, headers, "已删除模型测试项目")
        await _seed_document(session_maker, project_id)

        from app.models.user import ModelConfig
        from app.services.crypto import encrypt_key

        jwt_secret = os.environ.get("JWT_SECRET", "test-jwt-secret-for-tests-32chars!!")

        async with session_maker() as session:
            # 删除所有现有模型
            result = await session.execute(select(ModelConfig))
            for mc in result.scalars().all():
                mc.enabled = False
                mc.deleted_by_user = True

            # 插入一个 enabled=True 且 deleted_by_user=True 的模型（不应被查到）
            session.add(ModelConfig(
                model_id="deleted-but-enabled",
                name="已删除但enabled",
                provider="openai_compatible",
                api_base="http://llm.test/v1",
                encrypted_api_key=encrypt_key("sk-test", jwt_secret),
                llm_model="test",
                max_tokens=4096,
                enabled=True,
                deleted_by_user=True,
            ))

            # 插入一个 enabled=True 且 deleted_by_user=False 的模型（应被查到）
            session.add(ModelConfig(
                model_id="active-model",
                name="正常模型",
                provider="openai_compatible",
                api_base="http://llm.test/v1",
                encrypted_api_key=encrypt_key("sk-active", jwt_secret),
                llm_model="test",
                max_tokens=4096,
                enabled=True,
                deleted_by_user=False,
            ))
            await session.commit()

        from app.routers import review

        async def _noop_pipeline(*args, **kwargs):
            return None

        monkeypatch.setattr(review, "_run_pipeline", _noop_pipeline)

        resp = await client.post(
            f"/api/review/projects/{project_id}/reviews",
            json={"mode": "quick"},
            headers=headers,
        )

        # 应该成功，因为有一个 enabled && !deleted 的模型
        assert resp.status_code == 200, (
            f"期望审查成功（存在 enabled && !deleted 的模型），"
            f"实际 {resp.status_code}: {resp.text}。"
            f"如果返回 '无可用的LLM模型配置'，说明查询中 "
            f"`not ModelConfig.deleted_by_user` 误判（BUG-136 回归）。"
        )
        data = resp.json()
        assert "task_id" in data

    @pytest.mark.asyncio
    async def test_start_review_fails_when_only_deleted_models_exist(
        self, e2e_client, monkeypatch
    ):
        """只有 deleted_by_user=True 的模型时（即使 enabled=True），应返回 400。"""
        client, session_maker = e2e_client
        headers, user_id = await _register(client, "e2e_only_deleted_user")
        project_id = await _create_project(client, headers, "仅已删除模型测试项目")
        await _seed_document(session_maker, project_id)

        from app.models.user import ModelConfig
        from app.services.crypto import encrypt_key

        jwt_secret = os.environ.get("JWT_SECRET", "test-jwt-secret-for-tests-32chars!!")

        async with session_maker() as session:
            # 禁用/删除所有现有模型
            result = await session.execute(select(ModelConfig))
            for mc in result.scalars().all():
                mc.enabled = False
                mc.deleted_by_user = True

            # 只插入 deleted_by_user=True 但 enabled=True 的模型
            session.add(ModelConfig(
                model_id="deleted-only-model",
                name="只有已删除模型",
                provider="openai_compatible",
                api_base="http://llm.test/v1",
                encrypted_api_key=encrypt_key("sk-test", jwt_secret),
                llm_model="test",
                max_tokens=4096,
                enabled=True,
                deleted_by_user=True,
            ))
            await session.commit()

        from app.routers import review

        async def _noop_pipeline(*args, **kwargs):
            return None

        monkeypatch.setattr(review, "_run_pipeline", _noop_pipeline)

        resp = await client.post(
            f"/api/review/projects/{project_id}/reviews",
            json={"mode": "quick"},
            headers=headers,
        )

        assert resp.status_code == 400, (
            f"期望 400（只有已删除模型），实际 {resp.status_code}: {resp.text}"
        )
