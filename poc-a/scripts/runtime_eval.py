"""Runtime-backed retrieval evaluation for POC-A.

This helper reads converted review Markdown from a runtime database, generates
source-backed retrieval questions, and compares FTS5 plus local vector stores.
Runtime-derived data and results are written under runtime/ by default.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from embedding import _simple_tokenize


MIN_DOC_CHARS = 300
MAX_CHUNK_CHARS = 900
OVERLAP_CHARS = 120
DEFAULT_MAX_FEATURES = 4096


@dataclass(frozen=True)
class RuntimeDocument:
    source_id: str
    workspace_id: str
    title: str
    filename: str
    document_type: str
    status: str
    path: Path
    text: str


@dataclass(frozen=True)
class RuntimeChunk:
    chunk_id: str
    source_id: str
    workspace_id: str
    title: str
    section: str
    text: str


def _strip_docx(filename: str) -> str:
    return re.sub(r"\.(docx|doc|md|txt)$", "", filename.strip(), flags=re.I)


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if match:
            heading = match.group(1).strip()
            if heading and heading.lower() not in {"output", "title"}:
                return heading
    return None


def _resolve_document_path(md_path: str | None, runtime_root: Path) -> Path | None:
    if not md_path:
        return None

    raw = md_path.strip()
    if not raw:
        return None

    candidate = Path(raw)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    normalized = raw.replace("\\", "/")
    marker = "/runtime/"
    if marker in normalized:
        suffix = normalized.split(marker, 1)[1]
        mapped = runtime_root / suffix
        if mapped.exists():
            return mapped

    while normalized.startswith("../"):
        normalized = normalized[3:]
    if normalized.startswith("runtime/"):
        normalized = normalized[len("runtime/") :]

    mapped = runtime_root / normalized
    if mapped.exists():
        return mapped
    return None


def load_runtime_documents(db_path: Path, runtime_root: Path, *, min_chars: int = MIN_DOC_CHARS) -> list[RuntimeDocument]:
    """Load usable review documents from runtime review_documents metadata."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, project_id, filename, md_path, status, document_type, content_hash
            FROM review_documents
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()

    docs: list[RuntimeDocument] = []
    seen_keys: set[str] = set()
    for row in rows:
        if row["status"] == "failed":
            continue
        path = _resolve_document_path(row["md_path"], runtime_root)
        if path is None or not path.exists():
            continue

        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if len(text) < min_chars:
            continue

        dedupe_key = row["content_hash"] or str(path.resolve())
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        title = _first_heading(text) or _strip_docx(row["filename"])
        docs.append(
            RuntimeDocument(
                source_id=f"doc-{row['id']}",
                workspace_id=f"project-{row['project_id']}",
                title=title,
                filename=row["filename"],
                document_type=row["document_type"] or "unknown",
                status=row["status"],
                path=path,
                text=text,
            )
        )
    return docs


def _section_slices(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text))
    if not matches:
        return [("full", text)]

    sections: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if title or body:
            sections.append((title, body or title))
    return sections


def build_runtime_chunks(docs: list[RuntimeDocument]) -> list[RuntimeChunk]:
    chunks: list[RuntimeChunk] = []
    for doc in docs:
        chunk_no = 0
        for section, body in _section_slices(doc.text):
            section_text = f"{doc.title}\n{section}\n{body}".strip()
            start = 0
            while start < len(section_text):
                end = min(start + MAX_CHUNK_CHARS, len(section_text))
                chunk_text = section_text[start:end]
                chunk_no += 1
                chunks.append(
                    RuntimeChunk(
                        chunk_id=f"{doc.source_id}#{chunk_no}",
                        source_id=doc.source_id,
                        workspace_id=doc.workspace_id,
                        title=doc.title,
                        section=section,
                        text=chunk_text,
                    )
                )
                if end >= len(section_text):
                    break
                start = max(0, end - OVERLAP_CHARS)
    return chunks


