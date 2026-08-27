"""BUG-171：requirement-insights 三个子步骤仍使用错误的聚合 schema（review 发现，#3 同源 P0）。

evolution-match / feature-extraction / gap-assessment 均无 per-prompt schema，
_run_insight_substep_with_retry 回退加载 skill 级 output-schema.json
（required=project_name/output_type/metadata 的聚合结构），三个 prompt 的合法
扁平输出全部校验失败 → critical → 各重试 3 次返回 error → insight/full/draft
模式洞察链路不可用。

修复：补齐三份 output-schema.<prompt>.json 对齐各 prompt 扁平输出结构。
"""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SKILLS = ROOT / "skills"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.services.skill_runner import SkillRunner, _INSIGHT_SUB_STEPS  # noqa: E402
from app.services.skill_schema import SkillSchemaLoader  # noqa: E402


def _make_runner() -> SkillRunner:
    return SkillRunner(
        model_cfg={
            "api_base": "http://example.test",
            "api_key": "fake-key",
            "llm_model": "fake-model",
            "max_tokens": 4096,
        },
        skills_dir=SKILLS,
    )


def _seed_state(runner: SkillRunner) -> None:
    runner.pipeline_state["classify"] = {
        "categories": [{"name": "功能需求"}],
        "version_chains": [],
        "dependencies": [],
    }
    runner.pipeline_state["analyses"] = {
        "1": {"core_problem": "统一预约入口", "quality_score": 4, "boundary_issues": []},
    }


VALID_INSIGHT_PAYLOADS = {
    "evolution-match": {
        "matches": [
            {
                "issue_id": "issue_001",
                "issue": "跨部门审批边界未定义",
                "resolved_in": "doc2",
                "resolved_version": "V1.2",
                "status": "resolved",
                "evidence": "V1.2 明确了审批边界",
                "confidence": "high",
                "note": "",
            },
        ],
    },
    "feature-extraction": {
        "feature_dimensions": [
            {"feature_id": "feat_001", "name": "预约管理", "description": "核心预约能力", "source_doc_ids": ["doc1"], "category": "预约模块", "status": "covered"},
            {"feature_id": "feat_002", "name": "数据统计", "description": "漏斗与转化分析", "source_doc_ids": [], "category": "数据模块", "status": "gap"},
        ],
        "baseline_warning": "",
    },
    "gap-assessment": {
        "gap_assessments": [
            {"feature_id": "feat_002", "feature": "数据统计", "severity": "high", "impact": "无法量化转化", "suggestion": "补充埋点与报表需求", "priority": "high"},
        ],
        "overlap_assessments": [
            {"feature_id": "feat_001", "feature": "预约管理", "overlap_type": "evolution", "note": "V2 覆盖 V1", "action": "no_action"},
        ],
        "baseline_warning": "",
    },
}

_PROMPT_MARKERS = {
    "evolution-match": "# 跨版本边界外问题语义匹配",
    "feature-extraction": "# 功能维度提取",
    "gap-assessment": "# 缺口评估",
}


# ── schema 存在且不回退聚合 schema ──


@pytest.mark.parametrize("prompt_name,_key", _INSIGHT_SUB_STEPS)
def test_insight_substeps_load_prompt_schema_not_aggregate(prompt_name, _key):
    loader = SkillSchemaLoader(SKILLS)

    schema = loader.load("requirement-insights", prompt_name)
    assert schema is not None, f"{prompt_name} 缺少 output-schema.{prompt_name}.json"
    assert schema.get("title") != "Requirement Insights Output", prompt_name
    for field in ("project_name", "output_type", "metadata"):
        assert field not in schema.get("required", []), f"{prompt_name} 仍要求聚合顶层字段 {field}"


def test_valid_payloads_pass_first_try():
    loader = SkillSchemaLoader(SKILLS)

    for prompt_name, payload in VALID_INSIGHT_PAYLOADS.items():
        schema = loader.load("requirement-insights", prompt_name)
        errors = loader.validate(payload, schema)
        assert errors == [], f"{prompt_name} 合法 payload 校验失败: {errors}"


# ── 关键字段缺失必须判 critical ──


