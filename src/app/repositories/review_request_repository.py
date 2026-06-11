"""P4.A: 协作审查 Repository — ReviewRequest / ReviewRound / ReviewParticipant。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import ReviewRequest, ReviewRound, ReviewParticipant
from app.logging_config import now_cn


class ReviewRequestRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(self, *, project_id: int, initiator_id: int,
                     goal: str | None = None) -> ReviewRequest:
        req = ReviewRequest(
            project_id=project_id,
            initiator_id=initiator_id,
            goal=goal,
            status="initiated",
            current_round=1,
        )
        self._db.add(req)
        await self._db.flush()
        await self._db.refresh(req)
        return req

    async def get_by_id(self, request_id: int) -> ReviewRequest | None:
        result = await self._db.execute(
            select(ReviewRequest).where(ReviewRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: int) -> list[ReviewRequest]:
        result = await self._db.execute(
            select(ReviewRequest)
            .where(ReviewRequest.project_id == project_id)
            .order_by(ReviewRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_initiator(self, initiator_id: int) -> list[ReviewRequest]:
        result = await self._db.execute(
            select(ReviewRequest)
            .where(ReviewRequest.initiator_id == initiator_id)
            .order_by(ReviewRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_status(self, request: ReviewRequest, status: str) -> ReviewRequest:
        request.status = status
        request.updated_at = now_cn()
        await self._db.flush()
        await self._db.refresh(request)
        return request


class ReviewRoundRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(self, *, request_id: int, round_no: int,
                     submitted_snapshot_ref: str | None = None,
                     submitted_artifact_ref: str | None = None,
                     approver_id: int | None = None) -> ReviewRound:
        round_ = ReviewRound(
            request_id=request_id,
            round_no=round_no,
            submitted_snapshot_ref=submitted_snapshot_ref,
            submitted_artifact_ref=submitted_artifact_ref,
            approver_id=approver_id,
            decision="pending",
        )
        self._db.add(round_)
        await self._db.flush()
        await self._db.refresh(round_)
        return round_

    async def get_by_id(self, round_id: int) -> ReviewRound | None:
        result = await self._db.execute(
            select(ReviewRound).where(ReviewRound.id == round_id)
        )
        return result.scalar_one_or_none()

    async def list_by_request(self, request_id: int) -> list[ReviewRound]:
        result = await self._db.execute(
            select(ReviewRound)
            .where(ReviewRound.request_id == request_id)
            .order_by(ReviewRound.round_no)
        )
        return list(result.scalars().all())

    async def decide(self, round_: ReviewRound, *, approver_id: int,
                     decision: str, comment: str | None = None) -> ReviewRound:
        round_.approver_id = approver_id
        round_.decision = decision  # approved/rejected
        round_.decision_comment = comment
        round_.decided_at = now_cn()
        await self._db.flush()
        await self._db.refresh(round_)
        return round_


class ReviewParticipantRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def add_participant(self, *, request_id: int, user_id: int,
                              role: str) -> ReviewParticipant:
        p = ReviewParticipant(
            request_id=request_id,
            user_id=user_id,
            role=role,  # Reviewer/Approver/Observer
            status="active",
        )
        self._db.add(p)
        await self._db.flush()
        await self._db.refresh(p)
        return p

    async def list_by_request(self, request_id: int) -> list[ReviewParticipant]:
        result = await self._db.execute(
            select(ReviewParticipant)
            .where(ReviewParticipant.request_id == request_id)
            .order_by(ReviewParticipant.created_at)
        )
        return list(result.scalars().all())

    async def get_by_request_and_user(self, request_id: int, user_id: int) -> ReviewParticipant | None:
        result = await self._db.execute(
            select(ReviewParticipant).where(
                ReviewParticipant.request_id == request_id,
                ReviewParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def deactivate(self, participant: ReviewParticipant) -> ReviewParticipant:
        participant.status = "inactive"
        await self._db.flush()
        await self._db.refresh(participant)
        return participant
