from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class DocumentInfo(BaseModel):
    id: int
    filename: str
    file_size: int | None
    md_path: str | None
    category: str | None
    version: str | None
    document_type: str = "requirement"
    status: str = "uploaded"
    created_at: datetime | None = None


class ProjectInfo(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    description: str | None
    workspace_id: int | None = None
    doc_count: int = 0
    report_count: int = 0
    context_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    documents: list[DocumentInfo] | None = None


class StartReviewRequest(BaseModel):
    mode: str = Field(default="quick", pattern="^(quick|review|pm|insight|full|draft)$")
    document_ids: list[int] | None = None
    model_id: str | None = None
    force_reanalysis: bool = False
    thinking_level: str | None = None


class TaskInfo(BaseModel):
    task_id: int
    status: str
    mode: str
    current_step: int
    total_docs: int
    completed_docs: int
    context_version: int
    document_ids: list[int] | None = None
    estimated_seconds: int | None = None


class ProgressEvent(BaseModel):
    task_status: str
    current_step: int
    step_statuses: dict | None = None
    step_details: dict | None = None
    doc_progress: list | None = None


class AnalysisInfo(BaseModel):
    id: int
    document_id: int
    filename: str | None = None
    core_problem: str | None
    category: str | None
    boundary_in: list | None
    boundary_out: list | None
    boundary_issues: list | None = None
    key_points: dict | None = None
    resolution_tracking: list | None = None
    expert_review: dict | None = None
    spec_violations: list | None = None
    quality_score: float | None
    full_analysis: dict | None = None


class ReviewReport(BaseModel):
    task_id: int
    mode: str
    context_version: int
    analyses: list[AnalysisInfo] = []
    system_review: dict | None = None
    pm_assessment: dict | None = None
    insights: dict | None = None
    prd_draft: dict | None = None


class ContextUpdate(BaseModel):
    specifications: list | None = None
    required_sections: list | None = None
    scoring_overrides: dict | None = None
    category_overrides: dict | None = None
    professional_guidance: list | None = None
    change_log: str | None = None


class ContextInfo(BaseModel):
    context_id: int
    version: int
    is_active: bool
    updated_at: datetime | None
    context_data: dict | None = None


class PromptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str | None = None
    content: str = Field(..., min_length=1)


class PromptInfo(BaseModel):
    id: int
    name: str
    description: str | None
    version: int
    is_active: bool
