"""P4.B: 知识快照与产物 Repository — KnowledgeSnapshot / Artifact。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import KnowledgeSnapshot, Artifact
from app.logging_config import now_cn


class KnowledgeSnapshotRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        *,
        workspace_id: int,
        project_id: int,
        request_id: int | None = None,
        source_refs_json: str | None = None,
        chunk_refs_json: str | None = None,
        prompt_version: str | None = None,
        skill_version: str | None = None,
        model_config_hash: str | None = None,
    ) -> KnowledgeSnapshot:
        snapshot = KnowledgeSnapshot(
            workspace_id=workspace_id,
            project_id=project_id,
            request_id=request_id,
            source_refs_json=source_refs_json,
            chunk_refs_json=chunk_refs_json,
            prompt_version=prompt_version,
            skill_version=skill_version,
            model_config_hash=model_config_hash,
        )
        self._db.add(snapshot)
        await self._db.flush()
        await self._db.refresh(snapshot)
        return snapshot

    async def get_by_id(self, snapshot_id: int) -> KnowledgeSnapshot | None:
        result = await self._db.execute(
            select(KnowledgeSnapshot).where(KnowledgeSnapshot.id == snapshot_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: int) -> list[KnowledgeSnapshot]:
        result = await self._db.execute(
            select(KnowledgeSnapshot)
            .where(KnowledgeSnapshot.project_id == project_id)
            .order_by(KnowledgeSnapshot.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest_by_project(self, project_id: int) -> KnowledgeSnapshot | None:
        """获取项目最新的知识快照。"""
        result = await self._db.execute(
            select(KnowledgeSnapshot)
            .where(KnowledgeSnapshot.project_id == project_id)
            .order_by(KnowledgeSnapshot.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_request(self, request_id: int) -> KnowledgeSnapshot | None:
        """获取审查请求关联的知识快照。"""
        result = await self._db.execute(
            select(KnowledgeSnapshot)
            .where(KnowledgeSnapshot.request_id == request_id)
            .order_by(KnowledgeSnapshot.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class ArtifactRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        *,
        object_type: str,
        object_id: int,
        artifact_type: str,
        content_json: str | None = None,
        source_conversation_id: int | None = None,
        source_snapshot_ref: str | None = None,
        template_version: str | None = None,
    ) -> Artifact:
        artifact = Artifact(
            object_type=object_type,
            object_id=object_id,
            artifact_type=artifact_type,
            content_json=content_json,
            source_conversation_id=source_conversation_id,
            source_snapshot_ref=source_snapshot_ref,
            template_version=template_version,
            status="draft",
        )
        self._db.add(artifact)
        await self._db.flush()
        await self._db.refresh(artifact)
        return artifact

    async def get_by_id(self, artifact_id: int) -> Artifact | None:
        result = await self._db.execute(
            select(Artifact).where(Artifact.id == artifact_id)
        )
        return result.scalar_one_or_none()

    async def list_by_object(self, object_type: str, object_id: int) -> list[Artifact]:
        """列出指定对象的全部产物。"""
        result = await self._db.execute(
            select(Artifact)
            .where(
                Artifact.object_type == object_type,
                Artifact.object_id == object_id,
            )
            .order_by(Artifact.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_conversation(self, conversation_id: int) -> list[Artifact]:
        """列出对话关联的全部产物。"""
        result = await self._db.execute(
            select(Artifact)
            .where(Artifact.source_conversation_id == conversation_id)
            .order_by(Artifact.created_at.desc())
        )
        return list(result.scalars().all())

    async def confirm(self, artifact: Artifact) -> Artifact:
        """P4.B.4: 物料确认冻结 — draft→confirmed，confirmed 后不可修改。"""
        if artifact.status != "draft":
            raise ValueError(f"Artifact status is '{artifact.status}', can only confirm from 'draft'")
        artifact.status = "confirmed"
        artifact.confirmed_at = now_cn()
        artifact.updated_at = now_cn()
        await self._db.flush()
        await self._db.refresh(artifact)
        return artifact

    async def unconfirm(self, artifact: Artifact) -> Artifact:
        """取消确认 — confirmed→draft，回到可编辑状态。"""
        if artifact.status != "confirmed":
            raise ValueError(f"Artifact status is '{artifact.status}', can only unconfirm from 'confirmed'")
        artifact.status = "draft"
        artifact.confirmed_at = None
        artifact.updated_at = now_cn()
        await self._db.flush()
        await self._db.refresh(artifact)
        return artifact

    async def update_content(self, artifact: Artifact, content_json: str) -> Artifact:
        """更新产物内容（仅 draft 状态可修改）。"""
        if artifact.status != "draft":
            raise ValueError("Cannot update confirmed artifact")
        artifact.content_json = content_json
        artifact.updated_at = now_cn()
        await self._db.flush()
        await self._db.refresh(artifact)
        return artifact
