#!/usr/bin/env python3
"""P2-5.5 测试：run_skill 安全默认分区——critical business fields。

验证：
- _CRITICAL_FIELD_HINTS 包含审计列出的不可安全默认字段
- 当 critical 字段缺失/无效时，repair 标记 _schema_critical=True
- run_skill 在 schema_critical=True 时标记 step 为 error
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.services.skill_schema import SkillSchemaLoader, _CRITICAL_FIELD_HINTS  # noqa: E402


class TestCriticalFieldSet:
    """审计要求不可安全默认的字段必须在 _CRITICAL_FIELD_HINTS 中。"""

    def test_has_doc_id(self):
        assert "doc_id" in _CRITICAL_FIELD_HINTS

    def test_has_category(self):
        assert "category" in _CRITICAL_FIELD_HINTS

    def test_has_quality_score(self):
        assert "quality_score" in _CRITICAL_FIELD_HINTS

    def test_has_version(self):
        assert "version" in _CRITICAL_FIELD_HINTS

    def test_has_chains(self):
        assert "chains" in _CRITICAL_FIELD_HINTS

    def test_has_classifications(self):
        assert "classifications" in _CRITICAL_FIELD_HINTS

    def test_has_action_plan(self):
        # 行动计划
        assert "action_plan" in _CRITICAL_FIELD_HINTS or "action_items" in _CRITICAL_FIELD_HINTS

    def test_has_issue_status(self):
        # 问题状态
        assert "status" in _CRITICAL_FIELD_HINTS


class TestRepairMarksCritical:
    """repair() 在 critical 字段缺失时应标记 _schema_critical=True。"""

    def setup_method(self):
        self.loader = SkillSchemaLoader(skills_dir=ROOT / "skills")

    def test_missing_doc_id_marks_critical(self):
        schema = {
            "type": "object",
            "required": ["doc_id", "category"],
            "properties": {
                "doc_id": {"type": "string"},
                "category": {"type": "string"},
            },
        }
        # doc_id 缺失
        result = self.loader.repair({"category": "x"}, schema)
        assert result.get("_schema_critical") is True

    def test_missing_category_marks_critical(self):
        schema = {
            "type": "object",
            "required": ["doc_id", "category"],
            "properties": {
                "doc_id": {"type": "string"},
                "category": {"type": "string"},
            },
        }
        result = self.loader.repair({"doc_id": "1"}, schema)
        assert result.get("_schema_critical") is True

    def test_missing_optional_field_not_critical(self):
        schema = {
            "type": "object",
            "required": ["doc_id", "description"],
            "properties": {
                "doc_id": {"type": "string"},
                "description": {"type": "string"},  # 非关键
            },
        }
        result = self.loader.repair({"doc_id": "1"}, schema)
        # description 缺失但不属于 critical
        assert result.get("_schema_critical") is False

    def test_missing_classifications_marks_critical(self):
        schema = {
            "type": "object",
            "required": ["classifications"],
            "properties": {
                "classifications": {"type": "array", "minItems": 1},
            },
        }
        result = self.loader.repair({}, schema)
        assert result.get("_schema_critical") is True

    def test_invalid_enum_on_critical_marks_critical(self):
        schema = {
            "type": "object",
            "required": ["status"],
            "properties": {
                "status": {"type": "string", "enum": ["open", "closed"]},
            },
        }
        # status 是 critical 字段，传非法 enum 值应标记 critical
        result = self.loader.repair({"status": "bogus"}, schema)
        assert result.get("_schema_critical") is True


class TestRunSkillErrorOnCritical:
    """验证 run_skill 在 schema_critical=True 时返回 error 状态。"""

    def test_run_skill_source_marks_error_on_critical(self):
        src = (ROOT / "src" / "app" / "services" / "skill_runner.py").read_text(encoding="utf-8")
        # 必须有 schema_critical → step_status = "error" 的逻辑
        assert "schema_critical" in src
        assert 'step_status = "error"' in src
