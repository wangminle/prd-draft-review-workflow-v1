"""P2 知识库检索与对话 RAG — 自动化测试

覆盖范围：
- P2.A.1 KnowledgeDocument 数据模型
- P2.A.2 KnowledgeChunk 数据模型（含 embedding_status）
- P2.A.3 KnowledgeIngestionService（解析→切块→FTS 索引）
- P2.A.4 切块策略（章节保留、长度限制、重叠）
- P2.A.5 EmbeddingService（mock 测试，不调用真实 API）
- P2.B.3 RetrievalLog 数据模型
- P2.B.4 检索 API
- P2.D.3 AnswerFeedback 数据模型
- P2.E.1 KnowledgeVectorService（LanceDB 操作）
- P2.E.2 FTS5 降级回退
- P2.E.3 拒答策略（dist[0] + gap）
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.user import Base, User
from app.models.knowledge import (
    KnowledgeDocument,
    KnowledgeChunk,
    RetrievalLog,
    AnswerFeedback,
    VALID_EMBEDDING_STATUSES,
)
from app.models.workspace import KnowledgeSource, Workspace, WorkspaceMember
from app.repositories.knowledge_repository import (
    KnowledgeDocumentRepository,
    KnowledgeChunkRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.repositories.knowledge_source_repository import KnowledgeSourceRepository
from app.services.auth import hash_password


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def admin_user(db_session):
    admin = User(username="admin", password_hash=hash_password("admin@2026"), role="admin")
    db_session.add(admin)
    await db_session.flush()
    await db_session.refresh(admin)
    return admin


@pytest_asyncio.fixture
async def default_workspace(db_session, admin_user):
    ws = Workspace(name="测试空间", is_default=True, created_by=admin_user.id, status="active")
    db_session.add(ws)
    await db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="owner", status="active"))
    await db_session.flush()
    return ws


@pytest_asyncio.fixture
def sample_text():
    """供切块测试用的样例文本，含标题、章节、长段落。"""
    return """# 产品需求文档：智能对话系统

## 1. 项目概述

本项目旨在构建一个基于大语言模型的智能对话系统，支持多轮对话、上下文理解和知识库检索。

## 2. 功能需求

### 2.1 对话管理

用户可以创建、管理和删除对话会话。每个会话独立维护上下文和历史消息。

### 2.2 知识库检索

系统支持从团队资料库中检索相关文档，并将检索结果作为上下文注入对话。
检索采用向量相似度匹配，支持 FTS5 关键词降级。

### 2.3 审查集成

审查项目可以引用团队资料库中的文档，在审查过程中自动注入相关上下文。

## 3. 非功能需求

### 3.1 性能要求

- 单次检索延迟 < 500ms（P95）
- 系统支持 120 QPS 并发检索
- 冷启动预热后 P99 < 2s

### 3.2 安全要求

