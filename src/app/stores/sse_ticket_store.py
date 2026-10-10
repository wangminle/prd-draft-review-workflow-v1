"""SseTicketStore — 进程内短时单向票据存储器。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone


class SseTicketStore:
    """包装 in-memory SSE 票据字典，提供安全访问入口。"""

    def __init__(self):
        self._tickets: dict[str, dict] = {}

    def _prune_expired(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        expired = [
            ticket
            for ticket, payload in self._tickets.items()
            if not isinstance(payload.get("expires_at"), datetime)
            or payload.get("expires_at") <= current
        ]
        for ticket in expired:
            self._tickets.pop(ticket, None)

    def issue(self, user_id: int, ttl_seconds: int = 60, auth_version: int = 1) -> str:
        self._prune_expired()
        ticket = secrets.token_urlsafe(24)
        self._tickets[ticket] = {
            "user_id": user_id,
            # BUG-198：票据绑定签发时的会话版本号，消费时与 users.auth_version 比对
            "auth_version": auth_version,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        }
        return ticket

    def consume(self, ticket: str) -> dict | None:
        """消费一次性票据，返回 {"user_id", "auth_version"}；无效/过期返回 None。"""
        self._prune_expired()
        payload = self._tickets.pop(ticket, None)
        if not payload:
            return None

        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, datetime) or expires_at <= datetime.now(timezone.utc):
            return None

        user_id = payload.get("user_id")
        if user_id is None:
            return None
        # 旧格式票据（无 auth_version）按 0 处理，与任何有效会话版本都不匹配
        return {
            "user_id": int(user_id),
            "auth_version": int(payload.get("auth_version") or 0),
        }
