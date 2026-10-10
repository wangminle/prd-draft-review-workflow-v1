"""UserRepository — 用户账户持久化，覆盖 admin 用户管理和 auth 注册/改密。"""

from __future__ import annotations

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class SessionVersionConflictError(Exception):
    """BUG-200：写入时的会话版本条件不匹配——改密/重置并发冲突。

    在途改密请求携带认证时刻的 auth_version 作为原子更新条件；
    若期间管理员已重置密码（版本已推进），UPDATE 命中 0 行即抛出本异常。
    """


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
        values: dict = {}
        if role is not None:
            values["role"] = role
        if is_active is not None:
            values["is_active"] = is_active
        if password_hash is not None:
            values["password_hash"] = password_hash
            # BUG-196/199：密码更新与会话版本递增合并为原子 UPDATE，
            # 避免读后写丢失并发递增（改密/重置必须撤销全部旧 JWT）
            values["auth_version"] = User.auth_version + 1
        if values:
            await self._db.execute(
                sa_update(User).where(User.id == user_id).values(**values)
            )
            await self._db.refresh(user)
        await self._db.flush()
        return user

    async def update_password(
        self,
        user_id: int,
        password_hash: str,
        *,
        expected_auth_version: int | None = None,
    ) -> User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        # BUG-196/199：原子 UPDATE，会话版本由数据库递增，杜绝并发丢失更新
        stmt = (
            sa_update(User)
            .where(User.id == user_id)
            .values(
                password_hash=password_hash,
                auth_version=User.auth_version + 1,
            )
        )
        if expected_auth_version is not None:
            # BUG-200：乐观并发——认证时刻的会话版本作为写入条件；
            # 管理员重置等已推进版本时命中 0 行，拒绝在途请求覆盖新密码
            stmt = stmt.where(User.auth_version == expected_auth_version)
        result = await self._db.execute(stmt)
        if expected_auth_version is not None and result.rowcount == 0:
            raise SessionVersionConflictError(
                f"user {user_id} auth_version mismatch: expected {expected_auth_version}"
            )
        await self._db.flush()
        await self._db.refresh(user)
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
