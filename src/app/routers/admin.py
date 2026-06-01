"""管理路由：用户管理、Prompt 模板、模型配置（含 API Key 管理）"""

import logging
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.utils import now_cn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import DEFAULT_SKILL_CONFIGS, get_db
from app.logging_config import get_logs_dir
from app.middleware.auth import get_current_user
from app.models.user import Conversation, Message, ModelConfig, PromptTemplate, SkillConfig, User
from app.services.crypto import decrypt_key, encrypt_key, mask_key
from app.services.llm import check_connection, speed_test

logger = logging.getLogger(__name__)
router = APIRouter()


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

@router.get("/users")
async def list_users(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_active_at": u.last_active_at.isoformat() if u.last_active_at else None,
        }
        for u in users
    ]


@router.post("/users")
async def create_user(
    req: UserCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    from app.services.auth import hash_password

    existing = await db.execute(
        select(User).where(User.username == req.username)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    new_user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
    )
    db.add(new_user)
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
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.role is not None:
        target.role = req.role
    if req.is_active is not None:
        target.is_active = req.is_active
    if req.password:
        from app.services.auth import hash_password
        target.password_hash = hash_password(req.password)

    await db.commit()
    return {"status": "ok"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.username == "admin":
        raise HTTPException(status_code=400, detail="不能删除默认管理员")

    await db.delete(target)
    await db.commit()
    return {"status": "ok"}


# ── Prompt Templates ─────────────────────────────────────────────────────────

@router.get("/prompts")
async def list_prompts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    result = await db.execute(select(PromptTemplate).order_by(PromptTemplate.name))
    templates = result.scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "system_prompt": t.system_prompt,
            "user_prompt_template": t.user_prompt_template,
            "is_builtin": t.is_builtin,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in templates
    ]


@router.post("/prompts")
async def create_prompt(
    req: PromptCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    existing = await db.execute(
        select(PromptTemplate).where(PromptTemplate.name == req.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="模板名已存在")

    pt = PromptTemplate(
        name=req.name,
        description=req.description,
        system_prompt=req.system_prompt,
        user_prompt_template=req.user_prompt_template,
        is_builtin=False,
        created_by=user.id,
    )
    db.add(pt)
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
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == prompt_id)
    )
    pt = result.scalar_one_or_none()
    if not pt:
        raise HTTPException(status_code=404, detail="模板不存在")

    if req.name is not None:
        pt.name = req.name
    if req.description is not None:
        pt.description = req.description
    if req.system_prompt is not None:
        pt.system_prompt = req.system_prompt
    if req.user_prompt_template is not None:
        pt.user_prompt_template = req.user_prompt_template

    await db.commit()
    return {"status": "ok"}


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(
    prompt_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == prompt_id)
    )
    pt = result.scalar_one_or_none()
    if not pt:
        raise HTTPException(status_code=404, detail="模板不存在")
    if pt.is_builtin:
        raise HTTPException(status_code=400, detail="不能删除内置模板")

    await db.delete(pt)
    await db.commit()
    return {"status": "ok"}


# ── Model Configs (API Key Management) ───────────────────────────────────────

