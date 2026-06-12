import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session, get_db
from app.log_writers.audit_log_writer import AuditLogWriter
from app.middleware.auth import get_current_user, require_admin
from app.services.review_helpers import (
    build_context_injection,
    default_review_context,
    extract_pm_assessment_payload,
    merge_review_context_defaults,
)
from app.models.review import (
    DocAnalysis,
    ReviewContext,
    ReviewDocument,
    ReviewProject,
    ReviewPrompt,
    ReviewTask,
    SystemReview,
)
from app.models.user import ModelConfig, User
from app.runtime_paths import runtime_path
from app.storage.review_file_storage import ReviewFileStorage
from app.schemas.review import (
    AnalysisInfo,
    ContextInfo,
    ContextUpdate,
    DocumentInfo,
    ProjectCreate,
    ProjectInfo,
    PromptCreate,
    PromptInfo,
    ReviewReport,
    StartReviewRequest,
    TaskInfo,
)
from app.services.crypto import decrypt_key
from app.services.auth import consume_sse_ticket
from app.utils import now_cn
from app.services.retry import (
    ContextOverflowError,
    LLMRetryError,
    RetryConfig,
    structured_chat,
)
from app.repositories.review_task_repository import (
    DocAnalysisPayload,
    NewReviewTask,
    ReviewTaskRepository,
    SystemReviewPayload,
    TaskProgressPatch,
)
from app.repositories.review_project_repository import ReviewProjectRepository
from app.repositories.review_context_repository import (
    ReviewContextRepository,
    ContextCreateData,
)
from app.repositories.review_prompt_repository import (
    ReviewPromptRepository,
    ReviewPromptCreateData,
    ReviewPromptPatch,
)
from app.services.review_pipeline_persistence import ReviewPipelinePersistenceService
from app.services.skill_runner import SkillRunner, normalize_dimension_result

logger = logging.getLogger(__name__)
router = APIRouter()

_audit_log_writer = AuditLogWriter()
_review_file_storage = ReviewFileStorage()

# Skills directory: configured in config.yaml, resolved to absolute path at startup
_settings = get_settings()


def _resolve_skills_dir(configured: str | os.PathLike[str]) -> str:
    """Resolve Skills root independent of the process working directory."""
    configured_path = Path(configured).expanduser()
    if configured_path.is_absolute():
        return str(configured_path.resolve())

    project_root = Path(__file__).resolve().parents[3]
    candidates = [
        project_root / configured_path,
        Path.cwd() / configured_path,
        project_root.parent / configured_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return str((project_root / configured_path).resolve())


_skills_dir_raw = _settings.get("review", {}).get("skills_dir", "./skills")
SKILLS_DIR = _resolve_skills_dir(_skills_dir_raw)


def _estimate_review_seconds(mode: str) -> int:
    return {"quick": 120, "review": 300, "pm": 240, "insight": 480, "full": 600, "draft": 300}.get(mode, 180)


def _build_review_retry_config() -> RetryConfig:
    retry_cfg = _settings.get("review", {}).get("retry", {})
    return RetryConfig(
        max_attempts=retry_cfg.get("max_attempts", 5),
        initial_delay_ms=retry_cfg.get("initial_delay_ms", 2000),
        backoff_factor=retry_cfg.get("backoff_factor", 2.0),
        max_delay_ms=retry_cfg.get("max_delay_ms", 30000),
        timeout_seconds=retry_cfg.get("timeout_seconds", 120.0),
        connect_timeout_seconds=retry_cfg.get("connect_timeout_seconds", 10.0),
    )


async def _load_review_context(db: AsyncSession, project_id: int) -> dict | None:
    """Load active ReviewContext for a project, return parsed context_data."""
    result = await db.execute(
        select(ReviewContext)
        .where(ReviewContext.project_id == project_id, ReviewContext.is_active == True)
        .order_by(ReviewContext.version.desc())
        .limit(1)
    )
    ctx = result.scalar_one_or_none()
    if ctx is None:
        return default_review_context()
    return merge_review_context_defaults(json.loads(ctx.context_data))


async def _load_project_knowledge_context(db: AsyncSession, project_id: int, snapshot_ref: str | None = None) -> str | None:
    """P2.C.2: 加载项目引用资料的知识切块，注入审查上下文。

    P4.Pre.3: 支持 snapshot_version 回读 — 当 snapshot_ref 非空时，
    优先按 ProjectSourceRef.snapshot_version 过滤对应版本的知识切块。
    无快照引用时回退取最新。

    流程：
    1. 查找项目引用的所有 KnowledgeSource
    2. 查找每个 source 对应的 KnowledgeDocument → KnowledgeChunk
    3. 格式化为可注入 SkillRunner 的文本
    """
    from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
    from app.models.workspace import ProjectSourceRef, KnowledgeSource

    # 1. 获取项目引用的资料列表
    ref_result = await db.execute(
        select(ProjectSourceRef).where(ProjectSourceRef.project_id == project_id)
    )
    refs = ref_result.scalars().all()
    if not refs:
        return None

    source_ids = [ref.source_id for ref in refs]

    # P4.Pre.3: 构建 source_id → snapshot_version 映射
    snapshot_version_map: dict[int, int | None] = {}
    if snapshot_ref:
        # snapshot_ref 格式: "snapshot:{id}" 或直接用 ProjectSourceRef.snapshot_version
        for ref in refs:
            if ref.snapshot_version is not None:
                snapshot_version_map[ref.source_id] = ref.snapshot_version

    # 2. 仅使用仍处于 active 状态的引用资料，避免已归档资料继续影响审查结果。
    source_result = await db.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.id.in_(source_ids),
            KnowledgeSource.status == "active",
        )
    )
    active_source_map = {s.id: s.title for s in source_result.scalars().all()}
    if not active_source_map:
        return None

    doc_result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.source_id.in_(active_source_map.keys()))
    )
    docs = doc_result.scalars().all()

    # P4.Pre.3: 按 snapshot_version 过滤文档版本
    if snapshot_version_map and docs:
        filtered_docs = []
        for doc in docs:
            expected_ver = snapshot_version_map.get(doc.source_id)
            if expected_ver is not None and doc.version != expected_ver:
                continue  # 跳过版本不匹配的文档
            filtered_docs.append(doc)
        if filtered_docs:
            docs = filtered_docs

    if not docs:
        return None

    doc_ids = [doc.id for doc in docs]
    # 限制加载数量，防止超出 LLM 上下文窗口（每个 chunk 约 512 字符，50 个 ≈ 25K 字符）
    MAX_CHUNKS_PER_PROJECT = 50
    chunk_result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.document_id.in_(doc_ids))
        .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_no)
        .limit(MAX_CHUNKS_PER_PROJECT)
    )
    chunks = chunk_result.scalars().all()
    if not chunks:
        return None

    # 3. 格式化
    doc_source_map = {doc.id: doc.source_id for doc in docs}
    parts = []
    for chunk in chunks:
        source_id = doc_source_map.get(chunk.document_id)
        title = active_source_map.get(source_id, "未知资料")
        section_info = f" [{chunk.section}]" if chunk.section else ""
        parts.append(f"- [{title}{section_info}] {chunk.text}")

    return "\n".join(parts)


progress_queues: dict[int, asyncio.Queue] = {}


def _resolve_stored_file_path(stored_path: str | os.PathLike[str] | None) -> str | None:
    """Delegate path resolution to ReviewFileStorage."""
    return _review_file_storage._resolve_stored_file_path(stored_path)


def _to_runtime_relative_path(file_path: str | os.PathLike[str] | None) -> str | None:
    """Delegate runtime-relative conversion to ReviewFileStorage."""
    return _review_file_storage.to_runtime_relative_path(file_path)


def _system_review_has_complete_dimensions(sr: SystemReview) -> bool:
    return ReviewTaskRepository._system_review_has_complete_dimensions(sr)


async def _find_cached_system_review(
    db: AsyncSession,
    project_id: int,
    doc_ids: list[int] | None = None,
    context_version: int | None = None,
    model_id: str | None = None,
) -> SystemReview | None:
    repo = ReviewTaskRepository(db)
    return await repo.find_cached_system_review(project_id, doc_ids, context_version, model_id)




def _analysis_has_required_expert_review(analysis: DocAnalysis) -> bool:
    return ReviewTaskRepository._analysis_has_required_expert_review(analysis)


