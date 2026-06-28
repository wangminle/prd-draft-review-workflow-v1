"""Tests for BUG-054, BUG-055, BUG-056 — Pi Agent config fixes.

BUG-054: Nullable fields can be cleared (set to NULL) via explicit null.
BUG-055: Connection/speed tests reject unsupported providers (e.g. Anthropic).
BUG-056: Singleton config cannot produce duplicate rows under concurrent creation.
"""

import os
import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-tests")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db as original_get_db
from app.models.user import Base, User, PiAgentConfig
from app.services.auth import hash_password, create_access_token


def _make_test_app(db_path: str):
    """Create a minimal test app with pi_agent router."""
    from fastapi import FastAPI
    from app.routers import pi_agent

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

    app = FastAPI()
    app.dependency_overrides[original_get_db] = get_test_db
    app.include_router(pi_agent.router, prefix="/api/pi-agent")

    return app, engine, TestSessionLocal


@pytest_asyncio.fixture
async def pi_agent_env(tmp_path):
    """Set up a test database with admin user and Pi Agent config."""
    db_path = str(tmp_path / "test.db")
    app, engine, session_maker = _make_test_app(db_path)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create admin user
    async with session_maker() as session:
        session.add(User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin",
        ))
        await session.commit()

    # Generate token directly (need user_id from the created admin)
    async with session_maker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        admin_user = result.scalar_one()
    token = create_access_token(admin_user.id, "admin")
    headers = {"Authorization": f"Bearer {token}"}
    yield app, engine, session_maker, headers, db_path

    await engine.dispose()


# ── BUG-054: Nullable fields can be cleared ──────────────────────────────────


