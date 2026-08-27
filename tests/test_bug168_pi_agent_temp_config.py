"""BUG-168 / GitHub Issue #2：Pi Agent 填 Key 后连接测试仍提示「未配置」。

根因：前端「连接测试 / 测速」按钮不带任何参数请求后端，后端只读数据库
中已保存的配置——用户在表单里新填的 Key / Base / 模型名在被保存之前
无法被测试，若数据库尚未保存过 Key 则直接报「未配置 LLM API Key」。

修复（临时配置测试，不测试前自动持久化无效 Key）：
  1. POST /config/test-connection 与 /config/speed-test 增加可选请求体
     api_key / llm_provider / llm_api_base / llm_model；
  2. 请求传值优先测试表单值，未传字段回退数据库配置；
  3. 临时 Key 仅本次请求内存中使用：不落库、不更新测试状态、不写日志；
  4. 响应携带 config_saved=False，前端据此显示「当前配置尚未保存」。
"""

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from app.database import get_db as original_get_db  # noqa: E402
from app.models.user import Base, User, PiAgentConfig  # noqa: E402
from app.services.auth import hash_password, create_access_token  # noqa: E402


def _make_test_app(db_path: str):
    from fastapi import FastAPI
    from app.routers import pi_agent

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def get_test_db():
        async with TestSessionLocal() as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[original_get_db] = get_test_db
    app.include_router(pi_agent.router, prefix="/api/pi-agent")
    return app, engine, TestSessionLocal


@pytest_asyncio.fixture
async def pi_agent_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    app, engine, session_maker = _make_test_app(db_path)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as session:
        session.add(User(
            username="admin",
            password_hash=hash_password("admin@2026"),
            role="admin",
        ))
        await session.commit()

    async with session_maker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        admin_user = result.scalar_one()
    token = create_access_token(admin_user.id, "admin")
    headers = {"Authorization": f"Bearer {token}"}
    yield app, engine, session_maker, headers, db_path
    await engine.dispose()


