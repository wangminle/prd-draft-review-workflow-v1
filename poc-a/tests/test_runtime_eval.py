"""Runtime-backed POC-A evaluation helper tests."""

import sqlite3
import sys
from pathlib import Path


POC_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(POC_SCRIPTS))


def _create_review_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE review_documents (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            md_path TEXT,
            status TEXT NOT NULL,
            document_type TEXT,
            content_hash TEXT
        )
        """
    )
    return conn


def test_load_runtime_documents_filters_failed_missing_and_duplicates(tmp_path):
    from runtime_eval import load_runtime_documents

    runtime_root = tmp_path / "runtime"
    doc_dir = runtime_root / "data" / "converted" / "doc_1" / "需求A"
    doc_dir.mkdir(parents=True)
    md_path = doc_dir / "需求A.md"
    md_path.write_text("# 需求A\n\n# 一、需求背景\n\n这里是足够长的正文。" * 40, encoding="utf-8")

    db_path = tmp_path / "app.db"
    conn = _create_review_db(db_path)
    rows = [
        (1, 2, "需求A.docx", "data/converted/doc_1/需求A/需求A.md", "analyzed", "requirement", "hash-a"),
        (2, 2, "需求A副本.docx", "data/converted/doc_1/需求A/需求A.md", "converted", "historical", "hash-a"),
        (3, 2, "失败.docx", "data/converted/doc_3/失败.md", "failed", "requirement", "hash-b"),
        (4, 2, "缺失.docx", "data/converted/doc_4/缺失.md", "analyzed", "requirement", "hash-c"),
    ]
    conn.executemany(
        "INSERT INTO review_documents VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    docs = load_runtime_documents(db_path, runtime_root)

    assert [doc.source_id for doc in docs] == ["doc-1"]
    assert docs[0].workspace_id == "project-2"
    assert docs[0].title == "需求A"


def test_generate_runtime_questions_uses_exact_source_ids():
    from runtime_eval import RuntimeDocument, generate_runtime_questions

    docs = [
        RuntimeDocument(
            source_id="doc-7",
            workspace_id="project-2",
            title="设备预约能力优化",
            filename="设备预约能力优化.docx",
            document_type="requirement",
            status="analyzed",
            path=Path("/tmp/doc.md"),
            text="# 设备预约能力优化\n\n# 一、需求背景\n\n用户需要按动作查询预约。\n\n# 二、需求详情\n\n支持查询与删除。",
        )
    ]

    questions = generate_runtime_questions(docs, max_doc_questions=1)

    assert questions[0]["expect_ids"] == ["doc-7"]
    assert questions[0]["workspace_id"] == "project-2"
    assert any(q["category"] == "section_find" for q in questions)
