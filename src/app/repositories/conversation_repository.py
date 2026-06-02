"""ConversationRepository — 聊天会话、消息、消息搜索。

职责边界：
- 会话创建、查询、列表、删除
- 用户消息和助手消息写入
- FTS5 检索 SQL
- 所有权校验通过 user_id 参数下沉
- 不负责拼接 LLM prompt
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Conversation, Message
from app.utils import now_cn


@dataclass
class PaginatedResult:
    items: list
    total: int
    page: int
    page_size: int


@dataclass
class SearchHit:
    message_id: int
    conversation_id: int
    content: str
    created_at: datetime | None
    role: str
    conversation_title: str | None


class ConversationRepository:
    """聊天会话和消息的结构化持久化实现。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create_conversation(
        self, *, user_id: int, title: str | None, model_id: str, prompt_template: str | None
    ) -> Conversation:
        conv = Conversation(
            user_id=user_id,
            title=title,
            model_id=model_id,
            prompt_template=prompt_template,
        )
        self._db.add(conv)
        await self._db.flush()
        await self._db.refresh(conv)
        return conv

    async def get_conversation(self, conversation_id: int, *, user_id: int) -> Conversation | None:
        result = await self._db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_conversations(self, *, user_id: int, page: int = 1, page_size: int = 20) -> PaginatedResult:
        total_result = await self._db.execute(
            select(func.count()).where(Conversation.user_id == user_id)
        )
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        result = await self._db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = result.scalars().all()
        return PaginatedResult(items=items, total=total, page=page, page_size=page_size)

    async def append_message(
        self, *, conversation_id: int, role: str, content: str, token_count: int | None = None
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            token_count=token_count,
        )
        self._db.add(msg)
        await self._db.flush()
        await self._db.refresh(msg)
        return msg

    async def list_messages(self, conversation_id: int, *, user_id: int) -> list[Message]:
        # Verify ownership first
        conv = await self.get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            return []

        result = await self._db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    async def touch_updated_at(self, conversation_id: int) -> None:
        conv = await self._db.get(Conversation, conversation_id)
        if conv is not None:
            conv.updated_at = now_cn()

    async def delete_conversation(self, conversation_id: int, *, user_id: int) -> None:
        conv = await self.get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            return
        await self._db.delete(conv)

    async def search_messages(self, *, user_id: int, query: str, limit: int = 50) -> list[SearchHit]:
        fts_result = await self._db.execute(
            sa_text(
                "SELECT m.id, m.conversation_id, m.content, m.created_at, m.role, c.title "
                "FROM messages_fts fts "
                "JOIN messages m ON m.id = fts.rowid "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE messages_fts MATCH :query "
                "AND c.user_id = :user_id "
                "ORDER BY rank "
                "LIMIT :limit"
            ),
            {"query": query, "user_id": user_id, "limit": limit},
        )
        rows = fts_result.fetchall()
        return [
            SearchHit(
                message_id=row[0],
                conversation_id=row[1],
                content=row[2],
                created_at=row[3],
                role=row[4],
                conversation_title=row[5],
            )
            for row in rows
        ]