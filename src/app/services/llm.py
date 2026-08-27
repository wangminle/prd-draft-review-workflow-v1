"""LLM service — OpenAI-compatible adapter for multiple providers."""

from __future__ import annotations

import json
import logging
import time
import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from app.services.retry import RetryConfig, _is_retryable_status, _parse_retry_after

logger = logging.getLogger(__name__)

# ── max_tokens 安全上限 ──────────────────────────────────────────
# max_tokens 是 OpenAI API 的 **输出** token 上限，不是上下文窗口总量。
# 如果管理员误将模型上下文窗口大小（如 200000）填入 max_tokens，
# 会导致 prompt 无空间而触发 400 错误。
# 此处在运行时对 max_tokens 做硬上限，防止 DB 中的不合理值传到 API。
_MAX_OUTPUT_TOKENS_HARD_LIMIT = 100000


def _cap_max_tokens(max_tokens: int) -> int:
    """对 max_tokens 做安全上限，防止超出模型输出能力或上下文窗口。"""
    if max_tokens is None or max_tokens <= 0:
        return 4096
    return min(max_tokens, _MAX_OUTPUT_TOKENS_HARD_LIMIT)


# ── 上下文窗口自动压缩 ──────────────────────────────────────────
# 粗略估算 token 数：英文约 4 字符/token，中文约 1.5 字符/token，
# 混合场景取折中值 3 字符/token，再加少量 overhead。
_CHARS_PER_TOKEN = 3
_TOKEN_OVERHEAD_PER_MSG = 4  # 每条消息的 role/结构开销
_COMPRESSION_SAFETY_MARGIN = 512  # 预留安全余量，防止估算偏差


def estimate_tokens(text: str) -> int:
    """粗略估算文本的 token 数。"""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN + 1)


def _estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """估算消息列表的总 token 数（含每条消息的 overhead）。"""
    total = 0
    for msg in messages:
        total += _TOKEN_OVERHEAD_PER_MSG
        total += estimate_tokens(msg.get("content", ""))
    return total


def compress_messages_to_budget(
    messages: list[dict[str, str]],
    context_window: int,
    max_tokens: int,
) -> list[dict[str, str]]:
    """当消息列表预估 token 数超出上下文窗口预算时，从历史消息头部截断。

    预算 = context_window - max_tokens - 安全余量
    始终保留 system 消息和最后一条 user 消息。
    如果截断后仍有历史消息被丢弃，插入一条提示告知 AI 上下文被压缩。
    """
    if not messages or context_window <= 0:
        return messages

    budget = context_window - max_tokens - _COMPRESSION_SAFETY_MARGIN
    if budget <= 0:
        # 上下文窗口太小，不做截断，交给 API 层面的错误处理
        return messages

    total = _estimate_messages_tokens(messages)
    if total <= budget:
        return messages  # 未超限，无需压缩

    # 分离 system 消息、历史消息、最后一条 user 消息
    system_msgs: list[dict[str, str]] = []
    history_msgs: list[dict[str, str]] = []
    last_user_msg: dict[str, str] | None = None

    for i, msg in enumerate(messages):
        if msg["role"] == "system":
            system_msgs.append(msg)
        elif i == len(messages) - 1 and msg["role"] == "user":
            last_user_msg = msg
        else:
            history_msgs.append(msg)

    # 计算固定部分的 token 开销
    fixed_tokens = 0
    for m in system_msgs:
        fixed_tokens += _TOKEN_OVERHEAD_PER_MSG + estimate_tokens(m["content"])
    if last_user_msg:
        fixed_tokens += _TOKEN_OVERHEAD_PER_MSG + estimate_tokens(last_user_msg["content"])

    # 压缩提示消息的 token 开销
    compression_notice = {
        "role": "system",
        "content": "[系统提示] 由于上下文长度限制，部分早期对话记录已被省略。请基于当前信息继续回答。",
    }
    notice_tokens = _TOKEN_OVERHEAD_PER_MSG + estimate_tokens(compression_notice["content"])

    # 为历史消息预留的 token 预算
    history_budget = budget - fixed_tokens - notice_tokens
    if history_budget <= 0:
        # 固定部分已占满预算，只能保留 system + user（无历史）
        result = list(system_msgs)
        if last_user_msg:
            result.append(last_user_msg)
        return result

    # 从最新的历史消息开始保留，直到预算用尽
    kept_history: list[dict[str, str]] = []
    used = 0
    for msg in reversed(history_msgs):
        msg_tokens = _TOKEN_OVERHEAD_PER_MSG + estimate_tokens(msg["content"])
        if used + msg_tokens > history_budget:
            break
        kept_history.insert(0, msg)
        used += msg_tokens

    # 组装最终消息列表
    result = list(system_msgs)
    if len(kept_history) < len(history_msgs):
        result.append(compression_notice)
    result.extend(kept_history)
    if last_user_msg:
        result.append(last_user_msg)
    return result


