#!/usr/bin/env python3
"""P2-5.2 测试：competition.md 输出 schema 强制 source 标签。"""
from __future__ import annotations

import json
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "skills" / "system-review" / "templates" / "output-schema.json"


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _competition_schema():
    schema = _load_schema()
    return schema["properties"]["dimensions"]["properties"]["competition"]


class TestCompetitionSchema:
    def test_schema_loads(self):
        s = _load_schema()
        assert isinstance(s, dict)

    def test_competition_has_required_market_landscape(self):
        comp = _competition_schema()
        assert "market_landscape" in comp["required"]

    def test_market_landscape_requires_has_competition_data(self):
        comp = _competition_schema()
        ml = comp["properties"]["market_landscape"]
        assert "has_competition_data" in ml["required"]

    def test_key_players_have_source_tag(self):
        comp = _competition_schema()
        kp_item = comp["properties"]["market_landscape"]["properties"]["key_players"]["items"]
        assert "source" in kp_item["required"]
        assert kp_item["properties"]["source"]["enum"] == ["input_evidence", "industry_template", "model_inference"]

    def test_competitors_have_source_tag(self):
        comp = _competition_schema()
        comp_item = comp["properties"]["competitor_comparison"]["items"]
        comp_item_competitor = comp_item["properties"]["competitors"]["items"]
        assert "source" in comp_item_competitor["required"]
        assert "confidence" in comp_item_competitor["required"]

    def test_open_questions_field_exists(self):
        comp = _competition_schema()
        assert "open_questions" in comp["properties"]
        assert comp["properties"]["open_questions"]["type"] == "array"


class TestCompetitionPrompt:
    """验证 prompt 文件中的 source 分级规则。"""

    PROMPT_PATH = Path(__file__).resolve().parent.parent / "skills" / "system-review" / "prompts" / "competition.md"

    def test_prompt_has_source_taxonomy(self):
        content = self.PROMPT_PATH.read_text(encoding="utf-8")
        assert "input_evidence" in content
        assert "industry_template" in content
        assert "model_inference" in content

    def test_prompt_has_no_competition_data_rule(self):
        content = self.PROMPT_PATH.read_text(encoding="utf-8")
        # 没有竞品资料时必须只输出框架
        assert "competition_references" in content
        assert "待调研" in content or "open_questions" in content

    def test_prompt_model_inference_must_be_low_confidence(self):
        content = self.PROMPT_PATH.read_text(encoding="utf-8")
        assert 'confidence: "low"' in content or "model_inference" in content

    def test_prompt_has_open_questions_field(self):
        content = self.PROMPT_PATH.read_text(encoding="utf-8")
        assert "open_questions" in content
