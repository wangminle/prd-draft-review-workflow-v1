"""ReviewTaskRepository — 审查任务、逐篇分析、体系审查的结构化持久化。

职责边界：
- 结构化数据查询和写入（ReviewTask, DocAnalysis, SystemReview）
- 不负责文件系统访问、日志落盘、HTTPException
- 事务边界由 router/service 控制，方法内只 flush 不 commit
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import DocAnalysis, ReviewTask, SystemReview
from app.services.review_helpers import extract_pm_assessment_payload
from app.utils import now_cn

_REQUIRED_EXPERT_REVIEW_RULE_KEYS = frozenset([
    "scope_realism",
    "boundary_completeness",
    "structured_entitlements",
    "user_facing_naming",
    "copy_consistency",
    "phased_tech_plan",
])

logger = logging.getLogger(__name__)


# ── Data classes for creation/patch payloads ──


@dataclass
class NewReviewTask:
    project_id: int
    mode: str
    context_version: int
    model_id: str | None
    created_by: int | None
    step_statuses: str
    step_details: str
    total_docs: int


@dataclass
class TaskProgressPatch:
    """Partial update for task progress during pipeline execution."""
    status: str | None = None
    current_step: int | None = None
    completed_docs: int | None = None
    step_statuses: str | None = None
    step_details: str | None = None


@dataclass
class DocAnalysisPayload:
    document_id: int
    task_id: int
    core_problem: str | None = None
    category: str | None = None
    boundary_in: str | None = None
    boundary_out: str | None = None
    spec_violations: str | None = None
    quality_score: float | None = None
    full_analysis: str | None = None


@dataclass
class SystemReviewPayload:
    task_id: int
    project_id: int
    business_value: str | None = None
    architecture: str | None = None
    competition: str | None = None
    product_strategy: str | None = None
    tech_evolution: str | None = None
    pm_growth: str | None = None
    action_plan: str | None = None
    pm_scores: str | None = None


class ReviewTaskRepository:
    """审查任务、逐篇分析、体系审查的结构化持久化层。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    # ── Task CRUD ──

    async def create_task(self, data: NewReviewTask) -> ReviewTask:
        task = ReviewTask(
            project_id=data.project_id,
            mode=data.mode,
            status="pending",
            total_docs=data.total_docs,
            context_version=data.context_version,
            model_id=data.model_id,
            created_by=data.created_by,
            step_statuses=data.step_statuses,
            step_details=data.step_details,
        )
        self._db.add(task)
        await self._db.flush()
        await self._db.refresh(task)
        return task

    async def get_task(self, task_id: int) -> ReviewTask | None:
        result = await self._db.execute(
            select(ReviewTask).where(ReviewTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_task_with_owner_check(
        self, task_id: int, project_id: int, user_id: int
    ) -> ReviewTask | None:
        result = await self._db.execute(
            select(ReviewTask).where(
                ReviewTask.id == task_id,
                ReviewTask.project_id == project_id,
            )
        )
        task = result.scalar_one_or_none()
        if task is None or task.created_by != user_id:
            return None
        return task

    async def find_active_review_task(
        self,
        project_id: int,
        mode: str,
        document_ids: list[int],
        historical_document_ids: list[int] | None = None,
    ) -> ReviewTask | None:
        result = await self._db.execute(
            select(ReviewTask)
            .where(
                ReviewTask.project_id == project_id,
                ReviewTask.mode == mode,
                ReviewTask.status.in_(("pending", "running")),
            )
            .order_by(ReviewTask.created_at.desc())
        )
        for task in result.scalars().all():
            if self._is_same_active_review_scope(
                task, mode, document_ids, historical_document_ids
            ):
                return task
        return None

    async def update_task_progress(self, task_id: int, patch: TaskProgressPatch) -> ReviewTask | None:
        task = await self.get_task(task_id)
        if task is None:
            return None
        if patch.status is not None:
            task.status = patch.status
        if patch.current_step is not None:
            task.current_step = patch.current_step
        if patch.completed_docs is not None:
            task.completed_docs = patch.completed_docs
        if patch.step_statuses is not None:
            task.step_statuses = patch.step_statuses
        if patch.step_details is not None:
            task.step_details = patch.step_details
        await self._db.flush()
        return task

    async def mark_task_completed(
        self, task_id: int, *, final_status: str = "completed", completed_at: datetime | None = None
    ) -> ReviewTask | None:
        task = await self.get_task(task_id)
        if task is None:
            return None
        task.status = final_status
        task.completed_at = completed_at or now_cn()
        await self._db.flush()
        return task

    async def mark_task_failed(self, task_id: int) -> ReviewTask | None:
        task = await self.get_task(task_id)
        if task is None:
            return None
        task.status = "failed"
        task.completed_at = now_cn()
        await self._db.flush()
        return task

    async def mark_task_cancelled(self, task_id: int) -> ReviewTask | None:
        task = await self.get_task(task_id)
        if task is None:
            return None
        task.status = "cancelled"
        await self._db.flush()
        return task

    # ── DocAnalysis ──

    async def save_doc_analysis(self, payload: DocAnalysisPayload) -> DocAnalysis:
        da = DocAnalysis(
            document_id=payload.document_id,
            task_id=payload.task_id,
            core_problem=payload.core_problem,
            category=payload.category,
            boundary_in=payload.boundary_in,
            boundary_out=payload.boundary_out,
            spec_violations=payload.spec_violations,
            quality_score=payload.quality_score,
            full_analysis=payload.full_analysis,
        )
        self._db.add(da)
        await self._db.flush()
        return da

    async def find_cached_analyses(
        self, doc_ids: list[int], context_version: int | None = None
    ) -> dict[int, DocAnalysis]:
        query = select(DocAnalysis).where(DocAnalysis.document_id.in_(doc_ids))
        if context_version is not None:
            query = query.join(ReviewTask, DocAnalysis.task_id == ReviewTask.id).where(
                ReviewTask.context_version == context_version
            )
        query = query.order_by(DocAnalysis.id.desc())
        result = await self._db.execute(query)
        all_analyses = result.scalars().all()
        cache: dict[int, DocAnalysis] = {}
        for a in all_analyses:
            if not self._analysis_has_required_expert_review(a):
                logger.info(
                    "Cached analysis skipped for doc %d because expert_review is missing or incomplete",
                    a.document_id,
                )
                continue
            if a.document_id not in cache:
                cache[a.document_id] = a
        return cache

    # ── SystemReview ──

    async def save_system_review(self, payload: SystemReviewPayload) -> SystemReview:
        sr = SystemReview(
            task_id=payload.task_id,
            project_id=payload.project_id,
            business_value=payload.business_value,
            architecture=payload.architecture,
            competition=payload.competition,
            product_strategy=payload.product_strategy,
            tech_evolution=payload.tech_evolution,
            pm_growth=payload.pm_growth,
            action_plan=payload.action_plan,
            pm_scores=payload.pm_scores,
        )
        self._db.add(sr)
        await self._db.flush()
        return sr

    async def find_cached_system_review(
        self,
        project_id: int,
        doc_ids: list[int] | None = None,
        context_version: int | None = None,
        model_id: str | None = None,
    ) -> SystemReview | None:
        expected_doc_ids = set(doc_ids) if doc_ids is not None else None
        query = select(SystemReview).where(SystemReview.project_id == project_id)
        if context_version is not None or model_id is not None:
            query = query.join(ReviewTask, SystemReview.task_id == ReviewTask.id)
            if context_version is not None:
                query = query.where(ReviewTask.context_version == context_version)
            if model_id is not None:
                query = query.where(ReviewTask.model_id == model_id)
        query = query.order_by(SystemReview.id.desc())
        result = await self._db.execute(query)
        rows = result.scalars().all()
        for sr in rows:
            if not self._system_review_has_complete_dimensions(sr):
                continue
            if expected_doc_ids is not None:
                doc_result = await self._db.execute(
                    select(DocAnalysis.document_id).where(DocAnalysis.task_id == sr.task_id)
                )
                cached_doc_ids = set(doc_result.scalars().all())
                if cached_doc_ids != expected_doc_ids:
                    continue
            return sr
        return None

    # ── Internal helpers ──

    def _is_same_active_review_scope(
        self,
        task: ReviewTask,
        mode: str,
        document_ids: list[int],
        historical_document_ids: list[int] | None = None,
    ) -> bool:
        if getattr(task, "mode", None) != mode:
            return False
        artifacts = self._extract_task_artifacts(task)
        task_doc_ids = artifacts.get("document_ids") or []
        task_historical_ids = artifacts.get("historical_document_ids") or []
        historical_document_ids = historical_document_ids or []
        return (
            sorted(int(doc_id) for doc_id in task_doc_ids) == sorted(int(doc_id) for doc_id in document_ids)
            and sorted(int(doc_id) for doc_id in task_historical_ids) == sorted(int(doc_id) for doc_id in historical_document_ids)
        )

    @staticmethod
    def _extract_task_artifacts(task: ReviewTask) -> dict:
        try:
            return json.loads(task.step_details) if task.step_details else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _analysis_has_required_expert_review(analysis: DocAnalysis) -> bool:
        if not analysis.full_analysis:
            return False
        try:
            parsed = json.loads(analysis.full_analysis)
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(parsed, dict):
            return False
        expert_review = parsed.get("expert_review")
        if not expert_review or not isinstance(expert_review, dict):
            return False
        summary = str(expert_review.get("summary") or "").strip()
        if not summary:
            return False
        checks = expert_review.get("checks")
        if not checks or not isinstance(checks, list):
            return False
        seen_keys = {
            check.get("rule_key")
            for check in checks
            if isinstance(check, dict)
        }
        return _REQUIRED_EXPERT_REVIEW_RULE_KEYS.issubset(seen_keys)

    @staticmethod
    def _system_review_has_complete_dimensions(sr: SystemReview) -> bool:
        required_fields = [
            "business_value",
            "architecture",
            "competition",
            "product_strategy",
            "tech_evolution",
            "action_plan",
        ]
        if not all(getattr(sr, field, None) for field in required_fields):
            return False
        if not getattr(sr, "pm_scores", None):
            return False
        try:
            pm_scores = json.loads(sr.pm_scores)
        except (TypeError, json.JSONDecodeError):
            return False
        return extract_pm_assessment_payload(pm_scores) is not None