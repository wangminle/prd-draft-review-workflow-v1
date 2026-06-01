"""Pydantic 历史记录相关请求/响应模型"""

from pydantic import BaseModel, Field


class MessageInfo(BaseModel):
    id: int
    role: str
    content: str
    token_count: int | None
    created_at: str


class ConversationInfo(BaseModel):
    id: int
    title: str | None
    model_id: str
    created_at: str
    updated_at: str
    message_count: int = 0


class ConversationDetail(BaseModel):
    id: int
    title: str | None
    model_id: str
    messages: list[MessageInfo]


class SearchResult(BaseModel):
    conversation_id: int
    message_id: int
    role: str
    content: str
    created_at: str


class SearchResults(BaseModel):
    results: list[SearchResult]
    total: int


class PaginatedConversations(BaseModel):
    conversations: list[ConversationInfo]
    total: int
    page: int
    page_size: int
