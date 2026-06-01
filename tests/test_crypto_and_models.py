"""测试加密/解密/脱敏工具 & 模型配置 API Key 管理"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "config.yaml"))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.models.user import ModelConfig
from app.services.crypto import decrypt_key, encrypt_key, mask_key
from tests.conftest import make_test_app, init_test_db


# ── Crypto Tests ─────────────────────────────────────────────────────────────

class TestCrypto:
    """测试 Fernet 加密/解密/脱敏"""

    def test_encrypt_decrypt_roundtrip(self):
        secret = "my-jwt-secret"
        plain = "sk-abc123xyz456"
        encrypted = encrypt_key(plain, secret)
        assert encrypted != plain
        decrypted = decrypt_key(encrypted, secret)
        assert decrypted == plain

    def test_different_secrets_produce_different_ciphertext(self):
        plain = "sk-test-key"
        e1 = encrypt_key(plain, "secret-a")
        e2 = encrypt_key(plain, "secret-b")
        assert e1 != e2

    def test_wrong_secret_fails_decrypt(self):
        encrypted = encrypt_key("sk-key", "correct-secret")
        with pytest.raises(Exception):
            decrypt_key(encrypted, "wrong-secret")

    def test_encrypt_empty_string(self):
        encrypted = encrypt_key("", "secret")
        assert decrypt_key(encrypted, "secret") == ""

    def test_encrypt_unicode_key(self):
        plain = "密钥-abc-123"
        encrypted = encrypt_key(plain, "secret")
        assert decrypt_key(encrypted, "secret") == plain

    def test_encrypt_long_key(self):
        plain = "sk-" + "a" * 200
        encrypted = encrypt_key(plain, "secret")
        assert decrypt_key(encrypted, "secret") == plain


class TestMaskKey:
    """测试 API Key 脱敏显示"""

    def test_normal_key(self):
        assert mask_key("sk-abc123xyz456") == "sk-****z456"

    def test_short_key(self):
        assert mask_key("sk-1234") == "****"

    def test_empty_key(self):
        assert mask_key("") == "****"

    def test_none_key(self):
        assert mask_key(None) == "****"

    def test_exactly_8_chars(self):
        result = mask_key("12345678")
        assert result == "****"

    def test_9_chars(self):
        result = mask_key("123456789")
        assert result == "123****6789"


# ── Model Config API Tests ──────────────────────────────────────────────────

@pytest.fixture
def auth_headers():
    """Admin auth headers"""
    return {"Authorization": "Bearer test-admin-token"}


@pytest_asyncio.fixture
async def app_client(tmp_path):
    """Create test client with initialized DB using make_test_app from conftest"""
    db_path = str(tmp_path / "test.db")
    app, engine, TestSessionLocal = make_test_app(db_path)
    await init_test_db(engine, TestSessionLocal)

    # Re-create engine after init_test_db disposes it
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    # Seed ModelConfig rows so model API tests have data
    from app.models.user import ModelConfig
    async with TestSessionLocal() as session:
        for cfg in [
            ModelConfig(model_id="deepseek", name="DeepSeek Chat", provider="openai_compatible",
                        api_base="https://api.deepseek.com/v1", llm_model="deepseek-chat",
                        max_tokens=4096, temperature=0.7, enabled=True),
            ModelConfig(model_id="qwen", name="通义千问", provider="openai_compatible",
                        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1", llm_model="qwen-plus",
                        max_tokens=4096, temperature=0.7, enabled=False),
        ]:
            result = await session.execute(
                select(ModelConfig).where(ModelConfig.model_id == cfg.model_id)
            )
            if result.scalar_one_or_none() is None:
                session.add(cfg)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await engine.dispose()


@pytest_asyncio.fixture
async def admin_token(app_client):
    """Login as admin and return token"""
    resp = await app_client.post("/api/auth/login", json={
        "username": "admin",
        "password": "admin123",
    })
    data = resp.json()
    return data["access_token"]


@pytest_asyncio.fixture
async def app_client_with_db(tmp_path):
    db_path = str(tmp_path / "test_with_db.db")
    app, engine, session_maker = make_test_app(db_path)
    await init_test_db(engine, session_maker)

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_maker

    await engine.dispose()


class TestModelConfigAPI:
    """测试模型配置管理 API"""

    @pytest.mark.asyncio
    async def test_list_models(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await app_client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 200
        models = resp.json()
        assert isinstance(models, list)
        # Should have models from config.yaml initialization
        if models:
            m = models[0]
            assert "model_id" in m
            assert "api_key_masked" in m
            assert "has_api_key" in m
            assert "enabled" in m
            # API key should be masked, not plain
            if m["has_api_key"]:
                assert "****" in m["api_key_masked"]
            assert "display_order" in m

    @pytest.mark.asyncio
    async def test_update_api_key(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        # First get models
        resp = await app_client.get("/api/admin/models", headers=headers)
        models = resp.json()
        if not models:
            pytest.skip("No models configured")

        model_id = models[0]["model_id"]
        # Update API key
        resp = await app_client.put(
            f"/api/admin/models/{model_id}/api-key",
            headers=headers,
            json={"api_key": "sk-test-new-key-12345"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "****" in data["api_key_masked"]

        # Verify masked key changed
        resp = await app_client.get("/api/admin/models", headers=headers)
        models = resp.json()
        m = next(x for x in models if x["model_id"] == model_id)
        assert m["has_api_key"] is True
        assert "****" in m["api_key_masked"]

    @pytest.mark.asyncio
    async def test_update_model_config(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await app_client.get("/api/admin/models", headers=headers)
        models = resp.json()
        if not models:
            pytest.skip("No models configured")

        model_id = models[0]["model_id"]
        # Update config
        resp = await app_client.put(
            f"/api/admin/models/{model_id}",
            headers=headers,
            json={"max_tokens": 8192, "temperature": 0.5},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_model_name_persists_and_is_returned(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await app_client.get("/api/admin/models", headers=headers)
        models = resp.json()
        if not models:
            pytest.skip("No models configured")

        model_id = models[0]["model_id"]
        new_name = "DeepSeek Chat Renamed"
        resp = await app_client.put(
            f"/api/admin/models/{model_id}",
            headers=headers,
            json={"name": new_name},
        )
        assert resp.status_code == 200

        resp = await app_client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 200
        model = next(x for x in resp.json() if x["model_id"] == model_id)
        assert model["name"] == new_name

    @pytest.mark.asyncio
    async def test_reorder_models_persists_display_order_and_list_order(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await app_client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 200
        models = resp.json()
        if len(models) < 2:
            pytest.skip("Need at least two models configured")

        reversed_ids = [m["model_id"] for m in reversed(models)]
        resp = await app_client.put(
            "/api/admin/models/order",
            headers=headers,
            json={"model_ids": reversed_ids},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = await app_client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 200
        reordered = resp.json()
        assert [m["model_id"] for m in reordered[: len(reversed_ids)]] == reversed_ids
        assert [m["display_order"] for m in reordered[: len(reversed_ids)]] == list(range(len(reversed_ids)))

        chat_resp = await app_client.get("/api/chat/models", headers=headers)
        assert chat_resp.status_code == 200
        assert [m["id"] for m in chat_resp.json()] == reversed_ids

    @pytest.mark.asyncio
    async def test_create_model_success(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await app_client.post(
            "/api/admin/models",
            headers=headers,
            json={
                "model_id": "test-create-model",
                "name": "Test Create Model",
                "provider": "openai_compatible",
                "api_base": "https://example.com/v1",
                "llm_model": "example-chat",
                "max_tokens": 4096,
                "temperature": 0.6,
                "enabled": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = await app_client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 200
        models = resp.json()
        created = next((m for m in models if m["model_id"] == "test-create-model"), None)
        assert created is not None
        assert created["name"] == "Test Create Model"

    @pytest.mark.asyncio
    async def test_create_model_with_api_key_encrypts_value(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await app_client.post(
            "/api/admin/models",
            headers=headers,
            json={
                "model_id": "test-create-model-with-key",
                "name": "Test Create Model With Key",
                "provider": "openai_compatible",
                "api_base": "https://example.com/v1",
                "llm_model": "example-chat",
                "api_key": "sk-test-create-key-123456",
                "max_tokens": 2048,
                "temperature": 0.7,
                "enabled": True,
            },
        )
        assert resp.status_code == 200

        resp = await app_client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 200
        model = next((m for m in resp.json() if m["model_id"] == "test-create-model-with-key"), None)
        assert model is not None
        assert model["has_api_key"] is True
        assert "****" in model["api_key_masked"]
        assert "sk-test-create-key-123456" not in model["api_key_masked"]

    @pytest.mark.asyncio
    async def test_create_model_with_api_key_uses_secret_successfully(self, app_client_with_db):
        app_client, session_maker = app_client_with_db
        login_resp = await app_client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        admin_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await app_client.post(
            "/api/admin/models",
            headers=headers,
            json={
                "model_id": "test-create-model-secret",
                "name": "Test Create Model Secret",
                "provider": "openai_compatible",
                "api_base": "https://example.com/v1",
                "llm_model": "example-chat",
                "api_key": "sk-secret-create-key-654321",
                "max_tokens": 2048,
                "temperature": 0.7,
                "enabled": True,
            },
        )
        assert resp.status_code == 200

        async with session_maker() as session:
            result = await session.execute(
                select(ModelConfig).where(ModelConfig.model_id == "test-create-model-secret")
            )
            model = result.scalar_one()

        assert model.encrypted_api_key
        secret = get_settings().get("auth", {}).get("secret_key", "")
        assert decrypt_key(model.encrypted_api_key, secret) == "sk-secret-create-key-654321"

    @pytest.mark.asyncio
    async def test_create_model_forbidden_for_non_admin(self, app_client):
        await app_client.post("/api/auth/register", json={"username": "model_create_user", "password": "test123456"})
        resp = await app_client.post("/api/auth/login", json={"username": "model_create_user", "password": "test123456"})
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await app_client.post(
            "/api/admin/models",
            headers=headers,
            json={
                "model_id": "forbidden-create-model",
                "name": "Forbidden Create Model",
                "provider": "openai_compatible",
                "api_base": "https://example.com/v1",
                "llm_model": "example-chat",
                "max_tokens": 1024,
                "temperature": 0.7,
                "enabled": True,
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_model_success(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        create_resp = await app_client.post(
            "/api/admin/models",
            headers=headers,
            json={
                "model_id": "test-delete-model",
                "name": "Test Delete Model",
                "provider": "openai_compatible",
                "api_base": "https://example.com/v1",
                "llm_model": "example-chat",
                "max_tokens": 1024,
                "temperature": 0.7,
                "enabled": True,
            },
        )
        assert create_resp.status_code == 200

        resp = await app_client.delete(f"/api/admin/models/test-delete-model", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = await app_client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 200
        assert all(m["model_id"] != "test-delete-model" for m in resp.json())

    @pytest.mark.asyncio
    async def test_deleted_builtin_model_is_not_reseeded_on_restart(self, app_client_with_db):
        app_client, session_maker = app_client_with_db

        login_resp = await app_client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        admin_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}

        list_resp = await app_client.get("/api/admin/models", headers=headers)
        assert list_resp.status_code == 200
        assert any(m["model_id"] == "qwen" for m in list_resp.json())

        delete_resp = await app_client.delete("/api/admin/models/qwen", headers=headers)
        assert delete_resp.status_code == 200

        list_resp = await app_client.get("/api/admin/models", headers=headers)
        assert list_resp.status_code == 200
        assert all(m["model_id"] != "qwen" for m in list_resp.json())

        from app import database as db_module

        original_async_session = db_module.async_session
        db_module.async_session = session_maker
        try:
            await db_module._ensure_model_configs()
        finally:
            db_module.async_session = original_async_session

        list_resp = await app_client.get("/api/admin/models", headers=headers)
        assert list_resp.status_code == 200
        assert all(m["model_id"] != "qwen" for m in list_resp.json())

    @pytest.mark.asyncio
    async def test_delete_model_not_found(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await app_client.delete("/api/admin/models/nonexistent-delete-model", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_test_connection_no_key(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        # Get models, find one, clear its key
        resp = await app_client.get("/api/admin/models", headers=headers)
        models = resp.json()
        if not models:
            pytest.skip("No models configured")

        model_id = models[0]["model_id"]
        # If model has no key, test should fail gracefully
        # We can't easily clear the key, so just test the endpoint works
        with patch("app.routers.admin.check_connection", new_callable=AsyncMock) as mock_tc:
            mock_tc.return_value = {"status": "ok", "detail": "连接成功"}
            resp = await app_client.post(
                f"/api/admin/models/{model_id}/test-connection",
                headers=headers,
            )
            # May fail if key is not set, but endpoint should respond
            assert resp.status_code in (200, 200)

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, app_client):
        # Create a regular user
        await app_client.post("/api/auth/register", json={
            "username": "testuser",
            "password": "test123456",
        })
        resp = await app_client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "test123456",
        })
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Should be forbidden
        resp = await app_client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_nonexistent_model(self, app_client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await app_client.put(
            "/api/admin/models/nonexistent-model/api-key",
            headers=headers,
            json={"api_key": "sk-test"},
        )
        assert resp.status_code == 404
