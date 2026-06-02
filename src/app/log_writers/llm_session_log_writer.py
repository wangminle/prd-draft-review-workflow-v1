"""LlmSessionLogWriter — 每次 LLM 调用日志写入。"""

from __future__ import annotations

from app.logging_config import log_llm_session


class LlmSessionLogWriter:
    def write(
        self,
        *,
        model: str,
        messages: list[dict],
        response: str | dict,
        usage: dict | None = None,
        elapsed_ms: int | None = None,
        error: str | None = None,
        reasoning_content: str | None = None,
    ) -> None:
        log_llm_session(
            model,
            messages,
            response,
            usage=usage,
            elapsed_ms=elapsed_ms,
            error=error,
            reasoning_content=reasoning_content,
        )
