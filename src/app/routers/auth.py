"""认证路由 — 使用 AuditLogWriter 记录审计日志"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserInfo,
)
from app.log_writers.audit_log_writer import AuditLogWriter
from app.services.auth import create_access_token, hash_password, issue_sse_ticket, verify_password

router = APIRouter()
security = HTTPBearer()
_settings = get_settings()
_audit_log_writer = AuditLogWriter()


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """用户登录，返回 JWT token"""
    repo = UserRepository(db)
    user = await repo.get_by_username(req.username)

    if user is None or not verify_password(req.password, user.password_hash):
        _audit_log_writer.write(
            "auth.login",
            request=request,
            result="failed",
            detail={"username": req.username, "reason": "invalid_credentials"},
            level="warning",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        _audit_log_writer.write(
            "auth.login",
            actor=user,
            request=request,
            result="failed",
            detail={"username": req.username, "reason": "inactive_user"},
            level="warning",
        )
        raise HTTPException(status_code=403, detail="用户已被禁用")

    await repo.update_last_active(user.id)
    await db.commit()

    token = create_access_token(user.id, user.role)
    _audit_log_writer.write("auth.login", actor=user, request=request, detail={"username": user.username})
    return TokenResponse(access_token=token)


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    auth_settings = _settings.get("auth", {})
    if not auth_settings.get("allow_public_registration", True):
        _audit_log_writer.write(
            "auth.register",
            request=request,
            result="failed",
            detail={"username": req.username, "reason": "public_registration_disabled"},
            level="warning",
        )
        raise HTTPException(status_code=403, detail="当前环境未开放公开注册")

    repo = UserRepository(db)
    existing = await repo.get_by_username(req.username)
    if existing is not None:
        _audit_log_writer.write(
            "auth.register",
            request=request,
            result="failed",
            detail={"username": req.username, "reason": "username_exists"},
            level="warning",
        )
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = await repo.create(
        username=req.username,
        password_hash=hash_password(req.password),
        role="user",
    )
    await db.commit()

    token = create_access_token(user.id, user.role)
    _audit_log_writer.write("auth.register", actor=user, request=request, detail={"username": user.username, "role": user.role})
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
    if not verify_password(req.old_password, user.password_hash):
        _audit_log_writer.write(
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
    _audit_log_writer.write("auth.password_change", actor=user, request=request)
    return {"message": "密码修改成功"}