@router.get("/models")
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出所有模型配置，API Key 脱敏显示"""
    _require_admin(user)
    secret = _get_jwt_secret()

    result = await db.execute(
        select(ModelConfig)
        .where(ModelConfig.deleted_by_user == False)
        .order_by(ModelConfig.display_order, ModelConfig.name, ModelConfig.id)
    )
    models = result.scalars().all()

    items = []
    for mc in models:
        # Decrypt and mask API key for display
        masked = ""
        if mc.encrypted_api_key:
            try:
                plain = decrypt_key(mc.encrypted_api_key, secret)
                masked = mask_key(plain)
            except Exception:
                masked = "****(解密失败)"

        items.append({
            "id": mc.id,
            "display_order": mc.display_order,
            "model_id": mc.model_id,
            "name": mc.name,
            "provider": mc.provider,
            "api_base": mc.api_base,
            "api_key_masked": masked,
            "has_api_key": bool(mc.encrypted_api_key),
            "llm_model": mc.llm_model,
            "max_tokens": mc.max_tokens,
            "temperature": mc.temperature,
            "enabled": mc.enabled,
            "last_test_status": mc.last_test_status,
            "last_test_time": mc.last_test_time.isoformat() if mc.last_test_time else None,
            "last_test_latency_ms": mc.last_test_latency_ms,
        })
    return items


@router.post("/models")
async def create_model(
    req: ModelConfigCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新模型配置"""
    _require_admin(user)
    existing = await db.execute(select(ModelConfig).where(ModelConfig.model_id == req.model_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="模型 ID 已存在")

    max_order_result = await db.execute(select(func.max(ModelConfig.display_order)))
    next_order = (max_order_result.scalar_one_or_none() or -1) + 1

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
    )
    if req.api_key:
        secret = get_settings().get("auth", {}).get("secret_key", "")
        mc.encrypted_api_key = encrypt_key(req.api_key, secret)
    db.add(mc)
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
    result = await db.execute(select(ModelConfig).where(ModelConfig.deleted_by_user == False))
    models = result.scalars().all()
    existing_ids = {mc.model_id for mc in models}
    requested_ids = list(req.model_ids)

    if set(requested_ids) != existing_ids:
        raise HTTPException(status_code=400, detail="模型排序列表与现有模型不一致")

    by_id = {mc.model_id: mc for mc in models}
    for index, current_id in enumerate(requested_ids):
        by_id[current_id].display_order = index

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
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.model_id == model_id,
            ModelConfig.deleted_by_user == False,
        )
    )
    mc = result.scalar_one_or_none()
    if not mc:
        raise HTTPException(status_code=404, detail="模型不存在")

    builtin_model_ids = {item["id"] for item in get_settings().get("models", [])}
    if model_id in builtin_model_ids:
        mc.deleted_by_user = True
        mc.enabled = False
    else:
        await db.delete(mc)
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
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.model_id == model_id,
            ModelConfig.deleted_by_user == False,
        )
    )
    mc = result.scalar_one_or_none()
    if not mc:
        raise HTTPException(status_code=404, detail="模型不存在")

    if req.name is not None:
        mc.name = req.name
    if req.provider is not None:
        mc.provider = req.provider
    if req.api_base is not None:
        mc.api_base = req.api_base
    if req.llm_model is not None:
        mc.llm_model = req.llm_model
    if req.max_tokens is not None:
        mc.max_tokens = req.max_tokens
    if req.temperature is not None:
        mc.temperature = req.temperature
    if req.enabled is not None:
        mc.enabled = req.enabled

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
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.model_id == model_id,
            ModelConfig.deleted_by_user == False,
        )
    )
    mc = result.scalar_one_or_none()
    if not mc:
        raise HTTPException(status_code=404, detail="模型不存在")

    secret = _get_jwt_secret()
    mc.encrypted_api_key = encrypt_key(req.api_key, secret)
    # Reset test status since key changed
    mc.last_test_status = "unknown"
    mc.last_test_time = None
    mc.last_test_latency_ms = None

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
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.model_id == model_id,
            ModelConfig.deleted_by_user == False,
        )
    )
    mc = result.scalar_one_or_none()
    if not mc:
        raise HTTPException(status_code=404, detail="模型不存在")

    if not mc.encrypted_api_key:
        return {"status": "fail", "detail": "未配置 API Key"}

    secret = _get_jwt_secret()
    try:
        api_key = decrypt_key(mc.encrypted_api_key, secret)
    except Exception:
        return {"status": "fail", "detail": "API Key 解密失败"}

    # Run test
    test_result = await check_connection(mc.api_base, api_key, mc.llm_model)

    # Update test status in DB
    mc.last_test_status = test_result["status"]
    mc.last_test_time = now_cn()
    if test_result["status"] == "ok":
        mc.last_test_latency_ms = None
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
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.model_id == model_id,
            ModelConfig.deleted_by_user == False,
        )
    )
    mc = result.scalar_one_or_none()
    if not mc:
        raise HTTPException(status_code=404, detail="模型不存在")

    if not mc.encrypted_api_key:
        return {"status": "fail", "detail": "未配置 API Key", "latency_ms": None}

    secret = _get_jwt_secret()
    try:
        api_key = decrypt_key(mc.encrypted_api_key, secret)
    except Exception:
        return {"status": "fail", "detail": "API Key 解密失败", "latency_ms": None}

    # Run speed test
    test_result = await speed_test(mc.api_base, api_key, mc.llm_model)

    # Update test status in DB
    mc.last_test_status = test_result["status"]
    mc.last_test_time = now_cn()
    mc.last_test_latency_ms = test_result.get("latency_ms")
    await db.commit()

    return test_result


