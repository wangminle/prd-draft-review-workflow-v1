"""P6.A.1: 成本统计服务 — 从 LLM JSONL 日志聚合写入 CostDailySummary 表。

设计：
- `aggregate_daily(date_str)`: 读取 llm_sessions.jsonl 中指定日期的条目，按 workspace/user/mode/model 分组聚合
- `get_daily_summary(filters)`: 查询已聚合的 CostDailySummary
- LlmSessionLogWriter 仍写 JSONL，本服务定期或按需聚合
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import CostDailySummary
from app.utils import now_cn

logger = logging.getLogger(__name__)


def infer_mode_from_model(model: str) -> str:
    """从 model ID 推断调用模式（JSONL 暂无 mode 字段时的兜底）。

    使用较精确的规则，避免 ``pipeline`` 等名称因包含 ``pi`` 被误判为 agent。
    """
    model_lower = (model or "").lower()
    if "review" in model_lower or "per-analysis" in model_lower:
        return "review"
    if "agent" in model_lower:
        return "agent"
    if (
        "pi-agent" in model_lower
        or model_lower.startswith("pi-")
        or model_lower.endswith("-pi")
        or "/pi-" in model_lower
        or "-pi-" in model_lower
    ):
        return "agent"
    return "chat"


class CostStatsService:
    """P6.A.1: 成本统计服务。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def aggregate_daily(self, date_str: str | None = None) -> int:
        """从 llm_sessions.jsonl 聚合指定日期的 LLM 调用统计。

        Args:
            date_str: YYYY-MM-DD 格式，默认为今天

        Returns:
            聚合写入的行数
        """
        if date_str is None:
            date_str = now_cn().strftime("%Y-%m-%d")

        # 读取 JSONL 日志
        log_path = self._get_llm_log_path()
        if not log_path.exists():
            logger.info("[COST] LLM 日志文件不存在，跳过聚合")
            return 0

        # 聚合字典: (workspace_id, user_id, mode, model_id) → stats
        agg: dict[tuple, dict] = {}

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # 过滤日期
                    ts = entry.get("timestamp", "")
                    if not ts.startswith(date_str):
                        continue

                    model = entry.get("model", "unknown")
                    usage = entry.get("usage") or {}
                    elapsed_ms = entry.get("elapsed_ms") or 0
                    input_tokens = usage.get("prompt_tokens", 0) or 0
                    output_tokens = usage.get("completion_tokens", 0) or 0

                    # BUG-077：JSONL 暂无 workspace_id/user_id/mode，mode 由 model ID 推断
                    entry_mode = infer_mode_from_model(model)
                    key = (None, None, entry_mode, model)
                    if key not in agg:
                        agg[key] = {
                            "call_count": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "embedding_tokens": 0,
                            "total_elapsed_ms": 0,
                        }
                    agg[key]["call_count"] += 1
                    agg[key]["input_tokens"] += input_tokens
                    agg[key]["output_tokens"] += output_tokens
                    agg[key]["total_elapsed_ms"] += elapsed_ms or 0

        except Exception as e:
            logger.error(f"[COST] 读取 LLM 日志失败: {e}")
            return 0

        if not agg:
            logger.info(f"[COST] {date_str} 无 LLM 调用记录")
            return 0

        # 写入/更新 CostDailySummary
        rows = 0
        for (workspace_id, user_id, mode, model_id), stats in agg.items():
            # 检查是否已存在
            workspace_filter = (
                CostDailySummary.workspace_id.is_(None)
                if workspace_id is None
                else CostDailySummary.workspace_id == workspace_id
            )
            user_filter = (
                CostDailySummary.user_id.is_(None)
                if user_id is None
                else CostDailySummary.user_id == user_id
            )
            existing = await self._db.execute(
                select(CostDailySummary).where(
                    CostDailySummary.date == date_str,
                    CostDailySummary.model_id == model_id,
                    CostDailySummary.mode == mode,
                    workspace_filter,
                    user_filter,
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                row.call_count = stats["call_count"]
                row.input_tokens = stats["input_tokens"]
                row.output_tokens = stats["output_tokens"]
                row.embedding_tokens = stats["embedding_tokens"]
                row.total_elapsed_ms = stats["total_elapsed_ms"]
            else:
                row = CostDailySummary(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    mode=mode,
                    date=date_str,
                    model_id=model_id,
                    call_count=stats["call_count"],
                    input_tokens=stats["input_tokens"],
                    output_tokens=stats["output_tokens"],
                    embedding_tokens=stats["embedding_tokens"],
                    total_elapsed_ms=stats["total_elapsed_ms"],
                )
                self._db.add(row)
            rows += 1

        await self._db.flush()
        logger.info(f"[COST] {date_str} 聚合完成: {rows} 行")
        return rows

    async def get_summary(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        workspace_id: int | None = None,
        mode: str | None = None,
    ) -> list[dict]:
        """查询已聚合的成本统计。"""
        query = select(CostDailySummary).order_by(CostDailySummary.date.desc())
        if start_date:
            query = query.where(CostDailySummary.date >= start_date)
        if end_date:
            query = query.where(CostDailySummary.date <= end_date)
        if workspace_id:
            query = query.where(CostDailySummary.workspace_id == workspace_id)
        if mode:
            query = query.where(CostDailySummary.mode == mode)

        result = await self._db.execute(query.limit(100))
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "workspace_id": r.workspace_id,
                "user_id": r.user_id,
                "mode": r.mode,
                "date": r.date,
                "model_id": r.model_id,
                "call_count": r.call_count,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "embedding_tokens": r.embedding_tokens,
                "total_elapsed_ms": r.total_elapsed_ms,
            }
            for r in rows
        ]

    async def get_total_stats(self) -> dict:
        """获取汇总统计。"""
        result = await self._db.execute(
            select(
                func.sum(CostDailySummary.call_count),
                func.sum(CostDailySummary.input_tokens),
                func.sum(CostDailySummary.output_tokens),
                func.sum(CostDailySummary.embedding_tokens),
                func.sum(CostDailySummary.total_elapsed_ms),
            )
        )
        row = result.one()
        return {
            "total_calls": row[0] or 0,
            "total_input_tokens": row[1] or 0,
            "total_output_tokens": row[2] or 0,
            "total_embedding_tokens": row[3] or 0,
            "total_elapsed_ms": row[4] or 0,
        }

    def _get_llm_log_path(self) -> Path:
        """获取 LLM 日志文件路径。"""
        from app.runtime_paths import get_runtime_root
        return get_runtime_root() / "logs" / "llm_sessions.jsonl"
