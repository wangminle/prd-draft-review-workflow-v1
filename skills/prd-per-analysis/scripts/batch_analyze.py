#!/usr/bin/env python3
"""prd-per-analysis 批量模式：并发分析多篇PRD文档。

用法:
    python3 batch_analyze.py <classify_result_json> <output_dir> [options]

输入: prd-overview-classify 的输出JSON
输出: 每篇文档的分析JSON + 批量摘要

增量分析:
    默认跳过已存在且源文件未变化的分析结果。
    使用 --force 强制重新分析全部文档。
    缓存键由内容哈希、Prompt 版本和模型版本组成。
"""

import argparse
import asyncio
import hashlib
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

# 缓存键版本，Prompt 或分析逻辑变更时递增。
# v3: 增加 review_context_version 维度，使 ReviewContext（评分规则、规范等）
# 变更时缓存自动失效。
CACHE_KEY_VERSION = "3"

# 受控原文摘要的最大字符数。
EXCERPT_MAX_CHARS = 2000


class BatchSummary(BaseModel):
    total_docs: int = 0
    analyzed: int = 0
    failed: int = 0
    cached: int = 0
    avg_quality_score: float = 0.0
    avg_confidence: float = 0.0
    total_boundary_issues: int = 0
    results: list[dict] = Field(default_factory=list)


def load_classify_result(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_content_hash(md_path: Path, text_model: str,
                          review_context_version: str = "") -> str:
    """计算缓存键：内容哈希 + Prompt 版本 + 模型版本 + ReviewContext 版本。

    当源文件内容、分析逻辑版本、模型或 ReviewContext（评分规则、规范、
    目标能力基线等）发生变化时，缓存自动失效。
    """
    try:
        content = md_path.read_text(encoding="utf-8")
    except Exception:
        content = ""
    raw = f"{CACHE_KEY_VERSION}:{text_model}:{review_context_version}:{content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def is_cache_valid(result_path: Path, md_path: Path, text_model: str,
                    review_context_version: str = "") -> bool:
    """检查缓存是否有效：输出文件存在且内容哈希匹配。"""
    if not result_path.exists():
        return False
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        return False
    expected_hash = compute_content_hash(md_path, text_model, review_context_version)
    return existing.get("_cache_hash") == expected_hash


def _load_analysis_if_exists(output_dir: Path, doc_id: str) -> Optional[dict]:
    """如果输出目录中已存在该文档的分析结果，则加载。"""
    candidate = output_dir / f"{doc_id}.json"
    if candidate.exists():
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _build_excerpt(md_path: str, max_chars: int = EXCERPT_MAX_CHARS) -> str:
    """从 Markdown 文件中提取受控长度的原文摘要。"""
    if not md_path or not Path(md_path).exists():
        return ""
    try:
        content = Path(md_path).read_text(encoding="utf-8")
    except Exception:
        return ""
    if len(content) > max_chars:
        return content[:max_chars] + "\n...(截断)"
    return content


def build_context_for_doc(doc: dict, all_docs: list[dict], version_chains: list[dict],
                           output_dir: Path = None) -> dict:
    """构建上下文，包含后续文档的结构化分析内容和原文摘要。

    如果 output_dir 中已存在后续文档的分析结果，则注入其 core_problem、
    boundary_in、boundary_out、key_points 和原文摘要，使解决追踪有据可依。
    否则回退到仅包含元数据（与旧行为兼容）。
    """
    doc_id = doc.get("doc_id", "")

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
                    sub_id = subsequent_doc.get("doc_id", "")
                    entry = {
                        "doc_id": sub_id,
                        "version": subsequent_doc.get("version", ""),
                        "title": subsequent_doc.get("title", ""),
                    }
                    # 注入已有分析结果的结构化内容。
                    if output_dir:
                        analysis = _load_analysis_if_exists(output_dir, sub_id)
                        if analysis:
                            entry["core_problem"] = analysis.get("core_problem", "")
                            entry["boundary_in"] = analysis.get("boundary_in", [])
                            entry["boundary_out"] = analysis.get("boundary_out", [])
                            entry["key_points"] = analysis.get("key_points", {})
                    # 注入受控原文摘要。
                    entry["excerpt"] = _build_excerpt(subsequent_doc.get("md_path", ""))
                    subsequent.append(entry)

    return {"other_docs_excerpts": subsequent}


