"""管理路由：用户管理、Prompt 模板、模型配置（含 API Key 管理）"""

import logging

from app.utils import now_cn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.log_writers.audit_log_writer import AuditLogWriter
from app.log_writers.audit_log_reader import AuditLogReader
from app.middleware.auth import get_current_user
from app.models.user import Conversation, Message, ModelConfig, PromptTemplate, SkillConfig, User
from app.repositories.user_repository import UserRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.prompt_template_repository import PromptTemplateRepository
from app.repositories.skill_config_repository import SkillConfigRepository
from app.services.crypto import decrypt_key, encrypt_key, mask_key
from app.services.llm import check_connection, speed_test

logger = logging.getLogger(__name__)
router = APIRouter()

_audit_log_writer = AuditLogWriter()
_audit_log_reader = AuditLogReader()


def _get_jwt_secret() -> str:
    settings = get_settings()
    secret = settings.get("auth", {}).get("secret_key")
    if not secret or secret == "change-me-in-production":
        raise RuntimeError("JWT secret 未配置或使用默认值，请设置 .env 中的 JWT_SECRET")
    return secret


def _require_admin(user: User):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")


# ── Schemas ──────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="user", pattern=r"^(user|admin)$")


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(user|admin)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class PromptCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None


class PromptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None


class ModelConfigUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    api_base: str | None = None
    llm_model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    enabled: bool | None = None
    thinking_supported: bool | None = None
    thinking_level: str | None = None
    thinking_adapter: str | None = None
    thinking_payload: str | None = None

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, v):
        if v is not None and v not in ("off", "low", "high"):
            raise ValueError("thinking_level must be off, low, or high")
        return v

    @field_validator("thinking_adapter")
    @classmethod
    def validate_thinking_adapter(cls, v):
        if v is not None and v not in ("none", "openai_reasoning", "deepseek_reasoner", "qwen_thinking", "custom_json"):
            raise ValueError("invalid thinking_adapter")
        return v


class ModelConfigCreate(BaseModel):
    model_id: str
    name: str
    provider: str = "openai_compatible"
    api_base: str
    llm_model: str
    max_tokens: int = 4096
    temperature: float = 0.7
    enabled: bool = True
    api_key: str | None = None
    thinking_supported: bool = False
    thinking_level: str = "off"
    thinking_adapter: str = "none"
    thinking_payload: str | None = None

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, v):
        if v not in ("off", "low", "high"):
            raise ValueError("thinking_level must be off, low, or high")
        return v

    @field_validator("thinking_adapter")
    @classmethod
    def validate_thinking_adapter(cls, v):
        if v not in ("none", "openai_reasoning", "deepseek_reasoner", "qwen_thinking", "custom_json"):
            raise ValueError("invalid thinking_adapter")
        return v


class ApiKeyUpdate(BaseModel):
    api_key: str


class ModelOrderUpdate(BaseModel):
    model_ids: list[str] = Field(default_factory=list, min_length=1)


class SkillUpdate(BaseModel):
    update_url: str | None = Field(default=None, max_length=1000)

    @field_validator("update_url")
    @classmethod
    def normalize_update_url(cls, value: str | None):
        if value is None:
            return None
        value = value.strip()
        return value or None


# ── Users ────────────────────────────────────────────────────────────────────

def _serialize_user(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_active_at": u.last_active_at.isoformat() if u.last_active_at else None,
    }


