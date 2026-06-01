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
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    documents = relationship("ReviewDocument", back_populates="project", cascade="all, delete-orphan")
    contexts = relationship("ReviewContext", back_populates="project", cascade="all, delete-orphan")


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
