"""BUG-156 / BUG-157 / BUG-158 回归测试

BUG-156 (P0): Skill 禁用门控接入生产路径
    - start_review 创建任务前检查 Skill 状态：必需 Skill 禁用 → 409 拒绝；
      可选 Skill 禁用 → 正常创建 + step_details 记录降级计划。
    - _STEP_TO_SKILL_ID 覆盖全部步骤（含分类/逐篇分析）；执行期预检拒绝。
    - 被跳过的可选步骤把 degraded 信息（Skill/步骤/原因）持久化到 step_details。

BUG-157 (P1): 七维评审部分失败的状态传播
    - review_dimensions_meta.status == "partial" → 任务最终状态
      completed_with_warnings，且 meta 持久化到 step_details。

BUG-158 (P1): 线上分类回填白名单
    - 非白名单类别回填前改写为「待确认」并在 step_details 记录原始值；
    - 白名单配置缺失时降级为放行 + 记 warning，不硬失败。
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.conftest import init_test_db, make_test_app, drain_review_pipeline_tasks

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-tests-32chars!!")


# ── 公共 fixture 与 helper ────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/auth/login", json={
            "username": "admin", "password": "admin@2026",
        })
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac, session_maker

    await drain_review_pipeline_tasks(timeout=2.0)
    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


async def _create_project(client: AsyncClient, name: str) -> int:
    resp = await client.post("/api/review/projects", json={"name": name, "description": ""})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_document(session_maker, project_id: int) -> int:
    """插入一条带 md_path 的审查文档（管线 step 0 会复用已有 Markdown）。"""
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


async def _seed_model_config(session_maker, model_id: str = "test-bug156-model"):
    """插入 enabled 且带有效加密 API Key 的 ModelConfig（与 test_bug136 同法）。"""
    from app.models.user import ModelConfig
    from app.services.crypto import encrypt_key

    jwt_secret = os.environ.get("JWT_SECRET", "test-jwt-secret-for-tests-32chars!!")
    encrypted_key = encrypt_key("sk-test-bug156-key", jwt_secret)

    async with session_maker() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.model_id == model_id)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.enabled = True
            existing.deleted_by_user = False
            existing.encrypted_api_key = encrypted_key
            existing.api_base = "http://llm.test/v1"
            existing.llm_model = "test-model"
            existing.max_tokens = 4096
        else:
            session.add(ModelConfig(
                model_id=model_id,
                name="BUG156测试模型",
                provider="openai_compatible",
                api_base="http://llm.test/v1",
                encrypted_api_key=encrypted_key,
                llm_model="test-model",
                max_tokens=4096,
                temperature=0.3,
                enabled=True,
                deleted_by_user=False,
                last_test_status="unknown",
            ))
        # 禁用其他模型，确保测试隔离
        result = await session.execute(select(ModelConfig))
        for mc in result.scalars().all():
            if mc.model_id != model_id:
                mc.enabled = False
                mc.deleted_by_user = True
        await session.commit()


async def _set_skill_status(session_maker, skill_id: str, status: str):
    from app.models.user import SkillConfig

    async with session_maker() as session:
        result = await session.execute(
            select(SkillConfig).where(SkillConfig.skill_id == skill_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            session.add(SkillConfig(
                skill_id=skill_id, name=skill_id, description="测试技能", status=status,
            ))
        else:
            row.status = status
        await session.commit()


async def _get_task(session_maker, task_id: int):
    from app.models.review import ReviewTask

    async with session_maker() as session:
        result = await session.execute(select(ReviewTask).where(ReviewTask.id == task_id))
        return result.scalar_one()


def _step_details(task) -> dict:
    return json.loads(task.step_details) if task.step_details else {}


def _write_categories_config(skills_dir, categories: list[dict]) -> None:
    """在指定 skills 目录下写入 prd-overview-classify 的 default-categories.json。"""
    cfg_dir = Path(skills_dir) / "prd-overview-classify" / "templates"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "default-categories.json").write_text(
        json.dumps({"categories": categories}, ensure_ascii=False), encoding="utf-8"
    )


_MODE_STEPS = {
    "quick": ["预处理", "分类", "逐篇分析"],
    "review": ["预处理", "分类", "逐篇分析", "体系Review", "报告生成"],
    "insight": ["预处理", "分类", "逐篇分析", "体系Review", "需求洞察", "报告生成"],
}


def _install_fake_runner(monkeypatch, *, doc_id: int, classify_category: str = "未分类",
                         sr_meta_status: str = "success"):
    """用假 SkillRunner 替换 review.SkillRunner，避免真实 LLM 调用。

    - classify 返回指定 category 的单条分类结果
    - version-chain 返回空链
    - per_analysis 写入一条成功分析
    - system_review 按 sr_meta_status 生成全成功或 partial 的七维结果
    - report 返回 markdown
    """
    from app.routers import review
    from app.services.skill_runner import PipelineState, SkillStepResult

    class _FakeRunner:
        def __init__(self, **kwargs):
            self.state = PipelineState()
            self.pipeline_state = self.state
            self.context = kwargs.get("context") or {}

        def build_step_inputs(self, skill_name, state):
            return {}

        def _build_report_inputs(self, state):
            return {}

        async def run_skill(self, skill_name, inputs):
            assert skill_name == "classify"
            return SkillStepResult(status="success", data={
                "classifications": [{"doc_id": str(doc_id), "category": classify_category}],
            })

        async def run_skill_with_retry(self, skill_name, inputs):
            if skill_name == "classify_version_chain":
                return SkillStepResult(status="success", data={"chains": [], "dependencies": []})
            return SkillStepResult(status="success", data={"markdown": "# 测试报告"})

        async def _run_per_analysis(self, only_doc_ids=None, should_cancel=None):
            self.state["analyses"] = {str(doc_id): {
                "core_problem": "测试核心问题",
                "category": "未分类",
                "boundary_in": [],
                "boundary_out": [],
                "quality_score": 4,
            }}
            return False

        async def _run_system_review(self, should_cancel=None):
            dims = ["business-value", "architecture", "competition", "product-strategy",
                    "tech-evolution", "pm-assessment", "action-plan"]
            results = {d: {"summary": "ok"} for d in dims}
            failed = []
            if sr_meta_status == "partial":
                results["architecture"] = {"error": "模拟维度失败"}
                failed = ["architecture"]
            executed = [d for d in dims if d not in failed]
            self.state["review_dimensions"] = results
            self.state["review_dimensions_meta"] = {
                "dimensions_executed": executed,
                "dimensions_failed": failed,
                "total": 7,
                "success_count": len(executed),
                "failed_count": len(failed),
                "status": sr_meta_status,
            }
            return False

        async def _run_insights(self):
            self.state["insights"] = {"evolution": {}, "features": {}, "gap": {}}

    monkeypatch.setattr(review, "SkillRunner", _FakeRunner)

    async def _fake_read_markdown(path):
        return "# 测试文档内容"

    monkeypatch.setattr(review._review_file_storage, "read_markdown", _fake_read_markdown)
    return review


# ── BUG-156: Skill 禁用门控接入生产路径 ──────────────────────

@pytest.mark.asyncio
async def test_bug156_required_skill_inactive_rejects_start_review(client):
    """必需 Skill（逐篇分析）被禁用时，start_review 必须 4xx 拒绝并说明哪个 Skill。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug156-required-block")
    await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)
    await _set_skill_status(session_maker, "prd-per-analysis", "inactive")

    from app.routers import review

    async def _noop_pipeline(*args, **kwargs):
        return None

    from unittest.mock import patch
    with patch.object(review, "_run_pipeline", _noop_pipeline):
        resp = await ac.post(
            f"/api/review/projects/{project_id}/reviews",
            json={"mode": "quick"},
        )

    assert resp.status_code == 409, resp.text
    assert "prd-per-analysis" in resp.json()["detail"]

    # 不应创建任何任务
    from app.models.review import ReviewTask
    async with session_maker() as session:
        result = await session.execute(
            select(ReviewTask).where(ReviewTask.project_id == project_id)
        )
        assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_bug156_classify_skill_inactive_rejects_start_review(client):
    """必需 Skill（分类）被禁用时同样拒绝 — 覆盖 step 1 映射补全。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug156-classify-block")
    await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)
    await _set_skill_status(session_maker, "prd-overview-classify", "inactive")

    resp = await ac.post(
        f"/api/review/projects/{project_id}/reviews",
        json={"mode": "review"},
    )
    assert resp.status_code == 409, resp.text
    assert "prd-overview-classify" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_bug156_optional_skill_inactive_creates_task_with_degradation_plan(client):
    """可选 Skill（需求洞察）被禁用时任务正常创建，step_details 记录降级计划。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug156-optional-degraded")
    await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)
    await _set_skill_status(session_maker, "requirement-insights", "inactive")

    from app.routers import review

    async def _noop_pipeline(*args, **kwargs):
        return None

    from unittest.mock import patch
    with patch.object(review, "_run_pipeline", _noop_pipeline):
        resp = await ac.post(
            f"/api/review/projects/{project_id}/reviews",
            json={"mode": "insight"},
        )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]

    task = await _get_task(session_maker, task_id)
    details = _step_details(task)
    planned = details.get("planned_degraded_steps")
    assert planned, f"step_details 应包含降级计划: {details}"
    assert planned[0]["skill_id"] == "requirement-insights"
    assert planned[0]["step_name"] == "需求洞察"
    assert "inactive" in planned[0]["reason"]


