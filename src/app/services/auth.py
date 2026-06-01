"""认证服务：密码哈希、JWT 签发与验证"""

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

_settings = get_settings()
_sse_tickets: dict[str, dict] = {}


def _prune_expired_sse_tickets(now: datetime | None = None) -> None:
    current = now or datetime.now(timezone.utc)
    expired = [
        ticket
        for ticket, payload in _sse_tickets.items()
        if not isinstance(payload.get("expires_at"), datetime)
        or payload.get("expires_at") <= current
    ]
    for ticket in expired:
        _sse_tickets.pop(ticket, None)


def hash_password(password: str) -> str:
    """使用 bcrypt 对密码进行哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """验证密码与哈希是否匹配"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int, role: str) -> str:
    """创建 JWT access token"""
    auth_cfg = _settings["auth"]
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=auth_cfg["access_token_expire_minutes"]
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, auth_cfg["secret_key"], algorithm=auth_cfg["algorithm"])


def decode_token(token: str) -> dict:
    """解码并验证 JWT token

    Raises:
        JWTError: token 无效或已过期
    """
    auth_cfg = _settings["auth"]
    return jwt.decode(token, auth_cfg["secret_key"], algorithms=[auth_cfg["algorithm"]])


def issue_sse_ticket(user_id: int) -> str:
    """签发短时一次性 SSE 票据，避免在 URL 上传输主 JWT。"""
    auth_cfg = _settings.get("auth", {})
    ttl_seconds = int(auth_cfg.get("sse_ticket_ttl_seconds", 60))
    _prune_expired_sse_tickets()
    ticket = secrets.token_urlsafe(24)
    _sse_tickets[ticket] = {
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    }
    return ticket


def consume_sse_ticket(ticket: str) -> int | None:
    """消费一次性 SSE 票据，返回绑定用户 ID。"""
    _prune_expired_sse_tickets()
    payload = _sse_tickets.pop(ticket, None)
    if not payload:
        return None

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, datetime) or expires_at <= datetime.now(timezone.utc):
        return None

    user_id = payload.get("user_id")
    return int(user_id) if user_id is not None else None
