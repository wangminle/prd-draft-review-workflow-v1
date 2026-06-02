"""UserRepository — 用户账户持久化，覆盖 admin 用户管理和 auth 注册/改密。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """用户账户的结构化持久化实现。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_all(self) -> list[User]:
        result = await self._db.execute(select(User).order_by(User.id))
        return list(result.scalars().all())

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self._db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self._db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def create(
        self, *, username: str, password_hash: str, role: str = "user"
    ) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            role=role,
        )
        self._db.add(user)
        await self._db.flush()
        await self._db.refresh(user)
        return user

    async def update(
        self,
        user_id: int,
        *,
        role: str | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
    ) -> User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        if password_hash is not None:
            user.password_hash = password_hash
        await self._db.flush()
        return user

    async def update_password(self, user_id: int, password_hash: str) -> User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        user.password_hash = password_hash
        await self._db.flush()
        return user

    async def update_last_active(self, user_id: int) -> None:
        user = await self.get_by_id(user_id)
        if user is not None:
            from app.utils import now_cn

            user.last_active_at = now_cn()
            await self._db.flush()

    async def delete(self, user_id: int) -> bool:
        user = await self.get_by_id(user_id)
        if user is None:
            return False
        await self._db.delete(user)
        await self._db.flush()
        return True
