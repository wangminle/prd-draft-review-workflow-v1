"""知识库文档与切块数据查询与写入层。"""

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDocument, KnowledgeChunk, VALID_EMBEDDING_STATUSES
from app.models.workspace import KnowledgeSource


class KnowledgeDocumentRepository:
    """KnowledgeDocument 数据访问层。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_id(self, id: int) -> KnowledgeDocument | None:
        result = await self._db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_source_id(self, source_id: int) -> KnowledgeDocument | None:
        result = await self._db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.source_id == source_id)
        )
        return result.scalar_one_or_none()

    async def list_by_source_ids(self, source_ids: list[int]) -> list[KnowledgeDocument]:
        if not source_ids:
            return []
        result = await self._db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.source_id.in_(source_ids))
        )
        return list(result.scalars().all())

    async def create(
        self,
        source_id: int,
        filename: str | None = None,
        content_hash: str | None = None,
        version: int = 1,
        metadata_json: str | None = None,
    ) -> KnowledgeDocument:
        doc = KnowledgeDocument(
            source_id=source_id,
            filename=filename,
            content_hash=content_hash,
            version=version,
            metadata_json=metadata_json,
        )
        self._db.add(doc)
        await self._db.flush()
        await self._db.refresh(doc)
        return doc

    async def update_version(
        self, id: int, content_hash: str | None = None, metadata_json: str | None = None
    ) -> KnowledgeDocument | None:
        doc = await self.get_by_id(id)
        if doc is None:
            return None
        doc.version += 1
        if content_hash is not None:
            doc.content_hash = content_hash
        if metadata_json is not None:
            doc.metadata_json = metadata_json
        await self._db.flush()
        return doc

    async def delete_by_source_id(self, source_id: int) -> int:
        """删除 source_id 对应的所有文档（含 chunks cascade），返回删除文档数。"""
        result = await self._db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.source_id == source_id)
        )
        docs = list(result.scalars().all())
        count = len(docs)
        for doc in docs:
            await self._db.delete(doc)
        await self._db.flush()
        return count


class KnowledgeChunkRepository:
    """KnowledgeChunk 数据访问层。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_id(self, id: int) -> KnowledgeChunk | None:
        result = await self._db.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.id == id)
        )
        return result.scalar_one_or_none()

    async def list_by_document(self, document_id: int) -> list[KnowledgeChunk]:
        result = await self._db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_no)
        )
        return list(result.scalars().all())

    async def list_by_document_ids(self, document_ids: list[int]) -> list[KnowledgeChunk]:
        """批量获取多个文档的 chunks，按 document_id 和 chunk_no 排序。"""
        if not document_ids:
            return []
        result = await self._db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id.in_(document_ids))
            .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_no)
        )
        return list(result.scalars().all())

    async def list_pending_embedding(self, limit: int = 100) -> list[KnowledgeChunk]:
        """获取待嵌入的 chunks，供后台 embedding 任务消费。"""
        result = await self._db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.embedding_status == "pending")
            .order_by(KnowledgeChunk.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_document(self, document_id: int) -> int:
        result = await self._db.execute(
            select(func.count()).select_from(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document_id
            )
        )
        return result.scalar_one()

    async def create_batch(
        self,
        document_id: int,
        chunks_data: list[dict],
    ) -> list[KnowledgeChunk]:
        """批量创建 chunks。chunks_data 为 dict 列表，每个含 chunk_no/text/section/source_ref/metadata_json/visibility。"""
        chunks: list[KnowledgeChunk] = []
        for cd in chunks_data:
            chunk = KnowledgeChunk(
                document_id=document_id,
                chunk_no=cd["chunk_no"],
                text=cd["text"],
                section=cd.get("section"),
                source_ref=cd.get("source_ref"),
                visibility=cd.get("visibility", "team"),
                embedding_status="pending",
                metadata_json=cd.get("metadata_json"),
            )
            self._db.add(chunk)
            chunks.append(chunk)
        await self._db.flush()
        return chunks

    async def update_embedding_status(
        self,
        chunk_ids: list[int],
        status: str,
    ) -> int:
        """批量更新 embedding 状态，返回更新条数。"""
        if status not in VALID_EMBEDDING_STATUSES:
            raise ValueError(f"Invalid embedding_status: {status}, expected {VALID_EMBEDDING_STATUSES}")
        if not chunk_ids:
            return 0
        result = await self._db.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.id.in_(chunk_ids))
            .values(embedding_status=status)
        )
        await self._db.flush()
        return result.rowcount

    async def update_embedding_status_conditional(
        self,
        updates: list[tuple[int, str]],
        new_status: str,
        expected_status: str | None = None,
        disallowed_statuses: tuple[str, ...] | None = None,
    ) -> int:
        """带正文身份与状态条件约束的批量状态更新，防止并发覆盖新切块或破坏已完成状态（BUG-214）。"""
        if new_status not in VALID_EMBEDDING_STATUSES:
            raise ValueError(f"Invalid embedding_status: {new_status}, expected {VALID_EMBEDDING_STATUSES}")
        if not updates:
            return 0
        total_updated = 0
        active_doc_ids = select(KnowledgeDocument.id).join(
            KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id
        ).where(KnowledgeSource.status == "active")
        for entry in updates:
            chunk_id, text = entry[0], entry[1]
            conditions = [
                KnowledgeChunk.id == chunk_id,
                KnowledgeChunk.text == text,
            ]
            if len(entry) >= 3:
                # 身份条件：重入库后 document_id 变化，旧 worker 不能更新新切块；
                # 同时要求来源仍 active，与状态更新在同一条 SQL 中原子判断。
                conditions.append(KnowledgeChunk.document_id == entry[2])
                conditions.append(KnowledgeChunk.document_id.in_(active_doc_ids))
            if expected_status is not None:
                conditions.append(KnowledgeChunk.embedding_status == expected_status)
            if disallowed_statuses:
                conditions.append(KnowledgeChunk.embedding_status.notin_(disallowed_statuses))
            res = await self._db.execute(
                update(KnowledgeChunk)
                .where(*conditions)
                .values(embedding_status=new_status)
            )
            total_updated += res.rowcount
        await self._db.flush()
        return total_updated

    async def delete_by_document(self, document_id: int) -> int:
        """删除文档下所有 chunks，返回删除条数。"""
        result = await self._db.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
        )
        chunks = list(result.scalars().all())
        count = len(chunks)
        for chunk in chunks:
            await self._db.delete(chunk)
        await self._db.flush()
        return count
