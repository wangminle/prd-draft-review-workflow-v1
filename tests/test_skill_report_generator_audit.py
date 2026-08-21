#!/usr/bin/env python3
"""P2-5.3 测试：report-generator 参数与实现一致性。"""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "report-generator" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate  # noqa: E402
import mermaid_builder  # noqa: E402


class TestSectionsParameter:
    def test_resolve_sections_exists(self):
        assert hasattr(generate, "_resolve_sections")

    def test_resolve_sections_empty_returns_none(self):
        assert generate._resolve_sections("") is None

    def test_resolve_sections_valid(self):
        result = generate._resolve_sections("overview,insights")
        assert result is not None
        assert len(result) == 2

    def test_resolve_sections_unknown_skipped(self):
        result = generate._resolve_sections("nonexistent_section")
        # 未知章节应被过滤
        assert result == []


class TestFormatPdf:
    def test_format_pdf_constant(self):
        assert generate.FORMAT_PDF == "pdf"

    def test_valid_formats_contains_pdf(self):
        assert "pdf" in generate.VALID_FORMATS

    def test_markdown_to_pdf_function_exists(self):
        assert callable(generate.markdown_to_pdf)


class TestTotalReportsCount:
    def test_report_summary_uses_reports_not_files(self):
        # ReportSummary 应有 total_reports 和 total_files 两个独立字段
        fields = generate.ReportSummary.model_fields
        assert "total_reports" in fields
        assert "total_files" in fields


class TestRequirementsTxt:
    def test_anthropics_declared(self):
        req = (Path(__file__).resolve().parent.parent / "skills" / "report-generator" / "requirements.txt").read_text()
        assert "anthropic" in req


class TestChineseFont:
    def test_register_chinese_font_function_exists(self):
        # 应有中文字体注册函数
        assert hasattr(generate, "register_chinese_font") or any(
            "chinese" in name.lower() or "font" in name.lower()
            for name in dir(generate)
        )


class TestMdCellEscape:
    def test_escape_md_cell_pipe(self):
        assert "a\\|b" == mermaid_builder._escape_md_cell("a|b")

    def test_escape_md_cell_newline(self):
        assert "a b" == mermaid_builder._escape_md_cell("a\nb")

    def test_escape_md_cell_none(self):
        assert "" == mermaid_builder._escape_md_cell(None)


class TestMermaidEscape:
    def test_escape_quote(self):
        assert "&quot;" in mermaid_builder._escape_mermaid_label('a"b')

    def test_escape_pipe(self):
        assert "&verbar;" in mermaid_builder._escape_mermaid_label("a|b")

    def test_escape_brackets(self):
        out = mermaid_builder._escape_mermaid_label("a[b]c")
        assert "[" not in out
        assert "]" not in out

    def test_escape_newline(self):
        out = mermaid_builder._escape_mermaid_label("a\nb")
        assert "\n" not in out

    def test_sanitize_node_id(self):
        assert mermaid_builder._sanitize_node_id("doc-1.2") == "doc_1_2"
        assert mermaid_builder._sanitize_node_id("") == "node"


class TestMermaidBuilderUsage:
    def test_build_evolution_flowchart_exists(self):
        assert callable(mermaid_builder.build_evolution_flowchart)

    def test_build_dependency_graph_exists(self):
        assert callable(mermaid_builder.build_dependency_graph)

    def test_build_version_chain_timeline_exists(self):
        assert callable(mermaid_builder.build_version_chain_timeline)

    def test_generate_uses_all_three_builders(self):
        src = (SCRIPTS_DIR / "generate.py").read_text(encoding="utf-8")
        assert "build_evolution_flowchart" in src
        assert "build_dependency_graph" in src
        assert "build_version_chain_timeline" in src


class TestMermaidEmbedding:
    """BUG-162：依赖图与版本链时间线应嵌入报告正文，而非只进 _generate_result.json。"""

    DEPS = [{"from_doc_id": "doc-1", "to_doc_id": "doc-2", "relation": "依赖"}]
    DOCS = [{"doc_id": "doc-1"}, {"doc_id": "doc-2"}]
    CHAINS = [{
        "chain_name": "支付链路",
        "versions": [{"version": "v1.0", "title": "首版"}, {"version": "v2.0", "title": "改版"}],
    }]

    def _render(self, classify_data: dict, insights_data: dict | None = None) -> str:
        return generate.generate_per_analysis_md(
            "测试项目", [], classify_data, insights_data or {})

    def test_dependency_graph_embedded_when_present(self):
        md = self._render({"dependencies": self.DEPS, "documents": self.DOCS})
        assert "```mermaid" in md
        assert "graph LR" in md
        assert "-->" in md
        assert "依赖" in md

    def test_dependency_graph_absent_when_empty(self):
        md = self._render({"documents": self.DOCS})
        assert "graph LR" not in md
        assert "文档依赖关系" not in md

    def test_dependency_graph_absent_when_no_valid_edges(self):
        # 依赖条目缺少 from/to 时只剩 "graph LR" 头，视为空图不嵌入
        md = self._render({"dependencies": [{"relation": "依赖"}], "documents": self.DOCS})
        assert "graph LR" not in md

    def test_version_timeline_embedded_when_present(self):
        md = self._render({"version_chains": self.CHAINS})
        assert "gantt" in md
        assert "section 支付链路" in md

    def test_version_timeline_absent_when_empty(self):
        md = self._render({})
        assert "gantt" not in md
        assert "版本链时间线" not in md

    def test_version_timeline_absent_when_chains_have_no_versions(self):
        # 链无版本时时间线只有标题行，视为空图不嵌入
        md = self._render({"version_chains": [{"chain_name": "空链", "versions": []}]})
        assert "gantt" not in md

    def test_evolution_mermaid_still_embedded(self):
        # 原有 build_evolution_flowchart 嵌入路径（insights.mermaid_graph）保持不变
        md = self._render({}, {"evolution": {"mermaid_graph": "flowchart TD\n    a --> b"}})
        assert "flowchart TD" in md
        assert "## 四、需求演进脉络" in md
