"""知识入库服务：资料上传后触发 解析→切块→FTS 索引（同步）→提交异步 embedding 任务。

职责边界：
- 接收 KnowledgeSource ID，从 KnowledgeSource.extracted_text 提取正文
- 切块（调用 chunking.py）
- 写入 KnowledgeDocument + KnowledgeChunk（同步完成）
- 创建 FTS5 索引（同步完成）
- 提交异步 embedding 任务（非阻塞，upload 端点不等待 embedding 完成即返回）
- 不负责 embedding 调用本身（由 EmbeddingService + KnowledgeVectorService 处理）
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.models.workspace import KnowledgeSource
from app.repositories.knowledge_repository import KnowledgeDocumentRepository, KnowledgeChunkRepository
from app.services.chunking import chunk_text, ChunkResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# FTS5 trigram tokenizer 最小查询长度
_FTS_TRIGRAM_MIN_LENGTH = 3

# 知识检索输出最大字符数（防止超过 LLM 上下文窗口）
_MAX_KNOWLEDGE_CONTEXT_CHARS = 8000


def _sanitize_fts5_query(query: str) -> str:
    """转义 FTS5 MATCH 查询中的特殊字符。

    FTS5 trigram tokenizer 不使用 FTS5 查询语法中的特殊字符，
    但未转义的 `"` `*` `(` `)` 等会导致语法错误。
    策略：用双引号包裹整个查询词，使其作为短语匹配。
    """
    # 移除控制字符和空字符
    query = re.sub(r"[\x00-\x1f]", "", query)
    # 去除首尾空白
    query = query.strip()
    if not query:
        return ""
    # FTS5 MATCH 对引号、括号、星号和布尔操作符等有特殊语法含义；
    # trigram fallback 只需要纯文本匹配，因此统一移除这些语法字符，避免语法错误。
    query = re.sub(r"[\"'*()\[\]{}^~:+=/\\|-]+", " ", query)
    query = re.sub(r"\b(?:AND|OR|NOT)\b", " ", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query).strip()
    return query


class KnowledgeIngestionService:
    """知识入库编排服务。"""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._doc_repo = KnowledgeDocumentRepository(db)
        self._chunk_repo = KnowledgeChunkRepository(db)

    async def ingest_source(self, source_id: int) -> KnowledgeDocument | None:
        """对 KnowledgeSource 执行完整入库流程：解析→切块→FTS 索引→标记 pending embedding。

        Args:
            source_id: KnowledgeSource ID

        Returns:
            创建的 KnowledgeDocument，如果 source 不存在或无正文则返回 None
        """
        # 1. 读取 KnowledgeSource
        result = await self._db.execute(
            select(KnowledgeSource).where(KnowledgeSource.id == source_id)
        )
        source = result.scalar_one_or_none()
        if source is None:
            logger.warning(f"[INGEST] source_id={source_id} 不存在")
            return None

        extracted_text = source.extracted_text
        if not extracted_text or not extracted_text.strip():
            logger.warning(f"[INGEST] source_id={source_id} 无正文，跳过入库")
            return None

        # 2. 删除旧文档和 chunks（重新入库场景）
        await self._doc_repo.delete_by_source_id(source_id)

        # 2b. 清除旧向量索引和 FTS5 索引条目（防止重入库后召回旧内容）
        try:
            from app.services.knowledge_vector_service import get_knowledge_vector_service
            await get_knowledge_vector_service().delete_by_source(source_id)
        except Exception as e:
            logger.warning(f"[INGEST] 清除旧向量索引失败（可忽略首次或 LanceDB 不可用）: {e}")

        await self._cleanup_fts_entries(source_id)

        # 3. 计算内容哈希
        content_hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()

        # 4. 创建 KnowledgeDocument
        doc = await self._doc_repo.create(
            source_id=source_id,
            filename=source.filename,
            content_hash=content_hash,
            version=1,
            metadata_json=json.dumps({"source_type": source.source_type}, ensure_ascii=False),
        )

        # 5. 切块
        source_ref = source.filename or source.title
        chunk_results: list[ChunkResult] = chunk_text(
            extracted_text,
            source_ref=source_ref,
        )

        if not chunk_results:
            logger.info(f"[INGEST] source_id={source_id} 切块结果为空")
            return doc

        # 6. 批量创建 chunks（继承 source 的 visibility）
        visibility = source.visibility or "team"
        chunks_data = [
            {
                "chunk_no": cr.chunk_no,
                "text": cr.text,
                "section": cr.section,
                "source_ref": cr.source_ref,
                "metadata_json": cr.metadata_json,
                "visibility": visibility,
            }
            for cr in chunk_results
        ]
        chunks = await self._chunk_repo.create_batch(doc.id, chunks_data)

        # 7. 创建 FTS5 索引（同步完成）
        await self._ensure_fts_index(source_id, doc.id, chunks)

        logger.info(
            f"[INGEST] source_id={source_id} 入库完成: doc_id={doc.id}, "
            f"chunks={len(chunks)}, content_hash={content_hash[:12]}..."
        )
        return doc

    async def _cleanup_fts_entries(self, source_id: int) -> None:
        """清除指定 source 的旧 FTS5 索引条目（防止幽灵结果）。"""
        try:
            await self._db.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                USING fts5(text, section, source_ref, chunk_id UNINDEXED, source_id UNINDEXED, workspace_id UNINDEXED, tokenize='trigram')
            """))
            await self._db.execute(text("""
                DELETE FROM knowledge_chunks_fts WHERE source_id = :source_id
            """), {"source_id": source_id})
            await self._db.flush()
        except Exception as e:
            logger.warning(f"[INGEST] 清除旧 FTS 条目失败（可忽略首次）: {e}")

    async def _ensure_fts_index(self, source_id: int, doc_id: int, chunks: list[KnowledgeChunk]) -> None:
        """为 chunks 创建 FTS5 索引条目。

        使用 content-less FTS5 模式（不指定 content= 参数），
        避免与 knowledge_chunks 表的同步问题。

        修复 N+1 查询：source_id 和 workspace_id 在循环外查询一次。
        """
        # 创建 knowledge_chunks_fts 虚拟表（content-less 模式，trigram tokenizer）
        await self._db.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
            USING fts5(text, section, source_ref, chunk_id UNINDEXED, source_id UNINDEXED, workspace_id UNINDEXED, tokenize='trigram')
        """))

        # 一次性查询 source_id 和 workspace_id（修复 N+1 查询）
        source_obj_result = await self._db.execute(
            select(KnowledgeSource.workspace_id).where(KnowledgeSource.id == source_id)
        )
        ws_row = source_obj_result.one_or_none()
        if ws_row is None:
            logger.error(f"[INGEST] source_id={source_id} 对应的 KnowledgeSource 不存在，无法索引")
            return
        workspace_id = ws_row[0]

        # 插入 FTS 索引数据
        for chunk in chunks:
            await self._db.execute(text("""
                INSERT INTO knowledge_chunks_fts(text, section, source_ref, chunk_id, source_id, workspace_id)
                VALUES (:text, :section, :source_ref, :chunk_id, :source_id, :workspace_id)
            """), {
                "text": chunk.text,
                "section": chunk.section or "",
                "source_ref": chunk.source_ref or "",
                "chunk_id": chunk.id,
                "source_id": source_id,
                "workspace_id": workspace_id,
            })
        await self._db.flush()

    async def _allowed_source_ids_for_user(
        self,
        source_ids: list[int],
        user_id: int,
    ) -> set[int]:
        """返回 user 可读的 source_id 集合（team 或本人 private）。"""
        if not source_ids:
            return set()
        result = await self._db.execute(
            select(KnowledgeSource.id).where(
                KnowledgeSource.id.in_(source_ids),
                or_(
                    KnowledgeSource.visibility == "team",
                    and_(
                        KnowledgeSource.visibility == "private",
                        KnowledgeSource.owner_id == user_id,
                    ),
                ),
            )
        )
        return {row[0] for row in result.fetchall()}

    async def search_fts(
        self,
        query: str,
        workspace_id: int,
        limit: int = 10,
        user_id: int | None = None,
    ) -> list[dict]:
        """FTS5 关键词检索（LanceDB 降级回退时使用）。

        使用 content-less FTS5 表直接搜索，workspace_id 作为 UNINDEXED 字段过滤。

        Args:
            query: 检索关键词（至少 3 个字符，trigram tokenizer 限制）
            workspace_id: 限制工作空间范围
            limit: 返回条数

        Returns:
            [{id, text, section, source_ref, rank, source_id}, ...] 列表
        """
        # trigram tokenizer 要求至少 3 个字符
        sanitized = _sanitize_fts5_query(query)
        if len(sanitized) < _FTS_TRIGRAM_MIN_LENGTH:
            logger.debug(f"[FTS] 查询 '{sanitized[:20]}' 不足 {_FTS_TRIGRAM_MIN_LENGTH} 字符，返回空")
            return []

        # 确保 FTS 表存在
        await self._db.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
            USING fts5(text, section, source_ref, chunk_id UNINDEXED, source_id UNINDEXED, workspace_id UNINDEXED, tokenize='trigram')
        """))

        # FTS5 搜索 + workspace 过滤
        result = await self._db.execute(text("""
            SELECT
                chunk_id,
                text,
                section,
                source_ref,
                rank,
                source_id
            FROM knowledge_chunks_fts
            WHERE text MATCH :query
              AND workspace_id = :workspace_id
            ORDER BY rank
            LIMIT :limit
        """), {"query": sanitized, "workspace_id": int(workspace_id), "limit": limit})

        rows = result.fetchall()
        if not rows:
            return []

        if user_id is not None:
            source_ids = list({row[5] for row in rows})
            allowed = await self._allowed_source_ids_for_user(source_ids, user_id)
            rows = [row for row in rows if row[5] in allowed]

        return [
            {
                "id": row[0],
                "text": row[1],
                "section": row[2],
                "source_ref": row[3],
                "rank": row[4],
                "source_id": row[5],
            }
            for row in rows
        ]
