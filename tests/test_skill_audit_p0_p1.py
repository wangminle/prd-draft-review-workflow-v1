"""Tests for Skill audit fixes (P0-3.1, P0-3.2, P1-4.1).

Covers:
- system-review: structured dimensions_executed/failed + all_failed status
- requirement-insights: deterministic coverage_matrix construction
- requirement-insights: issue conservation when model drops issues
- requirement-insights: baseline_warning propagation
- requirement-insights: subsequent docs include structured analysis content
"""

import json
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.services.skill_runner import SkillRunner, _REVIEW_DIMENSIONS


def _make_runner(tmp_path: Path, context: dict | None = None) -> SkillRunner:
    return SkillRunner(
        model_cfg={
            "api_base": "http://example.test",
            "api_key": "fake-key",
            "llm_model": "fake-model",
            "max_tokens": 4096,
        },
        skills_dir=tmp_path,
        context=context or {},
    )


# ── P0-3.2: system-review all-fail propagation ──────────────────────────────


@pytest.mark.asyncio
async def test_system_review_all_dimensions_failing_marks_all_failed(tmp_path, monkeypatch):
    """When every dimension returns {"error": ...}, status must be 'all_failed'."""
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {
        "categories": [{"name": "X"}],
        "version_chains": [],
        "dependencies": [],
    }
    runner.pipeline_state["analyses"] = {"1": {"core_problem": "p", "quality_score": 4}}

    async def fail_dim(dim_name, inputs):
        return {"error": f"dimension {dim_name} failed"}

    monkeypatch.setattr(runner, "_run_dimension_with_retry", fail_dim)

    cancelled = await runner._run_system_review()

    assert cancelled is False
    meta = runner.pipeline_state["review_dimensions_meta"]
    assert meta["status"] == "all_failed"
    assert meta["failed_count"] == len(_REVIEW_DIMENSIONS)
    assert meta["success_count"] == 0
    assert set(meta["dimensions_failed"]) == set(_REVIEW_DIMENSIONS)
    assert meta["dimensions_executed"] == []


@pytest.mark.asyncio
async def test_system_review_partial_failure_marks_partial(tmp_path, monkeypatch):
    """When some dimensions fail and some succeed, status must be 'partial'."""
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {
        "categories": [{"name": "X"}],
        "version_chains": [],
        "dependencies": [],
    }
    runner.pipeline_state["analyses"] = {"1": {"core_problem": "p", "quality_score": 4}}

    async def mixed(dim_name, inputs):
        if dim_name == "competition":
            return {"error": "competition failed"}
        return {"dimension": dim_name, "summary": "ok"}

    monkeypatch.setattr(runner, "_run_dimension_with_retry", mixed)

    await runner._run_system_review()

    meta = runner.pipeline_state["review_dimensions_meta"]
    assert meta["status"] == "partial"
    assert "competition" in meta["dimensions_failed"]
    assert "competition" not in meta["dimensions_executed"]
    assert "business-value" in meta["dimensions_executed"]