# ── Skill Configs ────────────────────────────────────────────────────────────

async def _ensure_default_skill_configs(db: AsyncSession):
    result = await db.execute(select(SkillConfig))
    existing = {skill.skill_id: skill for skill in result.scalars().all()}

    changed = False
    for item in DEFAULT_SKILL_CONFIGS:
        skill = existing.get(item["skill_id"])
        if skill is None:
            db.add(SkillConfig(**item, is_builtin=True))
            changed = True
        else:
            skill.name = item["name"]
            skill.description = item["description"]
            skill.local_path = item["local_path"]
            skill.display_order = item["display_order"]
            skill.is_builtin = True
            changed = True

    if changed:
        await db.commit()


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
    await _ensure_default_skill_configs(db)
    result = await db.execute(select(SkillConfig).order_by(SkillConfig.display_order, SkillConfig.skill_id))
    return [_serialize_skill(skill) for skill in result.scalars().all()]


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    req: SkillUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    await _ensure_default_skill_configs(db)
    result = await db.execute(select(SkillConfig).where(SkillConfig.skill_id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill不存在")

    skill.update_url = req.update_url
    skill.updated_at = now_cn()
    await db.commit()
    await db.refresh(skill)
    return _serialize_skill(skill)


# ── Stats ────────────────────────────────────────────────────────────────────

def _parse_log_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        from app.utils import _CN_TZ
        return parsed.replace(tzinfo=_CN_TZ)
    return parsed.astimezone(timezone.utc)


def _load_recent_access_records(
    logs_dir: str | Path | None = None,
    now: datetime | None = None,
    days: int = 7,
    limit: int = 50,
) -> list[dict]:
    log_dir = Path(logs_dir) if logs_dir is not None else get_logs_dir()
    audit_file = log_dir / "audit.jsonl"
    if not audit_file.exists():
        return []

    from app.utils import _CN_TZ
    current = now or datetime.now(_CN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_CN_TZ)
    cutoff = current - timedelta(days=days)

    records = []
    with audit_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = _parse_log_timestamp(entry.get("timestamp"))
            if ts is None or ts < cutoff:
                continue

            request = entry.get("request") or {}
            actor = entry.get("actor") or {}
            records.append({
                "timestamp": ts.isoformat(),
                "username": actor.get("username") or "-",
                "action": entry.get("action") or "-",
                "method": request.get("method") or "-",
                "path": request.get("path") or "-",
                "client_ip": request.get("client_ip") or "-",
                "result": entry.get("result") or "-",
            })

    records.sort(key=lambda item: item["timestamp"], reverse=True)
    return records[:limit]


@router.get("/stats")
async def get_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)

    user_count = await db.execute(select(func.count(User.id)))
    conv_count = await db.execute(select(func.count(Conversation.id)))
    msg_count = await db.execute(select(func.count(Message.id)))

    return {
        "user_count": user_count.scalar(),
        "conversation_count": conv_count.scalar(),
        "message_count": msg_count.scalar(),
        "recent_visits": _load_recent_access_records(days=7, limit=50),
    }
