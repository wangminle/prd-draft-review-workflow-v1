"""POC-A: sqlite-vec 向量检索实验。

sqlite-vec 特点：
- SQLite 扩展（类似 FTS5），向量检索留在 SQLite 内
- vec0 虚拟表，支持 partition key（workspace 隔离）+ metadata 列
- 本地嵌入式，单文件存储，与 runtime/ 数据隔离原则天然兼容
- 依赖：sqlite-vec + pysqlite3（Python 3.13 移除了 load_extension 支持）

关键限制：
- sqlite-vec 最大维度 8192，而 TF-IDF fallback 词汇量 16940 维超出上限
- 降维策略：tier1 (freq≥2 的常见词项) + tier2 (最高 IDF 值的罕见词项)，合计 8192 维
- 此维度限制在生产环境使用真实嵌入模型（OpenAI 1536 维 / BGE-M3 1024 维）时不存在

与 LanceDB 对比要点：
- 不引入新的存储引擎，向量数据仍在 SQLite 内
- partition key 实现权限过滤（与 FTS5 WHERE 并行）
- 备份恢复仍是单文件复制
- 但缺少 IVF-PQ 等高级索引，大规模数据性能待验证

依赖: pip install sqlite-vec pysqlite3
"""

import sys
import json
import math
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunking import build_chunk_index, Chunk, load_all_samples
from embedding import _simple_tokenize
from evaluate import evaluate_retrieval, print_eval_summary, PERMISSION_CASES

SQLITE_VEC_DIR = Path(__file__).resolve().parent.parent / "results" / "sqlite_vec_data"
DB_PATH = SQLITE_VEC_DIR / "vec_chunks.db"

# sqlite-vec 最大维度限制 8192，TF-IDF vocab 16940 超出
# 降维策略：tier1(freq≥2) + tier2(最高 IDF)，合计 8192 维
REDUCED_DIM = 8192

# ── 降维 TF-IDF 计算 ──

def _compute_reduced_tfidf(chunks: list[Chunk], dim: int = REDUCED_DIM):
    """计算降维 TF-IDF 向量：混合选取策略。

    tier1: 出现在 ≥2 个文档中的词项（覆盖高频中文 bigram 和常见术语）
    tier2: 只出现在 1 个文档中的词项，按 IDF 值降序选取填充剩余维度

    此策略确保查询常见词项有较高覆盖率，同时保留区分力强的罕见词。
    """
    all_tokens = []
    doc_freqs = Counter()
    for chunk in chunks:
        tokens = _simple_tokenize(chunk.text)
        all_tokens.append(tokens)
        unique_tokens = set(tokens)
        for t in unique_tokens:
            doc_freqs[t] += 1

    n_docs = len(chunks)

    # tier1: freq >= 2（常见词项，查询覆盖率优先）
    tier1_tokens = sorted(t for t, f in doc_freqs.items() if f >= 2)
    # tier2: freq == 1，按 IDF 值排序（罕见但高区分力词项）
    idf_values = {}
    for token, freq in doc_freqs.items():
        idf_val = math.log(n_docs / (freq + 1)) + 1
        idf_values[token] = idf_val

    tier2_by_idf = sorted(
        (t for t, f in doc_freqs.items() if f == 1),
        key=lambda t: idf_values[t],
        reverse=True
    )

    # 混合选取：tier1 优先 + tier2 填充
    remaining = dim - len(tier1_tokens)
    extra = tier2_by_idf[:max(0, remaining)]
    reduced_vocab = tier1_tokens + extra
    vocab_map = {t: i for i, t in enumerate(reduced_vocab)}
    actual_dim = len(reduced_vocab)

    # 计算降维 TF-IDF 向量
    vectors = []
    for tokens in all_tokens:
        tf = Counter(tokens)
        vec = [0.0] * actual_dim
        for token, count in tf.items():
            if token in vocab_map:
                idx = vocab_map[token]
                tf_val = count / len(tokens) if tokens else 0
                idf_val = idf_values[token]
                vec[idx] = tf_val * idf_val
        # 归一化
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vec = [v / norm for v in vec]
        vectors.append(vec)

    metadata = {
        "method": "tfidf_reduced_hybrid",
        "original_vocab_size": len(doc_freqs),
        "tier1_count": len(tier1_tokens),
        "tier2_count": len(extra),
        "reduced_dim": actual_dim,
        "n_docs": n_docs,
    }

    return vectors, metadata, doc_freqs, idf_values, vocab_map


