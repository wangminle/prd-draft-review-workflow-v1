"""Embedding 服务：封装 OpenAI text-embedding-3-small API。

功能：
- 批处理（最大 100 chunks/批）
- 指数退避重试（最多 3 次）
- 模型名和 API key 从环境变量/配置注入，不硬编码
- 启动预热（连接 warmup）缓解冷启动 P99 延迟
- 查询缓存（相同 query 不重复调用 API）
- 为 BGE-M3 预留接口
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1536
DEFAULT_MAX_BATCH_SIZE = 100
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 1.0  # 秒


class EmbeddingService:
    """OpenAI Embedding API 封装。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._api_base = (api_base or os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")).rstrip("/")
        self._model = model or os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        self._dimensions = dimensions
        self._max_batch_size = max_batch_size
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._query_cache: dict[str, list[float]] = {}
        self._warmed_up = False

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def warmup(self) -> bool:
        """启动时预热 embedding API 连接，缓解冷启动 P99 延迟。

        Returns:
            是否预热成功
        """
        if self._warmed_up:
            return True

        if not self._api_key:
            logger.warning("[EMBED] 无 API key，跳过预热")
            return False

        try:
            start = time.monotonic()
            # 发一个最小请求来建立 HTTPS 连接
            result = await self._call_api(["warmup"])
            elapsed = time.monotonic() - start
            self._warmed_up = True
            logger.info(f"[EMBED] 预热完成，耗时 {elapsed:.0f}ms")
            return True
        except Exception as e:
            logger.warning(f"[EMBED] 预热失败: {e}")
            return False

    async def embed_query(self, query: str) -> list[float]:
        """嵌入单条查询文本，使用查询缓存。

        Args:
            query: 查询文本

        Returns:
            嵌入向量
        """
        # 查询缓存
        cache_key = hashlib.md5(query.encode("utf-8")).hexdigest()
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        vectors = await self._call_api([query])
        if vectors:
            self._query_cache[cache_key] = vectors[0]
            # 限制缓存大小
            if len(self._query_cache) > 1000:
                # 移除最早的 200 条
                keys = list(self._query_cache.keys())
                for k in keys[:200]:
                    del self._query_cache[k]
            return vectors[0]

        raise RuntimeError(f"Embedding query failed: {query[:50]}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文本，自动按 max_batch_size 分批。

        Args:
            texts: 文本列表

        Returns:
            嵌入向量列表（顺序与输入一致）
        """
        if not texts:
            return []

        all_vectors: list[list[float]] = []

        for i in range(0, len(texts), self._max_batch_size):
            batch = texts[i : i + self._max_batch_size]
            batch_vectors = await self._call_api(batch)
            all_vectors.extend(batch_vectors)

        return all_vectors

    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """调用 Embedding API，含指数退避重试。

        Args:
            texts: 文本列表

        Returns:
            嵌入向量列表
        """
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY 未配置")

        url = f"{self._api_base}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "input": texts,
        }
        # 仅当模型支持 dimensions 参数时添加
        if self._dimensions and "text-embedding-3" in self._model:
            payload["dimensions"] = self._dimensions

        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    # 按 index 排序确保顺序
                    embeddings = sorted(data["data"], key=lambda x: x["index"])
                    return [item["embedding"] for item in embeddings]

                if response.status_code == 429:
                    # Rate limit，等待后重试
                    retry_after = float(response.headers.get("retry-after", "2"))
                    delay = min(retry_after, 10.0)
                    logger.warning(f"[EMBED] Rate limited, 等待 {delay}s 后重试 (attempt {attempt + 1})")
                    await asyncio.sleep(delay)
                    continue

                # 其他错误
                last_error = RuntimeError(
                    f"Embedding API error: status={response.status_code}, body={response.text[:200]}"
                )
                logger.warning(f"[EMBED] API 错误 (attempt {attempt + 1}): {last_error}")

            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                last_error = e
                logger.warning(f"[EMBED] 连接错误 (attempt {attempt + 1}): {e}")

            # 指数退避
            if attempt < self._max_retries - 1:
                delay = self._retry_base_delay * (2 ** attempt)
                logger.info(f"[EMBED] {delay:.1f}s 后重试...")
                await asyncio.sleep(delay)

        raise RuntimeError(f"Embedding API 调用失败（重试 {self._max_retries} 次）: {last_error}")


# 全局单例
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """获取全局 EmbeddingService 单例。"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def reset_embedding_service() -> None:
    """重置全局单例（测试用）。"""
    global _embedding_service
    _embedding_service = None
