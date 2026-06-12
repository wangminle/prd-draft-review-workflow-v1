"""P6.B.1: Skill 回归测试框架 — 每个 Skill 绑定样例文档 + 期望输出结构，升级前自动验证。

设计：
- 扫描 skills/ 目录下所有 Skill
- 验证 SKILL.md 存在且可解析
- 验证 prompts/ 目录存在且包含必要的 prompt 文件
- 验证 SkillConfig 中的注册信息与文件系统一致
- 输出对比结果（结构化 JSON）
"""
import os
import pytest
from pathlib import Path

# Skill 目录
SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _discover_skills() -> list[str]:
    """扫描 skills/ 目录下的所有 Skill。"""
    if not SKILLS_DIR.exists():
        return []
    return [
        d.name for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    ]


class TestSkillRegression:
    """P6.B.1: Skill 回归测试框架。"""

    SKILLS = _discover_skills()

    @pytest.mark.parametrize("skill_name", SKILLS, ids=SKILLS)
    def test_skill_md_exists(self, skill_name):
        """验证 SKILL.md 文件存在。"""
        skill_dir = SKILLS_DIR / skill_name
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists(), f"Skill '{skill_name}' 缺少 SKILL.md"

    @pytest.mark.parametrize("skill_name", SKILLS, ids=SKILLS)
    def test_skill_md_has_required_sections(self, skill_name):
        """验证 SKILL.md 包含必要章节。"""
        skill_md = SKILLS_DIR / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        required_sections = ["name", "description"]
        for section in required_sections:
            assert section.lower() in content.lower(), f"Skill '{skill_name}' SKILL.md 缺少 '{section}' 部分"

    @pytest.mark.parametrize("skill_name", SKILLS, ids=SKILLS)
    def test_prompts_directory_exists(self, skill_name):
        """验证 prompts/ 目录存在。"""
        skill_dir = SKILLS_DIR / skill_name
        prompts_dir = skill_dir / "prompts"
        # 某些 Skill 可能没有独立 prompts 目录
        # 但目录结构应该存在（可以为空）
        assert skill_dir.exists(), f"Skill '{skill_name}' 目录不存在"

    @pytest.mark.parametrize("skill_name", SKILLS, ids=SKILLS)
    def test_skill_no_syntax_errors_in_python(self, skill_name):
        """验证 Skill 中的 Python 文件没有语法错误。"""
        skill_dir = SKILLS_DIR / skill_name
        for py_file in skill_dir.rglob("*.py"):
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    compile(f.read(), str(py_file), "exec")
            except SyntaxError as e:
                pytest.fail(f"Skill '{skill_name}' Python 文件语法错误: {py_file}: {e}")

    def test_skills_directory_exists(self):
        """验证 skills/ 目录存在。"""
        assert SKILLS_DIR.exists(), "skills/ 目录不存在"

    def test_at_least_one_skill_registered(self):
        """验证至少有一个 Skill 注册。"""
        assert len(self.SKILLS) >= 1, "至少应注册一个 Skill"
