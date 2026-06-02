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

    def issue(self, user_id: int, ttl_seconds: int = 60) -> str:
        self._prune_expired()
        ticket = secrets.token_urlsafe(24)
        self._tickets[ticket] = {
            "user_id": user_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        }
        return ticket

    def consume(self, ticket: str) -> int | None:
        self._prune_expired()
        payload = self._tickets.pop(ticket, None)
        if not payload:
            return None

        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, datetime) or expires_at <= datetime.now(timezone.utc):
            return None

        user_id = payload.get("user_id")
        return int(user_id) if user_id is not None else None
