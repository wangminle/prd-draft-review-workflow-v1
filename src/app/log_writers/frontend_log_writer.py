"""FrontendLogWriter — 浏览器端上报日志写入。"""

from __future__ import annotations

from app.logging_config import log_frontend


class FrontendLogWriter:
    def write(
        self,
        *,
        level: str,
        message: str,
        page: str | None = None,
        detail: dict | None = None,
    ) -> None:
        log_frontend(level, message, page=page, detail=detail)