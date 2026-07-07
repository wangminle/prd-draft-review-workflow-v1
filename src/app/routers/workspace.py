"""Workspace 资料库 API — P0.B 资料上传与管理 + P2.B 检索 API"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.repositories.knowledge_source_repository import KnowledgeSourceRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.workspace_access import require_action
from app.storage.knowledge_file_storage import KnowledgeFileStorage
from app.log_writers.audit_log_writer import AuditLogWriter

router = APIRouter()
_audit_log_writer = AuditLogWriter()
_knowledge_storage = KnowledgeFileStorage()

logger = logging.getLogger(__name__)


def _assert_team_source_readable(source, user: User) -> None:
    """BUG-086: 团队资料 API 不可读取他人 private 资料。"""
    if source.visibility == "private" and source.owner_type == "user":
        if source.owner_id != user.id:
            raise HTTPException(404, "资料不存在")


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
        "owner_type": source.owner_type,
        "visibility": source.visibility,
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
            "is_default": ws.is_default,
            "status": ws.status,
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
        }
        for ws in workspaces
    ]


@router.get("/workspace/default")
async def get_default_workspace(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = WorkspaceRepository(db)
    ws = await repo.get_default()
    if ws is None:
        raise HTTPException(404, "默认团队空间不存在")
    member = await repo.get_member(ws.id, user.id)
    require_action(member, "read", "查看团队空间")
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "is_default": ws.is_default,
        "status": ws.status,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


@router.put("/workspace/default")
async def update_default_workspace(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = WorkspaceRepository(db)
    ws = await repo.get_default()
    if ws is None:
        raise HTTPException(404, "默认团队空间不存在")
    member = await repo.get_member(ws.id, user.id)
    require_action(member, "manage", "更新团队空间")

    new_name = body.get("name")
    new_description = body.get("description")
    new_status = body.get("status")
    if new_name is not None:
        if not isinstance(new_name, str) or not new_name.strip():
            raise HTTPException(422, "团队名称不能为空")
        ws.name = new_name.strip()
    if new_description is not None:
        ws.description = new_description
    if new_status is not None:
        valid_statuses = ("active", "archived")
        if new_status not in valid_statuses:
            raise HTTPException(422, f"无效状态，允许值: {', '.join(valid_statuses)}")
        ws.status = new_status

    await db.commit()

    _audit_log_writer.write(
        "workspace.update",
        actor=user,
        request=request,
        target_type="workspace",
        target_id=ws.id,
        detail={"name": ws.name, "description": ws.description, "status": ws.status},
    )
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "is_default": ws.is_default,
        "status": ws.status,
    }


@router.get("/workspace/default/members")
async def list_default_members(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P1.A.2: 获取默认团队空间成员列表（含 inactive，管理员可恢复）"""
    repo = WorkspaceRepository(db)
    ws = await repo.get_default()
    if ws is None:
        raise HTTPException(404, "默认团队空间不存在")

    member = await repo.get_member(ws.id, user.id)
    require_action(member, "read", "查看成员")

    members = await repo.list_members_all(ws.id)
    return [
        {
            "id": m.id,
            "user_id": m.user_id,
            "username": m.user.username if m.user else "",
            "role": m.role,
            "status": m.status,
        }
        for m in members
    ]


