"""SkillConfigRepository — Skill 配置管理。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import SkillConfig
from app.database import DEFAULT_SKILL_CONFIGS


class SkillConfigRepository:
    """Skill 配置的结构化持久化实现。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_all(self, include_inactive: bool = False) -> list[SkillConfig]:
        query = select(SkillConfig).order_by(SkillConfig.display_order, SkillConfig.skill_id)
        if not include_inactive:
            query = query.where(SkillConfig.status == "active")
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def toggle_status(self, skill_id: str, status: str) -> SkillConfig | None:
        """P4.Pre.6: 启用/禁用技能。status 只允许 active/inactive。"""
        if status not in ("active", "inactive"):
            raise ValueError(f"Invalid status: {status}")
        skill = await self.get_by_skill_id(skill_id)
        if skill is None:
            return None
        skill.status = status
        await self._db.flush()
        await self._db.refresh(skill)
        return skill

    async def get_by_skill_id(self, skill_id: str) -> SkillConfig | None:
        result = await self._db.execute(
            select(SkillConfig).where(SkillConfig.skill_id == skill_id)
        )
        return result.scalar_one_or_none()

    async def ensure_defaults(self) -> None:
        result = await self._db.execute(select(SkillConfig))
        existing = {skill.skill_id: skill for skill in result.scalars().all()}

        changed = False
        for item in DEFAULT_SKILL_CONFIGS:
            skill = existing.get(item["skill_id"])
            if skill is None:
                self._db.add(SkillConfig(**item, is_builtin=True))
                changed = True
            else:
                skill.name = item["name"]
                skill.description = item["description"]
                skill.local_path = item["local_path"]
                skill.display_order = item["display_order"]
                skill.is_builtin = True
                changed = True

        if changed:
            await self._db.flush()

    async def update(
        self, skill_id: str, *, update_url: str | None, updated_at: datetime
    ) -> SkillConfig | None:
        skill = await self.get_by_skill_id(skill_id)
        if skill is None:
            return None
        skill.update_url = update_url
        skill.updated_at = updated_at
        await self._db.flush()
        await self._db.refresh(skill)
        return skill