@pytest.mark.asyncio
async def test_bug054_clear_vision_model(pi_agent_env):
    """Sending vision_model=null should set it to NULL, not be ignored."""
    app, engine, session_maker, headers, db_path = pi_agent_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First, set vision_model to a non-null value
        resp = await client.put(
            "/api/pi-agent/config",
            json={"vision_model": "gpt-4o"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["vision_model"] == "gpt-4o"

        # Now clear it by sending null
        resp = await client.put(
            "/api/pi-agent/config",
            json={"vision_model": None},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["vision_model"] is None, \
            "BUG-054: vision_model=null should clear the field, not be ignored"


@pytest.mark.asyncio
async def test_bug054_clear_system_prompt(pi_agent_env):
    """Sending system_prompt=null should set it to NULL."""
    app, engine, session_maker, headers, db_path = pi_agent_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Set system_prompt
        resp = await client.put(
            "/api/pi-agent/config",
            json={"system_prompt": "You are a helpful assistant."},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] == "You are a helpful assistant."

        # Clear it
        resp = await client.put(
            "/api/pi-agent/config",
            json={"system_prompt": None},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] is None, \
            "BUG-054: system_prompt=null should clear the field"


@pytest.mark.asyncio
async def test_bug054_omitted_fields_unchanged(pi_agent_env):
    """Fields not included in the request body should retain their values."""
    app, engine, session_maker, headers, db_path = pi_agent_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Set extension_path
        resp = await client.put(
            "/api/pi-agent/config",
            json={"extension_path": "/some/path.ts"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["extension_path"] == "/some/path.ts"

        # Update a different field without touching extension_path
        resp = await client.put(
            "/api/pi-agent/config",
            json={"llm_model": "gpt-4"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["extension_path"] == "/some/path.ts", \
            "BUG-054: omitted field should not be cleared"
        assert resp.json()["llm_model"] == "gpt-4"


@pytest.mark.asyncio
async def test_bug054_clear_all_nullable_fields(pi_agent_env):
    """All nullable fields should be clearable via explicit null."""
    app, engine, session_maker, headers, db_path = pi_agent_env

    nullable_fields = {
        "search_api_base": "https://search.example.com",
        "vision_api_base": "https://vision.example.com",
        "vision_model": "gpt-4o",
        "extension_path": "/ext/path",
        "skills_registry_url": "https://registry.example.com",
        "skills_installed_list": '["skill1"]',
        "system_prompt": "You are helpful.",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Set all nullable fields to non-null values
        resp = await client.put(
            "/api/pi-agent/config",
            json=nullable_fields,
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for field, value in nullable_fields.items():
            assert data[field] == value, f"Failed to set {field}"

        # Clear all nullable fields
        clear_payload = {field: None for field in nullable_fields}
        resp = await client.put(
            "/api/pi-agent/config",
            json=clear_payload,
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for field in nullable_fields:
            assert data[field] is None, \
                f"BUG-054: {field}=null should clear the field, got {data[field]!r}"


# ── BUG-055: Unsupported provider returns clear error ───────────────────────


@pytest.mark.asyncio
async def test_bug055_anthropic_test_connection_returns_fail(pi_agent_env):
    """Test connection with Anthropic provider should return an explicit unsupported error."""
    app, engine, session_maker, headers, db_path = pi_agent_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Set provider to anthropic
        resp = await client.put(
            "/api/pi-agent/config",
            json={"llm_provider": "anthropic"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Test connection should fail with clear message
        resp = await client.post(
            "/api/pi-agent/config/test-connection",
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "fail"
        assert "anthropic" in result["detail"].lower() or "不支持" in result["detail"], \
            "BUG-055: Anthropic provider should get an explicit unsupported message"


@pytest.mark.asyncio
async def test_bug055_anthropic_speed_test_returns_fail(pi_agent_env):
    """Speed test with Anthropic provider should return an explicit unsupported error."""
    app, engine, session_maker, headers, db_path = pi_agent_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/pi-agent/config",
            json={"llm_provider": "anthropic"},
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await client.post(
            "/api/pi-agent/config/speed-test",
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "fail"
        assert result["latency_ms"] is None
        assert "anthropic" in result["detail"].lower() or "不支持" in result["detail"]


@pytest.mark.asyncio
async def test_bug055_deepseek_provider_proceeds_to_test(pi_agent_env):
    """DeepSeek (OpenAI-compatible) should proceed past the provider check."""
    app, engine, session_maker, headers, db_path = pi_agent_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Default provider is deepseek -- no API key configured
        resp = await client.post(
            "/api/pi-agent/config/test-connection",
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        # Should fail because no API key is configured, NOT because of provider check
        assert "API Key" in result["detail"] or "未配置" in result["detail"], \
            "DeepSeek provider should pass the provider check (fail at key check instead)"


@pytest.mark.asyncio
async def test_bug055_openai_compatible_proceeds_to_test(pi_agent_env):
    """OpenAI-compatible provider should proceed past the provider check."""
    app, engine, session_maker, headers, db_path = pi_agent_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/pi-agent/config",
            json={"llm_provider": "openai_compatible"},
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await client.post(
            "/api/pi-agent/config/test-connection",
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        # Should fail because no API key, not because of provider
        assert "API Key" in result["detail"] or "未配置" in result["detail"]


# ── BUG-056: Singleton config uniqueness ─────────────────────────────────────


@pytest.mark.asyncio
async def test_bug056_get_or_create_returns_single_row():
    """get_or_create should always return exactly one row, even if called concurrently."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        from app.repositories.pi_agent_config_repository import PiAgentConfigRepository

        # Call get_or_create multiple times concurrently
        async def _create_config():
            async with session_maker() as session:
                repo = PiAgentConfigRepository(session)
                config = await repo.get_or_create()
                await session.commit()
                return config.id

        results = await asyncio.gather(*[_create_config() for _ in range(10)])

        # Verify only one row exists
        async with session_maker() as session:
            result = await session.execute(select(PiAgentConfig))
            rows = result.scalars().all()
            assert len(rows) == 1, \
                f"BUG-056: Expected exactly 1 row, got {len(rows)}"
    finally:
        await engine.dispose()
        try:
            os.unlink(db_path)
        except PermissionError:
            pass


@pytest.mark.asyncio
async def test_bug056_singleton_key_unique_constraint():
    """Inserting a second row with the same singleton_key should raise IntegrityError."""
    import tempfile
    from sqlalchemy.exc import IntegrityError

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Insert first row via ORM
        async with session_maker() as session:
            session.add(PiAgentConfig(singleton_key="default", llm_provider="deepseek"))
            await session.commit()

        # Second insert with same singleton_key should raise IntegrityError
        async with session_maker() as session:
            session.add(PiAgentConfig(singleton_key="default", llm_provider="openai"))
            with pytest.raises(IntegrityError):
                await session.commit()

        # Verify only one row exists
        async with session_maker() as session:
            result = await session.execute(select(PiAgentConfig))
            rows = result.scalars().all()
            assert len(rows) == 1, \
                f"BUG-056: Expected 1 row after duplicate insert, got {len(rows)}"
            assert rows[0].llm_provider == "deepseek"
    finally:
        await engine.dispose()
        try:
            os.unlink(db_path)
        except PermissionError:
            pass
