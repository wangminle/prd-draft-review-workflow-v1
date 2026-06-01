"""Pydantic 管理后台相关请求/响应模型"""

from pydantic import BaseModel, Field


class AdminCreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="user", pattern="^(user|admin)$")


class AdminUpdateUserRequest(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=50)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: str | None = Field(default=None, pattern="^(user|admin)$")
    is_active: bool | None = None


class AdminUserInfo(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: str


class AdminUserList(BaseModel):
    users: list[AdminUserInfo]
    total: int


class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None


class PromptTemplateDetail(BaseModel):
    id: int
    name: str
    description: str | None
    system_prompt: str | None
    user_prompt_template: str | None
    is_builtin: bool
    created_at: str


class SystemStats(BaseModel):
    total_users: int
    total_conversations: int
    total_messages: int
    active_models: int
    database_size_mb: float
