"""Workspace 数据查询与写入层。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace, WorkspaceMember


class WorkspaceRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_id(self, id: int) -> Workspace | None:
        result = await self._db.execute(select(Workspace).where(Workspace.id == id))
        return result.scalar_one_or_none()

    async def get_default(self) -> Workspace | None:
        result = await self._db.execute(select(Workspace).where(Workspace.name == "默认空间"))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Workspace]:
        result = await self._db.execute(
            select(Workspace).where(Workspace.status == "active").order_by(Workspace.id)
        )
        return list(result.scalars().all())

    async def create(self, name: str, description: str | None = None, created_by: int | None = None) -> Workspace:
        ws = Workspace(name=name, description=description, created_by=created_by, status="active")
        self._db.add(ws)
        await self._db.flush()
        await self._db.refresh(ws)
        return ws

    async def archive(self, id: int) -> Workspace | None:
        ws = await self.get_by_id(id)
        if ws is None:
            return None
        ws.status = "archived"
        await self._db.flush()
        return ws

    async def add_member(self, workspace_id: int, user_id: int, role: str = "member") -> WorkspaceMember:
        member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role, status="active")
        self._db.add(member)
        await self._db.flush()
        await self._db.refresh(member)
        return member

    async def get_member(self, workspace_id: int, user_id: int) -> WorkspaceMember | None:
        result = await self._db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.status == "active",
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_members(self, workspace_id: int) -> list[WorkspaceMember]:
        result = await self._db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.status == "active",
            ).order_by(WorkspaceMember.id)
        )
        return list(result.scalars().all())

    async def update_member_role(self, workspace_id: int, user_id: int, role: str) -> WorkspaceMember | None:
        member = await self.get_member(workspace_id, user_id)
        if member is None:
            return None
        member.role = role
        await self._db.flush()
        return member

    async def remove_member(self, workspace_id: int, user_id: int) -> bool:
        member = await self.get_member(workspace_id, user_id)
        if member is None:
            return False
        member.status = "removed"
        await self._db.flush()
        return True

    async def get_user_workspaces(self, user_id: int) -> list[Workspace]:
        result = await self._db.execute(
            select(Workspace).join(WorkspaceMember).where(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.status == "active",
                Workspace.status == "active",
            ).order_by(Workspace.id)
        )
        return list(result.scalars().all())