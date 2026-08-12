"""Tests for P1-4.3: SkillConfig.status gate must actually block execution."""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.services.skill_runner import (
    SkillRunner,
    SkillStepResult,
    SkillInactiveError,
    _REQUIRED_STEPS,
    _OPTIONAL_STEPS,
)


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


@pytest.mark.asyncio
async def test_required_skill_inactive_blocks_pipeline_start(tmp_path):
    """If a required Skill is in the inactive set, run_pipeline must raise."""
    runner = _make_runner(tmp_path)

    async def fake_run_per_analysis(*args, **kwargs):
        return False

    monkeypatch_target = "app.services.skill_runner.SkillRunner._run_per_analysis"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(monkeypatch_target, fake_run_per_analysis)
        with pytest.raises(SkillInactiveError) as exc_info:
            await runner.run_pipeline(
                "review",
                {
                    "docs": [],
                    "inactive_skills": ["prd-per-analysis"],  # required Skill
                },
            )
        assert "prd-per-analysis" in str(exc_info.value)


@pytest.mark.asyncio
async def test_optional_skill_inactive_runs_degraded(tmp_path, monkeypatch):
    """If an optional Skill (requirement-insights) is inactive, pipeline
    runs in degraded mode and records the skipped step.
    """
    runner = _make_runner(tmp_path)

    calls = []

    async def fake_per_analysis(*args, **kwargs):
        calls.append("per_analysis")
        return False

    async def fake_system_review(*args, **kwargs):
        calls.append("system_review")
        return False

    async def fake_run_skill_with_retry(skill_name, inputs):
        calls.append(skill_name)
        return SkillStepResult(data={"markdown": "ok"})

    monkeypatch.setattr(runner, "_run_per_analysis", fake_per_analysis)
    monkeypatch.setattr(runner, "_run_system_review", fake_system_review)
    monkeypatch.setattr(runner, "run_skill_with_retry", fake_run_skill_with_retry)

    await runner.run_pipeline(
        "insight",
        {
            "docs": [{"doc_id": "1", "md_content": "x", "filename": "a"}],
            "inactive_skills": ["requirement-insights"],  # optional Skill
        },
    )

    # insights step should NOT be called — it was skipped
    assert "insights" not in calls
    assert runner.state.get("degraded_steps")
    assert "insights" in runner.state["degraded_steps"]


@pytest.mark.asyncio
async def test_no_inactive_skills_runs_normally(tmp_path, monkeypatch):
    """When inactive_skills is empty/missing, pipeline behaves normally."""
    runner = _make_runner(tmp_path)

    calls = []

    async def fake_per_analysis(*args, **kwargs):
        calls.append("per_analysis")
        return False

    async def fake_run_skill_with_retry(skill_name, inputs):
        calls.append(skill_name)
        return SkillStepResult(data={"markdown": "ok"})

    monkeypatch.setattr(runner, "_run_per_analysis", fake_per_analysis)
    monkeypatch.setattr(runner, "run_skill_with_retry", fake_run_skill_with_retry)

    await runner.run_pipeline("quick", {"docs": [{"doc_id": "1", "md_content": "x", "filename": "a"}]})

    assert "per_analysis" in calls
    assert not runner.state.get("degraded_steps")


def test_required_vs_optional_steps_classified_correctly():
    """Required steps cannot be skipped; optional steps can."""
    assert "classify" in _REQUIRED_STEPS
    assert "per_analysis" in _REQUIRED_STEPS
    assert "system_review" in _REQUIRED_STEPS
    assert "report" in _REQUIRED_STEPS
    assert "insights" in _OPTIONAL_STEPS
    assert "insights" not in _REQUIRED_STEPS


@pytest.mark.asyncio
async def test_preflight_blocks_multiple_required_inactive(tmp_path):
    runner = _make_runner(tmp_path)
    with pytest.raises(SkillInactiveError) as exc_info:
        runner._preflight_skill_gate(
            ["classify", "per_analysis", "system_review", "report"],
            inactive_skills={"prd-overview-classify", "system-review"},
        )
    msg = str(exc_info.value)
    assert "prd-overview-classify" in msg
    assert "system-review" in msg


@pytest.mark.asyncio
async def test_preflight_allows_optional_inactive(tmp_path):
    """Optional Skills inactive should not raise from preflight."""
    runner = _make_runner(tmp_path)
    # Should not raise
    runner._preflight_skill_gate(
        ["classify", "per_analysis", "system_review", "insights", "report"],
        inactive_skills={"requirement-insights"},
    )
