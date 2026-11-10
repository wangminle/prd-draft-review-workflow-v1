"""BUG-214 的真实 SQLite/LanceDB 补偿交错回归。"""

import asyncio

import pytest
from sqlalchemy import select, update

from tests.conftest import init_test_db, make_test_app
from app.models.knowledge import KnowledgeChunk
from app.repositories.knowledge_repository import KnowledgeChunkRepository
from app.repositories.knowledge_source_repository import KnowledgeSourceRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services import embedding_worker, knowledge_vector_service
from app.services.embedding_worker import process_pending_embeddings
from app.services.knowledge_ingestion import KnowledgeIngestionService
from app.services.knowledge_vector_service import KnowledgeVectorService, VectorChunk


@pytest.mark.parametrize("case", ["partial_batch", "new_worker_done"])
async def test_compensation_preserves_current_done_vectors(tmp_path, monkeypatch, case):
    _, engine, sessions = make_test_app(str(tmp_path / "knowledge.db"))
    await init_test_db(engine, sessions)
    vectors = KnowledgeVectorService()
    vectors._vector_dir_override = tmp_path / "vectors"
    monkeypatch.setattr(embedding_worker, "get_knowledge_vector_service", lambda: vectors)
    monkeypatch.setattr(knowledge_vector_service, "get_knowledge_vector_service", lambda: vectors)

    class Embedder:
        async def embed_batch(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    async def run_worker():
        async with sessions() as db:
            return await process_pending_embeddings(db, embedding_service=Embedder())

    async with sessions() as db:
        workspace = await WorkspaceRepository(db).get_default()
        workspace_id = workspace.id
        source_ids = []
        labels = ["untouched", "reingested"] if case == "partial_batch" else ["unchanged"]
        for label in labels:
            source = await KnowledgeSourceRepository(db).create(
                workspace_id=workspace_id, source_type="upload", title=label,
                extracted_text=f"synthetic {label} body",
            )
            await KnowledgeIngestionService(db).ingest_source(source.id)
            source_ids.append(source.id)
        await db.commit()

    ready = asyncio.Event()
    release = asyncio.Event()
    original_update = KnowledgeChunkRepository.update_embedding_status_conditional
    first_update = True

    async def gated_update(repository, updates, status, *args, **kwargs):
        nonlocal first_update
        if status == "done" and first_update:
            first_update = False
            ready.set()
            await release.wait()
        return await original_update(repository, updates, status, *args, **kwargs)

    monkeypatch.setattr(KnowledgeChunkRepository, "update_embedding_status_conditional", gated_update)
    task = asyncio.create_task(run_worker())
    try:
        await asyncio.wait_for(ready.wait(), timeout=10)
        async with sessions() as db:
            ingestion = KnowledgeIngestionService(db)
            await ingestion.ingest_source(source_ids[-1])
            await db.commit()
            await ingestion.cleanup_pending_vectors()
        if case == "new_worker_done":
            assert await run_worker() == 1
    finally:
        release.set()
        written = await asyncio.wait_for(task, timeout=10)

    assert written == (1 if case == "partial_batch" else 0)
    async with sessions() as db:
        chunks = (await db.execute(select(KnowledgeChunk))).scalars().all()
        assert sum(chunk.embedding_status == "done" for chunk in chunks) == 1
    hits = await vectors.search([1.0, 0.0, 0.0], workspace_id, top_k=20)
    assert [hit.source_id for hit in hits] == [source_ids[0]]
    await engine.dispose()


async def test_old_vector_table_upgrade_and_cleanup_preserve_new_writer(tmp_path):
    vectors = KnowledgeVectorService()
    vectors._vector_dir_override = tmp_path / "legacy-vectors"
    vectors._get_db().create_table("knowledge_chunks", [{
        "chunk_id": 1, "source_id": 1, "workspace_id": 1,
        "title": "legacy", "section": "", "text": "same body",
        "owner_id": 1, "visibility": "team", "vector": [1.0, 0.0, 0.0],
    }])
    chunk = VectorChunk(1, 1, 1, "legacy", None, "same body")
    chunk.write_token = "writer-a"
    await vectors.upsert([chunk], [[1.0, 0.0, 0.0]])
    row = vectors._get_db().open_table("knowledge_chunks").to_arrow().to_pylist()[0]
    assert row.get("write_token") == "writer-a"

    chunk.write_token = "writer-b"
    await vectors.upsert([chunk], [[1.0, 0.0, 0.0]])
    await vectors.delete_stale_vectors([(1, "same body")], write_token="writer-a")
    assert len(await vectors.search([1.0, 0.0, 0.0], 1)) == 1
    await vectors.delete_stale_vectors([(1, "same body")], write_token="writer-b")
    assert await vectors.search([1.0, 0.0, 0.0], 1) == []


@pytest.mark.parametrize("new_writer_finishes", [False, True])
async def test_failed_worker_cleanup_respects_write_owner(tmp_path, monkeypatch, new_writer_finishes):
    _, engine, sessions = make_test_app(str(tmp_path / "failure.db"))
    await init_test_db(engine, sessions)
    vectors = KnowledgeVectorService()
    vectors._vector_dir_override = tmp_path / "failure-vectors"
    monkeypatch.setattr(embedding_worker, "get_knowledge_vector_service", lambda: vectors)

    async with sessions() as db:
        workspace = await WorkspaceRepository(db).get_default()
        workspace_id = workspace.id
        source = await KnowledgeSourceRepository(db).create(
            workspace_id=workspace_id, source_type="upload", title="failure",
            extracted_text="same body after failed status write",
        )
        await KnowledgeIngestionService(db).ingest_source(source.id)
        await db.commit()
        chunk = (await db.execute(select(KnowledgeChunk))).scalar_one()
        chunk_id, document_id, text, source_id = chunk.id, chunk.document_id, chunk.text, source.id

    original_update = KnowledgeChunkRepository.update_embedding_status_conditional

    async def fail_done(repository, updates, status, *args, **kwargs):
        if status == "done":
            raise OSError("synthetic status write failure")
        return await original_update(repository, updates, status, *args, **kwargs)

    original_delete = vectors.delete_stale_vectors

    async def replace_before_delete(pairs, *, write_token=None):
        if new_writer_finishes:
            # 在 SQLite 检查之后替换向量，验证旧补偿不依赖该检查的时效。
            replacement = VectorChunk(
                chunk_id, source_id, workspace_id, "failure", None, text,
                document_id=document_id, write_token="replacement-writer",
            )
            await vectors.upsert([replacement], [[1.0, 0.0, 0.0]])
            async with sessions() as db:
                await db.execute(update(KnowledgeChunk).where(
                    KnowledgeChunk.id == chunk_id,
                ).values(embedding_status="done"))
                await db.commit()
        return await original_delete(pairs, write_token=write_token)

    class Embedder:
        async def embed_batch(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(KnowledgeChunkRepository, "update_embedding_status_conditional", fail_done)
    monkeypatch.setattr(vectors, "delete_stale_vectors", replace_before_delete)
    async with sessions() as db:
        assert await process_pending_embeddings(db, embedding_service=Embedder()) == 0
    async with sessions() as db:
        chunk = await db.get(KnowledgeChunk, chunk_id)
        assert chunk.embedding_status == ("done" if new_writer_finishes else "failed")
    hits = await vectors.search([1.0, 0.0, 0.0], workspace_id)
    assert len(hits) == int(new_writer_finishes)
    await engine.dispose()
