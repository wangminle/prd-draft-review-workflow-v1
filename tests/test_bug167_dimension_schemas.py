"""BUG-167 / GitHub Issue #3：系统评审维度结果被完整报告 schema 校验必失败。

根因：system-review 7 个维度 prompt 只有一份 skill 级 output-schema.json
（完整报告结构，顶层 required = project_name/output_type/dimensions/metadata），
SkillSchemaLoader 找不到 per-prompt schema 时回退到它，维度扁平 payload 必然
校验失败 → output_type 枚举回填触发 critical → 3 次无效重试 → 维度全错。

修复：新增 7 份 output-schema.<dimension>.json 对齐各 prompt 扁平输出结构。
本文件锁定：
  1. 7 个维度各自加载到维度 schema，不再回退完整报告 schema；
  2. 合法维度结果首次校验即通过（structured_chat 只调用 1 次，无重试）；
  3. 缺少评分/证据等关键字段时仍能报错（critical 修复不得静默放行）；
  4. 完整系统评审 7 维度全部成功，review_dimensions_meta.success_count == 7。
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

from app.services.skill_runner import SkillRunner, _REVIEW_DIMENSIONS  # noqa: E402
from app.services.skill_schema import SkillSchemaLoader  # noqa: E402


FULL_REPORT_TOP_FIELDS = ("project_name", "output_type", "dimensions", "metadata")


def _score(value: int, evidence: str) -> dict:
    return {"score": value, "evidence": evidence}


VALID_DIMENSION_PAYLOADS: dict[str, dict] = {
    "business-value": {
        "strategic_value": {
            "user_value": _score(4, "解决统一预约痛点（doc1）"),
            "tech_barrier": _score(3, "端云协同有门槛（doc2）"),
            "market_scale": _score(4, "覆盖智能家居细分市场（doc1）"),
            "strategic_synergy": _score(3, "与公司战略部分协同（doc3）"),
            "feasibility": _score(4, "技术成熟、资源可获取（doc2）"),
        },
        "business_goals": [
            {"goal": "统一多端预约入口", "coverage": "high", "gap": "多端文案不一致", "evidence": "doc1"},
            {"goal": "提升预约转化率", "coverage": "medium", "gap": "缺少转化埋点", "evidence": "doc2"},
        ],
        "user_insights": [
            {"insight": "用户期望一站式预约", "source_doc_ids": ["doc1"], "confidence": "high"},
            {"insight": "对响应延迟敏感", "source_doc_ids": ["doc2"], "confidence": "medium"},
            {"insight": "重视历史记录可追溯", "source_doc_ids": ["doc1"], "confidence": "high"},
        ],
    },
    "architecture": {
        "evolution_stages": [
            {"stage": "起步期", "versions": ["V1.0", "V1.2"], "core_problems": ["预约入口分散"], "key_solutions": ["统一 H5 入口"]},
        ],
        "category_assessment": [
            {"category": "功能需求", "doc_count": 5, "assessment": "合理", "note": "归属清晰"},
        ],
        "dependency_issues": [
            {"type": "cross_category", "description": "预约依赖账号能力", "severity": "medium", "involved_docs": ["doc1", "doc4"]},
        ],
        "architecture_gaps": [
            {"type": "coverage_gap", "description": "数据统计域无文档", "suggestion": "补充数据需求文档"},
            {"type": "redundancy", "description": "doc2 与 doc3 内容重叠", "suggestion": "合并为版本链"},
        ],
    },
    "competition": {
        "market_landscape": {
            "position": "following",
            "key_players": [],
            "tech_route_difference": "竞品以云端调度为主，本方案端云协同",
            "has_competition_data": False,
        },
        "competitor_comparison": [
            {"dimension": "功能覆盖", "us": "覆盖预约全流程", "competitors": []},
        ],
        "differentiation": {
            "unique_strengths": [
                {"item": "统一多端入口", "source": "input_evidence", "confidence": "high"},
                {"item": "本地优先执行", "source": "model_inference", "confidence": "low"},
            ],
            "weaknesses": [
                {"item": "缺少数据闭环", "source": "model_inference", "confidence": "low"},
            ],
            "opportunities": [
                {"item": "跨设备场景协同", "source": "model_inference", "confidence": "low"},
            ],
        },
        "open_questions": ["主要竞品的预约并发方案与定价"],
    },
    "product-strategy": {
        "current_strategy_assessment": {
            "prioritization": "基本合理",
            "focus": "聚焦",
            "consistency": "偶有摇摆",
            "evidence": "doc1 优先级清晰，doc4 方向有一次反复",
        },
        "recommendations": [
            {"recommendation": "收敛预约入口", "targets": "业务目标：统一入口", "reasoning": "前置维度发现入口分散", "expected_impact": "转化率提升", "priority": "high"},
            {"recommendation": "补齐数据埋点", "targets": "竞争短板：数据闭环", "reasoning": "无法量化当前转化", "expected_impact": "漏斗可度量", "priority": "high"},
            {"recommendation": "统一多端文案", "targets": "业务目标：提升转化", "reasoning": "文案不一致影响信任", "expected_impact": "降低咨询量", "priority": "medium"},
        ],
        "roadmap": [
            {"period": "Q1", "items": [{"action": "合并 H5/App 入口", "category": "功能", "depends_on": []}]},
            {"period": "Q2", "items": [{"action": "建设埋点体系", "category": "数据", "depends_on": ["合并 H5/App 入口"]}]},
            {"period": "Q3-Q4", "items": [{"action": "跨设备协同一期", "category": "体验", "depends_on": ["建设埋点体系"]}]},
        ],
    },
    "tech-evolution": {
        "current_architecture": {
            "pattern": "端云协同",
            "core_decisions": [
                {"decision": "本地优先执行、云端兜底", "assessment": "合理", "risk": "双端状态同步冲突"},
            ],
        },
        "key_metrics": [
            {"name": "预约响应延迟", "value": "<200ms", "source_doc_ids": ["doc2"]},
        ],
        "tech_evolution": {
            "trend": "逐步完善",
            "tech_debt": [
                {"item": "临时缓存无过期策略", "severity": "medium", "suggestion": "引入 TTL 与容量上限"},
            ],
            "alignment_with_strategy": "一致",
        },
        "evolution_recommendations": [
            {"action": "升级同步协议", "reason": "降低双端冲突率", "priority": "medium"},
        ],
    },
    "pm-assessment": {
        "writing_scores": {
            "logic": _score(4, "每个需求有状态机与判定规则（doc1）"),
            "tech_depth": _score(3, "SDK 版本描述正确但缺参数（doc2）"),
            "boundary": _score(3, "部分文档写了不涉及（doc3）"),
            "business": _score(2, "只有定性描述无量化（doc1）"),
        },
        "thinking_scores": {
            "iteration": _score(4, "V1→V2 问题演进链清晰"),
            "experience": _score(3, "交互从用户认知出发（doc2）"),
            "data": _score(2, "无效果评估方案"),
            "business": _score(2, "无商业闭环设计"),
        },
        "pm_type": "技术型",
        "highlights": ["逻辑结构完整", "技术描述准确", "演进链清晰"],
        "blindspots": ["缺少商业量化", "缺数据评估方案", "边界定义不全"],
        "growth_path": {
            "short_term": ["补齐每篇文档的适用范围"],
            "mid_term": ["为核心场景建立数据指标"],
            "long_term": ["建立商业闭环评估机制"],
        },
    },
    "action-plan": {
        "short_term": [
            {"action": "统一五端预约文案", "source_dimension": "business_value", "urgency_reason": "直接影响转化", "success_criteria": "五端文案一致", "priority": "high"},
        ],
        "mid_term": [
            {"action": "建设预约漏斗埋点", "source_dimension": "product_strategy", "reason": "支撑效果评估", "success_criteria": "核心漏斗可量化", "priority": "medium"},
        ],
        "long_term": [
            {"action": "预约能力平台化", "source_dimension": "architecture", "reason": "复用核心能力", "success_criteria": "新场景接入成本减半", "priority": "low"},
        ],
        "milestones": [
            {"time": "1个月", "goal": "入口与文案统一", "depends_on": []},
            {"time": "3个月", "goal": "数据闭环可用", "depends_on": ["入口与文案统一"]},
            {"time": "6个月", "goal": "平台化一期", "depends_on": ["数据闭环可用"]},
        ],
        "risks": [
            {"risk": "多团队协调延期", "impact": "high", "likelihood": "medium", "mitigation": "建立跨团队周会"},
            {"risk": "数据合规审查", "impact": "medium", "likelihood": "low", "mitigation": "法务前置评审"},
        ],
    },
}

# user prompt 标题行中的维度标题，用于 fake LLM 分发（必须带标题名，
# 避免命中 pm-assessment 正文中“每维度1-5分”这类子串）
_DIMENSION_MARKERS = {
    "business-value": "维度1：业务价值分析",
    "architecture": "维度2：需求体系架构分析",
    "competition": "维度3：品牌与竞争定位分析",
    "product-strategy": "维度4：产品策略评估",
    "tech-evolution": "维度5：技术架构演进分析",
    "pm-assessment": "维度6：PM能力评估",
    "action-plan": "维度7：行动计划与优先级",
}


def _make_real_skills_runner() -> SkillRunner:
    return SkillRunner(
        model_cfg={
            "api_base": "http://example.test",
            "api_key": "fake-key",
            "llm_model": "fake-model",
            "max_tokens": 4096,
        },
        skills_dir=SKILLS,
    )


def _seed_pipeline_state(runner: SkillRunner) -> None:
    runner.pipeline_state["classify"] = {
        "categories": [{"name": "功能需求"}],
        "version_chains": [],
        "dependencies": [],
    }
    runner.pipeline_state["analyses"] = {
        "1": {"core_problem": "统一预约入口", "quality_score": 4},
    }
    runner.pipeline_state["docs"] = [
        {"doc_id": "1", "filename": "预约需求.docx", "md_content": "统一多端预约入口……"},
    ]


# ── 1. 维度 schema 存在且不回退完整报告 schema ──


def test_all_seven_dimensions_load_prompt_specific_schema():
    loader = SkillSchemaLoader(SKILLS)

    for dim_name in _REVIEW_DIMENSIONS:
        schema = loader.load("system-review", dim_name)
        assert schema is not None, f"{dim_name} 缺少 output-schema.{dim_name}.json"
        assert schema.get("title") != "System Review Output", dim_name
        required = schema.get("required", [])
        for field in FULL_REPORT_TOP_FIELDS:
            assert field not in required, f"{dim_name} schema 仍要求完整报告顶层字段 {field}"
            assert field not in schema.get("properties", {}), f"{dim_name} schema 声明了完整报告字段 {field}"


# ── 2. 合法维度 payload 首次校验即通过 ──


def test_valid_dimension_payloads_pass_validation_first_try():
    loader = SkillSchemaLoader(SKILLS)

    for dim_name, payload in VALID_DIMENSION_PAYLOADS.items():
        schema = loader.load("system-review", dim_name)
        errors = loader.validate(payload, schema)
        assert errors == [], f"{dim_name} 合法 payload 校验失败: {errors}"


@pytest.mark.asyncio
@pytest.mark.parametrize("dim_name", _REVIEW_DIMENSIONS)
async def test_dimension_retry_loop_calls_llm_once_on_valid_output(tmp_path, monkeypatch, dim_name):
    """Issue #3 核心：合法维度结果不应触发 3 次无效重试。"""
    import app.services.skill_runner as skill_runner_module

    runner = _make_real_skills_runner()
    _seed_pipeline_state(runner)

    calls = []

    async def fake_structured_chat(messages, **kwargs):
        calls.append(messages)
        return VALID_DIMENSION_PAYLOADS[dim_name]

    monkeypatch.setattr(skill_runner_module, "structured_chat", fake_structured_chat)

    result = await runner._run_dimension_with_retry(dim_name, runner._build_dimension_inputs(dim_name, {}))

    assert len(calls) == 1, f"{dim_name} 应首次校验即通过，实际调用 LLM {len(calls)} 次"
    assert not result.get("error"), result.get("error")
    assert result == VALID_DIMENSION_PAYLOADS[dim_name] or all(
        result.get(k) == v for k, v in VALID_DIMENSION_PAYLOADS[dim_name].items()
    )


