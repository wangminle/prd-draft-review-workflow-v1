"""认证服务：密码哈希、JWT 签发与验证"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import bcrypt
from jose import jwt

from app.config import get_settings
from app.stores.sse_ticket_store import SseTicketStore

if TYPE_CHECKING:
    from app.models.user import User

_settings = get_settings()
_sse_ticket_store = SseTicketStore()

# bcrypt 算法上限：密码 UTF-8 编码后不得超过 72 字节（BUG-197）
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    """使用 bcrypt 对密码进行哈希

    Raises:
        ValueError: 密码 UTF-8 编码后超过 72 字节（bcrypt 上限）
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"密码过长：UTF-8 编码后不得超过 {MAX_PASSWORD_BYTES} 字节"
        )
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """验证密码与哈希是否匹配；超长等非法输入按不匹配处理（BUG-197）"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str, auth_version: int = 1) -> str:
    """创建 JWT access token，av 为用户会话版本号（BUG-196）"""
    auth_cfg = _settings["auth"]
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=auth_cfg["access_token_expire_minutes"]
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "av": auth_version,
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


def issue_sse_ticket(user_id: int, auth_version: int = 1) -> str:
    """签发短时一次性 SSE 票据（绑定会话版本号），避免在 URL 上传输主 JWT。"""
    auth_cfg = _settings.get("auth", {})
    ttl_seconds = int(auth_cfg.get("sse_ticket_ttl_seconds", 60))
    return _sse_ticket_store.issue(user_id, ttl_seconds, auth_version)


def consume_sse_ticket(ticket: str) -> dict | None:
    """消费一次性 SSE 票据，返回 {"user_id", "auth_version"} 或 None。"""
    return _sse_ticket_store.consume(ticket)


async def validate_sse_ticket(ticket: str, db) -> User | None:
    """消费票据并校验用户与会话版本（BUG-198）。

    改密/管理员重置密码会递增 users.auth_version，此前签发的票据
    在消费时因版本不匹配立即失效。
    """
    payload = consume_sse_ticket(ticket)
    if payload is None:
        return None
    from app.repositories.user_repository import UserRepository

    user = await UserRepository(db).get_by_id(payload["user_id"])
    if user is None or not user.is_active:
        return None
    if payload["auth_version"] != (user.auth_version or 1):
        return None
    return user


async def is_session_alive(db, user_id: int, auth_version: int) -> bool:
    """长连接存活校验（BUG-198）：用户存在、启用且会话版本未发生变化。

    用原生 SQL 绕过会话身份映射缓存，并在读前 rollback 释放读事务快照，
    确保长连接存活期间能观察到其他会话已提交的 auth_version 变更。
    """
    from sqlalchemy import text as sa_text

    # 读前后各 rollback 一次：读前释放旧快照以观察到其他会话已提交的
    # auth_version 变更；读后立即释放 SHARED 锁，避免长连接会话阻塞写事务
    # （SQLite 回滚日志模式下读锁会阻塞写提交）。
    await db.rollback()
    result = await db.execute(
        sa_text("SELECT auth_version, is_active FROM users WHERE id = :id"),
        {"id": user_id},
    )
    row = result.first()
    await db.rollback()
    if row is None or not row[1]:
        return False
    return (row[0] or 1) == auth_version
