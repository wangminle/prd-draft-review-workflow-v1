"""FastAPI 应用入口"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 确保 src/ 在 sys.path 中，使 from app.xxx 导入正常
_src_dir = str(Path(__file__).parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from dotenv import load_dotenv

# 加载 .env 文件（优先 src/.env，其次项目根目录）
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

# 初始化日志系统（在所有业务模块导入之前）
from app.logging_config import setup_logging
from app.runtime_paths import runtime_path

_logs_dir = setup_logging(runtime_path("logs"))

from fastapi import Depends, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import init_db
from app.middleware.auth import get_optional_user
from app.models.user import User
from app.routers import admin, auth, chat, history, review, upload


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Prevent browser from caching API responses — ensures data isolation
    across different user sessions on the same browser."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动：初始化数据库
    await init_db()
    yield
    # 关闭：清理资源（如需要）


app = FastAPI(
    title="AI产品需求初审",
    description="局域网 AI 对话服务",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(NoCacheMiddleware)

# 注册 API 路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(chat.router, prefix="/api/chat", tags=["对话"])
app.include_router(upload.router, prefix="/api/upload", tags=["上传"])
app.include_router(history.router, prefix="/api/history", tags=["历史记录"])
app.include_router(admin.router, prefix="/api/admin", tags=["管理"])
app.include_router(review.router, prefix="/api/review", tags=["需求审查"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/log")
async def frontend_log(
    body: dict,
    request: Request,
    user: User | None = Depends(get_optional_user),
):
    """前端日志接口 — 记录浏览器端日志到 runtime/logs/frontend.jsonl"""
    from app.logging_config import log_audit, log_frontend
    level = body.get("level", "info")
    message = body.get("message", "")
    page = body.get("page")
    detail = body.get("detail")
    action = body.get("action") or message or "frontend.event"
    log_frontend(level, message, page, detail)
    log_audit(
        action,
        actor=user,
        request=request,
        target_type="frontend",
        target_id=page,
        result="success" if level != "error" else "failed",
        detail={"page": page, "message": message, "detail": detail},
        level=level,
    )
    return {"status": "ok"}


static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
