#!/usr/bin/env python3
"""prd-per-analysis 批量模式：并发分析多篇PRD文档。

用法:
    python batch_analyze.py <classify_result_json> <output_dir> [options]

输入: prd-overview-classify 的输出JSON
输出: 每篇文档的分析JSON + 批量摘要
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    print("错误：需要 pydantic，请运行 pip install pydantic", file=sys.stderr)
    sys.exit(1)


class BatchSummary(BaseModel):
    total_docs: int = 0
    analyzed: int = 0
    failed: int = 0
    avg_quality_score: float = 0.0
    avg_confidence: float = 0.0
    total_boundary_issues: int = 0
    results: list[dict] = Field(default_factory=list)


def load_classify_result(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_context_for_doc(doc: dict, all_docs: list[dict], version_chains: list[dict]) -> dict:
    doc_id = doc.get("doc_id", "")
    doc_version = doc.get("version", "")

    subsequent = []
    for chain in version_chains:
        versions = chain.get("versions", [])
        found_idx = -1
        for i, v in enumerate(versions):
            if v.get("doc_id") == doc_id:
                found_idx = i
                break
        if found_idx >= 0:
            for v in versions[found_idx + 1:]:
                subsequent_doc = next((d for d in all_docs if d.get("doc_id") == v.get("doc_id")), None)
                if subsequent_doc:
                    subsequent.append({
                        "doc_id": subsequent_doc.get("doc_id", ""),
                        "version": subsequent_doc.get("version", ""),
                        "title": subsequent_doc.get("title", ""),
                    })

    return {"other_docs_excerpts": subsequent}


async def analyze_single(doc: dict, context: dict, output_dir: Path, skill_root: Path,
                          enable_vision: bool, text_model: str, vision_model: str) -> Optional[dict]:
    md_path = doc.get("md_path", "")
    doc_id = doc.get("doc_id", "unknown")

    if not Path(md_path).exists():
        print(f"  [跳过] {doc_id}：Markdown文件不存在")
        return None

    context_path = output_dir / f"{doc_id}_context.json"
    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)

    result_path = output_dir / f"{doc_id}.json"

    cmd = [
        sys.executable,
        str(skill_root / "scripts" / "analyze.py"),
        md_path,
        str(result_path),
        "--doc-id", doc_id,
        "--category", doc.get("category", ""),
        "--version", doc.get("version", ""),
        "--context", str(context_path),
    ]

    if enable_vision:
        cmd.append("--enable-vision")

    env = os.environ.copy()
    env["TEXT_MODEL"] = text_model
    env["VISION_MODEL"] = vision_model

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"  [失败] {doc_id}：{stderr.decode()[:200]}", file=sys.stderr)
            return None

        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [失败] {doc_id}：{e}", file=sys.stderr)
        return None


async def run_batch(classify_path: Path, output_dir: Path, skill_root: Path,
                     enable_vision: bool, max_concurrent: int, text_model: str,
                     vision_model: str) -> BatchSummary:
    data = load_classify_result(classify_path)
    docs = data.get("documents", [])
    version_chains = data.get("version_chains", [])
    summary = BatchSummary(total_docs=len(docs))

    print("=== PRD 批量逐篇分析 ===")
    print(f"文档数：{len(docs)} | 并发数：{max_concurrent} | 图片理解：{enable_vision}")

    output_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited_analyze(doc):
        async with semaphore:
            context = build_context_for_doc(doc, docs, version_chains)
            result = await analyze_single(doc, context, output_dir, skill_root,
                                           enable_vision, text_model, vision_model)
            return doc.get("doc_id", ""), result

    tasks = [limited_analyze(doc) for doc in docs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for item in results:
        if isinstance(item, Exception):
            summary.failed += 1
            continue
        doc_id, result = item
        if result is None:
            summary.failed += 1
        else:
            summary.analyzed += 1
            summary.results.append(result)
            summary.total_boundary_issues += len(result.get("boundary_issues", []))
            qs = result.get("quality_score", 0)
            cf = result.get("confidence", 0)
            summary.avg_quality_score += qs
            summary.avg_confidence += cf

    if summary.analyzed > 0:
        summary.avg_quality_score /= summary.analyzed
        summary.avg_confidence /= summary.analyzed

    return summary


def main():
    parser = argparse.ArgumentParser(description="批量逐篇分析PRD文档")
    parser.add_argument("classify_result", help="prd-overview-classify输出JSON路径")
    parser.add_argument("output_dir", help="分析结果输出目录")
    parser.add_argument("--enable-vision", action="store_true", help="启用图片理解引擎")
    parser.add_argument("--max-concurrent", type=int, default=3, help="最大并发数（默认：3）")
    parser.add_argument("--skill-root", default=str(Path(__file__).parent.parent), help="Skill根目录")
    args = parser.parse_args()

    classify_path = Path(args.classify_result)
    if not classify_path.exists():
        print(f"错误：分类结果文件不存在：{classify_path}", file=sys.stderr)
        sys.exit(1)

    text_model = os.environ.get("TEXT_MODEL", "claude-sonnet-4-20250514")
    vision_model = os.environ.get("VISION_MODEL", "claude-sonnet-4-20250514")

    summary = asyncio.run(run_batch(
        classify_path, Path(args.output_dir), Path(args.skill_root),
        args.enable_vision, args.max_concurrent, text_model, vision_model
    ))

    summary_path = Path(args.output_dir) / "_batch_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary.model_dump_json(indent=2, ensure_ascii=False))

    print(f"\n批量分析完成：{summary.analyzed}/{summary.total_docs} 篇已分析，{summary.failed} 篇失败")
    print(f"平均质量评分：{summary.avg_quality_score:.1f} | 平均置信度：{summary.avg_confidence:.2f}")
    print(f"边界外问题总计：{summary.total_boundary_issues} 条")
    print(f"摘要已保存至：{summary_path}")


if __name__ == "__main__":
    main()
