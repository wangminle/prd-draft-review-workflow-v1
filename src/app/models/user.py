"""SQLAlchemy ORM 模型定义"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils import now_cn


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    model_id: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt_template: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    context_items = relationship("ContextItem", back_populates="conversation", cascade="all, delete-orphan", order_by="ContextItem.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    conversation = relationship("Conversation", back_populates="messages")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    user_prompt_template: Mapped[str | None] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)


class ContextItem(Base):
    __tablename__ = "chat_context_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    context_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    file_id: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(500))
    manual_text: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    conversation = relationship("Conversation", back_populates="context_items")


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    model_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="openai_compatible")
    api_base: Mapped[str] = mapped_column(String(500), nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    temperature: Mapped[float] = mapped_column(default=0.7)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    last_test_status: Mapped[str | None] = mapped_column(String(20))
    last_test_time: Mapped[datetime | None] = mapped_column(DateTime)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)


class SkillConfig(Base):
    __tablename__ = "skill_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(String(500))
    update_url: Mapped[str | None] = mapped_column(String(1000))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)