async def _find_cached_analyses(db: AsyncSession, doc_ids: list[int], context_version: int | None = None) -> dict[int, DocAnalysis]:
    repo = ReviewTaskRepository(db)
    return await repo.find_cached_analyses(doc_ids, context_version)


progress_queues: dict[int, asyncio.Queue] = {}


def _get_jwt_secret() -> str:
    settings = get_settings()
    secret = settings.get("auth", {}).get("secret_key")
    if not secret or secret == "change-me-in-production":
        raise RuntimeError("JWT secret 未配置或使用默认值，请设置 .env 中的 JWT_SECRET")
    return secret


async def _get_model_config(model_id: str | None, db: AsyncSession) -> dict:
    if model_id:
        result = await db.execute(
            select(ModelConfig).where(
                ModelConfig.model_id == model_id,
                ModelConfig.deleted_by_user == False,
            )
        )
    else:
        result = await db.execute(
            select(ModelConfig)
            .where(ModelConfig.enabled == True, ModelConfig.deleted_by_user == False)
            .order_by(ModelConfig.display_order, ModelConfig.name, ModelConfig.id)
            .limit(1)
        )
    mc = result.scalar_one_or_none()
    if mc is None:
        raise HTTPException(status_code=400, detail="无可用的LLM模型配置，请先在管理后台配置模型和API Key")
    if not mc.enabled:
        raise HTTPException(status_code=400, detail="所选模型已禁用，请选择其他模型或启用该模型")
    secret = _get_jwt_secret()
    api_key = ""
    if mc.encrypted_api_key:
        try:
            api_key = decrypt_key(mc.encrypted_api_key, secret)
        except Exception:
            raise HTTPException(status_code=400, detail="模型 API Key 解密失败，请在管理后台重新配置")
    if not api_key:
        raise HTTPException(status_code=400, detail="所选模型未配置 API Key，请先在管理后台配置")
    return {
        "model_id": mc.model_id,
        "api_base": mc.api_base,
        "api_key": api_key,
        "llm_model": mc.llm_model,
        "max_tokens": mc.max_tokens,
        "temperature": 0.3,
        "thinking_supported": mc.thinking_supported,
        "thinking_level": mc.thinking_level,
        "thinking_adapter": mc.thinking_adapter,
        "thinking_payload": mc.thinking_payload,
    }


def _project_to_info(p: ReviewProject, doc_count: int = 0, report_count: int = 0, ctx_ver: int | None = None) -> ProjectInfo:
    return ProjectInfo(
        id=p.id, name=p.name, description=p.description,
        workspace_id=p.workspace_id,
        doc_count=doc_count, report_count=report_count,
        context_version=ctx_ver, created_at=p.created_at, updated_at=p.updated_at,
    )


def _document_to_info(d: ReviewDocument) -> DocumentInfo:
    return DocumentInfo(
        id=d.id, filename=d.filename, file_size=d.file_size,
        md_path=d.md_path, category=d.category, version=d.version,
        document_type=d.document_type or "requirement",
        status=d.status, created_at=d.created_at,
    )


async def _save_project_documents(
    project_id: int,
    files: list[UploadFile],
    db: AsyncSession,
    document_type: str = "requirement",
):
    settings = get_settings()
    review_cfg = settings.get("review", {})
    upload_cfg = review_cfg.get("upload", {})
    max_size_mb = upload_cfg.get("max_file_size_mb", 50)
    allowed_ext = upload_cfg.get("allowed_extensions", [".docx"])

    saved = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in allowed_ext:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

        content = await f.read()
        if len(content) > max_size_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"文件过大: {f.filename}")

        stored = await _review_file_storage.save_uploaded_docx(
            project_id=project_id, document_type=document_type,
            filename=f.filename or "upload.docx", content=content,
        )

        doc = ReviewDocument(
            project_id=project_id,
            filename=f.filename or stored.file_id,
            file_path=stored.runtime_relative_path,
            file_size=len(content),
            document_type=document_type,
            status="uploaded",
        )
        repo = ReviewProjectRepository(db)
        await repo.add_document(doc)
        saved.append({"filename": f.filename, "size": len(content), "document_type": document_type})

    await db.commit()
    return {"uploaded": len(saved), "files": saved}


# ── Projects ──