def test_missing_critical_fields_fail_validation():
    loader = SkillSchemaLoader(SKILLS)
    import copy

    broken_match = copy.deepcopy(VALID_INSIGHT_PAYLOADS["evolution-match"])
    del broken_match["matches"][0]["status"]
    repaired = loader.repair(broken_match, loader.load("requirement-insights", "evolution-match"))
    assert repaired["_schema_critical"] is True

    broken_feature = copy.deepcopy(VALID_INSIGHT_PAYLOADS["feature-extraction"])
    del broken_feature["feature_dimensions"][0]["feature_id"]
    repaired = loader.repair(broken_feature, loader.load("requirement-insights", "feature-extraction"))
    assert repaired["_schema_critical"] is True

    broken_gap = copy.deepcopy(VALID_INSIGHT_PAYLOADS["gap-assessment"])
    del broken_gap["gap_assessments"][0]["severity"]
    repaired = loader.repair(broken_gap, loader.load("requirement-insights", "gap-assessment"))
    assert repaired["_schema_critical"] is True


# ── 子步骤执行：首验通过零重试 / 完整洞察链路 ──


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_name,_key", _INSIGHT_SUB_STEPS)
async def test_insight_substep_calls_llm_once_on_valid_output(monkeypatch, prompt_name, _key):
    import app.services.skill_runner as skill_runner_module

    runner = _make_runner()
    _seed_state(runner)

    calls = []

    async def fake_structured_chat(messages, **kwargs):
        calls.append(1)
        return VALID_INSIGHT_PAYLOADS[prompt_name]

    monkeypatch.setattr(skill_runner_module, "structured_chat", fake_structured_chat)

    result = await runner._run_insight_substep_with_retry(
        prompt_name, runner._build_insight_inputs(prompt_name, {})
    )

    assert len(calls) == 1, f"{prompt_name} 应首次校验即通过，实际调用 LLM {len(calls)} 次"
    assert not result.get("error"), result.get("error")
    assert "_schema_valid" not in result or result["_schema_valid"] is not False


@pytest.mark.asyncio
async def test_full_insights_chain_records_all_success(monkeypatch):
    """完整洞察链路：3 个子步骤全部成功，不再出现回退校验导致的 error。"""
    import app.services.skill_runner as skill_runner_module

    runner = _make_runner()
    _seed_state(runner)

    async def fake_structured_chat(messages, **kwargs):
        user_content = messages[-1]["content"]
        for prompt_name, marker in _PROMPT_MARKERS.items():
            if marker in user_content:
                return VALID_INSIGHT_PAYLOADS[prompt_name]
        raise AssertionError(f"无法识别 insights prompt: {user_content[:80]}")

    monkeypatch.setattr(skill_runner_module, "structured_chat", fake_structured_chat)

    await runner._run_insights()

    meta = runner.pipeline_state["insights_meta"]
    assert meta["sub_step_status"] == {
        "evolution-match": "success",
        "feature-extraction": "success",
        "gap-assessment": "success",
    }
    # 下游消费键齐全
    insights = runner.pipeline_state["insights"]
    assert insights["evolution"]["matches"][0]["issue_id"] == "issue_001"
    assert insights["features"]["feature_dimensions"][0]["feature_id"] == "feat_001"
    assert insights["gap"]["gap_assessments"][0]["severity"] == "high"


@pytest.mark.asyncio
async def test_broken_gap_output_fails_after_retries(monkeypatch):
    """缺 severity 的 gap 输出按失败处理（重试耗尽后报错），不得静默放行。"""
    import asyncio
    import copy

    import app.services.skill_runner as skill_runner_module

    runner = _make_runner()
    _seed_state(runner)

    broken = copy.deepcopy(VALID_INSIGHT_PAYLOADS["gap-assessment"])
    del broken["gap_assessments"][0]["severity"]

    calls = []

    async def fake_structured_chat(messages, **kwargs):
        calls.append(1)
        return broken

    async def fast_sleep(_delay):
        return None

    monkeypatch.setattr(skill_runner_module, "structured_chat", fake_structured_chat)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    result = await runner._run_insight_substep_with_retry(
        "gap-assessment", runner._build_insight_inputs("gap-assessment", {})
    )

    assert result.get("error"), "缺 severity 的结果不得被当作成功"
    assert len(calls) == runner.step_max_retries
