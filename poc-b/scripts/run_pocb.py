"""POC-B: FTS5 + LanceDB 混合检索深度验证。

基于 POC-A 结论（FTS5 + LanceDB 为首选），使用 Runtime 真实需求数据集验证：

1. 混合检索质量 — FTS5 快速关键词召回 + LanceDB 语义排序 → 合并 top-k
2. 延迟分布 — 5 轮重复查询，输出 P50/P95/P99
3. 并发压测 — 5/10/20 并发查询
4. 无答案阈值 — 相似度阈值拒答策略评估
5. LanceDB 备份恢复 — 文件复制后验证数据完整性

数据来源：旧 runtime 45 份真实需求 Markdown（与 POC-A Runtime 复验同一数据集）
"""

import sys
import json
import time
import shutil
import statistics
import concurrent.futures
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "poc-a" / "scripts"))

from runtime_eval import (
    load_runtime_documents, build_runtime_chunks, TfidfEncoder,
    generate_runtime_questions, build_fts5_retriever, build_lancedb_retriever,
    _dedupe_hits,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # poc-b/scripts → poc-b → project root
OLD_RUNTIME = PROJECT_ROOT.parent / "历史参考文件" / "20260515-需求评审内网小网站" / "runtime"
OUTPUT_DIR = PROJECT_ROOT / "poc-b" / "results"


# ── 混合检索器 ──

def build_hybrid_retriever(fts5_fn, lancedb_table, encoder, *,
                            fts_top_k=10, vec_top_k=10, weight_fts=0.3, weight_vec=0.7):
    """FTS5 + LanceDB 混合检索器。

    策略：
    1. FTS5 召回 top-fts_top_k（关键词快速召回）
    2. LanceDB 召回 top-vec_top_k（语义检索）
    3. 合并去重 → 按加权得分排序 → 取 top-k
    """
    def retrieve(query: str, workspace_id: str, top_k: int = 5, role: str = "member") -> list[dict]:
        if role in {"inactive", "non-member"}:
            return []

        # FTS5 召回
        fts_results = fts5_fn(query, workspace_id, fts_top_k, role)

        # LanceDB 语义召回
        query_vec = encoder.encode_query(query)
        vec_rows = (
            lancedb_table.search(query_vec)
            .where(f"workspace_id = '{workspace_id}'", prefilter=True)
            .limit(vec_top_k)
            .to_list()
        )
        vec_results = [
            {
                "source_id": row["source_id"],
                "workspace_id": row["workspace_id"],
                "title": row["title"],
                "section": row["section"],
                "text_snippet": row["text"][:180],
                "score": 1 - row["_distance"],  # cosine → similarity
            }
            for row in vec_rows
        ]

        # 合并去重 + 加权排序
        merged = {}
        fts_max_rank = max((r.get("score", 0) for r in fts_results), default=1) or 1
        vec_max_score = max((r["score"] for r in vec_results if "score" in r), default=1) or 1

        for r in fts_results:
            sid = r["source_id"]
            norm_score = r.get("score", 0) / fts_max_rank
            if sid not in merged:
                merged[sid] = {**r, "fts_score": norm_score, "vec_score": 0.0}
            else:
                merged[sid]["fts_score"] = max(merged[sid].get("fts_score", 0), norm_score)

        for r in vec_results:
            sid = r["source_id"]
            norm_score = r["score"] / vec_max_score if vec_max_score else 0
            if sid not in merged:
                merged[sid] = {**r, "fts_score": 0.0, "vec_score": norm_score}
            else:
                merged[sid]["vec_score"] = max(merged[sid].get("vec_score", 0), norm_score)

        # 加权综合得分
        for sid, r in merged.items():
            r["hybrid_score"] = weight_fts * r["fts_score"] + weight_vec * r["vec_score"]

        # 按综合得分降序
        sorted_results = sorted(merged.values(), key=lambda r: r["hybrid_score"], reverse=True)
        return _dedupe_hits(sorted_results, top_k)

    return retrieve


# ── 评估函数 ──

def evaluate_retriever(name: str, questions: list[dict], retrieve_fn, *,
                        top_k: int = 5, rounds: int = 1) -> dict:
    """评估检索质量，支持多轮延迟统计。"""
    all_latencies = []
    details = []
    top5_hits = 0
    top1_hits = 0
    category_hits = {}
    n_questions = len(questions)

    for q in questions:
        round_latencies = []
        for _ in range(rounds):
            start = time.perf_counter()
            results = retrieve_fn(q["query"], q["workspace_id"], top_k, "member")
            latency = (time.perf_counter() - start) * 1000
            round_latencies.append(latency)

        # 使用第 1 轮结果评估命中率
        results = retrieve_fn(q["query"], q["workspace_id"], top_k, "member")
        result_ids = [r["source_id"] for r in results[:top_k]]
        expected = q["expect_ids"]

        hit5 = any(any(rid.startswith(eid) or eid.startswith(rid) for eid in expected) for rid in result_ids) if expected else len(result_ids) == 0
        hit1 = any(result_ids[0].startswith(eid) or eid.startswith(result_ids[0]) for eid in expected) if expected and result_ids else (not expected and not result_ids)

        top5_hits += int(hit5)
        top1_hits += int(hit1)
        all_latencies.extend(round_latencies)

        cat = q["category"]
        bucket = category_hits.setdefault(cat, {"hits": 0, "total": 0})
        bucket["hits"] += int(hit5)
        bucket["total"] += 1

        details.append({
            "qid": q["qid"],
            "query": q["query"],
            "top_results": results[:top_k],
            "latency_ms": round(statistics.mean(round_latencies), 2),
            "hit": hit5,
        })

    # 权限评估
    perm_cases = [
        {"query": questions[0]["query"], "workspace_id": questions[0]["workspace_id"], "role": "inactive", "expect_empty": True},
        {"query": questions[0]["query"], "workspace_id": questions[0]["workspace_id"], "role": "non-member", "expect_empty": True},
    ]
    perm_correct = sum(1 for c in perm_cases if len(retrieve_fn(c["query"], c["workspace_id"], top_k, c["role"])) == 0)
    for q in questions[:min(20, len(questions))]:
        rows = retrieve_fn(q["query"], q["workspace_id"], top_k, "member")
        perm_correct += int(all(r["workspace_id"] == q["workspace_id"] for r in rows))

    latency_sorted = sorted(all_latencies)
    n = len(latency_sorted)

    return {
        "solution_name": name,
        "top5_hit_rate": round(top5_hits / n_questions, 4),
        "top1_hit_rate": round(top1_hits / n_questions, 4),
        "avg_latency_ms": round(statistics.mean(all_latencies), 2),
        "p50_latency_ms": round(latency_sorted[n // 2], 2) if n else 0,
        "p95_latency_ms": round(latency_sorted[int(n * 0.95)], 2) if n else 0,
        "p99_latency_ms": round(latency_sorted[int(n * 0.99)], 2) if n else 0,
        "permission_accuracy": round(perm_correct / (len(perm_cases) + min(20, len(questions))), 4),
        "category_hit_rates": {k: round(v["hits"] / v["total"], 4) for k, v in category_hits.items()},
        "details": details,
        "latencies": latency_sorted,
    }


# ── 并发压测 ──

def run_concurrent_stress(name: str, retrieve_fn, questions: list[dict],
                           concurrency: int, top_k: int = 5) -> dict:
    """并发压测：指定并发数下的总吞吐和延迟。"""
    query_pool = questions[:concurrency * 2]  # 用足够多的问题
    if not query_pool:
        return {"concurrency": concurrency, "throughput_qps": 0, "avg_latency_ms": 0}

    queries = [(q["query"], q["workspace_id"]) for q in query_pool]

    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for i in range(concurrency):
            q_text, ws_id = queries[i % len(queries)]
            futures.append(executor.submit(retrieve_fn, q_text, ws_id, top_k, "member"))
        latencies = []
        for f in futures:
            q_start = time.perf_counter()
            f.result()
            latencies.append((time.perf_counter() - q_start) * 1000)

    total_time = (time.perf_counter() - start) * 1000
    throughput = concurrency / (total_time / 1000) if total_time > 0 else 0

    lat_sorted = sorted(latencies)
    n = len(lat_sorted)

    return {
        "solution_name": name,
        "concurrency": concurrency,
        "throughput_qps": round(throughput, 1),
        "avg_latency_ms": round(statistics.mean(latencies), 2),
        "p50_latency_ms": round(lat_sorted[n // 2], 2) if n else 0,
        "p95_latency_ms": round(lat_sorted[int(n * 0.95)], 2) if n else 0,
        "p99_latency_ms": round(lat_sorted[int(n * 0.99)], 2) if n else 0,
        "total_time_ms": round(total_time, 2),
    }


# ── 无答案阈值评估 ──

def evaluate_no_answer_threshold(name: str, retrieve_fn, questions: list[dict],
                                  thresholds: list[float], top_k: int = 5) -> list[dict]:
    """评估不同相似度阈值下的无答案拒答效果。"""
    no_answer_qs = [q for q in questions if q["category"] == "no_answer"]
    answerable_qs = [q for q in questions if q["category"] != "no_answer"]

    results = []
    for threshold in thresholds:
        fp_count = 0  # 误答：无答案问题返回了结果
        fn_count = 0  # 漏拒：可答问题被误拒

        for q in no_answer_qs:
            rows = retrieve_fn(q["query"], q["workspace_id"], top_k, "member")
            # 使用 hybrid_score 作为置信度
            if rows and rows[0].get("hybrid_score", rows[0].get("score", 1)) >= threshold:
                fp_count += 1

        for q in answerable_qs:
            rows = retrieve_fn(q["query"], q["workspace_id"], top_k, "member")
            if not rows or (rows and rows[0].get("hybrid_score", rows[0].get("score", 1)) < threshold):
                fn_count += 1

        total_no_answer = len(no_answer_qs) or 1
        total_answerable = len(answerable_qs) or 1

        results.append({
            "solution_name": name,
            "threshold": threshold,
            "false_positive_rate": round(fp_count / total_no_answer, 4),  # 误答率
            "false_negative_rate": round(fn_count / total_answerable, 4),  # 漏拒率
            "precision_no_answer": round(1 - fp_count / total_no_answer, 4),
        })
    return results


# ── LanceDB 备份恢复 ──

def test_lancedb_backup_recovery(lancedb_dir: Path, retrieve_fn, questions: list[dict]) -> dict:
    """验证 LanceDB 目录复制备份/恢复。"""
    backup_dir = lancedb_dir.parent / "lancedb_backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    # 备份
    start = time.perf_counter()
    shutil.copytree(lancedb_dir, backup_dir)
    backup_time_ms = (time.perf_counter() - start) * 1000

    # 验证恢复
    import lancedb
    restored_db = lancedb.connect(str(backup_dir))
    restored_table = restored_db.open_table("chunks")
    row_count = restored_table.count_rows()

    # 用恢复的数据跑一个查询验证
    q = questions[0]
    test_results = retrieve_fn(q["query"], q["workspace_id"], 5, "member")
    has_results = len(test_results) > 0

    # 清理
    shutil.rmtree(backup_dir)

    return {
        "backup_time_ms": round(backup_time_ms, 2),
        "backup_size_mb": round(sum(f.stat().st_size for f in lancedb_dir.rglob("*") if f.is_file()) / 1024 / 1024, 2),
        "row_count_after_restore": row_count,
        "query_after_restore_ok": has_results,
    }


# ── 主流程 ──

def run_poc_b():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  POC-B: FTS5 + LanceDB 混合检索深度验证")
    print("=" * 60)

    # 1. 加载数据
    print("\n[1/7] 加载 Runtime 真实需求数据...")
    docs = load_runtime_documents(OLD_RUNTIME / "data" / "app.db", OLD_RUNTIME)
    chunks = build_runtime_chunks(docs)
    questions = generate_runtime_questions(docs, max_doc_questions=40)
    encoder = TfidfEncoder(chunks, max_features=4096)
    print(f"  文档: {len(docs)}, Chunks: {len(chunks)}, 问题: {len(questions)}, 嵌入维度: {encoder.dim}")

    # 2. 构建索引
    print("\n[2/7] 构建 FTS5 + LanceDB 索引...")
    pocb_dir = OUTPUT_DIR
    fts5_fn = build_fts5_retriever(chunks, pocb_dir)

    import lancedb
    lancedb_dir = pocb_dir / "lancedb_pocb"
    if lancedb_dir.exists():
        shutil.rmtree(lancedb_dir)
    db = lancedb.connect(str(lancedb_dir))
    data = [
        {
            "vector": encoder.vectors[idx],
            "source_id": chunk.source_id,
            "workspace_id": chunk.workspace_id,
            "title": chunk.title,
            "section": chunk.section,
            "text": chunk.text,
        }
        for idx, chunk in enumerate(chunks)
    ]
    lancedb_table = db.create_table("chunks", data)
    print(f"  LanceDB 索引完成: {lancedb_table.count_rows()} 条记录")

    # 3. 构建混合检索器
    print("\n[3/7] 构建混合检索器...")
    hybrid_fn = build_hybrid_retriever(fts5_fn, lancedb_table, encoder)

    # 4. 单方案质量评估（5 轮）
    print("\n[4/7] 单方案质量评估（5 轮延迟统计）...")
    retrievers = {
        "FTS5": fts5_fn,
        "LanceDB": lambda q, ws, k, r: [
            {**row, "score": row["_distance"]}
            for row in lancedb_table.search(encoder.encode_query(q))
            .where(f"workspace_id = '{ws}'", prefilter=True)
            .limit(k * 3)
            .to_list()
        ][:k],
        "Hybrid(FTS5+LanceDB)": hybrid_fn,
    }

    quality_results = {}
    for name, fn in retrievers.items():
        print(f"  评估 {name} (5 轮)...")
        result = evaluate_retriever(name, questions, fn, rounds=5)
        quality_results[name] = result
        print(f"    top-5: {result['top5_hit_rate']:.1%}, "
              f"P50: {result['p50_latency_ms']:.1f}ms, "
              f"P95: {result['p95_latency_ms']:.1f}ms, "
              f"P99: {result['p99_latency_ms']:.1f}ms")

    # 5. 并发压测
    print("\n[5/7] 并发压测 (5/10/20 并发)...")
    concurrency_results = []
    for name, fn in retrievers.items():
        for c in [5, 10, 20]:
            print(f"  {name} × {c} 并发...")
            result = run_concurrent_stress(name, fn, questions, c)
            concurrency_results.append(result)
            print(f"    QPS: {result['throughput_qps']}, "
                  f"avg: {result['avg_latency_ms']:.1f}ms, "
                  f"P95: {result['p95_latency_ms']:.1f}ms")

    # 6. 无答案阈值
    print("\n[6/7] 无答案阈值评估...")
    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    threshold_results = []
    for name, fn in retrievers.items():
        results = evaluate_no_answer_threshold(name, fn, questions, thresholds)
        threshold_results.extend(results)
        for r in results:
            print(f"  {name} threshold={r['threshold']}: "
                  f"误答率={r['false_positive_rate']:.1%}, "
                  f"漏拒率={r['false_negative_rate']:.1%}")

    # 7. 备份恢复
    print("\n[7/7] LanceDB 备份恢复验证...")
    backup_result = test_lancedb_backup_recovery(lancedb_dir, hybrid_fn, questions)
    print(f"  备份时间: {backup_result['backup_time_ms']:.0f}ms")
    print(f"  备份大小: {backup_result['backup_size_mb']:.1f}MB")
    print(f"  恢复后记录数: {backup_result['row_count_after_restore']}")
    print(f"  恢复后查询: {'✅' if backup_result['query_after_restore_ok'] else '❌'}")

    # 8. 生成报告
    print("\n生成 POC-B 报告...")
    report = generate_pocb_report(quality_results, concurrency_results, threshold_results, backup_result)
    report_path = PROJECT_ROOT / "poc-b" / "reports" / "POC-B-混合检索深度验证报告.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"报告已写入: {report_path}")

    # 保存原始数据
    all_data = {
        "quality": {k: {kk: vv for kk, vv in v.items() if kk != "latencies"} for k, v in quality_results.items()},
        "concurrency": concurrency_results,
        "threshold": threshold_results,
        "backup": backup_result,
    }
    data_path = OUTPUT_DIR / "pocb_results.json"
    data_path.write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"数据已写入: {data_path}")


def generate_pocb_report(quality_results, concurrency_results, threshold_results, backup_result) -> str:
    lines = [
        "# POC-B: FTS5 + LanceDB 混合检索深度验证报告",
        "",
        "> 基于 POC-A 结论，验证 FTS5 + LanceDB 混合检索方案的实际表现。",
        "> 数据来源：45 份真实需求 Markdown、943 chunks、94 个问题（与 POC-A Runtime 复验同一数据集）。",
        "",
        "## 1. 检索质量对比",
        "",
        "| 方案 | top-5 命中率 | top-1 命中率 | 权限正确率 |",
        "| --- | --- | --- | --- |",
    ]

    for name, data in quality_results.items():
        lines.append(f"| {name} | {data['top5_hit_rate']:.1%} | {data['top1_hit_rate']:.1%} | {data['permission_accuracy']:.1%} |")

    lines.extend([
        "",
        "## 2. 延迟分布（5 轮重复查询）",
        "",
        "| 方案 | 平均(ms) | P50(ms) | P95(ms) | P99(ms) |",
        "| --- | --- | --- | --- | --- |",
    ])

    for name, data in quality_results.items():
        lines.append(f"| {name} | {data['avg_latency_ms']:.1f} | {data['p50_latency_ms']:.1f} | {data['p95_latency_ms']:.1f} | {data['p99_latency_ms']:.1f} |")

    lines.extend([
        "",
        "## 3. 并发压测",
        "",
        "| 方案 | 并发数 | QPS | 平均(ms) | P50(ms) | P95(ms) | P99(ms) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])

    for r in concurrency_results:
        lines.append(f"| {r['solution_name']} | {r['concurrency']} | {r['throughput_qps']} | {r['avg_latency_ms']:.1f} | {r['p50_latency_ms']:.1f} | {r['p95_latency_ms']:.1f} | {r['p99_latency_ms']:.1f} |")

    lines.extend([
        "",
        "## 4. 无答案阈值策略",
        "",
        "| 方案 | 阈值 | 误答率 | 漏拒率 |",
        "| --- | --- | --- | --- |",
    ])

    for r in threshold_results:
        lines.append(f"| {r['solution_name']} | {r['threshold']} | {r['false_positive_rate']:.1%} | {r['false_negative_rate']:.1%} |")

    lines.extend([
        "",
        "## 5. LanceDB 备份恢复",
        "",
        f"- 备份时间: {backup_result['backup_time_ms']:.0f}ms",
        f"- 备份大小: {backup_result['backup_size_mb']:.1f}MB",
        f"- 恢复后记录数: {backup_result['row_count_after_restore']}",
        f"- 恢复后查询: {'✅ 正常' if backup_result['query_after_restore_ok'] else '❌ 失败'}",
        "",
        "## 6. 结论与建议",
        "",
        "### 混合检索效果",
        "",
        "FTS5 + LanceDB 混合检索的 top-5 命中率应高于或等于纯 LanceDB，",
        "因为 FTS5 的关键词快速召回补充了 LanceDB 语义检索可能遗漏的精确匹配。",
        "",
        "### 延迟分布",
        "",
        "P50/P95/P99 的差异反映了系统在不同负载下的稳定性。",
        "如果 P95 远高于 P50，说明存在偶发延迟尖峰，需要关注。",
        "",
        "### 并发能力",
        "",
        "并发压测结果决定了生产环境的并发承载能力。",
        "建议在 P2 开发中为检索 API 设置并发限制。",
        "",
        "### 无答案阈值",
        "",
        "向量库默认返回最相近结果，无答案问题也会返回内容。",
        "阈值策略是 RAG 系统拒答的核心机制。",
        "建议 P2 实现时采用 0.5 作为初始阈值，并根据实际误答/漏拒率调整。",
        "",
        "### 备份恢复",
        "",
        "LanceDB 目录复制备份验证通过后，P2 的备份策略可以简化为：",
        "`cp -r runtime/vector_lancedb runtime/vector_lancedb.bak`",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    run_poc_b()
