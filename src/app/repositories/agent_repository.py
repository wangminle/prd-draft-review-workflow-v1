"""Agent Profile / Authorization / Run / Trace / Approval Repository"""

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import (
    AgentApprovalRequest,
    AgentAuthorization,
    AgentProfile,
    AgentRun,
    AgentStep,
    ToolCallTrace,
)
from app.utils import now_cn

logger = logging.getLogger(__name__)


class AgentProfileRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_owner(self, owner_type: str, owner_id: int) -> Optional[AgentProfile]:
        result = await self._db.execute(
            select(AgentProfile)
            .where(AgentProfile.owner_type == owner_type, AgentProfile.owner_id == owner_id)
            .options(selectinload(AgentProfile.authorizations))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, profile_id: int) -> Optional[AgentProfile]:
        result = await self._db.execute(
            select(AgentProfile)
            .where(AgentProfile.id == profile_id)
            .options(selectinload(AgentProfile.authorizations))
        )
        return result.scalar_one_or_none()

    async def create(self, owner_type: str, owner_id: int, name: str = "My Agent",
                     system_policy: str | None = None,
                     allowed_tools_json: str | None = None) -> AgentProfile:
        profile = AgentProfile(
            owner_type=owner_type,
            owner_id=owner_id,
            name=name,
            system_policy=system_policy,
            allowed_tools_json=allowed_tools_json,
        )
        self._db.add(profile)
        await self._db.commit()
        await self._db.refresh(profile)
        return profile

    async def update(self, profile: AgentProfile, **kwargs) -> AgentProfile:
        for key, value in kwargs.items():
            if hasattr(profile, key) and value is not None:
                setattr(profile, key, value)
        profile.version += 1
        await self._db.commit()
        await self._db.refresh(profile)
        return profile


class AgentAuthorizationRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def list_by_agent(self, agent_id: int) -> list[AgentAuthorization]:
        result = await self._db.execute(
            select(AgentAuthorization).where(AgentAuthorization.agent_id == agent_id)
        )
        return list(result.scalars().all())

    async def create(self, agent_id: int, granted_by: int, scope_type: str,
                     scope_id: int | None = None,
                     permissions_json: str | None = None,
                     expires_at: datetime | None = None) -> AgentAuthorization:
        auth = AgentAuthorization(
            agent_id=agent_id,
            granted_by=granted_by,
            scope_type=scope_type,
            scope_id=scope_id,
            permissions_json=permissions_json,
            expires_at=expires_at,
        )
        self._db.add(auth)
        await self._db.commit()
        await self._db.refresh(auth)
        return auth

    async def revoke(self, auth_id: int) -> bool:
        result = await self._db.execute(
            select(AgentAuthorization).where(AgentAuthorization.id == auth_id)
        )
        auth = result.scalar_one_or_none()
        if not auth:
            return False
        await self._db.delete(auth)
        await self._db.commit()
        return True


class AgentRunRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(self, agent_id: int, user_id: int, goal: str,
                     conversation_id: int | None = None) -> AgentRun:
        run = AgentRun(
            agent_id=agent_id,
            user_id=user_id,
            goal=goal,
            conversation_id=conversation_id,
            status="planning",
        )
        self._db.add(run)
        await self._db.commit()
        await self._db.refresh(run)
        return run

    async def get_by_id(self, run_id: int) -> Optional[AgentRun]:
        result = await self._db.execute(
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .options(selectinload(AgentRun.steps), selectinload(AgentRun.traces))
        )
        return result.scalar_one_or_none()

    async def update_status(self, run: AgentRun, status: str, error_message: str | None = None) -> AgentRun:
        run.status = status
        if error_message:
            run.error_message = error_message
        if status in ("completed", "failed"):
            run.finished_at = now_cn()
        await self._db.commit()
        return run

    async def add_step(self, run_id: int, step_no: int, step_type: str,
                       tool_name: str | None = None,
                       input_ref: str | None = None) -> AgentStep:
        step = AgentStep(
            run_id=run_id,
            step_no=step_no,
            step_type=step_type,
            tool_name=tool_name,
            input_ref=input_ref,
            status="pending",
        )
        self._db.add(step)
        await self._db.commit()
        await self._db.refresh(step)
        return step

    async def update_step(self, step: AgentStep, status: str,
                          output_ref: str | None = None,
                          latency_ms: int | None = None) -> AgentStep:
        step.status = status
        if output_ref is not None:
            step.output_ref = output_ref
        if latency_ms is not None:
            step.latency_ms = latency_ms
        await self._db.commit()
        return step

    async def add_trace(self, run_id: int, tool_name: str,
                        input_json: str | None = None,
                        step_id: int | None = None,
                        risk_level: str = "low") -> ToolCallTrace:
        trace = ToolCallTrace(
            run_id=run_id,
            step_id=step_id,
            tool_name=tool_name,
            input_json=input_json,
            risk_level=risk_level,
            status="pending",
        )
        self._db.add(trace)
        await self._db.commit()
        await self._db.refresh(trace)
        return trace

    async def update_trace(self, trace: ToolCallTrace, status: str,
                           output_ref: str | None = None,
                           latency_ms: int | None = None) -> ToolCallTrace:
        trace.status = status
        if output_ref is not None:
            trace.output_ref = output_ref
        if latency_ms is not None:
            trace.latency_ms = latency_ms
        await self._db.commit()
        return trace


class AgentApprovalRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(self, run_id: int, requester_id: int, action_type: str,
                     approver_id: int,
                     payload_ref: str | None = None,
                     trace_id: int | None = None) -> AgentApprovalRequest:
        req = AgentApprovalRequest(
            run_id=run_id,
            trace_id=trace_id,
            requester_id=requester_id,
            approver_id=approver_id,
            action_type=action_type,
            payload_ref=payload_ref,
            status="pending",
        )
        self._db.add(req)
        await self._db.commit()
        await self._db.refresh(req)
        return req

    async def list_pending(self, approver_id: int) -> list[AgentApprovalRequest]:
        query = select(AgentApprovalRequest).where(
            AgentApprovalRequest.status == "pending",
            AgentApprovalRequest.approver_id == approver_id,
        )
        result = await self._db.execute(query.order_by(AgentApprovalRequest.created_at.desc()))
        return list(result.scalars().all())

    async def get_by_id(self, request_id: int) -> Optional[AgentApprovalRequest]:
        result = await self._db.execute(
            select(AgentApprovalRequest).where(AgentApprovalRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def decide(self, request: AgentApprovalRequest, approver_id: int,
                     decision: str, comment: str | None = None) -> AgentApprovalRequest:
        request.status = decision  # approved/rejected
        request.approver_id = approver_id
        request.decision_comment = comment
        request.decided_at = now_cn()
        await self._db.commit()
        return request
