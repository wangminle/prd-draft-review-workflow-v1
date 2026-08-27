"""Pi Agent 配置路由 — 独立于通用模型配置的能力模块管理。"""

import logging

from app.utils import now_cn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.repositories.pi_agent_config_repository import PiAgentConfigRepository
from app.services.crypto import decrypt_key, encrypt_key, mask_key
from app.services.llm import check_connection, speed_test

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_jwt_secret() -> str:
    settings = get_settings()
    secret = settings.get("auth", {}).get("secret_key")
    from app.services.jwt_secret import assert_jwt_secret_safe
    return assert_jwt_secret_safe(secret)


def _require_admin(user: User):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")


# ── Schemas ──────────────────────────────────────────────────────────────────


class PiAgentConfigUpdate(BaseModel):
    """Pi Agent 配置更新请求（所有字段可选，仅传入的字段会被更新）。"""

    # LLM
    llm_provider: str | None = None
    llm_api_base: str | None = None
    llm_model: str | None = None
    llm_max_tokens: int | None = None
    llm_temperature: float | None = None
    # Search
    search_enabled: bool | None = None
    search_provider: str | None = None
    search_api_base: str | None = None
    search_max_results: int | None = None
    # Vision
    vision_enabled: bool | None = None
    vision_provider: str | None = None
    vision_api_base: str | None = None
    vision_model: str | None = None
    # Extension
    extension_path: str | None = None
    extension_max_tool_calls: int | None = Field(default=None, ge=1, le=50)
    extension_blocked_tools: str | None = None
    # Skills
    skills_install_dir: str | None = None
    skills_registry_url: str | None = None
    skills_installed_list: str | None = None
    # General
    system_prompt: str | None = None
    enabled: bool | None = None


class PiAgentApiKeyUpdate(BaseModel):
    api_key: str


class PiAgentSearchApiKeyUpdate(BaseModel):
    api_key: str | None = None


class PiAgentVisionApiKeyUpdate(BaseModel):
    api_key: str | None = None


# ── Serialization ────────────────────────────────────────────────────────────


