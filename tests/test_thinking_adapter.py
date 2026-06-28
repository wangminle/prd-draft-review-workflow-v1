"""P1.6 — Thinking adapter 单元测试 & API 集成测试"""

import pytest
import pytest_asyncio
import os
import tempfile

from app.services.thinking_adapter import (
    ThinkingLevel,
    ThinkingAdapter,
    THINKING_ADAPTER_TEMPLATES,
    build_thinking_payload,
)


# ── Unit tests: build_thinking_payload ──


class TestBuildThinkingPayload:
    def test_off_level_returns_empty(self):
        assert build_thinking_payload("off", "openai_reasoning") == {}

    def test_none_adapter_returns_empty(self):
        assert build_thinking_payload("high", "none") == {}

    def test_off_with_none_adapter_returns_empty(self):
        assert build_thinking_payload("off", "none") == {}

    def test_openai_reasoning_low(self):
        result = build_thinking_payload("low", "openai_reasoning")
        assert result == {"reasoning_effort": "low"}

    def test_openai_reasoning_high(self):
        result = build_thinking_payload("high", "openai_reasoning")
        assert result == {"reasoning_effort": "high"}

    def test_deepseek_reasoner_low(self):
        result = build_thinking_payload("low", "deepseek_reasoner")
        assert result == {"reasoning_effort": "low"}

    def test_deepseek_reasoner_high(self):
        result = build_thinking_payload("high", "deepseek_reasoner")
        assert result == {"reasoning_effort": "high"}

    def test_qwen_thinking_low(self):
        result = build_thinking_payload("low", "qwen_thinking")
        assert result == {"enable_thinking": True, "thinking_budget": 4096}

    def test_qwen_thinking_high(self):
        result = build_thinking_payload("high", "qwen_thinking")
        assert result == {"enable_thinking": True, "thinking_budget": 32768}


class TestRuntimeOverride:
    def test_runtime_override_replaces_model_default(self):
        result = build_thinking_payload(
            "off", "openai_reasoning", runtime_level_override="high"
        )
        assert result == {"reasoning_effort": "high"}

    def test_runtime_override_off_uses_model_default_off(self):
        result = build_thinking_payload(
            "high", "openai_reasoning", runtime_level_override=None
        )
        assert result == {"reasoning_effort": "high"}

    def test_runtime_override_none_falls_back_to_config(self):
        result = build_thinking_payload(
            "low", "deepseek_reasoner", runtime_level_override=None
        )
        assert result == {"reasoning_effort": "low"}

    def test_runtime_override_empty_string_treated_as_none(self):
        result = build_thinking_payload(
            "low", "openai_reasoning", runtime_level_override=""
        )
        assert result == {"reasoning_effort": "low"}


class TestCustomJson:
    def test_custom_json_with_level_placeholder(self):
        payload = '{"reasoning_effort": "{{level}}"}'
        result = build_thinking_payload("high", "custom_json", thinking_payload=payload)
        assert result == {"reasoning_effort": "high"}

    def test_custom_json_with_nested_levels(self):
        payload = '{"model_specific": true, "effort": "{{level}}"}'
        result = build_thinking_payload("low", "custom_json", thinking_payload=payload)
        assert result == {"model_specific": True, "effort": "low"}

    def test_custom_json_with_per_level_config_returns_full_dict(self):
        payload = '{"low": {"effort": "low"}, "high": {"effort": "high"}}'
        result = build_thinking_payload("high", "custom_json", thinking_payload=payload)
        assert result == {"low": {"effort": "low"}, "high": {"effort": "high"}}

    def test_custom_json_flat_with_multiple_fields(self):
        payload = '{"effort": "{{level}}", "budget": 4096}'
        result = build_thinking_payload("low", "custom_json", thinking_payload=payload)
        assert result == {"effort": "low", "budget": 4096}

    def test_custom_json_nested_substitution(self):
        payload = '{"config": {"reasoning": "{{level}}", "enabled": true}}'
        result = build_thinking_payload("high", "custom_json", thinking_payload=payload)
        assert result == {"config": {"reasoning": "high", "enabled": True}}

    def test_custom_json_no_payload_returns_empty(self):
        result = build_thinking_payload("high", "custom_json", thinking_payload=None)
        assert result == {}

    def test_custom_json_empty_payload_returns_empty(self):
        result = build_thinking_payload("high", "custom_json", thinking_payload="")
        assert result == {}

    def test_custom_json_invalid_json_returns_empty(self):
        result = build_thinking_payload("high", "custom_json", thinking_payload="not json")
        assert result == {}


