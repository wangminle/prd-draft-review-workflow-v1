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


async def _require_project_write_member(db: AsyncSession, project_id: int, user_id: int):
    """要求项目 workspace 的 write 角色，但不套用“项目可见性=创建者”限制。

    BUG-212 回归：受邀 Approver/Reviewer 不是项目创建者，仍应能写评论/产物；
    assert_project_access 的 user_can_access_project 会把他们误判为无权限。
    """
    project = await ReviewProjectRepository(db).get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在或无权访问")
    ws_repo = WorkspaceRepository(db)
    workspace_id = project.workspace_id
    if workspace_id is None:
        default_ws = await ws_repo.get_default()
        workspace_id = default_ws.id if default_ws else None
    if workspace_id is None:
        raise HTTPException(403, "项目未关联团队空间，无法校验权限")
    member = await ws_repo.get_member(workspace_id, user_id)
    require_action(member, "write", "修改项目")
    return project, member


async def assert_review_request_access(db: AsyncSession, request_id: int, user_id: int) -> None:
    req_repo = ReviewRequestRepository(db)
    req = await req_repo.get_by_id(request_id)
    if req is None:
        raise HTTPException(404, "审查请求不存在或无权访问")

    project_repo = ReviewProjectRepository(db)
    project = await project_repo.get_project(req.project_id)
    if project is None:
        raise HTTPException(404, "审查请求不存在或无权访问")

    # SEC-09：发起人和项目创建者不能绕过 workspace 活跃成员校验。
    # 被移出团队/停用的成员不应继续保有请求及产物的读写权。
    ws_repo = WorkspaceRepository(db)
    workspace_id = project.workspace_id
    if workspace_id is None:
        default_ws = await ws_repo.get_default()
        workspace_id = default_ws.id if default_ws else None
    if workspace_id is None:
        raise HTTPException(404, "审查请求不存在或无权访问")
    member = await ws_repo.get_member(workspace_id, user_id)
    if member is None:
        raise HTTPException(404, "审查请求不存在或无权访问")

    if req.initiator_id == user_id:
        return

    if project.created_by == user_id:
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


async def assert_artifact_write_access(
    db: AsyncSession,
    artifact: Artifact,
    user_id: int,
    *,
    action: str = "write",
) -> None:
    """产物写/确认权限：Observer 只读；发起人/Reviewer/Approver/项目管理员可写。

    action:
      - write: 更新 draft 内容
      - confirm: 确认/解冻
    """
    await assert_artifact_access(db, artifact, user_id)

    if artifact.object_type == "conversation":
        # 会话产物：仅会话所有者（assert 已保证可读=所有者）
        return

    if artifact.object_type != "review_request":
        raise HTTPException(403, "无权修改该产物")

    req_repo = ReviewRequestRepository(db)
    req = await req_repo.get_by_id(artifact.object_id)
    if req is None:
        raise HTTPException(404, "审查请求不存在或无权访问")

    if req.initiator_id == user_id:
        await _require_project_write_member(db, req.project_id, user_id)
        return

    project_repo = ReviewProjectRepository(db)
    project = await project_repo.get_project(req.project_id)
    if project and project.created_by == user_id:
        await _require_project_write_member(db, req.project_id, user_id)
        return

    participant_repo = ReviewParticipantRepository(db)
    participant = await participant_repo.get_by_request_and_user(req.id, user_id)
    if participant is not None:
        if participant.status != "active":
            raise HTTPException(403, "当前角色无权修改该产物")
        if participant.role == "Observer":
            raise HTTPException(403, "观察者角色为只读，不能修改或确认产物")
        if action == "confirm" and participant.role not in ("Approver", "Reviewer"):
            raise HTTPException(403, "当前角色无权确认或解冻产物")
        if participant.role in ("Reviewer", "Approver"):
            await _require_project_write_member(db, req.project_id, user_id)
            return

    # workspace owner/admin 可写（未被显式设为 Observer/inactive 参与者时）
    if project is not None:
        ws_repo = WorkspaceRepository(db)
        workspace_id = project.workspace_id
        if workspace_id is None:
            default_ws = await ws_repo.get_default()
            workspace_id = default_ws.id if default_ws else None
        if workspace_id is not None:
            member = await ws_repo.get_member(workspace_id, user_id)
            if member and member.status == "active" and member.role in ("owner", "admin"):
                return

    raise HTTPException(403, "无权修改该产物")


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


async def assert_object_write_access(
    db: AsyncSession,
    object_type: str,
    object_id: int,
    user_id: int,
) -> None:
    """评论确认等写操作的多态权限校验（SEC-16）。

    读权限不等于写权限：Observer / 普通只读成员不能标记评论 resolved。
    """
    if object_type == "conversation":
        await assert_conversation_access(db, object_id, user_id)
        return

    if object_type == "review_round":
        result = await db.execute(select(ReviewRound).where(ReviewRound.id == object_id))
        rnd = result.scalar_one_or_none()
        if rnd is None:
            raise HTTPException(404, "审查轮次不存在或无权访问")
        object_type, object_id = "review_request", rnd.request_id

    if object_type == "review_request":
        await assert_review_request_access(db, object_id, user_id)
        req = await ReviewRequestRepository(db).get_by_id(object_id)
        if req is None:
            raise HTTPException(404, "审查请求不存在或无权访问")
        # BUG-212：发起人/创建者/参与者都必须具备 workspace write 角色，
        # 降为 viewer 后不能再解决评论。
        if req.initiator_id == user_id:
            await _require_project_write_member(db, req.project_id, user_id)
            return
        project = await ReviewProjectRepository(db).get_project(req.project_id)
        if project and project.created_by == user_id:
            await _require_project_write_member(db, req.project_id, user_id)
            return
        participant = await ReviewParticipantRepository(db).get_by_request_and_user(
            object_id, user_id,
        )
        if participant is not None:
            if participant.status != "active":
                raise HTTPException(403, "当前角色无权修改该对象")
            if participant.role == "Observer":
                raise HTTPException(403, "观察者角色为只读，不能修改或评论该对象")
            if participant.role in ("Reviewer", "Approver"):
                await _require_project_write_member(db, req.project_id, user_id)
                return
        if project is not None:
            try:
                _, member = await _require_project_write_member(db, req.project_id, user_id)
            except HTTPException:
                member = None
            if member is not None and member.role in ("owner", "admin"):
                return
        raise HTTPException(403, "当前角色无权修改该对象")

    if object_type == "artifact":
        result = await db.execute(select(Artifact).where(Artifact.id == object_id))
        artifact = result.scalar_one_or_none()
        if artifact is None:
            raise HTTPException(404, "产物不存在或无权访问")
        await assert_artifact_write_access(db, artifact, user_id)
        return

    if object_type == "knowledge_source":
        result = await db.execute(select(KnowledgeSource).where(KnowledgeSource.id == object_id))
        source = result.scalar_one_or_none()
        if source is None:
            raise HTTPException(404, "资料不存在或无权访问")
        if source.owner_type == "user" or source.visibility == "private":
            if source.owner_id != user_id:
                # BUG-212：私有资料即使调用者是同空间 writer 也不可写评论。
                raise HTTPException(404, "资料不存在或无权访问")
            return
        if source.workspace_id is not None:
            member = await WorkspaceRepository(db).get_member(source.workspace_id, user_id)
            require_action(member, "write", "修改资料评论")
            return
        raise HTTPException(403, "无权修改该资料评论")

    raise HTTPException(422, f"不支持的 object_type: {object_type}")
