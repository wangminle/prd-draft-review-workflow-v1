"""P4.B: 知识快照与产物路由 — Artifact CRUD / 确认冻结 / KnowledgeSnapshot。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.review import KnowledgeSnapshot, Artifact
from app.repositories.artifact_repository import (
    ArtifactRepository,
    KnowledgeSnapshotRepository,
)
from app.services.object_access import (
    assert_artifact_access,
    assert_object_access,
    assert_project_access,
)

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────

class CreateArtifact(BaseModel):
    object_type: str  # review_request/conversation
    object_id: int
    artifact_type: str  # html_presentation/svg_summary/mermaid_diagram/explanation_json
    content_json: str | None = None
    source_conversation_id: int | None = None
    source_snapshot_ref: str | None = None


class UpdateArtifactContent(BaseModel):
    content_json: str


class CreateSnapshot(BaseModel):
    workspace_id: int
    project_id: int
    request_id: int | None = None
    source_refs_json: str | None = None
    chunk_refs_json: str | None = None
    prompt_version: str | None = None
    skill_version: str | None = None
    model_config_hash: str | None = None


# ─── Helpers ──────────────────────────────────────────────────

def _serialize_artifact(a: Artifact) -> dict:
    return {
        "id": a.id,
        "object_type": a.object_type,
        "object_id": a.object_id,
        "artifact_type": a.artifact_type,
        "content_json": a.content_json,
        "source_conversation_id": a.source_conversation_id,
        "source_snapshot_ref": a.source_snapshot_ref,
        "template_version": a.template_version,
        "status": a.status,
        "confirmed_at": a.confirmed_at.isoformat() if a.confirmed_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _serialize_snapshot(s: KnowledgeSnapshot) -> dict:
    return {
        "id": s.id,
        "workspace_id": s.workspace_id,
        "project_id": s.project_id,
        "request_id": s.request_id,
        "source_refs_json": s.source_refs_json,
        "chunk_refs_json": s.chunk_refs_json,
        "prompt_version": s.prompt_version,
        "skill_version": s.skill_version,
        "model_config_hash": s.model_config_hash,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


# ─── Artifact Endpoints ──────────────────────────────────────

@router.post("/artifacts")
async def create_artifact(
    req: CreateArtifact,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P4.B.2: 创建产物（draft 状态）。"""
    if req.object_type not in ("review_request", "conversation"):
        raise HTTPException(422, "object_type must be review_request or conversation")

    await assert_object_access(db, req.object_type, req.object_id, user.id)
    if req.source_conversation_id is not None:
        await assert_object_access(db, "conversation", req.source_conversation_id, user.id)

    repo = ArtifactRepository(db)
    artifact = await repo.create(
        object_type=req.object_type,
        object_id=req.object_id,
        artifact_type=req.artifact_type,
        content_json=req.content_json,
        source_conversation_id=req.source_conversation_id,
        source_snapshot_ref=req.source_snapshot_ref,
    )
    await db.commit()
    return _serialize_artifact(artifact)


