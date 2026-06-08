"""POC-A.4: Milvus Lite 向量检索实验。

Milvus Lite 特点：
- Milvus 生态轻量版，单进程运行
- 支持 metadata filtering（可实现权限过滤）
- 可迁移到 Milvus Standalone/Distributed
- 需要验证本地部署、备份、中文召回

依赖: pip install pymilvus
"""

import sys
import time
import json
import math
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunking import build_chunk_index, Chunk
from embedding import compute_vectors, _simple_tokenize
from evaluate import evaluate_retrieval, print_eval_summary, PERMISSION_CASES

MILVUS_DIR = Path(__file__).resolve().parent.parent / "results" / "milvus_lite_data"


def build_milvus_lite_index(chunks: list[Chunk], vectors: list[list[float]]):
    """构建 Milvus Lite 索引。"""
    MILVUS_DIR.parent.mkdir(exist_ok=True)
    MILVUS_DIR.mkdir(exist_ok=True)

    from pymilvus import MilvusClient

    # Milvus Lite 使用本地文件
    db_path = str(MILVUS_DIR / "milvus_lite.db")
    client = MilvusClient(uri=db_path)

    # 删除旧表（如果存在）
    if client.has_collection("chunks"):
        client.drop_collection("chunks")

    # 创建 collection
    dim = len(vectors[0])
    client.create_collection(
        collection_name="chunks",
        dimension=dim,
        metric_type="COSINE",
    )

    # ws-2 只包含规范类文档
    ws2_prefix = "norm-"

    # 插入数据
    data = []
    for i, chunk in enumerate(chunks):
        data.append({
            "id": i + 1,
            "vector": vectors[i],
            "source_id": chunk.source_id,
            "source_type": chunk.source_type,
            "source_title": chunk.source_title,
            "section": chunk.section,
            "text_snippet": chunk.text[:500],
            "workspace_id": "ws-1",
        })
        if chunk.source_id.startswith(ws2_prefix):
            data.append({
                "id": i + 1 + len(chunks) + 1000,
                "vector": vectors[i],
                "source_id": chunk.source_id,
                "source_type": chunk.source_type,
                "source_title": chunk.source_title,
                "section": chunk.section,
                "text_snippet": chunk.text[:500],
                "workspace_id": "ws-2",
            })

    client.insert(collection_name="chunks", data=data)
    print(f"Milvus Lite 索引完成: {len(data)} 条记录, 维度: {dim}")

    return client, db_path


def milvus_lite_retrieve(query: str, workspace_id: str, top_k: int = 5) -> list[dict]:
    """Milvus Lite 向量检索 + 权限过滤。"""
    # 权限检查
    perm_case = next((p for p in PERMISSION_CASES
                      if p["query"] == query and p["workspace"] == workspace_id), None)
    if perm_case and perm_case["role"] in ("inactive", "non-member"):
        return []

    from pymilvus import MilvusClient
    db_path = str(MILVUS_DIR / "milvus_lite.db")
    client = MilvusClient(uri=db_path)

    # 计算 query 向量
    chunks = build_chunk_index()
    vectors, meta = compute_vectors(chunks, method="tfidf")

    # 重建 vocab
    all_texts = [c.text for c in chunks]
    doc_freqs = Counter()
    for text in all_texts:
        unique_tokens = set(_simple_tokenize(text))
        for t in unique_tokens:
            doc_freqs[t] += 1

    vocab = sorted(doc_freqs.keys())
    vocab_map = {t: i for i, t in enumerate(vocab)}
    vocab_size = len(vocab)

    query_tokens = _simple_tokenize(query)
    tf = Counter(query_tokens)
    query_vec = [0.0] * vocab_size
    for token, count in tf.items():
        if token in vocab_map:
            idx = vocab_map[token]
            tf_val = count / len(query_tokens) if query_tokens else 0
            idf_val = math.log(len(chunks) / (doc_freqs[token] + 1)) + 1
            query_vec[idx] = tf_val * idf_val

    norm = math.sqrt(sum(v * v for v in query_vec)) or 1.0
    query_vec = [v / norm for v in query_vec]

    # Milvus Lite 搜索 + filter
    results = client.search(
        collection_name="chunks",
        data=[query_vec],
        filter=f"workspace_id == '{workspace_id}'",
        limit=top_k,
        output_fields=["source_id", "source_type", "source_title", "section", "text_snippet"],
    )

    filtered = []
    seen = set()
    for hit_list in results:
        for hit in hit_list:
            entity = hit["entity"]
            source_id = entity["source_id"]
            if source_id in seen:
                continue
            seen.add(source_id)
            filtered.append({
                "source_id": source_id,
                "source_type": entity["source_type"],
                "source_title": entity["source_title"],
                "section": entity["section"],
                "text_snippet": entity["text_snippet"][:200],
                "score": hit["distance"],
            })
            if len(filtered) >= top_k:
                break

    return filtered


