from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.models.user import Base
from app.utils import now_cn


class ReviewProject(Base):
    __tablename__ = "review_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    documents = relationship("ReviewDocument", back_populates="project", cascade="all, delete-orphan")
    contexts = relationship("ReviewContext", back_populates="project", cascade="all, delete-orphan")
    source_refs = relationship("ProjectSourceRef", back_populates="project", cascade="all, delete-orphan")


class ReviewDocument(Base):
    __tablename__ = "review_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1000))
    file_size: Mapped[int | None] = mapped_column(Integer)
    md_path: Mapped[str | None] = mapped_column(String(1000))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(50))
    version: Mapped[str | None] = mapped_column(String(30))
    document_type: Mapped[str] = mapped_column(String(20), default="requirement")
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    parent_document_id: Mapped[int | None] = mapped_column(ForeignKey("review_documents.id"), nullable=True)  # P4.A.6: 版本链
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    project = relationship("ReviewProject", back_populates="documents")
    analyses = relationship("DocAnalysis", back_populates="document", cascade="all, delete-orphan")


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    total_docs: Mapped[int] = mapped_column(Integer, default=0)
    completed_docs: Mapped[int] = mapped_column(Integer, default=0)
    context_version: Mapped[int] = mapped_column(Integer, default=1)
    model_id: Mapped[str | None] = mapped_column(String(30))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    step_statuses: Mapped[str | None] = mapped_column(Text)
    step_details: Mapped[str | None] = mapped_column(Text)

    analyses = relationship("DocAnalysis", back_populates="task", cascade="all, delete-orphan")
    system_review = relationship("SystemReview", back_populates="task", cascade="all, delete-orphan", uselist=False)


class DocAnalysis(Base):
    __tablename__ = "doc_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("review_documents.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"), nullable=False)
    core_problem: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(50))
    boundary_in: Mapped[str | None] = mapped_column(Text)
    boundary_out: Mapped[str | None] = mapped_column(Text)
    spec_violations: Mapped[str | None] = mapped_column(Text)
    # Note: boundary_in/boundary_out are stored as JSON strings ("[\"a\",\"b\"]"),
    # but the API schema exposes them as list | None. Serialization handles the conversion.
    quality_score: Mapped[float | None] = mapped_column(Float)
    full_analysis: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    document = relationship("ReviewDocument", back_populates="analyses")
    task = relationship("ReviewTask", back_populates="analyses")


class SystemReview(Base):
    __tablename__ = "system_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id"), nullable=False)
    business_value: Mapped[str | None] = mapped_column(Text)
    architecture: Mapped[str | None] = mapped_column(Text)
    competition: Mapped[str | None] = mapped_column(Text)
    product_strategy: Mapped[str | None] = mapped_column(Text)
    tech_evolution: Mapped[str | None] = mapped_column(Text)
    pm_growth: Mapped[str | None] = mapped_column(Text)
    action_plan: Mapped[str | None] = mapped_column(Text)
    pm_scores: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    task = relationship("ReviewTask", back_populates="system_review")


class ReviewContext(Base):
    __tablename__ = "review_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    change_log: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    context_data: Mapped[str] = mapped_column(Text, nullable=False)

    project = relationship("ReviewProject", back_populates="contexts")


class ReviewPrompt(Base):
    __tablename__ = "review_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)


# ─── P4: 协作审查数据模型 ────────────────────────────────────────


class ReviewRequest(Base):
    """P4.A.1: 协作审查请求 — ReviewProject 通过后的后置扩展（串联而非替代）。"""
    __tablename__ = "review_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    initiator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="initiated")  # initiated/pending_approval/approved/rejected/archived
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    project = relationship("ReviewProject", backref="review_requests")


class ReviewParticipant(Base):
    """P4.A.2: 协作审查参与者。角色：Reviewer/Approver/Observer。"""
    __tablename__ = "review_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("review_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # Reviewer/Approver/Observer
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active/inactive
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)


class ReviewRound(Base):
    """P4.A.3: 协作审查轮次 — 每轮记录完整提交包和审查员决策。"""
    __tablename__ = "review_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("review_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_snapshot_ref: Mapped[str | None] = mapped_column(String(200))  # 快照版本引用
    submitted_artifact_ref: Mapped[str | None] = mapped_column(String(200))  # 物料版本引用
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/approved/rejected
    decision_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


# ─── P4.B: 知识快照与产物模型 ─────────────────────────────────────


class KnowledgeSnapshot(Base):
    """P4.B.1: 知识快照 — 审查发起时的完整知识版本快照。"""
    __tablename__ = "knowledge_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("review_requests.id", ondelete="SET NULL"), index=True)
    source_refs_json: Mapped[str | None] = mapped_column(Text)  # JSON: [{source_id, version, snapshot_version}]
    chunk_refs_json: Mapped[str | None] = mapped_column(Text)  # JSON: [{document_id, chunk_ids, version}]
    prompt_version: Mapped[str | None] = mapped_column(String(30))
    skill_version: Mapped[str | None] = mapped_column(String(30))
    model_config_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)


class Artifact(Base):
    """P4.B.2: 审查产物 — 讲解稿/图示/动画等迭代产物，draft→confirmed 状态。"""
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)  # review_request/conversation
    object_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)  # html_presentation/svg_summary/mermaid_diagram/explanation_json
    content_json: Mapped[str | None] = mapped_column(Text)  # 产物内容（JSON 或 HTML）
    source_conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    source_snapshot_ref: Mapped[str | None] = mapped_column(String(200))
    template_version: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft/confirmed
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)