@pytest.mark.asyncio
async def test_bug156_required_skill_inactive_rejected_at_execution(client, monkeypatch):
    """分类/逐篇分析在任务创建后被禁用 → 执行期预检拒绝（任务 failed）。

    覆盖 start_review 4xx 拦截之外的兜底路径（存量任务 / 创建后才禁用）。
    """
    ac, session_maker = client
    project_id = await _create_project(ac, "bug156-exec-block")
    doc_id = await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)

    # 先正常创建任务（此时无禁用 Skill）
    task_id = await _create_task_only(ac, monkeypatch, project_id, "review")

    # 创建后把分类与逐篇分析都禁用
    await _set_skill_status(session_maker, "prd-overview-classify", "inactive")
    await _set_skill_status(session_maker, "prd-per-analysis", "inactive")

    review = _install_fake_runner(monkeypatch, doc_id=doc_id)
    monkeypatch.setattr(review, "async_session", session_maker)

    await review._run_pipeline(
        task_id, project_id, "review", [doc_id],
        {"api_base": "http://llm.test/v1", "api_key": "k", "llm_model": "m"},
        _MODE_STEPS["review"], [], False,
    )

    task = await _get_task(session_maker, task_id)
    assert task.status == "failed"
    err = _step_details(task).get("error", "")
    assert "prd-overview-classify" in err
    assert "prd-per-analysis" in err