async def analyze_single(doc: dict, context: dict, output_dir: Path, skill_root: Path,
                          enable_vision: bool, text_model: str, vision_model: str,
                          force: bool = False,
                          review_context_version: str = "") -> Optional[dict]:
    md_path_str = doc.get("md_path", "")
    doc_id = doc.get("doc_id", "unknown")

    md_path = Path(md_path_str)
    if not md_path.exists():
        print(f"  [跳过] {doc_id}：Markdown文件不存在")
        return None

    result_path = output_dir / f"{doc_id}.json"

    # 增量缓存：跳过已存在且源文件未变化的结果。
    if not force and is_cache_valid(result_path, md_path, text_model, review_context_version):
        print(f"  [缓存] {doc_id}：源文件未变化，跳过分析")
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)

    context_path = output_dir / f"{doc_id}_context.json"
    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)

    cmd = [
        sys.executable,
        str(skill_root / "scripts" / "analyze.py"),
        md_path_str,
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
            result = json.load(f)

        # 写入缓存哈希，供下次增量判断使用。
        result["_cache_hash"] = compute_content_hash(
            md_path, text_model, review_context_version
        )
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result
    except Exception as e:
        print(f"  [失败] {doc_id}：{e}", file=sys.stderr)
        return None


async def run_batch(classify_path: Path, output_dir: Path, skill_root: Path,
                     enable_vision: bool, max_concurrent: int, text_model: str,
                     vision_model: str, force: bool = False,
                     review_context_version: str = "") -> BatchSummary:
    data = load_classify_result(classify_path)
    docs = data.get("documents", [])
    version_chains = data.get("version_chains", [])
    summary = BatchSummary(total_docs=len(docs))

    print("=== PRD 批量逐篇分析 ===")
    print(f"文档数：{len(docs)} | 并发数：{max_concurrent} | 图片理解：{enable_vision} | 强制重跑：{force}")
    if review_context_version:
        print(f"ReviewContext 版本：{review_context_version}")

    output_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited_analyze(doc):
        async with semaphore:
            context = build_context_for_doc(doc, docs, version_chains, output_dir)
            result = await analyze_single(doc, context, output_dir, skill_root,
                                           enable_vision, text_model, vision_model,
                                           force=force,
                                           review_context_version=review_context_version)
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
            # 区分缓存命中和新分析。
            if "_cache_hash" in result and not force:
                # 检查是否是本次写入的（有 hash 但不是新分析）
                # analyze_single 在缓存命中时直接返回旧结果（已有 hash），
                # 在新分析时写入新 hash。两者都有 _cache_hash，
                # 但缓存命中不会打印 [缓存] 以外的日志。
                pass
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
    parser.add_argument("--force", action="store_true",
                        help="强制重新分析全部文档，忽略增量缓存")
    parser.add_argument("--skill-root", default=str(Path(__file__).parent.parent), help="Skill根目录")
    parser.add_argument("--review-context-version", default="",
                        help="ReviewContext 版本哈希（变更时使缓存失效；通常由调用方计算并传入）")
    args = parser.parse_args()

    classify_path = Path(args.classify_result)
    if not classify_path.exists():
        print(f"错误：分类结果文件不存在：{classify_path}", file=sys.stderr)
        sys.exit(1)

    text_model = os.environ.get("TEXT_MODEL", "claude-sonnet-4-20250514")
    vision_model = os.environ.get("VISION_MODEL", "claude-sonnet-4-20250514")

    summary = asyncio.run(run_batch(
        classify_path, Path(args.output_dir), Path(args.skill_root),
        args.enable_vision, args.max_concurrent, text_model, vision_model,
        force=args.force,
        review_context_version=args.review_context_version,
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
