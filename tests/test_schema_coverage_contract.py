"""全局 schema 覆盖契约：所有实际执行的 prompt 必须显式声明输出模式（review 方案第 6 点）。

背景：#3（system-review 维度）、#4/BUG-170（report-polish）、BUG-171
（requirement-insights 子步骤）是同一类事故——prompt 实际产出与无意回退加载的
skill 级 output-schema.json 结构错位，导致校验必失败。

本契约从 SkillRunner 的执行映射派生"实际会执行的 (skill_dir, prompt_name)"
全集，逐项断言 per-prompt schema 文件存在，禁止未来新增 prompt 时再次无意
回退 skill 级 schema。同时断言派生清单与期望清单一致，防止清单本身漏配。
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

from app.services.skill_runner import (  # noqa: E402
    _INSIGHT_SUB_STEPS,
    _REVIEW_DIMENSIONS,
    _SKILL_NAMES,
    SkillRunner,
)


def _executed_prompts() -> set[tuple[str, str]]:
    """从 SkillRunner 执行映射派生实际执行的 (skill_dir, prompt_name) 全集。"""
    runner = SkillRunner(
        model_cfg={"api_base": "http://example.test", "api_key": "k", "llm_model": "m"},
        skills_dir=SKILLS,
    )
    prompts = set()
    for skill_name in ("classify", "classify_version_chain", "per_analysis", "report"):
        skill_dir = _SKILL_NAMES.get(skill_name, skill_name)
        prompts.add((skill_dir, runner._prompt_name_for(skill_name)))
    for dim in _REVIEW_DIMENSIONS:
        prompts.add(("system-review", dim))
    for prompt_name, _key in _INSIGHT_SUB_STEPS:
        prompts.add(("requirement-insights", prompt_name))
    return prompts


EXPECTED_PROMPTS = {
    ("prd-overview-classify", "classify"),
    ("prd-overview-classify", "version-chain"),
    ("prd-per-analysis", "per-doc-analysis"),
    ("report-generator", "report-polish"),
    ("system-review", "business-value"),
    ("system-review", "architecture"),
    ("system-review", "competition"),
    ("system-review", "product-strategy"),
    ("system-review", "tech-evolution"),
    ("system-review", "pm-assessment"),
    ("system-review", "action-plan"),
    ("requirement-insights", "evolution-match"),
    ("requirement-insights", "feature-extraction"),
    ("requirement-insights", "gap-assessment"),
}


def test_executed_prompts_registry_is_complete():
    derived = _executed_prompts()
    assert derived == EXPECTED_PROMPTS, (
        f"执行清单与期望不一致：多出 {derived - EXPECTED_PROMPTS}，缺少 {EXPECTED_PROMPTS - derived}。"
        "新增执行 prompt 时必须同步补 per-prompt schema 并更新本清单。"
    )


@pytest.mark.parametrize("skill_dir,prompt_name", sorted(EXPECTED_PROMPTS))
def test_every_executed_prompt_has_explicit_schema_file(skill_dir, prompt_name):
    """每个执行的 prompt 必须有显式 per-prompt schema，禁止无意回退 skill 级。"""
    schema_file = SKILLS / skill_dir / "templates" / f"output-schema.{prompt_name}.json"
    assert schema_file.exists(), (
        f"{schema_file.relative_to(ROOT)} 缺失：{skill_dir}/{prompt_name} 会回退到 "
        f"skill 级 output-schema.json，重演 #3/#4/BUG-171 类校验错位。"
        "若该 prompt 产出为自由文本，也应声明显式约束（如 raw_text 必填非空）。"
    )

    from app.services.skill_schema import SkillSchemaLoader

    loader = SkillSchemaLoader(SKILLS)
    prompt_schema = loader.load(skill_dir, prompt_name)
    assert prompt_schema is not None


def test_no_pipeline_prompt_validated_against_cli_manifest_schema():
    """任何管线 prompt 的生效 schema 都不得是 generate.py 的文件清单结构
    （required=project_name/files/summary）——那是 #4 事故的直接形态。"""
    from app.services.skill_schema import SkillSchemaLoader

    loader = SkillSchemaLoader(SKILLS)
    cli_required = ["project_name", "files", "summary"]

    for skill_dir, prompt_name in EXPECTED_PROMPTS:
        schema = loader.load(skill_dir, prompt_name)
        assert schema.get("required") != cli_required, (
            f"{skill_dir}/{prompt_name} 正在被文件清单结构校验（#4 形态）"
        )
