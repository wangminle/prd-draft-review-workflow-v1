"""PiAgentConfigRepository — Pi Agent 配置 CRUD（单行记录）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import PiAgentConfig

_UNSET = object()


class PiAgentConfigRepository:
    """Pi Agent 配置的结构化持久化实现。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get(self) -> PiAgentConfig | None:
        """获取唯一的 Pi Agent 配置行。"""
        result = await self._db.execute(select(PiAgentConfig))
        return result.scalar_one_or_none()

    async def get_or_create(self) -> PiAgentConfig:
        """获取配置行，不存在则创建默认配置（防并发重复）。

        Uses ORM add + IntegrityError handling so that concurrent
        first-time creation is safe: only one INSERT succeeds, the
        others fall back to SELECT.
        """
        config = await self.get()
        if config is None:
            config = PiAgentConfig(singleton_key="default")
            self._db.add(config)
            try:
                await self._db.flush()
            except IntegrityError:
                # Another session created the row concurrently —
                # roll back our failed insert and re-read.
                await self._db.rollback()
                config = await self.get()
                if config is None:
                    raise
        return config

    async def update(
        self,
        *,
        # LLM
        llm_provider: str | None = None,
        llm_api_base: str | None = None,
        llm_model: str | None = None,
        llm_max_tokens: int | None = None,
        llm_temperature: float | None = None,
        # Search
        search_enabled: bool | None = None,
        search_provider: str | None = None,
        search_api_base: str | None = _UNSET,
        search_max_results: int | None = None,
        # Vision
        vision_enabled: bool | None = None,
        vision_provider: str | None = None,
        vision_api_base: str | None = _UNSET,
        vision_model: str | None = _UNSET,
        # Extension
        extension_path: str | None = _UNSET,
        extension_max_tool_calls: int | None = None,
        extension_blocked_tools: str | None = None,
        # Skills
        skills_install_dir: str | None = None,
        skills_registry_url: str | None = _UNSET,
        skills_installed_list: str | None = _UNSET,
        # General
        system_prompt: str | None = _UNSET,
        enabled: bool | None = None,
    ) -> PiAgentConfig:
        """更新 Pi Agent 配置字段。

        Nullable fields use ``_UNSET`` sentinel so callers can pass
        ``None`` explicitly to clear them (set to NULL in DB).
        """
        config = await self.get_or_create()

        if llm_provider is not None:
            config.llm_provider = llm_provider
        if llm_api_base is not None:
            config.llm_api_base = llm_api_base
        if llm_model is not None:
            config.llm_model = llm_model
        if llm_max_tokens is not None:
            config.llm_max_tokens = llm_max_tokens
        if llm_temperature is not None:
            config.llm_temperature = llm_temperature

        if search_enabled is not None:
            config.search_enabled = search_enabled
        if search_provider is not None:
            config.search_provider = search_provider
        if search_api_base is not _UNSET:
            config.search_api_base = search_api_base
        if search_max_results is not None:
            config.search_max_results = search_max_results

        if vision_enabled is not None:
            config.vision_enabled = vision_enabled
        if vision_provider is not None:
            config.vision_provider = vision_provider
        if vision_api_base is not _UNSET:
            config.vision_api_base = vision_api_base
        if vision_model is not _UNSET:
            config.vision_model = vision_model

        if extension_path is not _UNSET:
            config.extension_path = extension_path
        if extension_max_tool_calls is not None:
            config.extension_max_tool_calls = extension_max_tool_calls
        if extension_blocked_tools is not None:
            config.extension_blocked_tools = extension_blocked_tools

        if skills_install_dir is not None:
            config.skills_install_dir = skills_install_dir
        if skills_registry_url is not _UNSET:
            config.skills_registry_url = skills_registry_url
        if skills_installed_list is not _UNSET:
            config.skills_installed_list = skills_installed_list

        if system_prompt is not _UNSET:
            config.system_prompt = system_prompt
        if enabled is not None:
            config.enabled = enabled

        await self._db.flush()
        return config

    async def update_llm_api_key(self, encrypted_api_key: str) -> PiAgentConfig:
        """更新 LLM API Key（加密存储）。"""
        config = await self.get_or_create()
        config.llm_encrypted_api_key = encrypted_api_key
        config.last_test_status = "unknown"
        config.last_test_time = None
        config.last_test_latency_ms = None
        await self._db.flush()
        return config

    async def update_search_api_key(self, encrypted_api_key: str | None) -> PiAgentConfig:
        """更新 Search Tool API Key。"""
        config = await self.get_or_create()
        config.search_encrypted_api_key = encrypted_api_key
        await self._db.flush()
        return config

    async def update_vision_api_key(self, encrypted_api_key: str | None) -> PiAgentConfig:
        """更新 Vision API Key。"""
        config = await self.get_or_create()
        config.vision_encrypted_api_key = encrypted_api_key
        await self._db.flush()
        return config

    async def update_test_status(
        self,
        *,
        status: str,
        test_time: datetime,
        latency_ms: int | float | None = None,
    ) -> PiAgentConfig:
        """更新连接测试结果。"""
        config = await self.get_or_create()
        config.last_test_status = status
        config.last_test_time = test_time
        config.last_test_latency_ms = int(latency_ms) if latency_ms is not None else None
        await self._db.flush()
        return config
