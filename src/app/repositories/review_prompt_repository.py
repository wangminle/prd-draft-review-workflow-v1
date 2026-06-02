"""ReviewPromptRepository — 评审风格 Prompt 的结构化持久化。

职责边界：
- 结构化数据查询和写入（ReviewPrompt）
- 不负责文件系统访问、日志落盘、HTTPException
- 事务边界由 router/service 控制，方法内只 flush 不 commit
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import ReviewPrompt

logger = logging.getLogger(__name__)


@dataclass
class ReviewPromptCreateData:
    name: str
    content: str
    description: str | None = None


@dataclass
class ReviewPromptPatch:
    content: str | None = None
    description: str | None = None
    is_active: bool | None = None


class ReviewPromptRepository:
    """评审风格 Prompt 的结构化持久化层。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_prompts(self) -> list[ReviewPrompt]:
        result = await self._db.execute(
            select(ReviewPrompt).order_by(ReviewPrompt.created_at)
        )
        return list(result.scalars().all())

    async def get_active_prompt(self, name: str) -> ReviewPrompt | None:
        result = await self._db.execute(
            select(ReviewPrompt).where(ReviewPrompt.name == name, ReviewPrompt.is_active == True)
        )
        return result.scalar_one_or_none()

    async def create_prompt(self, data: ReviewPromptCreateData) -> ReviewPrompt:
        p = ReviewPrompt(
            name=data.name,
            description=data.description,
            content=data.content,
            is_active=True,
        )
        self._db.add(p)
        await self._db.flush()
        await self._db.refresh(p)
        return p

    async def update_prompt(self, prompt_id: int, patch: ReviewPromptPatch) -> ReviewPrompt | None:
        result = await self._db.execute(
            select(ReviewPrompt).where(ReviewPrompt.id == prompt_id)
        )
        p = result.scalar_one_or_none()
        if p is None:
            return None
        if patch.content is not None:
            p.content = patch.content
        if patch.description is not None:
            p.description = patch.description
        if patch.is_active is not None:
            p.is_active = patch.is_active
        await self._db.flush()
        return p