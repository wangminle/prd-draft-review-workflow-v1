"""Workspace 知识源数据模型：团队共享资料。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.user import Base
from app.utils import now_cn

VALID_MEMBER_ROLES = ("owner", "admin", "member", "viewer")
VALID_WORKSPACE_STATUSES = ("active", "archived")
VALID_SOURCE_TYPES = ("upload", "lark_url", "api")
VALID_SOURCE_STATUSES = ("active", "archived", "processing", "failed")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    sources = relationship("KnowledgeSource", back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User")


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="upload")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(200))
    file_id: Mapped[str | None] = mapped_column(String(12))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    workspace = relationship("Workspace", back_populates="sources")
    owner = relationship("User")
    project_refs = relationship("ProjectSourceRef", back_populates="source", cascade="all, delete-orphan")
    documents = relationship("KnowledgeDocument", back_populates="source", cascade="all, delete-orphan")


class ProjectSourceRef(Base):
    __tablename__ = "project_source_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(20), nullable=False, default="context")
    snapshot_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    project = relationship("ReviewProject", back_populates="source_refs")
    source = relationship("KnowledgeSource", back_populates="project_refs")