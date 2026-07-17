"""多态对象访问权限解析 — Artifact / Comment / KnowledgeSnapshot。

按 object_type 解析到 conversation / review_request / project / workspace / knowledge_source，
统一做归属与成员权限校验，避免仅登录即可跨用户读写（BOLA）。
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import Artifact, ReviewRound
from app.models.workspace import KnowledgeSource
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.review_project_repository import ReviewProjectRepository
from app.repositories.review_request_repository import (
    ReviewParticipantRepository,
    ReviewRequestRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.workspace_access import require_action


async def assert_conversation_access(db: AsyncSession, conversation_id: int, user_id: int) -> None:
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_conversation(conversation_id, user_id=user_id)
    if conv is None:
        raise HTTPException(404, "会话不存在或无权访问")


async def assert_project_access(db: AsyncSession, project_id: int, user_id: int, action: str = "read") -> None:
    """与 review._verify_project_owner 对齐的项目访问校验。"""
    repo = ReviewProjectRepository(db)
    project = await repo.get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在或无权访问")

    ws_repo = WorkspaceRepository(db)
    workspace_id = project.workspace_id
    if workspace_id is None:
        default_ws = await ws_repo.get_default()
        if default_ws is None:
            raise HTTPException(403, "项目未关联团队空间，无法校验权限")
        workspace_id = default_ws.id

    member = await ws_repo.get_member(workspace_id, user_id)
    require_action(member, action, "访问项目")

    member_role = member.role if member else None
    if not repo.user_can_access_project(project, user_id, member_role):
        raise HTTPException(404, "项目不存在或无权访问")


async def assert_review_request_access(db: AsyncSession, request_id: int, user_id: int) -> None:
    req_repo = ReviewRequestRepository(db)
    req = await req_repo.get_by_id(request_id)
    if req is None:
        raise HTTPException(404, "审查请求不存在或无权访问")

    if req.initiator_id == user_id:
        return

    project_repo = ReviewProjectRepository(db)
    project = await project_repo.get_project(req.project_id)
    if project and project.created_by == user_id:
        return

    participant_repo = ReviewParticipantRepository(db)
    participant = await participant_repo.get_by_request_and_user(req.id, user_id)
    if participant and participant.status == "active":
        return

    # 空间 owner/admin 也可访问项目下的请求
    try:
        await assert_project_access(db, req.project_id, user_id, action="read")
        return
    except HTTPException:
        raise HTTPException(404, "审查请求不存在或无权访问")


async def assert_review_round_access(db: AsyncSession, round_id: int, user_id: int) -> None:
    result = await db.execute(select(ReviewRound).where(ReviewRound.id == round_id))
    rnd = result.scalar_one_or_none()
    if rnd is None:
        raise HTTPException(404, "审查轮次不存在或无权访问")
    await assert_review_request_access(db, rnd.request_id, user_id)


async def assert_knowledge_source_access(db: AsyncSession, source_id: int, user_id: int) -> None:
    result = await db.execute(select(KnowledgeSource).where(KnowledgeSource.id == source_id))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(404, "资料不存在或无权访问")

    # 个人私有资料：仅 owner
    if source.owner_type == "user" or source.visibility == "private":
        if source.owner_id != user_id:
            raise HTTPException(404, "资料不存在或无权访问")
        return

    if source.workspace_id is None:
        raise HTTPException(404, "资料不存在或无权访问")

    ws_repo = WorkspaceRepository(db)
    member = await ws_repo.get_member(source.workspace_id, user_id)
    require_action(member, "read", "访问资料")


async def assert_artifact_access(db: AsyncSession, artifact: Artifact, user_id: int) -> None:
    await assert_object_access(db, artifact.object_type, artifact.object_id, user_id)


async def assert_object_access(
    db: AsyncSession,
    object_type: str,
    object_id: int,
    user_id: int,
) -> None:
    """按多态 object_type/object_id 校验当前用户可读。"""
    if object_type == "conversation":
        await assert_conversation_access(db, object_id, user_id)
    elif object_type == "review_request":
        await assert_review_request_access(db, object_id, user_id)
    elif object_type == "review_round":
        await assert_review_round_access(db, object_id, user_id)
    elif object_type == "artifact":
        result = await db.execute(select(Artifact).where(Artifact.id == object_id))
        artifact = result.scalar_one_or_none()
        if artifact is None:
            raise HTTPException(404, "产物不存在或无权访问")
        await assert_artifact_access(db, artifact, user_id)
    elif object_type == "knowledge_source":
        await assert_knowledge_source_access(db, object_id, user_id)
    else:
        raise HTTPException(422, f"不支持的 object_type: {object_type}")