async def _save_llm_config(client, headers):
    """保存一份基线 LLM 配置（deepseek + 已保存 Key），供回退断言。"""
    resp = await client.put(
        "/api/pi-agent/config",
        json={
            "llm_provider": "deepseek",
            "llm_api_base": "http://saved-base.test/v1",
            "llm_model": "saved-model",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    resp = await client.put(
        "/api/pi-agent/config/llm-api-key",
        json={"api_key": "sk-saved-key"},
        headers=headers,
    )
    assert resp.status_code == 200


async def _get_config_row(session_maker) -> PiAgentConfig:
    async with session_maker() as session:
        result = await session.execute(select(PiAgentConfig))
        return result.scalar_one()


# ── 无请求体：回退数据库配置并记录测试状态（原行为不变） ──


@pytest.mark.asyncio
async def test_no_body_falls_back_to_saved_config_and_records_status(pi_agent_env, monkeypatch):
    app, engine, session_maker, headers, db_path = pi_agent_env

    captured = {}

    async def fake_check_connection(api_base, api_key, llm_model):
        captured.update(api_base=api_base, api_key=api_key, llm_model=llm_model)
        return {"status": "ok", "detail": "连接成功"}

    import app.routers.pi_agent as pi_agent_module
    monkeypatch.setattr(pi_agent_module, "check_connection", fake_check_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _save_llm_config(client, headers)

        resp = await client.post("/api/pi-agent/config/test-connection", headers=headers)

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "ok"
    assert result["config_saved"] is True
    assert captured == {
        "api_base": "http://saved-base.test/v1",
        "api_key": "sk-saved-key",
        "llm_model": "saved-model",
    }

    config = await _get_config_row(session_maker)
    assert config.last_test_status == "ok"


# ── 带临时配置：请求值优先，不落库、不更新测试状态 ──


@pytest.mark.asyncio
async def test_temp_config_uses_request_values_without_persisting(pi_agent_env, monkeypatch):
    app, engine, session_maker, headers, db_path = pi_agent_env

    captured = {}

    async def fake_check_connection(api_base, api_key, llm_model):
        captured.update(api_base=api_base, api_key=api_key, llm_model=llm_model)
        return {"status": "ok", "detail": "连接成功"}

    import app.routers.pi_agent as pi_agent_module
    monkeypatch.setattr(pi_agent_module, "check_connection", fake_check_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _save_llm_config(client, headers)

        resp = await client.post(
            "/api/pi-agent/config/test-connection",
            json={
                "api_key": "sk-temp-key",
                "llm_provider": "openai_compatible",
                "llm_api_base": "http://temp-base.test/v1",
                "llm_model": "temp-model",
            },
            headers=headers,
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "ok"
    assert result["config_saved"] is False, "临时配置测试必须告知前端「尚未保存」"
    assert captured == {
        "api_base": "http://temp-base.test/v1",
        "api_key": "sk-temp-key",
        "llm_model": "temp-model",
    }

    config = await _get_config_row(session_maker)
    # 临时 Key 不落库：保存的密文对应的明文仍是旧 Key
    from app.services.crypto import decrypt_key
    from app.routers.pi_agent import _get_jwt_secret
    assert decrypt_key(config.llm_encrypted_api_key, _get_jwt_secret()) == "sk-saved-key"
    # 临时配置的测试结果不代表已保存配置，不更新测试状态
    # （保存配置时被重置为 "unknown"，临时测试不得改写为 "ok"）
    assert config.last_test_status == "unknown"


@pytest.mark.asyncio
async def test_temp_body_partial_fields_fall_back_to_db(pi_agent_env, monkeypatch):
    """只传部分字段：未传字段回退数据库配置。"""
    app, engine, session_maker, headers, db_path = pi_agent_env

    captured = {}

    async def fake_check_connection(api_base, api_key, llm_model):
        captured.update(api_base=api_base, api_key=api_key, llm_model=llm_model)
        return {"status": "ok", "detail": "连接成功"}

    import app.routers.pi_agent as pi_agent_module
    monkeypatch.setattr(pi_agent_module, "check_connection", fake_check_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _save_llm_config(client, headers)

        resp = await client.post(
            "/api/pi-agent/config/test-connection",
            json={"llm_model": "temp-model"},
            headers=headers,
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["config_saved"] is False
    assert captured == {
        "api_base": "http://saved-base.test/v1",
        "api_key": "sk-saved-key",
        "llm_model": "temp-model",
    }


@pytest.mark.asyncio
async def test_empty_api_key_string_falls_back_to_saved_key(pi_agent_env, monkeypatch):
    """前端 Key 留空发送空串：应回退数据库已保存 Key（语义同「留空不修改」）。"""
    app, engine, session_maker, headers, db_path = pi_agent_env

    captured = {}

    async def fake_check_connection(api_base, api_key, llm_model):
        captured.update(api_base=api_base, api_key=api_key, llm_model=llm_model)
        return {"status": "ok", "detail": "连接成功"}

    import app.routers.pi_agent as pi_agent_module
    monkeypatch.setattr(pi_agent_module, "check_connection", fake_check_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _save_llm_config(client, headers)

        resp = await client.post(
            "/api/pi-agent/config/test-connection",
            json={"api_key": "", "llm_api_base": "http://temp2.test/v1"},
            headers=headers,
        )

    assert resp.status_code == 200
    assert resp.json()["config_saved"] is False
    assert captured["api_key"] == "sk-saved-key"
    assert captured["api_base"] == "http://temp2.test/v1"


@pytest.mark.asyncio
async def test_temp_provider_unsupported_returns_fail(pi_agent_env):
    """请求体指定不支持的 provider：返回明确的不支持错误，且不触达 LLM。"""
    app, engine, session_maker, headers, db_path = pi_agent_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _save_llm_config(client, headers)

        resp = await client.post(
            "/api/pi-agent/config/test-connection",
            json={"llm_provider": "anthropic", "api_key": "sk-any"},
            headers=headers,
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "fail"
    assert "不支持" in result["detail"]


@pytest.mark.asyncio
async def test_speed_test_uses_temp_config_same_way(pi_agent_env, monkeypatch):
    """测速接口采用相同的临时配置逻辑。"""
    app, engine, session_maker, headers, db_path = pi_agent_env

    captured = {}

    async def fake_speed_test(api_base, api_key, llm_model):
        captured.update(api_base=api_base, api_key=api_key, llm_model=llm_model)
        return {"status": "ok", "latency_ms": 321}

    import app.routers.pi_agent as pi_agent_module
    monkeypatch.setattr(pi_agent_module, "speed_test", fake_speed_test)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _save_llm_config(client, headers)

        resp = await client.post(
            "/api/pi-agent/config/speed-test",
            json={"api_key": "sk-temp-key", "llm_model": "temp-model"},
            headers=headers,
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "ok"
    assert result["latency_ms"] == 321
    assert result["config_saved"] is False
    assert captured == {
        "api_base": "http://saved-base.test/v1",
        "api_key": "sk-temp-key",
        "llm_model": "temp-model",
    }

    config = await _get_config_row(session_maker)
    # 保存配置时重置为 "unknown"；临时测速不得改写状态或延迟
    assert config.last_test_status == "unknown"
    assert config.last_test_latency_ms is None


@pytest.mark.asyncio
async def test_new_key_testable_before_save(pi_agent_env, monkeypatch):
    """Issue #2 核心场景：数据库从未保存过 Key，表单新填 Key 也能完成测试。"""
    app, engine, session_maker, headers, db_path = pi_agent_env

    captured = {}

    async def fake_check_connection(api_base, api_key, llm_model):
        captured.update(api_base=api_base, api_key=api_key, llm_model=llm_model)
        return {"status": "ok", "detail": "连接成功"}

    import app.routers.pi_agent as pi_agent_module
    monkeypatch.setattr(pi_agent_module, "check_connection", fake_check_connection)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 不保存任何 Key，直接用表单临时值测试
        resp = await client.post(
            "/api/pi-agent/config/test-connection",
            json={
                "api_key": "sk-brand-new-key",
                "llm_api_base": "http://brand-new.test/v1",
                "llm_model": "brand-new-model",
            },
            headers=headers,
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "ok"
    assert result["config_saved"] is False
    assert captured["api_key"] == "sk-brand-new-key"

    config = await _get_config_row(session_maker)
    assert config.llm_encrypted_api_key is None, "临时 Key 不得被持久化"
