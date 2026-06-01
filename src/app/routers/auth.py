"""认证路由"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserInfo,
)
from app.logging_config import log_audit
from app.services.auth import create_access_token, hash_password, issue_sse_ticket, verify_password
from app.utils import now_cn

router = APIRouter()
security = HTTPBearer()
_settings = get_settings()


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """用户登录，返回 JWT token"""
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(req.password, user.password_hash):
        log_audit(
            "auth.login",
            request=request,
            result="failed",
            detail={"username": req.username, "reason": "invalid_credentials"},
            level="warning",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        log_audit(
            "auth.login",
            actor=user,
            request=request,
            result="failed",
            detail={"username": req.username, "reason": "inactive_user"},
            level="warning",
        )
        raise HTTPException(status_code=403, detail="用户已被禁用")

    user.last_active_at = now_cn()
    await db.commit()

    token = create_access_token(user.id, user.role)
    log_audit("auth.login", actor=user, request=request, detail={"username": user.username})
    return TokenResponse(access_token=token)


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """用户注册

    默认注册为普通用户。是否开放公开注册由配置控制。
    """
    auth_settings = _settings.get("auth", {})
    if not auth_settings.get("allow_public_registration", True):
        log_audit(
            "auth.register",
            request=request,
            result="failed",
            detail={"username": req.username, "reason": "public_registration_disabled"},
            level="warning",
        )
        raise HTTPException(status_code=403, detail="当前环境未开放公开注册")

    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none() is not None:
        log_audit(
            "auth.register",
            request=request,
            result="failed",
            detail={"username": req.username, "reason": "username_exists"},
            level="warning",
        )
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role="user",
        last_active_at=now_cn(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.role)
    log_audit("auth.register", actor=user, request=request, detail={"username": user.username, "role": user.role})
    return TokenResponse(access_token=token)


@router.post("/sse-ticket")
async def create_sse_ticket(user: User = Depends(get_current_user)):
    """为当前登录用户签发短时一次性 SSE 票据。"""
    return {"ticket": issue_sse_ticket(user.id)}


@router.get("/me", response_model=UserInfo)
async def get_me(user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserInfo(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )


@router.put("/password")
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改当前用户密码"""
    from fastapi import HTTPException, status

    if not verify_password(req.old_password, user.password_hash):
        log_audit(
            "auth.password_change",
            actor=user,
            request=request,
            result="failed",
            detail={"reason": "old_password_mismatch"},
            level="warning",
        )
        raise HTTPException(status_code=400, detail="原密码错误")

    user.password_hash = hash_password(req.new_password)
    await db.commit()
    log_audit("auth.password_change", actor=user, request=request)
    return {"message": "密码修改成功"}
