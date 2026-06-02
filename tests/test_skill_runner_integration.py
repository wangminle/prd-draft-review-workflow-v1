"""SkillRunner 关键执行链集成测试。"""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.services.skill_runner import SkillRunner, SkillStepResult, _REVIEW_DIMENSIONS


def _make_runner(tmp_path: Path) -> SkillRunner:
    return SkillRunner(
        model_cfg={
            "api_base": "http://example.test",
            "api_key": "fake-key",
            "llm_model": "fake-model",
            "max_tokens": 4096,
        },
        skills_dir=tmp_path,
    )


def test_classify_allows_enough_completion_tokens_for_reasoning_models(tmp_path):
    runner = _make_runner(tmp_path)

    max_tokens, temperature = runner._llm_params_for("classify")

    assert max_tokens >= 2048
    assert temperature == 0.1


@pytest.mark.asyncio
async def test_skill_runner_executes_classify_and_per_analysis_steps(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    runner.pipeline_state["docs"] = [{
        "doc_id": "1",
        "filename": "需求A.docx",
        "md_content": "这是预约入口需求正文",
        "category": "功能需求",
        "version": "v1",
    }]

    calls = []

    async def fake_run_skill_with_retry(skill_name, inputs):
        calls.append(skill_name)
        if skill_name == "classify":
            assert "需求A.docx" in inputs["doc_titles_and_excerpts"]
            return SkillStepResult(data={"categories": [{"name": "功能需求"}], "version_chains": []})
        if skill_name == "per_analysis":
            assert inputs["doc_id"] == "1"
            assert inputs["category"] == "功能需求"
            return SkillStepResult(data={
                "core_problem": "统一预约入口",
                "quality_score": 4,
                "category": "功能需求",
                "expert_review": {
                    "summary": "范围基本清晰，但文案一致性仍需补齐。",
                    "checks": [
                        {"rule_key": "scope_realism", "rule_name": "需求范围要写实", "status": "pass", "evidence": "已说明预约入口范围", "suggestion": "保持"},
                        {"rule_key": "boundary_completeness", "rule_name": "能力边界要写全", "status": "pass", "evidence": "已写做什么/不做什么", "suggestion": "补充前置依赖"},
                        {"rule_key": "structured_entitlements", "rule_name": "权益和分类要结构化", "status": "risk", "evidence": "权益说明分散", "suggestion": "增加结构化表格"},
                        {"rule_key": "user_facing_naming", "rule_name": "用户侧命名要可理解", "status": "pass", "evidence": "命名较直白", "suggestion": "保持"},
                        {"rule_key": "copy_consistency", "rule_name": "多入口文案要统一", "status": "missing", "evidence": "文档未体现", "suggestion": "补充多入口对照表"},
                        {"rule_key": "phased_tech_plan", "rule_name": "技术方案要分期但不能糊涂", "status": "pass", "evidence": "有阶段划分", "suggestion": "补齐阶段退出条件"},
                    ],
                },
            })
        raise AssertionError(skill_name)

    monkeypatch.setattr(runner, "run_skill_with_retry", fake_run_skill_with_retry)

    classify_inputs = runner.build_step_inputs("classify", runner.pipeline_state)
    classify_result = await runner.run_skill_with_retry("classify", classify_inputs)
    runner.pipeline_state["classify"] = classify_result.data
    await runner._run_per_analysis()

    assert calls == ["classify", "per_analysis"]
    assert runner.pipeline_state["classify"]["categories"][0]["name"] == "功能需求"
    assert runner.pipeline_state["analyses"]["1"]["core_problem"] == "统一预约入口"
    assert runner.pipeline_state["analyses"]["1"]["expert_review"]["checks"][4]["status"] == "missing"


@pytest.mark.asyncio
async def test_per_analysis_requires_expert_review_block(tmp_path):
    runner = _make_runner(tmp_path)

    result = await runner.after_step("per_analysis", SkillStepResult(data={
        "core_problem": "统一预约入口",
        "category": "功能需求",
        "boundary_in": ["统一预约入口"],
        "boundary_out": ["跨部门审批"],
        "boundary_issues": [],
        "key_points": {"type": "technical"},
        "quality_score": 4,
        "confidence": 0.8,
    }))

    assert result.status == "error"
    assert "expert_review" in result.data["error"]


@pytest.mark.asyncio
async def test_per_analysis_fills_empty_expert_review_summary_when_all_checks_pass(tmp_path):
    runner = _make_runner(tmp_path)

    result = await runner.after_step("per_analysis", SkillStepResult(data={
        "core_problem": "统一预约入口",
        "category": "功能需求",
        "boundary_in": ["统一预约入口"],
        "boundary_out": ["跨部门审批"],
        "boundary_issues": [],
        "key_points": {"type": "technical"},
        "expert_review": {
            "summary": "",
            "checks": [
                {"rule_key": "scope_realism", "rule_name": "需求范围要写实", "status": "pass", "evidence": "已说明范围", "suggestion": "保持"},
                {"rule_key": "boundary_completeness", "rule_name": "能力边界要写全", "status": "pass", "evidence": "已说明边界", "suggestion": "保持"},
                {"rule_key": "structured_entitlements", "rule_name": "权益和分类要结构化", "status": "pass", "evidence": "已结构化", "suggestion": "保持"},
                {"rule_key": "user_facing_naming", "rule_name": "用户侧命名要可理解", "status": "pass", "evidence": "命名清晰", "suggestion": "保持"},
                {"rule_key": "copy_consistency", "rule_name": "多入口文案要统一", "status": "pass", "evidence": "文案一致", "suggestion": "保持"},
                {"rule_key": "phased_tech_plan", "rule_name": "技术方案要分期但不能糊涂", "status": "pass", "evidence": "阶段清楚", "suggestion": "保持"},
            ],
        },
        "quality_score": 4,
        "confidence": 0.8,
    }))

    assert result.status == "success"
    assert result.data["expert_review"]["summary"] == "专家六项评审均通过，暂无额外修改意见。"


@pytest.mark.asyncio
async def test_per_analysis_fills_empty_expert_review_summary_with_problem_items(tmp_path):
    runner = _make_runner(tmp_path)

    result = await runner.after_step("per_analysis", SkillStepResult(data={
        "core_problem": "统一预约入口",
        "category": "功能需求",
        "boundary_in": ["统一预约入口"],
        "boundary_out": ["跨部门审批"],
        "boundary_issues": [],
        "key_points": {"type": "technical"},
        "expert_review": {
            "summary": "-",
            "checks": [
                {"rule_key": "scope_realism", "rule_name": "需求范围要写实", "status": "pass", "evidence": "已说明范围", "suggestion": "保持"},
                {"rule_key": "boundary_completeness", "rule_name": "能力边界要写全", "status": "risk", "evidence": "依赖不清", "suggestion": "补齐前置条件"},
                {"rule_key": "structured_entitlements", "rule_name": "权益和分类要结构化", "status": "pass", "evidence": "已结构化", "suggestion": "保持"},
                {"rule_key": "user_facing_naming", "rule_name": "用户侧命名要可理解", "status": "pass", "evidence": "命名清晰", "suggestion": "保持"},
                {"rule_key": "copy_consistency", "rule_name": "多入口文案要统一", "status": "missing", "evidence": "文档未体现", "suggestion": "增加入口文案对照表"},
                {"rule_key": "phased_tech_plan", "rule_name": "技术方案要分期但不能糊涂", "status": "pass", "evidence": "阶段清楚", "suggestion": "保持"},
            ],
        },
        "quality_score": 4,
        "confidence": 0.8,
    }))

    assert result.status == "success"
    assert "能力边界要写全、多入口文案要统一" in result.data["expert_review"]["summary"]


@pytest.mark.asyncio
async def test_skill_runner_executes_system_review_dimensions(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {"categories": [{"name": "功能需求"}], "version_chains": [], "dependencies": []}
    runner.pipeline_state["analyses"] = {"1": {"core_problem": "统一预约入口", "quality_score": 4}}

    called_dims = []

    async def fake_run_dimension_with_retry(dim_name, inputs):
        called_dims.append(dim_name)
        assert "doc_analyses_summary" in inputs
        return {"dimension": dim_name, "summary": f"{dim_name} 输出"}

    monkeypatch.setattr(runner, "_run_dimension_with_retry", fake_run_dimension_with_retry)

    await runner._run_system_review()

    assert called_dims == _REVIEW_DIMENSIONS
    assert runner.pipeline_state["review_dimensions"]["business-value"]["summary"] == "business-value 输出"
    assert runner.pipeline_state["review_dimensions"]["pm-assessment"]["dimension"] == "pm-assessment"


@pytest.mark.asyncio
async def test_per_analysis_stops_between_documents_when_cancelled(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    runner.pipeline_state["docs"] = [
        {"doc_id": "1", "filename": "需求A.docx", "md_content": "内容A"},
        {"doc_id": "2", "filename": "需求B.docx", "md_content": "内容B"},
    ]
    calls = []

    async def fake_run_skill_with_retry(skill_name, inputs):
        calls.append(inputs["md_content"])
        return SkillStepResult(data={"core_problem": "已分析"})

    async def should_cancel():
        return len(calls) >= 1

    monkeypatch.setattr(runner, "run_skill_with_retry", fake_run_skill_with_retry)

    cancelled = await runner._run_per_analysis(should_cancel=should_cancel)

    assert cancelled is True
    assert calls == ["内容A"]
    assert set(runner.pipeline_state["analyses"].keys()) == {"1"}


@pytest.mark.asyncio
async def test_system_review_stops_between_dimensions_when_cancelled(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {"categories": [{"name": "功能需求"}], "version_chains": [], "dependencies": []}
    runner.pipeline_state["analyses"] = {"1": {"core_problem": "统一预约入口", "quality_score": 4}}
    called_dims = []

    async def fake_run_dimension_with_retry(dim_name, inputs):
        called_dims.append(dim_name)
        return {"dimension": dim_name}

    async def should_cancel():
        return len(called_dims) >= 1

    monkeypatch.setattr(runner, "_run_dimension_with_retry", fake_run_dimension_with_retry)

    cancelled = await runner._run_system_review(should_cancel=should_cancel)

    assert cancelled is True
    assert called_dims == [_REVIEW_DIMENSIONS[0]]
    assert set(runner.pipeline_state["review_dimensions"].keys()) == {_REVIEW_DIMENSIONS[0]}


@pytest.mark.asyncio
async def test_skill_runner_executes_insights_and_report_steps(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {"categories": [{"name": "功能需求"}], "version_chains": [], "dependencies": []}
    runner.pipeline_state["analyses"] = {"1": {"core_problem": "统一预约入口", "quality_score": 4, "boundary_in": ["统一入口"], "boundary_out": ["跨部门审批"]}}
    runner.pipeline_state["review_dimensions"] = {"business-value": {"summary": "提升预约转化"}}

    insight_calls = []

    async def fake_run_insight_substep_with_retry(prompt_name, inputs):
        insight_calls.append(prompt_name)
        if prompt_name == "evolution-match":
            return {"matches": [{"issue": "跨部门协同边界未定义"}]}
        if prompt_name == "feature-extraction":
            return {"coverage_matrix": [{"feature": "预约入口", "status": "covered"}], "gaps": [], "overlaps": []}
        if prompt_name == "gap-assessment":
            return {"gap_assessments": [{"feature": "审批链路", "severity": "medium"}]}
        raise AssertionError(prompt_name)

    async def fake_run_skill_with_retry(skill_name, inputs):
        assert skill_name == "report"
        assert "## 文档分类" in inputs["report_content"]
        assert "## 逐篇分析" in inputs["report_content"]
        assert "## 体系Review" in inputs["report_content"]
        assert "## 需求洞察" in inputs["report_content"]
        return SkillStepResult(data={"markdown": "# 报告\n\n已汇总"})

    monkeypatch.setattr(runner, "_run_insight_substep_with_retry", fake_run_insight_substep_with_retry)
    monkeypatch.setattr(runner, "run_skill_with_retry", fake_run_skill_with_retry)

    await runner._run_insights()
    report_inputs = runner._build_report_inputs(runner.pipeline_state)
    report_result = await runner.run_skill_with_retry("report", report_inputs)
    runner.pipeline_state["report"] = report_result.data

    assert insight_calls == ["evolution-match", "feature-extraction", "gap-assessment"]
    assert runner.pipeline_state["insights"]["gap"]["gap_assessments"][0]["feature"] == "审批链路"
    assert runner.pipeline_state["report"]["markdown"] == "# 报告\n\n已汇总"
