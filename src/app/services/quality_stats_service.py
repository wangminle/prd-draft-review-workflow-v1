"""P6.A.2: 质量统计服务 — 按项目统计评分趋势、高频缺失章节等。

设计：
- `aggregate_weekly(week_start)`: 聚合指定周的审查质量数据
- `get_weekly_summary(filters)`: 查询已聚合的 QualityWeeklySummary
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import QualityWeeklySummary, ReviewTask, ReviewProject
from app.utils import now_cn

logger = logging.getLogger(__name__)


class QualityStatsService:
    """P6.A.2: 质量统计服务。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def aggregate_weekly(self, week_start: str | None = None) -> int:
        """聚合指定周的审查质量统计。

        Args:
            week_start: YYYY-MM-DD 格式（周一），默认为本周

        Returns:
            聚合写入的行数
        """
        if week_start is None:
            today = now_cn()
            week_start_date = today - timedelta(days=today.weekday())
            week_start = week_start_date.strftime("%Y-%m-%d")

        # 计算本周结束日期
        start = datetime.strptime(week_start, "%Y-%m-%d")
        end = start + timedelta(days=6)
        end_str = end.strftime("%Y-%m-%d")

        # 查询本周审查任务统计
        from app.models.review import DocAnalysis
        result = await self._db.execute(
            select(DocAnalysis).where(
                DocAnalysis.created_at >= start,
                DocAnalysis.created_at <= end,
            )
        )
        analyses = result.scalars().all()

        total_reviews = len(analyses)
        avg_score = 0.0
        if total_reviews > 0:
            scores = [a.quality_score for a in analyses if a.quality_score is not None]
            if scores:
                avg_score = sum(scores) / len(scores)

        # 写入/更新 QualityWeeklySummary
        existing = await self._db.execute(
            select(QualityWeeklySummary).where(
                QualityWeeklySummary.week_start == week_start,
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            row.total_reviews = total_reviews
            row.avg_score = avg_score
        else:
            row = QualityWeeklySummary(
                workspace_id=None,
                week_start=week_start,
                avg_score=avg_score,
                total_reviews=total_reviews,
            )
            self._db.add(row)

        await self._db.flush()
        logger.info(f"[QUALITY] {week_start} 聚合完成: {total_reviews} reviews")
        return 1

    async def get_summary(
        self,
        start_week: str | None = None,
        end_week: str | None = None,
    ) -> list[dict]:
        """查询已聚合的质量统计。"""
        query = select(QualityWeeklySummary).order_by(QualityWeeklySummary.week_start.desc())
        if start_week:
            query = query.where(QualityWeeklySummary.week_start >= start_week)
        if end_week:
            query = query.where(QualityWeeklySummary.week_start <= end_week)

        result = await self._db.execute(query.limit(52))
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "workspace_id": r.workspace_id,
                "week_start": r.week_start,
                "avg_score": r.avg_score,
                "total_reviews": r.total_reviews,
                "high_freq_missing_sections": r.high_freq_missing_sections,
                "high_freq_boundary_questions": r.high_freq_boundary_questions,
                "issue_close_rate": r.issue_close_rate,
            }
            for r in rows
        ]
