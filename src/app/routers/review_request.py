"""P4.A: 协作审查路由 — ReviewRequest / ReviewRound / ReviewParticipant API。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.review import ReviewRequest, ReviewRound, ReviewParticipant
from app.repositories.review_request_repository import (
    ReviewRequestRepository,
    ReviewRoundRepository,
    ReviewParticipantRepository,
)
from app.repositories.review_project_repository import ReviewProjectRepository

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Schemas ──────────────────────────────────────────────────

class CreateReviewRequest(BaseModel):
    project_id: int
    approver_ids: list[int] = []  # 指定审查员
    goal: str | None = None


class RoundDecision(BaseModel):
    decision: str  # approved/rejected
    comment: str | None = None


# ─── Helpers ──────────────────────────────────────────────────

def _serialize_request(req: ReviewRequest) -> dict:
    return {
        "id": req.id,
        "project_id": req.project_id,
        "initiator_id": req.initiator_id,
        "goal": req.goal,
        "status": req.status,
        "current_round": req.current_round,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
    }


def _serialize_round(round_: ReviewRound) -> dict:
    return {
        "id": round_.id,
        "request_id": round_.request_id,
        "round_no": round_.round_no,
        "submitted_snapshot_ref": round_.submitted_snapshot_ref,
        "submitted_artifact_ref": round_.submitted_artifact_ref,
        "approver_id": round_.approver_id,
        "decision": round_.decision,
        "decision_comment": round_.decision_comment,
        "created_at": round_.created_at.isoformat() if round_.created_at else None,
        "decided_at": round_.decided_at.isoformat() if round_.decided_at else None,
    }


def _serialize_participant(p: ReviewParticipant) -> dict:
    return {
        "id": p.id,
        "request_id": p.request_id,
        "user_id": p.user_id,
        "role": p.role,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


async def _can_access_request(db: AsyncSession, req: ReviewRequest, user_id: int) -> bool:
    """检查用户是否有权访问某个审查请求（发起人/项目创建者/参与者）。"""
    if req.initiator_id == user_id:
        return True
    # 项目创建者
    project_repo = ReviewProjectRepository(db)
    project = await project_repo.get_project(req.project_id)
    if project and project.created_by == user_id:
        return True
    # 参与者
    participant_repo = ReviewParticipantRepository(db)
    participant = await participant_repo.get_by_request_and_user(req.id, user_id)
    if participant and participant.status == "active":
        return True
    return False


# ─── Endpoints ────────────────────────────────────────────────

@router.post("/requests")
async def create_review_request(
    req: CreateReviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P4.A.4: 发起协作审查请求（阶段A通过后）。"""
    # 验证项目存在
    project_repo = ReviewProjectRepository(db)
    project = await project_repo.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "项目不存在")

    # 权限校验：用户必须是项目创建者（先于业务参数校验，
    # 否则无权用户会因为缺少 approver_ids 收到 422 而非 403，
    # 既泄露接口存在性，也与越权拦截语义不一致）
    if project.created_by != user.id:
        raise HTTPException(403, "只有项目创建者可以发起协作审查")

    # BUG-084：协作审查必须至少指定一名审批人，否则创建后无人可决策
    if not req.approver_ids:
        raise HTTPException(422, "至少指定一名审批人")

    # 创建 ReviewRequest
    request_repo = ReviewRequestRepository(db)
    review_req = await request_repo.create(
        project_id=req.project_id,
        initiator_id=user.id,
        goal=req.goal,
    )

    # 创建 ReviewRound(round_no=1)
    round_repo = ReviewRoundRepository(db)
    await round_repo.create(
        request_id=review_req.id,
        round_no=1,
        approver_id=req.approver_ids[0] if req.approver_ids else None,
    )

    # 添加参与者
    participant_repo = ReviewParticipantRepository(db)
    await participant_repo.add_participant(
        request_id=review_req.id, user_id=user.id, role="Reviewer",
    )
    for approver_id in req.approver_ids:
        await participant_repo.add_participant(
            request_id=review_req.id, user_id=approver_id, role="Approver",
        )

    # 更新状态为 pending_approval
    await request_repo.update_status(review_req, "pending_approval")

    # P4.D.3: 通知 Approver
    if req.approver_ids:
        from app.services.notification_service import NotificationService
        notif_service = NotificationService(db)
        await notif_service.notify_review_request_created(
            request_id=review_req.id,
            project_id=req.project_id,
            initiator_id=user.id,
            approver_ids=req.approver_ids,
            goal=req.goal,
        )

    await db.commit()
    await db.refresh(review_req)

    return _serialize_request(review_req)