async def _create_task_only(ac, monkeypatch, project_id: int, mode: str) -> int:
    """创建任务但不让管线自动运行，返回 task_id。"""
    from app.routers import review

    async def _noop_pipeline(*args, **kwargs):
        return None

    monkeypatch.setattr(review, "_run_pipeline", _noop_pipeline)
    resp = await ac.post(
        f"/api/review/projects/{project_id}/reviews",
        json={"mode": mode},
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]
    # 还原真实 _run_pipeline，供测试手动驱动
    monkeypatch.undo()
    return task_id


@pytest.mark.asyncio
async def test_bug156_optional_skill_inactive_step_skipped_and_degraded_persisted(client, monkeypatch):
    """可选 Skill 禁用 → 执行期步骤 skipped + 结构化 degraded 持久化 + 降级终态。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug156-skip-persist")
    doc_id = await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)

    task_id = await _create_task_only(ac, monkeypatch, project_id, "insight")

    # 任务创建后再禁用可选 Skill（走执行期逐步门控）
    await _set_skill_status(session_maker, "requirement-insights", "inactive")

    review = _install_fake_runner(monkeypatch, doc_id=doc_id, sr_meta_status="success")
    monkeypatch.setattr(review, "async_session", session_maker)

    await review._run_pipeline(
        task_id, project_id, "insight", [doc_id],
        {"api_base": "http://llm.test/v1", "api_key": "k", "llm_model": "m"},
        _MODE_STEPS["insight"], [], False,
    )

    task = await _get_task(session_maker, task_id)
    step_statuses = json.loads(task.step_statuses)
    # insight 模式步骤: 0 预处理 / 1 分类 / 2 逐篇分析 / 3 体系Review / 4 需求洞察 / 5 报告生成
    assert step_statuses["4"] == "skipped", step_statuses
    assert step_statuses["5"] == "completed", step_statuses

    # 降级导致终态为 completed_with_warnings
    assert task.status == "completed_with_warnings"

    # degraded 信息结构化持久化：哪个 Skill、哪个步骤、原因
    details = _step_details(task)
    degraded = details.get("degraded_steps")
    assert degraded, f"step_details 应包含 degraded_steps: {details}"
    entry = degraded[0]
    assert entry["skill_id"] == "requirement-insights"
    assert entry["step_name"] == "需求洞察"
    assert entry["step_index"] == 4
    assert "inactive" in entry["reason"]


# ── BUG-157: 七维评审部分失败的状态传播 ──────────────────────

@pytest.mark.asyncio
async def test_bug157_partial_dimensions_mark_completed_with_warnings(client, monkeypatch):
    """sr_meta.status == partial → 任务终态 completed_with_warnings。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug157-partial")
    doc_id = await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)

    task_id = await _create_task_only(ac, monkeypatch, project_id, "review")

    review = _install_fake_runner(monkeypatch, doc_id=doc_id, sr_meta_status="partial")
    monkeypatch.setattr(review, "async_session", session_maker)

    await review._run_pipeline(
        task_id, project_id, "review", [doc_id],
        {"api_base": "http://llm.test/v1", "api_key": "k", "llm_model": "m"},
        _MODE_STEPS["review"], [], False,
    )

    task = await _get_task(session_maker, task_id)
    assert task.status == "completed_with_warnings", (
        f"部分维度失败应置 completed_with_warnings，实际 {task.status}"
    )


