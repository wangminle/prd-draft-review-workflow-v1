"""Tests for BUG-161 fixes in skills/requirement-insights/scripts/insights.py.

Covers:
- --target-baseline provided: no "no-baseline" warning, baseline_source set,
  baseline capabilities without document coverage surface as gap
- no baseline: warning present, baseline_source is None
- evolution matches keep issue_id/evidence/confidence in final output
- gap assessment backfill aligns by feature_id (shuffled model output must
  not misalign); missing feature_id degrades to positional with warnings
- overlap assessment still runs when gaps list is empty
"""

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "skills" / "requirement-insights" / "scripts" / "insights.py"

spec = importlib.util.spec_from_file_location("insights_script", SCRIPT)
insights = importlib.util.module_from_spec(spec)
sys.modules.setdefault("insights_script", insights)
spec.loader.exec_module(insights)


def _analyses():
    return [
        {"doc_id": "doc1", "version": "v1", "category": "预约",
         "boundary_in": ["服务预约"], "boundary_out": [],
         "core_problem": "服务预约流程", "boundary_issues": []},
        {"doc_id": "doc2", "version": "v2", "category": "控制",
         "boundary_in": ["模式控制"], "boundary_out": [],
         "core_problem": "模式切换", "boundary_issues": []},
    ]


def _doc_index(analyses):
    return insights.build_doc_index(analyses, {"documents": []})


def _make_llm_router(monkeypatch, feature_extraction=None, gap_assessment=None,
                     evolution_match=None, calls=None):
    def fake_call_llm(client, system_prompt, user_msg, text_model):
        if calls is not None:
            calls.append(system_prompt)
        if "功能维度提取" in system_prompt:
            return feature_extraction or {}
        if "缺口评估" in system_prompt:
            return gap_assessment or {}
        if "演进" in system_prompt or "匹配" in system_prompt:
            return evolution_match or {}
        return {}

    monkeypatch.setattr(insights, "call_llm", fake_call_llm)


# ── baseline provided ────────────────────────────────────────────────────────


def test_target_baseline_provided_no_warning_and_baseline_gap(monkeypatch):
    """--target-baseline 传入后：无'无基线'warning，baseline_source 标注，
    基线中无文档覆盖的能力被标记为 gap（即使提取结果漏掉了它）。"""
    _make_llm_router(
        monkeypatch,
        feature_extraction={
            "feature_dimensions": [
                {"feature_id": "feat_001", "name": "服务预约",
                 "source_doc_ids": ["doc1"], "status": "covered"},
            ],
            "baseline_warning": "",
        },
        gap_assessment={"gap_assessments": [
            {"feature_id": "feat_002", "feature": "审批流",
             "severity": "high", "impact": "核心流程缺失",
             "suggestion": "补充审批需求文档"},
        ]},
    )
    analyses = _analyses()

    result = insights.run_gap_analysis(
        None, _doc_index(analyses), analyses, categories=[], text_model="fake",
        target_baseline=["服务预约", "审批流"])

    assert result["baseline_warning"] == ""
    assert result["baseline_source"] == "user_provided"

    matrix = {e["feature"]: e for e in result["coverage_matrix"]}
    assert matrix["服务预约"]["status"] == "covered"
    assert matrix["服务预约"]["source_doc_ids"] == ["doc1"]
    # 基线中的"审批流"未被提取结果覆盖，由代码合并为显式 gap
    assert "审批流" in matrix
    assert matrix["审批流"]["status"] == "gap"
    assert matrix["审批流"]["covered_by"] == []
    assert matrix["审批流"]["feature_id"]

    assert result["summary"]["gaps"] == 1
    gap = result["gaps"][0]
    assert gap["feature"] == "审批流"
    assert gap["severity"] == "high"
    assert result["assessment_alignment"]["method"] == "feature_id"


def test_no_target_baseline_keeps_warning(monkeypatch):
    """不传基线时 warning 存在，baseline_source 为 None。"""
    _make_llm_router(
        monkeypatch,
        feature_extraction={
            "feature_dimensions": [
                {"feature_id": "feat_001", "name": "服务预约",
                 "source_doc_ids": ["doc1"], "status": "extracted"},
            ],
            "baseline_warning": "未提供独立目标能力基线，仅完成现有需求覆盖分析",
        },
    )
    analyses = _analyses()

    result = insights.run_gap_analysis(
        None, _doc_index(analyses), analyses, categories=[], text_model="fake")

    assert "未提供独立目标能力基线" in result["baseline_warning"]
    assert result["baseline_source"] is None


# ── evolution matches keep evidence/confidence ───────────────────────────────


