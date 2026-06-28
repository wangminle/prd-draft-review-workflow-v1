"""KnowledgeSource 数据查询与写入层。"""

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.workspace import KnowledgeSource, ProjectSourceRef, VALID_OWNER_TYPES, VALID_VISIBILITIES


class KnowledgeSourceRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_id(self, id: int) -> KnowledgeSource | None:
        result = await self._db.execute(select(KnowledgeSource).where(KnowledgeSource.id == id))
        return result.scalar_one_or_none()

    async def list_by_workspace(
        self,
        workspace_id: int,
        source_type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        owner_type: str | None = None,
        visibility: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[KnowledgeSource]:
        """列出团队资料（默认只返回 owner_type=workspace, visibility=team 的团队可见资料）。

        个人私有资料（owner_type=user, visibility=private）只能通过 list_personal_sources 访问，
        不会在此方法中返回，防止同 workspace 成员看到他人的私有资料。
        """
        # BUG-078 修复：默认只返回团队可见资料，防止私有资料泄露
        effective_owner_type = owner_type if owner_type is not None else "workspace"
        effective_visibility = visibility if visibility is not None else "team"

        query = select(KnowledgeSource).options(
            selectinload(KnowledgeSource.owner)
        ).where(
            KnowledgeSource.workspace_id == workspace_id,
            KnowledgeSource.owner_type == effective_owner_type,
            KnowledgeSource.visibility == effective_visibility,
        ).order_by(KnowledgeSource.updated_at.desc())
        if status:
            query = query.where(KnowledgeSource.status == status)
        else:
            query = query.where(KnowledgeSource.status == "active")
        if source_type:
            query = query.where(KnowledgeSource.source_type == source_type)
        if tag:
            query = query.where(KnowledgeSource.metadata_json.contains(tag))
        query = query.offset(offset).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def list_personal_sources(
        self,
        user_id: int,
        source_type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[KnowledgeSource]:
        """列出个人私有资料（owner_type=user, owner_id=user_id）。"""
        query = select(KnowledgeSource).options(
            selectinload(KnowledgeSource.owner)
        ).where(
            KnowledgeSource.owner_type == "user",
            KnowledgeSource.owner_id == user_id,
        ).order_by(KnowledgeSource.updated_at.desc())
        if status:
            query = query.where(KnowledgeSource.status == status)
        else:
            query = query.where(KnowledgeSource.status == "active")
        if source_type:
            query = query.where(KnowledgeSource.source_type == source_type)
        if tag:
            query = query.where(KnowledgeSource.metadata_json.contains(tag))
        query = query.offset(offset).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def count_by_workspace(self, workspace_id: int, status: str | None = None, owner_type: str | None = None, visibility: str | None = None) -> int:
        # BUG-078 修复：默认只统计团队可见资料
        effective_owner_type = owner_type if owner_type is not None else "workspace"
        effective_visibility = visibility if visibility is not None else "team"
        query = select(func.count()).select_from(KnowledgeSource).where(
            KnowledgeSource.workspace_id == workspace_id,
            KnowledgeSource.status == (status or "active"),
            KnowledgeSource.owner_type == effective_owner_type,
            KnowledgeSource.visibility == effective_visibility,
        )
        result = await self._db.execute(query)
        return result.scalar_one()

    async def count_personal(self, user_id: int, status: str | None = None) -> int:
        """统计个人私有资料数量。"""
        query = select(func.count()).select_from(KnowledgeSource).where(
            KnowledgeSource.owner_type == "user",
            KnowledgeSource.owner_id == user_id,
            KnowledgeSource.status == (status or "active"),
        )
        result = await self._db.execute(query)
        return result.scalar_one()

    async def create(
        self,
        source_type: str,
        title: str,
        workspace_id: int | None = None,
        owner_type: str = "workspace",
        visibility: str = "team",
        filename: str | None = None,
        file_id: str | None = None,
        content_hash: str | None = None,
        extracted_text: str | None = None,
        owner_id: int | None = None,
        metadata_json: str | None = None,
    ) -> KnowledgeSource:
        if owner_type not in VALID_OWNER_TYPES:
            raise ValueError(f"Invalid owner_type: {owner_type}, expected one of {VALID_OWNER_TYPES}")
        if visibility not in VALID_VISIBILITIES:
            raise ValueError(f"Invalid visibility: {visibility}, expected one of {VALID_VISIBILITIES}")
        source = KnowledgeSource(
            workspace_id=workspace_id,
            owner_type=owner_type,
            visibility=visibility,
            source_type=source_type,
            title=title,
            filename=filename,
            file_id=file_id,
            content_hash=content_hash,
            extracted_text=extracted_text,
            version=1,
            owner_id=owner_id,
            status="active",
            metadata_json=metadata_json,
        )
        self._db.add(source)
        await self._db.flush()
        await self._db.refresh(source)
        return source

    async def update_version(self, id: int, content_hash: str | None = None, metadata_json: str | None = None) -> KnowledgeSource | None:
        source = await self.get_by_id(id)
        if source is None:
            return None
        source.version += 1
        if content_hash is not None:
            source.content_hash = content_hash
        if metadata_json is not None:
            source.metadata_json = metadata_json
        await self._db.flush()
        return source

    async def archive(self, id: int) -> KnowledgeSource | None:
        source = await self.get_by_id(id)
        if source is None:
            return None
        source.status = "archived"
        await self._db.flush()
        return source

    async def set_status(self, id: int, status: str) -> KnowledgeSource | None:
        source = await self.get_by_id(id)
        if source is None:
            return None
        source.status = status
        await self._db.flush()
        return source


class ProjectSourceRefRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def add_ref(
        self,
        project_id: int,
        source_id: int,
        ref_type: str = "context",
        snapshot_version: int | None = None,
    ) -> ProjectSourceRef:
        ref = ProjectSourceRef(
            project_id=project_id,
            source_id=source_id,
            ref_type=ref_type,
            snapshot_version=snapshot_version,
        )
        self._db.add(ref)
        await self._db.flush()
        await self._db.refresh(ref)
        return ref

    async def list_by_project(self, project_id: int) -> list[ProjectSourceRef]:
        result = await self._db.execute(
            select(ProjectSourceRef).where(
                ProjectSourceRef.project_id == project_id,
            ).order_by(ProjectSourceRef.id)
        )
        return list(result.scalars().all())

    async def list_by_source(self, source_id: int) -> list[ProjectSourceRef]:
        result = await self._db.execute(
            select(ProjectSourceRef).where(
                ProjectSourceRef.source_id == source_id,
            ).order_by(ProjectSourceRef.id)
        )
        return list(result.scalars().all())

    async def remove_ref(self, id: int) -> bool:
        result = await self._db.execute(select(ProjectSourceRef).where(ProjectSourceRef.id == id))
        ref = result.scalar_one_or_none()
        if ref is None:
            return False
        await self._db.delete(ref)
        await self._db.flush()
        return True

    async def freeze_snapshot(self, project_id: int) -> list[ProjectSourceRef]:
        """审查启动时冻结所有引用资料的 snapshot_version。"""
        refs = await self.list_by_project(project_id)
        from app.models.workspace import KnowledgeSource
        for ref in refs:
            if ref.snapshot_version is None:
                source_result = await self._db.execute(
                    select(KnowledgeSource).where(KnowledgeSource.id == ref.source_id)
                )
                source = source_result.scalar_one_or_none()
                if source:
                    ref.snapshot_version = source.version
        await self._db.flush()
        return refs