@pytest.mark.asyncio
async def test_dimension_missing_score_triggers_retry_then_error(monkeypatch):
    """缺 score 属于 critical 修复：维度必须按失败处理（重试后报错）。"""
    import asyncio

    import app.services.skill_runner as skill_runner_module

    runner = _make_real_skills_runner()
    _seed_pipeline_state(runner)

    broken = {
        "strategic_value": {
            "user_value": {"evidence": "缺分数"},
            "tech_barrier": _score(3, "有门槛"),
            "market_scale": _score(4, "细分市场"),
            "strategic_synergy": _score(3, "部分协同"),
            "feasibility": _score(4, "技术成熟"),
        },
        "business_goals": VALID_DIMENSION_PAYLOADS["business-value"]["business_goals"],
        "user_insights": VALID_DIMENSION_PAYLOADS["business-value"]["user_insights"],
    }

    calls = []

    async def fake_structured_chat(messages, **kwargs):
        calls.append(1)
        return broken

    monkeypatch.setattr(skill_runner_module, "structured_chat", fake_structured_chat)
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    result = await runner._run_dimension_with_retry(
        "business-value", runner._build_dimension_inputs("business-value", {})
    )

    assert result.get("error"), "缺 score 的维度结果不得被当作成功"
    assert len(calls) == runner.step_max_retries


