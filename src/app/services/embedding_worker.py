"""异步 Embedding 消费者：轮询 pending chunks → embed_batch → upsert → 更新状态。"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.workspace import KnowledgeSource
from app.repositories.knowledge_repository import KnowledgeChunkRepository
from app.services.embedding_service import EmbeddingService
from app.services.knowledge_vector_service import (
    VectorChunk,
    get_knowledge_vector_service,
)

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None

DEFAULT_POLL_INTERVAL_SEC = 5.0
DEFAULT_BATCH_SIZE = 32


async def _load_chunk_context(
    db: AsyncSession,
    chunk: KnowledgeChunk,
) -> tuple[KnowledgeDocument | None, KnowledgeSource | None]:
    doc_result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == chunk.document_id)
    )
    doc = doc_result.scalar_one_or_none()
    if doc is None:
        return None, None
    src_result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == doc.source_id)
    )
    source = src_result.scalar_one_or_none()
    return doc, source


async def process_pending_embeddings(
    db: AsyncSession,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    embedding_service: EmbeddingService | None = None,
) -> int:
    """处理一批 pending embedding。返回成功写入向量的条数。"""
    chunk_repo = KnowledgeChunkRepository(db)
    pending = await chunk_repo.list_pending_embedding(limit=batch_size)
    if not pending:
        return 0

    embedder = embedding_service or EmbeddingService()
    vector_svc = get_knowledge_vector_service()

    vector_chunks: list[VectorChunk] = []
    texts: list[str] = []
    chunk_ids: list[int] = []

    for chunk in pending:
        doc, source = await _load_chunk_context(db, chunk)
        if doc is None or source is None:
            await chunk_repo.update_embedding_status([chunk.id], "failed")
            continue
        workspace_id = source.workspace_id or 0
        vector_chunks.append(
            VectorChunk(
                chunk_id=chunk.id,
                source_id=source.id,
                workspace_id=workspace_id,
                title=source.title or "",
                section=chunk.section,
                text=chunk.text,
                owner_id=source.owner_id,
                visibility=chunk.visibility or source.visibility or "team",
            )
        )
        texts.append(chunk.text)
        chunk_ids.append(chunk.id)

    if not texts:
        await db.commit()
        return 0

    try:
        await chunk_repo.update_embedding_status(chunk_ids, "processing")
        await db.commit()

        vectors = await embedder.embed_batch(texts)
        written = await vector_svc.upsert(vector_chunks, vectors)
        await chunk_repo.update_embedding_status(chunk_ids, "done")
        await db.commit()
        logger.info("[EMBED-WORKER] processed=%d written=%d", len(chunk_ids), written)
        return written
    except Exception as e:
        logger.exception("[EMBED-WORKER] batch failed: %s", e)
        try:
            await db.rollback()
            await chunk_repo.update_embedding_status(chunk_ids, "failed")
            await db.commit()
        except Exception:
            logger.exception("[EMBED-WORKER] failed to mark chunks as failed")
        return 0


async def _worker_loop(poll_interval: float = DEFAULT_POLL_INTERVAL_SEC) -> None:
    from app.database import async_session

    assert _stop_event is not None
    logger.info("[EMBED-WORKER] started")
    while not _stop_event.is_set():
        try:
            async with async_session() as db:
                await process_pending_embeddings(db)
        except Exception:
            logger.exception("[EMBED-WORKER] loop error")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass
    logger.info("[EMBED-WORKER] stopped")


async def start_embedding_worker(poll_interval: float = DEFAULT_POLL_INTERVAL_SEC) -> None:
    """启动后台 embedding 消费者（幂等）。"""
    global _worker_task, _stop_event
    if _worker_task is not None and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop(poll_interval), name="embedding-worker")


async def stop_embedding_worker() -> None:
    """停止后台 embedding 消费者。"""
    global _worker_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _worker_task is not None:
        try:
            await asyncio.wait_for(_worker_task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _worker_task.cancel()
        _worker_task = None
    _stop_event = None