class TestAdapterTemplates:
    def test_all_builtin_adapters_have_low_and_high(self):
        for adapter in (ThinkingAdapter.OPENAI_REASONING, ThinkingAdapter.DEEPSEEK_REASONER, ThinkingAdapter.QWEN_THINKING):
            levels = THINKING_ADAPTER_TEMPLATES[adapter]
            assert ThinkingLevel.LOW in levels
            assert ThinkingLevel.HIGH in levels

    def test_none_adapter_not_in_templates(self):
        assert ThinkingAdapter.NONE not in THINKING_ADAPTER_TEMPLATES


class TestEdgeCases:
    def test_unknown_level_returns_empty(self):
        result = build_thinking_payload("medium", "openai_reasoning")
        assert result == {}

    def test_unknown_adapter_returns_empty(self):
        result = build_thinking_payload("high", "unknown_adapter")
        assert result == {}


# ── API Integration tests: model config with thinking fields ──


class TestModelConfigThinkingAPI:
    @pytest_asyncio.fixture
    async def client(self):
        from httpx import ASGITransport, AsyncClient
        from tests.conftest import make_test_app, init_test_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            app, engine, session_maker = make_test_app(db_path)
            await init_test_db(engine, session_maker)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                token_resp = await ac.post("/api/auth/login", json={
                    "username": "admin", "password": "admin123",
                })
                token = token_resp.json()["access_token"]
                ac.headers["Authorization"] = f"Bearer {token}"
                yield ac
        finally:
            await engine.dispose()
            try:
                os.unlink(db_path)
            except PermissionError:
                pass

    async def _create_and_get_model(self, client, model_id, **extra):
        resp = await client.post("/api/admin/models", json={
            "model_id": model_id,
            "name": model_id,
            "api_base": "https://api.example.com/v1",
            "llm_model": "test-model",
            "api_key": "test-key",
            **extra,
        })
        assert resp.status_code == 200
        models = (await client.get("/api/admin/models")).json()
        return next(m for m in models if m["model_id"] == model_id)

    async def test_create_model_with_thinking(self, client):
        m = await self._create_and_get_model(client, "thinking-test-model",
            thinking_supported=True, thinking_level="low", thinking_adapter="openai_reasoning")
        assert m["thinking_supported"] is True
        assert m["thinking_level"] == "low"
        assert m["thinking_adapter"] == "openai_reasoning"

    async def test_create_model_without_thinking(self, client):
        m = await self._create_and_get_model(client, "no-thinking-model")
        assert m["thinking_supported"] is False
        assert m["thinking_level"] == "off"
        assert m["thinking_adapter"] == "none"

    async def test_update_model_thinking_fields(self, client):
        await self._create_and_get_model(client, "update-thinking-model")
        resp = await client.put("/api/admin/models/update-thinking-model", json={
            "thinking_supported": True,
            "thinking_level": "high",
            "thinking_adapter": "qwen_thinking",
        })
        assert resp.status_code == 200
        models = (await client.get("/api/admin/models")).json()
        m = next(x for x in models if x["model_id"] == "update-thinking-model")
        assert m["thinking_supported"] is True
        assert m["thinking_level"] == "high"
        assert m["thinking_adapter"] == "qwen_thinking"

    async def test_invalid_thinking_level_rejected(self, client):
        resp = await client.post("/api/admin/models", json={
            "model_id": "bad-level-model",
            "name": "Bad Level",
            "api_base": "https://api.example.com/v1",
            "llm_model": "test-model",
            "api_key": "test-key",
            "thinking_level": "medium",
        })
        assert resp.status_code == 422

    async def test_invalid_thinking_adapter_rejected(self, client):
        resp = await client.post("/api/admin/models", json={
            "model_id": "bad-adapter-model",
            "name": "Bad Adapter",
            "api_base": "https://api.example.com/v1",
            "llm_model": "test-model",
            "api_key": "test-key",
            "thinking_adapter": "invalid_one",
        })
        assert resp.status_code == 422

    async def test_thinking_payload_stored_and_returned(self, client):
        payload = '{"reasoning_effort": "{{level}}"}'
        m = await self._create_and_get_model(client, "custom-payload-model",
            thinking_supported=True, thinking_adapter="custom_json", thinking_payload=payload)
        assert m["thinking_payload"] == payload

    async def test_chat_list_models_returns_thinking_info(self, client):
        await self._create_and_get_model(client, "chat-thinking-model",
            thinking_supported=True, thinking_level="low", thinking_adapter="openai_reasoning", enabled=True)

        resp = await client.get("/api/chat/models")
        assert resp.status_code == 200
        models = resp.json()
        target = next(m for m in models if m["id"] == "chat-thinking-model")
        assert target["thinking_supported"] is True
        assert target["thinking_level"] == "low"

    async def test_chat_request_accepts_thinking_level(self, client):
        await self._create_and_get_model(client, "chat-override-model",
            thinking_supported=True, thinking_level="low", thinking_adapter="openai_reasoning", enabled=True)

        resp = await client.post("/api/chat", json={
            "message": "hello",
            "model_id": "chat-override-model",
            "thinking_level": "high",
        })
        assert resp.status_code in (200, 201)

    async def test_chat_sends_off_to_override_default(self, client):
        """BUG-006: selecting 'off' must send thinking_level='off' to override model default."""
        await self._create_and_get_model(client, "override-off-model",
            thinking_supported=True, thinking_level="high", thinking_adapter="openai_reasoning", enabled=True)

        resp = await client.post("/api/chat", json={
            "message": "hello",
            "model_id": "override-off-model",
            "thinking_level": "off",
        })
        assert resp.status_code in (200, 201)

    async def test_thinking_payload_can_be_cleared(self, client):
        """BUG-007: explicitly sending thinking_payload=null should clear it."""
        m = await self._create_and_get_model(client, "clear-payload-model",
            thinking_supported=True, thinking_adapter="custom_json",
            thinking_payload='{"reasoning_effort": "{{level}}"}')
        assert m["thinking_payload"] is not None

        resp = await client.put("/api/admin/models/clear-payload-model", json={
            "thinking_payload": None,
        })
        assert resp.status_code == 200
        models = (await client.get("/api/admin/models")).json()
        updated = next(x for x in models if x["model_id"] == "clear-payload-model")
        assert updated["thinking_payload"] is None

    async def test_update_without_payload_preserves_existing(self, client):
        """BUG-007: update without sending thinking_payload should preserve existing value."""
        m = await self._create_and_get_model(client, "keep-payload-model",
            thinking_supported=True, thinking_adapter="custom_json",
            thinking_payload='{"reasoning_effort": "{{level}}"}')
        assert m["thinking_payload"] is not None

        resp = await client.put("/api/admin/models/keep-payload-model", json={
            "thinking_level": "high",
        })
        assert resp.status_code == 200
        models = (await client.get("/api/admin/models")).json()
        updated = next(x for x in models if x["model_id"] == "keep-payload-model")
        assert updated["thinking_payload"] == '{"reasoning_effort": "{{level}}"}'


class TestDBMigration:
    @pytest_asyncio.fixture
    async def client(self):
        from httpx import ASGITransport, AsyncClient
        from tests.conftest import make_test_app, init_test_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            app, engine, session_maker = make_test_app(db_path)
            await init_test_db(engine, session_maker)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                token_resp = await ac.post("/api/auth/login", json={
                    "username": "admin", "password": "admin123",
                })
                token = token_resp.json()["access_token"]
                ac.headers["Authorization"] = f"Bearer {token}"
                yield ac
        finally:
            await engine.dispose()
            try:
                os.unlink(db_path)
            except PermissionError:
                pass

    async def test_migration_columns_exist(self, client):
        resp = await client.get("/api/admin/models")
        assert resp.status_code == 200
        models = resp.json()
        if models:
            m = models[0]
            assert "thinking_supported" in m
            assert "thinking_level" in m
            assert "thinking_adapter" in m
            assert "thinking_payload" in m