@pytest.mark.asyncio
async def test_system_review_all_success_marks_success(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {
        "categories": [{"name": "X"}],
        "version_chains": [],
        "dependencies": [],
    }
    runner.pipeline_state["analyses"] = {"1": {"core_problem": "p", "quality_score": 4}}

    async def ok(dim_name, inputs):
        return {"dimension": dim_name}

    monkeypatch.setattr(runner, "_run_dimension_with_retry", ok)

    await runner._run_system_review()

    meta = runner.pipeline_state["review_dimensions_meta"]
    assert meta["status"] == "success"
    assert meta["failed_count"] == 0


# ── P0-3.1: deterministic coverage_matrix construction ───────────────────────


def test_build_coverage_matrix_marks_gap_when_no_source_docs(tmp_path):
    runner = _make_runner(tmp_path)
    analyses = {"doc1": {"boundary_in": ["X"], "core_problem": "p"}}

    matrix = runner._build_coverage_matrix(
        [{"feature_id": "feat_001", "name": "Y", "source_doc_ids": []}],
        analyses,
    )

    assert matrix[0]["status"] == "gap"
    assert matrix[0]["covered_by"] == []


def test_build_coverage_matrix_marks_overlap_when_multiple_docs(tmp_path):
    runner = _make_runner(tmp_path)
    analyses = {
        "doc1": {"boundary_in": ["X"], "core_problem": "p"},
        "doc2": {"boundary_in": ["X"], "core_problem": "q"},
    }

    matrix = runner._build_coverage_matrix(
        [{"feature_id": "feat_001", "name": "X", "source_doc_ids": ["doc1", "doc2"]}],
        analyses,
    )

    assert matrix[0]["status"] == "overlap"
    assert set(matrix[0]["covered_by"]) == {"doc1", "doc2"}


def test_build_coverage_matrix_falls_back_to_substring_match(tmp_path):
    """When the model returns no source_doc_ids, derive them from boundary_in."""
    runner = _make_runner(tmp_path)
    analyses = {
        "doc1": {"boundary_in": ["统一预约入口"], "core_problem": "..."},
        "doc2": {"boundary_in": ["其它能力"], "core_problem": "x"},
    }

    matrix = runner._build_coverage_matrix(
        [{"name": "统一预约入口"}],  # no source_doc_ids, no feature_id
        analyses,
    )

    assert matrix[0]["status"] == "covered"
    assert matrix[0]["covered_by"] == ["doc1"]
    assert matrix[0]["feature_id"] == "feat_001"


@pytest.mark.asyncio
async def test_gap_assessment_receives_non_empty_coverage_matrix(tmp_path, monkeypatch):
    """The original bug: feature-extraction returned feature_dimensions but
    _build_insight_inputs('gap-assessment') read coverage_matrix (always empty).
    Now coverage_matrix must be deterministically derived.
    """
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {"categories": [], "version_chains": []}
    runner.pipeline_state["analyses"] = {
        "doc1": {"boundary_in": ["预约"], "boundary_out": [], "core_problem": "预约"},
        "doc2": {"boundary_in": ["其它"], "boundary_out": [], "core_problem": "其它"},
    }

    feature_extraction_output = {
        "feature_dimensions": [
            {"feature_id": "feat_001", "name": "预约", "source_doc_ids": ["doc1"]},
            {"feature_id": "feat_002", "name": "审批", "source_doc_ids": []},
            {"feature_id": "feat_003", "name": "预约", "source_doc_ids": ["doc1", "doc2"]},
        ],
        "baseline_warning": "未提供独立目标能力基线",
    }

    inputs = runner._build_insight_inputs("gap-assessment", {"features": feature_extraction_output})

    coverage_matrix = json.loads(inputs["coverage_matrix"])
    gaps = json.loads(inputs["gaps"])
    overlaps = json.loads(inputs["overlaps"])

    assert len(coverage_matrix) == 3
    assert {entry["status"] for entry in coverage_matrix} == {"covered", "gap", "overlap"}
    assert len(gaps) == 1
    assert gaps[0]["feature"] == "审批"
    assert len(overlaps) == 1
    assert inputs["baseline_warning"] == "未提供独立目标能力基线"


# ── P1-4.1: issue conservation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_conservation_backfill_when_model_drops_issues(tmp_path, monkeypatch):
    """When the model returns fewer matches than input issues, the runner
    must backfill unresolved entries so total_issues is conserved.
    """
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {
        "categories": [],
        "version_chains": [
            {"chain_name": "c1", "versions": [
                {"doc_id": "doc1", "version": "v1", "title": "t1"},
                {"doc_id": "doc2", "version": "v2", "title": "t2"},
            ]},
        ],
    }
    runner.pipeline_state["analyses"] = {
        "doc1": {
            "boundary_in": [], "boundary_out": [],
            "boundary_issues": [
                {"issue": "问题A", "severity": "high"},
                {"issue": "问题B", "severity": "medium"},
            ],
            "core_problem": "p1",
        },
        "doc2": {
            "boundary_in": [], "boundary_out": [],
            "boundary_issues": [],
            "core_problem": "p2",
        },
    }

    async def fake_substep(prompt_name, inputs):
        if prompt_name == "evolution-match":
            # Model only returns ONE match, dropping 问题B
            return {"matches": [
                {"issue_id": "doc1_issue_000", "issue": "问题A", "status": "resolved",
                 "resolved_in": "doc2", "evidence": "...", "confidence": "high"},
            ]}
        if prompt_name == "feature-extraction":
            return {"feature_dimensions": [], "baseline_warning": "no baseline"}
        if prompt_name == "gap-assessment":
            return {"gap_assessments": []}
        return {}

    monkeypatch.setattr(runner, "_run_insight_substep_with_retry", fake_substep)

    await runner._run_insights()

    evolution = runner.pipeline_state["insights"]["evolution"]
    matches = evolution["matches"]
    assert len(matches) == 2  # backfilled 问题B

    backfilled = [m for m in matches if m.get("issue") == "问题B"]
    assert len(backfilled) == 1
    assert backfilled[0]["status"] == "unresolved"
    assert backfilled[0]["confidence"] == "low"

    meta = runner.pipeline_state["insights_meta"]
    conservation = meta["issue_conservation"]
    assert conservation["valid"] is True
    assert conservation["total_issues"] == 2
    assert conservation["resolved"] == 1
    assert conservation["unresolved"] == 1


def test_compute_issue_conservation_invariant_holds():
    runner = _make_runner(Path("/tmp"))
    evolution = {"matches": [
        {"status": "resolved"},
        {"status": "partial"},
        {"status": "unresolved"},
    ]}
    result = runner._compute_issue_conservation(evolution)
    assert result["valid"] is True
    assert result["total_issues"] == 3
    assert result["resolved"] == 1
    assert result["partial"] == 1
    assert result["unresolved"] == 1


def test_compute_issue_conservation_invariant_violation_when_status_missing():
    """If the model returns matches with no status field, they should still
    count as unresolved (default), keeping the invariant valid.
    """
    runner = _make_runner(Path("/tmp"))
    evolution = {"matches": [{"issue": "x"}, {"status": "resolved"}]}
    result = runner._compute_issue_conservation(evolution)
    assert result["valid"] is True
    assert result["unresolved"] == 1


# ── P1-4.1: subsequent docs include structured analysis content ──────────────


@pytest.mark.asyncio
async def test_evolution_match_inputs_include_subsequent_doc_analysis(tmp_path, monkeypatch):
    """subsequent_docs must include core_problem/boundary_in/key_points/excerpt,
    not just metadata.
    """
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {
        "categories": [],
        "version_chains": [
            {"chain_name": "c1", "versions": [
                {"doc_id": "doc1", "version": "v1", "title": "t1"},
                {"doc_id": "doc2", "version": "v2", "title": "t2"},
            ]},
        ],
    }
    runner.pipeline_state["analyses"] = {
        "doc1": {
            "boundary_in": [], "boundary_out": [],
            "boundary_issues": [{"issue": "问题A"}],
            "core_problem": "p1",
        },
        "doc2": {
            "boundary_in": ["新边界"], "boundary_out": [],
            "boundary_issues": [],
            "core_problem": "解决 p1 的方案",
            "key_points": {"type": "plan"},
        },
    }

    inputs = runner._build_insight_inputs("evolution-match", {})

    current_issues = json.loads(inputs["current_issues"])
    subsequent_docs = json.loads(inputs["subsequent_docs"])

    # current_issues must carry stable issue_id and doc_id
    assert current_issues[0]["issue_id"] == "doc1_issue_000"
    assert current_issues[0]["doc_id"] == "doc1"
    # Each issue must also have its subsequent_docs attached
    assert current_issues[0]["subsequent_docs"][0]["core_problem"] == "解决 p1 的方案"
    assert current_issues[0]["subsequent_docs"][0]["boundary_in"] == ["新边界"]
    assert current_issues[0]["subsequent_docs"][0]["key_points"] == {"type": "plan"}
    assert "excerpt" in current_issues[0]["subsequent_docs"][0]

    # subsequent_docs map must also include structured content
    assert "doc1" in subsequent_docs
    assert subsequent_docs["doc1"][0]["core_problem"] == "解决 p1 的方案"


# ── P0-3.1: baseline_warning propagation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_baseline_warning_propagates_to_insights_meta(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    runner.pipeline_state["classify"] = {"categories": [], "version_chains": []}
    runner.pipeline_state["analyses"] = {"doc1": {"boundary_in": [], "boundary_out": []}}

    async def fake_substep(prompt_name, inputs):
        if prompt_name == "feature-extraction":
            return {
                "feature_dimensions": [],
                "baseline_warning": "未提供独立目标能力基线，仅完成覆盖分析",
            }
        if prompt_name == "evolution-match":
            return {"matches": []}
        if prompt_name == "gap-assessment":
            return {"gap_assessments": []}
        return {}

    monkeypatch.setattr(runner, "_run_insight_substep_with_retry", fake_substep)

    await runner._run_insights()

    meta = runner.pipeline_state["insights_meta"]
    assert "未提供独立目标能力基线" in meta["baseline_warning"]


def test_feature_extraction_inputs_include_target_baseline(tmp_path):
    """When ReviewContext provides target_capability_baseline, it must be
    injected into feature-extraction inputs.
    """
    runner = _make_runner(
        tmp_path,
        context={"target_capability_baseline": ["预约", "审批", "通知"]},
    )
    runner.pipeline_state["classify"] = {"categories": [], "version_chains": []}
    runner.pipeline_state["analyses"] = {}

    inputs = runner._build_insight_inputs("feature-extraction", {})

    baseline = json.loads(inputs["target_baseline"])
    assert baseline == ["预约", "审批", "通知"]