@router.put("/workspace/default/members/{user_id}")
async def update_default_member(
    user_id: int,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P1.A.2: 变更成员角色或停用/恢复成员"""
    repo = WorkspaceRepository(db)
    ws = await repo.get_default()
    if ws is None:
        raise HTTPException(404, "默认团队空间不存在")

    caller = await repo.get_member(ws.id, user.id)
    require_action(caller, "manage", "管理成员")

    # 禁止变更自身角色/状态
    if user_id == user.id:
        raise HTTPException(403, "不能变更自身的角色或状态")

    target = await repo.get_member_any_status(ws.id, user_id)
    if target is None:
        raise HTTPException(404, "该用户不是团队成员")

    new_role = body.get("role")
    new_status = body.get("status")

    if new_role is not None:
        valid_roles = ("owner", "admin", "member", "viewer")
        if new_role not in valid_roles:
            raise HTTPException(422, f"无效角色，允许值: {', '.join(valid_roles)}")
        target = await repo.update_member_role(ws.id, user_id, new_role)

    if new_status is not None:
        valid_statuses = ("active", "inactive")
        if new_status not in valid_statuses:
            raise HTTPException(422, f"无效状态，允许值: {', '.join(valid_statuses)}")
        target.status = new_status
        await db.flush()

    await db.commit()

    # Refresh target to get latest state; fetch user separately for username
    await db.refresh(target)
    target_user = await db.execute(select(User).where(User.id == target.user_id))
    target_user_obj = target_user.scalar_one_or_none()

    _audit_log_writer.write(
        "workspace.update_member",
        actor=user,
        request=request,
        target_type="workspace_member",
        target_id=user_id,
        detail={"role": target.role, "status": target.status, "user_id": user_id},
    )
    return {
        "id": target.id,
        "user_id": target.user_id,
        "username": target_user_obj.username if target_user_obj else "",
        "role": target.role,
        "status": target.status,
    }


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
    require_action(member, "read", "查看成员")

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
    owner_type: str | None = None,
    visibility: str | None = None,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P0.B.2 + P5.A.1: 列出资料，支持 owner_type/visibility 过滤"""
    # BUG-108: 团队资料列表不允许筛选 owner_type=user 的个人私有资料。
    # 仓储层 list_by_workspace 只按 workspace_id+owner_type+visibility 过滤、不绑定 owner_id，
    # 若放行 owner_type=user 会返回同空间所有成员的私有资料元数据，造成越权枚举。
    # 个人资料请通过 /workspace/personal/sources 端点访问（仅返回 owner_id=当前用户 的记录）。
    if owner_type == "user":
        raise HTTPException(400, "个人资料请通过个人资料接口访问")

    repo = WorkspaceRepository(db)
    ws = await repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await repo.get_member(workspace_id, user.id)
    require_action(member, "read", "查看资料")

    ks_repo = KnowledgeSourceRepository(db)
    sources = await ks_repo.list_by_workspace(
        workspace_id,
        source_type=source_type,
        status=status,
        tag=tag,
        owner_type=owner_type,
        visibility=visibility,
        offset=offset,
        limit=limit,
    )
    return [_source_to_info(s) for s in sources]


@router.delete("/workspace/{workspace_id}/sources/{source_id}")
async def delete_source(
    workspace_id: int,
    source_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P0.B.3 + P5.A.1: 删除资料（软删除）——团队资料需 manage 权限，个人资料需 owner 本人"""
    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(404, "资料不存在")

    # P5.A.1: 个人资料权限判断
    if source.owner_type == "user":
        if source.owner_id != user.id:
            raise HTTPException(403, "只能删除自己的个人资料")
        # BUG-076 修复：校验 workspace_id 归属，确保审计日志上下文正确
        if source.workspace_id is not None and source.workspace_id != workspace_id:
            raise HTTPException(404, "资料不存在")
    else:
        # 团队资料需要 manage 权限
        if source.workspace_id != workspace_id:
            raise HTTPException(404, "资料不存在")
        ws_repo = WorkspaceRepository(db)
        ws = await ws_repo.get_by_id(workspace_id)
        if ws is None:
            raise HTTPException(404, "空间不存在")
        member = await ws_repo.get_member(workspace_id, user.id)
        require_action(member, "manage", "删除资料")

    result = await ks_repo.archive(source_id)
    if result is None:
        raise HTTPException(404, "资料不存在")

    # 归档资料后必须同步移除检索索引，避免已删除资料继续被 RAG 召回。
    try:
        from app.services.knowledge_vector_service import get_knowledge_vector_service
        from app.services.knowledge_ingestion import KnowledgeIngestionService
        await get_knowledge_vector_service().delete_by_source(source_id)
        await KnowledgeIngestionService(db)._cleanup_fts_entries(source_id)
    except Exception as e:
        logger.warning(f"[SOURCE] 清理资料检索索引失败 source_id={source_id}: {e}")

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
    require_action(member, "manage", "修改标签")

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(404, "资料不存在")

    tags = body.get("tags", [])
    if not isinstance(tags, list):
        raise HTTPException(status_code=422, detail="tags 必须是字符串数组")
    if len(tags) > 20:
        raise HTTPException(status_code=422, detail="标签数量不能超过 20 个")
    for tag in tags:
        if not isinstance(tag, str):
            raise HTTPException(status_code=422, detail="每个标签必须是字符串")

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
    visibility: str = "team",
    file: UploadFile = File(...),
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P0.B.1 + P5.A.1: 上传文件到资料库，支持 visibility=team/private"""
    from app.models.workspace import VALID_VISIBILITIES
    if visibility not in VALID_VISIBILITIES:
        raise HTTPException(422, f"无效 visibility，允许值: {', '.join(VALID_VISIBILITIES)}")

    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    # visibility=private 不需要 write 权限（个人资料），但仍需是成员
    if visibility == "team":
        member = await ws_repo.get_member(workspace_id, user.id)
        require_action(member, "write", "上传团队资料")
    else:
        # private: 只需是团队成员即可
        member = await ws_repo.get_member(workspace_id, user.id)
        require_action(member, "read", "上传个人资料")

    content = await file.read()
    max_size = 20 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(413, "文件过大，最大允许 20MB")

    filename = file.filename or "upload"
    stored = _knowledge_storage.save_upload(filename=filename, content=content)

    ks_repo = KnowledgeSourceRepository(db)
    owner_type = "user" if visibility == "private" else "workspace"
    source = await ks_repo.create(
        workspace_id=workspace_id,
        source_type="upload",
        title=filename,
        filename=stored.original_filename,
        file_id=stored.file_id,
        content_hash=stored.content_hash,
        extracted_text=stored.extracted_text,
        owner_id=user.id,
        owner_type=owner_type,
        visibility=visibility,
    )

    # P2.A.3: 上传后同步完成解析正文的切块与 FTS5 索引；向量索引可由后续 embedding 流程补齐。
    if stored.extracted_text and stored.extracted_text.strip():
        try:
            from app.services.knowledge_ingestion import KnowledgeIngestionService
            await KnowledgeIngestionService(db).ingest_source(source.id)
        except Exception as e:
            logger.error(f"[INGEST] 上传后自动入库失败 source_id={source.id}: {e}")
            source.status = "failed"
            await db.commit()
            raise HTTPException(500, "资料上传成功但入库失败，请稍后重试")

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
    require_action(member, "read", "查看资料详情")

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(404, "资料不存在")

    _assert_team_source_readable(source, user)

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
    require_action(member, "read", "下载资料")

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(404, "资料不存在")

    _assert_team_source_readable(source, user)

    if not source.file_id:
        raise HTTPException(404, "资料没有可下载的文件")

    content = _knowledge_storage.read_file(source.file_id)
    if content is None:
        raise HTTPException(404, "文件不存在或已被删除")

    from fastapi.responses import Response
    # RFC 6266 安全编码文件名，防止 HTTP header 注入
    safe_filename = (source.filename or source.file_id).replace('"', '_').replace('\r', '').replace('\n', '')
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


# ---------- P2: 检索 API ----------


class RetrieveRequest(BaseModel):
    """P2.B.4 检索请求。"""
    query: str = Field(..., min_length=1, max_length=1000, description="检索查询文本")
    top_k: int = Field(default=5, ge=1, le=20, description="返回条数")
    filters: dict | None = Field(default=None, description="附加过滤条件")


@router.post("/workspace/{workspace_id}/retrieve")
async def retrieve_knowledge(
    workspace_id: int,
    body: RetrieveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P2.B.4: 检索知识库 — 向量检索 + FTS5 降级 + 拒答策略"""
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await ws_repo.get_member(workspace_id, user.id)
    require_action(member, "read", "检索知识库")

    from app.services.retrieval_service import RetrievalService
    try:
        retrieval = RetrievalService()
        response = await retrieval.retrieve(
            query=body.query,
            workspace_id=workspace_id,
            filters=body.filters,
            top_k=body.top_k,
        )
    except Exception as e:
        logger.error(f"[RETRIEVE] 检索失败: {e}")
        raise HTTPException(500, "检索服务暂时不可用")

    # 写入检索日志
    from app.models.knowledge import RetrievalLog
    log = RetrievalLog(
        query=body.query,
        workspace_id=workspace_id,
        filters_json=json.dumps(body.filters, ensure_ascii=False) if body.filters else None,
        hit_count=response.total,
        selected_chunks=json.dumps(
            [r.chunk_id for r in response.results], ensure_ascii=False
        ) if response.results else None,
        latency_ms=response.latency_ms,
        fallback_reason=response.fallback_reason,
        user_id=user.id,
    )
    db.add(log)
    await db.commit()

    return {
        "query": response.query,
        "results": [
            {
                "chunk_id": r.chunk_id,
                "source_id": r.source_id,
                "section": r.section,
                "text_snippet": r.text_snippet,
                "distance": r._distance,
                "confidence": r.confidence,
                "rejected": r.rejected,
            }
            for r in response.results
        ],
        "total": response.total,
        "latency_ms": response.latency_ms,
        "fallback_reason": response.fallback_reason,
    }


@router.post("/workspace/{workspace_id}/sources/{source_id}/ingest")
async def ingest_source(
    workspace_id: int,
    source_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P2.A.3: 触发资料入库流程 — 解析→切块→FTS 索引→标记 pending embedding"""
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise HTTPException(404, "空间不存在")

    member = await ws_repo.get_member(workspace_id, user.id)
    require_action(member, "write", "触发资料入库")

    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(404, "资料不存在")

    from app.services.knowledge_ingestion import KnowledgeIngestionService
    try:
        ingestion = KnowledgeIngestionService(db)
        doc = await ingestion.ingest_source(source_id)
    except Exception as e:
        logger.error(f"[INGEST] 入库失败 source_id={source_id}: {e}")
        raise HTTPException(500, "资料入库失败，请稍后重试")

    if doc is None:
        raise HTTPException(422, "资料无正文或入库失败")

    await db.commit()

    _audit_log_writer.write(
        "source.ingest",
        actor=user,
        request=request,
        target_type="knowledge_source",
        target_id=source_id,
        detail={"source_id": source_id, "doc_id": doc.id, "content_hash": doc.content_hash},
    )

    return {
        "message": "入库完成，FTS 索引已建立，embedding 待处理",
        "doc_id": doc.id,
        "content_hash": doc.content_hash,
        "version": doc.version,
    }


# ---------- P5.A.1: 个人私有知识作用域 API ----------


@router.get("/personal/sources")
async def list_personal_sources(
    source_type: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    offset: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P5.A.1: 列出当前用户的个人私有资料"""
    ks_repo = KnowledgeSourceRepository(db)
    sources = await ks_repo.list_personal_sources(
        user_id=user.id,
        source_type=source_type,
        status=status,
        tag=tag,
        offset=offset,
        limit=limit,
    )
    return [_source_to_info(s) for s in sources]


@router.post("/personal/sources")
async def upload_personal_source(
    file: UploadFile = File(...),
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P5.A.1: 上传文件到个人私有资料库（owner_type=user, visibility=private）"""
    content = await file.read()
    max_size = 20 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(413, "文件过大，最大允许 20MB")

    filename = file.filename or "upload"
    stored = _knowledge_storage.save_upload(filename=filename, content=content)

    ks_repo = KnowledgeSourceRepository(db)
    # 关联到默认 workspace 以便 FTS5 检索，但 visibility=private
    ws_repo = WorkspaceRepository(db)
    ws = await ws_repo.get_default()
    workspace_id = ws.id if ws else None

    source = await ks_repo.create(
        workspace_id=workspace_id,
        source_type="upload",
        title=filename,
        filename=stored.original_filename,
        file_id=stored.file_id,
        content_hash=stored.content_hash,
        extracted_text=stored.extracted_text,
        owner_id=user.id,
        owner_type="user",
        visibility="private",
    )

    # 自动入库
    if stored.extracted_text and stored.extracted_text.strip():
        try:
            from app.services.knowledge_ingestion import KnowledgeIngestionService
            await KnowledgeIngestionService(db).ingest_source(source.id)
        except Exception as e:
            logger.error(f"[INGEST] 个人资料上传后自动入库失败 source_id={source.id}: {e}")
            source.status = "failed"
            await db.commit()
            raise HTTPException(500, "资料上传成功但入库失败，请稍后重试")

    await db.commit()

    _audit_log_writer.write(
        "source.upload_personal",
        actor=user,
        request=request,
        target_type="knowledge_source",
        target_id=source.id,
        detail={"source_id": source.id, "title": filename, "visibility": "private"},
    )

    info = _source_to_info(source)
    info["extracted_text"] = source.extracted_text
    return info


@router.get("/personal/sources/{source_id}")
async def get_personal_source_detail(
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P5.A.1: 获取个人私有资料详情"""
    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(404, "资料不存在")
    if source.owner_type != "user" or source.owner_id != user.id:
        raise HTTPException(403, "无权访问此资料")

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


@router.delete("/personal/sources/{source_id}")
async def delete_personal_source(
    source_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P5.A.1: 删除个人私有资料"""
    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(404, "资料不存在")
    if source.owner_type != "user" or source.owner_id != user.id:
        raise HTTPException(403, "只能删除自己的个人资料")

    result = await ks_repo.archive(source_id)
    if result is None:
        raise HTTPException(404, "资料不存在")

    try:
        from app.services.knowledge_vector_service import get_knowledge_vector_service
        from app.services.knowledge_ingestion import KnowledgeIngestionService
        await get_knowledge_vector_service().delete_by_source(source_id)
        await KnowledgeIngestionService(db)._cleanup_fts_entries(source_id)
    except Exception as e:
        logger.warning(f"[SOURCE] 清理个人资料检索索引失败 source_id={source_id}: {e}")

    await db.commit()
    _audit_log_writer.write(
        "source.delete_personal",
        actor=user,
        request=request,
        target_type="knowledge_source",
        target_id=source_id,
        detail={"source_id": source_id, "title": source.title},
    )
    return {"message": "已删除"}


@router.get("/personal/sources/{source_id}/download")
async def download_personal_source(
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P5.A.1: 下载个人私有资料原文件。"""
    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(404, "资料不存在")
    if source.owner_type != "user" or source.owner_id != user.id:
        raise HTTPException(403, "无权访问此资料")

    if not source.file_id:
        raise HTTPException(404, "资料没有可下载的文件")

    content = _knowledge_storage.read_file(source.file_id)
    if content is None:
        raise HTTPException(404, "文件不存在或已被删除")

    from fastapi.responses import Response
    safe_filename = (source.filename or source.file_id).replace('"', '_').replace('\r', '').replace('\n', '')
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.post("/personal/retrieve")
async def retrieve_personal_knowledge(
    body: RetrieveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P5.A.1: 检索个人私有知识库"""
    from app.services.retrieval_service import RetrievalService
    try:
        retrieval = RetrievalService(db_session=db)
        response = await retrieval.retrieve(
            query=body.query,
            workspace_id=None,
            filters=body.filters,
            top_k=body.top_k,
            user_id=user.id,
            scope="personal",
        )
    except Exception as e:
        logger.error(f"[RETRIEVE] 个人知识检索失败: {e}")
        raise HTTPException(500, "检索服务暂时不可用")

    return {
        "query": response.query,
        "results": [
            {
                "chunk_id": r.chunk_id,
                "source_id": r.source_id,
                "section": r.section,
                "text_snippet": r.text_snippet,
                "distance": r._distance,
                "confidence": r.confidence,
                "rejected": r.rejected,
            }
            for r in response.results
        ],
        "total": response.total,
        "latency_ms": response.latency_ms,
        "fallback_reason": response.fallback_reason,
    }
