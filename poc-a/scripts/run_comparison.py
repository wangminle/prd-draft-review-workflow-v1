"""POC-A.6: 对比报告生成器。

读取所有方案的评估结果 JSON，生成对比表格和决策建议。
包含 FTS5、LanceDB、Milvus Lite、Chroma 和 sqlite-vec 五个方案。
"""

import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def load_eval_results() -> dict:
    """加载所有方案的评估结果。"""
    results = {}
    for f in RESULTS_DIR.glob("*_eval.json"):
        name = f.stem.replace("_eval", "")
        data = json.loads(f.read_text(encoding="utf-8"))
        results[name] = data
    return results


def load_metrics() -> dict:
    """加载所有方案的额外指标。"""
    metrics = {}
    for f in RESULTS_DIR.glob("*_metrics.json"):
        name = f.stem.replace("_metrics", "")
        data = json.loads(f.read_text(encoding="utf-8"))
        metrics[name] = data
    return metrics


def generate_comparison_report(eval_results: dict, metrics: dict) -> str:
    """生成对比报告 Markdown。"""
    report = []
    report.append("# POC-A 检索方案对比报告")
    report.append("")
    report.append("> 基于 30 份样例文档、30 个检索问题、10 个权限过滤用例的统一评估。")
    report.append("> 嵌入方法: TF-IDF fallback（如后续使用 OpenAI/BGE 嵌入，命中率将显著提升）")
    report.append("> sqlite-vec 因维度上限 8192，TF-IDF 从 16940 维降维到 8192 维（混合选取策略）")
    report.append("")
    report.append("## 1. 方案总览")
    report.append("")
    report.append("| 方案 | 存储方式 | 依赖包 | 权限过滤 | 备份恢复 | runtime 兼容 |")
    report.append("| --- | --- | --- | --- | --- | --- |")

    solutions = {
        "fts5_baseline": ("SQLite FTS5", "内置（零依赖）", "SQL WHERE", "文件复制", "✅ 天然兼容"),
        "lancedb_tfidf": ("LanceDB", "lancedb+pyarrow", "metadata filter", "目录复制", "✅ runtime/ 目录"),
        "milvus_lite_tfidf": ("Milvus Lite", "pymilvus+milvus_lite", "metadata filter", "文件复制", "⚠️ 需验证进程锁"),
        "chroma_tfidf": ("Chroma", "chromadb", "collection 分离", "目录复制", "✅ runtime/ 目录"),
        "sqlite_vec_tfidf": ("sqlite-vec", "sqlite-vec+pysqlite3", "partition key", "文件复制", "✅ 天然兼容"),
    }

    for name, (storage, deps, perm, backup, runtime) in solutions.items():
        if name in eval_results or name in metrics:
            report.append(f"| {storage} | {deps} | {perm} | {backup} | {runtime} |")

    report.append("")
    report.append("## 2. 检索质量对比")
    report.append("")
    report.append("| 方案 | 嵌入维度 | top-5 命中率 | top-1 命中率 | 平均延迟(ms) | 权限正确率 | 数据大小(KB) |")
    report.append("| --- | --- | --- | --- | --- | --- | --- |")

    for name, data in eval_results.items():
        sol_info = solutions.get(name, (name, "", "", "", ""))
        m = metrics.get(name, {})
        dim = m.get("embedding_dim", "N/A")
        report.append(f"| {sol_info[0]} | {dim} | {data['top5_hit_rate']:.1%} | {data['top1_hit_rate']:.1%} "
                      f"| {data['avg_latency_ms']:.1f} | {data['permission_accuracy']:.1%} "
                      f"| {m.get('db_size_kb', 'N/A')} |")

    report.append("")
    report.append("## 3. 分类别命中率")
    report.append("")
    report.append("| 方案 | 章节查找 | 风险定位 | 术语解释 | 跨文档对比 | 无答案 |")
    report.append("| --- | --- | --- | --- | --- | --- |")

    for name, data in eval_results.items():
        sol_info = solutions.get(name, (name, "", "", "", ""))
        cats = data.get("category_hit_rates", {})
        report.append(f"| {sol_info[0]} | {cats.get('section_find', 0):.1%} "
                      f"| {cats.get('risk_find', 0):.1%} "
                      f"| {cats.get('term_explain', 0):.1%} "
                      f"| {cats.get('cross_doc', 0):.1%} "
                      f"| {cats.get('no_answer', 0):.1%} |")

    report.append("")
    report.append("## 4. 关键指标详细分析")
    report.append("")
    report.append("### 4.1 各问题命中详情")
    report.append("")
    report.append("| QID | 问题 | FTS5 | LanceDB | Milvus Lite | Chroma | sqlite-vec |")
    report.append("| --- | --- | --- | --- | --- | --- | --- |")

    # 对齐所有方案的同一问题
    question_ids = []
    if eval_results:
        first = list(eval_results.values())[0]
        question_ids = [d["qid"] for d in first["details"]]

    for qid in question_ids:
        q_text = ""
        hits = {}
        for name, data in eval_results.items():
            for d in data["details"]:
                if d["qid"] == qid:
                    q_text = d["query"]
                    sol_info = solutions.get(name, (name, "", "", "", ""))
                    top_ids = [r["source_id"] for r in d["top_results"][:5]]
                    hits[sol_info[0]] = "✅" if d["hit"] else "❌"
                    if not top_ids:
                        hits[sol_info[0]] = "∅"
                    break

        fts5_hit = hits.get("SQLite FTS5", "-")
        lance_hit = hits.get("LanceDB", "-")
        milvus_hit = hits.get("Milvus Lite", "-")
        chroma_hit = hits.get("Chroma", "-")
        sqlite_vec_hit = hits.get("sqlite-vec", "-")
        report.append(f"| {qid} | {q_text} | {fts5_hit} | {lance_hit} | {milvus_hit} | {chroma_hit} | {sqlite_vec_hit} |")

    report.append("")
    report.append("## 5. 优劣势分析")
    report.append("")

    for name, info in solutions.items():
        sol_name = info[0]
        report.append(f"### {sol_name}")
        report.append("")
        if name in eval_results:
            data = eval_results[name]
            m = metrics.get(name, {})
            report.append(f"- **命中率**: top-5 {data['top5_hit_rate']:.1%}, top-1 {data['top1_hit_rate']:.1%}")
            report.append(f"- **延迟**: {data['avg_latency_ms']:.1f} ms")
            report.append(f"- **权限过滤**: {data['permission_accuracy']:.1%}")
            report.append(f"- **数据大小**: {m.get('db_size_kb', 'N/A')} KB")
            report.append(f"- **备份恢复**: {m.get('backup_recovery', '未测试')}")
            report.append(f"- **runtime 兼容**: {info[4]}")
            report.append(f"- **依赖**: {info[1]}")
            # sqlite-vec specific notes
            if name == "sqlite_vec_tfidf":
                report.append(f"- **维度限制**: sqlite-vec 最大 8192 维，TF-IDF 原始 16940 维需降维")
                report.append(f"- **降维策略**: tier1 (freq≥2 的常见词项) + tier2 (最高 IDF 罕见词项)")
                report.append(f"- **降维影响**: POC baseline 下 sqlite-vec 命中率 73.3% 高于 LanceDB 66.7%，但低于完整 TF-IDF 方案的上限（8192 vs 16940 维导致部分查询词项丢失）")
                report.append(f"- **Python 限制**: Python 3.13 移除 load_extension，需 pysqlite3 替代")
                report.append(f"- **生产环境**: 使用真实嵌入模型（OpenAI 1536/BGE-M3 1024）时维度限制不构成问题")
        else:
            report.append("- **未完成 POC 实验**")
        report.append("")

    report.append("## 6. 决策建议")
    report.append("")
    report.append("### Phase 2 首选方案")
    report.append("")
    report.append("基于以上对比数据，推荐以下方案组合：")
    report.append("")
    report.append("```")
    report.append("FTS5（关键词检索） + LanceDB（语义检索）")
    report.append("混合检索：先 FTS5 快速召回 → LanceDB 语义排序 → 合并 top-k")
    report.append("```")
    report.append("")
    report.append("### sqlite-vec 作为替代方案评估")
    report.append("")
    report.append("sqlite-vec 的定位：")
    report.append("- **优势**: 向量检索留在 SQLite 内，不引入新存储引擎；partition key 天然隔离 workspace；单文件备份")
    report.append("- **劣势**: POC baseline 下因维度限制部分查询词项丢失，top-1 命中率 43.3% 低于 LanceDB 53.3%；缺少 IVF-PQ 等高级索引；Python 3.13 需额外 pysqlite3 依赖")
    report.append("- **生产可行性**: 使用真实嵌入模型（≤8192 维）时维度限制不构成问题，命中率应与 LanceDB 相当")
    report.append("- **决策**: sqlite-vec 不作为 P2 MVP 首选，但作为 LanceDB 的轻量替代备选。若 P2 后期需要简化依赖栈（去掉 LanceDB/pyarrow），可评估迁移到 sqlite-vec")
    report.append("")
    report.append("### 决策门槛")
    report.append("")
    report.append("- top-5 命中率 ≥ 80%（使用真实嵌入模型后）")
    report.append("- 权限过滤正确率 = 100%（零越权召回）")
    report.append("- 平均延迟 < 1s（FTS）/ < 3s（混合）")
    report.append("- 备份恢复可通过文件/目录复制完成")
    report.append("- 数据存储兼容 runtime/ 数据隔离原则")

    return "\n".join(report)


def run_comparison():
    """生成对比报告。"""
    REPORTS_DIR.mkdir(exist_ok=True)

    eval_results = load_eval_results()
    metrics = load_metrics()

    if not eval_results:
        print("⚠️ 尚无评估结果，请先运行各方案的 POC 实验")
        return

    print(f"已加载 {len(eval_results)} 个方案的评估结果")
    for name, data in eval_results.items():
        print(f"  {name}: top-5={data['top5_hit_rate']:.1%}, top-1={data['top1_hit_rate']:.1%}, "
              f"latency={data['avg_latency_ms']:.1f}ms, perm={data['permission_accuracy']:.1%}")

    report = generate_comparison_report(eval_results, metrics)
    report_path = REPORTS_DIR / "POC-A-对比报告.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n对比报告已写入: {report_path}")

    # 同时输出到终端
    print("\n" + report)


if __name__ == "__main__":
    run_comparison()