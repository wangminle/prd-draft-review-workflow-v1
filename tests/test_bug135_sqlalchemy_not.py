"""BUG-135: SQLAlchemy `not` 关键字误用为 `not_()` 函数的契约测试。

问题：review.py 的 `_get_model_config()` 在 SQLAlchemy 查询中使用了
Python 的 `not` 关键字取反 Column 对象：

    # Bug: not 作用于 Column 返回 False（Column 对象 __bool__ 恒 True），
    # 传给 .where() 后等价于 WHERE 0，查不到任何模型
    .where(ModelConfig.enabled, not ModelConfig.deleted_by_user)

    # 修复：使用 SQLAlchemy 的 not_() 函数生成 SQL NOT
    .where(ModelConfig.enabled, not_(ModelConfig.deleted_by_user))

影响：当用户未指定 model_id 时，系统无法找到任何启用的模型配置，
报 "无可用的LLM模型配置"，Pi Agent 和审查管线全部不可用。

本测试在源码层面验证修复的正确性。
"""

import re
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
REVIEW_PY = PROJECT_ROOT / "src" / "app" / "routers" / "review.py"


class TestNotImported:
    """验证 not_ 已从 sqlalchemy 导入。"""

    def test_not_imported_from_sqlalchemy(self):
        content = REVIEW_PY.read_text(encoding="utf-8")
        assert "not_" in content, "review.py 中未找到 not_，可能未导入"
        # 确认是 import 语句
        assert re.search(r"from sqlalchemy import.*\bnot_\b", content), (
            "review.py 未从 sqlalchemy 导入 not_"
        )


class TestNoBareNotOnColumn:
    """验证不存在 `not Model.column` 模式（Python not 作用于 Column 对象）。"""

    def test_no_bare_not_on_model_config(self):
        content = REVIEW_PY.read_text(encoding="utf-8")
        # 搜索 `not ModelConfig.` 模式 -- 这就是 bug 的特征
        matches = re.findall(r"\bnot\s+ModelConfig\.\w+", content)
        assert not matches, (
            f"review.py 中发现 `not ModelConfig.xxx` 模式（Python not 作用于 "
            f"SQLAlchemy Column），应改用 not_(): {matches}"
        )

    def test_no_bare_not_on_any_orm_model(self):
        """全 src 目录扫描，确保不存在 `not SomeClass.column` 模式。"""
        src_dir = PROJECT_ROOT / "src"
        offenders = []
        for py_file in src_dir.rglob("*.py"):
            rel = py_file.relative_to(PROJECT_ROOT)
            content = py_file.read_text(encoding="utf-8")
            # 匹配 `not ClassName.attr` 但排除 `not_` 和 `not None` / `not x` 等
            # 只关心 ClassName 首字母大写（ORM Model 惯例）后跟 .属性
            for m in re.finditer(r"\bnot\s+([A-Z][a-zA-Z]+)\.([a-z_]\w*)", content):
                # 排除注释行
                line_start = content.rfind("\n", 0, m.start()) + 1
                line = content[line_start:content.find("\n", m.end())]
                if line.strip().startswith("#"):
                    continue
                offenders.append(f"{rel}:{line.strip()}")
        assert not offenders, (
            "发现 `not ORMClass.attr` 模式（Python not 作用于 SQLAlchemy Column），"
            "应改用 not_():\n" + "\n".join(offenders)
        )


class TestNotUsedInWhereClauses:
    """验证 not_() 在 WHERE 子句中正确使用。"""

    def test_not_used_for_deleted_by_user(self):
        content = REVIEW_PY.read_text(encoding="utf-8")
        # 确认 not_(ModelConfig.deleted_by_user) 出现在查询中
        assert "not_(ModelConfig.deleted_by_user)" in content, (
            "review.py 中未找到 not_(ModelConfig.deleted_by_user)，"
            "模型查询可能仍使用错误的 `not` 关键字"
        )

    def test_not_count_at_least_two(self):
        """两处查询（按 model_id 查 + 默认查）都应使用 not_()。"""
        content = REVIEW_PY.read_text(encoding="utf-8")
        count = content.count("not_(ModelConfig.deleted_by_user)")
        assert count >= 2, (
            f"review.py 中 not_(ModelConfig.deleted_by_user) 出现 {count} 次，"
            f"期望至少 2 次（按 model_id 查 + 默认查）"
        )
