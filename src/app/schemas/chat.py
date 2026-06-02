"""Pydantic 对话相关请求/响应模型"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    model_id: str = Field(default="deepseek", max_length=30)
    prompt_template: str | None = "default"
    message: str = Field(..., min_length=1)
    file_ids: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    url_texts: dict[str, str] = Field(default_factory=dict)
    context_rules: list[str] = Field(default_factory=list)
    mention_context_item_ids: list[int] = Field(default_factory=list)
    thinking_level: str | None = None
    stream: bool = True


class ChatResponse(BaseModel):
    conversation_id: int
    content: str


class ModelInfo(BaseModel):
    id: str
    name: str
    enabled: bool
    thinking_supported: bool = False
    thinking_level: str = "off"


class ModelList(BaseModel):
    models: list[ModelInfo]


class PromptTemplateInfo(BaseModel):
    id: int
    name: str
    description: str | None


class ContextItemCreate(BaseModel):
    context_type: str = Field(..., max_length=30)
    title: str = Field(..., max_length=200)
    file_id: str | None = None
    url: str | None = None
    manual_text: str | None = None
    extracted_text: str | None = None
    enabled: bool = True


class ContextItemUpdate(BaseModel):
    title: str | None = None
    enabled: bool | None = None


class ContextItemInfo(BaseModel):
    id: int
    context_type: str
    title: str
    file_id: str | None
    url: str | None
    manual_text: str | None
    extracted_text: str | None
    enabled: bool
    created_at: str