@router.get("/users")
async def list_users(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    repo = UserRepository(db)
    users = await repo.list_all()
    return [_serialize_user(u) for u in users]


@router.post("/users")
async def create_user(
    req: UserCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    from app.services.auth import hash_password

    repo = UserRepository(db)
    existing = await repo.get_by_username(req.username)
    if existing is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")

    new_user = await repo.create(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
    )
    await db.commit()
    return {"status": "ok", "id": new_user.id}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    req: UserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    from app.services.auth import hash_password

    repo = UserRepository(db)
    target = await repo.update(
        user_id,
        role=req.role,
        is_active=req.is_active,
        password_hash=(
            hash_password(req.password) if req.password else None
        ),
    )
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    await db.commit()
    return {"status": "ok"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    repo = UserRepository(db)
    target = await repo.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.username == "admin":
        raise HTTPException(status_code=400, detail="不能删除默认管理员")

    await repo.delete(user_id)
    await db.commit()
    return {"status": "ok"}


# ── Prompt Templates ─────────────────────────────────────────────────────────

def _serialize_prompt(t: PromptTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "system_prompt": t.system_prompt,
        "user_prompt_template": t.user_prompt_template,
        "is_builtin": t.is_builtin,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/prompts")
async def list_prompts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    repo = PromptTemplateRepository(db)
    templates = await repo.list_all()
    return [_serialize_prompt(t) for t in templates]


@router.post("/prompts")
async def create_prompt(
    req: PromptCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    repo = PromptTemplateRepository(db)
    existing = await repo.get_by_name(req.name)
    if existing is not None:
        raise HTTPException(status_code=400, detail="模板名已存在")

    pt = await repo.create(
        name=req.name,
        description=req.description,
        system_prompt=req.system_prompt,
        user_prompt_template=req.user_prompt_template,
        is_builtin=False,
        created_by=user.id,
    )
    await db.commit()
    return {"status": "ok", "id": pt.id}


@router.put("/prompts/{prompt_id}")
async def update_prompt(
    prompt_id: int,
    req: PromptUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    repo = PromptTemplateRepository(db)
    pt = await repo.update(
        prompt_id,
        name=req.name,
        description=req.description,
        system_prompt=req.system_prompt,
        user_prompt_template=req.user_prompt_template,
    )
    if pt is None:
        raise HTTPException(status_code=404, detail="模板不存在")

    await db.commit()
    return {"status": "ok"}


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(
    prompt_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    repo = PromptTemplateRepository(db)
    pt = await repo.get_by_id(prompt_id)
    if pt is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    if pt.is_builtin:
        raise HTTPException(status_code=400, detail="不能删除内置模板")

    await repo.delete(prompt_id)
    await db.commit()
    return {"status": "ok"}


# ── Model Configs (API Key Management) ───────────────────────────────────────

def _serialize_model(mc: ModelConfig, masked_key: str = "") -> dict:
    return {
        "id": mc.id,
        "display_order": mc.display_order,
        "model_id": mc.model_id,
        "name": mc.name,
        "provider": mc.provider,
        "api_base": mc.api_base,
        "api_key_masked": masked_key,
        "has_api_key": bool(mc.encrypted_api_key),
        "llm_model": mc.llm_model,
        "max_tokens": mc.max_tokens,
        "temperature": mc.temperature,
        "enabled": mc.enabled,
        "thinking_supported": mc.thinking_supported,
        "thinking_level": mc.thinking_level,
        "thinking_adapter": mc.thinking_adapter,
        "thinking_payload": mc.thinking_payload,
        "last_test_status": mc.last_test_status,
        "last_test_time": mc.last_test_time.isoformat() if mc.last_test_time else None,
        "last_test_latency_ms": mc.last_test_latency_ms,
    }


@router.get("/models")
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出所有模型配置，API Key 脱敏显示"""
    _require_admin(user)
    secret = _get_jwt_secret()
    repo = ModelConfigRepository(db)
    models = await repo.list_all()

    items = []
    for mc in models:
        masked = ""
        if mc.encrypted_api_key:
            try:
                plain = decrypt_key(mc.encrypted_api_key, secret)
                masked = mask_key(plain)
            except Exception:
                masked = "****(解密失败)"
        items.append(_serialize_model(mc, masked_key=masked))
    return items


@router.post("/models")
async def create_model(
    req: ModelConfigCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新模型配置"""
    _require_admin(user)
    repo = ModelConfigRepository(db)
    existing = await repo.get_by_model_id(req.model_id)
    if existing is not None:
        raise HTTPException(status_code=400, detail="模型 ID 已存在")

    next_order = (await repo.get_max_display_order()) + 1

    mc = ModelConfig(
        display_order=next_order,
        model_id=req.model_id,
        name=req.name,
        provider=req.provider,
        api_base=req.api_base,
        llm_model=req.llm_model,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        enabled=req.enabled,
        deleted_by_user=False,
        thinking_supported=req.thinking_supported,
        thinking_level=req.thinking_level,
        thinking_adapter=req.thinking_adapter,
        thinking_payload=req.thinking_payload,
    )
    if req.api_key:
        secret = get_settings().get("auth", {}).get("secret_key", "")
        mc.encrypted_api_key = encrypt_key(req.api_key, secret)
    await repo.create(mc)
    await db.commit()
    return {"status": "ok"}


@router.put("/models/order")
async def update_model_order(
    req: ModelOrderUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """批量更新模型显示顺序。"""
    _require_admin(user)
    repo = ModelConfigRepository(db)
    models = await repo.list_all()
    existing_ids = {mc.model_id for mc in models}
    requested_ids = list(req.model_ids)

    if set(requested_ids) != existing_ids:
        raise HTTPException(status_code=400, detail="模型排序列表与现有模型不一致")

    await repo.update_display_order(requested_ids)
    await db.commit()
    return {"status": "ok"}


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除模型配置"""
    _require_admin(user)
    repo = ModelConfigRepository(db)
    mc = await repo.get_by_model_id(model_id)
    if mc is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    builtin_model_ids = {item["id"] for item in get_settings().get("models", [])}
    tombstone = model_id in builtin_model_ids
    await repo.delete(model_id, tombstone=tombstone)
    await db.commit()
    return {"status": "ok"}


@router.put("/models/{model_id}")
async def update_model_config(
    model_id: str,
    req: ModelConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新模型配置（名称、API Base、参数等）"""
    _require_admin(user)
    repo = ModelConfigRepository(db)
    update_kwargs = dict(
        name=req.name,
        provider=req.provider,
        api_base=req.api_base,
        llm_model=req.llm_model,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        enabled=req.enabled,
        thinking_supported=req.thinking_supported,
        thinking_level=req.thinking_level,
        thinking_adapter=req.thinking_adapter,
    )
    if "thinking_payload" in req.model_fields_set:
        update_kwargs["thinking_payload"] = req.thinking_payload
    mc = await repo.update(model_id, **update_kwargs)
    if mc is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    await db.commit()
    return {"status": "ok"}


@router.put("/models/{model_id}/api-key")
async def update_api_key(
    model_id: str,
    req: ApiKeyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新模型的 API Key（加密存储）"""
    _require_admin(user)
    repo = ModelConfigRepository(db)
    mc = await repo.get_by_model_id(model_id)
    if mc is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    secret = _get_jwt_secret()
    await repo.update_api_key(model_id, encrypt_key(req.api_key, secret))

    await db.commit()
    return {"status": "ok", "api_key_masked": mask_key(req.api_key)}


@router.post("/models/{model_id}/test-connection")
async def model_test_connection(
    model_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """测试模型 API 连接"""
    _require_admin(user)
    repo = ModelConfigRepository(db)
    mc = await repo.get_by_model_id(model_id)
    if mc is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    if not mc.encrypted_api_key:
        return {"status": "fail", "detail": "未配置 API Key"}

    secret = _get_jwt_secret()
    try:
        api_key = decrypt_key(mc.encrypted_api_key, secret)
    except Exception:
        return {"status": "fail", "detail": "API Key 解密失败"}

    test_result = await check_connection(mc.api_base, api_key, mc.llm_model)

    await repo.update_test_status(
        model_id,
        status=test_result["status"],
        test_time=now_cn(),
    )
    await db.commit()

    return test_result


@router.post("/models/{model_id}/speed-test")
async def model_speed_test(
    model_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """测试模型 API 响应速度"""
    _require_admin(user)
    repo = ModelConfigRepository(db)
    mc = await repo.get_by_model_id(model_id)
    if mc is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    if not mc.encrypted_api_key:
        return {"status": "fail", "detail": "未配置 API Key", "latency_ms": None}

    secret = _get_jwt_secret()
    try:
        api_key = decrypt_key(mc.encrypted_api_key, secret)
    except Exception:
        return {"status": "fail", "detail": "API Key 解密失败", "latency_ms": None}

    test_result = await speed_test(mc.api_base, api_key, mc.llm_model)

    await repo.update_test_status(
        model_id,
        status=test_result["status"],
        test_time=now_cn(),
        latency_ms=test_result.get("latency_ms"),
    )
    await db.commit()

    return test_result


# ── Skill Configs ────────────────────────────────────────────────────────────

def _serialize_skill(skill: SkillConfig):
    return {
        "id": skill.id,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "local_path": skill.local_path,
        "update_url": skill.update_url,
        "display_order": skill.display_order,
        "is_builtin": skill.is_builtin,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


@router.get("/skills")
async def list_skills(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    repo = SkillConfigRepository(db)
    await repo.ensure_defaults()
    await db.commit()
    skills = await repo.list_all()
    return [_serialize_skill(skill) for skill in skills]


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    req: SkillUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    repo = SkillConfigRepository(db)
    await repo.ensure_defaults()
    await db.commit()
    skill = await repo.update(skill_id, update_url=req.update_url, updated_at=now_cn())
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill不存在")

    await db.commit()
    return _serialize_skill(skill)


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)

    user_count = await db.execute(select(func.count(User.id)))
    conv_count = await db.execute(select(func.count(Conversation.id)))
    msg_count = await db.execute(select(func.count(Message.id)))

    recent = _audit_log_reader.list_recent_access_records(days=7, limit=50)
    recent_dicts = [
        {
            "timestamp": r.timestamp,
            "username": r.username,
            "action": r.action,
            "method": r.method,
            "path": r.path,
            "client_ip": r.client_ip,
            "result": r.result,
        }
        for r in recent
    ]

    return {
        "user_count": user_count.scalar(),
        "conversation_count": conv_count.scalar(),
        "message_count": msg_count.scalar(),
        "recent_visits": recent_dicts,
    }
