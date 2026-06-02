"""ReviewContextRepository — 项目级评审上下文版本的结构化持久化。

职责边界：
- 结构化数据查询和写入（ReviewContext）
- 不负责文件系统访问、日志落盘、HTTPException
- 事务边界由 router/service 控制，方法内只 flush 不 commit
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import ReviewContext

logger = logging.getLogger(__name__)


@dataclass
class ContextCreateData:
    project_id: int
    context_data: str
    change_log: str | None = None
    updated_by: int | None = None


@dataclass
class ContextPatch:
    is_active: bool | None = None
    change_log: str | None = None


class ReviewContextRepository:
    """项目级评审上下文版本的结构化持久化层。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_active_context(self, project_id: int, *, user_id: int | None = None) -> ReviewContext | None:
        result = await self._db.execute(
            select(ReviewContext)
            .where(ReviewContext.project_id == project_id, ReviewContext.is_active == True)
            .order_by(ReviewContext.version.desc())
            .limit(1)
        )
        ctx = result.scalar_one_or_none()
        if ctx is None:
            return None
        return ctx

    async def list_context_versions(self, project_id: int) -> list[ReviewContext]:
        result = await self._db.execute(
            select(ReviewContext)
            .where(ReviewContext.project_id == project_id)
            .order_by(ReviewContext.version.desc())
        )
        return list(result.scalars().all())

    async def deactivate_old_version(self, project_id: int) -> None:
        result = await self._db.execute(
            select(ReviewContext)
            .where(ReviewContext.project_id == project_id, ReviewContext.is_active == True)
        )
        for old in result.scalars().all():
            old.is_active = False
        await self._db.flush()

    async def activate_new_version(self, project_id: int, *, data: dict, change_log: str | None = None, updated_by: int | None = None) -> ReviewContext:
        await self.deactivate_old_version(project_id)
        result = await self._db.execute(
            select(ReviewContext.version)
            .where(ReviewContext.project_id == project_id)
            .order_by(ReviewContext.version.desc())
            .limit(1)
        )
        max_ver = result.scalar_one_or_none() or 0
        ctx = ReviewContext(
            project_id=project_id,
            version=max_ver + 1,
            is_active=True,
            context_data=json.dumps(data, ensure_ascii=False),
            change_log=change_log,
            updated_by=updated_by,
        )
        self._db.add(ctx)
        await self._db.flush()
        await self._db.refresh(ctx)
        return ctx