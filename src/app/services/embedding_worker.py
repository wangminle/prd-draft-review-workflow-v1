"""异步 Embedding 消费者：轮询 pending chunks → embed_batch → upsert → 更新状态。"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.workspace import KnowledgeSource
from app.repositories.knowledge_repository import KnowledgeChunkRepository
from app.services.embedding_service import EmbeddingService
from app.services.knowledge_vector_service import (
    VectorChunk,
    KnowledgeVectorService,
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


async def _cleanup_written_vectors(
    db: AsyncSession,
    vector_svc: KnowledgeVectorService,
    pairs: list[tuple[int, str, int]],
    write_token: str,
) -> None:
    """只补偿本次写入，保留当前已完成身份和其他 worker 的向量。"""
    if not pairs:
        return
    await db.rollback()
    rows = await db.execute(
        select(KnowledgeChunk.id, KnowledgeChunk.text, KnowledgeChunk.document_id)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
        .where(
            KnowledgeChunk.id.in_([pair[0] for pair in pairs]),
            KnowledgeChunk.embedding_status == "done",
            KnowledgeSource.status == "active",
        )
    )
    completed = {tuple(row) for row in rows.fetchall()}
    stale = [pair for pair in pairs if pair not in completed]
    if stale:
        await vector_svc.delete_stale_vectors(stale, write_token=write_token)


async def process_pending_embeddings(
    db: AsyncSession,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    embedding_service: EmbeddingService | None = None,
) -> int:
    """处理一批 pending embedding。返回成功写入向量的条数。

    BUG-148: 如果 worker 在 processing 阶段崩溃（OOM、API 异常等），
    chunks 的 embedding_status 会卡在 "processing" 永远不会被重新消费。
    每次循环开始时将所有 "processing" chunks 重置为 "pending"——
    正常流程中 processing -> done/failed 在一次循环内完成，
    任何残留的 processing 状态都是上次崩溃遗留。
    """
    chunk_repo = KnowledgeChunkRepository(db)

    # 重置 stale "processing" chunks（worker 崩溃后遗留）
    from sqlalchemy import update as sa_update
    stale_result = await db.execute(
        sa_update(KnowledgeChunk)
        .where(KnowledgeChunk.embedding_status == "processing")
        .values(embedding_status="pending")
    )
    if stale_result.rowcount > 0:
        logger.warning(
            "[EMBED-WORKER] reset %d stale 'processing' chunks to 'pending'",
            stale_result.rowcount,
        )
        await db.commit()

    pending = await chunk_repo.list_pending_embedding(limit=batch_size)
    if not pending:
        return 0

    embedder = embedding_service or EmbeddingService()
    vector_svc = get_knowledge_vector_service()

    vector_chunks: list[VectorChunk] = []
    texts: list[str] = []
    chunk_ids: list[int] = []
    write_token = uuid.uuid4().hex

    for chunk in pending:
        doc, source = await _load_chunk_context(db, chunk)
        if doc is None or source is None or source.status != "active":
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
                document_id=chunk.document_id,
                write_token=write_token,
            )
        )
        texts.append(chunk.text)
        chunk_ids.append(chunk.id)

    if not texts:
        await db.commit()
        return 0

    vector_write_started = False
    try:
        await chunk_repo.update_embedding_status(chunk_ids, "processing")
        await db.commit()

        vectors = await embedder.embed_batch(texts)
        # BUG-214：embedding 期间源资料可能已重入库、被新 worker 完成，或已被删除归档。
        # 先释放读快照确保读到最新已提交状态，再联合校验切块正文、切块状态与 source.status。
        await db.rollback()
        current_rows = await db.execute(
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.text,
                KnowledgeChunk.embedding_status,
                KnowledgeSource.id,
                KnowledgeSource.status,
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(KnowledgeChunk.id.in_(chunk_ids))
        )
        current_state = {
            row[0]: (row[1], row[2], row[3], row[4])
            for row in current_rows.fetchall()
        }
        kept_chunks = []
        kept_vectors = []
        kept_ids = []
        archived_chunk_ids = []
        archived_source_ids = set()
        for chunk, vector in zip(vector_chunks, vectors):
            state = current_state.get(chunk.chunk_id)
            if state is None:
                continue
            cur_text, cur_status, cur_source_id, cur_source_status = state
            if cur_source_status != "active" or cur_source_id != chunk.source_id:
                if cur_source_status != "active" and cur_text == chunk.text and cur_status != "done":
                    archived_chunk_ids.append(chunk.chunk_id)
                    archived_source_ids.add(cur_source_id)
                continue
            if cur_text != chunk.text or cur_status == "done":
                # 正文已被替换或新 worker 已完成写入，绝不回写旧向量或覆盖新状态
                continue
            kept_chunks.append(chunk)
            kept_vectors.append(vector)
            kept_ids.append(chunk.chunk_id)

        if archived_chunk_ids:
            await chunk_repo.update_embedding_status(archived_chunk_ids, "failed")
            await db.commit()
        for sid in archived_source_ids:
            try:
                await vector_svc.delete_by_source(sid)
            except Exception:
                logger.warning("[EMBED-WORKER] failed to cleanup archived source=%s vectors", sid)

        if not kept_chunks:
            logger.warning("[EMBED-WORKER] all chunks changed, completed, or archived during embedding, skip stale writes")
            return 0
        vector_chunks, vectors, chunk_ids = kept_chunks, kept_vectors, kept_ids
        vector_write_started = True
        written = await vector_svc.upsert(vector_chunks, vectors)

        # 写入向量后再次校验：若在 upsert 窗口内资料被归档或切块正文被替换，立即补偿清理。
        await db.rollback()
        post_rows = await db.execute(
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.text,
                KnowledgeChunk.embedding_status,
                KnowledgeSource.id,
                KnowledgeSource.status,
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(KnowledgeChunk.id.in_(chunk_ids))
        )
        post_state = {
            row[0]: (row[1], row[2], row[3], row[4])
            for row in post_rows.fetchall()
        }
        final_done_pairs = []
        post_stale_pairs = []
        for chunk in vector_chunks:
            state = post_state.get(chunk.chunk_id)
            if state is None:
                post_stale_pairs.append((chunk.chunk_id, chunk.text, chunk.document_id))
                continue
            cur_text, _cur_status, cur_source_id, cur_source_status = state
            if cur_source_status != "active" or cur_source_id != chunk.source_id:
                post_stale_pairs.append((chunk.chunk_id, chunk.text, chunk.document_id))
                continue
            if cur_text != chunk.text:
                post_stale_pairs.append((chunk.chunk_id, chunk.text, chunk.document_id))
                continue
            final_done_pairs.append((chunk.chunk_id, chunk.text, chunk.document_id))

        if post_stale_pairs:
            try:
                await _cleanup_written_vectors(db, vector_svc, post_stale_pairs, write_token)
            except Exception:
                logger.warning("[EMBED-WORKER] failed to cleanup post-upsert stale vectors")

        updated_done = 0
        if final_done_pairs:
            # 必须把切块身份（id, text, document_id）、来源 active 与当前状态限制
            # 放到同一条 SQL 中原子提交。
            rejected_pairs = []
            for pair in final_done_pairs:
                updated = await chunk_repo.update_embedding_status_conditional(
                    [pair], "done", expected_status="processing",
                )
                updated_done += updated
                if not updated:
                    rejected_pairs.append(pair)
            await db.commit()
            if rejected_pairs:
                try:
                    await _cleanup_written_vectors(db, vector_svc, rejected_pairs, write_token)
                except Exception:
                    logger.warning("[EMBED-WORKER] failed to cleanup stale vectors after status race")
        logger.info("[EMBED-WORKER] processed=%d written=%d", updated_done, written if updated_done else 0)
        return updated_done
    except Exception as e:
        logger.exception("[EMBED-WORKER] batch failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            logger.exception("[EMBED-WORKER] rollback failed")
        # 只处理仍与旧正文一致且尚未被新 worker 完成的 chunk；复用 ID 的新切块不能被旧 worker 误删/误标。
        stale_pairs = []
        try:
            current_rows = await db.execute(
                select(
                    KnowledgeChunk.id,
                    KnowledgeChunk.text,
                    KnowledgeChunk.embedding_status,
                ).where(
                    KnowledgeChunk.id.in_(chunk_ids)
                )
            )
            current_info = {row[0]: (row[1], row[2]) for row in current_rows.fetchall()}
            for chunk in vector_chunks:
                info = current_info.get(chunk.chunk_id)
                if info is not None and info[0] == chunk.text and info[1] != "done":
                    stale_pairs.append((chunk.chunk_id, chunk.text, chunk.document_id))
        except Exception:
            logger.exception("[EMBED-WORKER] failed to filter stale chunks")
        if vector_write_started and stale_pairs:
            try:
                await _cleanup_written_vectors(db, vector_svc, stale_pairs, write_token)
            except Exception:
                logger.exception("[EMBED-WORKER] failed to compensate vector writes")
        try:
            if stale_pairs:
                # 异常路径：带条件原子更新，绝不把已被新 worker 处理为 done 的切块改回 failed
                await chunk_repo.update_embedding_status_conditional(
                    stale_pairs, "failed", disallowed_statuses=("done",)
                )
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