@router.get("/artifacts")
async def list_artifacts(
    object_type: str | None = None,
    object_id: int | None = None,
    conversation_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出产物。"""
    repo = ArtifactRepository(db)
    if conversation_id:
        await assert_object_access(db, "conversation", conversation_id, user.id)
        artifacts = await repo.list_by_conversation(conversation_id)
    elif object_type and object_id:
        await assert_object_access(db, object_type, object_id, user.id)
        artifacts = await repo.list_by_object(object_type, object_id)
    else:
        return []
    return [_serialize_artifact(a) for a in artifacts]


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取产物详情。"""
    repo = ArtifactRepository(db)
    artifact = await repo.get_by_id(artifact_id)
    if not artifact:
        raise HTTPException(404, "产物不存在")
    await assert_artifact_access(db, artifact, user.id)
    return _serialize_artifact(artifact)


@router.put("/artifacts/{artifact_id}/content")
async def update_artifact_content(
    artifact_id: int,
    req: UpdateArtifactContent,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新产物内容（仅 draft 状态可修改）。"""
    repo = ArtifactRepository(db)
    artifact = await repo.get_by_id(artifact_id)
    if not artifact:
        raise HTTPException(404, "产物不存在")
    await assert_artifact_access(db, artifact, user.id)
    try:
        await repo.update_content(artifact, req.content_json)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return _serialize_artifact(artifact)


@router.post("/artifacts/{artifact_id}/confirm")
async def confirm_artifact(
    artifact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P4.B.4: 物料确认冻结 — draft→confirmed。"""
    repo = ArtifactRepository(db)
    artifact = await repo.get_by_id(artifact_id)
    if not artifact:
        raise HTTPException(404, "产物不存在")
    await assert_artifact_access(db, artifact, user.id)
    try:
        await repo.confirm(artifact)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 通知项目相关参与者（defer_push：commit 成功后才推送，避免幽灵通知 BUG-106）
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db, defer_push=True)
    if artifact.object_type == "review_request":
        from app.repositories.review_request_repository import ReviewParticipantRepository
        participant_repo = ReviewParticipantRepository(db)
        participants = await participant_repo.list_by_request(artifact.object_id)
        recipient_ids = [p.user_id for p in participants if p.user_id != user.id and p.status == "active"]
        await notif_service.notify_artifact_confirmed(
            artifact_id=artifact.id,
            object_type=artifact.object_type,
            object_id=artifact.object_id,
            confirmer_id=user.id,
            recipient_ids=recipient_ids,
        )

    await db.commit()
    notif_service.flush_pending()
    return _serialize_artifact(artifact)


@router.post("/artifacts/{artifact_id}/unconfirm")
async def unconfirm_artifact(
    artifact_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消物料确认 — confirmed→draft。"""
    repo = ArtifactRepository(db)
    artifact = await repo.get_by_id(artifact_id)
    if not artifact:
        raise HTTPException(404, "产物不存在")
    await assert_artifact_access(db, artifact, user.id)
    try:
        await repo.unconfirm(artifact)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return _serialize_artifact(artifact)


# ─── KnowledgeSnapshot Endpoints ─────────────────────────────

@router.post("/snapshots")
async def create_snapshot(
    req: CreateSnapshot,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P4.B.1: 创建知识快照。"""
    await assert_project_access(db, req.project_id, user.id, action="write")
    repo = KnowledgeSnapshotRepository(db)
    snapshot = await repo.create(
        workspace_id=req.workspace_id,
        project_id=req.project_id,
        request_id=req.request_id,
        source_refs_json=req.source_refs_json,
        chunk_refs_json=req.chunk_refs_json,
        prompt_version=req.prompt_version,
        skill_version=req.skill_version,
        model_config_hash=req.model_config_hash,
    )
    await db.commit()
    return _serialize_snapshot(snapshot)


@router.get("/snapshots")
async def list_snapshots(
    project_id: int | None = None,
    request_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出知识快照。"""
    repo = KnowledgeSnapshotRepository(db)
    if request_id:
        await assert_object_access(db, "review_request", request_id, user.id)
        snapshot = await repo.get_by_request(request_id)
        return [_serialize_snapshot(snapshot)] if snapshot else []
    elif project_id:
        await assert_project_access(db, project_id, user.id, action="read")
        snapshots = await repo.list_by_project(project_id)
        return [_serialize_snapshot(s) for s in snapshots]
    return []


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(
    snapshot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取知识快照详情。"""
    repo = KnowledgeSnapshotRepository(db)
    snapshot = await repo.get_by_id(snapshot_id)
    if not snapshot:
        raise HTTPException(404, "快照不存在")
    await assert_project_access(db, snapshot.project_id, user.id, action="read")
    return _serialize_snapshot(snapshot)
