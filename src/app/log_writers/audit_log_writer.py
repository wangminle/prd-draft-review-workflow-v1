"""AuditLogWriter — 结构化业务审计日志写入。"""

from __future__ import annotations

from app.logging_config import log_audit


class AuditLogWriter:
    def write(
        self,
        action: str,
        *,
        actor=None,
        request=None,
        target_type: str | None = None,
        target_id: int | str | None = None,
        result: str = "success",
        detail: dict | None = None,
        level: str = "info",
    ) -> None:
        log_audit(
            action,
            actor=actor,
            request=request,
            target_type=target_type,
            target_id=target_id,
            result=result,
            detail=detail,
            level=level,
        )