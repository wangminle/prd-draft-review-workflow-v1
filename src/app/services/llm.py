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


def build_messages(
    template: PromptTemplate | None,
    history: list[ChatMessage],
    user_content: str,
    context: str | None = None,
) -> list[dict[str, str]]:
    """Build the message list for the LLM API call."""
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
    return messages


def _model_test_retry_delay(headers, attempt: int, config: RetryConfig) -> float:
    retry_seconds = _parse_retry_after(headers)
    if retry_seconds is not None:
        return retry_seconds
    return min(
        config.initial_delay_ms / 1000.0 * (config.backoff_factor ** attempt),
        config.max_delay_ms / 1000.0,
    )


async def _post_model_test_with_retry(
    url: str,
    *,
    payload: dict,
    headers: dict,
    timeout: httpx.Timeout,
    config: RetryConfig = RetryConfig(),
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
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }

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
                finish_reason = choices[0].get("finish_reason")

                if delta_text:
                    token_count += 1

                usage = None
                if finish_reason and "usage" in data:
                    usage = data["usage"]

                yield StreamChunk(delta=delta_text, finish_reason=finish_reason, usage=usage)


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
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.error("LLM API error %d: %s", resp.status_code, resp.text[:500])
            raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage")
        elapsed_ms = int((time.time() - start_time) * 1000)
        log_llm_session(llm_model, messages, text, usage, elapsed_ms=elapsed_ms)
        return text, usage