@pytest.mark.asyncio
async def test_bug157_review_dimensions_meta_persisted(client, monkeypatch):
    """review_dimensions_meta（executed/failed/counts）持久化到 step_details。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug157-meta")
    doc_id = await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)

    task_id = await _create_task_only(ac, monkeypatch, project_id, "review")

    review = _install_fake_runner(monkeypatch, doc_id=doc_id, sr_meta_status="partial")
    monkeypatch.setattr(review, "async_session", session_maker)

    await review._run_pipeline(
        task_id, project_id, "review", [doc_id],
        {"api_base": "http://llm.test/v1", "api_key": "k", "llm_model": "m"},
        _MODE_STEPS["review"], [], False,
    )

    task = await _get_task(session_maker, task_id)
    details = _step_details(task)
    meta = details.get("review_dimensions_meta")
    assert meta, f"step_details 应包含 review_dimensions_meta: {details}"
    assert meta["status"] == "partial"
    assert meta["dimensions_failed"] == ["architecture"]
    assert meta["failed_count"] == 1
    assert meta["success_count"] == 6
    assert meta["total"] == 7
    assert "business-value" in meta["dimensions_executed"]


# ── BUG-158: 分类回填白名单 ──────────────────────────────────

@pytest.mark.asyncio
async def test_bug158_non_whitelist_category_marked_pending(client, monkeypatch, tmp_path):
    """模型返回非白名单类别 → 回填为「待确认」，原始值记录到 step_details。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug158-whitelist")
    doc_id = await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)

    task_id = await _create_task_only(ac, monkeypatch, project_id, "quick")

    review = _install_fake_runner(monkeypatch, doc_id=doc_id, classify_category="编造的类别")
    monkeypatch.setattr(review, "async_session", session_maker)
    # 提供带真实类别的白名单配置（仓库模板默认 categories 为空，不能作为
    # 「已配置」场景），确保校验在有效配置下进行。
    _write_categories_config(tmp_path, [{"name": "数据管理"}, {"name": "权限控制"}])
    monkeypatch.setattr(review, "SKILLS_DIR", str(tmp_path))

    await review._run_pipeline(
        task_id, project_id, "quick", [doc_id],
        {"api_base": "http://llm.test/v1", "api_key": "k", "llm_model": "m"},
        _MODE_STEPS["quick"], [], False,
    )

    # 文档类别被改写为待确认
    from app.models.review import ReviewDocument
    async with session_maker() as session:
        result = await session.execute(select(ReviewDocument).where(ReviewDocument.id == doc_id))
        doc = result.scalar_one()
    assert doc.category == "待确认", f"非白名单类别应回填为待确认，实际 {doc.category}"

    # 原始返回值持久化到 step_details
    task = await _get_task(session_maker, task_id)
    details = _step_details(task)
    corrections = details.get("category_whitelist_corrections")
    assert corrections, f"step_details 应记录白名单改写: {details}"
    assert corrections[0]["original_category"] == "编造的类别"
    assert corrections[0]["corrected_category"] == "待确认"


