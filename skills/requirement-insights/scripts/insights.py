#!/usr/bin/env python3
"""requirement-insights: 需求洞察（演进追踪+缺口分析）。

用法:
    python insights.py <classify_json> <analysis_dir> <output_json> [options]

输入: prd-overview-classify输出JSON + prd-per-analysis输出目录
输出: 演进追踪+缺口分析结果JSON + 可选Mermaid图
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

OUTPUT_TYPE_EVOLUTION = "evolution"
OUTPUT_TYPE_GAP = "gap"
OUTPUT_TYPE_ALL = "all"
VALID_OUTPUT_TYPES = [OUTPUT_TYPE_EVOLUTION, OUTPUT_TYPE_GAP, OUTPUT_TYPE_ALL]


class EvolutionVersion(BaseModel):
    version: str = ""
    doc_id: str = ""
    title: str = ""
    boundary_issues_raised: list[str] = Field(default_factory=list)
    boundary_issues_resolved: list[str] = Field(default_factory=list)
    boundary_issues_remaining: list[str] = Field(default_factory=list)


class EvolutionChain(BaseModel):
    chain_name: str = ""
    versions: list[EvolutionVersion] = Field(default_factory=list)


class EvolutionSummary(BaseModel):
    total_chains: int = 0
    total_issues: int = 0
    resolved: int = 0
    partial: int = 0
    unresolved: int = 0


class EvolutionResult(BaseModel):
    evolution_chains: list[EvolutionChain] = Field(default_factory=list)
    summary: EvolutionSummary = Field(default_factory=EvolutionSummary)
    mermaid_graph: str = ""


class CoverageEntry(BaseModel):
    feature: str = ""
    covered_by: list[str] = Field(default_factory=list)
    status: str = "covered"


class Gap(BaseModel):
    feature: str = ""
    description: str = ""
    severity: str = "medium"
    suggestion: str = ""


class Overlap(BaseModel):
    feature: str = ""
    covered_by: list[str] = Field(default_factory=list)
    note: str = ""


class GapSummary(BaseModel):
    total_features: int = 0
    covered: int = 0
    gaps: int = 0
    overlap_count: int = 0


class GapAnalysisResult(BaseModel):
    feature_dimensions: list[str] = Field(default_factory=list)
    coverage_matrix: list[CoverageEntry] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    overlaps: list[Overlap] = Field(default_factory=list)
    summary: GapSummary = Field(default_factory=GapSummary)


class InsightsMetadata(BaseModel):
    total_docs: int = 0
    output_type: str = OUTPUT_TYPE_ALL
    models_used: dict = Field(default_factory=dict)


class InsightsResult(BaseModel):
    project_name: str = ""
    output_type: str = OUTPUT_TYPE_ALL
    evolution: Optional[dict] = None
    gap_analysis: Optional[dict] = None
    metadata: InsightsMetadata = Field(default_factory=InsightsMetadata)


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


def parse_llm_json(text: str) -> dict:
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {"raw_output": text}


def call_llm(client, system_prompt: str, user_msg: str, text_model: str) -> dict:
    try:
        response = client.messages.create(
            model=text_model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        return parse_llm_json(response.content[0].text)
    except Exception as e:
        print(f"  错误：LLM调用失败：{e}", file=sys.stderr)
        return {"error": str(e)}


def build_doc_index(analyses: list[dict], classify_data: dict) -> dict:
    index = {}
    for doc in classify_data.get("documents", []):
        doc_id = doc.get("doc_id", "")
        index[doc_id] = {
            "doc_id": doc_id,
            "filename": doc.get("filename", ""),
            "md_path": doc.get("md_path", ""),
            "category": doc.get("category", ""),
            "version": doc.get("version", ""),
            "title": doc.get("title", ""),
        }
    for a in analyses:
        doc_id = a.get("doc_id", "")
        if doc_id in index:
            index[doc_id]["analysis"] = a
        else:
            index[doc_id] = {"doc_id": doc_id, "analysis": a,
                             "version": a.get("version", ""),
                             "category": a.get("category", "")}
    return index


def run_evolution_tracking(client, doc_index: dict, version_chains: list[dict],
                           analyses: list[dict], text_model: str) -> dict:
    system_prompt = load_prompt("evolution-match.md")
    if not system_prompt:
        print("  警告：未找到演进匹配Prompt文件", file=sys.stderr)
        return {"evolution_chains": [], "summary": {}}

    evolution_chains = []
    total_issues = 0
    resolved = 0
    partial = 0
    unresolved = 0

    for chain in version_chains:
        chain_name = chain.get("chain_name", "")
        versions = chain.get("versions", [])

        chain_versions = []
        for v_info in versions:
            doc_id = v_info.get("doc_id", "")
            doc_data = doc_index.get(doc_id, {})
            analysis = doc_data.get("analysis", {})

            issues = analysis.get("boundary_issues", [])
            raised = [bi.get("issue", "") for bi in issues if bi.get("issue")]

            chain_versions.append({
                "version": v_info.get("version", doc_data.get("version", "")),
                "doc_id": doc_id,
                "title": v_info.get("title", doc_data.get("title", "")),
                "boundary_issues_raised": raised,
                "analysis": analysis,
            })

        for i, cv in enumerate(chain_versions):
            if not cv["boundary_issues_raised"]:
                cv["boundary_issues_resolved"] = []
                cv["boundary_issues_remaining"] = []
                continue

            subsequent = chain_versions[i + 1:]
            if not subsequent:
                cv["boundary_issues_resolved"] = []
                cv["boundary_issues_remaining"] = cv["boundary_issues_raised"]
                for _ in cv["boundary_issues_raised"]:
                    unresolved += 1
                    total_issues += 1
                continue

            subsequent_summary = []
            for s in subsequent:
                subsequent_summary.append({
                    "doc_id": s["doc_id"],
                    "version": s["version"],
                    "title": s["title"],
                    "core_problem": s.get("analysis", {}).get("core_problem", ""),
                    "boundary_in": s.get("analysis", {}).get("boundary_in", []),
                    "key_points": s.get("analysis", {}).get("key_points", {}),
                })

            user_msg = (f"## 当前版本的边界外问题\n"
                        f"{json.dumps(cv['boundary_issues_raised'], ensure_ascii=False)}\n\n"
                        f"## 后续版本文档内容\n"
                        f"{json.dumps(subsequent_summary, ensure_ascii=False, indent=2)}")

            result = call_llm(client, system_prompt, user_msg, text_model)
            matches = result.get("matches", [])

            resolved_issues = []
            remaining_issues = []

            for m in matches:
                status = m.get("status", "unresolved")
                if status == "resolved":
                    resolved_issues.append(m.get("issue", ""))
                    resolved += 1
                elif status == "partial":
                    remaining_issues.append(m.get("issue", ""))
                    partial += 1
                else:
                    remaining_issues.append(m.get("issue", ""))
                    unresolved += 1
                total_issues += 1

            cv["boundary_issues_resolved"] = resolved_issues
            cv["boundary_issues_remaining"] = remaining_issues

        evolution_chain = {
            "chain_name": chain_name,
            "versions": [],
        }
        for cv in chain_versions:
            evolution_chain["versions"].append({
                "version": cv["version"],
                "doc_id": cv["doc_id"],
                "title": cv["title"],
                "boundary_issues_raised": cv["boundary_issues_raised"],
                "boundary_issues_resolved": cv["boundary_issues_resolved"],
                "boundary_issues_remaining": cv["boundary_issues_remaining"],
            })
        evolution_chains.append(evolution_chain)

    summary = {
        "total_chains": len(evolution_chains),
        "total_issues": total_issues,
        "resolved": resolved,
        "partial": partial,
        "unresolved": unresolved,
    }

    return {"evolution_chains": evolution_chains, "summary": summary}


def generate_mermaid(evolution_chains: list[dict]) -> str:
    lines = ["flowchart TD"]
    for ci, chain in enumerate(evolution_chains):
        versions = chain.get("versions", [])
        prev_node = None
        for i, v in enumerate(versions):
            version_str = v.get("version", "").replace(".", "_")
            title = v.get("title", "")
            remaining = v.get("boundary_issues_remaining", [])
            resolved = v.get("boundary_issues_resolved", [])

            if remaining and resolved:
                label = f"🟡 {title}"
            elif remaining:
                label = f"🔴 {title}"
            elif resolved:
                label = f"🟢 {title}"
            else:
                label = title

            node_id = f"chain{ci}_{version_str}"
            lines.append(f'    {node_id}["{label}"]')

            if prev_node:
                if resolved:
                    lines.append(f"    {prev_node} -->|解决| {node_id}")
                elif remaining and not resolved:
                    lines.append(f"    {prev_node} -->|未解决| {node_id}")
                else:
                    lines.append(f"    {prev_node} --> {node_id}")
            prev_node = node_id

    return "\n".join(lines)


def run_gap_analysis(client, doc_index: dict, analyses: list[dict],
                     categories: list[dict], text_model: str,
                     feature_dims: list[str] = None) -> dict:
    boundary_data = []
    for a in analyses:
        doc_id = a.get("doc_id", "")
        boundary_data.append({
            "doc_id": doc_id,
            "boundary_in": a.get("boundary_in", []),
            "boundary_out": a.get("boundary_out", []),
            "category": a.get("category", ""),
        })

    if feature_dims:
        feature_dimensions = feature_dims
    else:
        extraction_prompt = load_prompt("feature-extraction.md")
        if not extraction_prompt:
            print("  警告：未找到功能提取Prompt文件，使用boundary_in作为维度", file=sys.stderr)
            feature_dimensions = list(set(
                bi for bd in boundary_data for bi in bd.get("boundary_in", [])
            ))
        else:
            user_msg = (f"## 所有文档的边界信息\n"
                        f"{json.dumps(boundary_data, ensure_ascii=False, indent=2)}\n\n"
                        f"## 文档分类\n"
                        f"{json.dumps(categories, ensure_ascii=False, indent=2)}")

            result = call_llm(client, extraction_prompt, user_msg, text_model)
            raw_dims = result.get("feature_dimensions", [])
            if isinstance(raw_dims, list):
                feature_dimensions = []
                for d in raw_dims:
                    if isinstance(d, str):
                        feature_dimensions.append(d)
                    elif isinstance(d, dict):
                        feature_dimensions.append(d.get("name", ""))
            else:
                feature_dimensions = list(set(
                    bi for bd in boundary_data for bi in bd.get("boundary_in", [])
                ))

    coverage_matrix = []
    for dim in feature_dimensions:
        covered_by = []
        for a in analyses:
            boundary_in = a.get("boundary_in", [])
            core_problem = a.get("core_problem", "")
            doc_id = a.get("doc_id", "")
            doc_version = a.get("version", "")
            check_text = " ".join(boundary_in) + " " + core_problem
            if dim.lower() in check_text.lower() or any(
                    dim.lower() in bi.lower() for bi in boundary_in):
                covered_by.append(doc_version or doc_id)

        if covered_by:
            status = "overlap" if len(covered_by) > 1 else "covered"
        else:
            status = "gap"
        coverage_matrix.append({
            "feature": dim,
            "covered_by": covered_by,
            "status": status,
        })

    gaps = [cm for cm in coverage_matrix if cm["status"] == "gap"]
    overlaps = [cm for cm in coverage_matrix if cm["status"] == "overlap"]

    gap_assessments = []
    if gaps:
        assessment_prompt = load_prompt("gap-assessment.md")
        if assessment_prompt:
            user_msg = (f"## 功能覆盖矩阵\n"
                        f"{json.dumps(coverage_matrix, ensure_ascii=False, indent=2)}\n\n"
                        f"## 缺口列表\n"
                        f"{json.dumps(gaps, ensure_ascii=False, indent=2)}\n\n"
                        f"## 重叠列表\n"
                        f"{json.dumps(overlaps, ensure_ascii=False, indent=2)}\n\n"
                        f"## 文档分类\n"
                        f"{json.dumps(categories, ensure_ascii=False, indent=2)}")

            result = call_llm(client, assessment_prompt, user_msg, text_model)
            gap_assessments = result.get("gap_assessments", [])
            overlap_assessments = result.get("overlap_assessments", [])

            for i, g in enumerate(gaps):
                if i < len(gap_assessments):
                    g["description"] = gap_assessments[i].get("impact", "")
                    g["severity"] = gap_assessments[i].get("severity", "medium")
                    g["suggestion"] = gap_assessments[i].get("suggestion", "")

            for i, o in enumerate(overlaps):
                if i < len(overlap_assessments):
                    oa = overlap_assessments[i]
                    o["note"] = oa.get("note", o.get("note", ""))
    else:
        overlap_assessments = []

    gaps_final = [{"feature": g["feature"],
                    "description": g.get("description", ""),
                    "severity": g.get("severity", "medium"),
                    "suggestion": g.get("suggestion", "")} for g in gaps]

    overlaps_final = [{"feature": o["feature"],
                        "covered_by": o["covered_by"],
                        "note": o.get("note", "")} for o in overlaps]

    covered_count = len([cm for cm in coverage_matrix if cm["status"] in ("covered", "overlap")])

    return {
        "feature_dimensions": feature_dimensions,
        "coverage_matrix": coverage_matrix,
        "gaps": gaps_final,
        "overlaps": overlaps_final,
        "summary": {
            "total_features": len(feature_dimensions),
            "covered": covered_count,
            "gaps": len(gaps_final),
            "overlap_count": len(overlaps_final),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="需求洞察（演进追踪+缺口分析）")
    parser.add_argument("classify_json", help="prd-overview-classify输出JSON路径")
    parser.add_argument("analysis_dir", help="prd-per-analysis输出目录")
    parser.add_argument("output_json", help="输出JSON文件路径")
    parser.add_argument("--output-type", default=OUTPUT_TYPE_ALL,
                        choices=VALID_OUTPUT_TYPES,
                        help="输出类型（默认：all）")
    parser.add_argument("--feature-dims", default="",
                        help="自定义功能维度JSON路径（跳过LLM提取）")
    parser.add_argument("--include-mermaid", action="store_true",
                        help="在输出中包含Mermaid演进图")
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

    print("=== 需求洞察 ===")
    print(f"输出类型：{args.output_type}")
    print(f"文本引擎：{text_model}")

    classify_data = load_classify_result(classify_path)
    analyses = load_analysis_results(analysis_dir)
    project_name = classify_data.get("project_name", classify_path.stem)

    print(f"项目：{project_name} | 文档数：{len(classify_data.get('documents', []))} | 分析结果：{len(analyses)}篇")

    version_chains = classify_data.get("version_chains", [])
    categories = classify_data.get("categories", [])
    doc_index = build_doc_index(analyses, classify_data)

    feature_dims = None
    if args.feature_dims:
        try:
            with open(args.feature_dims, "r", encoding="utf-8") as f:
                dims_data = json.load(f)
                feature_dims = dims_data if isinstance(dims_data, list) else dims_data.get("feature_dimensions", [])
            print(f"使用自定义功能维度：{len(feature_dims)}个")
        except Exception as e:
            print(f"警告：加载功能维度失败：{e}", file=sys.stderr)

    evolution_result = None
    gap_result = None

    if args.output_type in [OUTPUT_TYPE_EVOLUTION, OUTPUT_TYPE_ALL]:
        print(f"\n正在执行演进追踪（{len(version_chains)}条版本链）...")
        evolution_result = run_evolution_tracking(
            client, doc_index, version_chains, analyses, text_model)
        summary = evolution_result.get("summary", {})
        print(f"  ✓ 演进追踪完成：{summary.get('total_issues', 0)}个问题，"
              f"{summary.get('resolved', 0)}已解决，"
              f"{summary.get('partial', 0)}部分，"
              f"{summary.get('unresolved', 0)}未解决")

        if args.include_mermaid:
            evolution_result["mermaid_graph"] = generate_mermaid(
                evolution_result.get("evolution_chains", []))
            print(f"  ✓ Mermaid图已生成")

    if args.output_type in [OUTPUT_TYPE_GAP, OUTPUT_TYPE_ALL]:
        print(f"\n正在执行缺口分析...")
        gap_result = run_gap_analysis(
            client, doc_index, analyses, categories, text_model, feature_dims)
        gap_summary = gap_result.get("summary", {})
        print(f"  ✓ 缺口分析完成：{gap_summary.get('total_features', 0)}个功能维度，"
              f"{gap_summary.get('gaps', 0)}个缺口，"
              f"{gap_summary.get('overlap_count', 0)}个重叠")

    result = InsightsResult(
        project_name=project_name,
        output_type=args.output_type,
        evolution=evolution_result,
        gap_analysis=gap_result,
        metadata=InsightsMetadata(
            total_docs=len(classify_data.get("documents", [])),
            output_type=args.output_type,
            models_used={"text": text_model},
        ),
    )

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2, ensure_ascii=False))

    print(f"\n结果已保存至：{output_path}")


if __name__ == "__main__":
    main()
