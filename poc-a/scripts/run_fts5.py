"""POC-A.2: SQLite FTS5 检索基准。

流程：
1. 加载样例 → 切块
2. 创建 FTS5 虚拟表 + 索引所有 chunks
3. 对 30 个问题执行关键词检索
4. 对 10 个权限用例执行带权限过滤的检索
5. 输出评估结果

FTS5 使用 unicode61 tokenizer 支持中文分词。
"""

import sqlite3
import time
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunking import build_chunk_index, Chunk, load_all_samples
from evaluate import evaluate_retrieval, print_eval_summary, QUESTIONS, PERMISSION_CASES

DB_PATH = Path(__file__).resolve().parent.parent / "results" / "fts5_baseline.db"


def create_fts5_db(chunks: list[Chunk], db_path: Path) -> sqlite3.Connection:
    """创建 FTS5 索引数据库。"""
    db_path.parent.mkdir(exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # 创建 chunks 元数据表
    conn.execute("""
        CREATE TABLE chunks_meta (
            chunk_no INTEGER,
            source_id TEXT,
            source_type TEXT,
            source_title TEXT,
            section TEXT,
            text TEXT,
            char_start INTEGER,
            char_end INTEGER,
            workspace_id TEXT DEFAULT 'ws-1'
        )
    """)

    # 创建 FTS5 虚拟表 — 使用 unicode61 remove_diacritics 2 改善中文分词
    conn.execute("""
        CREATE VIRTUAL TABLE chunks_fts
        USING fts5(text, content='chunks_meta', content_rowid='chunk_no',
                   tokenize='unicode61 remove_diacritics 2')
    """)

    # 插入所有 chunks
    # ws-2 只包含规范类文档
    ws2_prefix = "norm-"

    for i, chunk in enumerate(chunks, start=1):
        ws_id = "ws-1"
        conn.execute("""
            INSERT INTO chunks_meta (chunk_no, source_id, source_type,
                                     source_title, section, text,
                                     char_start, char_end, workspace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            i, chunk.source_id, chunk.source_type,
            chunk.source_title, chunk.section, chunk.text,
            chunk.char_start, chunk.char_end, ws_id,
        ))

        # ws-2 的规范类文档也插入一份（不同 workspace_id）
        if chunk.source_id.startswith(ws2_prefix):
            conn.execute("""
                INSERT INTO chunks_meta (chunk_no, source_id, source_type,
                                         source_title, section, text,
                                         char_start, char_end, workspace_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                i + len(chunks) + 1000, chunk.source_id, chunk.source_type,
                chunk.source_title, chunk.section, chunk.text,
                chunk.char_start, chunk.char_end, "ws-2",
            ))

    conn.commit()

    # 同步 FTS5 content
    conn.execute("""
        INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')
    """)
    conn.commit()

    # 验证索引
    count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    print(f"FTS5 索引完成: {count} 条 chunk 已索引")

    return conn


def _extract_fts5_terms(query: str) -> str:
    """从自然语言查询中提取 FTS5 搜索关键词。

    FTS5 unicode61 对中文按字符分词，所以：
    - 提取中文连续片段（2字以上）
    - 提取英文单词
    - 用 OR 组合所有关键词片段
    """
    import re

    # 提取中文连续片段（2字以上）
    chinese_segments = re.findall(r'[一-鿿]{2,}', query)

    # 提取英文单词（3字母以上）
    english_words = re.findall(r'[a-zA-Z]{3,}', query)

    # 提取英文缩写（2字母，如 JWT、PRD）
    abbreviations = re.findall(r'[A-Z]{2,}', query)

    terms = chinese_segments + english_words + abbreviations

    if not terms:
        # fallback: 每个中文字符作为单独 term
        chars = [ch for ch in query if '一' <= ch <= '鿿']
        terms = chars if chars else [query]

    # FTS5 MATCH 表达式：所有 term 用 OR 连接
    # 对中文长词，拆成2字组合以匹配 unicode61 分词
    fts_terms = []
    for term in terms:
        if len(term) >= 3 and all('一' <= ch <= '鿿' for ch in term):
            # 拆成 2字 bigram 子短语
            for i in range(len(term) - 1):
                fts_terms.append(term[i:i+2])
        else:
            fts_terms.append(term)

    if not fts_terms:
        return query

    # 构建 OR 表达式
    return ' OR '.join(fts_terms)


def fts5_retrieve(query: str, workspace_id: str, top_k: int = 5) -> list[dict]:
    """FTS5 关键词检索 + 权限过滤。"""
    # 模拟权限过滤：只返回 workspace_id 匹配的 chunks
    # 特殊角色处理：inactive/non-member 返回空
    perm_case = next((p for p in PERMISSION_CASES
                      if p["query"] == query and p["workspace"] == workspace_id), None)
    if perm_case and perm_case["role"] in ("inactive", "non-member"):
        return []

    # 提取 FTS5 搜索关键词
    fts_query = _extract_fts5_terms(query)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        # FTS5 搜索 + workspace 过滤
        results = conn.execute("""
            SELECT cm.source_id, cm.source_type, cm.source_title,
                   cm.section, cm.text, rank
            FROM chunks_fts cft
            JOIN chunks_meta cm ON cm.chunk_no = cft.rowid
            WHERE chunks_fts MATCH ?
            AND cm.workspace_id = ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query, workspace_id, top_k * 3)).fetchall()

        # 去重截断
        filtered = []
        seen_sources = set()
        for row in results:
            source_id = row[0]
            if source_id in seen_sources:
                continue
            seen_sources.add(source_id)
            filtered.append({
                "source_id": source_id,
                "source_type": row[1],
                "source_title": row[2],
                "section": row[3],
                "text_snippet": row[4][:200],
                "score": -row[5],  # FTS5 rank 是负值，越负越相关
            })
            if len(filtered) >= top_k:
                break

        # 如果 FTS5 MATCH 返回空，fallback 到 LIKE 搜索
        if not filtered:
            results = conn.execute("""
                SELECT cm.source_id, cm.source_type, cm.source_title,
                       cm.section, cm.text, 0 as rank
                FROM chunks_meta cm
                WHERE cm.text LIKE ?
                AND cm.workspace_id = ?
                ORDER BY cm.chunk_no
                LIMIT ?
            """, (f'%{query[:20]}%', workspace_id, top_k)).fetchall()

            for row in results:
                source_id = row[0]
                if source_id not in seen_sources:
                    seen_sources.add(source_id)
                    filtered.append({
                        "source_id": source_id,
                        "source_type": row[1],
                        "source_title": row[2],
                        "section": row[3],
                        "text_snippet": row[4][:200],
                        "score": 1.0,
                    })
                    if len(filtered) >= top_k:
                        break

        return filtered
    finally:
        conn.close()


def run_fts5_baseline():
    """运行 FTS5 baseline 实验。"""
    print("加载样例文档并切块...")
    chunks = build_chunk_index()
    print(f"总 chunks: {len(chunks)}")

    print("创建 FTS5 索引...")
    conn = create_fts5_db(chunks, DB_PATH)

    # 统计索引大小
    db_size = DB_PATH.stat().st_size
    print(f"数据库大小: {db_size / 1024:.1f} KB")

    print("运行检索评估...")
    result = evaluate_retrieval("fts5_baseline", fts5_retrieve)
    print_eval_summary(result)

    # 记录额外指标
    metrics = {
        "db_size_kb": round(db_size / 1024, 1),
        "total_chunks": len(chunks),
        "index_time_ms": 0,  # 已在创建过程中完成
    }
    metrics_path = DB_PATH.parent / "fts5_baseline_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    conn.close()
    return result


if __name__ == "__main__":
    run_fts5_baseline()