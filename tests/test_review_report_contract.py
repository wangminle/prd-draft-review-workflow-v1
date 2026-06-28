"""需求审查报告返回契约测试。"""

import json
import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def report_client():
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


async def _seed_review(session_maker, project_id: int, user_id: int, mode: str, *, insights=None, prd_draft=None, report_markdown=None) -> int:
    from app.models.review import DocAnalysis, ReviewDocument, ReviewTask, SystemReview

    step_details = {}
    if insights is not None:
        step_details["insights"] = insights
    if prd_draft is not None:
        step_details["prd_draft"] = prd_draft
    if report_markdown is not None:
        step_details["report_markdown"] = report_markdown

    async with session_maker() as session:
        doc = ReviewDocument(
            project_id=project_id,
            filename=f"{mode}-需求A.docx",
            status="analyzed",
            document_type="requirement",
        )
        session.add(doc)
        await session.flush()

        task = ReviewTask(
            project_id=project_id,
            mode=mode,
            status="completed",
            current_step=5,
            total_docs=1,
            completed_docs=1,
            context_version=3,
            model_id="deepseek",
            created_by=user_id,
            step_statuses='{"0":"completed","1":"completed"}',
            step_details=json.dumps(step_details, ensure_ascii=False),
        )
        session.add(task)
        await session.flush()

        full_analysis = {
            "boundary_issues": [{"issue": "跨部门协同边界未定义", "severity": "medium"}],
            "key_points": {"type": "summary", "solution_highlights": ["统一入口"]},
            "resolution_tracking": [{"issue": "跨部门协同边界未定义", "status": "partial"}],
            "expert_review": {
                "summary": "范围基本清晰，但专家建议补齐文案统一和分期边界。",
                "checks": [
                    {"rule_key": "scope_realism", "rule_name": "需求范围要写实", "status": "pass", "evidence": "已明确统一预约入口", "suggestion": "保持当前写法"},
                    {"rule_key": "boundary_completeness", "rule_name": "能力边界要写全", "status": "risk", "evidence": "跨部门审批仍模糊", "suggestion": "补充依赖边界"},
                    {"rule_key": "structured_entitlements", "rule_name": "权益和分类要结构化", "status": "risk", "evidence": "用户权益描述较散", "suggestion": "增加结构化表格"},
                    {"rule_key": "user_facing_naming", "rule_name": "用户侧命名要可理解", "status": "pass", "evidence": "统一预约入口命名可理解", "suggestion": "保持"},
                    {"rule_key": "copy_consistency", "rule_name": "多入口文案要统一", "status": "missing", "evidence": "文档未体现多入口命名对照", "suggestion": "增加入口文案对照表"},
                    {"rule_key": "phased_tech_plan", "rule_name": "技术方案要分期但不能糊涂", "status": "risk", "evidence": "未说明阶段切换条件", "suggestion": "补充阶段退出条件"},
                ],
            },
        }
        session.add(DocAnalysis(
            document_id=doc.id,
            task_id=task.id,
            core_problem="统一预约入口",
            category="功能需求",
            boundary_in="[\"统一预约入口\"]",
            boundary_out="[\"跨部门审批\"]",
            spec_violations=json.dumps(["缺少验收口径"], ensure_ascii=False),
            quality_score=4.5,
            full_analysis=json.dumps(full_analysis, ensure_ascii=False),
        ))
        session.add(SystemReview(
            task_id=task.id,
            project_id=project_id,
            business_value=json.dumps({"summary": "提升预约转化"}, ensure_ascii=False),
            pm_scores=json.dumps({
                "writing_scores": {"logic": {"score": 4, "evidence": "结构清晰"}},
                "thinking_scores": {"data": {"score": 3, "evidence": "有数据采集"}},
            }, ensure_ascii=False),
        ))
        await session.commit()
        return task.id


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["insight", "full"])
async def test_report_returns_insights_when_mode_is_insight_or_full(report_client, mode):
    client, session_maker = report_client
    headers, user_id = await _register(client, f"report_insight_{mode}")
    project_id = await _create_project(client, headers, f"{mode} 报告项目")
    review_id = await _seed_review(
        session_maker,
        project_id,
        user_id,
        mode,
        insights={"gap": {"summary": "存在能力空白"}},
        report_markdown="# 已润色报告\n\n正文",
    )

    resp = await client.get(f"/api/review/projects/{project_id}/reviews/{review_id}/report", headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["task_id"] == review_id
    assert data["mode"] == mode
    assert data["context_version"] == 3
    assert data["insights"]["gap"]["summary"] == "存在能力空白"
    assert data["analyses"][0]["core_problem"] == "统一预约入口"
    assert data["analyses"][0]["expert_review"]["summary"] == "范围基本清晰，但专家建议补齐文案统一和分期边界。"
    assert data["system_review"]["business_value"]["summary"] == "提升预约转化"
    assert data["pm_assessment"]["writing_scores"]["logic"]["score"] == 4


@pytest.mark.asyncio
async def test_analyses_endpoint_exposes_expert_review_block(report_client):
    client, session_maker = report_client
    headers, user_id = await _register(client, "report_expert_review_user")
    project_id = await _create_project(client, headers, "expert review 项目")
    review_id = await _seed_review(session_maker, project_id, user_id, "quick")

    resp = await client.get(f"/api/review/projects/{project_id}/reviews/{review_id}/analyses", headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data[0]["expert_review"]["checks"][4]["rule_key"] == "copy_consistency"
    assert data[0]["expert_review"]["checks"][4]["status"] == "missing"


@pytest.mark.asyncio
async def test_report_returns_prd_draft_when_mode_is_draft(report_client):
    client, session_maker = report_client
    headers, user_id = await _register(client, "report_prd_draft_user")
    project_id = await _create_project(client, headers, "draft 报告项目")
    review_id = await _seed_review(
        session_maker,
        project_id,
        user_id,
        "draft",
        prd_draft={"title": "预约工作台 PRD", "background": "解决预约入口分散"},
    )

    resp = await client.get(f"/api/review/projects/{project_id}/reviews/{review_id}/report", headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mode"] == "draft"
    assert data["prd_draft"]["title"] == "预约工作台 PRD"
    assert data["prd_draft"]["background"] == "解决预约入口分散"


@pytest.mark.asyncio
async def test_start_review_returns_existing_active_task_for_same_doc_scope(report_client, monkeypatch):
    from app.models.review import ReviewDocument, ReviewTask
    from app.routers import review
    from sqlalchemy import select

    async def _noop_pipeline(*args, **kwargs):
        return None
    async def _model_config(*args, **kwargs):
        return {
            "model_id": "deepseek",
            "api_base": "http://llm.test",
            "api_key": "test-key",
            "llm_model": "deepseek",
            "max_tokens": 1024,
        }

    monkeypatch.setattr(review, "_run_pipeline", _noop_pipeline)
    monkeypatch.setattr(review, "_get_model_config", _model_config)
    client, session_maker = report_client
    headers, user_id = await _register(client, "review_active_dedupe_user")
    project_id = await _create_project(client, headers, "active dedupe 项目")

    async with session_maker() as session:
        doc = ReviewDocument(
            project_id=project_id,
            filename="需求A.docx",
            status="uploaded",
            document_type="requirement",
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        doc_id = doc.id

    payload = {"mode": "insight", "document_ids": [doc_id], "model_id": "deepseek"}
    first = await client.post(f"/api/review/projects/{project_id}/reviews", headers=headers, json=payload)
    second = await client.post(f"/api/review/projects/{project_id}/reviews", headers=headers, json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["task_id"] == first.json()["task_id"]

    async with session_maker() as session:
        result = await session.execute(
            select(ReviewTask).where(
                ReviewTask.project_id == project_id,
                ReviewTask.mode == "insight",
                ReviewTask.created_by == user_id,
            )
        )
        assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_report_markdown_prefers_polished_markdown_artifact(report_client):
    client, session_maker = report_client
    headers, user_id = await _register(client, "report_markdown_user")
    project_id = await _create_project(client, headers, "markdown 报告项目")
    review_id = await _seed_review(
        session_maker,
        project_id,
        user_id,
        "review",
        report_markdown="# 已润色报告\n\n这里是最终正文",
    )

    resp = await client.get(
        f"/api/review/projects/{project_id}/reviews/{review_id}/report?format=markdown",
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.text == "# 已润色报告\n\n这里是最终正文"


@pytest.mark.asyncio
async def test_list_reviews_exposes_selected_document_ids_for_running_tasks(report_client):
    client, session_maker = report_client
    headers, user_id = await _register(client, "report_running_doc_scope_user")
    project_id = await _create_project(client, headers, "running task scope 项目")

    from app.models.review import ReviewDocument, ReviewTask

    async with session_maker() as session:
        doc = ReviewDocument(
            project_id=project_id,
            filename="运行中需求A.docx",
            status="uploaded",
            document_type="requirement",
        )
        session.add(doc)
        await session.flush()

        task = ReviewTask(
            project_id=project_id,
            mode="quick",
            status="running",
            current_step=1,
            total_docs=1,
            completed_docs=0,
            context_version=2,
            model_id="deepseek",
            created_by=user_id,
            step_statuses='{"0":"completed","1":"running","2":"pending"}',
            step_details=json.dumps({"document_ids": [doc.id]}, ensure_ascii=False),
        )
        session.add(task)
        await session.commit()

    resp = await client.get(f"/api/review/projects/{project_id}/reviews", headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data[0]["task_id"] == task.id
    assert data[0]["status"] == "running"
    assert data[0]["document_ids"] == [doc.id]


def test_markdown_report_fallback_includes_expert_review():
    from app.routers.review import _render_markdown_report
    from app.schemas.review import AnalysisInfo

    analyses = [AnalysisInfo(
        id=1,
        document_id=1,
        filename="需求A.docx",
        core_problem="统一预约入口",
        category="功能需求",
        boundary_in=["统一预约入口"],
        boundary_out=["跨部门审批"],
        expert_review={
            "summary": "范围基本清晰，但文案统一仍需加强。",
            "checks": [
                {"rule_key": "scope_realism", "rule_name": "需求范围要写实", "status": "pass", "evidence": "已说明范围", "suggestion": "保持"},
                {"rule_key": "boundary_completeness", "rule_name": "能力边界要写全", "status": "risk", "evidence": "边界不完整", "suggestion": "补齐依赖"},
                {"rule_key": "structured_entitlements", "rule_name": "权益和分类要结构化", "status": "risk", "evidence": "权益分散", "suggestion": "结构化输出"},
                {"rule_key": "user_facing_naming", "rule_name": "用户侧命名要可理解", "status": "pass", "evidence": "命名直白", "suggestion": "保持"},
                {"rule_key": "copy_consistency", "rule_name": "多入口文案要统一", "status": "missing", "evidence": "文档未体现", "suggestion": "补入口对照"},
                {"rule_key": "phased_tech_plan", "rule_name": "技术方案要分期但不能糊涂", "status": "risk", "evidence": "缺阶段条件", "suggestion": "补齐条件"},
            ],
        },
        spec_violations=None,
        quality_score=4.5,
        full_analysis=None,
    )]

    markdown = _render_markdown_report(analyses, {}, None, None)

    assert "专家意见结论: 范围基本清晰，但文案统一仍需加强。" in markdown
    assert "需求范围要写实: 通过" in markdown
    assert "多入口文案要统一: 缺失" in markdown


@pytest.mark.asyncio
async def test_cached_system_review_requires_same_document_scope(report_client):
    client, session_maker = report_client
    headers, user_id = await _register(client, "report_cache_scope_user")
    project_id = await _create_project(client, headers, "缓存范围项目")

    from app.models.review import DocAnalysis, ReviewDocument, ReviewTask, SystemReview
    from app.routers.review import _find_cached_system_review

    complete_json = json.dumps({"summary": "完整维度"}, ensure_ascii=False)
    pm_scores = json.dumps({"writing_scores": {"logic": {"score": 4}}}, ensure_ascii=False)

    async with session_maker() as session:
        docs = [
            ReviewDocument(
                project_id=project_id,
                filename=f"需求{i}.docx",
                status="analyzed",
                document_type="requirement",
            )
            for i in range(1, 4)
        ]
        session.add_all(docs)
        await session.flush()

        batch_task = ReviewTask(
            project_id=project_id,
            mode="review",
            status="completed",
            total_docs=3,
            completed_docs=3,
            context_version=3,
            model_id="deepseek",
            created_by=user_id,
        )
        single_task = ReviewTask(
            project_id=project_id,
            mode="review",
            status="completed",
            total_docs=1,
            completed_docs=1,
            context_version=3,
            model_id="deepseek",
            created_by=user_id,
        )
        session.add_all([batch_task, single_task])
        await session.flush()

        for doc in docs:
            session.add(DocAnalysis(document_id=doc.id, task_id=batch_task.id, core_problem=f"批量-{doc.id}"))
        session.add(DocAnalysis(document_id=docs[0].id, task_id=single_task.id, core_problem="单篇-1"))

        batch_sr = SystemReview(
            task_id=batch_task.id,
            project_id=project_id,
            business_value=complete_json,
            architecture=complete_json,
            competition=complete_json,
            product_strategy=complete_json,
            tech_evolution=complete_json,
            action_plan=complete_json,
            pm_scores=pm_scores,
        )
        single_sr = SystemReview(
            task_id=single_task.id,
            project_id=project_id,
            business_value=complete_json,
            architecture=complete_json,
            competition=complete_json,
            product_strategy=complete_json,
            tech_evolution=complete_json,
            action_plan=complete_json,
            pm_scores=pm_scores,
        )
        session.add_all([batch_sr, single_sr])
        await session.flush()
        batch_sr_id = batch_sr.id
        single_sr_id = single_sr.id
        doc_ids = [doc.id for doc in docs]
        await session.commit()

        hit_batch = await _find_cached_system_review(
            session,
            project_id,
            doc_ids=doc_ids,
            context_version=3,
            model_id="deepseek",
        )
        hit_single = await _find_cached_system_review(
            session,
            project_id,
            doc_ids=[doc_ids[0]],
            context_version=3,
            model_id="deepseek",
        )
        miss_other_doc = await _find_cached_system_review(
            session,
            project_id,
            doc_ids=[doc_ids[1]],
            context_version=3,
            model_id="deepseek",
        )
        miss_model = await _find_cached_system_review(
            session,
            project_id,
            doc_ids=[doc_ids[0]],
            context_version=3,
            model_id="other-model",
        )

    assert hit_batch.id == batch_sr_id
    assert hit_single.id == single_sr_id
    assert miss_other_doc is None
    assert miss_model is None