def _serialize_pi_agent_config(config, *, secret: str) -> dict:
    """将 PiAgentConfig ORM 对象序列化为 API 响应，API Key 脱敏。"""
    llm_key_masked = ""
    if config.llm_encrypted_api_key:
        try:
            llm_key_masked = mask_key(decrypt_key(config.llm_encrypted_api_key, secret))
        except Exception:
            llm_key_masked = "****(解密失败)"

    search_key_masked = ""
    if config.search_encrypted_api_key:
        try:
            search_key_masked = mask_key(decrypt_key(config.search_encrypted_api_key, secret))
        except Exception:
            search_key_masked = "****(解密失败)"

    vision_key_masked = ""
    if config.vision_encrypted_api_key:
        try:
            vision_key_masked = mask_key(decrypt_key(config.vision_encrypted_api_key, secret))
        except Exception:
            vision_key_masked = "****(解密失败)"

    return {
        # LLM
        "llm_provider": config.llm_provider,
        "llm_api_base": config.llm_api_base,
        "llm_model": config.llm_model,
        "llm_api_key_masked": llm_key_masked,
        "llm_has_api_key": bool(config.llm_encrypted_api_key),
        "llm_max_tokens": config.llm_max_tokens,
        "llm_temperature": config.llm_temperature,
        # Search
        "search_enabled": config.search_enabled,
        "search_provider": config.search_provider,
        "search_api_base": config.search_api_base,
        "search_api_key_masked": search_key_masked,
        "search_has_api_key": bool(config.search_encrypted_api_key),
        "search_max_results": config.search_max_results,
        # Vision
        "vision_enabled": config.vision_enabled,
        "vision_provider": config.vision_provider,
        "vision_api_base": config.vision_api_base,
        "vision_api_key_masked": vision_key_masked,
        "vision_has_api_key": bool(config.vision_encrypted_api_key),
        "vision_model": config.vision_model,
        # Extension
        "extension_path": config.extension_path,
        "extension_max_tool_calls": config.extension_max_tool_calls,
        "extension_blocked_tools": config.extension_blocked_tools,
        # Skills
        "skills_install_dir": config.skills_install_dir,
        "skills_registry_url": config.skills_registry_url,
        "skills_installed_list": config.skills_installed_list,
        # General
        "system_prompt": config.system_prompt,
        "enabled": config.enabled,
        "last_test_status": config.last_test_status,
        "last_test_time": config.last_test_time.isoformat() if config.last_test_time else None,
        "last_test_latency_ms": config.last_test_latency_ms,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_pi_agent_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取 Pi Agent 配置。"""
    _require_admin(user)
    secret = _get_jwt_secret()
    repo = PiAgentConfigRepository(db)
    config = await repo.get_or_create()
    return _serialize_pi_agent_config(config, secret=secret)


@router.put("/config")
async def update_pi_agent_config(
    req: PiAgentConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新 Pi Agent 配置（除 API Key 外的所有字段）。

    Only fields explicitly included in the request body are forwarded
    to the repository.  Nullable fields sent as ``null`` will clear
    the stored value (set to NULL).
    """
    _require_admin(user)
    secret = _get_jwt_secret()
    repo = PiAgentConfigRepository(db)

    update_kwargs = {}
    for field_name in req.model_fields_set:
        update_kwargs[field_name] = getattr(req, field_name)

    config = await repo.update(**update_kwargs)
    await db.commit()
    return _serialize_pi_agent_config(config, secret=secret)


@router.put("/config/llm-api-key")
async def update_llm_api_key(
    req: PiAgentApiKeyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新 Pi Agent LLM API Key（加密存储）。"""
    _require_admin(user)
    secret = _get_jwt_secret()
    repo = PiAgentConfigRepository(db)
    encrypted = encrypt_key(req.api_key, secret)
    await repo.update_llm_api_key(encrypted)
    await db.commit()
    return {"status": "ok", "api_key_masked": mask_key(req.api_key)}


@router.put("/config/search-api-key")
async def update_search_api_key(
    req: PiAgentSearchApiKeyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新 Pi Agent Search Tool API Key。"""
    _require_admin(user)
    secret = _get_jwt_secret()
    repo = PiAgentConfigRepository(db)
    if req.api_key:
        encrypted = encrypt_key(req.api_key, secret)
    else:
        encrypted = None
    await repo.update_search_api_key(encrypted)
    await db.commit()
    return {"status": "ok", "api_key_masked": mask_key(req.api_key) if req.api_key else ""}


@router.put("/config/vision-api-key")
async def update_vision_api_key(
    req: PiAgentVisionApiKeyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新 Pi Agent Vision API Key。"""
    _require_admin(user)
    secret = _get_jwt_secret()
    repo = PiAgentConfigRepository(db)
    if req.api_key:
        encrypted = encrypt_key(req.api_key, secret)
    else:
        encrypted = None
    await repo.update_vision_api_key(encrypted)
    await db.commit()
    return {"status": "ok", "api_key_masked": mask_key(req.api_key) if req.api_key else ""}


class PiAgentTempTestConfig(BaseModel):
    """连接测试/测速的可选临时配置（GitHub Issue #2）。

    用于「先测试、后保存」：前端把表单当前值放进请求体，后端优先用
    请求值测试；未传字段回退数据库已保存配置。临时值（尤其 api_key）
    仅在本次请求内存中生效，不落库、不写日志——保存仍需走「保存配置」。
    """

    api_key: str | None = None
    llm_provider: str | None = None
    llm_api_base: str | None = None
    llm_model: str | None = None


_OPENAI_COMPATIBLE_PROVIDERS = frozenset({
    "deepseek",
    "openai",
    "openai_compatible",
})


def _resolve_temp_test_config(
    body: PiAgentTempTestConfig, config
) -> tuple[str, str | None, str, str, bool]:
    """合并临时测试配置与数据库配置。

    返回 (provider, api_key_or_None, api_base, llm_model, has_temp)。
    api_key 为 None 表示「请求未携带临时 Key，需回退数据库密文」。
    """
    temp_key = (body.api_key or "").strip()
    has_temp = any((
        temp_key,
        (body.llm_provider or "").strip(),
        (body.llm_api_base or "").strip(),
        (body.llm_model or "").strip(),
    ))
    provider = (body.llm_provider or "").strip() or config.llm_provider
    api_base = (body.llm_api_base or "").strip() or config.llm_api_base
    llm_model = (body.llm_model or "").strip() or config.llm_model
    return provider, (temp_key or None), api_base, llm_model, has_temp


@router.post("/config/test-connection")
async def test_pi_agent_connection(
    req: PiAgentTempTestConfig | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """测试 Pi Agent LLM API 连接。

    Only providers that use the OpenAI-compatible /chat/completions
    protocol are currently supported.  Other providers (e.g. Anthropic)
    return a clear unsupported status instead of a misleading error.

    可选请求体（Issue #2）：api_key / llm_provider / llm_api_base / llm_model
    为表单临时值，优先于数据库配置；仅本次请求生效，不落库、不写日志。
    """
    _require_admin(user)
    secret = _get_jwt_secret()
    repo = PiAgentConfigRepository(db)
    config = await repo.get_or_create()

    body = req or PiAgentTempTestConfig()
    provider, temp_key, api_base, llm_model, has_temp = _resolve_temp_test_config(body, config)

    if provider not in _OPENAI_COMPATIBLE_PROVIDERS:
        return {
            "status": "fail",
            "detail": f"当前连接测试不支持 provider='{provider}'，"
                      f"仅支持 OpenAI 兼容协议的 Provider",
        }

    if temp_key:
        api_key = temp_key
    elif config.llm_encrypted_api_key:
        try:
            api_key = decrypt_key(config.llm_encrypted_api_key, secret)
        except Exception:
            return {"status": "fail", "detail": "LLM API Key 解密失败"}
    else:
        return {"status": "fail", "detail": "未配置 LLM API Key"}

    test_result = await check_connection(api_base, api_key, llm_model)

    if has_temp:
        # 临时配置的测试结果不代表已保存配置：不更新库内测试状态，
        # 并显式告知前端「当前配置尚未保存」。commit 仅持久化
        # get_or_create 可能新建的默认配置行（不含任何临时值）。
        test_result["config_saved"] = False
        await db.commit()
        return test_result

    await repo.update_test_status(
        status=test_result["status"],
        test_time=now_cn(),
    )
    await db.commit()
    test_result["config_saved"] = True
    return test_result


@router.post("/config/speed-test")
async def test_pi_agent_speed(
    req: PiAgentTempTestConfig | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """测试 Pi Agent LLM API 响应速度。

    Only providers that use the OpenAI-compatible /chat/completions
    protocol are currently supported.

    可选请求体（Issue #2）与 test-connection 相同：表单临时值优先，
    仅本次请求生效，不落库、不写日志。
    """
    _require_admin(user)
    secret = _get_jwt_secret()
    repo = PiAgentConfigRepository(db)
    config = await repo.get_or_create()

    body = req or PiAgentTempTestConfig()
    provider, temp_key, api_base, llm_model, has_temp = _resolve_temp_test_config(body, config)

    if provider not in _OPENAI_COMPATIBLE_PROVIDERS:
        return {
            "status": "fail",
            "latency_ms": None,
            "detail": f"当前测速不支持 provider='{provider}'，"
                      f"仅支持 OpenAI 兼容协议的 Provider",
        }

    if temp_key:
        api_key = temp_key
    elif config.llm_encrypted_api_key:
        try:
            api_key = decrypt_key(config.llm_encrypted_api_key, secret)
        except Exception:
            return {"status": "fail", "detail": "LLM API Key 解密失败", "latency_ms": None}
    else:
        return {"status": "fail", "detail": "未配置 LLM API Key", "latency_ms": None}

    test_result = await speed_test(api_base, api_key, llm_model)

    if has_temp:
        test_result["config_saved"] = False
        # 同 test-connection：commit 仅落 get_or_create 的默认行，不落临时值
        await db.commit()
        return test_result

    await repo.update_test_status(
        status=test_result["status"],
        test_time=now_cn(),
        latency_ms=test_result.get("latency_ms"),
    )
    await db.commit()
    test_result["config_saved"] = True
    return test_result
