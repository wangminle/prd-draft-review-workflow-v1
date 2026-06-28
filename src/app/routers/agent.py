"""Agent Profile / Run / Approval API endpoints (P3)"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.repositories.agent_repository import (
    AgentApprovalRepository,
    AgentAuthorizationRepository,
    AgentProfileRepository,
    AgentRunRepository,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────

class AgentProfileUpdate(BaseModel):
    name: Optional[str] = None
    system_policy: Optional[str] = None
    allowed_tools: Optional[list[str]] = None  # will be serialized to JSON
    status: Optional[str] = None
    default_scope_type: Optional[str] = None  # P5.A.2: personal/workspace


class AuthorizationCreate(BaseModel):
    scope_type: str  # workspace/project/personal
    scope_id: Optional[int] = None
    permissions: Optional[list[str]] = None  # ["read", "write", "search", "execute"]
    expires_at: Optional[str] = None  # ISO datetime


class AgentRunCreate(BaseModel):
    goal: str
    conversation_id: Optional[int] = None


class ApprovalDecision(BaseModel):
    decision: str  # approved/rejected
    comment: Optional[str] = None


class MCPServerConfigCreate(BaseModel):
    name: str
    server_type: str = "stdio"
    endpoint_ref: str
    workspace_id: Optional[int] = None
    metadata_json: Optional[str] = None


class MCPToolPolicyCreate(BaseModel):
    tool_name: str
    allowed_roles: Optional[list[str]] = None
    requires_approval: bool = False
    risk_level: str = "low"


# ─── Helpers ──────────────────────────────────────────────────

def _serialize_profile(profile) -> dict:
    allowed_tools = []
    if profile.allowed_tools_json:
        try:
            allowed_tools = json.loads(profile.allowed_tools_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": profile.id,
        "owner_type": profile.owner_type,
        "owner_id": profile.owner_id,
        "name": profile.name,
        "system_policy": profile.system_policy,
        "allowed_tools": allowed_tools,
        "status": profile.status,
        "default_scope_type": getattr(profile, "default_scope_type", "personal"),
        "version": profile.version,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _serialize_authorization(auth) -> dict:
    perms = []
    if auth.permissions_json:
        try:
            perms = json.loads(auth.permissions_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": auth.id,
        "agent_id": auth.agent_id,
        "granted_by": auth.granted_by,
        "scope_type": auth.scope_type,
        "scope_id": auth.scope_id,
        "permissions": perms,
        "expires_at": auth.expires_at.isoformat() if auth.expires_at else None,
        "created_at": auth.created_at.isoformat() if auth.created_at else None,
    }


def _serialize_run(run) -> dict:
    return {
        "id": run.id,
        "agent_id": run.agent_id,
        "user_id": run.user_id,
        "conversation_id": run.conversation_id,
        "goal": run.goal,
        "status": run.status,
        "total_steps": run.total_steps,
        "total_tool_calls": run.total_tool_calls,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _serialize_run_detail(run) -> dict:
    data = _serialize_run(run)
    data["steps"] = [_serialize_step(s) for s in (run.steps or [])]
    data["traces"] = [_serialize_trace(t) for t in (run.traces or [])]
    return data


def _serialize_step(step) -> dict:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "step_no": step.step_no,
        "step_type": step.step_type,
        "tool_name": step.tool_name,
        "input_ref": step.input_ref,
        "output_ref": step.output_ref,
        "status": step.status,
        "latency_ms": step.latency_ms,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }


def _serialize_trace(trace) -> dict:
    return {
        "id": trace.id,
        "run_id": trace.run_id,
        "step_id": trace.step_id,
        "tool_name": trace.tool_name,
        "input_json": trace.input_json,
        "output_ref": trace.output_ref,
        "status": trace.status,
        "risk_level": trace.risk_level,
        "approval_status": trace.approval_status,
        "latency_ms": trace.latency_ms,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }


def _serialize_approval(req) -> dict:
    return {
        "id": req.id,
        "run_id": req.run_id,
        "trace_id": req.trace_id,
        "requester_id": req.requester_id,
        "approver_id": req.approver_id,
        "action_type": req.action_type,
        "payload_ref": req.payload_ref,
        "status": req.status,
        "decision_comment": req.decision_comment,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
    }


# ─── Agent Profile (P3.A.3) ──────────────────────────────────

@router.get("/profile")
async def get_agent_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentProfileRepository(db)
    profile = await repo.get_by_owner("user", user.id)
    if not profile:
        profile = await repo.create("user", user.id)
    return _serialize_profile(profile)


@router.put("/profile")
async def update_agent_profile(
    req: AgentProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentProfileRepository(db)
    profile = await repo.get_by_owner("user", user.id)
    if not profile:
        profile = await repo.create("user", user.id)

    update_kwargs = {}
    if req.name is not None:
        update_kwargs["name"] = req.name
    if req.system_policy is not None:
        update_kwargs["system_policy"] = req.system_policy
    if req.allowed_tools is not None:
        update_kwargs["allowed_tools_json"] = json.dumps(req.allowed_tools, ensure_ascii=False)
    if req.status is not None:
        if req.status not in ("active", "disabled"):
            raise HTTPException(400, "status must be 'active' or 'disabled'")
        update_kwargs["status"] = req.status
    if req.default_scope_type is not None:
        if req.default_scope_type not in ("personal", "workspace"):
            raise HTTPException(400, "default_scope_type must be 'personal' or 'workspace'")
        update_kwargs["default_scope_type"] = req.default_scope_type

    if update_kwargs:
        profile = await repo.update(profile, **update_kwargs)
    return _serialize_profile(profile)


# ─── Agent Authorization (P3.A.2) ────────────────────────────

@router.get("/profile/authorizations")
async def list_authorizations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile_repo = AgentProfileRepository(db)
    profile = await profile_repo.get_by_owner("user", user.id)
    if not profile:
        return []
    auth_repo = AgentAuthorizationRepository(db)
    auths = await auth_repo.list_by_agent(profile.id)
    return [_serialize_authorization(a) for a in auths]


@router.post("/profile/authorizations")
async def create_authorization(
    req: AuthorizationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile_repo = AgentProfileRepository(db)
    profile = await profile_repo.get_by_owner("user", user.id)
    if not profile:
        profile = await profile_repo.create("user", user.id)

    if req.scope_type not in ("workspace", "project", "personal"):
        raise HTTPException(400, "scope_type must be workspace/project/personal")

    auth_repo = AgentAuthorizationRepository(db)
    auth = await auth_repo.create(
        agent_id=profile.id,
        granted_by=user.id,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        permissions_json=json.dumps(req.permissions or [], ensure_ascii=False),
    )
    return _serialize_authorization(auth)


@router.delete("/profile/authorizations/{auth_id}")
async def revoke_authorization(
    auth_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile_repo = AgentProfileRepository(db)
    profile = await profile_repo.get_by_owner("user", user.id)
    if not profile:
        raise HTTPException(404, "Authorization not found")

    auth_repo = AgentAuthorizationRepository(db)
    auth = await auth_repo.get_by_id(auth_id)
    if not auth or auth.agent_id != profile.id:
        raise HTTPException(404, "Authorization not found")

    ok = await auth_repo.revoke(auth_id)
    if not ok:
        raise HTTPException(404, "Authorization not found")
    return {"status": "revoked"}


# ─── Agent Run (P3.B) ────────────────────────────────────────

@router.post("/runs")
async def create_agent_run(
    req: AgentRunCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile_repo = AgentProfileRepository(db)
    profile = await profile_repo.get_by_owner("user", user.id)
    if not profile:
        profile = await profile_repo.create("user", user.id)
    if profile.status != "active":
        raise HTTPException(400, "Agent is disabled")

    from app.repositories.workspace_repository import WorkspaceRepository
    from app.services.budget_guard import ensure_workspace_llm_allowed
    ws_repo = WorkspaceRepository(db)
    default_ws = await ws_repo.get_default()
    await ensure_workspace_llm_allowed(db, default_ws.id if default_ws else None)

    run_repo = AgentRunRepository(db)
    run = await run_repo.create(
        agent_id=profile.id,
        user_id=user.id,
        goal=req.goal,
        conversation_id=req.conversation_id,
    )
    return _serialize_run(run)


@router.get("/runs/{run_id}")
async def get_agent_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run_repo = AgentRunRepository(db)
    run = await run_repo.get_by_id(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if run.user_id != user.id:
        raise HTTPException(403, "Not your agent run")
    return _serialize_run_detail(run)


@router.get("/runs")
async def list_agent_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models.user import AgentRun
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.user_id == user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()
    return [_serialize_run(r) for r in runs]


@router.post("/runs/{run_id}/execute")
async def execute_agent_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """方案 A: 执行 Agent Run — 启动 Pi 子进程，返回完整结果。"""
    from app.services.agent_application_service import AgentApplicationService

    run_repo = AgentRunRepository(db)
    run = await run_repo.get_by_id(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if run.user_id != user.id:
        raise HTTPException(403, "Not your agent run")
    if run.status not in ("planning", "failed"):
        raise HTTPException(400, f"Run status is '{run.status}', cannot execute")

    profile_repo = AgentProfileRepository(db)
    profile = await profile_repo.get_by_id(run.agent_id)
    if not profile:
        raise HTTPException(404, "Agent profile not found")

    svc = AgentApplicationService(db)
    result = await svc.execute_via_pi_sync(run, profile, db)
    return result


@router.post("/runs/{run_id}/stream")
async def stream_agent_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """方案 A: 执行 Agent Run — SSE 流式返回 Pi 事件。"""
    from fastapi.responses import StreamingResponse
    from app.services.agent_application_service import AgentApplicationService

    run_repo = AgentRunRepository(db)
    run = await run_repo.get_by_id(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if run.user_id != user.id:
        raise HTTPException(403, "Not your agent run")
    if run.status not in ("planning", "failed"):
        raise HTTPException(400, f"Run status is '{run.status}', cannot execute")

    profile_repo = AgentProfileRepository(db)
    profile = await profile_repo.get_by_id(run.agent_id)
    if not profile:
        raise HTTPException(404, "Agent profile not found")

    from app.repositories.workspace_repository import WorkspaceRepository
    from app.services.budget_guard import ensure_workspace_llm_allowed
    ws_repo = WorkspaceRepository(db)
    default_ws = await ws_repo.get_default()
    await ensure_workspace_llm_allowed(db, default_ws.id if default_ws else None)

    svc = AgentApplicationService(db)

    async def event_generator():
        async for event in svc.execute_via_pi(run, profile, db):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ─── Tool Registry (P3.C.1) ─────────────────────────────────

@router.get("/tools")
async def list_agent_tools(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出所有可用工具。"""
    from app.services.tool_registry import get_tool_registry
    registry = get_tool_registry()
    profile_repo = AgentProfileRepository(db)
    profile = await profile_repo.get_by_owner("user", user.id)
    allowed = None
    if profile and profile.allowed_tools_json:
        try:
            allowed = json.loads(profile.allowed_tools_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return registry.list_schemas(allowed)


# ─── Approval (P3.D) ─────────────────────────────────────────

@router.get("/approvals")
async def list_pending_approvals(
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentApprovalRepository(db)
    # P4.Pre.4: 只返回当前用户作为审批人的待审批请求
    requests = await repo.list_pending(approver_id=user.id)
    return [_serialize_approval(r) for r in requests]


@router.post("/approvals/{request_id}/decide")
async def decide_approval(
    request_id: int,
    req: ApprovalDecision,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")

    repo = AgentApprovalRepository(db)
    approval = await repo.get_by_id(request_id)
    if not approval:
        raise HTTPException(404, "Approval request not found")
    if approval.status != "pending":
        raise HTTPException(400, f"Already {approval.status}")
    if approval.approver_id != user.id:
        raise HTTPException(403, "只有指定的审批人可以决策")

    approval = await repo.decide(approval, user.id, req.decision, req.comment)
    return _serialize_approval(approval)


# ─── MCP Config (P3.C) ──────────────────────────────────────

@router.get("/mcp/servers")
async def list_mcp_servers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models.user import MCPServerConfig
    result = await db.execute(select(MCPServerConfig).order_by(MCPServerConfig.created_at.desc()))
    servers = result.scalars().all()
    return [
        {
            "id": s.id, "workspace_id": s.workspace_id, "name": s.name,
            "server_type": s.server_type, "endpoint_ref": s.endpoint_ref,
            "status": s.status, "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in servers
    ]


@router.post("/mcp/servers")
async def create_mcp_server(
    req: MCPServerConfigCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import MCPServerConfig
    server = MCPServerConfig(
        name=req.name,
        server_type=req.server_type,
        endpoint_ref=req.endpoint_ref,
        workspace_id=req.workspace_id,
        metadata_json=req.metadata_json,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return {
        "id": server.id, "name": server.name, "server_type": server.server_type,
        "endpoint_ref": server.endpoint_ref, "status": server.status,
    }


@router.get("/mcp/servers/{server_id}/policies")
async def list_mcp_policies(
    server_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models.user import MCPToolPolicy
    result = await db.execute(
        select(MCPToolPolicy).where(MCPToolPolicy.server_id == server_id)
    )
    policies = result.scalars().all()
    return [
        {
            "id": p.id, "server_id": p.server_id, "tool_name": p.tool_name,
            "allowed_roles_json": p.allowed_roles_json,
            "requires_approval": p.requires_approval, "risk_level": p.risk_level,
        }
        for p in policies
    ]


@router.post("/mcp/servers/{server_id}/policies")
async def create_mcp_policy(
    server_id: int,
    req: MCPToolPolicyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import MCPToolPolicy
    policy = MCPToolPolicy(
        server_id=server_id,
        tool_name=req.tool_name,
        allowed_roles_json=json.dumps(req.allowed_roles or [], ensure_ascii=False),
        requires_approval=req.requires_approval,
        risk_level=req.risk_level,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return {
        "id": policy.id, "server_id": policy.server_id, "tool_name": policy.tool_name,
        "requires_approval": policy.requires_approval, "risk_level": policy.risk_level,
    }
