"""Workspace 资料库 API — P0.B 资料上传与管理"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.repositories.knowledge_source_repository import KnowledgeSourceRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.storage.knowledge_file_storage import KnowledgeFileStorage
from app.log_writers.audit_log_writer import AuditLogWriter

router = APIRouter()
_audit_log_writer = AuditLogWriter()
_knowledge_storage = KnowledgeFileStorage()

logger = logging.getLogger(__name__)

_MANAGE_ROLES = {"owner", "admin"}
_WRITE_ROLES = {"owner", "admin", "member"}
_READ_ROLES = {"owner", "admin", "member", "viewer"}


def _require_role(member, allowed_roles: set[str], action: str):
    """检查成员角色是否在允许范围内，否则抛出 403。"""
    if member is None:
        raise HTTPException(403, "你不是该空间的成员")
    if member.role not in allowed_roles:
        raise HTTPException(403, f"你的角色({member.role})不允许执行{action}操作")


def _source_to_info(source):
    tags = []
    if source.metadata_json:
        try:
            meta = json.loads(source.metadata_json)
            tags = meta.get("tags", [])
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": source.id,
        "workspace_id": source.workspace_id,
        "source_type": source.source_type,
        "title": source.title,
        "filename": source.filename,
        "file_id": source.file_id,
        "content_hash": source.content_hash,
        "version": source.version,
        "status": source.status,
        "tags": tags,
        "owner_name": source.owner.username if source.owner else "",
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


@router.get("/workspace")
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = WorkspaceRepository(db)
    workspaces = await repo.get_user_workspaces(user.id)
    return [
        {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "status": ws.status,
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
        }
        for ws in workspaces
    ]


@router.get("/workspace/{workspace_id}/members")
async def list_members(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = WorkspaceRepository(db)
    ws = await repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await repo.get_member(workspace_id, user.id)
    _require_role(member, _READ_ROLES, "查看成员")

    members = await repo.list_members(workspace_id)
    result = []
    for m in members:
        username = m.user.username if m.user else ""
        result.append({
            "id": m.id,
            "user_id": m.user_id,
            "username": username,
            "role": m.role,
            "status": m.status,
        })
    return result


@router.get("/workspace/{workspace_id}/sources")
async def list_sources(
    workspace_id: int,
    source_type: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = WorkspaceRepository(db)
    ws = await repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await repo.get_member(workspace_id, user.id)
    _require_role(member, _READ_ROLES, "查看资料")

    ks_repo = KnowledgeSourceRepository(db)
    sources = await ks_repo.list_by_workspace(workspace_id, source_type=source_type, status=status, tag=tag, offset=offset, limit=limit)
    return [_source_to_info(s) for s in sources]


@router.delete("/workspace/{workspace_id}/sources/{source_id}")
async def delete_source(
    workspace_id: int,
    source_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await ws_repo.get_member(workspace_id, user.id)
    _require_role(member, _MANAGE_ROLES, "删除资料")

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(404, "资料不存在")

    result = await ks_repo.archive(source_id)
    if result is None:
        raise HTTPException(404, "资料不存在")

    await db.commit()
    _audit_log_writer.write(
        "source.delete",
        actor=user,
        request=request,
        target_type="knowledge_source",
        target_id=source_id,
        detail={"source_id": source_id, "title": source.title},
    )
    return {"message": "已删除"}


@router.put("/workspace/{workspace_id}/sources/{source_id}/tags")
async def update_source_tags(
    workspace_id: int,
    source_id: int,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await ws_repo.get_member(workspace_id, user.id)
    _require_role(member, _MANAGE_ROLES, "修改标签")

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(404, "资料不存在")

    tags = body.get("tags", [])
    if not isinstance(tags, list):
        raise HTTPException(status_code=422, detail="tags 必须是字符串数组")

    meta = {}
    if source.metadata_json:
        try:
            meta = json.loads(source.metadata_json)
        except (json.JSONDecodeError, TypeError):
            pass
    meta["tags"] = tags
    source.metadata_json = json.dumps(meta, ensure_ascii=False)
    source.version += 1
    await db.commit()

    _audit_log_writer.write(
        "source.update_tags",
        actor=user,
        request=request,
        target_type="knowledge_source",
        target_id=source_id,
        detail={"source_id": source_id, "tags": tags},
    )
    return _source_to_info(source)


@router.post("/workspace/{workspace_id}/sources")
async def upload_source(
    workspace_id: int,
    file: UploadFile = File(...),
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P0.B.1: 上传文件到团队资料库，解析为 KnowledgeSource"""
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await ws_repo.get_member(workspace_id, user.id)
    _require_role(member, _WRITE_ROLES, "上传资料")

    content = await file.read()
    max_size = 20 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(413, "文件过大，最大允许 20MB")

    filename = file.filename or "upload"
    stored = _knowledge_storage.save_upload(filename=filename, content=content)

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.create(
        workspace_id=workspace_id,
        source_type="upload",
        title=filename,
        filename=stored.original_filename,
        file_id=stored.file_id,
        content_hash=stored.content_hash,
        extracted_text=stored.extracted_text,
        owner_id=user.id,
    )
    await db.commit()

    _audit_log_writer.write(
        "source.upload",
        actor=user,
        request=request,
        target_type="knowledge_source",
        target_id=source.id,
        detail={"source_id": source.id, "title": filename, "content_hash": stored.content_hash},
    )

    info = _source_to_info(source)
    info["extracted_text"] = source.extracted_text
    return info


@router.get("/workspace/{workspace_id}/sources/{source_id}")
async def get_source_detail(
    workspace_id: int,
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await ws_repo.get_member(workspace_id, user.id)
    _require_role(member, _READ_ROLES, "查看资料详情")

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(404, "资料不存在")

    info = _source_to_info(source)
    info["extracted_text"] = source.extracted_text

    from app.repositories.knowledge_source_repository import ProjectSourceRefRepository
    ref_repo = ProjectSourceRefRepository(db)
    refs = await ref_repo.list_by_source(source_id)
    info["project_refs"] = [
        {"project_id": r.project_id, "ref_type": r.ref_type, "snapshot_version": r.snapshot_version}
        for r in refs
    ]

    return info


@router.get("/workspace/{workspace_id}/sources/{source_id}/download")
async def download_source_file(
    workspace_id: int,
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await ws_repo.get_member(workspace_id, user.id)
    _require_role(member, _READ_ROLES, "下载资料")

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(404, "资料不存在")

    if not source.file_id:
        raise HTTPException(404, "资料没有可下载的文件")

    content = _knowledge_storage.read_file(source.file_id)
    if content is None:
        raise HTTPException(404, "文件不存在或已被删除")

    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={source.filename or source.file_id}"},
    )
