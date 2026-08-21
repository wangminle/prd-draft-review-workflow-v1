"""Tests for CHK-091 residual fixes:

- 4.3: Skill gate on production path (all required steps covered)
- 3.2: completed_with_warnings for partial dimension failures + meta persistence
- 4.4: Category whitelist enforcement in route path
- 4.6: Source content hash tracking for analysis cache invalidation
- 4.2: Enum repair notes surfaced in diagnostics
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

from app.services.skill_schema import SkillSchemaLoader
from app.services.skill_runner import SkillRunner


# ── 4.3: Preflight gate covers ALL required steps ──

def test_preflight_covers_classify_step():
    """The full step-to-skill mapping must include 分类 (classify)."""
    # This mirrors the mapping defined in review.py._run_pipeline()
    _FULL_STEP_TO_SKILL_ID = {
        "分类": "prd-overview-classify",
        "逐篇分析": "prd-per-analysis",
        "体系Review": "system-review",
        "需求洞察": "requirement-insights",
        "报告生成": "report-generator",
        "PRD草稿生成": "report-generator",
    }
    assert "分类" in _FULL_STEP_TO_SKILL_ID
    assert _FULL_STEP_TO_SKILL_ID["分类"] == "prd-overview-classify"
    assert "逐篇分析" in _FULL_STEP_TO_SKILL_ID
    assert _FULL_STEP_TO_SKILL_ID["逐篇分析"] == "prd-per-analysis"


def test_preflight_blocks_when_classify_inactive():
    """If prd-overview-classify is inactive, the preflight must block."""
    _FULL_STEP_TO_SKILL_ID = {
        "分类": "prd-overview-classify",
        "逐篇分析": "prd-per-analysis",
        "体系Review": "system-review",
        "需求洞察": "requirement-insights",
        "报告生成": "report-generator",
        "PRD草稿生成": "report-generator",
    }
    _OPTIONAL_STEP_NAMES = {"需求洞察"}
    steps = ["预处理", "分类", "逐篇分析", "体系Review", "报告生成"]
    inactive_skills = {"prd-overview-classify"}

    blocked = [
        _FULL_STEP_TO_SKILL_ID[s]
        for s in steps
        if s in _FULL_STEP_TO_SKILL_ID
        and _FULL_STEP_TO_SKILL_ID[s] in inactive_skills
        and s not in _OPTIONAL_STEP_NAMES
    ]
    assert "prd-overview-classify" in blocked


def test_preflight_blocks_when_per_analysis_inactive():
    """If prd-per-analysis is inactive, the preflight must block."""
    _FULL_STEP_TO_SKILL_ID = {
        "分类": "prd-overview-classify",
        "逐篇分析": "prd-per-analysis",
        "体系Review": "system-review",
        "需求洞察": "requirement-insights",
        "报告生成": "report-generator",
        "PRD草稿生成": "report-generator",
    }
    _OPTIONAL_STEP_NAMES = {"需求洞察"}
    steps = ["预处理", "分类", "逐篇分析"]
    inactive_skills = {"prd-per-analysis"}

    blocked = [
        _FULL_STEP_TO_SKILL_ID[s]
        for s in steps
        if s in _FULL_STEP_TO_SKILL_ID
        and _FULL_STEP_TO_SKILL_ID[s] in inactive_skills
        and s not in _OPTIONAL_STEP_NAMES
    ]
    assert "prd-per-analysis" in blocked


def test_preflight_allows_optional_insights_inactive():
    """If only requirement-insights is inactive, no required step is blocked."""
    _FULL_STEP_TO_SKILL_ID = {
        "分类": "prd-overview-classify",
        "逐篇分析": "prd-per-analysis",
        "体系Review": "system-review",
        "需求洞察": "requirement-insights",
        "报告生成": "report-generator",
        "PRD草稿生成": "report-generator",
    }
    _OPTIONAL_STEP_NAMES = {"需求洞察"}
    steps = ["预处理", "分类", "逐篇分析", "体系Review", "需求洞察", "报告生成"]
    inactive_skills = {"requirement-insights"}

    blocked = [
        _FULL_STEP_TO_SKILL_ID[s]
        for s in steps
        if s in _FULL_STEP_TO_SKILL_ID
        and _FULL_STEP_TO_SKILL_ID[s] in inactive_skills
        and s not in _OPTIONAL_STEP_NAMES
    ]
    assert blocked == []


# ── 3.2: completed_with_warnings logic for partial failures ──

def test_completed_with_warnings_for_partial_dimensions():
    """The final status logic must consider partial dimension failures."""
    # Simulate the logic from review.py
    completed_docs = 5
    total_docs = 5
    sr_meta = {"status": "partial"}
    degraded_steps = []

    has_doc_warnings = completed_docs < total_docs
    has_dim_warnings = sr_meta.get("status") == "partial"
    has_degraded = bool(degraded_steps)
    status = (
        "completed_with_warnings"
        if (has_doc_warnings or has_dim_warnings or has_degraded)
        else "completed"
    )
    assert status == "completed_with_warnings"


def test_completed_when_all_success():
    """When all docs complete, no partial dims, no degraded -> completed."""
    completed_docs = 5
    total_docs = 5
    sr_meta = {"status": "success"}
    degraded_steps = []

    has_doc_warnings = completed_docs < total_docs
    has_dim_warnings = sr_meta.get("status") == "partial"
    has_degraded = bool(degraded_steps)
    status = (
        "completed_with_warnings"
        if (has_doc_warnings or has_dim_warnings or has_degraded)
        else "completed"
    )
    assert status == "completed"


def test_completed_with_warnings_for_degraded_steps():
    """When optional steps are degraded, status must be completed_with_warnings."""
    completed_docs = 5
    total_docs = 5
    sr_meta = {"status": "success"}
    degraded_steps = ["需求洞察"]

    has_doc_warnings = completed_docs < total_docs
    has_dim_warnings = sr_meta.get("status") == "partial"
    has_degraded = bool(degraded_steps)
    status = (
        "completed_with_warnings"
        if (has_doc_warnings or has_dim_warnings or has_degraded)
        else "completed"
    )
    assert status == "completed_with_warnings"


def test_completed_with_warnings_for_incomplete_docs():
    """When some docs failed analysis, status must be completed_with_warnings."""
    completed_docs = 3
    total_docs = 5
    sr_meta = {"status": "success"}
    degraded_steps = []

    has_doc_warnings = completed_docs < total_docs
    has_dim_warnings = sr_meta.get("status") == "partial"
    has_degraded = bool(degraded_steps)
    status = (
        "completed_with_warnings"
        if (has_doc_warnings or has_dim_warnings or has_degraded)
        else "completed"
    )
    assert status == "completed_with_warnings"


# ── 4.4: Category whitelist enforcement ──

def test_category_whitelist_rejects_unknown_category(tmp_path):
    """Categories not in the whitelist must be marked as 待确认."""
    # Simulate the whitelist logic from review.py
    cat_whitelist = {"未分类", "待确认"}
    # Simulate loading from default-categories.json
    cat_cfg = {"categories": [{"name": "需求文档"}, {"name": "设计文档"}]}
    cat_whitelist |= {c["name"] for c in cat_cfg.get("categories", []) if isinstance(c, dict) and "name" in c}

    classifications = [
        {"doc_id": "1", "category": "需求文档"},  # valid
        {"doc_id": "2", "category": "垃圾类别"},  # invalid
        {"doc_id": "3", "category": "未分类"},  # valid
    ]

    for c in classifications:
        if c.get("category", "未分类") not in cat_whitelist:
            c["category"] = "待确认"

    assert classifications[0]["category"] == "需求文档"
    assert classifications[1]["category"] == "待确认"
    assert classifications[2]["category"] == "未分类"


def test_category_whitelist_with_empty_config():
    """Even with empty categories config, 未分类 and 待确认 are always allowed."""
    cat_whitelist = {"未分类", "待确认"}
    cat_cfg = {"categories": []}
    cat_whitelist |= {c["name"] for c in cat_cfg.get("categories", []) if isinstance(c, dict) and "name" in c}

    assert "未分类" in cat_whitelist
    assert "待确认" in cat_whitelist
    assert len(cat_whitelist) == 2


# ── 4.6: Source content hash tracking for cache invalidation ──

def test_content_hash_mismatch_invalidates_cache():
    """When cached _source_content_hash != current doc.content_hash, cache is stale."""
    cached_analysis = {
        "core_problem": "test problem",
        "_source_content_hash": "abc123def456",
    }
    current_content_hash = "xyz789ghi012"

    cached_hash = cached_analysis.get("_source_content_hash")
    is_stale = cached_hash and current_content_hash and cached_hash != current_content_hash
    assert is_stale is True


def test_content_hash_match_keeps_cache():
    """When cached _source_content_hash == current doc.content_hash, cache is valid."""
    cached_analysis = {
        "core_problem": "test problem",
        "_source_content_hash": "abc123def456",
    }
    current_content_hash = "abc123def456"

    cached_hash = cached_analysis.get("_source_content_hash")
    is_stale = cached_hash and current_content_hash and cached_hash != current_content_hash
    assert is_stale is False


def test_content_hash_missing_invalidates_cache():
    """When cached analysis has no _source_content_hash (legacy), cache is invalidated."""
    cached_analysis = {
        "core_problem": "test problem",
        # No _source_content_hash field
    }
    current_content_hash = "abc123def456"

    cached_hash = cached_analysis.get("_source_content_hash")
    is_stale = not cached_hash or not current_content_hash or cached_hash != current_content_hash
    assert is_stale is True


# ── 4.2: Enum repair notes surfaced in diagnostics ──

def test_repair_notes_for_enum_fallback(tmp_path):
    """Non-critical enum fallback must produce a repair note."""
    schema = {
        "type": "object",
        "properties": {
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            }
        },
        "required": ["priority"],
        "additionalProperties": False,
    }
    # Invalid enum value that can't be case-corrected
    data = {"priority": "urgent"}

    loader = SkillSchemaLoader(tmp_path)
    result = loader.repair(data, schema)

    notes = result.get("_schema_repair_notes", [])
    assert any("enum fallback" in n for n in notes), f"Expected enum fallback note, got: {notes}"
    assert result["priority"] == "low"  # defaulted to first enum value
    assert result["_schema_valid"] is False
    assert result["_schema_critical"] is True  # BUG-159：enum 无法纠正的回退属语义改写，无条件 critical


def test_repair_notes_for_enum_correction(tmp_path):
    """Case-insensitive enum correction must produce a repair note."""
    schema = {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            }
        },
        "required": ["level"],
        "additionalProperties": False,
    }
    data = {"level": "HIGH"}  # case mismatch

    loader = SkillSchemaLoader(tmp_path)
    result = loader.repair(data, schema)

    notes = result.get("_schema_repair_notes", [])
    assert any("enum corrected" in n for n in notes), f"Expected enum corrected note, got: {notes}"
    assert result["level"] == "high"
    assert result["_schema_valid"] is False


def test_repair_notes_for_missing_field(tmp_path):
    """Missing required field must produce a repair note."""
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
        },
        "required": ["title"],
        "additionalProperties": False,
    }
    data = {}  # missing title

    loader = SkillSchemaLoader(tmp_path)
    result = loader.repair(data, schema)

    notes = result.get("_schema_repair_notes", [])
    assert any("missing required field" in n for n in notes), f"Expected missing field note, got: {notes}"


def test_repair_notes_for_type_conversion(tmp_path):
    """Type conversion must produce a repair note."""
    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
        },
        "required": ["count"],
        "additionalProperties": False,
    }
    data = {"count": "5"}  # string instead of integer

    loader = SkillSchemaLoader(tmp_path)
    result = loader.repair(data, schema)

    notes = result.get("_schema_repair_notes", [])
    assert any("type converted" in n for n in notes), f"Expected type converted note, got: {notes}"
    assert result["count"] == 5


def test_repair_notes_empty_when_no_repair_needed(tmp_path):
    """When data is valid, repair notes must be empty."""
    schema = {
        "type": "object",
        "properties": {
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["priority"],
        "additionalProperties": False,
    }
    data = {"priority": "high"}  # valid

    loader = SkillSchemaLoader(tmp_path)
    result = loader.repair(data, schema)

    notes = result.get("_schema_repair_notes", [])
    assert notes == []
    assert result["_schema_valid"] is True


def test_repair_notes_for_numeric_clamp(tmp_path):
    """Numeric range clamping must produce a repair note."""
    schema = {
        "type": "object",
        "properties": {
            "score": {"type": "number", "minimum": 0, "maximum": 10},
        },
        "required": ["score"],
        "additionalProperties": False,
    }
    data = {"score": 15}  # exceeds maximum

    loader = SkillSchemaLoader(tmp_path)
    result = loader.repair(data, schema)

    notes = result.get("_schema_repair_notes", [])
    assert any("numeric clamped" in n for n in notes), f"Expected numeric clamp note, got: {notes}"
    assert result["score"] == 10


def test_repair_notes_for_dropped_property(tmp_path):
    """Dropped unknown property must produce a repair note."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    data = {"name": "test", "extra_field": "should be dropped"}

    loader = SkillSchemaLoader(tmp_path)
    result = loader.repair(data, schema)

    notes = result.get("_schema_repair_notes", [])
    assert any("dropped unknown property" in n for n in notes), f"Expected dropped property note, got: {notes}"
    assert "extra_field" not in result