async def _fast_sleep(_delay):
    return None


# ── 3. 关键字段缺失仍能被 schema 拦截 ──


def test_missing_score_and_evidence_are_reported_by_dimension_schema():
    loader = SkillSchemaLoader(SKILLS)
    schema = loader.load("system-review", "business-value")

    missing_score = {
        "strategic_value": {
            "user_value": {"evidence": "只有证据没有分"},
            "tech_barrier": _score(3, "有门槛"),
            "market_scale": _score(4, "细分市场"),
            "strategic_synergy": _score(3, "部分协同"),
            "feasibility": _score(4, "技术成熟"),
        },
        "business_goals": [
            {"goal": "统一入口", "coverage": "high", "evidence": "doc1"},
            {"goal": "提升转化", "coverage": "medium", "evidence": "doc2"},
        ],
        "user_insights": [
            {"insight": "一站式", "source_doc_ids": ["doc1"], "confidence": "high"},
            {"insight": "低延迟", "source_doc_ids": ["doc2"], "confidence": "medium"},
            {"insight": "可追溯", "source_doc_ids": ["doc1"], "confidence": "high"},
        ],
    }
    errors = loader.validate(missing_score, schema)
    assert any("score" in err for err in errors), errors
    repaired = loader.repair(missing_score, schema)
    assert repaired["_schema_critical"] is True, "缺 score 必须标记 critical，不得静默放行"

    missing_evidence = {
        "strategic_value": {
            "user_value": {"score": 4},
            "tech_barrier": _score(3, "有门槛"),
            "market_scale": _score(4, "细分市场"),
            "strategic_synergy": _score(3, "部分协同"),
            "feasibility": _score(4, "技术成熟"),
        },
        "business_goals": [
            {"goal": "统一入口", "coverage": "high", "evidence": "doc1"},
            {"goal": "提升转化", "coverage": "medium", "evidence": "doc2"},
        ],
        "user_insights": [
            {"insight": "一站式", "source_doc_ids": ["doc1"], "confidence": "high"},
            {"insight": "低延迟", "source_doc_ids": ["doc2"], "confidence": "medium"},
            {"insight": "可追溯", "source_doc_ids": ["doc1"], "confidence": "high"},
        ],
    }
    errors = loader.validate(missing_evidence, schema)
    assert any("evidence" in err for err in errors), errors


