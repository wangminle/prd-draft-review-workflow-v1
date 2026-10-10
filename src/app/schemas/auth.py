"""Pydantic 认证相关请求/响应模型"""

from pydantic import BaseModel, Field, field_validator

# bcrypt 算法上限：密码 UTF-8 编码后不得超过 72 字节（BUG-197）
MAX_PASSWORD_BYTES = 72

PASSWORD_BYTES_MESSAGE = (
    f"密码过长：UTF-8 编码后不得超过 {MAX_PASSWORD_BYTES} 字节"
    "（约 72 个英文字符或 24 个中文字符）"
)


def _validate_password_bytes(v: str | None) -> str | None:
    """校验密码 UTF-8 字节长度不超过 bcrypt 上限，超限返回 422 而非 500。"""
    if v is not None and len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(PASSWORD_BYTES_MESSAGE)
    return v


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)

    _check_password_bytes = field_validator("password")(_validate_password_bytes)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: int
    username: str
    role: str
    created_at: str


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)

    _check_new_password_bytes = field_validator("new_password")(_validate_password_bytes)
