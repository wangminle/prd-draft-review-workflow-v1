"""BUG-153 ~ BUG-155: 代码审查 follow-up

BUG-153: 旧数据库 create_all 不会补 UniqueConstraint，需兼容迁移（先去重再建唯一索引）
BUG-154: IntegrityError 后整批 rollback + 遗留孤儿文件；应用 savepoint 并删除本次 stored 文件
BUG-155: 测试 fixture 丢弃 _pipeline_tasks 引用前未 cancel/await，导致 aiosqlite 线程异常
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import init_test_db, make_test_app


_MINIMAL_DOCX = b"PK\x05\x06" + b"\x00" * 18


class _MemUpload:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self):
        return self._content


@pytest_asyncio.fixture
async def followup_client(tmp_path):
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    from app.routers import review as review_mod
    from app.storage.review_file_storage import ReviewFileStorage

    original_storage = review_mod._review_file_storage
    review_mod._review_file_storage = ReviewFileStorage(upload_dir=str(tmp_path / "uploads"))

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/auth/login", json={
            "username": "admin", "password": "admin@2026",
        })
        token = resp.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac, session_maker, tmp_path / "uploads"

    review_mod._review_file_storage = original_storage
    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


# ── BUG-153: 旧库唯一索引兼容迁移 ─────────────────────────────────


class TestBUG153LegacyUniqueIndexMigration:
    def test_ensure_review_schema_creates_unique_index(self):
        """_ensure_review_schema 必须对已有表补建唯一索引，而不是只依赖 create_all。"""
        from app.database import _ensure_review_document_unique_index, _ensure_review_schema

        schema_src = inspect.getsource(_ensure_review_schema)
        assert "_ensure_review_document_unique_index" in schema_src, (
            "_ensure_review_schema 应调用兼容迁移，否则从 V0.3.10 升级的数据库"
            "仍无法阻止并发重复上传"
        )
        src = inspect.getsource(_ensure_review_document_unique_index)
        assert "uq_review_doc_proj_type_filename" in src
        assert "CREATE UNIQUE INDEX" in src

    async def test_legacy_db_dedupes_then_adds_unique_index(self):
        """已有 review_documents 表无唯一索引、且存在重复行时，迁移应去重并建索引。"""
        from app.database import _ensure_review_schema
        from app.utils import now_cn

        db_path = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(db_path)
        now = now_cn().isoformat(sep=" ")
        conn.executescript(f"""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(50),
                password_hash VARCHAR(128),
                role VARCHAR(10),
                created_at DATETIME,
                last_active_at DATETIME
            );
            CREATE TABLE review_projects (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                workspace_id INTEGER
            );
            CREATE TABLE review_documents (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                filename VARCHAR(500) NOT NULL,
                file_path VARCHAR(1000),
                file_size INTEGER,
                md_path VARCHAR(1000),
                content_hash VARCHAR(64),
                category VARCHAR(50),
                version VARCHAR(30),
                document_type VARCHAR(20) DEFAULT 'requirement',
                status VARCHAR(20) DEFAULT 'uploaded',
                parent_document_id INTEGER,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE doc_analyses (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL
            );
            CREATE TABLE system_reviews (
                id INTEGER PRIMARY KEY,
                task_id INTEGER,
                project_id INTEGER,
                product_strategy TEXT,
                tech_evolution TEXT,
                dimensions_meta TEXT
            );
            CREATE TABLE chat_context_items (
                id INTEGER PRIMARY KEY,
                extracted_text TEXT
            );
            CREATE TABLE model_configs (
                id INTEGER PRIMARY KEY,
                display_order INTEGER DEFAULT 0,
                deleted_by_user INTEGER DEFAULT 0,
                thinking_supported INTEGER DEFAULT 0,
                thinking_level VARCHAR(10) DEFAULT 'off',
                thinking_adapter VARCHAR(30) DEFAULT 'none',
                thinking_payload TEXT,
                context_window INTEGER DEFAULT 0
            );
            CREATE TABLE workspaces (
                id INTEGER PRIMARY KEY,
                name TEXT,
                is_default INTEGER DEFAULT 0
            );
            CREATE TABLE knowledge_sources (
                id INTEGER PRIMARY KEY,
                file_id VARCHAR(12),
                extracted_text TEXT
            );
            INSERT INTO review_projects (id, name, created_at, updated_at)
            VALUES (1, 'legacy-proj', '{now}', '{now}');
            INSERT INTO review_documents
                (id, project_id, filename, document_type, status, created_at)
            VALUES
                (10, 1, 'dup.docx', 'requirement', 'uploaded', '{now}'),
                (11, 1, 'dup.docx', 'requirement', 'uploaded', '{now}'),
                (12, 1, 'other.docx', 'requirement', 'uploaded', '{now}');
            INSERT INTO doc_analyses (id, document_id, task_id)
            VALUES (1, 11, 1);
        """)
        conn.commit()
        conn.close()

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        try:
            async with engine.begin() as aconn:
                await _ensure_review_schema(aconn)

            async with engine.connect() as aconn:
                rows = (await aconn.execute(sa_text(
                    "SELECT id FROM review_documents WHERE filename='dup.docx' ORDER BY id"
                ))).fetchall()
                assert [r[0] for r in rows] == [10], (
                    "迁移应保留最小 id 的重复行，删除其余重复记录"
                )

                leftover_analyses = (await aconn.execute(sa_text(
                    "SELECT id FROM doc_analyses WHERE document_id=11"
                ))).fetchall()
                assert leftover_analyses == [], "被删除重复文档上的分析行应一并清理"

                idx = (await aconn.execute(sa_text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND name='uq_review_doc_proj_type_filename'"
                ))).fetchone()
                assert idx is not None, "迁移后应存在 uq_review_doc_proj_type_filename 唯一索引"

            async with engine.begin() as aconn:
                with pytest.raises(IntegrityError):
                    await aconn.execute(sa_text(
                        "INSERT INTO review_documents "
                        "(project_id, filename, document_type, status, created_at) "
                        f"VALUES (1, 'dup.docx', 'requirement', 'uploaded', '{now}')"
                    ))
        finally:
            await engine.dispose()
            if os.path.exists(db_path):
                os.unlink(db_path)


# ── BUG-154: IntegrityError 应用 savepoint，删除孤儿文件 ───────────


class TestBUG154UploadIntegritySavepoint:
    def test_save_project_documents_uses_savepoint_and_deletes_orphan(self):
        from app.routers.review import _save_project_documents

        src = inspect.getsource(_save_project_documents)
        assert "begin_nested" in src, (
            "IntegrityError 应在 savepoint 内处理，避免 rollback 整批已 flush 的文档"
        )
        assert "rollback()" not in src.replace(" ", ""), (
            "不应再对整段 session 执行 rollback，以免撤销同批已成功文档"
        )
        assert "delete_document_files" in src, (
            "失败分支应删除本次已写入磁盘的 stored 文件"
        )

    async def test_integrity_error_keeps_earlier_docs_and_deletes_orphan(
        self, followup_client,
    ):
        """同批后一个文件 flush 失败时：前面成功的文档应保留，失败文件应从磁盘删除。"""
        ac, session_maker, upload_root = followup_client
        from app.models.review import ReviewDocument
        from app.routers.review import _save_project_documents
        from app.storage.review_file_storage import ReviewFileStorage

        resp = await ac.post("/api/review/projects", json={"name": "savepoint-test"})
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        async with session_maker() as db:
            orig_flush = db.flush
            orig_add = db.add
            added_docs = {"n": 0}

            def _counting_add(obj):
                if isinstance(obj, ReviewDocument):
                    added_docs["n"] += 1
                return orig_add(obj)

            async def _flush_fail_second(*args, **kwargs):
                # 第二个文档 flush 时模拟唯一约束冲突（add_document 内部也会 flush）
                if added_docs["n"] >= 2:
                    raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
                return await orig_flush(*args, **kwargs)

            db.add = _counting_add  # type: ignore[method-assign]
            db.flush = _flush_fail_second  # type: ignore[method-assign]

            result = await _save_project_documents(
                project_id,
                [
                    _MemUpload("keep.docx", _MINIMAL_DOCX),
                    _MemUpload("drop.docx", _MINIMAL_DOCX),
                ],
                db,
            )

        assert result["uploaded"] == 1, result
        assert result["files"][0]["filename"] == "keep.docx"
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["filename"] == "drop.docx"

        async with session_maker() as db:
            docs = (await db.execute(
                select(ReviewDocument).where(ReviewDocument.project_id == project_id)
            )).scalars().all()
            names = sorted(d.filename for d in docs)
            assert names == ["keep.docx"], (
                f"整批 rollback 会丢掉已成功文档，当前库中文件: {names}"
            )
            keep = docs[0]
            assert keep.file_path
            storage = ReviewFileStorage(upload_dir=str(upload_root))
            keep_abs = storage._resolve_stored_file_path(keep.file_path)
            assert keep_abs and os.path.exists(keep_abs), "成功文档的磁盘文件应保留"

        leftover = list(Path(upload_root).rglob("*.docx")) if upload_root.exists() else []
        assert len(leftover) == 1, (
            f"失败文件应被删除，磁盘上不应遗留孤儿 docx，实际: {leftover}"
        )


# ── BUG-155: fixture 应 cancel/await 审查管线任务 ──────────────────


class TestBUG155PipelineTaskFixtureCleanup:
    def test_conftest_stops_pipeline_tasks_before_clear(self):
        src = Path(__file__).parent.joinpath("conftest.py").read_text(encoding="utf-8")
        assert "stop_all_pipeline_tasks" in src, (
            "clear_review_progress_queues 应调用 stop_all_pipeline_tasks，"
            "而不是直接 clear _pipeline_tasks"
        )

    async def test_drain_helper_cancels_unfinished_pipeline_tasks(self):
        from app.routers import review as review_mod
        from tests.conftest import drain_review_pipeline_tasks

        started = asyncio.Event()

        async def _hang():
            started.set()
            await asyncio.sleep(60)

        task = asyncio.create_task(_hang(), name="review-pipeline-test-hang")
        review_mod._pipeline_tasks[987654] = task
        await started.wait()
        try:
            await drain_review_pipeline_tasks(timeout=1.0)
            assert task.cancelled() or task.done()
            assert review_mod._pipeline_tasks == {}
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            review_mod._pipeline_tasks.pop(987654, None)
