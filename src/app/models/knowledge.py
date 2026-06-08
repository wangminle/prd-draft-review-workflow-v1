"""知识库文档与切块数据模型：资料解析后的结构化存储。

KnowledgeDocument: 一个 KnowledgeSource 对应一个 KnowledgeDocument，
                   记录文档级元信息（章节结构、页码、段落数等）。

KnowledgeChunk:    一个 Document 切分成多个 Chunk，
                   每个 Chunk 保留来源追溯信息（section/source_ref），
                   embedding_status 追踪异步嵌入进度。

RetrievalLog:      检索请求日志，记录 query、命中数、延迟、降级原因等。
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.user import Base
from app.utils import now_cn

VALID_EMBEDDING_STATUSES = ("pending", "done", "failed")
VALID_ANSWER_OBJECT_TYPES = ("retrieval", "chat", "review")
VALID_ANSWER_RATINGS = ("helpful", "unhelpful")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("source_id", name="uq_knowledge_doc_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    filename: Mapped[str | None] = mapped_column(String(200))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_cn, onupdate=now_cn
    )

    # relationships
    source = relationship("KnowledgeSource", back_populates="documents")
    chunks = relationship(
        "KnowledgeChunk", back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_no", name="uq_chunk_doc_chunkno"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(String(200))
    source_ref: Mapped[str | None] = mapped_column(String(200))
    embedding_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    # relationships
    document = relationship("KnowledgeDocument", back_populates="chunks")


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    filters_json: Mapped[str | None] = mapped_column(Text)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_chunks: Mapped[str | None] = mapped_column(Text)  # JSON: chunk_id 列表
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fallback_reason: Mapped[str | None] = mapped_column(String(200))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)


class AnswerFeedback(Base):
    """P2.D.3: 检索结果用户反馈。"""
    __tablename__ = "answer_feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)  # retrieval / chat / review
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    rating: Mapped[str] = mapped_column(String(20), nullable=False)  # helpful / unhelpful
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
