"""测试数据库模型和初始化 + 时间工具与模型默认时间"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))


def test_zombie_task_cleanup_marks_failed_step_and_completed_at():
    from types import SimpleNamespace

    from app.database import _mark_zombie_task_failed

    task = SimpleNamespace(
        status="running",
        current_step=5,
        step_statuses='{"0":"completed","1":"completed","5":"running"}',
        completed_at=None,
    )

    _mark_zombie_task_failed(task)

    assert task.status == "failed"
    assert '"5": "failed"' in task.step_statuses
    assert task.completed_at is not None


@pytest.mark.asyncio
async def test_orm_models_import():
    """SQLAlchemy ORM 模型应能正确导入"""
    from app.models.user import Base, Conversation, Message, PromptTemplate, User

    assert Base is not None
    assert hasattr(User, "__tablename__")
    assert hasattr(Conversation, "__tablename__")
    assert hasattr(Message, "__tablename__")
    assert hasattr(PromptTemplate, "__tablename__")


@pytest.mark.asyncio
async def test_user_model_columns():
    """User 模型应定义正确的列"""
    from app.models.user import User

    # 检查列名
    mapper = User.__mapper__
    columns = {c.name: c for c in mapper.columns}
    assert "id" in columns
    assert "username" in columns
    assert "password_hash" in columns
    assert "role" in columns
    assert "created_at" in columns
    assert "is_active" in columns


@pytest.mark.asyncio
async def test_conversation_model_columns():
    """Conversation 模型应定义正确的列和外键"""
    from app.models.user import Conversation

    mapper = Conversation.__mapper__
    columns = {c.name: c for c in mapper.columns}
    assert "id" in columns
    assert "user_id" in columns
    assert "title" in columns
    assert "model_id" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    # user_id 应为外键
    fk = [c for c in columns["user_id"].foreign_keys]
    assert len(fk) > 0


@pytest.mark.asyncio
async def test_message_model_columns():
    """Message 模型应定义正确的列"""
    from app.models.user import Message

    mapper = Message.__mapper__
    columns = {c.name: c for c in mapper.columns}
    assert "id" in columns
    assert "conversation_id" in columns
    assert "role" in columns
    assert "content" in columns
    assert "token_count" in columns
    assert "created_at" in columns


@pytest.mark.asyncio
async def test_database_init_creates_tables():
    """数据库初始化应创建所有表"""
    import tempfile
    from pathlib import Path

    from app.models.user import Base
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    # 使用临时数据库
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 验证表已创建
        async with engine.connect() as conn:
            def get_tables(sync_conn):
                inspector = inspect(sync_conn)
                return inspector.get_table_names()
            tables = await conn.run_sync(get_tables)

        assert "users" in tables
        assert "conversations" in tables
        assert "messages" in tables
        assert "prompt_templates" in tables

        await engine.dispose()
    finally:
        Path(db_path).unlink(missing_ok=True)


# ─── P4 新增 ORM 模型导入验证（原散布于多个文件）──────────────


@pytest.mark.asyncio
async def test_p4_orm_models_import():
    """P4 新增的 ORM 模型应能正确导入"""
    from app.models.user import Notification, Comment
    from app.models.review import KnowledgeSnapshot, Artifact, ReviewRequest, ReviewRound, ReviewParticipant

    for model in [Notification, Comment, KnowledgeSnapshot, Artifact, ReviewRequest, ReviewRound, ReviewParticipant]:
        assert hasattr(model, "__tablename__"), f"{model.__name__} missing __tablename__"


@pytest.mark.asyncio
async def test_notification_model_columns():
    """Notification 模型应定义正确的列"""
    from app.models.user import Notification

    columns = {c.name: c for c in Notification.__mapper__.columns}
    assert "recipient_id" in columns
    assert "actor_id" in columns
    assert "object_type" in columns
    assert "object_id" in columns
    assert "type" in columns
    assert "status" in columns
    assert "title" in columns
    assert "body" in columns
    assert "created_at" in columns


@pytest.mark.asyncio
async def test_comment_model_columns():
    """Comment 模型应定义正确的列"""
    from app.models.user import Comment

    columns = {c.name: c for c in Comment.__mapper__.columns}
    assert "object_type" in columns
    assert "object_id" in columns
    assert "author_id" in columns
    assert "body" in columns
    assert "parent_id" in columns
    assert "created_at" in columns


@pytest.mark.asyncio
async def test_knowledge_snapshot_model_columns():
    """KnowledgeSnapshot 模型应定义正确的列"""
    from app.models.review import KnowledgeSnapshot

    columns = {c.name: c for c in KnowledgeSnapshot.__mapper__.columns}
    assert "workspace_id" in columns
    assert "project_id" in columns
    assert "request_id" in columns
    assert "source_refs_json" in columns
    assert "chunk_refs_json" in columns
    assert "prompt_version" in columns
    assert "skill_version" in columns
    assert "model_config_hash" in columns


@pytest.mark.asyncio
async def test_artifact_model_columns():
    """Artifact 模型应定义正确的列"""
    from app.models.review import Artifact

    columns = {c.name: c for c in Artifact.__mapper__.columns}
    assert "object_type" in columns
    assert "object_id" in columns
    assert "artifact_type" in columns
    assert "content_json" in columns
    assert "source_conversation_id" in columns
    assert "source_snapshot_ref" in columns
    assert "status" in columns
    assert "confirmed_at" in columns


@pytest.mark.asyncio
async def test_review_document_has_parent_document_id():
    """ReviewDocument 应有 parent_document_id 版本链字段"""
    from app.models.review import ReviewDocument

    columns = {c.name: c for c in ReviewDocument.__mapper__.columns}
    assert "parent_document_id" in columns


# ─── now_cn 时间工具 + 模型默认时间（原 test_time_utils.py）──────────


def test_now_cn_returns_utc_plus_8():
    cn_now = __import__("app.utils", fromlist=["now_cn"]).now_cn()
    expected = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)

    assert abs((cn_now - expected).total_seconds()) < 5


def test_models_use_now_cn_for_created_at_defaults():
    from app.models.user import Conversation, Message, ModelConfig, PromptTemplate, User
    from app.models.review import DocAnalysis, ReviewContext, ReviewDocument, ReviewProject, ReviewPrompt, ReviewTask, SystemReview
    from app.utils import now_cn

    created_models = [
        User,
        Conversation,
        Message,
        PromptTemplate,
        ModelConfig,
        ReviewProject,
        ReviewDocument,
        ReviewTask,
        DocAnalysis,
        SystemReview,
        ReviewPrompt,
    ]

    for model in created_models:
        column = model.__mapper__.columns["created_at"]
        assert column.default.arg.__name__ == now_cn.__name__, model.__name__
        assert column.default.arg.__module__ == now_cn.__module__, model.__name__

    for model in [Conversation, ModelConfig, ReviewProject, ReviewContext]:
        column = model.__mapper__.columns["updated_at"]
        assert column.default.arg.__name__ == now_cn.__name__, model.__name__
        assert column.default.arg.__module__ == now_cn.__module__, model.__name__

    for model in [Conversation, ModelConfig, ReviewProject]:
        column = model.__mapper__.columns["updated_at"]
        assert column.onupdate.arg.__name__ == now_cn.__name__, model.__name__
        assert column.onupdate.arg.__module__ == now_cn.__module__, model.__name__


@pytest.mark.asyncio
async def test_review_request_model_columns():
    """ReviewRequest 模型应定义正确的列"""
    from app.models.review import ReviewRequest

    columns = {c.name: c for c in ReviewRequest.__mapper__.columns}
    assert "project_id" in columns
    assert "initiator_id" in columns
    assert "status" in columns
    assert "current_round" in columns
    assert "goal" in columns


@pytest.mark.asyncio
async def test_review_round_model_columns():
    """ReviewRound 模型应定义正确的列"""
    from app.models.review import ReviewRound

    columns = {c.name: c for c in ReviewRound.__mapper__.columns}
    assert "request_id" in columns
    assert "round_no" in columns
    assert "submitted_snapshot_ref" in columns
    assert "submitted_artifact_ref" in columns
    assert "approver_id" in columns
    assert "decision" in columns
    assert "decision_comment" in columns


@pytest.mark.asyncio
async def test_review_participant_model_columns():
    """ReviewParticipant 模型应定义正确的列"""
    from app.models.review import ReviewParticipant

    columns = {c.name: c for c in ReviewParticipant.__mapper__.columns}
    assert "request_id" in columns
    assert "user_id" in columns
    assert "role" in columns
    assert "status" in columns
