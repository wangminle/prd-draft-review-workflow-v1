"""ContextItemRepository — 会话上下文项。

职责边界：
- 上下文项列表、启用/禁用、新建、删除、清空
- 所有权校验通过 user_id 参数下沉
- 文件正文抽取在 storage/service，不放进 repository
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import ContextItem, Conversation


@dataclass
class ContextItemCreateData:
    context_type: str
    title: str
    file_id: str | None = None
    url: str | None = None
    manual_text: str | None = None
    extracted_text: str | None = None
    enabled: bool = True


@dataclass
class ContextItemPatch:
    title: str | None = None
    enabled: bool | None = None


class ContextItemRepository:
    """会话上下文项的结构化持久化实现。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def _verify_conversation_owner(self, conversation_id: int, user_id: int) -> Conversation | None:
        result = await self._db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_items(self, conversation_id: int, *, user_id: int) -> list[ContextItem]:
        conv = await self._verify_conversation_owner(conversation_id, user_id)
        if conv is None:
            return []
        result = await self._db.execute(
            select(ContextItem)
            .where(ContextItem.conversation_id == conversation_id)
            .order_by(ContextItem.created_at)
        )
        return list(result.scalars().all())

    async def list_enabled_items(self, conversation_id: int, *, user_id: int) -> list[ContextItem]:
        conv = await self._verify_conversation_owner(conversation_id, user_id)
        if conv is None:
            return []
        result = await self._db.execute(
            select(ContextItem).where(
                ContextItem.conversation_id == conversation_id,
                ContextItem.enabled == True,
            ).order_by(ContextItem.created_at)
        )
        return list(result.scalars().all())

    async def create_item(
        self, conversation_id: int, *, user_id: int, data: ContextItemCreateData
    ) -> ContextItem | None:
        conv = await self._verify_conversation_owner(conversation_id, user_id)
        if conv is None:
            return None

        item = ContextItem(
            conversation_id=conversation_id,
            context_type=data.context_type,
            title=data.title,
            file_id=data.file_id,
            url=data.url,
            manual_text=data.manual_text,
            extracted_text=data.extracted_text,
            enabled=data.enabled,
        )
        self._db.add(item)
        await self._db.flush()
        await self._db.refresh(item)
        return item

    async def update_item(
        self, conversation_id: int, item_id: int, *, user_id: int, patch: ContextItemPatch
    ) -> ContextItem | None:
        conv = await self._verify_conversation_owner(conversation_id, user_id)
        if conv is None:
            return None

        result = await self._db.execute(
            select(ContextItem).where(
                ContextItem.id == item_id,
                ContextItem.conversation_id == conversation_id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return None

        if patch.title is not None:
            item.title = patch.title
        if patch.enabled is not None:
            item.enabled = patch.enabled
        await self._db.flush()
        await self._db.refresh(item)
        return item

    async def delete_item(self, conversation_id: int, item_id: int, *, user_id: int) -> bool:
        """删除上下文项。返回 True 表示成功删除，False 表示会话或 item 不存在。"""
        conv = await self._verify_conversation_owner(conversation_id, user_id)
        if conv is None:
            return False

        result = await self._db.execute(
            select(ContextItem).where(
                ContextItem.id == item_id,
                ContextItem.conversation_id == conversation_id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return False
        await self._db.delete(item)
        return True