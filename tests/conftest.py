"""Pytest 配置 — 集成测试数据库隔离"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))
# Ensure JWT_SECRET is set before any app module loads config —
# config.yaml uses ${JWT_SECRET} which resolves to "" if unset,
# but we need a stable non-empty secret for API key encryption/decryption.
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-tests")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db as original_get_db
from app.models.user import Base, User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def clear_review_progress_queues():
    """Keep module-level SSE queues isolated between test cases."""
    from app.routers import review

    review.progress_queues.clear()
    yield
    review.progress_queues.clear()


def make_test_app(db_path: str):
    """创建独立的 FastAPI 测试应用"""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from app.routers import admin, auth, chat, history, review, upload

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def get_test_db():
        async with TestSessionLocal() as session:
            try:
                yield session
            finally:
                pass

    # 创建独立的 app，不传 lifespan（手动初始化数据库）
    app = FastAPI(title="AI产品需求初审 (Test)")
    app.dependency_overrides[original_get_db] = get_test_db

    app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
    app.include_router(chat.router, prefix="/api/chat", tags=["对话"])
    app.include_router(upload.router, prefix="/api/upload", tags=["上传"])
    app.include_router(history.router, prefix="/api/history", tags=["历史记录"])
    app.include_router(admin.router, prefix="/api/admin", tags=["管理"])
    app.include_router(review.router, prefix="/api/review", tags=["需求审查"])

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": "0.2.8"}

    return app, engine, TestSessionLocal


async def init_test_db(engine, session_maker):
    """初始化测试数据库"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        await conn.execute(sa_text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts "
            "USING fts5(content, content='messages', content_rowid='id', "
            "tokenize='unicode61')"
        ))
    async with session_maker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none() is None:
            session.add(User(
                username="admin",
                password_hash=hash_password("admin123"),
                role="admin",
            ))

        # Add builtin prompt templates
        from app.models.user import PromptTemplate
        builtins = [
            {"name": "default", "description": "通用智能助手", "system_prompt": "你是一个智能助手", "user_prompt_template": None, "is_builtin": True},
            {"name": "code_review", "description": "代码审查助手", "system_prompt": "你是代码审查专家", "user_prompt_template": "请审查：{content}", "is_builtin": True},
            {"name": "translator", "description": "中英翻译助手", "system_prompt": "你是专业翻译", "user_prompt_template": "请翻译：{content}", "is_builtin": True},
            {"name": "summarizer", "description": "文本摘要助手", "system_prompt": "你擅长文本摘要", "user_prompt_template": "请总结：{content}", "is_builtin": True},
        ]
        for bt in builtins:
            result = await session.execute(
                select(PromptTemplate).where(PromptTemplate.name == bt["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(PromptTemplate(**bt))

        # Seed ModelConfig rows from config.yaml (mirrors _ensure_model_configs in database.py)
        from app.config import get_settings
        from app.models.user import ModelConfig
        from app.services.crypto import encrypt_key

        settings = get_settings()
        jwt_secret = settings.get("auth", {}).get("secret_key", "test-jwt-secret-for-tests")

        result = await session.execute(select(ModelConfig))
        existing = {mc.model_id for mc in result.scalars().all()}

        for m in settings.get("models", []):
            if m["id"] in existing:
                continue

            # Resolve API key — env vars won't be set in tests, so use placeholder
            raw_key = m.get("api_key", "")
            if raw_key.startswith("${") and raw_key.endswith("}"):
                env_var = raw_key[2:-1]
                raw_key = os.environ.get(env_var, "test-api-key")

            encrypted_key = encrypt_key(raw_key, jwt_secret) if raw_key else None

            mc = ModelConfig(
                model_id=m["id"],
                name=m["name"],
                provider=m.get("adapter", "openai_compatible"),
                api_base=m["base_url"],
                encrypted_api_key=encrypted_key,
                llm_model=m.get("model", m["id"]),
                max_tokens=m.get("max_tokens", 4096),
                temperature=m.get("temperature", 0.7),
                enabled=m.get("enabled", True),
                last_test_status="unknown",
            )
            session.add(mc)

        await session.commit()

    await engine.dispose()