@router.get("/requests")
async def list_review_requests(
    project_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出协作审查请求（按项目或当前用户过滤）。"""
    request_repo = ReviewRequestRepository(db)
    if project_id:
        # 权限校验：按项目查询时，需验证用户可访问该项目
        project_repo = ReviewProjectRepository(db)
        project = await project_repo.get_project_if_accessible(project_id, user.id)
        if not project:
            raise HTTPException(403, "无权查看该项目的协作审查")
        all_requests = await request_repo.list_by_project(project_id)
        # 非项目创建者仅能看到自己参与的请求
        if project.created_by != user.id:
            participant_repo = ReviewParticipantRepository(db)
            accessible = []
            for req_item in all_requests:
                if await _can_access_request(db, req_item, user.id):
                    accessible.append(req_item)
            requests = accessible
        else:
            requests = all_requests
    else:
        requests = await request_repo.list_by_initiator(user.id)
    return [_serialize_request(r) for r in requests]


@router.get("/requests/{request_id}")
async def get_review_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取协作审查请求详情。"""
    request_repo = ReviewRequestRepository(db)
    req = await request_repo.get_by_id(request_id)
    if not req:
        raise HTTPException(404, "审查请求不存在")
    # 权限校验：用户必须是发起人或项目创建者或参与者
    if not await _can_access_request(db, req, user.id):
        raise HTTPException(403, "无权查看此审查请求")
    return _serialize_request(req)


@router.get("/requests/{request_id}/rounds")
async def list_review_rounds(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取审查请求的所有轮次。"""
    # 权限校验：先验证请求访问权
    request_repo = ReviewRequestRepository(db)
    req = await request_repo.get_by_id(request_id)
    if not req:
        raise HTTPException(404, "审查请求不存在")
    if not await _can_access_request(db, req, user.id):
        raise HTTPException(403, "无权查看此审查请求的轮次")

    round_repo = ReviewRoundRepository(db)
    rounds = await round_repo.list_by_request(request_id)
    return [_serialize_round(r) for r in rounds]


@router.post("/rounds/{round_id}/decide")
async def decide_round(
    round_id: int,
    req: RoundDecision,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P4.A.5: 审查员对轮次做出决策（approved/rejected）。"""
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(422, "decision must be 'approved' or 'rejected'")

    round_repo = ReviewRoundRepository(db)
    review_round = await round_repo.get_by_id(round_id)
    if not review_round:
        raise HTTPException(404, "审查轮次不存在")
    if review_round.decision != "pending":
        raise HTTPException(400, f"轮次已决策: {review_round.decision}")

    # 权限校验：当前用户必须是该轮次的指定审批人或有效 Approver 参与者
    if review_round.approver_id and review_round.approver_id != user.id:
        # 指定了 approver_id 但不是当前用户 → 检查是否为该请求的 Approver 参与者
        participant_repo = ReviewParticipantRepository(db)
        participant = await participant_repo.get_by_request_and_user(
            review_round.request_id, user.id,
        )
        if not participant or participant.role != "Approver":
            raise HTTPException(403, "只有指定的审批人可以做出决策")
    elif not review_round.approver_id:
        # 未指定 approver_id，检查参与者中是否有 Approver 角色
        participant_repo = ReviewParticipantRepository(db)
        participant = await participant_repo.get_by_request_and_user(
            review_round.request_id, user.id,
        )
        if not participant or participant.role != "Approver":
            raise HTTPException(403, "只有审批人角色可以做出决策")

    # 决策
    review_round = await round_repo.decide(
        review_round,
        approver_id=user.id,
        decision=req.decision,
        comment=req.comment,
    )

    # 更新 ReviewRequest 状态
    request_repo = ReviewRequestRepository(db)
    review_req = await request_repo.get_by_id(review_round.request_id)
    if review_req:
        if req.decision == "approved":
            await request_repo.update_status(review_req, "approved")
        elif req.decision == "rejected":
            await request_repo.update_status(review_req, "rejected")

        # P4.D.3: 通知发起人
        from app.services.notification_service import NotificationService
        notif_service = NotificationService(db)
        await notif_service.notify_review_round_decided(
            request_id=review_req.id,
            round_no=review_round.round_no,
            decision=req.decision,
            comment=req.comment,
            initiator_id=review_req.initiator_id,
            approver_id=user.id,
        )

    await db.commit()
    return _serialize_round(review_round)


@router.post("/requests/{request_id}/resubmit")
async def resubmit_review_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P4.A.5: 发起人驳回后重新提交（创建新一轮）。"""
    request_repo = ReviewRequestRepository(db)
    review_req = await request_repo.get_by_id(request_id)
    if not review_req:
        raise HTTPException(404, "审查请求不存在")
    if review_req.status != "rejected":
        raise HTTPException(400, "只有被驳回的请求可以重新提交")
    if review_req.initiator_id != user.id:
        raise HTTPException(403, "只有发起人可以重新提交")

    # 创建新轮次 — 继承上一轮的 approver_id，避免"无人审批"
    round_repo = ReviewRoundRepository(db)
    new_round_no = review_req.current_round + 1
    # 查找上一轮的 approver_id
    prev_rounds = await round_repo.list_by_request(review_req.id)
    prev_approver_id = None
    for r in reversed(prev_rounds):
        if r.approver_id:
            prev_approver_id = r.approver_id
            break
    await round_repo.create(
        request_id=review_req.id,
        round_no=new_round_no,
        approver_id=prev_approver_id,
    )

    # 更新 ReviewRequest
    review_req.current_round = new_round_no
    await request_repo.update_status(review_req, "pending_approval")

    # P4.D.3: 通知审批人重新提交
    if prev_approver_id:
        try:
            async with db.begin_nested():
                from app.services.notification_service import NotificationService
                notif_service = NotificationService(db)
                await notif_service.notify_review_request_created(
                    request_id=review_req.id,
                    project_id=review_req.project_id,
                    initiator_id=user.id,
                    approver_ids=[prev_approver_id],
                    goal=review_req.goal,
                )
        except Exception as exc:
            logger.warning("review request resubmit notification failed: %s", exc)

    await db.commit()
    await db.refresh(review_req)

    return _serialize_request(review_req)


@router.get("/requests/{request_id}/participants")
async def list_review_participants(
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取审查请求的参与者列表。"""
    # 权限校验：先验证请求访问权
    request_repo = ReviewRequestRepository(db)
    req = await request_repo.get_by_id(request_id)
    if not req:
        raise HTTPException(404, "审查请求不存在")
    if not await _can_access_request(db, req, user.id):
        raise HTTPException(403, "无权查看此审查请求的参与者")

    participant_repo = ReviewParticipantRepository(db)
    participants = await participant_repo.list_by_request(request_id)
    return [_serialize_participant(p) for p in participants]


@router.post("/requests/{request_id}/participants")
async def add_review_participant(
    request_id: int,
    user_id: int = None,
    role: str = "Observer",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """添加审查参与者。"""
    # 权限校验：只有请求发起人或项目创建者可以添加参与者
    request_repo = ReviewRequestRepository(db)
    req = await request_repo.get_by_id(request_id)
    if not req:
        raise HTTPException(404, "审查请求不存在")
    if req.initiator_id != user.id:
        project_repo = ReviewProjectRepository(db)
        project = await project_repo.get_project(req.project_id)
        if not project or project.created_by != user.id:
            raise HTTPException(403, "只有发起人或项目创建者可以添加参与者")

    if role not in ("Reviewer", "Approver", "Observer"):
        raise HTTPException(422, "role must be Reviewer/Approver/Observer")

    participant_repo = ReviewParticipantRepository(db)
    p = await participant_repo.add_participant(
        request_id=request_id,
        user_id=user_id or user.id,
        role=role,
    )
    await db.commit()
    return _serialize_participant(p)
