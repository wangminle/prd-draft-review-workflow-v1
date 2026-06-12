"""知识库文档与切块数据查询与写入层。"""

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDocument, KnowledgeChunk, VALID_EMBEDDING_STATUSES


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
