"""Workspace 月度配额运行时拦截 — P6.C.1"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import CostDailySummary, WorkspaceBudget
from app.utils import now_cn

logger = logging.getLogger(__name__)


async def get_monthly_token_usage(db: AsyncSession, workspace_id: int) -> int:
    """统计 workspace 当月 token 用量（input + output）。"""
    month_prefix = now_cn().strftime("%Y-%m")
    result = await db.execute(
        select(
            func.coalesce(
                func.sum(CostDailySummary.input_tokens + CostDailySummary.output_tokens),
                0,
            )
        ).where(
            CostDailySummary.date.like(f"{month_prefix}-%"),
            # BUG-109: 只统计该 workspace 的专属行，不含 workspace_id IS NULL 的全局汇总行。
            # 全局行会被重复计入每个 workspace，导致 current_month_tokens 偏大、
            # ensure_workspace_llm_allowed 在 block 模式下误封未超限的 workspace。
            CostDailySummary.workspace_id == workspace_id,
        )
    )
    return int(result.scalar_one() or 0)


async def ensure_workspace_llm_allowed(db: AsyncSession, workspace_id: int | None) -> None:
    """若 workspace 配额已超限且 hard_limit_action=block，则拒绝 LLM/Agent 调用。"""
    if workspace_id is None:
        return

    result = await db.execute(
        select(WorkspaceBudget).where(WorkspaceBudget.workspace_id == workspace_id)
    )
    budget = result.scalar_one_or_none()
    if not budget or budget.monthly_token_limit is None:
        return
    if budget.hard_limit_action != "block":
        return

    usage = await get_monthly_token_usage(db, workspace_id)
    if usage >= budget.monthly_token_limit:
        logger.warning(
            "budget_guard.block workspace_id=%s usage=%s limit=%s",
            workspace_id, usage, budget.monthly_token_limit,
        )
        raise HTTPException(
            429,
            f"团队本月 token 配额已用尽（{usage}/{budget.monthly_token_limit}），请联系管理员",
        )
