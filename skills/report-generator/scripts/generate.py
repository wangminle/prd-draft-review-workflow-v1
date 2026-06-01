#!/usr/bin/env python3
"""report-generator: 从分析结果生成结构化Markdown/PDF报告。

用法:
    python generate.py <classify_json> <analysis_dir> <review_json> <output_dir> [options]

输入: prd-overview-classify + prd-per-analysis + system-review 的输出
输出: Markdown/PDF报告文件
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    print("错误：需要 pydantic，请运行 pip install pydantic", file=sys.stderr)
    sys.exit(1)

DEFAULT_TEXT_MODEL = "claude-sonnet-4-20250514"
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

REPORT_TYPE_PER_ANALYSIS = "per_analysis"
REPORT_TYPE_FULL_REVIEW = "full_review"
REPORT_TYPE_NEXT_DIRECTIONS = "next_directions"
REPORT_TYPE_PM_DEVELOPMENT = "pm_development"
REPORT_TYPE_PRD_DRAFT = "prd_draft"
REPORT_TYPE_INSIGHTS = "insights"
REPORT_TYPE_ALL = "all"
VALID_REPORT_TYPES = [REPORT_TYPE_PER_ANALYSIS, REPORT_TYPE_FULL_REVIEW,
                      REPORT_TYPE_NEXT_DIRECTIONS, REPORT_TYPE_PM_DEVELOPMENT,
                      REPORT_TYPE_PRD_DRAFT, REPORT_TYPE_INSIGHTS, REPORT_TYPE_ALL]

FORMAT_MD = "md"
FORMAT_PDF = "pdf"
FORMAT_ALL = "all"
VALID_FORMATS = [FORMAT_MD, FORMAT_PDF, FORMAT_ALL]


class OutputFile(BaseModel):
    type: str = "markdown"
    path: str = ""
    size: int = 0


class MermaidChart(BaseModel):
    type: str = ""
    chart_id: str = ""
    code: str = ""


class ReportSummary(BaseModel):
    total_reports: int = 0
    total_md_size: int = 0
    chart_count: int = 0


class GenerateResult(BaseModel):
    project_name: str = ""
    files: list[OutputFile] = Field(default_factory=list)
    mermaid_charts: list[MermaidChart] = Field(default_factory=list)
    summary: ReportSummary = Field(default_factory=ReportSummary)


def load_json(path: str) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"警告：加载文件失败 {path}：{e}", file=sys.stderr)
        return {}


def load_analysis_results(analysis_dir: Path) -> list[dict]:
    results = []
    if not analysis_dir.exists():
        return results
    for f in sorted(analysis_dir.iterdir()):
        if f.suffix == ".json" and not f.name.startswith("_"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    results.append(json.load(fh))
            except Exception:
                pass
    return results


def get_api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def polish_report(client, content: str, text_model: str) -> str:
    system_prompt = load_prompt("report-polish.md")
    if not system_prompt:
        return content
    try:
        response = client.messages.create(
            model=text_model,
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text
    except Exception as e:
        print(f"  警告：报告润色失败：{e}", file=sys.stderr)
        return content


def generate_per_analysis_md(project_name: str, analyses: list[dict],
                              classify_data: dict, insights_data: dict) -> str:
    lines = [f"# {project_name} — 需求文档逐篇分析报告\n"]

    categories = classify_data.get("categories", [])
    version_chains = classify_data.get("version_chains", [])
    docs = classify_data.get("documents", [])

    lines.append("## 一、文档概览\n")
    lines.append(f"文档总数：{len(docs)}篇 | 分类数：{len(categories)} | 版本链：{len(version_chains)}条\n")

    if categories:
        lines.append("### 分类分布\n")
        lines.append("| 分类 | 文档数 |")
        lines.append("|------|--------|")
        for c in categories:
            lines.append(f"| {c.get('name', '')} | {c.get('doc_count', 0)} |")
        lines.append("")

    lines.append("## 二、逐篇分析\n")
    for a in analyses:
        doc_id = a.get("doc_id", "")
        core_problem = a.get("core_problem", "")
        category = a.get("category", "")
        boundary_in = a.get("boundary_in", [])
        boundary_out = a.get("boundary_out", [])
        boundary_issues = a.get("boundary_issues", [])
        quality_score = a.get("quality_score", 0)
        key_points = a.get("key_points", {})

        stars = "★" * int(quality_score) + "☆" * (5 - int(quality_score))

        lines.append(f"### {doc_id}\n")
        lines.append(f"- **核心问题**：{core_problem}")
        lines.append(f"- **分类**：{category}")
        lines.append(f"- **质量评分**：{stars} {quality_score}/5\n")

        if boundary_in:
            lines.append("**边界（做）**：")
            for bi in boundary_in:
                lines.append(f"- ✅ {bi}")
            lines.append("")
        if boundary_out:
            lines.append("**边界（不做）**：")
            for bo in boundary_out:
                lines.append(f"- ❌ {bo}")
            lines.append("")

        if boundary_issues:
            lines.append("**边界外问题**：")
            for bi in boundary_issues:
                res = bi.get("resolution", {})
                status = res.get("status", "unresolved")
                icon = {"resolved": "✅", "partial": "⚠️", "unresolved": "🔴"}.get(status, "❓")
                lines.append(f"- {icon} {bi.get('issue', '')}（{status}）")
            lines.append("")

        kp_type = key_points.get("type", "")
        highlights = key_points.get("solution_highlights", [])
        params = key_points.get("key_parameters", [])
        if highlights:
            lines.append(f"**要点（{kp_type}）**：")
            for h in highlights:
                lines.append(f"- {h}")
            lines.append("")
        if params:
            lines.append("**关键参数**：")
            for p in params:
                lines.append(f"- {p.get('name', '')}：{p.get('value', '')}")
            lines.append("")

    all_issues = []
    for a in analyses:
        for bi in a.get("boundary_issues", []):
            res = bi.get("resolution", {})
            all_issues.append({
                "issue": bi.get("issue", ""),
                "source": a.get("doc_id", ""),
                "version": a.get("version", ""),
                "status": res.get("status", "unresolved"),
                "resolved_by": res.get("resolved_by", ""),
            })

    if all_issues:
        lines.append("## 三、边界外问题追踪汇总\n")
        lines.append("| 问题 | 来源版本 | 解决状态 | 解决版本 |")
        lines.append("|------|---------|---------|---------|")
        for iss in all_issues:
            lines.append(f"| {iss['issue'][:30]} | {iss['version']} | {iss['status']} | {iss['resolved_by'] or '-'} |")
        lines.append("")

    if insights_data:
        evolution = insights_data.get("evolution", {})
        mermaid = evolution.get("mermaid_graph", "")
        if mermaid:
            lines.append("## 四、需求演进脉络\n")
            lines.append("```mermaid")
            lines.append(mermaid)
            lines.append("```\n")

    avg_score = sum(a.get("quality_score", 0) for a in analyses) / max(len(analyses), 1)
    lines.append("## 五、文档质量评价\n")
    lines.append(f"平均质量评分：{avg_score:.1f}/5\n")

    return "\n".join(lines)


def generate_full_review_md(project_name: str, review_data: dict) -> str:
    dimensions = review_data.get("dimensions", {})
    reports = review_data.get("reports", {})
    if reports.get("full_report_md"):
        return reports["full_report_md"]

    lines = [f"# {project_name} — 体系化Review报告\n"]

    dim_labels = [
        ("business_value", "一、业务价值分析"),
        ("architecture", "二、需求体系架构"),
        ("competition", "三、品牌与竞争定位"),
        ("product_strategy", "四、产品策略评估"),
        ("tech_evolution", "五、技术架构演进"),
        ("pm_assessment", "六、PM能力评估"),
        ("action_plan", "七、行动计划与优先级"),
    ]

    section_num = 0
    for dim_key, dim_label in dim_labels:
        dim_data = dimensions.get(dim_key)
        if not dim_data:
            continue
        section_num += 1
        cn_num = "一二三四五六七"[section_num - 1] if section_num <= 7 else str(section_num)
        prefix = dim_label.split("、")[0] if "、" in dim_label else cn_num
        lines.append(f"## {dim_label}\n")
        lines.append(f"```json")
        lines.append(json.dumps(dim_data, ensure_ascii=False, indent=2))
        lines.append("```\n")

    return "\n".join(lines)


def generate_next_directions_md(project_name: str, review_data: dict,
                                 insights_data: dict) -> str:
    reports = review_data.get("reports", {})
    if reports.get("next_directions_md"):
        return reports["next_directions_md"]

    lines = [f"# {project_name} — 下一步需求方向建议\n"]

    dimensions = review_data.get("dimensions", {})
    bv = dimensions.get("business_value", {})
    if bv:
        goals = bv.get("business_goals", [])
        if goals:
            lines.append("## 当前业务目标与差距\n")
            for g in goals:
                lines.append(f"- **{g.get('goal', '')}**（覆盖：{g.get('coverage', '')}）— 差距：{g.get('gap', '')}")
            lines.append("")

    arch = dimensions.get("architecture", {})
    if arch:
        gaps = arch.get("architecture_gaps", [])
        if gaps:
            lines.append("## 架构层面的需求方向\n")
            for g in gaps:
                lines.append(f"- [{g.get('type', '')}] {g.get('description', '')} → {g.get('suggestion', '')}")
            lines.append("")

    if insights_data:
        evolution = insights_data.get("evolution", {})
        evo_summary = evolution.get("summary", {})
        unresolved = evo_summary.get("unresolved", 0)
        partial = evo_summary.get("partial", 0)
        if unresolved or partial:
            lines.append(f"## 演进层面的需求方向\n")
            lines.append(f"仍有 {unresolved} 个未解决问题和 {partial} 个部分解决问题，需后续版本覆盖。\n")

        gap_analysis = insights_data.get("gap_analysis", {})
        gaps = gap_analysis.get("gaps", [])
        if gaps:
            lines.append("## 功能层面的需求方向\n")
            for g in gaps:
                lines.append(f"- 🔴 **{g.get('feature', '')}**（{g.get('severity', '')}）→ {g.get('suggestion', '')}")
            lines.append("")

    ap = dimensions.get("action_plan", {})
    if ap:
        for period_key, label in [("short_term", "短期1-3月"), ("mid_term", "中期3-6月")]:
            items = ap.get(period_key, [])
            if items:
                lines.append(f"## {label}行动项\n")
                for item in items:
                    lines.append(f"- **{item.get('action', '')}**（优先级：{item.get('priority', '')}）")
                lines.append("")

    return "\n".join(lines)


def generate_pm_development_md(project_name: str, review_data: dict) -> str:
    reports = review_data.get("reports", {})
    if reports.get("quality_assessment_md"):
        return reports["quality_assessment_md"]

    pm = review_data.get("dimensions", {}).get("pm_assessment", {})
    if not pm:
        return f"# {project_name} — PM发展建议\n\nPM评估数据不可用。\n"

    lines = [f"# {project_name} — PM发展建议\n"]
    lines.append(f"**PM类型：{pm.get('pm_type', '未确定')}**\n")

    ws = pm.get("writing_scores", {})
    if ws:
        lines.append("## 写作风格评估\n")
        lines.append("| 维度 | 评分 | 证据 |")
        lines.append("|------|------|------|")
        for key, label in [("logic", "逻辑结构"), ("tech_depth", "技术深度"),
                           ("boundary", "边界意识"), ("business", "商业视角")]:
            s = ws.get(key, {})
            lines.append(f"| {label} | {s.get('score', '-')} | {s.get('evidence', '-')} |")
        lines.append("")

    ts = pm.get("thinking_scores", {})
    if ts:
        lines.append("## 产品思维评估\n")
        lines.append("| 维度 | 评分 | 证据 |")
        lines.append("|------|------|------|")
        for key, label in [("iteration", "迭代思维"), ("experience", "体验思维"),
                           ("data", "数据思维"), ("business", "商业思维")]:
            s = ts.get(key, {})
            lines.append(f"| {label} | {s.get('score', '-')} | {s.get('evidence', '-')} |")
        lines.append("")

    highlights = pm.get("highlights", [])
    if highlights:
        lines.append("## 亮点\n")
        for h in highlights:
            lines.append(f"- ✅ {h}")
        lines.append("")

    blindspots = pm.get("blindspots", [])
    if blindspots:
        lines.append("## 盲点\n")
        for b in blindspots:
            lines.append(f"- ❌ {b}")
        lines.append("")

    gp = pm.get("growth_path", {})
    if gp:
        lines.append("## 成长路径\n")
        for key, label in [("short_term", "短期1-3月"), ("mid_term", "中期3-6月"), ("long_term", "远期6-12月")]:
            items = gp.get(key, [])
            if items:
                lines.append(f"### {label}\n")
                for i in items:
                    lines.append(f"- {i}")
                lines.append("")

    return "\n".join(lines)


def generate_prd_draft_md(project_name: str, review_data: dict) -> str:
    reports = review_data.get("reports", {})
    if reports.get("prd_draft_md"):
        return reports["prd_draft_md"]
    return f"# {project_name} — 基于历史分析的需求文档初稿\n\n（请使用 --target-doc 参数指定目标文档以生成针对性初稿）\n"


def generate_insights_md(project_name: str, insights_data: dict) -> str:
    if not insights_data:
        return f"# {project_name} — 需求洞察报告\n\n无洞察数据。\n"

    lines = [f"# {project_name} — 需求洞察报告\n"]

    evolution = insights_data.get("evolution", {})
    if evolution:
        lines.append("## 一、演进链追踪\n")
        chains = evolution.get("evolution_chains", [])
        for chain in chains:
            lines.append(f"### {chain.get('chain_name', '')}\n")
            versions = chain.get("versions", [])
            for v in versions:
                remaining = v.get("boundary_issues_remaining", [])
                resolved = v.get("boundary_issues_resolved", [])
                lines.append(f"**{v.get('version', '')} {v.get('title', '')}**")
                if resolved:
                    lines.append(f"  ✅ 已解决：{', '.join(resolved)}")
                if remaining:
                    lines.append(f"  🔴 遗留：{', '.join(remaining)}")
                lines.append("")

        summary = evolution.get("summary", {})
        lines.append("### 汇总\n")
        lines.append(f"| 指标 | 数量 |")
        lines.append("|------|------|")
        lines.append(f"| 演进链 | {summary.get('total_chains', 0)} |")
        lines.append(f"| 总问题数 | {summary.get('total_issues', 0)} |")
        lines.append(f"| 已解决 | {summary.get('resolved', 0)} |")
        lines.append(f"| 部分解决 | {summary.get('partial', 0)} |")
        lines.append(f"| 未解决 | {summary.get('unresolved', 0)} |")
        lines.append("")

        mermaid = evolution.get("mermaid_graph", "")
        if mermaid:
            lines.append("```mermaid")
            lines.append(mermaid)
            lines.append("```\n")

    gap_analysis = insights_data.get("gap_analysis", {})
    if gap_analysis:
        lines.append("## 二、功能覆盖矩阵\n")
        matrix = gap_analysis.get("coverage_matrix", [])
        if matrix:
            lines.append("| 功能维度 | 覆盖文档 | 状态 |")
            lines.append("|---------|---------|------|")
            for entry in matrix:
                status_icon = {"covered": "✅", "gap": "❌", "overlap": "🔄"}.get(entry.get("status", ""), "❓")
                covered = ", ".join(entry.get("covered_by", [])) or "-"
                lines.append(f"| {entry.get('feature', '')} | {covered} | {status_icon} {entry.get('status', '')} |")
            lines.append("")

        gaps = gap_analysis.get("gaps", [])
        if gaps:
            lines.append("## 三、需求缺口\n")
            for g in gaps:
                lines.append(f"- 🔴 **{g.get('feature', '')}**（{g.get('severity', '')}）→ {g.get('suggestion', '')}")
            lines.append("")

        overlaps = gap_analysis.get("overlaps", [])
        if overlaps:
            lines.append("## 四、功能重叠\n")
            for o in overlaps:
                lines.append(f"- 🔄 **{o.get('feature', '')}**：{o.get('note', '')}（覆盖：{', '.join(o.get('covered_by', []))}）")
            lines.append("")

    return "\n".join(lines)


def markdown_to_pdf(md_path: Path, pdf_path: Path) -> bool:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import mm
    except ImportError:
        print("  警告：reportlab未安装，跳过PDF生成（pip install reportlab）", file=sys.stderr)
        return False

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"  警告：读取Markdown失败：{e}", file=sys.stderr)
        return False

    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                            leftMargin=25 * mm, rightMargin=25 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)

    styles = getSampleStyleSheet()
    cn_style = ParagraphStyle('ChineseNormal', parent=styles['Normal'],
                               fontName='Helvetica', fontSize=10, leading=14)
    cn_h1 = ParagraphStyle('ChineseH1', parent=styles['Heading1'],
                            fontName='Helvetica', fontSize=18, leading=22)
    cn_h2 = ParagraphStyle('ChineseH2', parent=styles['Heading2'],
                            fontName='Helvetica', fontSize=14, leading=18)

    story = []
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 6))
        elif stripped.startswith("# "):
            story.append(Paragraph(stripped[2:], cn_h1))
        elif stripped.startswith("## "):
            story.append(Paragraph(stripped[3:], cn_h2))
        else:
            text = stripped.replace("|", " │ ").replace("**", "")
            try:
                story.append(Paragraph(text, cn_style))
            except Exception:
                pass

    try:
        doc.build(story)
        return True
    except Exception as e:
        print(f"  警告：PDF生成失败：{e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="报告生成与可视化")
    parser.add_argument("classify_json", help="prd-overview-classify输出JSON路径")
    parser.add_argument("analysis_dir", help="prd-per-analysis输出目录")
    parser.add_argument("review_json", help="system-review输出JSON路径")
    parser.add_argument("output_dir", help="输出目录")
    parser.add_argument("--insights-json", default="", help="requirement-insights输出JSON路径")
    parser.add_argument("--report-type", default=REPORT_TYPE_ALL,
                        choices=VALID_REPORT_TYPES,
                        help="报告类型（默认：all）")
    parser.add_argument("--format", default=FORMAT_MD,
                        choices=VALID_FORMATS,
                        help="输出格式（默认：md）")
    parser.add_argument("--sections", default="",
                        help="指定报告章节，逗号分隔（如overview,per_analysis,evolution）")
    parser.add_argument("--polish", action="store_true", help="使用LLM润色报告")
    args = parser.parse_args()

    classify_path = Path(args.classify_json)
    if not classify_path.exists():
        print(f"错误：分类结果文件不存在：{classify_path}", file=sys.stderr)
        sys.exit(1)

    review_path = Path(args.review_json)
    if not review_path.exists():
        print(f"错误：Review结果文件不存在：{review_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== 报告生成 ===")
    print(f"报告类型：{args.report_type}")
    print(f"输出格式：{args.format}")

    classify_data = load_json(str(classify_path))
    analyses = load_analysis_results(Path(args.analysis_dir))
    review_data = load_json(str(review_path))
    insights_data = load_json(args.insights_json) if args.insights_json else {}
    project_name = classify_data.get("project_name", classify_path.stem)

    print(f"项目：{project_name} | 分析结果：{len(analyses)}篇")

    client = None
    if args.polish:
        api_key = get_api_key()
        if not api_key:
            print("警告：--polish 需要 ANTHROPIC_API_KEY，跳过润色", file=sys.stderr)
            args.polish = False
        else:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                print("警告：anthropic未安装，跳过润色", file=sys.stderr)
                args.polish = False

    text_model = os.environ.get("TEXT_MODEL", DEFAULT_TEXT_MODEL)
    result = GenerateResult(project_name=project_name)
    total_md_size = 0
    chart_count = 0

    report_generators = {
        REPORT_TYPE_PER_ANALYSIS: ("逐篇分析报告", lambda: generate_per_analysis_md(
            project_name, analyses, classify_data, insights_data)),
        REPORT_TYPE_FULL_REVIEW: ("体系Review报告", lambda: generate_full_review_md(
            project_name, review_data)),
        REPORT_TYPE_NEXT_DIRECTIONS: ("下一步需求方向建议", lambda: generate_next_directions_md(
            project_name, review_data, insights_data)),
        REPORT_TYPE_PM_DEVELOPMENT: ("PM发展建议", lambda: generate_pm_development_md(
            project_name, review_data)),
        REPORT_TYPE_PRD_DRAFT: ("PRD初稿", lambda: generate_prd_draft_md(
            project_name, review_data)),
        REPORT_TYPE_INSIGHTS: ("需求洞察报告", lambda: generate_insights_md(
            project_name, insights_data)),
    }

    types_to_generate = list(report_generators.keys()) if args.report_type == REPORT_TYPE_ALL else [args.report_type]

    for rt in types_to_generate:
        if rt not in report_generators:
            continue
        label, gen_func = report_generators[rt]
        print(f"\n正在生成：{label}...")

        content = gen_func()

        if args.polish and client:
            print(f"  正在润色...")
            content = polish_report(client, content, text_model)

        md_path = output_dir / f"{label}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)

        md_size = len(content.encode("utf-8"))
        total_md_size += md_size
        result.files.append(OutputFile(type="markdown", path=str(md_path), size=md_size))
        print(f"  ✓ Markdown已保存：{md_path}（{md_size}字节）")

        if args.format in [FORMAT_PDF, FORMAT_ALL]:
            pdf_path = output_dir / f"{label}.pdf"
            if markdown_to_pdf(md_path, pdf_path):
                pdf_size = pdf_path.stat().st_size
                result.files.append(OutputFile(type="pdf", path=str(pdf_path), size=pdf_size))
                print(f"  ✓ PDF已保存：{pdf_path}（{pdf_size}字节）")
            else:
                print(f"  ⚠️ PDF生成跳过")

    if insights_data:
        evolution = insights_data.get("evolution", {})
        mermaid = evolution.get("mermaid_graph", "")
        if mermaid:
            result.mermaid_charts.append(MermaidChart(
                type="evolution", chart_id="evolution_overview", code=mermaid))
            chart_count += 1

    result.summary = ReportSummary(
        total_reports=len(result.files),
        total_md_size=total_md_size,
        chart_count=chart_count,
    )

    result_path = output_dir / "_generate_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2, ensure_ascii=False))

    print(f"\n报告生成完成：{len(result.files)}个文件，{total_md_size}字节")
    print(f"结果已保存至：{result_path}")


if __name__ == "__main__":
    main()