@pytest.mark.asyncio
async def test_bug158_empty_categories_config_passes_through(client, monkeypatch, tmp_path):
    """default-categories.json 存在但 categories 为空（模板默认态）→ 等同配置缺失，
    降级放行并记 warning；不得把所有真实类别误判为「待确认」。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug158-empty-cats")
    doc_id = await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)

    task_id = await _create_task_only(ac, monkeypatch, project_id, "quick")

    review = _install_fake_runner(monkeypatch, doc_id=doc_id, classify_category="数据管理")
    monkeypatch.setattr(review, "async_session", session_maker)
    # 空类别配置：文件存在、解析成功，但 categories 列表为空
    _write_categories_config(tmp_path, [])
    monkeypatch.setattr(review, "SKILLS_DIR", str(tmp_path))

    await review._run_pipeline(
        task_id, project_id, "quick", [doc_id],
        {"api_base": "http://llm.test/v1", "api_key": "k", "llm_model": "m"},
        _MODE_STEPS["quick"], [], False,
    )

    from app.models.review import ReviewDocument
    async with session_maker() as session:
        result = await session.execute(select(ReviewDocument).where(ReviewDocument.id == doc_id))
        doc = result.scalar_one()
    assert doc.category == "数据管理", (
        f"空类别配置应等同配置缺失放行原值，不得改为待确认，实际 {doc.category}"
    )

    task = await _get_task(session_maker, task_id)
    details = _step_details(task)
    assert details.get("category_whitelist_warning"), (
        f"空类别配置应记录 warning 到 step_details: {details}"
    )
    assert not details.get("category_whitelist_corrections"), (
        f"空类别配置下不应发生白名单改写: {details}"
    )
    assert task.status == "completed"


@pytest.mark.asyncio
async def test_bug158_whitelist_config_missing_passes_through(client, monkeypatch, tmp_path):
    """白名单配置缺失 → 降级放行模型返回值并记 warning，不硬失败。"""
    ac, session_maker = client
    project_id = await _create_project(ac, "bug158-no-config")
    doc_id = await _seed_document(session_maker, project_id)
    await _seed_model_config(session_maker)

    task_id = await _create_task_only(ac, monkeypatch, project_id, "quick")

    review = _install_fake_runner(monkeypatch, doc_id=doc_id, classify_category="任意新类别")
    monkeypatch.setattr(review, "async_session", session_maker)
    # 指向空目录，使 default-categories.json 不存在
    monkeypatch.setattr(review, "SKILLS_DIR", str(tmp_path))

    await review._run_pipeline(
        task_id, project_id, "quick", [doc_id],
        {"api_base": "http://llm.test/v1", "api_key": "k", "llm_model": "m"},
        _MODE_STEPS["quick"], [], False,
    )

    from app.models.review import ReviewDocument
    async with session_maker() as session:
        result = await session.execute(select(ReviewDocument).where(ReviewDocument.id == doc_id))
        doc = result.scalar_one()
    # 配置缺失时放行，不改写为待确认
    assert doc.category == "任意新类别", f"配置缺失应放行原值，实际 {doc.category}"

    task = await _get_task(session_maker, task_id)
    details = _step_details(task)
    assert details.get("category_whitelist_warning"), (
        f"配置缺失应记录 warning 到 step_details: {details}"
    )
    # 任务仍正常完成（quick 模式全部文档分析成功）
    assert task.status == "completed"
