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

from app.database import DEFAULT_ADMIN_PASSWORD
from app.models.user import Base, User
from app.services.auth import hash_password, verify_password


@pytest.mark.asyncio
async def test_default_admin_uses_random_password_on_init(tmp_path, monkeypatch, caplog):
    import app.database as database_module

    db_path = tmp_path / "bootstrap_preset_admin.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.delenv("ADMIN_INITIAL_PASSWORD", raising=False)
    monkeypatch.delenv("ALLOW_DEFAULT_ADMIN_PASSWORD", raising=False)
    # BUG-194：隔离随机初始密码一次性文件的写入位置
    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path))

    with caplog.at_level("WARNING"):
        await database_module._ensure_default_admin()

    async with session_maker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one()

    assert any("管理员账号已创建" in record.message for record in caplog.records)
    assert DEFAULT_ADMIN_PASSWORD == "admin@2026"
    assert verify_password(DEFAULT_ADMIN_PASSWORD, admin.password_hash) is False
    assert verify_password("admin123", admin.password_hash) is False

    # BUG-194：随机密码只落 0600 一次性文件，绝不进入任何日志
    secret_file = tmp_path / "secrets" / "admin_initial_password.txt"
    assert secret_file.exists(), "随机初始密码必须写入一次性保密文件"
    secret = secret_file.read_text(encoding="utf-8")
    assert secret and len(secret) >= 20
    assert (secret_file.stat().st_mode & 0o777) == 0o600
    assert (secret_file.parent.stat().st_mode & 0o777) == 0o700
    assert secret not in caplog.text, "初始密码不得出现在日志中"
    assert verify_password(secret, admin.password_hash) is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_env_password_path_creates_no_secret_file(tmp_path, monkeypatch):
    """指定 ADMIN_INITIAL_PASSWORD 时不产生一次性密码文件。"""
    import app.database as database_module

    db_path = tmp_path / "bootstrap_env_admin.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "Str0ng-Env-Passw0rd!")
    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path))

    await database_module._ensure_default_admin()

    assert not (tmp_path / "secrets" / "admin_initial_password.txt").exists()
    async with session_maker() as session:
        admin = (await session.execute(
            select(User).where(User.username == "admin")
        )).scalar_one()
    assert verify_password("Str0ng-Env-Passw0rd!", admin.password_hash) is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_consume_admin_initial_secret_removes_file(tmp_path, monkeypatch):
    """BUG-194：改密后一次性文件被删除；重复消费幂等返回 False。"""
    import app.database as database_module

    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path))
    path = database_module._write_admin_initial_secret("tmp-secret-123")
    assert path.exists()
    assert (path.stat().st_mode & 0o777) == 0o600

    assert database_module.consume_admin_initial_secret() is True
    assert not path.exists()
    assert database_module.consume_admin_initial_secret() is False


def test_change_password_consumes_secret_for_admin():
    """BUG-194：auth.change_password 对 admin 用户调用一次性文件消费。"""
    auth_src = (ROOT / "src" / "app" / "routers" / "auth.py").read_text(encoding="utf-8")
    block = auth_src.split("async def change_password", 1)[1].split("\n@router", 1)[0]
    assert 'user.username == "admin"' in block
    assert "consume_admin_initial_secret()" in block


@pytest.mark.asyncio
async def test_preset_password_blocks_startup_without_allow_flag(tmp_path, monkeypatch):
    import app.database as database_module

    db_path = tmp_path / "bootstrap_preset_password.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    preset_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
    async with session_maker() as session:
        session.add(User(username="admin", password_hash=preset_hash, role="admin"))
        await session.commit()

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.delenv("ALLOW_DEFAULT_ADMIN_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="默认"):
        await database_module._ensure_default_admin()

    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_admin123_is_still_warned_with_allow_flag(tmp_path, monkeypatch, caplog):
    import app.database as database_module

    db_path = tmp_path / "bootstrap_legacy_weak.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    weak_hash = hash_password("admin123")
    async with session_maker() as session:
        session.add(User(username="admin", password_hash=weak_hash, role="admin"))
        await session.commit()

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.setenv("ALLOW_DEFAULT_ADMIN_PASSWORD", "1")

    with caplog.at_level("WARNING"):
        await database_module._ensure_default_admin()

    async with session_maker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one()

    assert any("弱口令" in record.message for record in caplog.records)
    assert admin.password_hash == weak_hash
    assert verify_password("admin123", admin.password_hash) is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_env_default_password_rejected_without_allow_flag(tmp_path, monkeypatch):
    """ADMIN_INITIAL_PASSWORD=内置默认口令：无放行开关时拒绝创建。"""
    import app.database as database_module

    db_path = tmp_path / "bootstrap_env_default_reject.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    monkeypatch.delenv("ALLOW_DEFAULT_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path))

    with pytest.raises(RuntimeError, match="内置默认"):
        await database_module._ensure_default_admin()

    await engine.dispose()


@pytest.mark.asyncio
async def test_env_default_password_allowed_with_flag(tmp_path, monkeypatch, caplog):
    """内部部署组合：放行开关下可用内置默认口令 admin@2026 首次建号。"""
    import app.database as database_module

    db_path = tmp_path / "bootstrap_env_default_allow.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(database_module, "async_session", session_maker)
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    monkeypatch.setenv("ALLOW_DEFAULT_ADMIN_PASSWORD", "1")
    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path))

    with caplog.at_level("WARNING"):
        await database_module._ensure_default_admin()

    async with session_maker() as session:
        admin = (await session.execute(
            select(User).where(User.username == "admin")
        )).scalar_one()

    assert verify_password(DEFAULT_ADMIN_PASSWORD, admin.password_hash) is True
    assert not (tmp_path / "secrets" / "admin_initial_password.txt").exists()
    assert any("内置默认口令" in r.message for r in caplog.records)
    await engine.dispose()
