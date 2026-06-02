"""认证服务：密码哈希、JWT 签发与验证"""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings
from app.stores.sse_ticket_store import SseTicketStore

_settings = get_settings()
_sse_ticket_store = SseTicketStore()


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
    return _sse_ticket_store.issue(user_id, ttl_seconds)


def consume_sse_ticket(ticket: str) -> int | None:
    """消费一次性 SSE 票据，返回绑定用户 ID。"""
    return _sse_ticket_store.consume(ticket)
