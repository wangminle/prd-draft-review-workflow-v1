"""PromptTemplateRepository — Prompt 模板 CRUD。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import PromptTemplate


class PromptTemplateRepository:
    """Prompt 模板的结构化持久化实现。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_all(self) -> list[PromptTemplate]:
        result = await self._db.execute(
            select(PromptTemplate).order_by(PromptTemplate.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, prompt_id: int) -> PromptTemplate | None:
        result = await self._db.execute(
            select(PromptTemplate).where(PromptTemplate.id == prompt_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> PromptTemplate | None:
        result = await self._db.execute(
            select(PromptTemplate).where(PromptTemplate.name == name)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        description: str | None = None,
        system_prompt: str | None = None,
        user_prompt_template: str | None = None,
        is_builtin: bool = False,
        created_by: int | None = None,
    ) -> PromptTemplate:
        pt = PromptTemplate(
            name=name,
            description=description,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            is_builtin=is_builtin,
            created_by=created_by,
        )
        self._db.add(pt)
        await self._db.flush()
        await self._db.refresh(pt)
        return pt

    async def update(
        self,
        prompt_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        user_prompt_template: str | None = None,
    ) -> PromptTemplate | None:
        pt = await self.get_by_id(prompt_id)
        if pt is None:
            return None
        if name is not None:
            pt.name = name
        if description is not None:
            pt.description = description
        if system_prompt is not None:
            pt.system_prompt = system_prompt
        if user_prompt_template is not None:
            pt.user_prompt_template = user_prompt_template
        await self._db.flush()
        return pt

    async def delete(self, prompt_id: int) -> bool:
        pt = await self.get_by_id(prompt_id)
        if pt is None:
            return False
        await self._db.delete(pt)
        await self._db.flush()
        return True