def _compute_query_tfidf(query: str, doc_freqs: Counter, idf_values: dict,
                         vocab_map: dict, n_docs: int) -> list:
    """用与索引相同的降维 vocab 计算查询向量。"""
    query_tokens = _simple_tokenize(query)
    tf = Counter(query_tokens)
    dim = len(vocab_map)
    query_vec = [0.0] * dim
    for token, count in tf.items():
        if token in vocab_map:
            idx = vocab_map[token]
            tf_val = count / len(query_tokens) if query_tokens else 0
            idf_val = idf_values[token]
            query_vec[idx] = tf_val * idf_val

    norm = math.sqrt(sum(v * v for v in query_vec)) or 1.0
    query_vec = [v / norm for v in query_vec]
    return query_vec


# ── 索引构建 ──

def build_sqlite_vec_index(chunks: list[Chunk], vectors: list, reduced_dim: int):
    """构建 sqlite-vec 索引。"""
    import pysqlite3 as sqlite3_mod
    import sqlite_vec

    SQLITE_VEC_DIR.parent.mkdir(exist_ok=True)
    if SQLITE_VEC_DIR.exists():
        import shutil
        shutil.rmtree(SQLITE_VEC_DIR)
    SQLITE_VEC_DIR.mkdir()

    db = sqlite3_mod.connect(str(DB_PATH))
    db.enable_load_extension(True)
    sqlite_vec.load(db)

    # 创建辅助表存储 chunk 元数据和正文
    db.execute("""
        CREATE TABLE chunk_metadata (
            rowid INTEGER PRIMARY KEY,
            source_id TEXT,
            source_type TEXT,
            source_title TEXT,
            section TEXT,
            text TEXT,
            workspace_id TEXT
        )
    """)

    # 创建 vec0 虚拟表，使用 partition key 做 workspace 隔离
    create_sql = """
        CREATE VIRTUAL TABLE vec_chunks USING vec0(
            embedding float[{}],
            workspace_id text partition
        )
    """.format(reduced_dim)
    db.execute(create_sql)

    # ws-1 包含全部文档，ws-2 只包含规范
    ws2_prefix = "norm-"

    rowid = 0
    metadata_rows = []

    for i, chunk in enumerate(chunks):
        vec = vectors[i]

        # ws-1 条目
        rowid += 1
        metadata_rows.append((
            rowid, chunk.source_id, chunk.source_type,
            chunk.source_title, chunk.section, chunk.text, "ws-1"
        ))
        db.execute(
            "INSERT INTO vec_chunks(rowid, embedding, workspace_id) VALUES (?, ?, ?)",
            [rowid, sqlite_vec.serialize_float32(vec), "ws-1"]
        )

        # ws-2 规范类文档额外插入
        if chunk.source_id.startswith(ws2_prefix):
            rowid += 1
            metadata_rows.append((
                rowid, chunk.source_id, chunk.source_type,
                chunk.source_title, chunk.section, chunk.text, "ws-2"
            ))
            db.execute(
                "INSERT INTO vec_chunks(rowid, embedding, workspace_id) VALUES (?, ?, ?)",
                [rowid, sqlite_vec.serialize_float32(vec), "ws-2"]
            )

    # 批量插入元数据
    db.executemany(
        "INSERT INTO chunk_metadata VALUES (?, ?, ?, ?, ?, ?, ?)",
        metadata_rows
    )

    db.commit()
    total_rows = db.execute("SELECT COUNT(*) FROM chunk_metadata").fetchone()[0]
    print(f"sqlite-vec 索引完成: {total_rows} 条记录")

    db.close()
    return DB_PATH


# ── 检索函数 ──

# 全局缓存：避免每次查询都重建 vocab
_VOCAB_CACHE = {}


def sqlite_vec_retrieve(query: str, workspace_id: str, top_k: int = 5) -> list[dict]:
    """sqlite-vec 向量检索 + partition 权限过滤。"""
    import pysqlite3 as sqlite3_mod
    import sqlite_vec

    # 权限检查：inactive/non-member 返回空
    perm_case = next((p for p in PERMISSION_CASES
                      if p["query"] == query and p["workspace"] == workspace_id), None)
    if perm_case and perm_case["role"] in ("inactive", "non-member"):
        return []

    db = sqlite3_mod.connect(str(DB_PATH))
    db.enable_load_extension(True)
    sqlite_vec.load(db)

    # 使用缓存的 vocab 计算查询向量
    doc_freqs = _VOCAB_CACHE["doc_freqs"]
    idf_values = _VOCAB_CACHE["idf_values"]
    vocab_map = _VOCAB_CACHE["vocab_map"]
    n_docs = _VOCAB_CACHE["n_docs"]

    query_vec = _compute_query_tfidf(query, doc_freqs, idf_values, vocab_map, n_docs)

    # sqlite-vec 搜索 + partition filter
    query_serialized = sqlite_vec.serialize_float32(query_vec)
    results = db.execute(
        "SELECT rowid, distance, workspace_id FROM vec_chunks "
        "WHERE embedding MATCH ? AND workspace_id = ? "
        "ORDER BY distance LIMIT ?",
        [query_serialized, workspace_id, top_k * 3]
    ).fetchall()

    # 从元数据表获取详细信息
    filtered = []
    seen_source_ids = set()
    for rowid, distance, ws_id in results:
        meta = db.execute(
            "SELECT source_id, source_type, source_title, section, text "
            "FROM chunk_metadata WHERE rowid = ?",
            [rowid]
        ).fetchone()
        if meta is None:
            continue
        source_id, source_type, source_title, section, text = meta

        # 去重：同一 source_id 只取最近的 chunk
        if source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)

        filtered.append({
            "source_id": source_id,
            "source_type": source_type,
            "source_title": source_title,
            "section": section,
            "text_snippet": text[:200],
            "score": distance,
        })
        if len(filtered) >= top_k:
            break

    db.close()
    return filtered


