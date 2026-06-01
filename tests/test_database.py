"""测试数据库模型和初始化"""

import pytest


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
