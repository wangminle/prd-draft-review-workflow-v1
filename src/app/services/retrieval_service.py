"""检索服务：消费 KnowledgeVectorService.search()，附加 confidence 字段，含权限过滤和降级回退。

P2.B.1 RetrievalService:
- retrieve(query, workspace_id, filters, top_k) → 调用 EmbeddingService.embed(query) →
  KnowledgeVectorService.search() → 附加 confidence → 返回

P2.E.2 FTS5 降级回退:
- LanceDB 不可用时自动回退到 FTS5

P2.E.3 拒答策略:
- dist[0] 绝对阈值：LanceDB 1.0（可配置）
- gap = results[1]._distance - results[0]._distance < 阈值（默认 0.065）时标记低置信
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.knowledge_vector_service import (
    KnowledgeVectorService,
    SearchResult,
    VectorChunk,
    get_knowledge_vector_service,
)
from app.services.embedding_service import EmbeddingService, get_embedding_service

logger = logging.getLogger(__name__)

# 默认拒答阈值（POC-C 校准值）
DEFAULT_DIST_THRESHOLD = 1.0       # dist[0] 绝对阈值（LanceDB L2 距离）
DEFAULT_GAP_THRESHOLD = 0.065      # top-1/top-2 gap 低置信阈值


@dataclass
class RetrievalResult:
    """检索结果条目。"""
    chunk_id: int
    source_id: int
    section: str | None
    text_snippet: str
    _distance: float
    confidence: str = "high"  # high / medium / low
    rejected: bool = False


@dataclass
class RetrievalResponse:
    """检索 API 响应。"""
    results: list[RetrievalResult]
    total: int
    latency_ms: float
    fallback_reason: str | None = None  # 降级原因
    query: str = ""


class RetrievalService:
    """检索编排服务。"""

    def __init__(
        self,
        vector_service: KnowledgeVectorService | None = None,
        embedding_service: EmbeddingService | None = None,
        dist_threshold: float = DEFAULT_DIST_THRESHOLD,
        gap_threshold: float = DEFAULT_GAP_THRESHOLD,
        db_session=None,
    ):
        self._vector_service = vector_service or get_knowledge_vector_service()
        self._embedding_service = embedding_service or get_embedding_service()
        self._dist_threshold = dist_threshold
        self._gap_threshold = gap_threshold
        self._db_session = db_session  # 可注入 db session（测试用）

    async def retrieve(
        self,
        query: str,
        workspace_id: int | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int = 5,
        user_id: int | None = None,
        scope: str = "workspace",
    ) -> RetrievalResponse:
        """执行检索：嵌入查询 → 向量检索 → 附加 confidence → 降级判断。

        Args:
            query: 查询文本
            workspace_id: 限制工作空间范围
            filters: 附加过滤条件（预留）
            top_k: 返回条数
            user_id: P5.A.1 personal scope 时按 owner_id 过滤
            scope: "workspace"（默认，按 workspace_id 过滤）或 "personal"（按 owner_id 过滤）

        Returns:
            RetrievalResponse
        """
        start_time = time.monotonic()
        fallback_reason = None

        # Step 1: LanceDB 不可用时直接降级，避免无意义 embedding API 调用
        if not self._vector_service.is_available:
            logger.warning("[RETRIEVE] LanceDB 不可用，降级到 FTS5")
            return await self._fallback_fts(
                query, workspace_id, top_k,
                fallback_reason="lancedb_unavailable",
                start_time=start_time,
                user_id=user_id,
                scope=scope,
            )

        # Step 2: 嵌入查询
        try:
            query_vec = await self._embedding_service.embed_query(query)
        except Exception as e:
            logger.error(f"[RETRIEVE] embedding 失败: {e}")
            # embedding 失败时降级到 FTS5
            return await self._fallback_fts(
                query, workspace_id, top_k,
                fallback_reason=f"embedding_failed: {str(e)[:100]}",
                start_time=start_time,
                user_id=user_id,
                scope=scope,
            )

        # Step 3: 向量检索（P5.A.1: 支持 personal scope）
        try:
            search_results = await self._vector_service.search(
                query_vec, workspace_id, top_k=top_k,
                user_id=user_id, scope=scope,
            )
        except (ImportError, RuntimeError, OSError) as e:
            logger.warning(f"[RETRIEVE] LanceDB 检索失败，降级到 FTS5: {e}")
            return await self._fallback_fts(
                query, workspace_id, top_k,
                fallback_reason=f"lancedb_unavailable: {str(e)[:100]}",
                start_time=start_time,
                user_id=user_id,
                scope=scope,
            )

        if not search_results:
            logger.info("[RETRIEVE] LanceDB 未返回结果，尝试降级到 FTS5")
            return await self._fallback_fts(
                query, workspace_id, top_k,
                fallback_reason="lancedb_empty_results",
                start_time=start_time,
                user_id=user_id,
                scope=scope,
            )

        # Step 4: 附加 confidence（拒答策略）
        results = self._apply_rejection_policy(search_results)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        return RetrievalResponse(
            results=results,
            total=len(results),
            latency_ms=round(elapsed_ms, 1),
            fallback_reason=fallback_reason,
            query=query,
        )

    def _apply_rejection_policy(self, search_results: list[SearchResult]) -> list[RetrievalResult]:
        """P2.E.3 拒答策略：dist[0] 绝对阈值 + gap 低置信标记。

        规则：
        1. 如果 top-1 的 dist[0] > dist_threshold → 所有结果标记 rejected（全部拒答）
        2. 如果 gap = dist[1] - dist[0] < gap_threshold → top-1 标记 low confidence
        3. 否则按距离远近标记 high/medium
        """
        if not search_results:
            return []

        # 规则 1: top-1 超出绝对阈值 → 全部拒答
        if search_results[0]._distance > self._dist_threshold:
            return [
                RetrievalResult(
                    chunk_id=sr.chunk_id,
                    source_id=sr.source_id,
                    section=sr.section,
                    text_snippet=sr.text_snippet,
                    _distance=sr._distance,
                    confidence="low",
                    rejected=True,
                )
                for sr in search_results
            ]

        results: list[RetrievalResult] = []

        for i, sr in enumerate(search_results):
            # 规则 2: gap 低置信判断（仅对 top-1 生效）
            if i == 0 and len(search_results) > 1:
                gap = search_results[1]._distance - sr._distance
                if gap < self._gap_threshold:
                    results.append(RetrievalResult(
                        chunk_id=sr.chunk_id,
                        source_id=sr.source_id,
                        section=sr.section,
                        text_snippet=sr.text_snippet,
                        _distance=sr._distance,
                        confidence="low",
                        rejected=True,
                    ))
                    continue

            # 规则 3: 按距离分级
            if sr._distance <= self._dist_threshold * 0.5:
                confidence = "high"
            else:
                confidence = "medium"

            results.append(RetrievalResult(
                chunk_id=sr.chunk_id,
                source_id=sr.source_id,
                section=sr.section,
                text_snippet=sr.text_snippet,
                _distance=sr._distance,
                confidence=confidence,
                rejected=False,
            ))

        return results

    async def _fallback_fts(
        self,
        query: str,
        workspace_id: int | None,
        top_k: int,
        fallback_reason: str,
        start_time: float,
        user_id: int | None = None,
        scope: str = "workspace",
    ) -> RetrievalResponse:
        """FTS5 降级回退检索。"""
        from app.services.knowledge_ingestion import KnowledgeIngestionService

        # personal scope：按 owner_id 做 FTS5 降级（向量未就绪时仍可检索本人资料）
        if scope == "personal" and not workspace_id:
            if user_id is None:
                elapsed_ms = (time.monotonic() - start_time) * 1000
                return RetrievalResponse(
                    results=[],
                    total=0,
                    latency_ms=round(elapsed_ms, 1),
                    fallback_reason=fallback_reason,
                    query=query,
                )
            try:
                if self._db_session is not None:
                    ingestion = KnowledgeIngestionService(self._db_session)
                    fts_results = await ingestion.search_fts_personal(
                        query, user_id=user_id, limit=top_k,
                    )
                else:
                    from app.database import async_session
                    async with async_session() as db:
                        ingestion = KnowledgeIngestionService(db)
                        fts_results = await ingestion.search_fts_personal(
                            query, user_id=user_id, limit=top_k,
                        )
                results: list[RetrievalResult] = []
                for r in fts_results:
                    results.append(RetrievalResult(
                        chunk_id=r["id"],
                        source_id=r["source_id"],
                        section=r.get("section"),
                        text_snippet=r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"],
                        _distance=0.0,
                        confidence="medium",
                        rejected=False,
                    ))
                elapsed_ms = (time.monotonic() - start_time) * 1000
                return RetrievalResponse(
                    results=results,
                    total=len(results),
                    latency_ms=round(elapsed_ms, 1),
                    fallback_reason=fallback_reason or "personal_fts",
                    query=query,
                )
            except Exception as e:
                logger.warning(f"[RETRIEVE] personal FTS fallback failed: {e}")
                elapsed_ms = (time.monotonic() - start_time) * 1000
                return RetrievalResponse(
                    results=[],
                    total=0,
                    latency_ms=round(elapsed_ms, 1),
                    fallback_reason=fallback_reason,
                    query=query,
                )

        try:
            if self._db_session is not None:
                # 使用注入的 db session（测试场景）
                ingestion = KnowledgeIngestionService(self._db_session)
                fts_results = await ingestion.search_fts(
                    query, workspace_id, limit=top_k, user_id=user_id,
                )
            else:
                # 生产环境：从全局 session 工厂获取
                from app.database import async_session
                async with async_session() as db:
                    ingestion = KnowledgeIngestionService(db)
                    fts_results = await ingestion.search_fts(
                        query, workspace_id, limit=top_k, user_id=user_id,
                    )

            results: list[RetrievalResult] = []
            for r in fts_results:
                results.append(RetrievalResult(
                    chunk_id=r["id"],
                    source_id=r["source_id"],
                    section=r.get("section"),
                    text_snippet=r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"],
                    _distance=0.0,  # FTS 无 _distance 概念
                    confidence="medium",  # FTS 降级结果默认 medium
                    rejected=False,
                ))

            elapsed_ms = (time.monotonic() - start_time) * 1000
            return RetrievalResponse(
                results=results,
                total=len(results),
                latency_ms=round(elapsed_ms, 1),
                fallback_reason=fallback_reason,
                query=query,
            )
        except Exception as e:
            logger.error(f"[RETRIEVE] FTS5 降级也失败: {e}")
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return RetrievalResponse(
                results=[],
                total=0,
                latency_ms=round(elapsed_ms, 1),
                fallback_reason=f"all_failed: {str(e)[:100]}",
                query=query,
            )