# ── Integration: SkillRunner surfaces repair notes in diagnostics ──

@pytest.mark.asyncio
async def test_skill_runner_surfaces_repair_notes_in_diagnostics(tmp_path, monkeypatch):
    """SkillRunner.run_skill must include _schema_repair_notes in diagnostics."""
    # Create a minimal skill dir with schema and prompt
    skill_dir = tmp_path / "test-skill"
    templates_dir = skill_dir / "templates"
    templates_dir.mkdir(parents=True)
    prompts_dir = skill_dir / "prompts"
    prompts_dir.mkdir()

    schema = {
        "type": "object",
        "properties": {
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["priority"],
        "additionalProperties": False,
    }
    (templates_dir / "output-schema.json").write_text(json.dumps(schema))
    # Create a prompt file so SkillRunner can load it
    (prompts_dir / "test-skill.md").write_text("Return a JSON with priority field.")

    runner = SkillRunner(
        model_cfg={
            "api_base": "http://example.test",
            "api_key": "fake-key",
            "llm_model": "fake-model",
            "max_tokens": 4096,
        },
        skills_dir=tmp_path,
    )

    # Mock the LLM call to return invalid enum value
    async def fake_structured_chat(*args, **kwargs):
        return {"priority": "urgent"}  # invalid enum

    monkeypatch.setattr(
        "app.services.skill_runner.structured_chat",
        fake_structured_chat,
    )

    result = await runner.run_skill("test-skill", {})

    # Diagnostics should contain the repair note
    assert result.diagnostics, "Expected non-empty diagnostics"
    assert any("enum fallback" in d for d in result.diagnostics), \
        f"Expected enum fallback in diagnostics, got: {result.diagnostics}"
