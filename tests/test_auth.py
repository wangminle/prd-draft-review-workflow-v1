"""测试认证服务 (app.services.auth)"""

import pytest
from jose import JWTError

from app.services.auth import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        """密码哈希和验证应正确工作"""
        password = "test_password_123"
        hashed = hash_password(password)

        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        """错误密码应验证失败"""
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_different_hashes_for_same_password(self):
        """相同密码每次哈希结果应不同（salt）"""
        password = "test"
        h1 = hash_password(password)
        h2 = hash_password(password)
        assert h1 != h2


class TestJWT:
    def test_create_and_decode_token(self):
        """JWT 签发和解析应正确"""
        token = create_access_token(user_id=1, role="admin")
        payload = decode_token(token)

        assert payload["sub"] == "1"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_user_token(self):
        """普通用户角色应正确写入 token"""
        token = create_access_token(user_id=42, role="user")
        payload = decode_token(token)

        assert payload["sub"] == "42"
        assert payload["role"] == "user"

    def test_invalid_token_raises_error(self):
        """无效 token 应抛出 JWTError"""
        with pytest.raises(JWTError):
            decode_token("invalid.token.here")

    def test_expired_token_raises_error(self):
        """过期 token 应抛出异常"""
        from jose import jwt as jose_jwt
        from app.config import get_settings

        settings = get_settings()
        expired = jose_jwt.encode(
            {"sub": "1", "role": "user", "exp": 0},
            settings["auth"]["secret_key"],
            algorithm=settings["auth"]["algorithm"],
        )

        with pytest.raises(JWTError):
            decode_token(expired)