@dataclass
class LLMModel:
    """Runtime model config used by LLM service."""
    model_id: str
    name: str
    provider: str
    api_base: str
    api_key: str
    llm_model: str
    max_tokens: int = 4096
    temperature: float = 0.7
    enabled: bool = True


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class PromptTemplate:
    name: str
    description: str
    system_prompt: str
    user_prompt_template: str  # {content} placeholder for user input


@dataclass
class StreamChunk:
    delta: str
    finish_reason: str | None = None
    usage: dict | None = None
    reasoning_content: str = ""


def build_messages(
    template: PromptTemplate | None,
    history: list[ChatMessage],
    user_content: str,
    context: str | None = None,
    context_window: int = 0,
    max_tokens: int = 4096,
) -> list[dict[str, str]]:
    """Build the message list for the LLM API call.

    When context_window is set (>0), proactively compress conversation history
    to fit within the token budget (context_window - max_tokens - safety margin).
    """
    messages: list[dict[str, str]] = []

    # System prompt from template
    if template and template.system_prompt:
        messages.append({"role": "system", "content": template.system_prompt})

    # Conversation history
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    # Current user message — apply template if present
    if template and template.user_prompt_template:
        user_text = template.user_prompt_template.replace("{content}", user_content)
    else:
        user_text = user_content

    # Append file/URL context
    if context:
        user_text = f"{user_text}\n\n---\n参考资料：\n{context}"

    messages.append({"role": "user", "content": user_text})

    # 上下文窗口自动压缩：预估 token 超限时从历史头部截断
    if context_window > 0:
        messages = compress_messages_to_budget(
            messages, context_window=context_window, max_tokens=max_tokens,
        )

    return messages


def _model_test_retry_delay(headers, attempt: int, config: RetryConfig) -> float:
    retry_seconds = _parse_retry_after(headers)
    if retry_seconds is not None:
        return retry_seconds
    return min(
        config.initial_delay_ms / 1000.0 * (config.backoff_factor ** attempt),
        config.max_delay_ms / 1000.0,
    )


# 管理后台「测试模型」为交互式请求：保持轻量重试（5 次 / 单次等待上限 30s），
# 不随审查管线的 7 次长退避（2/4/8/16/32/64s）放大前端等待时间。
_MODEL_TEST_RETRY_CONFIG = RetryConfig(
    max_attempts=5,
    initial_delay_ms=2000,
    backoff_factor=2.0,
    max_delay_ms=30000,
    timeout_seconds=15.0,
    connect_timeout_seconds=5.0,
)


async def _post_model_test_with_retry(
    url: str,
    *,
    payload: dict,
    headers: dict,
    timeout: httpx.Timeout,
    config: RetryConfig = _MODEL_TEST_RETRY_CONFIG,
) -> tuple[httpx.Response | None, Exception | None]:
    last_resp: httpx.Response | None = None
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(config.max_attempts):
            try:
                resp = await client.post(url, json=payload, headers=headers)
                last_resp = resp
                last_error = None
                if resp.status_code == 200:
                    return resp, None
                if not _is_retryable_status(resp.status_code):
                    return resp, None
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_resp = None
                last_error = e
            except Exception as e:
                last_resp = None
                last_error = e

            if attempt < config.max_attempts - 1:
                delay = _model_test_retry_delay(getattr(last_resp, "headers", {}) if last_resp else {}, attempt, config)
                logger.warning("Model test retry attempt %d/%d, waiting %.1fs", attempt + 1, config.max_attempts, delay)
                await asyncio.sleep(delay)

    return last_resp, last_error