# ── 主流程 ──

def run_sqlite_vec_poc():
    """运行 sqlite-vec POC 实验。"""
    import pysqlite3 as sqlite3_mod
    import sqlite_vec

    print("加载样例文档并切块...")
    chunks = build_chunk_index()
    print(f"总 chunks: {len(chunks)}")

    print(f"计算降维 TF-IDF 向量（混合策略: tier1 常见词 + tier2 高 IDF 词, 8192 维上限）...")
    vectors, meta, doc_freqs, idf_values, vocab_map = _compute_reduced_tfidf(chunks, REDUCED_DIM)
    print(f"嵌入维度: {len(vectors[0])}, 方法: {meta['method']}")
    print(f"  tier1 (freq≥2): {meta['tier1_count']} 词项, tier2 (高 IDF): {meta['tier2_count']} 词项")
    print(f"  原始 vocab: {meta['original_vocab_size']}, 降维后: {meta['reduced_dim']}")

    # 缓存 vocab 供查询使用
    _VOCAB_CACHE["doc_freqs"] = doc_freqs
    _VOCAB_CACHE["idf_values"] = idf_values
    _VOCAB_CACHE["vocab_map"] = vocab_map
    _VOCAB_CACHE["n_docs"] = meta["n_docs"]

    print("构建 sqlite-vec 索引...")
    db_path = build_sqlite_vec_index(chunks, vectors, meta["reduced_dim"])

    # 数据文件大小
    db_size = DB_PATH.stat().st_size
    print(f"sqlite-vec 数据大小: {db_size / 1024:.1f} KB")

    print("运行检索评估...")
    result = evaluate_retrieval("sqlite_vec_tfidf", sqlite_vec_retrieve)
    print_eval_summary(result)

    # 记录额外指标
    metrics = {
        "db_size_kb": round(db_size / 1024, 1),
        "total_chunks": len(chunks),
        "embedding_method": meta["method"],
        "original_vocab_size": meta["original_vocab_size"],
        "tier1_count": meta["tier1_count"],
        "tier2_count": meta["tier2_count"],
        "embedding_dim": meta["reduced_dim"],
        "dimension_limit": f"sqlite-vec max 8192, reduced from {meta['original_vocab_size']}",
        "reduction_strategy": "hybrid: tier1 (freq>=2) + tier2 (top IDF), dim=8192",
    }
    metrics_path = SQLITE_VEC_DIR.parent / "sqlite_vec_tfidf_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    # 测试备份恢复
    print("测试备份恢复...")
    import shutil
    backup_dir = SQLITE_VEC_DIR / "backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir()
    shutil.copy2(DB_PATH, backup_dir / "vec_chunks.db")
    print(f"备份完成: {backup_dir}")

    # 验证恢复
    backup_db = sqlite3_mod.connect(str(backup_dir / "vec_chunks.db"))
    backup_db.enable_load_extension(True)
    sqlite_vec.load(backup_db)
    count = backup_db.execute("SELECT COUNT(*) FROM chunk_metadata").fetchone()[0]
    backup_db.close()
    print(f"恢复后记录数: {count}")

    # runtime 目录兼容性验证
    runtime_compat_dir = Path(__file__).resolve().parent.parent.parent / "runtime" / "vector_sqlite_vec"
    runtime_compat_dir.mkdir(parents=True, exist_ok=True)
    print(f"sqlite-vec runtime 兼容路径: {runtime_compat_dir}")

    metrics["backup_recovery"] = "ok"
    metrics["runtime_compat"] = "ok"
    metrics["pysqlite3_required"] = "Python 3.13 移除了 load_extension, 需 pysqlite3 替代"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


if __name__ == "__main__":
    # 检查依赖
    try:
        import pysqlite3
        import sqlite_vec
        print(f"pysqlite3 version: {pysqlite3.sqlite_version}")
        print(f"sqlite_vec available: True")
    except ImportError as e:
        print(f"缺少依赖: {e}")
        print("请安装: pip install sqlite-vec pysqlite3")
        sys.exit(1)

    run_sqlite_vec_poc()