def test_out_of_range_score_fails_validation():
    loader = SkillSchemaLoader(SKILLS)
    schema = loader.load("system-review", "pm-assessment")

    payload = {
        "writing_scores": {
            "logic": {"score": 9, "evidence": "越界分"},
            "tech_depth": _score(3, "基本正确"),
            "boundary": _score(3, "部分有边界"),
            "business": _score(2, "缺量化"),
        },
        "thinking_scores": VALID_DIMENSION_PAYLOADS["pm-assessment"]["thinking_scores"],
        "pm_type": "技术型",
        "highlights": ["结构清晰", "演进完整", "技术准确"],
        "blindspots": ["缺商业量化", "缺数据方案", "边界不全"],
        "growth_path": {"short_term": ["补边界"], "mid_term": ["补指标"], "long_term": ["建闭环"]},
    }
    errors = loader.validate(payload, schema)
    assert any("maximum" in err for err in errors), errors


# ── 4. 完整系统评审 success_count == 7 ──


@pytest.mark.asyncio
async def test_full_system_review_records_success_count_seven(monkeypatch):
    import app.services.skill_runner as skill_runner_module

    runner = _make_real_skills_runner()
    _seed_pipeline_state(runner)

    async def fake_structured_chat(messages, **kwargs):
        user_content = messages[-1]["content"]
        for dim_name, marker in _DIMENSION_MARKERS.items():
            if marker in user_content:
                return VALID_DIMENSION_PAYLOADS[dim_name]
        raise AssertionError(f"无法识别维度 prompt: {user_content[:80]}")

    monkeypatch.setattr(skill_runner_module, "structured_chat", fake_structured_chat)

    cancelled = await runner._run_system_review()

    assert cancelled is False
    meta = runner.pipeline_state["review_dimensions_meta"]
    assert meta["success_count"] == 7
    assert meta["failed_count"] == 0
    assert meta["status"] == "success"
    assert meta["dimensions_executed"] == _REVIEW_DIMENSIONS
    # 各维度结果保留完整扁平结构（未被误解包/误修复）
    assert runner.pipeline_state["review_dimensions"]["tech-evolution"]["current_architecture"]["pattern"] == "端云协同"
    assert runner.pipeline_state["review_dimensions"]["action-plan"]["milestones"][0]["time"] == "1个月"
