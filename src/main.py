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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import init_db
from app.middleware.auth import get_optional_user
from app.models.user import User
from app.routers import admin, agent, auth, chat, history, review, upload, workspace, pi_agent, review_request, notification, artifact, governance
from app.services.branding_config import (
    get_branding_config,
    resolve_branding_asset,
    ensure_branding_dirs,
    DEFAULT_BRANDING,
)


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
    ensure_branding_dirs()
    await init_db()
    # 注册 Agent 内置工具 (P3.C.1)
    from app.services.tool_registry import register_builtin_tools
    register_builtin_tools()
    yield


app = FastAPI(
    title=DEFAULT_BRANDING["app_title"],
    description="局域网 AI 对话服务",
    version="0.3.4",
    lifespan=lifespan,
)

app.add_middleware(NoCacheMiddleware)

# 注册 API 路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(chat.router, prefix="/api/chat", tags=["对话"])
app.include_router(upload.router, prefix="/api/upload", tags=["上传"])
app.include_router(history.router, prefix="/api/history", tags=["历史记录"])
app.include_router(admin.router, prefix="/api/admin", tags=["管理"])
app.include_router(pi_agent.router, prefix="/api/pi-agent", tags=["Pi Agent"])
app.include_router(review.router, prefix="/api/review", tags=["需求审查"])
app.include_router(workspace.router, prefix="/api", tags=["团队空间"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(review_request.router, prefix="/api/review", tags=["协作审查"])
app.include_router(notification.router, prefix="/api/notifications", tags=["通知与评论"])
app.include_router(artifact.router, prefix="/api/review", tags=["知识快照与产物"])
app.include_router(governance.router, prefix="/api", tags=["治理与运营"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "0.3.4"}


@app.get("/api/app/branding")
async def get_branding():
    """返回合并后的品牌配置供前端使用。"""
    config = get_branding_config()
    result = dict(config)
    # 将资产文件名转换为可访问 URL
    for key in ("login_logo", "topbar_logo", "favicon"):
        val = result.get(key)
        if val:
            result[key] = f"/assets/branding/{val}"
        else:
            result[key] = ""
    return result


@app.get("/assets/branding/{path:path}")
async def serve_branding_asset(path: str):
    """只服务 runtime/assets/branding/ 下的静态资产文件。

    拒绝穿越、绝对路径等非法请求。
    """
    if not path or path.startswith(".") or ".." in path.split("/"):
        return Response(status_code=404)

    asset_dir = runtime_path("assets", "branding")
    file_path = asset_dir / path

    # 安全检查：确保文件在 branding 目录内
    try:
        file_path.resolve().relative_to(asset_dir.resolve())
    except ValueError:
        return Response(status_code=404)

    if not file_path.exists() or not file_path.is_file():
        return Response(status_code=404)

    return FileResponse(str(file_path))


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