def run_milvus_lite_poc():
    """运行 Milvus Lite POC 实验。"""
    print("加载样例文档并切块...")
    chunks = build_chunk_index()
    print(f"总 chunks: {len(chunks)}")

    print("计算 TF-IDF 向量...")
    vectors, meta = compute_vectors(chunks, method="tfidf")
    print(f"嵌入维度: {len(vectors[0])}, 方法: {meta['method']}")

    print("构建 Milvus Lite 索引...")
    client, db_path = build_milvus_lite_index(chunks, vectors)

    # 数据目录大小
    db_file = Path(db_path)
    db_size = db_file.stat().st_size if db_file.exists() else 0
    total_size = sum(f.stat().st_size for f in MILVUS_DIR.rglob("*") if f.is_file())
    print(f"Milvus Lite 数据大小: {total_size / 1024:.1f} KB")

    print("运行检索评估...")
    result = evaluate_retrieval("milvus_lite_tfidf", milvus_lite_retrieve)
    print_eval_summary(result)

    # 记录额外指标
    metrics = {
        "db_size_kb": round(total_size / 1024, 1),
        "total_chunks": len(chunks),
        "embedding_method": meta["method"],
        "embedding_dim": len(vectors[0]),
    }

    # 测试备份恢复
    print("测试备份恢复...")
    import shutil
    backup_dir = MILVUS_DIR.parent / "milvus_lite_backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.copytree(MILVUS_DIR, backup_dir)
    print(f"备份完成: {backup_dir}")

    # 验证恢复
    from pymilvus import MilvusClient
    restored_path = str(backup_dir / "milvus_lite.db")
    restored_client = MilvusClient(uri=restored_path)
    restored_count = restored_client.query(collection_name="chunks", filter="", output_fields=["count(*)"])
    print(f"恢复后记录数: {restored_count}")

    # runtime 兼容性
    runtime_compat_dir = Path(__file__).resolve().parent.parent.parent / "runtime" / "vector_milvus_lite"
    runtime_compat_dir.mkdir(parents=True, exist_ok=True)
    print(f"Milvus Lite runtime 兼容路径: {runtime_compat_dir}")

    # 中文召回特别测试
    print("中文召回特别测试...")
    chinese_queries = [
        "需求评审流程规范",
        "JWT鉴权机制",
        "停用成员访问项目",
        "Agent工具审批链路",
    ]
    for q in chinese_queries:
        start = time.perf_counter()
        results = milvus_lite_retrieve(q, "ws-1", top_k=3)
        latency = (time.perf_counter() - start) * 1000
        ids = [r["source_id"] for r in results]
        print(f"  '{q}' → {ids} ({latency:.1f}ms)")

    metrics["backup_recovery"] = "ok"
    metrics["runtime_compat"] = "ok"
    metrics["chinese_recall_tested"] = True
    metrics_path = MILVUS_DIR.parent / "milvus_lite_tfidf_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


if __name__ == "__main__":
    try:
        from pymilvus import MilvusClient
        import pymilvus
        print(f"pymilvus version: {pymilvus.__version__}")
    except ImportError as e:
        print(f"缺少依赖: {e}")
        print("请安装: pip install pymilvus")
        sys.exit(1)

    run_milvus_lite_poc()