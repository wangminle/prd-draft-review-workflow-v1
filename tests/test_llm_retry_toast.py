"""LLM 调用重试机制增强测试。

需求：
1. 重试退避序列扩展为 2/4/8/16/32/64 秒（1 次首发 + 6 次重试，共 7 次尝试）
2. 重试等待前向用户在线 SSE 连接推送瞬时 toast 事件（type=llm_retry，
   不落库、不计未读数），前端 notification.js 仅弹 toast

配套改动：
- RetryConfig 默认 max_attempts 5→7、max_delay_ms 30000→64000
- review.py _build_review_retry_config 代码默认值同步 7/64000
- src/config.yaml review.retry 显式配置同步 7/64000
- llm.py 管理后台「测试模型」固定轻量配置（5 次/30s 上限），不随新默认放大
- notification_service.push_transient_event：纯内存 SSE 透传，不创建 DB 通知
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notification_service import (
    clear_channel,
    get_notification_channel,
    push_transient_event,
)
from app.services.retry import LLMRetryError, RetryConfig, retryable_chat

ROOT = Path(__file__).resolve().parents[1]


def _make_500_response():
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "server error"
    resp.headers = {}
    return resp


def _make_ok_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"completion_tokens": 1},
    }
    return resp


def _patch_client(monkeypatch, responses):
    """将 retry.httpx.AsyncClient 替换为按序返回 responses 的 mock。"""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr("app.services.retry.httpx.AsyncClient", mock_client_cls)
    return mock_client


class TestRetryConfigDefaults:
    def test_default_attempts_and_delay_cap(self):
        cfg = RetryConfig()
        assert cfg.max_attempts == 7, "默认应为 7 次尝试（1 首发 + 6 重试）"
        assert cfg.max_delay_ms == 64000, "延迟上限须容纳第 6 次 64s 等待"

    def test_delay_sequence_is_2_4_8_16_32_64(self):
        cfg = RetryConfig()
        delays = [
            min(
                cfg.initial_delay_ms / 1000.0 * (cfg.backoff_factor ** attempt),
                cfg.max_delay_ms / 1000.0,
            )
            for attempt in range(cfg.max_attempts - 1)
        ]
        assert delays == [2.0, 4.0, 8.0, 16.0, 32.0, 64.0]


class TestRetryExhaustion:
    @pytest.mark.asyncio
    async def test_seven_attempts_six_waits_then_llm_retry_error(self, monkeypatch):
        responses = [_make_500_response() for _ in range(7)]
        mock_client = _patch_client(monkeypatch, responses)

        sleeps: list[float] = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        with pytest.raises(LLMRetryError):
            await retryable_chat(
                [{"role": "user", "content": "hi"}],
                api_base="http://api",
                api_key="key",
                llm_model="model",
            )

        assert mock_client.post.await_count == 7
        assert sleeps == [2.0, 4.0, 8.0, 16.0, 32.0, 64.0]


class TestRetryToastBroadcast:
    """重试等待前应向用户 SSE 通道推送 llm_retry toast。"""

    @pytest.fixture(autouse=True)
    def _cleanup_channel(self):
        yield
        clear_channel(987001)

    @pytest.mark.asyncio
    async def test_500_retries_push_toast_events(self, monkeypatch):
        channel = get_notification_channel(987001)
        mock_client = _patch_client(monkeypatch, [_make_500_response() for _ in range(7)])

        async def fake_sleep(seconds):
            pass

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        with pytest.raises(LLMRetryError):
            await retryable_chat(
                [{"role": "user", "content": "hi"}],
                api_base="http://api",
                api_key="key",
                llm_model="model",
                user_id=987001,
            )

        assert mock_client.post.await_count == 7
        assert len(channel) == 6, "6 次重试各推送 1 条 toast"
        events = [json.loads(e) for e in channel]
        assert all(e["type"] == "llm_retry" for e in events)
        assert "第 1/6 次" in events[0]["title"]
        assert "2 秒后" in events[0]["title"]
        assert "服务端错误 500" in events[0]["title"]
        assert "第 6/6 次" in events[-1]["title"]
        assert "64 秒后" in events[-1]["title"]

    @pytest.mark.asyncio
    async def test_no_user_id_no_toast(self, monkeypatch):
        channel = get_notification_channel(987002)
        try:
            _patch_client(monkeypatch, [_make_500_response() for _ in range(7)])

            async def fake_sleep(seconds):
                pass

            monkeypatch.setattr(asyncio, "sleep", fake_sleep)

            with pytest.raises(LLMRetryError):
                await retryable_chat(
                    [{"role": "user", "content": "hi"}],
                    api_base="http://api",
                    api_key="key",
                    llm_model="model",
                    user_id=None,
                )
            assert channel == [], "无 user_id（如管理后台连通性测试）不应推送 toast"
        finally:
            clear_channel(987002)

    @pytest.mark.asyncio
    async def test_429_reason_is_rate_limit(self, monkeypatch):
        channel = get_notification_channel(987003)
        try:
            resp = _make_500_response()
            resp.status_code = 429
            _patch_client(monkeypatch, [resp, _make_ok_response()])

            async def fake_sleep(seconds):
                pass

            monkeypatch.setattr(asyncio, "sleep", fake_sleep)

            await retryable_chat(
                [{"role": "user", "content": "hi"}],
                api_base="http://api",
                api_key="key",
                llm_model="model",
                user_id=987003,
            )

            assert len(channel) == 1
            event = json.loads(channel[0])
            assert event["type"] == "llm_retry"
            assert "请求被限流" in event["title"]
        finally:
            clear_channel(987003)

    def test_push_transient_event_without_channel_is_noop(self):
        # 无在线连接时直接丢弃，不抛异常
        push_transient_event(999999999, {"type": "llm_retry", "title": "x"})


class TestModelTestConfigPinned:
    """管理后台「测试模型」保持轻量重试（5 次/30s 上限）。"""

    def test_model_test_config_not_scaled(self):
        from app.services.llm import _MODEL_TEST_RETRY_CONFIG

        assert _MODEL_TEST_RETRY_CONFIG.max_attempts == 5
        assert _MODEL_TEST_RETRY_CONFIG.max_delay_ms == 30000

    def test_existing_check_connection_behavior_unchanged(self):
        """llm.py 既有测试仍断言 5 次尝试（2/4/8/16 等待），此处锁源码默认参数。"""
        content = (ROOT / "src" / "app" / "services" / "llm.py").read_text(encoding="utf-8")
        assert "config: RetryConfig = _MODEL_TEST_RETRY_CONFIG" in content


class TestReviewRetryConfigContract:
    """审查管线重试配置：代码默认值与 config.yaml 显式值均为 7 次/64s 上限。"""

    def test_review_router_defaults(self):
        content = (ROOT / "src" / "app" / "routers" / "review.py").read_text(encoding="utf-8")
        assert 'retry_cfg.get("max_attempts", 7)' in content
        assert 'retry_cfg.get("max_delay_ms", 64000)' in content

    def test_config_yaml_values(self):
        content = (ROOT / "src" / "config.yaml").read_text(encoding="utf-8")
        retry_block = content.split("retry:", 1)[1].split("pipeline:", 1)[0]
        assert "max_attempts: 7" in retry_block
        assert "max_delay_ms: 64000" in retry_block


class TestFrontendToastContract:
    """notification.js：llm_retry 事件仅弹 toast，不计未读、不入通知列表。"""

    def test_llm_retry_branch_before_unread_increment(self):
        content = (ROOT / "src" / "static" / "js" / "notification.js").read_text(encoding="utf-8")
        assert "msg.type === 'llm_retry'" in content
        branch = content.split("msg.type === 'llm_retry'", 1)[1].split("const notif = msg", 1)[0]
        assert "App._showToast" in branch, "llm_retry 分支应直接弹 toast"
        assert "return" in branch, "llm_retry 分支处理后应 return，不进入通知计数流程"
