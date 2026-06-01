"""测试 LLM service 模块 — build_messages, StreamChunk, test_connection, speed_test"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "config.yaml"))

import pytest

from app.services.llm import (
    ChatMessage,
    LLMModel,
    PromptTemplate,
    StreamChunk,
    build_messages,
    check_connection,
    speed_test,
)
from app.services.retry import RetryConfig, retryable_chat, structured_chat


class TestBuildMessages:
    """测试消息构建逻辑"""

    def test_no_template_no_history(self):
        msgs = build_messages(None, [], "你好")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "你好"

    def test_with_system_prompt(self):
        template = PromptTemplate(
            name="default",
            description="通用助手",
            system_prompt="你是一个智能助手",
            user_prompt_template="{content}",
        )
        msgs = build_messages(template, [], "你好")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "你是一个智能助手"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "你好"

    def test_with_custom_template(self):
        template = PromptTemplate(
            name="translator",
            description="翻译",
            system_prompt="你是翻译助手",
            user_prompt_template="请翻译以下内容：\n{content}",
        )
        msgs = build_messages(template, [], "Hello world")
        assert msgs[1]["content"] == "请翻译以下内容：\nHello world"

    def test_with_history(self):
        history = [
            ChatMessage(role="user", content="你好"),
            ChatMessage(role="assistant", content="你好！有什么可以帮你的？"),
        ]
        msgs = build_messages(None, history, "帮我写代码")
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "你好"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "user"
        assert msgs[2]["content"] == "帮我写代码"

    def test_with_context(self):
        msgs = build_messages(None, [], "分析这个文件", context="文件内容：ABC")
        assert len(msgs) == 1
        assert "参考资料" in msgs[0]["content"]
        assert "文件内容：ABC" in msgs[0]["content"]

    def test_template_and_context_combined(self):
        template = PromptTemplate(
            name="code_review",
            description="代码审查",
            system_prompt="你是代码审查专家",
            user_prompt_template="请审查：{content}",
        )
        msgs = build_messages(template, [], "def foo():", context="文件：main.py")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert "参考资料" in msgs[1]["content"]
        assert "def foo():" in msgs[1]["content"]


class TestStreamChunk:
    """测试 StreamChunk 数据类"""

    def test_delta_chunk(self):
        chunk = StreamChunk(delta="你好")
        assert chunk.delta == "你好"
        assert chunk.finish_reason is None
        assert chunk.usage is None

    def test_done_chunk(self):
        chunk = StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 50})
        assert chunk.finish_reason == "stop"
        assert chunk.usage["total_tokens"] == 50


class TestLLMModel:
    """测试 LLMModel 数据类"""

    def test_defaults(self):
        m = LLMModel(model_id="test", name="Test", provider="openai", api_base="http://x", api_key="k", llm_model="m")
        assert m.max_tokens == 4096
        assert m.temperature == 0.7
        assert m.enabled is True


class TestConnectionCheck:
    """测试 check_connection 函数"""

    @pytest.mark.asyncio
    async def test_success(self):
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await check_connection("http://api", "key", "model")
            assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_auth_failure(self):
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.status_code = 401
            mock_resp.json = MagicMock(return_value={"error": {"message": "Unauthorized"}})
            mock_resp.text = '{"error":{"message":"Unauthorized"}}'
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await check_connection("http://api", "bad-key", "model")
            assert result["status"] == "fail"
            assert mock_client.post.await_count == 1

    @pytest.mark.asyncio
    async def test_retries_retryable_status_until_success(self):
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_client = AsyncMock()
            resp_500_a = AsyncMock()
            resp_500_a.status_code = 500
            resp_500_a.text = "server error"
            resp_500_a.headers = {}
            resp_500_a.json = MagicMock(return_value={"error": {"message": "server error"}})
            resp_500_b = AsyncMock()
            resp_500_b.status_code = 500
            resp_500_b.text = "server error"
            resp_500_b.headers = {}
            resp_500_b.json = MagicMock(return_value={"error": {"message": "server error"}})
            resp_ok = AsyncMock()
            resp_ok.status_code = 200
            mock_client.post = AsyncMock(side_effect=[resp_500_a, resp_500_b, resp_ok])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await check_connection("http://api", "key", "model")

            assert result["status"] == "ok"
            assert mock_client.post.await_count == 3
            mock_sleep.assert_has_awaits([call(2.0), call(4.0)])

    @pytest.mark.asyncio
    async def test_retries_retryable_status_up_to_default_max_attempts(self):
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_client = AsyncMock()
            responses = []
            for _ in range(5):
                resp = AsyncMock()
                resp.status_code = 500
                resp.text = "server error"
                resp.headers = {}
                resp.json = MagicMock(return_value={"error": {"message": "server error"}})
                responses.append(resp)
            mock_client.post = AsyncMock(side_effect=responses)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await check_connection("http://api", "key", "model")

            assert result["status"] == "fail"
            assert "HTTP 500" in result["detail"]
            assert mock_client.post.await_count == 5
            mock_sleep.assert_has_awaits([call(2.0), call(4.0), call(8.0), call(16.0)])


class TestSpeedTest:
    """测试 speed_test 函数"""

    @pytest.mark.asyncio
    async def test_success(self):
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await speed_test("http://api", "key", "model")
            assert result["status"] == "ok"
            assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_retries_retryable_status_until_success(self):
        with patch("app.services.llm.httpx.AsyncClient") as mock_client_cls, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_client = AsyncMock()
            resp_500_a = AsyncMock()
            resp_500_a.status_code = 500
            resp_500_a.text = "server error"
            resp_500_a.headers = {}
            resp_500_b = AsyncMock()
            resp_500_b.status_code = 500
            resp_500_b.text = "server error"
            resp_500_b.headers = {}
            resp_ok = AsyncMock()
            resp_ok.status_code = 200
            mock_client.post = AsyncMock(side_effect=[resp_500_a, resp_500_b, resp_ok])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await speed_test("http://api", "key", "model")

            assert result["status"] == "ok"
            assert mock_client.post.await_count == 3
            mock_sleep.assert_has_awaits([call(2.0), call(4.0)])


@pytest.mark.asyncio
async def test_retryable_chat_uses_configured_request_timeout():
    with patch("app.services.retry.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"total_tokens": 12},
        })
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        text, _usage = await retryable_chat(
            [{"role": "user", "content": "生成报告"}],
            api_base="http://api",
            api_key="key",
            llm_model="model",
            config=RetryConfig(timeout_seconds=300, connect_timeout_seconds=12),
        )

        assert text == '{"ok": true}'
        timeout = mock_client_cls.call_args.kwargs["timeout"]
        assert timeout.read == 300
        assert timeout.connect == 12


class TestStructuredChatRetry:
    @pytest.mark.asyncio
    async def test_retries_when_success_response_has_no_content(self):
        with patch("app.services.retry.httpx.AsyncClient") as mock_client_cls, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_client = AsyncMock()
            empty_resp = MagicMock()
            empty_resp.status_code = 200
            empty_resp.json.return_value = {
                "choices": [{"message": {"content": None}}],
                "usage": {"completion_tokens": 512},
            }
            ok_resp = MagicMock()
            ok_resp.status_code = 200
            ok_resp.json.return_value = {
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"completion_tokens": 8},
            }
            mock_client.post = AsyncMock(side_effect=[empty_resp, ok_resp])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await structured_chat(
                [{"role": "user", "content": "输出JSON"}],
                api_base="http://api",
                api_key="key",
                llm_model="model",
            )

            assert result == {"ok": True}
            assert mock_client.post.await_count == 2
            mock_sleep.assert_awaited_once_with(2.0)
