"""ReviewPipelinePersistenceService — pipeline 运行中的任务状态和结果持久化编排。

职责边界：
- 组合 ReviewTaskRepository 的 write 方法
- 封装 step_statuses / step_details 的 JSON 读写
- 封装任务失败、完成、取消的标准化流程
- 不负责 SSE 通知、SkillRunner 调用、文件转换
- 事务边界由 router 控制（service 只 flush）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.review_task_repository import (
    DocAnalysisPayload,
    ReviewTaskRepository,
    SystemReviewPayload,
    TaskProgressPatch,
)
from app.utils import now_cn

logger = logging.getLogger(__name__)


@dataclass
class StepStatusUpdate:
    step_statuses: dict
    step_details: dict | None = None


class ReviewPipelinePersistenceService:
    """pipeline 运行中写入文档状态、analysis、system review、task progress。"""

    # ── Static helpers (no db needed, used by router thin wrappers) ──

    @staticmethod
    def merge_step_details_static(task, **updates) -> None:
        data = ReviewPipelinePersistenceService._extract_task_artifacts(task)
        data.update({k: v for k, v in updates.items() if v is not None})
        task.step_details = json.dumps(data, ensure_ascii=False)

    @staticmethod
    def parse_step_statuses(task) -> dict:
        try:
            return json.loads(task.step_statuses) if task.step_statuses else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _extract_task_artifacts(task) -> dict:
        try:
            return json.loads(task.step_details) if task.step_details else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = ReviewTaskRepository(db)

    async def load_task(self, task_id: int) -> object | None:
        return await self._repo.get_task(task_id)

    async def mark_running(self, task_id: int) -> StepStatusUpdate:
        task = await self._repo.get_task(task_id)
        if task is None:
            return None
        step_statuses = json.loads(task.step_statuses) if task.step_statuses else {}
        await self._repo.update_task_progress(task_id, TaskProgressPatch(status="running"))
        return StepStatusUpdate(step_statuses=step_statuses)

    async def start_step(self, task_id: int, step_idx: int, step_statuses: dict) -> TaskProgressPatch:
        step_statuses[str(step_idx)] = "running"
        patch = TaskProgressPatch(
            current_step=step_idx,
            step_statuses=json.dumps(step_statuses),
        )
        await self._repo.update_task_progress(task_id, patch)
        return patch

    async def complete_step(self, task_id: int, step_idx: int, step_statuses: dict) -> TaskProgressPatch:
        step_statuses[str(step_idx)] = "completed"
        patch = TaskProgressPatch(
            step_statuses=json.dumps(step_statuses),
        )
        await self._repo.update_task_progress(task_id, patch)
        return patch

    async def fail_step(self, task_id: int, step_idx: int, step_statuses: dict) -> TaskProgressPatch:
        step_statuses[str(step_idx)] = "failed"
        task = await self._repo.get_task(task_id)
        if task is None:
            return None
        task.status = "failed"
        task.completed_at = now_cn()
        task.step_statuses = json.dumps(step_statuses, ensure_ascii=False)
        await self._db.flush()
        return TaskProgressPatch(status="failed", step_statuses=json.dumps(step_statuses))

    async def complete_task(self, task_id: int, completed_docs: int, total_docs: int) -> TaskProgressPatch:
        final_status = "completed_with_warnings" if completed_docs < total_docs else "completed"
        task = await self._repo.get_task(task_id)
        if task is None:
            return None
        task.status = final_status
        task.completed_at = now_cn()
        task.completed_docs = completed_docs
        await self._db.flush()
        return TaskProgressPatch(status=final_status, completed_docs=completed_docs)

    async def fail_task(self, task_id: int) -> None:
        task = await self._repo.get_task(task_id)
        if task is None:
            return
        task.status = "failed"
        task.completed_at = now_cn()
        await self._db.flush()

    # ── Step details ──

    def merge_step_details(self, task, **updates) -> None:
        data = self._extract_task_artifacts(task)
        data.update({k: v for k, v in updates.items() if v is not None})
        task.step_details = json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _extract_task_artifacts(task) -> dict:
        try:
            return json.loads(task.step_details) if task.step_details else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    # ── Analysis & SystemReview ──

    async def save_cached_doc_analysis(self, cached_analysis, document_id: int, task_id: int, category: str | None = None) -> None:
        await self._repo.save_doc_analysis(DocAnalysisPayload(
            document_id=document_id,
            task_id=task_id,
            core_problem=cached_analysis.core_problem,
            category=category or cached_analysis.category,
            boundary_in=cached_analysis.boundary_in,
            boundary_out=cached_analysis.boundary_out,
            spec_violations=cached_analysis.spec_violations,
            quality_score=cached_analysis.quality_score,
            full_analysis=cached_analysis.full_analysis,
        ))

    async def save_new_doc_analysis(self, document_id: int, task_id: int, analysis: dict, doc_category: str | None = None) -> None:
        await self._repo.save_doc_analysis(DocAnalysisPayload(
            document_id=document_id,
            task_id=task_id,
            core_problem=analysis.get("core_problem"),
            category=analysis.get("category", doc_category),
            boundary_in=json.dumps(analysis.get("boundary_in", []), ensure_ascii=False) if isinstance(analysis.get("boundary_in"), list) else str(analysis.get("boundary_in", "")),
            boundary_out=json.dumps(analysis.get("boundary_out", []), ensure_ascii=False) if isinstance(analysis.get("boundary_out"), list) else str(analysis.get("boundary_out", "")),
            spec_violations=json.dumps(analysis.get("spec_violations", []), ensure_ascii=False) if isinstance(analysis.get("spec_violations"), list) else None,
            quality_score=analysis.get("quality_score"),
            full_analysis=json.dumps(analysis, ensure_ascii=False),
        ))

    async def save_cached_system_review(self, cached_sr, task_id: int, project_id: int) -> None:
        await self._repo.save_system_review(SystemReviewPayload(
            task_id=task_id,
            project_id=project_id,
            business_value=cached_sr.business_value,
            architecture=cached_sr.architecture,
            competition=cached_sr.competition,
            product_strategy=cached_sr.product_strategy,
            tech_evolution=cached_sr.tech_evolution,
            pm_growth=cached_sr.pm_growth,
            action_plan=cached_sr.action_plan,
            pm_scores=cached_sr.pm_scores,
        ))

    async def save_new_system_review(self, merged: dict, pm_scores, task_id: int, project_id: int) -> None:
        await self._repo.save_system_review(SystemReviewPayload(
            task_id=task_id,
            project_id=project_id,
            business_value=json.dumps(merged.get("business_value"), ensure_ascii=False) if merged.get("business_value") else None,
            architecture=json.dumps(merged.get("architecture"), ensure_ascii=False) if merged.get("architecture") else None,
            competition=json.dumps(merged.get("competition"), ensure_ascii=False) if merged.get("competition") else None,
            product_strategy=json.dumps(merged.get("product_strategy"), ensure_ascii=False) if merged.get("product_strategy") else None,
            tech_evolution=json.dumps(merged.get("tech_evolution"), ensure_ascii=False) if merged.get("tech_evolution") else None,
            pm_growth=json.dumps(merged.get("pm_growth"), ensure_ascii=False) if merged.get("pm_growth") else None,
            action_plan=json.dumps(merged.get("action_plan"), ensure_ascii=False) if merged.get("action_plan") else None,
            pm_scores=json.dumps(pm_scores, ensure_ascii=False) if pm_scores else None,
        ))