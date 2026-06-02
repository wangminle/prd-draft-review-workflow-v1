"""ModelConfigRepository — 模型配置 CRUD。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import ModelConfig

_UNSET = object()


class ModelConfigRepository:
    """模型配置的结构化持久化实现。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_all(self) -> list[ModelConfig]:
        result = await self._db.execute(
            select(ModelConfig)
            .where(ModelConfig.deleted_by_user == False)
            .order_by(ModelConfig.display_order, ModelConfig.name, ModelConfig.id)
        )
        return list(result.scalars().all())

    async def get_by_model_id(self, model_id: str) -> ModelConfig | None:
        result = await self._db.execute(
            select(ModelConfig).where(
                ModelConfig.model_id == model_id,
                ModelConfig.deleted_by_user == False,
            )
        )
        return result.scalar_one_or_none()

    async def get_max_display_order(self) -> int:
        result = await self._db.execute(select(func.max(ModelConfig.display_order)))
        return result.scalar_one_or_none() or -1

    async def create(self, mc: ModelConfig) -> ModelConfig:
        self._db.add(mc)
        await self._db.flush()
        await self._db.refresh(mc)
        return mc

    async def update(
        self,
        model_id: str,
        *,
        name: str | None = None,
        provider: str | None = None,
        api_base: str | None = None,
        llm_model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        enabled: bool | None = None,
        thinking_supported: bool | None = None,
        thinking_level: str | None = None,
        thinking_adapter: str | None = None,
        thinking_payload: str | None = _UNSET,
    ) -> ModelConfig | None:
        mc = await self.get_by_model_id(model_id)
        if mc is None:
            return None
        if name is not None:
            mc.name = name
        if provider is not None:
            mc.provider = provider
        if api_base is not None:
            mc.api_base = api_base
        if llm_model is not None:
            mc.llm_model = llm_model
        if max_tokens is not None:
            mc.max_tokens = max_tokens
        if temperature is not None:
            mc.temperature = temperature
        if enabled is not None:
            mc.enabled = enabled
        if thinking_supported is not None:
            mc.thinking_supported = thinking_supported
        if thinking_level is not None:
            mc.thinking_level = thinking_level
        if thinking_adapter is not None:
            mc.thinking_adapter = thinking_adapter
        if thinking_payload is not _UNSET:
            mc.thinking_payload = thinking_payload
        await self._db.flush()
        return mc

    async def update_api_key(
        self, model_id: str, encrypted_api_key: str
    ) -> ModelConfig | None:
        mc = await self.get_by_model_id(model_id)
        if mc is None:
            return None
        mc.encrypted_api_key = encrypted_api_key
        mc.last_test_status = "unknown"
        mc.last_test_time = None
        mc.last_test_latency_ms = None
        await self._db.flush()
        return mc

    async def update_test_status(
        self,
        model_id: str,
        *,
        status: str,
        test_time: datetime,
        latency_ms: int | float | None = None,
    ) -> ModelConfig | None:
        mc = await self.get_by_model_id(model_id)
        if mc is None:
            return None
        mc.last_test_status = status
        mc.last_test_time = test_time
        mc.last_test_latency_ms = int(latency_ms) if latency_ms is not None else None
        await self._db.flush()
        return mc

    async def update_display_order(self, model_ids: list[str]) -> None:
        result = await self._db.execute(
            select(ModelConfig).where(ModelConfig.deleted_by_user == False)
        )
        models = list(result.scalars().all())
        by_id = {mc.model_id: mc for mc in models}
        for index, current_id in enumerate(model_ids):
            if current_id in by_id:
                by_id[current_id].display_order = index
        await self._db.flush()

    async def delete(self, model_id: str, *, tombstone: bool = False) -> bool:
        result = await self._db.execute(
            select(ModelConfig).where(
                ModelConfig.model_id == model_id,
                ModelConfig.deleted_by_user == False,
            )
        )
        mc = result.scalar_one_or_none()
        if mc is None:
            return False
        if tombstone:
            mc.deleted_by_user = True
            mc.enabled = False
        else:
            await self._db.delete(mc)
        await self._db.flush()
        return True