async def stream_chat(
    model_id: str,
    api_base: str,
    api_key: str,
    llm_model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 4096,
    temperature: float = 0.7,
    extra_body: dict | None = None,
) -> AsyncIterator[StreamChunk]:
    """Stream chat completion from an OpenAI-compatible API."""
    if not api_key:
        raise ValueError(f"No API key for model: {model_id}")

    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": llm_model,
        "messages": messages,
        "max_tokens": _cap_max_tokens(max_tokens),
        "temperature": temperature,
        "stream": True,
    }
    if extra_body:
        payload.update(extra_body)

    token_count = 0
    start_time = time.time()

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                logger.error("LLM API error %d: %s", resp.status_code, body.decode()[:500])
                raise RuntimeError(f"LLM API error {resp.status_code}: {body.decode()[:200]}")

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    elapsed = time.time() - start_time
                    yield StreamChunk(
                        delta="",
                        finish_reason="stop",
                        usage={"total_tokens": token_count, "elapsed_seconds": round(elapsed, 2)},
                    )
                    return

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = data.get("choices", [])
                if not choices:
                    continue

                delta_obj = choices[0].get("delta", {})
                delta_text = delta_obj.get("content", "")
                reasoning_text = delta_obj.get("reasoning_content") or ""
                finish_reason = choices[0].get("finish_reason")

                if delta_text:
                    token_count += 1
                if reasoning_text:
                    token_count += 1

                usage = None
                if finish_reason and "usage" in data:
                    usage = data["usage"]

                yield StreamChunk(
                    delta=delta_text,
                    finish_reason=finish_reason,
                    usage=usage,
                    reasoning_content=reasoning_text,
                )


async def check_connection(api_base: str, api_key: str, llm_model: str) -> dict:
    """Test if a model API connection works. Returns {status, detail}."""
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": llm_model,
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,
        "stream": False,
    }

    try:
        resp, error = await _post_model_test_with_retry(
            url,
            payload=payload,
            headers=headers,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        if resp and resp.status_code == 200:
            return {"status": "ok", "detail": "连接成功"}
        if resp:
            try:
                err = resp.json()
                detail = err.get("error", {}).get("message", resp.text[:200])
            except Exception:
                detail = resp.text[:200]
            return {"status": "fail", "detail": f"HTTP {resp.status_code}: {detail}"}
        if isinstance(error, httpx.TimeoutException):
            return {"status": "fail", "detail": "连接超时"}
        if isinstance(error, httpx.ConnectError):
            return {"status": "fail", "detail": "无法连接到服务器"}
        if error:
            return {"status": "fail", "detail": str(error)[:200]}
        return {"status": "fail", "detail": "未知错误"}
    except httpx.TimeoutException:
        return {"status": "fail", "detail": "连接超时"}
    except httpx.ConnectError:
        return {"status": "fail", "detail": "无法连接到服务器"}
    except Exception as e:
        return {"status": "fail", "detail": str(e)[:200]}


async def speed_test(api_base: str, api_key: str, llm_model: str) -> dict:
    """Speed test: send a simple prompt and measure latency. Returns {latency_ms, status}."""
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": llm_model,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 10,
        "stream": False,
    }

    start_time = time.time()
    try:
        resp, error = await _post_model_test_with_retry(
            url,
            payload=payload,
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        elapsed_ms = int((time.time() - start_time) * 1000)
        if resp and resp.status_code == 200:
            return {"status": "ok", "latency_ms": elapsed_ms}
        if resp:
            return {"status": "fail", "latency_ms": elapsed_ms, "detail": f"HTTP {resp.status_code}"}
        if isinstance(error, httpx.TimeoutException):
            return {"status": "fail", "latency_ms": elapsed_ms, "detail": "超时"}
        if error:
            return {"status": "fail", "latency_ms": elapsed_ms, "detail": str(error)[:100]}
        return {"status": "fail", "latency_ms": elapsed_ms, "detail": "未知错误"}
    except httpx.TimeoutException:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {"status": "fail", "latency_ms": elapsed_ms, "detail": "超时"}
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {"status": "fail", "latency_ms": elapsed_ms, "detail": str(e)[:100]}


async def non_stream_chat(
    model_id: str,
    api_base: str,
    api_key: str,
    llm_model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 4096,
    temperature: float = 0.7,
    extra_body: dict | None = None,
    workspace_id: int | None = None,
    user_id: int | None = None,
    mode: str | None = None,
) -> tuple[str, dict | None]:
    """Non-streaming chat completion — returns (full_text, usage)."""
    if not api_key:
        raise ValueError(f"No API key for model: {model_id}")

    from app.logging_config import log_llm_session
    start_time = time.time()

    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": llm_model,
        "messages": messages,
        "max_tokens": _cap_max_tokens(max_tokens),
        "temperature": temperature,
        "stream": False,
    }
    if extra_body:
        payload.update(extra_body)

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.error("LLM API error %d: %s", resp.status_code, resp.text[:500])
            raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        message = data["choices"][0].get("message", {})
        text = message.get("content") or ""
        reasoning_content = message.get("reasoning_content") or ""
        usage = data.get("usage")
        elapsed_ms = int((time.time() - start_time) * 1000)
        log_llm_session(
            llm_model,
            messages,
            text,
            usage,
            elapsed_ms=elapsed_ms,
            reasoning_content=reasoning_content,
            workspace_id=workspace_id,
            user_id=user_id,
            mode=mode,
        )
        return text, usage
