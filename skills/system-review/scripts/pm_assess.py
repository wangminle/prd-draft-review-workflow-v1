#!/usr/bin/env python3
"""system-review PM评估独立入口：仅执行维度6（PM能力评估）。

用法:
    python pm_assess.py <classify_json> <analysis_dir> <output_json> [options]

输入: prd-overview-classify输出JSON + prd-per-analysis输出目录
输出: PM能力评估JSON + Markdown报告
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
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class WritingScore(BaseModel):
    score: int = 0
    evidence: str = ""


class WritingScores(BaseModel):
    logic: WritingScore = Field(default_factory=WritingScore)
    tech_depth: WritingScore = Field(default_factory=WritingScore)
    boundary: WritingScore = Field(default_factory=WritingScore)
    business: WritingScore = Field(default_factory=WritingScore)


class ThinkingScores(BaseModel):
    iteration: WritingScore = Field(default_factory=WritingScore)
    experience: WritingScore = Field(default_factory=WritingScore)
    data: WritingScore = Field(default_factory=WritingScore)
    business: WritingScore = Field(default_factory=WritingScore)


class GrowthPath(BaseModel):
    short_term: list[str] = Field(default_factory=list)
    mid_term: list[str] = Field(default_factory=list)
    long_term: list[str] = Field(default_factory=list)


class PMAssessmentResult(BaseModel):
    writing_scores: WritingScores = Field(default_factory=WritingScores)
    thinking_scores: ThinkingScores = Field(default_factory=ThinkingScores)
    pm_type: str = "均衡型"
    highlights: list[str] = Field(default_factory=list)
    blindspots: list[str] = Field(default_factory=list)
    growth_path: GrowthPath = Field(default_factory=GrowthPath)


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("错误：需要设置 ANTHROPIC_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)
    return key


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def load_classify_result(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_analysis_results(analysis_dir: Path) -> list[dict]:
    results = []
    if not analysis_dir.exists():
        return results
    for f in sorted(analysis_dir.iterdir()):
        if f.suffix == ".json" and not f.name.startswith("_"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    data["_source_file"] = f.name
                    results.append(data)
            except Exception as e:
                print(f"  警告：加载分析结果失败 {f.name}：{e}", file=sys.stderr)
    return results


def load_rubric(path: str) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def read_original_docs(classify_data: dict) -> list[dict]:
    docs = []
    for doc in classify_data.get("documents", []):
        md_path = doc.get("md_path", "")
        if md_path and Path(md_path).exists():
            try:
                content = Path(md_path).read_text(encoding="utf-8")
                docs.append({
                    "doc_id": doc.get("doc_id", ""),
                    "title": doc.get("title", ""),
                    "version": doc.get("version", ""),
                    "md_content": content,
                })
            except Exception:
                pass
    return docs


def build_analyses_summary(analyses: list[dict]) -> str:
    summaries = []
    for a in analyses:
        summaries.append({
            "doc_id": a.get("doc_id", ""),
            "core_problem": a.get("core_problem", ""),
            "category": a.get("category", ""),
            "boundary_issues_count": len(a.get("boundary_issues", [])),
            "quality_score": a.get("quality_score", 0),
        })
    return json.dumps(summaries, ensure_ascii=False, indent=2)


def parse_pm_output(text: str) -> dict:
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {"raw_output": text}


def generate_pm_assessment_md(result: PMAssessmentResult, project_name: str) -> str:
    lines = [f"# {project_name} — PM能力评估报告\n"]

    lines.append(f"## PM类型：{result.pm_type}\n")

    ws = result.writing_scores
    lines.append("## 写作风格评估\n")
    lines.append("| 维度 | 评分 | 证据 |")
    lines.append("|------|------|------|")
    for key, label in [("logic", "逻辑结构"), ("tech_depth", "技术深度"),
                       ("boundary", "边界意识"), ("business", "商业视角")]:
        s = getattr(ws, key, WritingScore())
        lines.append(f"| {label} | {s.score} | {s.evidence} |")
    lines.append("")

    ts = result.thinking_scores
    lines.append("## 产品思维评估\n")
    lines.append("| 维度 | 评分 | 证据 |")
    lines.append("|------|------|------|")
    for key, label in [("iteration", "迭代思维"), ("experience", "体验思维"),
                       ("data", "数据思维"), ("business", "商业思维")]:
        s = getattr(ts, key, WritingScore())
        lines.append(f"| {label} | {s.score} | {s.evidence} |")
    lines.append("")

    if result.highlights:
        lines.append("## 亮点\n")
        for h in result.highlights:
            lines.append(f"- ✅ {h}")
        lines.append("")

    if result.blindspots:
        lines.append("## 盲点\n")
        for b in result.blindspots:
            lines.append(f"- ❌ {b}")
        lines.append("")

    gp = result.growth_path
    lines.append("## 成长路径\n")
    for key, label in [("short_term", "短期1-3月"), ("mid_term", "中期3-6月"), ("long_term", "远期6-12月")]:
        items = getattr(gp, key, [])
        if items:
            lines.append(f"### {label}\n")
            for i in items:
                lines.append(f"- {i}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="PM能力评估（体系化Review维度6独立入口）")
    parser.add_argument("classify_json", help="prd-overview-classify输出JSON路径")
    parser.add_argument("analysis_dir", help="prd-per-analysis输出目录")
    parser.add_argument("output_json", help="输出JSON文件路径")
    parser.add_argument("--rubric", default="", help="PM评分量规JSON路径（覆盖默认标准）")
    args = parser.parse_args()

    classify_path = Path(args.classify_json)
    if not classify_path.exists():
        print(f"错误：分类结果文件不存在：{classify_path}", file=sys.stderr)
        sys.exit(1)

    analysis_dir = Path(args.analysis_dir)
    if not analysis_dir.exists():
        print(f"错误：分析结果目录不存在：{analysis_dir}", file=sys.stderr)
        sys.exit(1)

    api_key = get_api_key()
    try:
        import anthropic
    except ImportError:
        print("错误：需要 anthropic，请运行 pip install anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    text_model = os.environ.get("TEXT_MODEL", DEFAULT_TEXT_MODEL)

    print("=== PM能力评估 ===")
    print(f"文本引擎：{text_model}")

    classify_data = load_classify_result(classify_path)
    analyses = load_analysis_results(analysis_dir)
    project_name = classify_data.get("project_name", classify_path.stem)
    rubric = load_rubric(args.rubric)

    print(f"项目：{project_name} | 文档数：{len(classify_data.get('documents', []))}")

    original_docs = read_original_docs(classify_data)
    analyses_summary = build_analyses_summary(analyses)

    system_prompt = load_prompt("system-context.md")
    dimension_prompt = load_prompt("pm-assessment.md")

    if not dimension_prompt:
        print("错误：未找到PM评估Prompt文件", file=sys.stderr)
        sys.exit(1)

    combined_system = f"{system_prompt}\n\n---\n\n{dimension_prompt}"

    full_docs_content = json.dumps(
        [{"doc_id": d["doc_id"], "title": d["title"], "md_content": d["md_content"]}
         for d in original_docs],
        ensure_ascii=False
    )

    user_parts = []
    user_parts.append(f"## 所有文档原文\n{full_docs_content}")
    user_parts.append(f"## 逐篇分析结果摘要\n{analyses_summary}")
    user_parts.append(f"## 分类信息\n{json.dumps(classify_data.get('categories', []), ensure_ascii=False, indent=2)}")
    user_parts.append(f"## 版本链信息\n{json.dumps(classify_data.get('version_chains', []), ensure_ascii=False, indent=2)}")

    if rubric:
        user_parts.append(f"## 评分量规覆盖\n{json.dumps(rubric, ensure_ascii=False, indent=2)}")

    user_msg = "\n\n".join(user_parts)

    print("正在评估PM能力...")
    try:
        response = client.messages.create(
            model=text_model,
            max_tokens=4096,
            system=combined_system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw_result = parse_pm_output(response.content[0].text)
    except Exception as e:
        print(f"错误：PM评估失败：{e}", file=sys.stderr)
        sys.exit(1)

    if "raw_output" in raw_result:
        print("警告：LLM未返回有效JSON，已保存原始输出", file=sys.stderr)

    try:
        result = PMAssessmentResult(**raw_result)
    except Exception as e:
        print(f"警告：结果校验问题：{e}，保存原始结果", file=sys.stderr)
        result = PMAssessmentResult()

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2, ensure_ascii=False))

    report_md = generate_pm_assessment_md(result, project_name)
    report_path = output_path.parent / f"{output_path.stem}_pm_assessment.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"\n结果已保存至：{output_path}")
    print(f"报告已保存至：{report_path}")
    print(f"PM类型：{result.pm_type}")
    ws = result.writing_scores
    ts = result.thinking_scores
    w_avg = (ws.logic.score + ws.tech_depth.score + ws.boundary.score + ws.business.score) / 4
    t_avg = (ts.iteration.score + ts.experience.score + ts.data.score + ts.business.score) / 4
    print(f"写作平均：{w_avg:.1f} | 思维平均：{t_avg:.1f}")


if __name__ == "__main__":
    main()
