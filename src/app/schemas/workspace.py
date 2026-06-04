from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TagUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list)


class SourceRefCreate(BaseModel):
    source_id: int
    ref_type: str = Field(default="context", pattern="^(context|reference|background)$")
    snapshot_version: int | None = None


class SourceRefInfo(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    project_id: int
    source_id: int
    ref_type: str
    snapshot_version: int | None
    created_at: datetime | None = None


class SourceInfo(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    workspace_id: int
    source_type: str
    title: str
    filename: str | None
    content_hash: str | None
    version: int
    status: str
    tags: list[str] = []
    created_at: datetime | None
    updated_at: datetime | None