- 跨工作空间检索必须返回空结果
- 成员停用后不可检索团队资料
- 检索日志记录所有查询
"""


@pytest_asyncio.fixture
async def source_with_text(db_session, default_workspace):
    """创建有正文的 KnowledgeSource。"""
    ks_repo = KnowledgeSourceRepository(db_session)
    source = await ks_repo.create(
        workspace_id=default_workspace.id,
        source_type="upload",
        title="测试文档.md",
        extracted_text="# 测试章节\n\n这是一个关于向量检索的测试文档。包含关键词匹配和语义理解。",
    )
    await db_session.flush()
    return source


# ── P2.A.1: KnowledgeDocument 数据模型 ──


class TestKnowledgeDocumentModel:
    """P2.A.1: KnowledgeDocument 表创建和 CRUD。"""

    @pytest.mark.asyncio
    async def test_knowledge_document_table_exists(self, db_session):
        """验证 knowledge_documents 表创建成功。"""
        result = await db_session.execute(text("PRAGMA table_info(knowledge_documents)"))
        columns = {row[1] for row in result.fetchall()}
        assert "id" in columns
        assert "source_id" in columns
        assert "filename" in columns
        assert "content_hash" in columns
        assert "version" in columns
        assert "metadata_json" in columns

    @pytest.mark.asyncio
    async def test_knowledge_document_crud(self, db_session, default_workspace):
        """验证 KnowledgeDocument CRUD 操作。"""
        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(workspace_id=default_workspace.id, source_type="upload", title="test.md")
        await db_session.flush()

        repo = KnowledgeDocumentRepository(db_session)
        doc = await repo.create(source_id=source.id, filename="test.md", content_hash="abc123")
        assert doc.id is not None
        assert doc.source_id == source.id
        assert doc.version == 1

        fetched = await repo.get_by_id(doc.id)
        assert fetched is not None
        assert fetched.filename == "test.md"

        by_source = await repo.get_by_source_id(source.id)
        assert by_source is not None

        updated = await repo.update_version(doc.id, content_hash="def456")
        assert updated.version == 2
        assert updated.content_hash == "def456"

    @pytest.mark.asyncio
    async def test_knowledge_document_delete_by_source(self, db_session, default_workspace):
        """验证通过 source_id 删除文档（1:1 关系，每个 source 对应一个 document）。"""
        ks_repo = KnowledgeSourceRepository(db_session)
        source1 = await ks_repo.create(workspace_id=default_workspace.id, source_type="upload", title="test1.md")
        source2 = await ks_repo.create(workspace_id=default_workspace.id, source_type="upload", title="test2.md")
        await db_session.flush()

        repo = KnowledgeDocumentRepository(db_session)
        await repo.create(source_id=source1.id, filename="test1.md")
        await repo.create(source_id=source2.id, filename="test2.md")
        await db_session.flush()

        # 删除 source1 对应的文档
        count = await repo.delete_by_source_id(source1.id)
        assert count == 1

        by_source1 = await repo.get_by_source_id(source1.id)
        assert by_source1 is None

        # source2 的文档仍然存在
        by_source2 = await repo.get_by_source_id(source2.id)
        assert by_source2 is not None


# ── P2.A.2: KnowledgeChunk 数据模型 ──


class TestKnowledgeChunkModel:
    """P2.A.2: KnowledgeChunk 表创建和 CRUD，含 embedding_status。"""

    @pytest.mark.asyncio
    async def test_knowledge_chunk_table_exists(self, db_session):
        """验证 knowledge_chunks 表创建成功。"""
        result = await db_session.execute(text("PRAGMA table_info(knowledge_chunks)"))
        columns = {row[1] for row in result.fetchall()}
        assert "id" in columns
        assert "document_id" in columns
        assert "chunk_no" in columns
        assert "text" in columns
        assert "section" in columns
        assert "source_ref" in columns
        assert "embedding_status" in columns

    @pytest.mark.asyncio
    async def test_embedding_status_default(self, db_session, default_workspace):
        """验证 embedding_status 默认为 pending。"""
        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(workspace_id=default_workspace.id, source_type="upload", title="test.md")
        await db_session.flush()

        doc_repo = KnowledgeDocumentRepository(db_session)
        doc = await doc_repo.create(source_id=source.id)

        repo = KnowledgeChunkRepository(db_session)
        chunks = await repo.create_batch(doc.id, [
            {"chunk_no": 1, "text": "hello"},
            {"chunk_no": 2, "text": "world"},
        ])
        assert len(chunks) == 2
        assert chunks[0].embedding_status == "pending"
        assert chunks[1].embedding_status == "pending"

    @pytest.mark.asyncio
    async def test_update_embedding_status(self, db_session, default_workspace):
        """验证批量更新 embedding_status。"""
        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(workspace_id=default_workspace.id, source_type="upload", title="test.md")
        await db_session.flush()

        doc_repo = KnowledgeDocumentRepository(db_session)
        doc = await doc_repo.create(source_id=source.id)

        repo = KnowledgeChunkRepository(db_session)
        chunks = await repo.create_batch(doc.id, [
            {"chunk_no": 1, "text": "hello"},
            {"chunk_no": 2, "text": "world"},
            {"chunk_no": 3, "text": "foo"},
        ])
        await db_session.flush()

        count = await repo.update_embedding_status([chunks[0].id, chunks[1].id], "done")
        assert count == 2

        fetched = await repo.get_by_id(chunks[0].id)
        assert fetched.embedding_status == "done"
        fetched2 = await repo.get_by_id(chunks[2].id)
        assert fetched2.embedding_status == "pending"

    @pytest.mark.asyncio
    async def test_invalid_embedding_status_rejected(self, db_session):
        """验证无效 embedding_status 被拒绝。"""
        repo = KnowledgeChunkRepository(db_session)
        with pytest.raises(ValueError, match="Invalid embedding_status"):
            await repo.update_embedding_status([1], "invalid")

    @pytest.mark.asyncio
    async def test_list_pending_embedding(self, db_session, default_workspace):
        """验证获取待嵌入 chunks。"""
        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(workspace_id=default_workspace.id, source_type="upload", title="test.md")
        await db_session.flush()

        doc_repo = KnowledgeDocumentRepository(db_session)
        doc = await doc_repo.create(source_id=source.id)

        repo = KnowledgeChunkRepository(db_session)
        chunks = await repo.create_batch(doc.id, [
            {"chunk_no": i, "text": f"chunk {i}"}
            for i in range(1, 6)
        ])
        await db_session.flush()

        await repo.update_embedding_status([chunks[0].id, chunks[1].id], "done")

        pending = await repo.list_pending_embedding(limit=10)
        pending_ids = {c.id for c in pending}
        assert chunks[2].id in pending_ids
        assert chunks[3].id in pending_ids
        assert chunks[4].id in pending_ids
        assert chunks[0].id not in pending_ids


# ── P2.A.4: 切块策略 ──


class TestChunkingStrategy:
    """P2.A.4: 切块策略测试。"""

    def test_chunk_empty_text(self):
        from app.services.chunking import chunk_text
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_chunk_short_text(self):
        from app.services.chunking import chunk_text
        text = "这是一段简短的文本。"
        result = chunk_text(text)
        assert len(result) == 1
        assert result[0].text == text

    def test_chunk_preserves_sections(self, sample_text):
        from app.services.chunking import chunk_text
        result = chunk_text(sample_text)
        sections = {r.section for r in result if r.section}
        assert len(sections) >= 3

    def test_chunk_max_chars_respected(self, sample_text):
        from app.services.chunking import chunk_text, MAX_CHUNK_CHARS
        result = chunk_text(sample_text, max_chars=MAX_CHUNK_CHARS)
        for r in result:
            assert len(r.text) <= MAX_CHUNK_CHARS * 1.1

    def test_chunk_source_ref_propagated(self):
        from app.services.chunking import chunk_text
        result = chunk_text("一些文本", source_ref="test.md")
        assert all(r.source_ref == "test.md" for r in result)

    def test_chunk_long_paragraph_hard_split(self):
        from app.services.chunking import chunk_text
        long_text = "这是一段很长的文本。" * 200
        result = chunk_text(long_text, max_chars=512)
        assert len(result) > 1
        for r in result:
            assert len(r.text) <= 560

    def test_chunk_no_heading(self):
        from app.services.chunking import chunk_text
        text = "这是第一段。\n\n这是第二段。\n\n这是第三段。"
        result = chunk_text(text)
        assert len(result) >= 1
        assert result[0].section is None

    def test_chunk_custom_params(self):
        from app.services.chunking import chunk_text
        text = "A" * 1000
        result = chunk_text(text, max_chars=200, overlap_chars=20)
        assert len(result) > 3


# ── P2.A.3: KnowledgeIngestionService ──


class TestKnowledgeIngestionService:
    """P2.A.3: 知识入库服务测试。"""

    @pytest.mark.asyncio
    async def test_ingest_source_creates_document_and_chunks(self, db_session, default_workspace):
        from app.services.knowledge_ingestion import KnowledgeIngestionService

        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(
            workspace_id=default_workspace.id,
            source_type="upload",
            title="test.md",
            extracted_text="# 标题\n\n这是测试内容。\n\n## 第二节\n\n更多内容。",
        )
        await db_session.flush()

        ingestion = KnowledgeIngestionService(db_session)
        doc = await ingestion.ingest_source(source.id)
        assert doc is not None
        assert doc.source_id == source.id

        chunk_repo = KnowledgeChunkRepository(db_session)
        chunks = await chunk_repo.list_by_document(doc.id)
        assert len(chunks) >= 1
        assert all(c.embedding_status == "pending" for c in chunks)

    @pytest.mark.asyncio
    async def test_ingest_nonexistent_source_returns_none(self, db_session):
        from app.services.knowledge_ingestion import KnowledgeIngestionService
        ingestion = KnowledgeIngestionService(db_session)
        result = await ingestion.ingest_source(99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_ingest_source_with_no_text_returns_none(self, db_session, default_workspace):
        from app.services.knowledge_ingestion import KnowledgeIngestionService

        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(
            workspace_id=default_workspace.id, source_type="upload", title="empty.md"
        )
        await db_session.flush()

        ingestion = KnowledgeIngestionService(db_session)
        result = await ingestion.ingest_source(source.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_ingest_reingest_replaces_old_data(self, db_session, default_workspace):
        from app.services.knowledge_ingestion import KnowledgeIngestionService

        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(
            workspace_id=default_workspace.id,
            source_type="upload",
            title="test.md",
            extracted_text="第一次内容",
        )
        await db_session.flush()

        ingestion = KnowledgeIngestionService(db_session)
        doc1 = await ingestion.ingest_source(source.id)
        assert doc1 is not None

        # 更新正文并提交
        source.extracted_text = "第二次内容，完全不同的文本"
        await db_session.flush()

        # 重新创建 ingestion service（避免缓存问题）
        ingestion2 = KnowledgeIngestionService(db_session)
        doc2 = await ingestion2.ingest_source(source.id)
        assert doc2 is not None
        # 新文档应该创建（旧文档被删除后创建新的）
        assert doc2.source_id == source.id


# ── P2.A.5: EmbeddingService ──


class TestEmbeddingService:
    """P2.A.5: Embedding 服务测试（mock API，不调用真实 API）。"""

    def test_embedding_service_init_from_env(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "EMBEDDING_MODEL": "custom-model"}):
            from app.services.embedding_service import EmbeddingService, reset_embedding_service
            reset_embedding_service()
            svc = EmbeddingService()
            assert svc._api_key == "test-key"
            assert svc.model == "custom-model"
            reset_embedding_service()

    def test_embedding_service_default_model(self):
        from app.services.embedding_service import EmbeddingService, DEFAULT_EMBEDDING_MODEL
        svc = EmbeddingService(api_key="test")
        assert svc.model == DEFAULT_EMBEDDING_MODEL
        assert svc.dimensions == 1536

    @pytest.mark.asyncio
    async def test_embed_query_uses_cache(self):
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService(api_key="test")

        mock_vector = [0.1] * 1536
        svc._call_api = AsyncMock(return_value=[mock_vector])

        result1 = await svc.embed_query("test query")
        assert result1 == mock_vector
        assert svc._call_api.call_count == 1

        result2 = await svc.embed_query("test query")
        assert result2 == mock_vector
        assert svc._call_api.call_count == 1

    @pytest.mark.asyncio
    async def test_embed_batch_splits_correctly(self):
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService(api_key="test", max_batch_size=3)

        # _call_api 对每批返回对应数量的 vectors
        call_count = 0

        async def mock_call_api(texts):
            return [[0.1] * 1536 for _ in texts]

        svc._call_api = AsyncMock(side_effect=mock_call_api)

        texts = ["text1", "text2", "text3", "text4", "text5"]
        result = await svc.embed_batch(texts)
        assert len(result) == 5
        assert svc._call_api.call_count == 2

    @pytest.mark.asyncio
    async def test_embed_no_api_key_raises(self):
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService(api_key="")
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY 未配置"):
            await svc.embed_query("test")


# ── P2.B.3: RetrievalLog 数据模型 ──


class TestRetrievalLogModel:
    """P2.B.3: RetrievalLog 表创建和写入。"""

    @pytest.mark.asyncio
    async def test_retrieval_log_table_exists(self, db_session):
        result = await db_session.execute(text("PRAGMA table_info(retrieval_logs)"))
        columns = {row[1] for row in result.fetchall()}
        assert "id" in columns
        assert "query" in columns
        assert "workspace_id" in columns
        assert "hit_count" in columns
        assert "latency_ms" in columns
        assert "fallback_reason" in columns
        assert "user_id" in columns

    @pytest.mark.asyncio
    async def test_retrieval_log_write(self, db_session):
        log = RetrievalLog(
            query="测试查询",
            workspace_id=1,
            hit_count=3,
            latency_ms=150.5,
            user_id=1,
        )
        db_session.add(log)
        await db_session.flush()
        assert log.id is not None
        assert log.query == "测试查询"
        assert log.latency_ms == 150.5


# ── P2.D.3: AnswerFeedback 数据模型 ──


class TestAnswerFeedbackModel:
    """P2.D.3: AnswerFeedback 表创建和写入。"""

    @pytest.mark.asyncio
    async def test_answer_feedback_table_exists(self, db_session):
        result = await db_session.execute(text("PRAGMA table_info(answer_feedbacks)"))
        columns = {row[1] for row in result.fetchall()}
        assert "id" in columns
        assert "object_type" in columns
        assert "object_id" in columns
        assert "user_id" in columns
        assert "rating" in columns
        assert "comment" in columns

    @pytest.mark.asyncio
    async def test_answer_feedback_write(self, db_session):
        feedback = AnswerFeedback(
            object_type="retrieval",
            object_id=1,
            user_id=1,
            rating="helpful",
            comment="很有帮助",
        )
        db_session.add(feedback)
        await db_session.flush()
        assert feedback.id is not None
        assert feedback.rating == "helpful"


# ── P2.E.1: KnowledgeVectorService ──


class TestKnowledgeVectorService:
    """P2.E.1: KnowledgeVectorService LanceDB 操作测试。"""

    @pytest.mark.asyncio
    async def test_vector_service_upsert_and_search(self, tmp_path):
        try:
            import lancedb
        except ImportError:
            pytest.skip("LanceDB 未安装")

        from app.services.knowledge_vector_service import KnowledgeVectorService, VectorChunk

        svc = KnowledgeVectorService()
        svc._get_db = lambda: lancedb.connect(str(tmp_path))

        chunks = [
            VectorChunk(chunk_id=1, source_id=100, workspace_id=1, title="测试文档", section="第一节", text="这是测试内容"),
            VectorChunk(chunk_id=2, source_id=100, workspace_id=1, title="测试文档", section="第二节", text="更多测试内容"),
        ]
        vectors = [[0.1] * 1536, [0.2] * 1536]

        count = await svc.upsert(chunks, vectors)
        assert count == 2

        results = await svc.search([0.1] * 1536, workspace_id=1, top_k=5)
        assert len(results) >= 1
        assert results[0].source_id == 100

    @pytest.mark.asyncio
    async def test_vector_service_search_filters_workspace(self, tmp_path):
        try:
            import lancedb
        except ImportError:
            pytest.skip("LanceDB 未安装")

        from app.services.knowledge_vector_service import KnowledgeVectorService, VectorChunk

        svc = KnowledgeVectorService()
        svc._get_db = lambda: lancedb.connect(str(tmp_path))

        await svc.upsert(
            [VectorChunk(chunk_id=1, source_id=100, workspace_id=1, title="WS1", section=None, text="workspace 1 content")],
            [[0.1] * 1536],
        )

        results = await svc.search([0.1] * 1536, workspace_id=2, top_k=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_vector_service_backup_restore(self, tmp_path):
        try:
            import lancedb
        except ImportError:
            pytest.skip("LanceDB 未安装")

        from app.services.knowledge_vector_service import KnowledgeVectorService, VectorChunk

        # 使用真实目录（LanceDB 备份基于目录复制）
        db_dir = tmp_path / "lancedb"
        svc = KnowledgeVectorService()
        svc._vector_dir_override = db_dir  # 覆盖索引目录
        svc._get_db = lambda: lancedb.connect(str(db_dir))

        await svc.upsert(
            [VectorChunk(chunk_id=1, source_id=100, workspace_id=1, title="test", section=None, text="backup test")],
            [[0.1] * 1536],
        )

        # 备份
        backup_path = tmp_path / "backup"
        result = await svc.backup(backup_path)
        assert backup_path.exists()
        assert any(backup_path.iterdir())

        # 恢复
        svc2 = KnowledgeVectorService()
        svc2._vector_dir_override = db_dir  # 恢复到同目录
        success = await svc2.restore(backup_path)
        assert success

    @pytest.mark.asyncio
    async def test_vector_service_delete_by_source(self, tmp_path):
        try:
            import lancedb
        except ImportError:
            pytest.skip("LanceDB 未安装")

        from app.services.knowledge_vector_service import KnowledgeVectorService, VectorChunk

        svc = KnowledgeVectorService()
        svc._get_db = lambda: lancedb.connect(str(tmp_path))

        await svc.upsert(
            [VectorChunk(chunk_id=1, source_id=100, workspace_id=1, title="test", section=None, text="delete test")],
            [[0.1] * 1536],
        )

        result = await svc.delete_by_source(100)
        # LanceDB delete 不返回 count，但不应报错

        # 搜索应返回空
        results = await svc.search([0.1] * 1536, workspace_id=1, top_k=5)
        assert len(results) == 0


# ── P2.E.2: FTS5 降级回退 ──


class TestFTS5Fallback:
    """P2.E.2: FTS5 降级回退测试。"""

    @pytest.mark.asyncio
    async def test_fts_search_basic(self, db_session, source_with_text):
        from app.services.knowledge_ingestion import KnowledgeIngestionService

        ingestion = KnowledgeIngestionService(db_session)
        await ingestion.ingest_source(source_with_text.id)
        await db_session.commit()

        # 重新获取 ingestion（FTS 虚拟表在同一 session 中）
        ingestion2 = KnowledgeIngestionService(db_session)
        results = await ingestion2.search_fts("向量检索", source_with_text.workspace_id)
        assert len(results) >= 1
        assert "向量检索" in results[0]["text"]


# ── P2.E.3: 拒答策略 ──


class TestRejectionPolicy:
    """P2.E.3: 拒答策略测试（dist[0] + gap）。"""

    def test_dist_threshold_rejection(self):
        from app.services.retrieval_service import RetrievalService, SearchResult

        svc = RetrievalService(dist_threshold=1.0, gap_threshold=0.065)

        results = svc._apply_rejection_policy([
            SearchResult(chunk_id=1, source_id=1, section=None, text_snippet="test", _distance=1.5),
            SearchResult(chunk_id=2, source_id=1, section=None, text_snippet="test2", _distance=1.8),
        ])
        assert all(r.rejected for r in results)
        assert all(r.confidence == "low" for r in results)

    def test_gap_threshold_rejection(self):
        from app.services.retrieval_service import RetrievalService, SearchResult

        svc = RetrievalService(dist_threshold=1.0, gap_threshold=0.065)

        results = svc._apply_rejection_policy([
            SearchResult(chunk_id=1, source_id=1, section=None, text_snippet="test", _distance=0.8),
            SearchResult(chunk_id=2, source_id=1, section=None, text_snippet="test2", _distance=0.82),
        ])
        assert results[0].rejected is True
        assert results[0].confidence == "low"

    def test_high_confidence_result(self):
        from app.services.retrieval_service import RetrievalService, SearchResult

        svc = RetrievalService(dist_threshold=1.0, gap_threshold=0.065)

        results = svc._apply_rejection_policy([
            SearchResult(chunk_id=1, source_id=1, section=None, text_snippet="test", _distance=0.3),
            SearchResult(chunk_id=2, source_id=1, section=None, text_snippet="test2", _distance=0.8),
        ])
        assert results[0].rejected is False
        assert results[0].confidence == "high"

    def test_medium_confidence_result(self):
        from app.services.retrieval_service import RetrievalService, SearchResult

        svc = RetrievalService(dist_threshold=1.0, gap_threshold=0.065)

        results = svc._apply_rejection_policy([
            SearchResult(chunk_id=1, source_id=1, section=None, text_snippet="test", _distance=0.7),
            SearchResult(chunk_id=2, source_id=1, section=None, text_snippet="test2", _distance=0.9),
        ])
        assert results[0].rejected is False
        assert results[0].confidence == "medium"

    def test_empty_results_returns_empty(self):
        from app.services.retrieval_service import RetrievalService
        svc = RetrievalService()
        result = svc._apply_rejection_policy([])
        assert result == []

    def test_single_result_no_gap_check(self):
        from app.services.retrieval_service import RetrievalService, SearchResult

        svc = RetrievalService(dist_threshold=1.0, gap_threshold=0.065)

        results = svc._apply_rejection_policy([
            SearchResult(chunk_id=1, source_id=1, section=None, text_snippet="test", _distance=0.5),
        ])
        assert results[0].rejected is False

    def test_configurable_thresholds(self):
        from app.services.retrieval_service import RetrievalService, SearchResult

        # 更宽松的阈值
        svc = RetrievalService(dist_threshold=2.0, gap_threshold=0.01)

        results = svc._apply_rejection_policy([
            SearchResult(chunk_id=1, source_id=1, section=None, text_snippet="test", _distance=1.5),
            SearchResult(chunk_id=2, source_id=1, section=None, text_snippet="test2", _distance=1.51),
        ])
        # dist=1.5 < 2.0 → 不绝对拒答；gap=0.01 → 不低置信
        assert results[0].rejected is False


# ── P2.B.1: RetrievalService 降级回退 ──


class TestRetrievalServiceFallback:
    """P2.B.1 + P2.E.2: RetrievalService 降级回退测试。"""

    @pytest.mark.asyncio
    async def test_retrieve_falls_back_to_fts_when_lancedb_unavailable(self, db_session, source_with_text):
        """LanceDB 不可用时自动降级到 FTS5。"""
        from app.services.retrieval_service import RetrievalService
        from app.services.knowledge_vector_service import KnowledgeVectorService

        # 先入库（创建 FTS 索引）
        from app.services.knowledge_ingestion import KnowledgeIngestionService
        ingestion = KnowledgeIngestionService(db_session)
        await ingestion.ingest_source(source_with_text.id)
        await db_session.commit()

        # 创建 Mock vector service 模拟 LanceDB 不可用
        mock_vector = MagicMock(spec=KnowledgeVectorService)
        mock_vector.is_available = False

        # Mock embedding service 返回向量（但不会用到，因为 vector service 不可用）
        from app.services.embedding_service import EmbeddingService
        mock_embedding = MagicMock(spec=EmbeddingService)
        mock_embedding.embed_query = AsyncMock(return_value=[0.1] * 1536)

        svc = RetrievalService(
            vector_service=mock_vector,
            embedding_service=mock_embedding,
            db_session=db_session,  # 注入测试 session
        )
        response = await svc.retrieve("向量检索", source_with_text.workspace_id)

        assert response.fallback_reason is not None
        # 应该有结果（FTS5 降级成功）
        assert response.total >= 1
        # LanceDB 不可用时不应先调用 embedding API，避免无意义外部请求
        mock_embedding.embed_query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retrieve_falls_back_to_fts_when_lancedb_empty(self, db_session, source_with_text):
        """LanceDB 可用但未建向量索引时，应降级到已有 FTS5 索引。"""
        from app.services.retrieval_service import RetrievalService
        from app.services.knowledge_vector_service import KnowledgeVectorService
        from app.services.embedding_service import EmbeddingService
        from app.services.knowledge_ingestion import KnowledgeIngestionService

        ingestion = KnowledgeIngestionService(db_session)
        await ingestion.ingest_source(source_with_text.id)
        await db_session.commit()

        mock_vector = MagicMock(spec=KnowledgeVectorService)
        mock_vector.is_available = True
        mock_vector.search = AsyncMock(return_value=[])

        mock_embedding = MagicMock(spec=EmbeddingService)
        mock_embedding.embed_query = AsyncMock(return_value=[0.1] * 1536)

        svc = RetrievalService(
            vector_service=mock_vector,
            embedding_service=mock_embedding,
            db_session=db_session,
        )
        response = await svc.retrieve("向量检索", source_with_text.workspace_id)

        assert response.fallback_reason == "lancedb_empty_results"
        assert response.total >= 1

    @pytest.mark.asyncio
    async def test_fts_special_char_query_does_not_fail(self, db_session, source_with_text):
        """FTS fallback 应清理特殊字符，避免 MATCH 语法错误导致 all_failed。"""
        from app.services.knowledge_ingestion import KnowledgeIngestionService

        ingestion = KnowledgeIngestionService(db_session)
        await ingestion.ingest_source(source_with_text.id)
        await db_session.commit()

        results = await ingestion.search_fts('向量检索 "权益" OR (', source_with_text.workspace_id)
        assert isinstance(results, list)


class TestReviewKnowledgeContext:
    """P2.C.2 审查知识上下文注入边界测试。"""

    @pytest.mark.asyncio
    async def test_review_context_skips_archived_sources(self, db_session, default_workspace, admin_user):
        """已归档资料不应继续注入审查上下文。"""
        from app.models.review import ReviewProject
        from app.models.workspace import ProjectSourceRef
        from app.services.knowledge_ingestion import KnowledgeIngestionService
        from app.routers.review import _load_project_knowledge_context

        active_source = KnowledgeSource(
            workspace_id=default_workspace.id,
            source_type="upload",
            title="有效资料.md",
            extracted_text="# 有效资料\n\n这是 active source 应注入的上下文。",
            owner_id=admin_user.id,
            status="active",
        )
        archived_source = KnowledgeSource(
            workspace_id=default_workspace.id,
            source_type="upload",
            title="归档资料.md",
            extracted_text="# 归档资料\n\n这是 archived source 不应注入的上下文。",
            owner_id=admin_user.id,
            status="archived",
        )
        db_session.add_all([active_source, archived_source])
        await db_session.flush()

        project = ReviewProject(
            name="审查项目",
            created_by=admin_user.id,
            workspace_id=default_workspace.id,
        )
        db_session.add(project)
        await db_session.flush()
        db_session.add_all([
            ProjectSourceRef(project_id=project.id, source_id=active_source.id, ref_type="context"),
            ProjectSourceRef(project_id=project.id, source_id=archived_source.id, ref_type="context"),
        ])
        await db_session.flush()

        ingestion = KnowledgeIngestionService(db_session)
        await ingestion.ingest_source(active_source.id)
        await ingestion.ingest_source(archived_source.id)
        await db_session.commit()

        context = await _load_project_knowledge_context(db_session, project.id)
        assert context is not None
        assert "有效资料" in context
        assert "active source" in context
        assert "归档资料" not in context
        assert "archived source" not in context