async def _verify_project_owner(db: AsyncSession, project_id: int, user_id: int) -> ReviewProject:
    repo = ReviewProjectRepository(db)
    project = await repo.get_project_with_owner_check(project_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")

    # P1.B.2: workspace active member 校验 — 停用成员不可访问项目资源
    # legacy 项目（workspace_id=None）回退到默认 workspace 校验
    from app.repositories.workspace_repository import WorkspaceRepository
    from app.services.workspace_access import require_action
    ws_repo = WorkspaceRepository(db)
    workspace_id = project.workspace_id
    if workspace_id is None:
        default_ws = await ws_repo.get_default()
        if default_ws is None:
            raise HTTPException(status_code=403, detail="项目未关联团队空间，无法校验权限")
        workspace_id = default_ws.id

    member = await ws_repo.get_member(workspace_id, user_id)
    require_action(member, "read", "访问项目")

    return project


async def _verify_review_task_owner(db: AsyncSession, project_id: int, review_id: int, user_id: int) -> ReviewTask:
    """Verify user owns the project AND the review task belongs to the project."""
    await _verify_project_owner(db, project_id, user_id)
    result = await db.execute(
        select(ReviewTask).where(ReviewTask.id == review_id, ReviewTask.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    return task


@router.get("/projects", response_model=list[ProjectInfo])
async def list_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # P1.B.2: 构建用户活跃 workspace ID 集合，过滤项目可见性
    from app.repositories.workspace_repository import WorkspaceRepository
    ws_repo = WorkspaceRepository(db)
    user_workspaces = await ws_repo.get_user_workspaces(user.id)
    active_ws_ids = {ws.id for ws in user_workspaces}

    # legacy 项目（workspace_id=None）归入默认 workspace 可见性
    default_ws = await ws_repo.get_default()
    legacy_visible = default_ws is not None and default_ws.id in active_ws_ids

    # P4.Pre.1: 按用户活跃 workspace 过滤项目可见性，不再限制 created_by
    from app.services.workspace_access import can
    result = await db.execute(select(ReviewProject).order_by(ReviewProject.updated_at.desc()))
    all_projects = result.scalars().all()
    out = []
    for p in all_projects:
        # workspace_id 非空且用户不在活跃集合中 → 跳过
        if p.workspace_id is not None and p.workspace_id not in active_ws_ids:
            continue
        # workspace_id 为空（legacy）且用户不在默认 workspace → 跳过
        if p.workspace_id is None and not legacy_visible:
            continue
        # P4.Pre.1: owner/admin 可看全部，member/viewer 只看自己创建的
        member = await ws_repo.get_member(p.workspace_id or (default_ws.id if default_ws else None), user.id)
        member_role = member.role if member else None
        if member_role not in ("owner", "admin") and p.created_by != user.id:
            continue
        dc = await db.execute(select(func.count()).where(ReviewDocument.project_id == p.id))
        doc_count = dc.scalar() or 0
        rc = await db.execute(
            select(func.count()).where(
                ReviewTask.project_id == p.id,
                ReviewTask.status.in_(("completed", "completed_with_warnings")),
            )
        )
        report_count = rc.scalar() or 0
        cv = await db.execute(select(ReviewContext.version).where(ReviewContext.project_id == p.id, ReviewContext.is_active == True).order_by(ReviewContext.version.desc()).limit(1))
        ctx_ver = cv.scalar_one_or_none()
        out.append(_project_to_info(p, doc_count, report_count, ctx_ver))
    return out


@router.post("/projects", response_model=ProjectInfo)
async def create_project(req: ProjectCreate, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.repositories.workspace_repository import WorkspaceRepository
    from app.services.workspace_access import is_active_member
    ws_repo = WorkspaceRepository(db)
    # 单团队部署：取用户所属的第一个 workspace 作为项目归属
    user_workspaces = await ws_repo.get_user_workspaces(user.id)
    if not user_workspaces:
        raise HTTPException(status_code=403, detail="你不是任何团队空间的活跃成员，无法创建项目")
    workspace_id = user_workspaces[0].id

    # P1.B.2: 校验用户是 workspace 的活跃成员
    member = await ws_repo.get_member(workspace_id, user.id)
    if not is_active_member(member):
        raise HTTPException(status_code=403, detail="你的成员状态不允许创建项目")

    repo = ReviewProjectRepository(db)
    p = await repo.create_project(name=req.name, description=req.description, created_by=user.id, workspace_id=workspace_id)
    await db.commit()
    _audit_log_writer.write(
        "project.create",
        actor=user,
        request=request,
        target_type="project",
        target_id=p.id,
        detail={"project_id": p.id, "name": p.name},
    )
    return _project_to_info(p)


@router.get("/projects/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _verify_project_owner(db, project_id, user.id)
    dc = await db.execute(select(func.count()).where(ReviewDocument.project_id == p.id))
    doc_count = dc.scalar() or 0
    rc = await db.execute(
        select(func.count()).where(
            ReviewTask.project_id == p.id,
            ReviewTask.status.in_(("completed", "completed_with_warnings")),
        )
    )
    report_count = rc.scalar() or 0
    cv = await db.execute(select(ReviewContext.version).where(ReviewContext.project_id == p.id, ReviewContext.is_active == True).order_by(ReviewContext.version.desc()).limit(1))
    ctx_ver = cv.scalar_one_or_none()

    info = _project_to_info(p, doc_count, report_count, ctx_ver)
    dr = await db.execute(select(ReviewDocument).where(ReviewDocument.project_id == project_id).order_by(ReviewDocument.created_at))
    info.documents = [_document_to_info(d) for d in dr.scalars().all()]
    return info


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _verify_project_owner(db, project_id, user.id)
    project_name = p.name

    active_task_result = await db.execute(
        select(ReviewTask.id)
        .where(
            ReviewTask.project_id == project_id,
            ReviewTask.status.in_(("pending", "running")),
        )
        .limit(1)
    )
    active_task_id = active_task_result.scalar_one_or_none()
    if active_task_id is not None:
        _audit_log_writer.write(
            "project.delete",
            actor=user,
            request=request,
            target_type="project",
            target_id=project_id,
            result="failed",
            detail={"project_id": project_id, "name": project_name, "reason": "review_running", "task_id": active_task_id},
            level="warning",
        )
        raise HTTPException(status_code=409, detail="当前项目仍有运行中的审查任务，请先取消或等待完成")

    doc_result = await db.execute(select(ReviewDocument).where(ReviewDocument.project_id == project_id))
    docs = doc_result.scalars().all()

    await _review_file_storage.delete_project_files(project_id)

    for doc in docs:
        await _review_file_storage.delete_document_files(doc.id, file_path=doc.file_path, md_path=doc.md_path)

    # P4: 删除关联的协作审查子记录（review_requests 级联删除）
    # SQLAlchemy 不会自动执行 ON DELETE CASCADE，需手动删除子记录
    from app.models.review import ReviewRequest, ReviewRound, ReviewParticipant
    req_result = await db.execute(select(ReviewRequest).where(ReviewRequest.project_id == project_id))
    for req in req_result.scalars().all():
        # 删除轮次和参与者
        round_result = await db.execute(select(ReviewRound).where(ReviewRound.request_id == req.id))
        for rnd in round_result.scalars().all():
            await db.execute(
                ReviewParticipant.__table__.delete().where(ReviewParticipant.request_id == req.id)
            )
            await db.delete(rnd)
        await db.delete(req)

    await db.delete(p)
    await db.commit()
    _audit_log_writer.write(
        "project.delete",
        actor=user,
        request=request,
        target_type="project",
        target_id=project_id,
        detail={"project_id": project_id, "name": project_name},
    )
    return {"message": "已删除"}


# ── Project Source Refs (P0.C.1) ──

@router.post("/project/{project_id}/sources")
async def add_project_source_ref(
    project_id: int,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await _verify_project_owner(db, project_id, user.id)

    source_id = body.get("source_id")
    if not source_id or not isinstance(source_id, int):
        raise HTTPException(status_code=422, detail="source_id 必填且为整数")

    ref_type = body.get("ref_type", "context")
    if ref_type not in ("context", "reference", "background"):
        raise HTTPException(status_code=422, detail="ref_type 必须为 context/reference/background")

    snapshot_version = body.get("snapshot_version")

    from app.repositories.knowledge_source_repository import ProjectSourceRefRepository, KnowledgeSourceRepository
    from app.repositories.workspace_repository import WorkspaceRepository
    ks_repo = KnowledgeSourceRepository(db)
    source = await ks_repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="资料不存在")

    # P0 验收补：source 必须属于项目所在 workspace 且状态 active
    if source.status != "active":
        raise HTTPException(status_code=400, detail="资料已归档，不能引用")

    if p.workspace_id and source.workspace_id != p.workspace_id:
        raise HTTPException(status_code=403, detail="资料不属于该项目所在团队空间")

    ws_repo = WorkspaceRepository(db)
    member = await ws_repo.get_member(source.workspace_id, user.id)
    from app.services.workspace_access import is_active_member
    if not is_active_member(member):
        raise HTTPException(status_code=403, detail="你没有该资料的查看权限或成员状态不活跃")

    ref_repo = ProjectSourceRefRepository(db)
    ref = await ref_repo.add_ref(
        project_id=project_id,
        source_id=source_id,
        ref_type=ref_type,
        snapshot_version=snapshot_version,
    )
    await db.commit()

    _audit_log_writer.write(
        "project.add_source_ref",
        actor=user,
        request=request,
        target_type="project",
        target_id=project_id,
        detail={
            "project_id": project_id,
            "source_id": source_id,
            "ref_type": ref_type,
            "snapshot_version": snapshot_version,
        },
    )
    return {
        "id": ref.id,
        "project_id": ref.project_id,
        "source_id": ref.source_id,
        "ref_type": ref.ref_type,
        "snapshot_version": ref.snapshot_version,
        "created_at": ref.created_at.isoformat() if ref.created_at else None,
    }


@router.get("/project/{project_id}/sources")
async def list_project_source_refs(
    project_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project_owner(db, project_id, user.id)

    from app.repositories.knowledge_source_repository import ProjectSourceRefRepository
    ref_repo = ProjectSourceRefRepository(db)
    refs = await ref_repo.list_by_project(project_id)
    return [
        {
            "id": r.id,
            "project_id": r.project_id,
            "source_id": r.source_id,
            "ref_type": r.ref_type,
            "snapshot_version": r.snapshot_version,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in refs
    ]


# ── Documents ──

@router.post("/projects/{project_id}/documents")
async def upload_docs(
    project_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project_owner(db, project_id, user.id)

    result = await _save_project_documents(project_id, files, db, "requirement")
    _audit_log_writer.write(
        "document.upload",
        actor=user,
        request=request,
        target_type="project",
        target_id=project_id,
        detail={"project_id": project_id, "document_type": "requirement", "files": result.get("files", [])},
    )
    return result


@router.post("/projects/{project_id}/historical-documents")
async def upload_historical_docs(
    project_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project_owner(db, project_id, user.id)

    result = await _save_project_documents(project_id, files, db, "historical")
    _audit_log_writer.write(
        "document.upload",
        actor=user,
        request=request,
        target_type="project",
        target_id=project_id,
        detail={"project_id": project_id, "document_type": "historical", "files": result.get("files", [])},
    )
    return result


@router.get("/projects/{project_id}/documents", response_model=list[DocumentInfo])
async def list_docs(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_project_owner(db, project_id, user.id)
    result = await db.execute(select(ReviewDocument).where(ReviewDocument.project_id == project_id).order_by(ReviewDocument.created_at))
    return [_document_to_info(d) for d in result.scalars().all()]


@router.delete("/projects/{project_id}/documents/{doc_id}")
async def delete_doc(project_id: int, doc_id: int, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_project_owner(db, project_id, user.id)
    result = await db.execute(select(ReviewDocument).where(ReviewDocument.id == doc_id, ReviewDocument.project_id == project_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    filename = doc.filename
    await _review_file_storage.delete_document_files(doc.id, file_path=doc.file_path, md_path=doc.md_path)
    await db.delete(doc)
    await db.commit()
    _audit_log_writer.write(
        "document.delete",
        actor=user,
        request=request,
        target_type="document",
        target_id=doc_id,
        detail={"project_id": project_id, "document_id": doc_id, "filename": filename},
    )
    return {"ok": True}


# ── Reviews ──

@router.get("/projects/{project_id}/reviews")
async def list_reviews(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all review tasks for a project."""
    await _verify_project_owner(db, project_id, user.id)
    result = await db.execute(
        select(ReviewTask)
        .where(ReviewTask.project_id == project_id)
        .order_by(ReviewTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [TaskInfo(
        task_id=t.id, status=t.status, mode=t.mode,
        current_step=t.current_step, total_docs=t.total_docs,
        completed_docs=t.completed_docs, context_version=t.context_version,
        document_ids=_extract_task_artifacts(t).get("document_ids"),
        estimated_seconds=None,
    ) for t in tasks]


@router.post("/projects/{project_id}/reviews", response_model=TaskInfo)
async def start_review(
    project_id: int,
    req: StartReviewRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_project_owner(db, project_id, user.id)

    doc_result = await db.execute(select(ReviewDocument).where(ReviewDocument.project_id == project_id))
    all_docs = doc_result.scalars().all()

    if req.document_ids:
        docs = [d for d in all_docs if d.id in req.document_ids]
    else:
        docs = [d for d in all_docs if (d.document_type or "requirement") == "requirement"]

    if not docs:
        raise HTTPException(status_code=400, detail="没有可审查的文档，请先上传")

    # For draft mode, also collect historical documents
    historical_doc_ids = []
    if req.mode == "draft":
        historical_docs = [d for d in all_docs if (d.document_type or "requirement") == "historical"]
        historical_doc_ids = [d.id for d in historical_docs]

    model_cfg = await _get_model_config(req.model_id, db)

    # Enrich model_cfg with thinking extra_body
    if model_cfg.get("thinking_supported") and model_cfg.get("thinking_adapter") != "none":
        from app.services.thinking_adapter import build_thinking_payload
        extra_body = build_thinking_payload(
            thinking_level=model_cfg.get("thinking_level", "off"),
            thinking_adapter=model_cfg.get("thinking_adapter", "none"),
            thinking_payload=model_cfg.get("thinking_payload"),
            runtime_level_override=req.thinking_level,
        )
        model_cfg["extra_body"] = extra_body

    cv = await db.execute(select(ReviewContext.version).where(ReviewContext.project_id == project_id, ReviewContext.is_active == True).order_by(ReviewContext.version.desc()).limit(1))
    ctx_ver = cv.scalar_one_or_none() or 1

    mode_steps = {
        "quick": ["预处理", "分类", "逐篇分析"],
        "review": ["预处理", "分类", "逐篇分析", "体系Review", "报告生成"],
        "pm": ["预处理", "分类", "逐篇分析", "体系Review", "报告生成"],
        "insight": ["预处理", "分类", "逐篇分析", "体系Review", "需求洞察", "报告生成"],
        "full": ["预处理", "分类", "逐篇分析", "体系Review", "需求洞察", "报告生成"],
        "draft": ["预处理", "分类", "逐篇分析", "体系Review", "需求洞察", "PRD草稿生成", "报告生成"],
    }
    steps = mode_steps.get(req.mode, mode_steps["quick"])
    step_statuses = {str(i): "pending" for i in range(len(steps))}
    selected_doc_ids = [d.id for d in docs]
    est = _estimate_review_seconds(req.mode)

    active_task = await _find_active_review_task(db, project_id, req.mode, selected_doc_ids, historical_doc_ids)
    if active_task is not None:
        return TaskInfo(
            task_id=active_task.id,
            status=active_task.status,
            mode=active_task.mode,
            current_step=active_task.current_step,
            total_docs=active_task.total_docs,
            completed_docs=active_task.completed_docs,
            context_version=active_task.context_version,
            document_ids=selected_doc_ids,
            estimated_seconds=est,
        )

    repo = ReviewTaskRepository(db)
    task = await repo.create_task(NewReviewTask(
        project_id=project_id,
        mode=req.mode,
        context_version=ctx_ver,
        model_id=model_cfg["model_id"],
        created_by=user.id,
        step_statuses=json.dumps(step_statuses),
        step_details=json.dumps({
            "document_ids": selected_doc_ids,
            "historical_document_ids": historical_doc_ids,
            "thinking_level": req.thinking_level,
        }, ensure_ascii=False),
        total_docs=len(docs),
    ))
    await db.commit()
    _audit_log_writer.write(
        "review.start",
        actor=user,
        request=request,
        target_type="review_task",
        target_id=task.id,
        detail={
            "project_id": project_id,
            "task_id": task.id,
            "mode": req.mode,
            "model_id": model_cfg["model_id"],
            "document_ids": selected_doc_ids,
            "historical_document_ids": historical_doc_ids,
            "context_version": ctx_ver,
            "total_docs": len(docs),
            "force_reanalysis": req.force_reanalysis,
        },
    )

    progress_queues[task.id] = asyncio.Queue()

    asyncio.create_task(_run_pipeline(task.id, project_id, req.mode, selected_doc_ids, model_cfg, steps, historical_doc_ids, req.force_reanalysis))

    return TaskInfo(
        task_id=task.id, status="pending", mode=req.mode,
        current_step=0, total_docs=len(docs), completed_docs=0,
        context_version=ctx_ver, document_ids=selected_doc_ids, estimated_seconds=est,
    )


@router.get("/projects/{project_id}/reviews/{review_id}")
async def review_progress_sse(
    project_id: int, review_id: int,
    ticket: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if not ticket:
        raise HTTPException(status_code=401, detail="未提供认证票据")

    user_id_from_ticket = consume_sse_ticket(ticket)
    if user_id_from_ticket is None:
        raise HTTPException(status_code=401, detail="认证票据无效或已过期")

    proj_result = await db.execute(select(ReviewProject).where(ReviewProject.id == project_id, ReviewProject.created_by == user_id_from_ticket))
    if proj_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="无权访问该项目")
    task_result = await db.execute(select(ReviewTask).where(ReviewTask.id == review_id, ReviewTask.project_id == project_id))
    if task_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="审查任务不存在")

    queue = progress_queues.get(review_id)
    if not queue:
        try:
            result = await db.execute(select(ReviewTask).where(ReviewTask.id == review_id))
            task = result.scalar_one_or_none()
            if task is None:
                raise HTTPException(status_code=404, detail="审查任务不存在")
            data = {"task_status": task.status, "current_step": task.current_step}
            return StreamingResponse(iter([f"data: {json.dumps(data)}\n\n"]), media_type="text/event-stream")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail="审查任务不存在")

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("task_status") in ("completed", "failed", "cancelled"):
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/projects/{project_id}/reviews/{review_id}/status")
async def review_task_status(project_id: int, review_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await _verify_review_task_owner(db, project_id, review_id, user.id)
    ss = json.loads(task.step_statuses) if task.step_statuses else {}
    sd = json.loads(task.step_details) if task.step_details else {}
    doc_result = await db.execute(select(ReviewDocument).where(ReviewDocument.project_id == project_id))
    doc_progress = [
        {"filename": d.filename, "status": d.status, "document_type": d.document_type or "requirement"}
        for d in doc_result.scalars().all()
    ]
    return {"task_status": task.status, "current_step": task.current_step, "step_statuses": ss, "step_details": sd, "doc_progress": doc_progress}


@router.post("/projects/{project_id}/reviews/{review_id}/cancel")
async def cancel_review(project_id: int, review_id: int, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await _verify_review_task_owner(db, project_id, review_id, user.id)
    if task.status not in ("pending", "running"):
        _audit_log_writer.write(
            "review.cancel",
            actor=user,
            request=request,
            target_type="review_task",
            target_id=review_id,
            result="failed",
            detail={"project_id": project_id, "task_id": review_id, "status": task.status, "reason": "task_finished"},
            level="warning",
        )
        raise HTTPException(status_code=400, detail="任务已结束")
    task.status = "cancelled"
    await db.commit()
    q = progress_queues.get(review_id)
    if q:
        await q.put({"task_status": "cancelled"})
    _audit_log_writer.write(
        "review.cancel",
        actor=user,
        request=request,
        target_type="review_task",
        target_id=review_id,
        detail={"project_id": project_id, "task_id": review_id, "mode": task.mode},
    )
    return {"message": "已取消"}


@router.get("/projects/{project_id}/reviews/{review_id}/analyses", response_model=list[AnalysisInfo])
async def get_analyses(project_id: int, review_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_review_task_owner(db, project_id, review_id, user.id)
    result = await db.execute(select(DocAnalysis).where(DocAnalysis.task_id == review_id))
    analyses = result.scalars().all()
    out = []
    for a in analyses:
        dr = await db.execute(select(ReviewDocument.filename).where(ReviewDocument.id == a.document_id))
        fn = dr.scalar_one_or_none()
        sv = json.loads(a.spec_violations) if a.spec_violations else None
        fa = json.loads(a.full_analysis) if a.full_analysis else None
        bi = fa.get("boundary_issues") if fa else None
        kp = fa.get("key_points") if fa else None
        rt = fa.get("resolution_tracking") if fa else None
        er = fa.get("expert_review") if fa else None
        out.append(AnalysisInfo(
            id=a.id, document_id=a.document_id, filename=fn,
            core_problem=a.core_problem, category=a.category,
            boundary_in=json.loads(a.boundary_in) if a.boundary_in else None,
            boundary_out=json.loads(a.boundary_out) if a.boundary_out else None,
            boundary_issues=bi, key_points=kp, resolution_tracking=rt, expert_review=er,
            spec_violations=sv, quality_score=a.quality_score, full_analysis=fa,
        ))
    return out


@router.get("/projects/{project_id}/reviews/{review_id}/system-review")
async def get_system_review(project_id: int, review_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_review_task_owner(db, project_id, review_id, user.id)
    result = await db.execute(select(SystemReview).where(SystemReview.task_id == review_id, SystemReview.project_id == project_id))
    sr = result.scalar_one_or_none()
    if sr is None:
        return {}
    return {
        "business_value": _parse_system_review_dimension(sr.business_value, "business-value"),
        "architecture": _parse_system_review_dimension(sr.architecture, "architecture"),
        "competition": _parse_system_review_dimension(sr.competition, "competition"),
        "product_strategy": _parse_system_review_dimension(sr.product_strategy, "product-strategy"),
        "tech_evolution": _parse_system_review_dimension(sr.tech_evolution, "tech-evolution"),
        "pm_growth": json.loads(sr.pm_growth) if sr.pm_growth else None,
        "action_plan": _parse_system_review_dimension(sr.action_plan, "action-plan"),
        "pm_scores": json.loads(sr.pm_scores) if sr.pm_scores else None,
    }


def _parse_system_review_dimension(raw: str | None, dim_name: str) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return normalize_dimension_result(dim_name, parsed)


def _extract_task_artifacts(task) -> dict:
    if task is None or not getattr(task, "step_details", None):
        return {}
    try:
        data = json.loads(task.step_details)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_same_active_review_scope(task: ReviewTask, mode: str, document_ids: list[int], historical_document_ids: list[int] | None = None) -> bool:
    if getattr(task, "mode", None) != mode:
        return False

    artifacts = _extract_task_artifacts(task)
    task_doc_ids = artifacts.get("document_ids") or []
    task_historical_ids = artifacts.get("historical_document_ids") or []
    historical_document_ids = historical_document_ids or []

    return (
        sorted(int(doc_id) for doc_id in task_doc_ids) == sorted(int(doc_id) for doc_id in document_ids)
        and sorted(int(doc_id) for doc_id in task_historical_ids) == sorted(int(doc_id) for doc_id in historical_document_ids)
    )


async def _find_active_review_task(
    db: AsyncSession,
    project_id: int,
    mode: str,
    document_ids: list[int],
    historical_document_ids: list[int] | None = None,
) -> ReviewTask | None:
    repo = ReviewTaskRepository(db)
    return await repo.find_active_review_task(project_id, mode, document_ids, historical_document_ids)


def _merge_task_step_details(task: ReviewTask, **updates) -> None:
    ReviewPipelinePersistenceService.merge_step_details_static(task, **updates)


def _mark_current_step_failed(task: ReviewTask) -> dict:
    step_statuses = ReviewPipelinePersistenceService.parse_step_statuses(task)
    current_step = getattr(task, "current_step", None)
    if current_step is not None:
        step_statuses[str(current_step)] = "failed"
    task.step_statuses = json.dumps(step_statuses, ensure_ascii=False)
    return step_statuses


def _finalize_task_failed(task: ReviewTask) -> dict:
    task.status = "failed"
    task.completed_at = now_cn()
    return _mark_current_step_failed(task)


def _raise_if_step_failed(step_name: str, result):
    if getattr(result, "is_error", False):
        data = getattr(result, "data", {}) or {}
        detail = data.get("error") if isinstance(data, dict) else None
        raise RuntimeError(detail or f"{step_name}执行失败")
    return result


@router.get("/projects/{project_id}/reviews/{review_id}/report")
async def get_report(
    project_id: int, review_id: int,
    request: Request,
    format: str = Query("json", pattern="^(json|markdown)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_review_task_owner(db, project_id, review_id, user.id)
    analyses = await get_analyses(project_id, review_id, user, db)
    sr_data = await get_system_review(project_id, review_id, user, db)

    result = await db.execute(select(ReviewTask).where(ReviewTask.id == review_id, ReviewTask.project_id == project_id))
    task = result.scalar_one_or_none()

    pm_assessment = None
    if sr_data and sr_data.get("pm_scores"):
        ps = sr_data.get("pm_scores")
        pm_assessment = extract_pm_assessment_payload(ps)
        if pm_assessment:
            sr_data["pm_scores"] = pm_assessment

    artifacts = _extract_task_artifacts(task)

    _audit_log_writer.write(
        "review.report_view",
        actor=user,
        request=request,
        target_type="review_task",
        target_id=review_id,
        detail={"project_id": project_id, "task_id": review_id, "mode": task.mode if task else None, "format": format},
    )

    if format == "markdown":
        md = _render_markdown_report(analyses, sr_data, pm_assessment, task)
        return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")

    return ReviewReport(
        task_id=review_id,
        mode=task.mode if task else "unknown",
        context_version=task.context_version if task else 1,
        analyses=analyses,
        system_review=sr_data if sr_data else None,
        pm_assessment=pm_assessment,
        insights=artifacts.get("insights"),
        prd_draft=artifacts.get("prd_draft"),
    )


# ── Context ──

@router.get("/projects/{project_id}/context", response_model=ContextInfo)
async def get_context(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_project_owner(db, project_id, user.id)
    result = await db.execute(select(ReviewContext).where(ReviewContext.project_id == project_id, ReviewContext.is_active == True).order_by(ReviewContext.version.desc()).limit(1))
    ctx = result.scalar_one_or_none()
    if ctx is None:
        return ContextInfo(context_id=0, version=1, is_active=True, updated_at=None, context_data=default_review_context())
    return ContextInfo(context_id=ctx.id, version=ctx.version, is_active=ctx.is_active, updated_at=ctx.updated_at, context_data=merge_review_context_defaults(json.loads(ctx.context_data)))


@router.put("/projects/{project_id}/context", response_model=ContextInfo)
async def update_context(project_id: int, req: ContextUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_project_owner(db, project_id, user.id)
    ctx_repo = ReviewContextRepository(db)
    # Load old context for merge
    old_ctx = await ctx_repo.get_active_context(project_id)
    data = merge_review_context_defaults(json.loads(old_ctx.context_data)) if old_ctx and old_ctx.context_data else default_review_context()

    if req.specifications is not None:
        data["specifications"] = req.specifications
    if req.required_sections is not None:
        data["required_sections"] = req.required_sections
    if req.scoring_overrides is not None:
        data["scoring_overrides"] = req.scoring_overrides
    if req.category_overrides is not None:
        data["category_overrides"] = req.category_overrides
    if req.professional_guidance is not None:
        data["professional_guidance"] = req.professional_guidance

    ctx = await ctx_repo.activate_new_version(project_id, data=data, change_log=req.change_log, updated_by=user.id)
    await db.commit()
    return ContextInfo(context_id=ctx.id, version=ctx.version, is_active=True, updated_at=ctx.updated_at, context_data=data)


# ── Prompts ──

@router.get("/prompts", response_model=list[PromptInfo])
async def list_prompts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ReviewPrompt).order_by(ReviewPrompt.name))
    return [PromptInfo(id=p.id, name=p.name, description=p.description, version=p.version, is_active=p.is_active) for p in result.scalars().all()]


@router.post("/prompts", response_model=PromptInfo)
async def create_prompt(req: PromptCreate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    prompt_repo = ReviewPromptRepository(db)
    p = await prompt_repo.create_prompt(ReviewPromptCreateData(name=req.name, description=req.description, content=req.content))
    await db.commit()
    return PromptInfo(id=p.id, name=p.name, description=p.description, version=p.version, is_active=p.is_active)


@router.put("/prompts/{prompt_id}", response_model=PromptInfo)
async def update_prompt(prompt_id: int, req: PromptCreate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ReviewPrompt).where(ReviewPrompt.id == prompt_id))
    p = result.scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Prompt不存在")
    p.name = req.name
    p.description = req.description
    p.content = req.content
    p.version += 1
    await db.commit()
    await db.refresh(p)
    return PromptInfo(id=p.id, name=p.name, description=p.description, version=p.version, is_active=p.is_active)


# ── Pipeline ──

async def _run_pipeline(
    task_id: int,
    project_id: int,
    mode: str,
    doc_ids: list[int],
    model_cfg: dict,
    steps: list[str],
    historical_doc_ids: list[int] | None = None,
    force_reanalysis: bool = False,
):
    async with async_session() as db:
        result = await db.execute(select(ReviewTask).where(ReviewTask.id == task_id))
        task = result.scalar_one_or_none()
        if task is None:
            return

        # Re-query docs in this session so status updates are tracked
        doc_result = await db.execute(select(ReviewDocument).where(ReviewDocument.id.in_(doc_ids)))
        docs = doc_result.scalars().all()

        # Load ReviewContext for this project
        context = await _load_review_context(db, project_id)
        context_data = context or {}

        # P2.C.2: 加载项目引用资料的知识切块注入审查上下文
        knowledge_chunks_text = await _load_project_knowledge_context(db, project_id)
        if knowledge_chunks_text:
            context_data["knowledge_chunks"] = knowledge_chunks_text

        # Create SkillRunner instance
        pipeline_cfg = _settings.get("review", {}).get("pipeline", {})
        runner = SkillRunner(
            model_cfg=model_cfg,
            skills_dir=SKILLS_DIR,
            context=context_data,
            retry_config=_build_review_retry_config(),
            step_max_retries=pipeline_cfg.get("step_max_retries", 3),
            step_retry_delay=pipeline_cfg.get("step_retry_delay", 5),
        )

        # P0.C.3: Freeze snapshot versions for project source refs
        from app.repositories.knowledge_source_repository import ProjectSourceRefRepository
        ref_repo = ProjectSourceRefRepository(db)
        await ref_repo.freeze_snapshot(project_id)
        await db.flush()

        task.status = "running"
        step_statuses = json.loads(task.step_statuses) if task.step_statuses else {}
        await db.commit()

        repo = ReviewTaskRepository(db)
        queue = progress_queues.get(task_id)

        try:
            async def _check_cancelled():
                """Re-read task status from DB; exit pipeline if cancelled."""
                await db.refresh(task)
                if task.status == "cancelled":
                    logger.info("Pipeline cancelled (task %d), exiting", task_id)
                    if queue:
                        await queue.put({"task_status": "cancelled"})
                    return True
                return False

            # Step 0: 预处理 (docx → Markdown)
            step_idx = 0
            step_statuses[str(step_idx)] = "running"
            task.current_step = step_idx
            task.step_statuses = json.dumps(step_statuses)
            await db.commit()
            if queue:
                await queue.put({"task_status": "running", "current_step": step_idx, "step_statuses": step_statuses})

            for doc in docs:
                if await _check_cancelled(): return
                try:
                    source_path = _resolve_stored_file_path(doc.file_path)
                    md_path = await _convert_docx(source_path, doc.id, doc.filename)
                    doc.md_path = _to_runtime_relative_path(md_path)
                    doc.content_hash = _file_hash(source_path) if source_path and os.path.exists(source_path) else None
                    doc.status = "converted"
                except Exception as e:
                    logger.error("docx conversion failed for %s: %s", doc.filename, e)
                    doc.status = "failed"
                await db.commit()

            if await _check_cancelled(): return

            step_statuses[str(step_idx)] = "completed"
            task.step_statuses = json.dumps(step_statuses)
            await db.commit()
            if queue:
                await queue.put({"task_status": "running", "current_step": step_idx + 1, "step_statuses": step_statuses, "doc_progress": [{"filename": d.filename, "status": d.status} for d in docs]})

            # Build initial pipeline inputs from docs
            converted_docs = [d for d in docs if d.status == "converted"]
            if not converted_docs:
                step_statuses = _finalize_task_failed(task)
                await db.commit()
                if queue:
                    await queue.put({"task_status": "failed", "current_step": step_idx, "step_statuses": step_statuses, "error": "所有文档转换失败，无法继续审查"})
                logger.error("All docx conversions failed for task %d", task_id)
                return
            doc_dicts = []
            for doc in converted_docs:
                md_content = ""
                if doc.md_path:
                    try:
                        md_content = await _review_file_storage.read_markdown(doc.md_path)
                    except FileNotFoundError:
                        md_content = ""
                doc_dicts.append({
                    "doc_id": str(doc.id),
                    "id": doc.id,
                    "filename": doc.filename,
                    "md_content": md_content,
                    "category": doc.category or "",
                    "version": doc.version or "",
                    "md_path": doc.md_path,
                })
            runner.state["docs"] = doc_dicts
            runner.state["project_id"] = project_id

            # Preprocess historical docs (draft mode): convert to MD, inject as context only
            if historical_doc_ids:
                hist_result = await db.execute(select(ReviewDocument).where(ReviewDocument.id.in_(historical_doc_ids)))
                hist_docs = hist_result.scalars().all()
                hist_dicts = []
                for hdoc in hist_docs:
                    if await _check_cancelled(): return
                    try:
                        source_path = _resolve_stored_file_path(hdoc.file_path)
                        md_path = await _convert_docx(source_path, hdoc.id, hdoc.filename)
                        hdoc.md_path = _to_runtime_relative_path(md_path)
                        hdoc.content_hash = _file_hash(source_path) if source_path and os.path.exists(source_path) else None
                        hdoc.status = "converted"
                    except Exception as e:
                        logger.error("historical docx conversion failed for %s: %s", hdoc.filename, e)
                        hdoc.status = "failed"
                    await db.commit()

                    md_content = ""
                    if hdoc.md_path:
                        try:
                            md_content = await _review_file_storage.read_markdown(hdoc.md_path)
                        except FileNotFoundError:
                            md_content = ""
                    if md_content:
                        hist_dicts.append({
                            "doc_id": str(hdoc.id),
                            "filename": hdoc.filename,
                            "md_content": md_content,
                            "document_type": "historical",
                        })
                runner.state["historical_docs"] = hist_dicts

            if await _check_cancelled(): return

            # Step 1: 分类 (SkillRunner)
            step_idx = 1
            step_statuses[str(step_idx)] = "running"
            task.current_step = step_idx
            task.step_statuses = json.dumps(step_statuses)
            await db.commit()
            if queue:
                await queue.put({"task_status": "running", "current_step": step_idx, "step_statuses": step_statuses})

            classify_inputs = runner.build_step_inputs("classify", runner.state)
            classify_result = await runner.run_skill("classify", classify_inputs)

            # Run version-chain as second classify sub-step
            classifications = classify_result.data.get("classifications", [])
            categories = list({c.get("category", "未分类") for c in classifications})
            doc_list_str = json.dumps(runner.state["docs"], ensure_ascii=False)
            categories_str = json.dumps(categories, ensure_ascii=False)
            version_chain_inputs = {"doc_list": doc_list_str, "categories": categories_str}
            version_chain_result = await runner.run_skill_with_retry("classify_version_chain", version_chain_inputs)

            # Store combined classify result in pipeline_state
            classify_combined = {
                "classifications": classifications,
                "categories": [{"name": cat, "keywords": [], "description": ""} for cat in categories],
                "version_chains": version_chain_result.data.get("chains", version_chain_result.data.get("version_chains", [])),
                "dependencies": version_chain_result.data.get("dependencies", []),
            }
            runner.state["classify"] = classify_combined

            # Map classify result back to per-doc DB updates
            for doc in converted_docs:
                matched = None
                for c in classifications:
                    if str(c.get("doc_id")) == str(doc.id) or c.get("doc_id") == doc.filename:
                        matched = c
                        break
                if matched:
                    doc.category = matched.get("category", "未分类")
                else:
                    doc.category = "未分类"
                # Extract version from version chains
                doc.version = ""
                for chain in classify_combined.get("version_chains", []):
                    for v in chain.get("versions", []):
                        if str(v.get("doc_id")) == str(doc.id):
                            doc.version = v.get("version", "")
                            break
                doc.status = "classified"
            await db.commit()

            step_statuses[str(step_idx)] = "completed"
            task.step_statuses = json.dumps(step_statuses)
            await db.commit()
            if queue:
                await queue.put({"task_status": "running", "current_step": step_idx + 1, "step_statuses": step_statuses})

            if await _check_cancelled(): return

            # Step 2: 逐篇分析 (SkillRunner per_analysis) — with caching
            step_idx = 2
            step_statuses[str(step_idx)] = "running"
            task.current_step = step_idx
            task.step_statuses = json.dumps(step_statuses)
            await db.commit()
            if queue:
                await queue.put({"task_status": "running", "current_step": step_idx, "step_statuses": step_statuses})

            completed = 0
            # Re-build doc_dicts with updated category/version from classify step
            for i, doc in enumerate(converted_docs):
                runner.state["docs"][i]["category"] = doc.category or ""
                runner.state["docs"][i]["version"] = doc.version or ""

            # Check cache: docs already analyzed in previous tasks can skip LLM
            doc_ids_to_analyze = [doc.id for doc in converted_docs]
            cached_analyses = {} if force_reanalysis else await _find_cached_analyses(db, doc_ids_to_analyze, task.context_version)

            # Only run LLM analysis for docs not in cache
            docs_needing_analysis = []
            for doc in converted_docs:
                if doc.id in cached_analyses:
                    # Reuse cached analysis — inject into runner state
                    ca = cached_analyses[doc.id]
                    cached_analysis = json.loads(ca.full_analysis) if ca.full_analysis else {
                        "core_problem": ca.core_problem,
                        "category": ca.category or doc.category,
                        "boundary_in": json.loads(ca.boundary_in) if ca.boundary_in else [],
                        "boundary_out": json.loads(ca.boundary_out) if ca.boundary_out else [],
                        "quality_score": ca.quality_score,
                    }
                    analyses = runner.state.get("analyses", None)
                    if analyses is None:
                        analyses = {}
                        runner.state["analyses"] = analyses
                    analyses[str(doc.id)] = cached_analysis
                    # Also create a DocAnalysis record for this task
                    await repo.save_doc_analysis(DocAnalysisPayload(
                        document_id=doc.id, task_id=task_id,
                        core_problem=ca.core_problem,
                        category=ca.category or doc.category,
                        boundary_in=ca.boundary_in,
                        boundary_out=ca.boundary_out,
                        spec_violations=ca.spec_violations,
                        quality_score=ca.quality_score,
                        full_analysis=ca.full_analysis,
                    ))
                    doc.status = "analyzed"
                    completed += 1
                    await db.commit()
                    logger.info("Cached analysis reused for doc %d (%s)", doc.id, doc.filename)
                else:
                    docs_needing_analysis.append(doc)

            # Run LLM analysis only for uncached docs
            if docs_needing_analysis:
                uncached_ids = [str(doc.id) for doc in docs_needing_analysis]
                cancelled = await runner._run_per_analysis(only_doc_ids=uncached_ids, should_cancel=_check_cancelled)
                if cancelled or await _check_cancelled(): return
                analyses_state = runner.state.get("analyses", {})

                for doc in docs_needing_analysis:
                    doc_id = str(doc.id)
                    analysis = analyses_state.get(doc_id, {})
                    if analysis and not analysis.get("error"):
                        await repo.save_doc_analysis(DocAnalysisPayload(
                            document_id=doc.id, task_id=task_id,
                            core_problem=analysis.get("core_problem"),
                            category=analysis.get("category", doc.category),
                            boundary_in=json.dumps(analysis.get("boundary_in", []), ensure_ascii=False) if isinstance(analysis.get("boundary_in"), list) else str(analysis.get("boundary_in", "")),
                            boundary_out=json.dumps(analysis.get("boundary_out", []), ensure_ascii=False) if isinstance(analysis.get("boundary_out"), list) else str(analysis.get("boundary_out", "")),
                            spec_violations=json.dumps(analysis.get("spec_violations", []), ensure_ascii=False) if isinstance(analysis.get("spec_violations"), list) else None,
                            quality_score=analysis.get("quality_score"),
                            full_analysis=json.dumps(analysis, ensure_ascii=False),
                        ))
                        doc.status = "analyzed"
                        completed += 1
                    else:
                        logger.error("analysis failed for doc %s: %s", doc.filename, analysis.get("error", "unknown"))
                        doc.status = "analysis_failed"
                    await db.commit()

                    if queue:
                        await queue.put({"task_status": "running", "current_step": step_idx, "step_statuses": step_statuses, "doc_progress": [{"filename": d.filename, "status": d.status} for d in docs]})

            task.completed_docs = completed
            total_docs_count = len(converted_docs)
            if completed == 0 and total_docs_count > 0:
                step_statuses = _finalize_task_failed(task)
                await db.commit()
                if queue:
                    await queue.put({"task_status": "failed", "current_step": step_idx, "step_statuses": step_statuses, "error": "所有文档分析失败"})
                logger.error("All analyses failed for task %d", task_id)
                return

            step_statuses[str(step_idx)] = "completed"
            task.step_statuses = json.dumps(step_statuses)
            await db.commit()
            if queue:
                await queue.put({"task_status": "running", "current_step": step_idx + 1, "step_statuses": step_statuses})

            # Remaining steps depend on mode
            if mode == "quick":
                task.status = "completed_with_warnings" if completed < total_docs_count else "completed"
                task.completed_at = now_cn()
                await db.commit()
                if queue:
                    final_status = task.status
                    await queue.put({"task_status": final_status, "current_step": len(steps)})
                return

            # Steps 3+: SkillRunner-driven review steps with retry
            step_max_retries = pipeline_cfg.get("step_max_retries", 3)
            step_retry_delay = pipeline_cfg.get("step_retry_delay", 5)

            for si in range(3, len(steps)):
                if await _check_cancelled(): return
                step_idx = si
                step_name = steps[si]
                step_result = None

                for attempt in range(step_max_retries):
                    if await _check_cancelled(): return
                    step_statuses[str(step_idx)] = "running" if attempt == 0 else "retrying"
                    task.current_step = step_idx
                    task.step_statuses = json.dumps(step_statuses)
                    await db.commit()
                    if queue:
                        await queue.put({"task_status": "running", "current_step": step_idx, "step_statuses": step_statuses})

                    try:
                        if step_name == "体系Review":
                            # Check cache: reuse 7-dimension results from any previous task
                            cached_sr = None
                            if not force_reanalysis:
                                cached_sr = await _find_cached_system_review(
                                    db,
                                    project_id,
                                    doc_ids=[doc.id for doc in converted_docs],
                                    context_version=task.context_version,
                                    model_id=task.model_id,
                                )
                            if cached_sr:
                                logger.info("Cached SystemReview reused for project %d (from SR id %d)", project_id, cached_sr.id)
                                # Copy cached results into runner state and current task's SystemReview
                                dim_results = {}
                                col_to_dim = {
                                    "business_value": "business-value",
                                    "architecture": "architecture",
                                    "competition": "competition",
                                    "product_strategy": "product-strategy",
                                    "tech_evolution": "tech-evolution",
                                    "pm_scores": "pm-assessment",
                                    "action_plan": "action-plan",
                                }
                                for col, dim_name in col_to_dim.items():
                                    raw = getattr(cached_sr, col, None)
                                    if raw:
                                        try:
                                            dim_results[dim_name] = json.loads(raw)
                                        except (json.JSONDecodeError, TypeError):
                                            dim_results[dim_name] = raw
                                runner.pipeline_state["review_dimensions"] = dim_results

                                # Copy cached SystemReview into current task's record
                                await repo.save_system_review(SystemReviewPayload(
                                    task_id=task_id, project_id=project_id,
                                    business_value=cached_sr.business_value,
                                    architecture=cached_sr.architecture,
                                    competition=cached_sr.competition,
                                    product_strategy=cached_sr.product_strategy,
                                    tech_evolution=cached_sr.tech_evolution,
                                    pm_growth=cached_sr.pm_growth,
                                    action_plan=cached_sr.action_plan,
                                    pm_scores=cached_sr.pm_scores,
                                ))
                                await db.commit()

                                if queue:
                                    await queue.put({"task_status": "running", "current_step": step_idx, "step_statuses": step_statuses, "dimension_progress": {"completed_dimensions": 7, "total_dimensions": 7, "cached": True}})
                            else:
                                # No cache — run 7 dimensions fresh
                                cancelled = await runner._run_system_review(should_cancel=_check_cancelled)
                                if cancelled or await _check_cancelled(): return
                                # Persist dimension results to SystemReview
                                dim_results = runner.state.get("review_dimensions", {})
                                # Merge all dimension results into a flat dict for DB storage
                                merged = {}
                                for dim_name, dim_data in dim_results.items():
                                    # Map dimension prompt names to DB column names
                                    col_map = {
                                        "business-value": "business_value",
                                        "architecture": "architecture",
                                        "competition": "competition",
                                        "product-strategy": "product_strategy",
                                        "tech-evolution": "tech_evolution",
                                        "pm-assessment": "pm_scores",
                                        "action-plan": "action_plan",
                                    }
                                    col = col_map.get(dim_name, dim_name)
                                    merged[col] = dim_data

                                pm_scores = extract_pm_assessment_payload(merged.get("pm_scores"))
                                await repo.save_system_review(SystemReviewPayload(
                                    task_id=task_id, project_id=project_id,
                                    business_value=json.dumps(merged.get("business_value"), ensure_ascii=False) if merged.get("business_value") else None,
                                    architecture=json.dumps(merged.get("architecture"), ensure_ascii=False) if merged.get("architecture") else None,
                                    competition=json.dumps(merged.get("competition"), ensure_ascii=False) if merged.get("competition") else None,
                                    product_strategy=json.dumps(merged.get("product_strategy"), ensure_ascii=False) if merged.get("product_strategy") else None,
                                    tech_evolution=json.dumps(merged.get("tech_evolution"), ensure_ascii=False) if merged.get("tech_evolution") else None,
                                    pm_growth=json.dumps(merged.get("pm_growth"), ensure_ascii=False) if merged.get("pm_growth") else None,
                                    action_plan=json.dumps(merged.get("action_plan"), ensure_ascii=False) if merged.get("action_plan") else None,
                                    pm_scores=json.dumps(pm_scores, ensure_ascii=False) if pm_scores else None,
                                ))
                                await db.commit()

                                # Emit dimension-level progress
                                if queue:
                                    dims_done = len(dim_results)
                                    total_dims = 7
                                    await queue.put({"task_status": "running", "current_step": step_idx, "step_statuses": step_statuses, "dimension_progress": {"completed_dimensions": dims_done, "total_dimensions": total_dims}})

                        elif step_name == "需求洞察":
                            await runner._run_insights()
                            _merge_task_step_details(task, insights=runner.state.get("insights"))
                            if queue:
                                await queue.put({"task_status": "running", "current_step": step_idx, "step_statuses": step_statuses, "insights_progress": {"completed_sub_steps": 3, "total_sub_steps": 3}})

                        elif step_name == "PRD草稿生成":
                            # Use system_review dimensions + per_analysis + historical docs to generate PRD draft
                            draft_inputs = runner._build_report_inputs(runner.state)
                            draft_inputs["output_type"] = "prd_draft"
                            # Inject historical document content for PRD context
                            hist_docs = runner.state.get("historical_docs", [])
                            if hist_docs:
                                hist_summaries = []
                                for hd in hist_docs:
                                    content = hd.get("md_content", "")
                                    # Truncate to avoid exceeding context limits
                                    if len(content) > 8000:
                                        content = content[:8000] + "\n... (截断)"
                                    hist_summaries.append(f"### 历史文档: {hd.get('filename', '未知')}\n{content}")
                                draft_inputs["historical_context"] = "\n\n---\n\n".join(hist_summaries)
                            draft_result = await runner.run_skill_with_retry("report", draft_inputs)
                            _raise_if_step_failed(step_name, draft_result)
                            runner.state["prd_draft"] = draft_result.data
                            _merge_task_step_details(task, prd_draft=draft_result.data)

                        elif step_name == "报告生成":
                            report_inputs = runner._build_report_inputs(runner.state)
                            report_inputs["output_type"] = "report"
                            report_result = await runner.run_skill_with_retry("report", report_inputs)
                            _raise_if_step_failed(step_name, report_result)
                            runner.state["report"] = report_result.data
                            # Store polished report markdown if available
                            md_content = report_result.data.get("markdown") or report_result.data.get("report_content") or report_result.data.get("raw_text")
                            if md_content:
                                _merge_task_step_details(task, report_markdown=md_content)

                        step_result = "success"
                        break
                    except Exception as e:
                        logger.warning("Step %d (%s) attempt %d/%d failed: %s", si, step_name, attempt + 1, step_max_retries, e)
                        if attempt < step_max_retries - 1:
                            await asyncio.sleep(step_retry_delay)

                if step_result != "success":
                    logger.error("Step %d (%s) exhausted %d retries", si, step_name, step_max_retries)
                    # Abort pipeline: subsequent steps depend on this step's output
                    step_statuses = _finalize_task_failed(task)
                    await db.commit()
                    if queue:
                        await queue.put({"task_status": "failed", "current_step": step_idx, "step_statuses": step_statuses})
                    return
                else:
                    step_statuses[str(step_idx)] = "completed"
                task.step_statuses = json.dumps(step_statuses)
                await db.commit()
                if queue:
                    await queue.put({"task_status": "running", "current_step": step_idx + 1, "step_statuses": step_statuses})

            # Final task status: completed or completed_with_warnings
            task.status = "completed_with_warnings" if task.completed_docs < task.total_docs else "completed"
            task.completed_at = now_cn()
            await db.commit()
            if queue:
                final_status = task.status
                await queue.put({"task_status": final_status, "current_step": len(steps)})

        except Exception as e:
            logger.error("Pipeline failed: %s", e)
            step_statuses = _finalize_task_failed(task)
            await db.commit()
            if queue:
                await queue.put({
                    "task_status": "failed",
                    "current_step": task.current_step,
                    "step_statuses": step_statuses,
                    "error": str(e),
                })
        finally:
            progress_queues.pop(task_id, None)


async def _convert_docx(file_path: str | None, doc_id: int, original_filename: str | None = None, force: bool = False) -> str:
    """Delegate DOCX conversion to ReviewFileStorage, return md_path."""
    result = await _review_file_storage.convert_docx(
        file_path=file_path, document_id=doc_id,
        original_filename=original_filename, force=force,
        skills_dir=SKILLS_DIR,
    )
    return result.md_path


def _file_hash(file_path: str) -> str:
    return _review_file_storage.compute_file_hash(file_path)

def _render_markdown_report(analyses: list[AnalysisInfo], sr_data: dict, pm_assessment: dict | None, task: ReviewTask | None) -> str:
    artifacts = _extract_task_artifacts(task)
    if artifacts.get("report_markdown"):
        return str(artifacts["report_markdown"])

    lines = [f"# 需求审查报告", ""]
    if task:
        lines.append(f"- 审查模式: {task.mode}")
        lines.append(f"- 评审上下文版本: V{task.context_version}")
        lines.append(f"- 生成时间: {now_cn().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## 逐篇分析")
    lines.append("")
    for a in analyses:
        lines.append(f"### {a.filename or f'文档{a.document_id}'}")
        lines.append(f"- 核心问题: {a.core_problem or '-'}")
        lines.append(f"- 分类: {a.category or '-'}")
        lines.append(f"- 质量评分: {a.quality_score or '-'} / 5")
        if a.expert_review:
            summary = a.expert_review.get("summary") or "-"
            lines.append(f"- 专家意见结论: {summary}")
            checks = a.expert_review.get("checks") or []
            status_map = {"pass": "通过", "risk": "有风险", "missing": "缺失"}
            for check in checks:
                rule_name = check.get("rule_name") or check.get("rule_key") or "未命名规则"
                status = status_map.get(check.get("status"), check.get("status") or "未判断")
                evidence = check.get("evidence") or "-"
                suggestion = check.get("suggestion") or "-"
                lines.append(f"  - {rule_name}: {status}；依据：{evidence}；建议：{suggestion}")
        if a.spec_violations:
            lines.append(f"- 规范缺失: {', '.join(str(v) for v in a.spec_violations)}")
        lines.append("")

    if sr_data:
        lines.append("## 体系Review")
        lines.append("")
        for key, label in [("business_value", "业务价值"), ("architecture", "体系架构"), ("competition", "竞争定位"), ("action_plan", "行动计划")]:
            val = sr_data.get(key)
            if val:
                lines.append(f"### {label}")
                lines.append(f"```json\n{json.dumps(val, ensure_ascii=False, indent=2)}\n```")
                lines.append("")

    return "\n".join(lines)
