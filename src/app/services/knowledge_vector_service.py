"""KnowledgeVectorService：封装 LanceDB 向量索引操作。

P2.E.1 实现：
- upsert(chunks, vectors) 批量写入
- search(query_vec, workspace_id, top_k) 带 prefilter 权限过滤
- 备份恢复
- 索引目录 runtime/vector/lancedb/

API 契约（供 G1 RetrievalService 参考）：

    class KnowledgeVectorService:
        async def upsert(self, chunks: list[VectorChunk], vectors: list[list[float]]) -> int
        async def search(self, query_vec: list[float], workspace_id: int, top_k: int = 5) -> list[SearchResult]
        async def delete_by_source(self, source_id: int) -> int
        async def backup(self, dest: Path) -> Path
        async def restore(self, src: Path) -> bool

    @dataclass
    class VectorChunk:
        chunk_id: int
        source_id: int
        workspace_id: int
        title: str
        section: str | None
        text: str

    @dataclass
    class SearchResult:
        chunk_id: int
        source_id: int
        section: str | None
        text_snippet: str
        _distance: float
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.runtime_paths import get_runtime_root

logger = logging.getLogger(__name__)

# LanceDB 索引目录
VECTOR_DIR_NAME = "vector/lancedb"


def _get_vector_dir() -> Path:
    """获取 LanceDB 索引目录路径。"""
    return get_runtime_root() / VECTOR_DIR_NAME


@dataclass
class VectorChunk:
    """写入向量索引的 chunk 数据。"""
    chunk_id: int
    source_id: int
    workspace_id: int
    title: str
    section: str | None
    text: str
    owner_id: int | None = None
    visibility: str = "team"


@dataclass
class SearchResult:
    """向量检索结果。"""
    chunk_id: int
    source_id: int
    section: str | None
    text_snippet: str
    _distance: float


class KnowledgeVectorService:
    """LanceDB 向量索引服务。"""

    def __init__(self):
        self._db = None
        self._table = None
        self._initialized = False

    def _get_db(self):
        """懒加载 LanceDB 连接。"""
        if self._db is not None:
            return self._db

        try:
            import lancedb
        except ImportError:
            raise ImportError(
                "LanceDB 未安装。请运行: pip install lancedb"
            )

        vector_dir = self._resolve_vector_dir()
        vector_dir.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(vector_dir))
        return self._db

    async def upsert(
        self,
        chunks: list[VectorChunk],
        vectors: list[list[float]],
    ) -> int:
        """批量写入 chunk + vector 到 LanceDB。

        Args:
            chunks: VectorChunk 列表
            vectors: 对应的嵌入向量列表

        Returns:
            写入条数
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks({len(chunks)}) 和 vectors({len(vectors)}) 长度不一致")

        if not chunks:
            return 0

        db = self._get_db()
        import lancedb
        import pyarrow as pa
        import numpy as np

        # 构造 Arrow 表数据（LanceDB 需要 list of dict 而非 dict of lists）
        import pyarrow as pa

        data = [
            {
                "chunk_id": c.chunk_id,
                "source_id": c.source_id,
                "workspace_id": c.workspace_id,
                "title": c.title,
                "section": c.section or "",
                "text": c.text,
                "owner_id": c.owner_id or 0,
                "visibility": c.visibility,
                "vector": vectors[i],
            }
            for i, c in enumerate(chunks)
        ]

        table_name = "knowledge_chunks"

        try:
            table = db.open_table(table_name)
            # 删除已存在的同 chunk_id 记录后追加
            chunk_ids = [c.chunk_id for c in chunks]
            # LanceDB delete 使用 SQL 过滤表达式
            ids_str = ",".join(str(cid) for cid in chunk_ids)
            try:
                table.delete(f"chunk_id IN ({ids_str})")
            except Exception:
                # 如果表为空或无匹配，忽略
                pass
            # 追加新数据
            table.add(data)
            self._table = table
        except (ValueError, FileNotFoundError, KeyError):
            # 表不存在，创建新表
            table = db.create_table(table_name, data, mode="create")
            self._table = table

        self._initialized = True
        logger.info(f"[VECTOR] upsert {len(chunks)} chunks to LanceDB")
        return len(chunks)

    async def search(
        self,
        query_vec: list[float],
        workspace_id: int | None = None,
        top_k: int = 5,
        user_id: int | None = None,
        scope: str = "workspace",
    ) -> list[SearchResult]:
        """向量检索，带 workspace/personal prefilter 权限过滤。

        Args:
            query_vec: 查询向量
            workspace_id: 限制工作空间范围
            top_k: 返回条数
            user_id: P5.A.1 personal scope 时按 owner_id 过滤
            scope: "workspace"（默认，按 workspace_id 过滤）或 "personal"（按 owner_id 过滤）

        Returns:
            SearchResult 列表
        """
        db = self._get_db()
        table_name = "knowledge_chunks"

        try:
            table = db.open_table(table_name)
        except Exception:
            # 表不存在，返回空结果
            logger.debug(f"[VECTOR] 表 {table_name} 不存在，返回空结果")
            return []

        import numpy as np

        query = np.array(query_vec)

        # P5.A.1: 根据 scope 构建 prefilter 条件
        if scope == "personal" and user_id is not None:
            where_clause = f"owner_id = {int(user_id)} AND visibility = 'private'"
        elif workspace_id is not None:
            if user_id is not None:
                uid = int(user_id)
                wid = int(workspace_id)
                where_clause = (
                    f"workspace_id = {wid} AND "
                    f"(visibility = 'team' OR (visibility = 'private' AND owner_id = {uid}))"
                )
            else:
                where_clause = f"workspace_id = {int(workspace_id)} AND visibility = 'team'"
        else:
            # 无过滤条件，返回空（安全默认）
            logger.warning("[VECTOR] search 缺少 workspace_id 或 user_id，返回空结果")
            return []

        # LanceDB search with prefilter
        try:
            results = (
                table.search(query)
                .where(where_clause, prefilter=True)
                .limit(top_k)
                .to_list()
            )
        except Exception as e:
            logger.error(f"[VECTOR] search error: {e}")
            return []

        search_results: list[SearchResult] = []
        for row in results:
            # 截断 text 作为 snippet
            text = row.get("text", "")
            snippet = text[:200] + "..." if len(text) > 200 else text
            search_results.append(SearchResult(
                chunk_id=int(row.get("chunk_id", 0)),
                source_id=int(row.get("source_id", 0)),
                section=row.get("section") or None,
                text_snippet=snippet,
                _distance=float(row.get("_distance", 0.0)),
            ))

        return search_results

    async def delete_by_source(self, source_id: int) -> int:
        """删除某个 source 的所有向量记录。

        Args:
            source_id: KnowledgeSource ID

        Returns:
            删除条数（LanceDB 不返回精确删除数，返回 0 表示无错误）
        """
        db = self._get_db()
        table_name = "knowledge_chunks"

        try:
            table = db.open_table(table_name)
            table.delete(f"source_id = {int(source_id)}")
            return 0  # LanceDB delete 不返回 count
        except Exception:
            return 0

    def _resolve_vector_dir(self) -> Path:
        """获取 LanceDB 索引目录路径（允许测试覆盖）。"""
        if hasattr(self, '_vector_dir_override'):
            return self._vector_dir_override
        return _get_vector_dir()

    async def backup(self, dest: Path | None = None) -> Path:
        """备份 LanceDB 索引目录。

        Args:
            dest: 备份目标路径，默认为 runtime/vector/lancedb_backup_{timestamp}

        Returns:
            备份目录路径
        """
        vector_dir = self._resolve_vector_dir()
        if not vector_dir.exists():
            raise FileNotFoundError(f"LanceDB 索引目录不存在: {vector_dir}")

        if dest is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = get_runtime_root() / f"vector/lancedb_backup_{timestamp}"

        shutil.copytree(str(vector_dir), str(dest))
        logger.info(f"[VECTOR] 备份完成: {dest}")
        return dest

    async def restore(self, src: Path) -> bool:
        """从备份恢复 LanceDB 索引。

        Args:
            src: 备份源路径

        Returns:
            是否恢复成功
        """
        if not src.exists():
            logger.error(f"[VECTOR] 备份源不存在: {src}")
            return False

        vector_dir = self._resolve_vector_dir()

        # 先删除当前索引
        if vector_dir.exists():
            shutil.rmtree(str(vector_dir))

        # 复制备份
        shutil.copytree(str(src), str(vector_dir))

        # 重置连接
        self._db = None
        self._table = None
        self._initialized = False

        logger.info(f"[VECTOR] 恢复完成: {src} → {vector_dir}")
        return True

    @property
    def is_available(self) -> bool:
        """LanceDB 是否可用。"""
        try:
            import lancedb
            return True
        except ImportError:
            return False


# 全局单例
_vector_service: KnowledgeVectorService | None = None


def get_knowledge_vector_service() -> KnowledgeVectorService:
    """获取全局 KnowledgeVectorService 单例。"""
    global _vector_service
    if _vector_service is None:
        _vector_service = KnowledgeVectorService()
    return _vector_service


def reset_knowledge_vector_service() -> None:
    """重置全局单例（测试用）。"""
    global _vector_service
    _vector_service = None
