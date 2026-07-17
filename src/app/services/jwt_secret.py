"""JWT secret 安全校验 — 拒绝示例/弱/过短密钥。"""

from __future__ import annotations

# 已知不安全的示例/占位密钥（含历史默认值与 .env.example 曾公开的固定值）
INSECURE_JWT_SECRETS = frozenset({
    "change-me-in-production",
    "change-this-to-a-random-secret-string",
    "secret",
    "jwt-secret",
    "your-secret-key",
})

MIN_JWT_SECRET_LENGTH = 32


def assert_jwt_secret_safe(secret: str | None) -> str:
    """校验 JWT secret 可用；不安全则抛 RuntimeError。"""
    if not secret or not str(secret).strip():
        raise RuntimeError("JWT secret 未配置，请设置 .env 中的 JWT_SECRET（至少 32 字符随机串）")
    value = str(secret).strip()
    if value in INSECURE_JWT_SECRETS:
        raise RuntimeError(
            "JWT secret 使用了公开示例/默认值，存在伪造 Token 风险。"
            "请设置随机密钥，例如: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if len(value) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT secret 过短（当前 {len(value)} 字符），请使用至少 {MIN_JWT_SECRET_LENGTH} 字符的随机串"
        )
    return value
