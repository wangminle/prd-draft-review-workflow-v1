"""默认管理员启动初始化回归测试。"""

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.models.user import Base, User
from app.services.auth import hash_password, verify_password


@pytest.mark.asyncio
async def test_default_admin_password_is_randomized_on_init(tmp_path, monkeypatch, caplog):
    import app.database as database_module

    db_path = tmp_path / "bootstrap_random_admin.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(database_module, "async_session", session_maker)

    with caplog.at_level("INFO"):
        await database_module._ensure_default_admin()

    async with session_maker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one()

    assert any("管理员账号已创建" in record.message for record in caplog.records)
    assert verify_password("admin123", admin.password_hash) is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_weak_password_is_warned_not_reset(tmp_path, monkeypatch, caplog):
    import app.database as database_module

    db_path = tmp_path / "bootstrap_weak_password.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    weak_hash = hash_password("admin123")
    async with session_maker() as session:
        session.add(User(username="admin", password_hash=weak_hash, role="admin"))
        await session.commit()

    monkeypatch.setattr(database_module, "async_session", session_maker)

    with caplog.at_level("WARNING"):
        await database_module._ensure_default_admin()

    async with session_maker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one()

    assert any("弱口令" in record.message for record in caplog.records)
    assert admin.password_hash == weak_hash
    assert verify_password("admin123", admin.password_hash) is True

    await engine.dispose()