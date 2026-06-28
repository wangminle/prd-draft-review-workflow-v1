"""P6: 治理与运营 — 成本统计、质量统计、Skill/Prompt 治理、配额管理。"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.review import CostDailySummary, QualityWeeklySummary, WorkspaceBudget

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── P6.A: 成本与质量仪表盘 API ──────────────────────────────


@router.get("/governance/cost/daily")
async def get_cost_daily(
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.A.1: 查询每日成本统计。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.services.cost_stats_service import CostStatsService
    service = CostStatsService(db)
    return await service.get_summary(start_date=start_date, end_date=end_date)


@router.post("/governance/cost/aggregate")
async def aggregate_cost_daily(
    date_str: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.A.1: 手动触发成本聚合。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.services.cost_stats_service import CostStatsService
    service = CostStatsService(db)
    rows = await service.aggregate_daily(date_str)
    await db.commit()
    return {"rows": rows}


@router.get("/governance/cost/total")
async def get_cost_total(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.A.1: 汇总成本统计。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.services.cost_stats_service import CostStatsService
    service = CostStatsService(db)
    return await service.get_total_stats()


@router.get("/governance/quality/weekly")
async def get_quality_weekly(
    start_week: str | None = None,
    end_week: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.A.2: 查询每周质量统计。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.services.quality_stats_service import QualityStatsService
    service = QualityStatsService(db)
    return await service.get_summary(start_week=start_week, end_week=end_week)


# ─── P6.B: Skill/Prompt/Agent 治理 ────────────────────────────


@router.get("/governance/skills")
async def list_skill_packages(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.B.2: 列出 SkillPackage（基于 SkillConfig 扩展）。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.models.user import SkillConfig
    result = await db.execute(
        select(SkillConfig).order_by(SkillConfig.id)
    )
    skills = result.scalars().all()
    return [
        {
            "id": s.id,
            "skill_id": s.skill_id,
            "name": s.name,
            "description": s.description,
            "status": s.status,
            "version": s.version,
            "local_path": s.local_path,
            "is_builtin": s.is_builtin,
        }
        for s in skills
    ]


@router.put("/governance/skills/{skill_db_id}/status")
async def update_skill_status(
    skill_db_id: int,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.B.2: 更新 Skill 状态（published/draft/deprecated）。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.models.user import SkillConfig
    result = await db.execute(select(SkillConfig).where(SkillConfig.id == skill_db_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(404, "Skill 不存在")

    new_status = body.get("status")
    valid_statuses = ("active", "inactive", "published", "draft", "deprecated")
    if new_status not in valid_statuses:
        raise HTTPException(422, f"无效状态，允许值: {', '.join(valid_statuses)}")

    skill.status = new_status
    await db.commit()
    return {"id": skill.id, "status": skill.status}


@router.put("/governance/agent/{agent_id}/archive")
async def archive_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.B.3: Agent 退役（disabled→archived），需检查无活跃运行。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.models.user import AgentProfile, AgentRun
    result = await db.execute(
        select(AgentProfile).where(AgentProfile.id == agent_id).with_for_update()
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "Agent 不存在")
    if profile.status != "disabled":
        raise HTTPException(422, "只有 disabled 状态的 Agent 才能退役")

    # BUG-089: 行锁内再次检查活跃运行，避免 TOCTOU
    active_runs = await db.execute(
        select(AgentRun).where(
            AgentRun.agent_id == agent_id,
            AgentRun.status.in_(["planning", "running"]),
        )
    )
    if active_runs.scalars().first():
        raise HTTPException(422, "Agent 有活跃运行，无法退役")

    profile.status = "archived"
    await db.commit()
    return {"id": profile.id, "status": profile.status}


@router.get("/governance/agents")
async def list_governance_agents(
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.B.3: 列出 Agent Profile（治理页退役管理）。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.models.user import AgentProfile
    query = select(AgentProfile).order_by(AgentProfile.updated_at.desc())
    if status:
        query = query.where(AgentProfile.status == status)
    result = await db.execute(query.limit(100))
    profiles = result.scalars().all()
    return [
        {
            "id": p.id,
            "owner_type": p.owner_type,
            "owner_id": p.owner_id,
            "name": p.name,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in profiles
    ]


@router.get("/governance/permissions/audit")
async def get_permissions_audit(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.B.4: 权限审计报告 — workspace 角色变更 + Agent 授权变更。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    from app.models.workspace import WorkspaceMember
    from app.models.user import AgentAuthorization

    # Workspace 角色变更
    members_result = await db.execute(select(WorkspaceMember))
    members = members_result.scalars().all()

    # Agent 授权变更
    auths_result = await db.execute(select(AgentAuthorization))
    auths = auths_result.scalars().all()

    return {
        "workspace_members": [
            {"user_id": m.user_id, "workspace_id": m.workspace_id, "role": m.role, "status": m.status}
            for m in members
        ],
        "agent_authorizations": [
            {"id": a.id, "agent_id": a.agent_id, "scope_type": a.scope_type, "granted_by": a.granted_by, "permissions": a.permissions_json}
            for a in auths
        ],
    }


# ─── P6.C: Workspace 配额 ────────────────────────────────────


class BudgetUpdate(BaseModel):
    monthly_token_limit: int | None = Field(default=None, ge=0)
    monthly_cost_limit: float | None = Field(default=None, ge=0)
    warning_threshold_pct: float = Field(default=80.0, ge=0, le=100)
    hard_limit_action: str = "notify"  # notify/block


@router.get("/governance/budget/{workspace_id}")
async def get_budget(
    workspace_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.C.1: 获取 Workspace 配额。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    # BUG-074 修复：验证 workspace 存在性
    from app.models.workspace import Workspace
    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    if not ws_result.scalar_one_or_none():
        raise HTTPException(404, "Workspace 不存在")

    result = await db.execute(
        select(WorkspaceBudget).where(WorkspaceBudget.workspace_id == workspace_id)
    )
    budget = result.scalar_one_or_none()
    from app.services.budget_guard import get_monthly_token_usage
    current_month_tokens = await get_monthly_token_usage(db, workspace_id)

    if not budget:
        return {
            "id": None,
            "workspace_id": workspace_id,
            "monthly_token_limit": None,
            "monthly_cost_limit": None,
            "warning_threshold_pct": 80.0,
            "hard_limit_action": "notify",
            "current_month_tokens": current_month_tokens,
        }
    return {
        "id": budget.id,
        "workspace_id": budget.workspace_id,
        "monthly_token_limit": budget.monthly_token_limit,
        "monthly_cost_limit": budget.monthly_cost_limit,
        "warning_threshold_pct": budget.warning_threshold_pct,
        "hard_limit_action": budget.hard_limit_action,
        "current_month_tokens": current_month_tokens,
    }


@router.put("/governance/budget/{workspace_id}")
async def update_budget(
    workspace_id: int,
    body: BudgetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P6.C.3: 设置 Workspace 配额。"""
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")

    if body.hard_limit_action not in ("notify", "block"):
        raise HTTPException(422, "hard_limit_action 必须是 'notify' 或 'block'")

    # BUG-074 修复：验证 workspace 存在性，防止创建孤儿 budget 记录
    from app.models.workspace import Workspace
    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    if not ws_result.scalar_one_or_none():
        raise HTTPException(404, "Workspace 不存在")

    result = await db.execute(
        select(WorkspaceBudget).where(WorkspaceBudget.workspace_id == workspace_id)
    )
    budget = result.scalar_one_or_none()

    if budget:
        budget.monthly_token_limit = body.monthly_token_limit
        budget.monthly_cost_limit = body.monthly_cost_limit
        budget.warning_threshold_pct = body.warning_threshold_pct
        budget.hard_limit_action = body.hard_limit_action
    else:
        budget = WorkspaceBudget(
            workspace_id=workspace_id,
            monthly_token_limit=body.monthly_token_limit,
            monthly_cost_limit=body.monthly_cost_limit,
            warning_threshold_pct=body.warning_threshold_pct,
            hard_limit_action=body.hard_limit_action,
        )
        db.add(budget)

    await db.commit()
    # BUG-073 修复：响应补充 id 字段
    return {
        "id": budget.id,
        "workspace_id": budget.workspace_id,
        "monthly_token_limit": budget.monthly_token_limit,
        "monthly_cost_limit": budget.monthly_cost_limit,
        "warning_threshold_pct": budget.warning_threshold_pct,
        "hard_limit_action": budget.hard_limit_action,
    }
