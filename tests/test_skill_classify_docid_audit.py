#!/usr/bin/env python3
"""P2-5.4 测试：classify doc_id 统一为 DB 主键，移除文件名回退。"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "app"
if str(SRC.parent.parent) not in sys.path:
    sys.path.insert(0, str(SRC.parent.parent))

SKILLS_DIR = ROOT / "skills"
SCRIPTS_DIR = SKILLS_DIR / "prd-overview-classify" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class TestClassifyInputUsesDbId:
    def test_build_classify_inputs_includes_db_id(self):
        """_build_classify_inputs 应在 excerpt 中包含 DB id。"""
        from app.services.skill_runner import SkillRunner

        runner = SkillRunner.__new__(SkillRunner)
        runner.skills_dir = SKILLS_DIR
        runner.context = {}
        state = {
            "docs": [
                {"id": 42, "filename": "alpha.md", "md_content": "alpha content"},
                {"id": 77, "filename": "beta.md", "md_content": "beta content"},
            ]
        }
        inputs = runner._build_classify_inputs(state)
        excerpts = inputs["doc_titles_and_excerpts"]
        # DB id 必须出现在输入中
        assert "[42]" in excerpts
        assert "[77]" in excerpts
        # 文件名仍作为展示
        assert "alpha.md" in excerpts

    def test_build_classify_inputs_no_db_id_falls_back(self):
        """没有 DB id 时不应崩溃（用 doc_id 或空串兜底）。"""
        from app.services.skill_runner import SkillRunner

        runner = SkillRunner.__new__(SkillRunner)
        runner.skills_dir = SKILLS_DIR
        runner.context = {}
        state = {"docs": [{"filename": "no_id.md", "md_content": "x"}]}
        inputs = runner._build_classify_inputs(state)
        assert "no_id.md" in inputs["doc_titles_and_excerpts"]


class TestRouterNoFilenameFallback:
    """验证 review.py 路由不再使用文件名回退匹配。"""

    def test_router_source_has_no_filename_fallback(self):
        review_py = (SRC / "routers" / "review.py").read_text(encoding="utf-8")
        # 不应出现 doc_id == doc.filename 这种回退
        assert "c.get(\"doc_id\") == doc.filename" not in review_py
        # 应保留精确 DB id 匹配
        assert "str(c.get(\"doc_id\")) == str(doc.id)" in review_py


class TestClassifyPromptFormat:
    """classify.md prompt 应明确使用 [doc_id] 格式。"""

    def test_prompt_uses_doc_id_bracket(self):
        prompt = (SKILLS_DIR / "prd-overview-classify" / "prompts" / "classify.md").read_text(encoding="utf-8")
        assert "[abc123]" in prompt  # 示例中含 [doc_id] 格式
        assert "doc_id" in prompt