def test_evolution_matches_preserve_issue_id_evidence_confidence(monkeypatch):
    """最终输出保留 evolution matches 的 issue_id/evidence/confidence；
    模型漏返回的问题由代码回填为 unresolved + confidence=low。"""
    _make_llm_router(
        monkeypatch,
        evolution_match={"matches": [
            {"issue_id": "doc1_issue_000", "issue": "问题A",
             "status": "resolved", "resolved_in": "doc2",
             "resolved_version": "v2",
             "evidence": "doc2 核心问题已覆盖该问题", "confidence": "high"},
        ]},
    )
    analyses = [
        {"doc_id": "doc1", "version": "v1", "category": "X",
         "boundary_in": [], "boundary_out": [], "core_problem": "p1",
         "boundary_issues": [{"issue": "问题A", "severity": "high"},
                              {"issue": "问题B", "severity": "medium"}]},
        {"doc_id": "doc2", "version": "v2", "category": "X",
         "boundary_in": [], "boundary_out": [], "core_problem": "p2",
         "boundary_issues": []},
    ]
    version_chains = [{"chain_name": "c1", "versions": [
        {"doc_id": "doc1", "version": "v1", "title": "t1"},
        {"doc_id": "doc2", "version": "v2", "title": "t2"},
    ]}]

    result = insights.run_evolution_tracking(
        None, _doc_index(analyses), version_chains, analyses, "fake")

    matches = result["matches"]
    assert len(matches) == 2

    by_issue = {m["issue"]: m for m in matches}
    assert by_issue["问题A"]["issue_id"] == "doc1_issue_000"
    assert by_issue["问题A"]["evidence"] == "doc2 核心问题已覆盖该问题"
    assert by_issue["问题A"]["confidence"] == "high"

    backfilled = by_issue["问题B"]
    assert backfilled["issue_id"] == "doc1_issue_001"
    assert backfilled["status"] == "unresolved"
    assert backfilled["confidence"] == "low"

    assert result["summary"]["conservation_valid"] is True
    assert result["summary"]["total_issues"] == 2


# ── gap backfill aligns by feature_id ────────────────────────────────────────


def test_gap_assessment_aligned_by_feature_id_not_position(monkeypatch):
    """模型乱序返回 gap_assessments 时，按 feature_id 对齐回填，不错位。"""
    _make_llm_router(
        monkeypatch,
        feature_extraction={"feature_dimensions": [
            {"feature_id": "feat_001", "name": "服务预约",
             "source_doc_ids": ["doc1"]},
            {"feature_id": "feat_002", "name": "审批流", "source_doc_ids": []},
            {"feature_id": "feat_003", "name": "消息通知", "source_doc_ids": []},
        ]},
        # 乱序：feat_003 在前，feat_002 在后
        gap_assessment={"gap_assessments": [
            {"feature_id": "feat_003", "feature": "消息通知",
             "severity": "high", "impact": "影响通知主流程",
             "suggestion": "补通知需求"},
            {"feature_id": "feat_002", "feature": "审批流",
             "severity": "low", "impact": "辅助能力",
             "suggestion": "补审批需求"},
        ]},
    )
    analyses = _analyses()

    result = insights.run_gap_analysis(
        None, _doc_index(analyses), analyses, categories=[], text_model="fake")

    gaps = {g["feature"]: g for g in result["gaps"]}
    assert gaps["审批流"]["severity"] == "low"
    assert gaps["审批流"]["suggestion"] == "补审批需求"
    assert gaps["消息通知"]["severity"] == "high"
    assert gaps["消息通知"]["description"] == "影响通知主流程"
    assert result["assessment_alignment"]["method"] == "feature_id"
    assert result["assessment_alignment"]["warnings"] == []


def test_gap_assessment_missing_feature_id_falls_back_to_positional(monkeypatch):
    """模型输出缺 feature_id 时降级为位置匹配，并标注对齐方式与警告。"""
    _make_llm_router(
        monkeypatch,
        feature_extraction={"feature_dimensions": [
            {"feature_id": "feat_001", "name": "审批流", "source_doc_ids": []},
        ]},
        gap_assessment={"gap_assessments": [
            {"feature": "审批流", "severity": "medium",
             "impact": "影响部分场景", "suggestion": "补审批需求"},
        ]},
    )
    analyses = _analyses()

    result = insights.run_gap_analysis(
        None, _doc_index(analyses), analyses, categories=[], text_model="fake")

    assert result["gaps"][0]["description"] == "影响部分场景"
    assert result["assessment_alignment"]["method"] == "positional_fallback"
    assert any("降级" in w for w in result["assessment_alignment"]["warnings"])


def test_overlap_assessment_runs_when_no_gaps(monkeypatch):
    """gaps 为空时 overlap 评估不再被丢弃。"""
    calls = []
    _make_llm_router(
        monkeypatch,
        feature_extraction={"feature_dimensions": [
            {"feature_id": "feat_001", "name": "共享能力",
             "source_doc_ids": ["doc1", "doc2"]},
        ]},
        gap_assessment={"gap_assessments": [], "overlap_assessments": [
            {"feature_id": "feat_001", "feature": "共享能力",
             "overlap_type": "redundant", "note": "两篇文档重复覆盖，建议合并"},
        ]},
        calls=calls,
    )
    analyses = _analyses()

    result = insights.run_gap_analysis(
        None, _doc_index(analyses), analyses, categories=[], text_model="fake")

    assert result["gaps"] == []
    assert any("缺口评估" in c for c in calls)  # 评估确实被调用
    assert result["overlaps"][0]["note"] == "两篇文档重复覆盖，建议合并"
    assert result["assessment_alignment"]["method"] == "feature_id"
