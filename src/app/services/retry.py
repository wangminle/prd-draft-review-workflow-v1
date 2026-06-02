import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


class ContextOverflowError(Exception):
    pass


class LLMRetryError(Exception):
    pass


_OVERFLOW_PATTERNS = [
    r"exceeds.*context.?window",
    r"maximum.*context.*length.*\d+",
    r"prompt.*too.*long",
    r"token.*count.*exceeds",
    r"context_length_exceeded",
    r"input.*too.*long",
    r"reduce.*length.*messages",
    r"exceeds.*limit.*\d+",
    r"request entity too large",
    r"context length is only \d+",
    r"input length.*exceeds.*context",
    r"prompt too long.*exceeded.*context",
    r"too large for model",
    r"model_context_window_exceeded",
]

_OVERFLOW_RE = re.compile("|".join(_OVERFLOW_PATTERNS), re.IGNORECASE)


@dataclass
class RetryConfig:
    max_attempts: int = 5
    initial_delay_ms: int = 2000
    backoff_factor: float = 2.0
    max_delay_ms: int = 30000
    timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 10.0


def _is_context_overflow(error_text: str) -> bool:
    return bool(_OVERFLOW_RE.search(error_text))


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _parse_retry_after(headers: httpx.Headers) -> float | None:
    retry_ms = headers.get("retry-after-ms")
    if retry_ms:
        try:
            return float(retry_ms) / 1000.0
        except ValueError:
            pass

    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass

    return None


async def retryable_chat(
    messages: list[dict[str, str]],
    *,
    api_base: str,
    api_key: str,
    llm_model: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    extra_body: dict | None = None,
    config: RetryConfig = RetryConfig(),
) -> tuple[str, dict | None]:
    from app.logging_config import log_llm_session
    start_time = time.time()
    last_error = None

    for attempt in range(config.max_attempts):
        try:
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
            if extra_body:
                payload.update(extra_body)

            timeout = httpx.Timeout(
                config.timeout_seconds,
                connect=config.connect_timeout_seconds,
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code == 200:
                data = resp.json()
                message = data["choices"][0].get("message", {})
                text = message.get("content")
                reasoning_content = message.get("reasoning_content", "") or ""
                if not isinstance(text, str) or not text.strip():
                    finish_reason = data["choices"][0].get("finish_reason")
                    raise ValueError(f"LLM returned empty content (finish_reason={finish_reason})")
                usage = data.get("usage")
                elapsed_ms = int((time.time() - start_time) * 1000)
                log_llm_session(llm_model, messages, text, usage, elapsed_ms=elapsed_ms, reasoning_content=reasoning_content)
                return text, usage

            error_text = resp.text[:500]

            if _is_context_overflow(error_text):
                raise ContextOverflowError(f"Context overflow: {error_text[:200]}")

            if _is_retryable_status(resp.status_code):
                retry_seconds = _parse_retry_after(resp.headers)
                if retry_seconds is None:
                    retry_seconds = min(
                        config.initial_delay_ms / 1000.0 * (config.backoff_factor ** attempt),
                        config.max_delay_ms / 1000.0,
                    )

                logger.warning(
                    "LLM API retryable error %d, attempt %d/%d, waiting %.1fs",
                    resp.status_code, attempt + 1, config.max_attempts, retry_seconds,
                )
                last_error = RuntimeError(f"LLM API error {resp.status_code}: {error_text[:200]}")
                await asyncio.sleep(retry_seconds)
                continue

            raise RuntimeError(f"LLM API error {resp.status_code}: {error_text[:200]}")

        except ContextOverflowError:
            raise
        except httpx.TimeoutException as e:
            last_error = e
            delay = min(
                config.initial_delay_ms / 1000.0 * (config.backoff_factor ** attempt),
                config.max_delay_ms / 1000.0,
            )
            logger.warning("LLM timeout, attempt %d/%d, waiting %.1fs", attempt + 1, config.max_attempts, delay)
            await asyncio.sleep(delay)
            continue
        except httpx.ConnectError as e:
            last_error = e
            delay = min(
                config.initial_delay_ms / 1000.0 * (config.backoff_factor ** attempt),
                config.max_delay_ms / 1000.0,
            )
            logger.warning("LLM connection error, attempt %d/%d, waiting %.1fs", attempt + 1, config.max_attempts, delay)
            await asyncio.sleep(delay)
            continue
        except (RuntimeError, LLMRetryError):
            raise
        except Exception as e:
            last_error = e
            delay = min(
                config.initial_delay_ms / 1000.0 * (config.backoff_factor ** attempt),
                config.max_delay_ms / 1000.0,
            )
            logger.warning("LLM unexpected error, attempt %d/%d: %s", attempt + 1, config.max_attempts, e)
            await asyncio.sleep(delay)
            continue

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_llm_session(llm_model, messages, "", None, elapsed_ms=elapsed_ms, error=str(last_error))
    raise LLMRetryError(f"LLM retry exhausted after {config.max_attempts} attempts: {last_error}")


async def structured_chat(
    messages: list[dict[str, str]],
    *,
    api_base: str,
    api_key: str,
    llm_model: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    extra_body: dict | None = None,
    config: RetryConfig = RetryConfig(),
) -> dict:
    text, usage = await retryable_chat(
        messages,
        api_base=api_base,
        api_key=api_key,
        llm_model=llm_model,
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body=extra_body,
        config=config,
    )
    return _parse_json_response(text)


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return {"raw_text": text}
