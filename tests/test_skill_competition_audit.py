#!/usr/bin/env python3
"""P2-5.2 测试：competition.md 输出 schema 强制 source 标签。"""
from __future__ import annotations

import json
import sys
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "skills" / "system-review" / "templates" / "output-schema.json"

REVIEW_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "system-review" / "scripts"
if str(REVIEW_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(REVIEW_SCRIPTS_DIR))

import review  # noqa: E402


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


class TestCompetitionModelCompat:
    """BUG-162：pydantic 模型兼容字符串与 dict 两种形态。"""

    def test_market_landscape_accepts_string_players(self):
        ml = review.MarketLandscape(key_players=["竞品X", "竞品Y"])
        assert ml.key_players == ["竞品X", "竞品Y"]

    def test_market_landscape_accepts_dict_players(self):
        ml = review.MarketLandscape(key_players=[
            {"name": "竞品A", "source": "industry_template", "confidence": "medium"},
        ])
        assert ml.key_players[0]["name"] == "竞品A"

    def test_differentiation_accepts_dict_items(self):
        diff = review.Differentiation(unique_strengths=[
            {"item": "全流程闭环", "source": "input_evidence", "confidence": "high"},
        ])
        assert diff.unique_strengths[0]["item"] == "全流程闭环"

    def test_competition_result_has_open_questions(self):
        result = review.CompetitionResult(open_questions=["头部竞品有哪些？"])
        assert result.open_questions == ["头部竞品有哪些？"]


class TestCompetitionRendering:
    """BUG-162：generate_full_report_md 渲染新结构（dict + source/confidence）。"""

    def _render(self, competition: dict) -> str:
        return review.generate_full_report_md({"competition": competition}, "测试项目")

    def test_dict_key_players_render_source_and_confidence(self):
        md = self._render({
            "market_landscape": {
                "position": "following",
                "has_competition_data": True,
                "key_players": [
                    {"name": "竞品A", "source": "industry_template", "confidence": "medium"},
                ],
            },
        })
        assert "竞品A（来源：行业模板 · 置信度：中）" in md
        # 不得把 dict repr 渲染进 Markdown
        assert "'name'" not in md

    def test_string_key_players_backward_compatible(self):
        md = self._render({
            "market_landscape": {
                "position": "exploring",
                "key_players": ["竞品X", "竞品Y"],
            },
        })
        # 纯字符串列表渲染不变
        assert "主要玩家：竞品X, 竞品Y" in md
        assert "待调研问题" not in md

    def test_dict_differentiation_rendered_with_labels(self):
        md = self._render({
            "differentiation": {
                "unique_strengths": [
                    {"item": "全流程闭环", "source": "input_evidence", "confidence": "high"},
                ],
                "weaknesses": ["品牌知名度低"],
            },
        })
        assert "- 💪 优势：全流程闭环（来源：输入证据 · 置信度：高）" in md
        assert "- ⚠️ 短板：品牌知名度低" in md
        assert "'item'" not in md

    def test_open_questions_rendered_when_present(self):
        md = self._render({
            "market_landscape": {"position": "exploring", "has_competition_data": False},
            "open_questions": ["目标行业的头部竞品有哪些？"],
        })
        assert "### 待调研问题" in md
        assert "- 目标行业的头部竞品有哪些？" in md

    def test_open_questions_absent_when_empty(self):
        md = self._render({
            "market_landscape": {"position": "exploring", "key_players": ["竞品X"]},
        })
        assert "待调研问题" not in md