def _clean_query_term(value: str, max_len: int = 28) -> str:
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[#*`|：:（）()\[\]【】]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_len].strip()


def _section_candidates(doc: RuntimeDocument) -> list[str]:
    sections = []
    for section, body in _section_slices(doc.text):
        clean = _clean_query_term(section)
        if not clean or clean == doc.title or clean in {"版本历史", "目录"}:
            continue
        sections.append(clean)
    return sections


def generate_runtime_questions(docs: list[RuntimeDocument], *, max_doc_questions: int = 40) -> list[dict]:
    """Generate deterministic source-backed retrieval questions."""
    questions: list[dict] = []
    selected_docs = docs[:max_doc_questions]
    for doc in selected_docs:
        title_term = _clean_query_term(doc.title, max_len=36)
        questions.append(
            {
                "qid": f"RQ-{len(questions) + 1:03d}",
                "query": f"{title_term} 主要需求是什么",
                "workspace_id": doc.workspace_id,
                "expect_ids": [doc.source_id],
                "category": "title_find",
            }
        )

        sections = _section_candidates(doc)
        if sections:
            section = sections[0]
            questions.append(
                {
                    "qid": f"RQ-{len(questions) + 1:03d}",
                    "query": f"{title_term} 的 {section} 包含哪些内容",
                    "workspace_id": doc.workspace_id,
                    "expect_ids": [doc.source_id],
                    "category": "section_find",
                }
            )

    workspace_ids = sorted({doc.workspace_id for doc in docs})
    default_workspace = workspace_ids[0] if workspace_ids else "project-0"
    for no_answer in [
        "区块链积分结算规则是什么",
        "海外税务发票自动报销流程是什么",
        "员工绩效薪酬审批怎么配置",
        "供应链仓储机器人路径规划方案是什么",
    ]:
        questions.append(
            {
                "qid": f"RQ-{len(questions) + 1:03d}",
                "query": no_answer,
                "workspace_id": default_workspace,
                "expect_ids": [],
                "category": "no_answer",
            }
        )
    return questions


class TfidfEncoder:
    def __init__(self, chunks: list[RuntimeChunk], *, max_features: int = DEFAULT_MAX_FEATURES):
        doc_freqs: Counter[str] = Counter()
        tokenized = []
        for chunk in chunks:
            tokens = _simple_tokenize(chunk.text)
            tokenized.append(tokens)
            doc_freqs.update(set(tokens))

        ranked = sorted(doc_freqs.items(), key=lambda item: (-item[1], item[0]))
        self.vocab = [token for token, _ in ranked[:max_features]]
        self.vocab_map = {token: idx for idx, token in enumerate(self.vocab)}
        self.doc_freqs = doc_freqs
        self.n_docs = len(chunks)
        self.vectors = [self.encode_tokens(tokens) for tokens in tokenized]

    @property
    def dim(self) -> int:
        return len(self.vocab)

    def encode_tokens(self, tokens: list[str]) -> list[float]:
        tf = Counter(tokens)
        vec = [0.0] * len(self.vocab)
        for token, count in tf.items():
            idx = self.vocab_map.get(token)
            if idx is None:
                continue
            tf_val = count / len(tokens) if tokens else 0.0
            idf_val = math.log(max(self.n_docs, 1) / (self.doc_freqs[token] + 1)) + 1
            vec[idx] = tf_val * idf_val
        norm = math.sqrt(sum(value * value for value in vec)) or 1.0
        return [value / norm for value in vec]

    def encode_query(self, query: str) -> list[float]:
        return self.encode_tokens(_simple_tokenize(query))


def _dedupe_hits(rows: list[dict], top_k: int) -> list[dict]:
    hits = []
    seen = set()
    for row in rows:
        if row["source_id"] in seen:
            continue
        seen.add(row["source_id"])
        hits.append(row)
        if len(hits) >= top_k:
            break
    return hits


def _extract_fts_terms(query: str) -> str:
    chinese_segments = re.findall(r"[一-鿿]{2,}", query)
    english_words = re.findall(r"[a-zA-Z]{2,}", query)
    terms = chinese_segments + english_words
    fts_terms = []
    for term in terms:
        if all("\u4e00" <= ch <= "\u9fff" for ch in term) and len(term) >= 3:
            fts_terms.extend(term[i : i + 2] for i in range(len(term) - 1))
        else:
            fts_terms.append(term)
    return " OR ".join(dict.fromkeys(fts_terms)) or query


def build_fts5_retriever(chunks: list[RuntimeChunk], output_dir: Path) -> Callable[[str, str, int, str], list[dict]]:
    db_path = output_dir / "runtime_fts5.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE chunks_meta (chunk_id TEXT, source_id TEXT, workspace_id TEXT, title TEXT, section TEXT, text TEXT)")
    conn.execute(
        """
        CREATE VIRTUAL TABLE chunks_fts
        USING fts5(text, content='chunks_meta', content_rowid='rowid',
                   tokenize='unicode61 remove_diacritics 2')
        """
    )
    conn.executemany(
        "INSERT INTO chunks_meta VALUES (?, ?, ?, ?, ?, ?)",
        [(c.chunk_id, c.source_id, c.workspace_id, c.title, c.section, c.text) for c in chunks],
    )
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()

    def retrieve(query: str, workspace_id: str, top_k: int = 5, role: str = "member") -> list[dict]:
        if role in {"inactive", "non-member"}:
            return []
        fts_query = _extract_fts_terms(query)
        local = sqlite3.connect(str(db_path))
        try:
            rows = local.execute(
                """
                SELECT cm.source_id, cm.workspace_id, cm.title, cm.section, cm.text, rank
                FROM chunks_fts f
                JOIN chunks_meta cm ON cm.rowid = f.rowid
                WHERE chunks_fts MATCH ? AND cm.workspace_id = ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, workspace_id, top_k * 5),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            local.close()
        return _dedupe_hits(
            [
                {
                    "source_id": row[0],
                    "workspace_id": row[1],
                    "title": row[2],
                    "section": row[3],
                    "text_snippet": row[4][:180],
                    "score": -row[5],
                }
                for row in rows
            ],
            top_k,
        )

    return retrieve


def build_lancedb_retriever(chunks: list[RuntimeChunk], encoder: TfidfEncoder, output_dir: Path):
    import lancedb

    db_dir = output_dir / "lancedb_runtime"
    if db_dir.exists():
        shutil.rmtree(db_dir)
    db = lancedb.connect(str(db_dir))
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
    table = db.create_table("chunks", data)

    def retrieve(query: str, workspace_id: str, top_k: int = 5, role: str = "member") -> list[dict]:
        if role in {"inactive", "non-member"}:
            return []
        query_vec = encoder.encode_query(query)
        rows = (
            table.search(query_vec)
            .where(f"workspace_id = '{workspace_id}'", prefilter=True)
            .limit(top_k * 5)
            .to_list()
        )
        return _dedupe_hits(
            [
                {
                    "source_id": row["source_id"],
                    "workspace_id": row["workspace_id"],
                    "title": row["title"],
                    "section": row["section"],
                    "text_snippet": row["text"][:180],
                    "score": row["_distance"],
                }
                for row in rows
            ],
            top_k,
        )

    return retrieve


def build_chroma_retriever(chunks: list[RuntimeChunk], encoder: TfidfEncoder, output_dir: Path):
    import chromadb

    db_dir = output_dir / "chroma_runtime"
    if db_dir.exists():
        shutil.rmtree(db_dir)
    client = chromadb.PersistentClient(path=str(db_dir))
    collection = client.get_or_create_collection(name="runtime_chunks", metadata={"hnsw:space": "cosine"})
    collection.add(
        ids=[chunk.chunk_id for chunk in chunks],
        embeddings=encoder.vectors,
        documents=[chunk.text for chunk in chunks],
        metadatas=[
            {
                "source_id": chunk.source_id,
                "workspace_id": chunk.workspace_id,
                "title": chunk.title,
                "section": chunk.section,
            }
            for chunk in chunks
        ],
    )

    def retrieve(query: str, workspace_id: str, top_k: int = 5, role: str = "member") -> list[dict]:
        if role in {"inactive", "non-member"}:
            return []
        result = collection.query(
            query_embeddings=[encoder.encode_query(query)],
            n_results=min(top_k * 5, len(chunks)),
            where={"workspace_id": workspace_id},
            include=["metadatas", "documents", "distances"],
        )
        rows = []
        for idx, meta in enumerate(result["metadatas"][0] if result["metadatas"] else []):
            rows.append(
                {
                    "source_id": meta["source_id"],
                    "workspace_id": meta["workspace_id"],
                    "title": meta["title"],
                    "section": meta["section"],
                    "text_snippet": result["documents"][0][idx][:180],
                    "score": 1 - result["distances"][0][idx],
                }
            )
        return _dedupe_hits(rows, top_k)

    return retrieve


def build_sqlite_vec_retriever(chunks: list[RuntimeChunk], encoder: TfidfEncoder, output_dir: Path):
    import pysqlite3 as sqlite3_mod
    import sqlite_vec

    db_dir = output_dir / "sqlite_vec_runtime"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "vec_chunks.db"
    if db_path.exists():
        db_path.unlink()

    db = sqlite3_mod.connect(str(db_path))
    db.enable_load_extension(True)
    sqlite_vec.load(db)

    # Metadata table
    db.execute("""
        CREATE TABLE chunk_metadata (
            rowid INTEGER PRIMARY KEY,
            source_id TEXT,
            workspace_id TEXT,
            title TEXT,
            section TEXT,
            text TEXT
        )
    """)

    # vec0 virtual table with partition key for workspace isolation
    db.execute("""
        CREATE VIRTUAL TABLE vec_chunks USING vec0(
            embedding float[{}],
            workspace_id text partition
        )
    """.format(encoder.dim))

    metadata_rows = []
    for idx, chunk in enumerate(chunks):
        rowid = idx + 1
        metadata_rows.append((rowid, chunk.source_id, chunk.workspace_id, chunk.title, chunk.section, chunk.text))
        db.execute(
            "INSERT INTO vec_chunks(rowid, embedding, workspace_id) VALUES (?, ?, ?)",
            [rowid, sqlite_vec.serialize_float32(encoder.vectors[idx]), chunk.workspace_id]
        )

    db.executemany("INSERT INTO chunk_metadata VALUES (?, ?, ?, ?, ?, ?)", metadata_rows)
    db.commit()
    db.close()

    def retrieve(query: str, workspace_id: str, top_k: int = 5, role: str = "member") -> list[dict]:
        if role in {"inactive", "non-member"}:
            return []

        db = sqlite3_mod.connect(str(db_path))
        db.enable_load_extension(True)
        sqlite_vec.load(db)

        query_vec = encoder.encode_query(query)
        query_serialized = sqlite_vec.serialize_float32(query_vec)

        results = db.execute(
            "SELECT rowid, distance FROM vec_chunks "
            "WHERE embedding MATCH ? AND workspace_id = ? "
            "ORDER BY distance LIMIT ?",
            [query_serialized, workspace_id, top_k * 5]
        ).fetchall()

        rows = []
        for rowid, distance in results:
            meta = db.execute(
                "SELECT source_id, workspace_id, title, section, text FROM chunk_metadata WHERE rowid = ?",
                [rowid]
            ).fetchone()
            if meta:
                rows.append({
                    "source_id": meta[0],
                    "workspace_id": meta[1],
                    "title": meta[2],
                    "section": meta[3],
                    "text_snippet": meta[4][:180],
                    "score": distance,
                })

        db.close()
        return _dedupe_hits(rows, top_k)

    return retrieve


def build_milvus_retriever(chunks: list[RuntimeChunk], encoder: TfidfEncoder, output_dir: Path):
    from pymilvus import MilvusClient

    db_dir = output_dir / "milvus_runtime"
    if db_dir.exists():
        shutil.rmtree(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(db_dir / "milvus_lite.db")
    client = MilvusClient(uri=db_path)
    if client.has_collection("chunks"):
        client.drop_collection("chunks")
    client.create_collection(collection_name="chunks", dimension=encoder.dim, metric_type="COSINE")
    client.insert(
        collection_name="chunks",
        data=[
            {
                "id": idx + 1,
                "vector": encoder.vectors[idx],
                "source_id": chunk.source_id,
                "workspace_id": chunk.workspace_id,
                "title": chunk.title[:500],
                "section": chunk.section[:500],
                "text_snippet": chunk.text[:500],
            }
            for idx, chunk in enumerate(chunks)
        ],
    )

    def retrieve(query: str, workspace_id: str, top_k: int = 5, role: str = "member") -> list[dict]:
        if role in {"inactive", "non-member"}:
            return []
        results = client.search(
            collection_name="chunks",
            data=[encoder.encode_query(query)],
            filter=f"workspace_id == '{workspace_id}'",
            limit=top_k * 5,
            output_fields=["source_id", "workspace_id", "title", "section", "text_snippet"],
        )
        rows = []
        for hit in results[0] if results else []:
            entity = hit["entity"]
            rows.append(
                {
                    "source_id": entity["source_id"],
                    "workspace_id": entity["workspace_id"],
                    "title": entity["title"],
                    "section": entity["section"],
                    "text_snippet": entity["text_snippet"][:180],
                    "score": hit["distance"],
                }
            )
        return _dedupe_hits(rows, top_k)

    return retrieve


def evaluate_retriever(name: str, questions: list[dict], retrieve_fn, *, top_k: int = 5) -> dict:
    details = []
    top5_hits = 0
    top1_hits = 0
    total_latency = 0.0
    category = {}

    for question in questions:
        started = time.perf_counter()
        rows = retrieve_fn(question["query"], question["workspace_id"], top_k, "member")
        latency = (time.perf_counter() - started) * 1000
        result_ids = [row["source_id"] for row in rows]
        expected = question["expect_ids"]
        hit5 = any(result_id in expected for result_id in result_ids[:top_k]) if expected else len(result_ids) == 0
        hit1 = result_ids[0] in expected if expected and result_ids else (not expected and not result_ids)
        top5_hits += int(hit5)
        top1_hits += int(hit1)
        total_latency += latency
        bucket = category.setdefault(question["category"], {"hits": 0, "total": 0})
        bucket["hits"] += int(hit5)
        bucket["total"] += 1
        details.append({**question, "top_results": rows, "latency_ms": round(latency, 2), "hit": hit5})

    perm_cases = [
        {"query": questions[0]["query"], "workspace_id": questions[0]["workspace_id"], "role": "inactive", "expect_empty": True},
        {"query": questions[0]["query"], "workspace_id": questions[0]["workspace_id"], "role": "non-member", "expect_empty": True},
    ]
    permission_hits = 0
    for case in perm_cases:
        rows = retrieve_fn(case["query"], case["workspace_id"], top_k, case["role"])
        permission_hits += int(len(rows) == 0)
    for question in questions[: min(20, len(questions))]:
        rows = retrieve_fn(question["query"], question["workspace_id"], top_k, "member")
        permission_hits += int(all(row["workspace_id"] == question["workspace_id"] for row in rows))
        perm_cases.append({"query": question["query"], "workspace_id": question["workspace_id"], "role": "member", "expect_empty": False})

    return {
        "solution_name": name,
        "top5_hit_rate": round(top5_hits / len(questions), 4),
        "top1_hit_rate": round(top1_hits / len(questions), 4),
        "avg_latency_ms": round(total_latency / len(questions), 2),
        "permission_accuracy": round(permission_hits / len(perm_cases), 4),
        "category_hit_rates": {
            key: round(value["hits"] / value["total"], 4) for key, value in category.items()
        },
        "details": details,
    }


def _write_report(output_dir: Path, results: dict[str, dict], doc_count: int, chunk_count: int, question_count: int) -> Path:
    lines = [
        "# Runtime POC-A 检索方案复验报告",
        "",
        f"- 文档数: {doc_count}",
        f"- Chunks: {chunk_count}",
        f"- 问题数: {question_count}",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| 方案 | top-5 命中率 | top-1 命中率 | 平均延迟(ms) | 权限正确率 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, data in results.items():
        lines.append(
            f"| {name} | {data['top5_hit_rate']:.1%} | {data['top1_hit_rate']:.1%} | "
            f"{data['avg_latency_ms']:.1f} | {data['permission_accuracy']:.1%} |"
        )
    lines.extend(["", "## 分类型命中率", ""])
    for name, data in results.items():
        cats = ", ".join(f"{key}={value:.1%}" for key, value in data["category_hit_rates"].items())
        lines.append(f"- {name}: {cats}")
    path = output_dir / "runtime_poc_a_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_runtime_poc(args: argparse.Namespace) -> dict[str, dict]:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    docs = load_runtime_documents(args.db_path, args.runtime_root)
    if not docs:
        raise RuntimeError("未找到可用的 runtime Markdown 文档")
    chunks = build_runtime_chunks(docs)
    questions = generate_runtime_questions(docs, max_doc_questions=args.max_docs)
    encoder = TfidfEncoder(chunks, max_features=args.max_features)

    (output_dir / "runtime_questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "runtime_docs_manifest.json").write_text(
        json.dumps([{**asdict(doc), "path": str(doc.path)} for doc in docs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    retrievers = {"FTS5": build_fts5_retriever(chunks, output_dir)}
    if not args.skip_lancedb:
        retrievers["LanceDB"] = build_lancedb_retriever(chunks, encoder, output_dir)
    if not args.skip_milvus:
        retrievers["Milvus Lite"] = build_milvus_retriever(chunks, encoder, output_dir)
    if not args.skip_chroma:
        retrievers["Chroma"] = build_chroma_retriever(chunks, encoder, output_dir)
    if not args.skip_sqlite_vec:
        retrievers["sqlite-vec"] = build_sqlite_vec_retriever(chunks, encoder, output_dir)

    results = {}
    for name, retriever in retrievers.items():
        result = evaluate_retriever(name, questions, retriever)
        results[name] = result
        (output_dir / f"{name.lower().replace(' ', '_')}_eval.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"{name}: top5={result['top5_hit_rate']:.1%}, "
            f"top1={result['top1_hit_rate']:.1%}, "
            f"latency={result['avg_latency_ms']:.1f}ms, "
            f"perm={result['permission_accuracy']:.1%}"
        )

    report_path = _write_report(output_dir, results, len(docs), len(chunks), len(questions))
    print(f"报告: {report_path}")
    print(f"TF-IDF dim: {encoder.dim}; docs={len(docs)}; chunks={len(chunks)}; questions={len(questions)}")
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run runtime-backed POC-A retrieval evaluation.")
    project_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--db-path", type=Path, default=project_root / "runtime" / "data" / "app.db")
    parser.add_argument("--runtime-root", type=Path, default=project_root / "runtime")
    parser.add_argument("--output-dir", type=Path, default=project_root / "runtime" / "poc-a-real")
    parser.add_argument("--max-docs", type=int, default=40)
    parser.add_argument("--max-features", type=int, default=DEFAULT_MAX_FEATURES)
    parser.add_argument("--skip-lancedb", action="store_true")
    parser.add_argument("--skip-milvus", action="store_true")
    parser.add_argument("--skip-chroma", action="store_true")
    parser.add_argument("--skip-sqlite-vec", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_runtime_poc(parse_args())
