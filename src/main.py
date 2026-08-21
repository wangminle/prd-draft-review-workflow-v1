"""FastAPI 应用入口"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 确保 src/ 在 sys.path 中，使 from app.xxx 导入正常
_src_dir = str(Path(__file__).parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from dotenv import load_dotenv

from app.env_file import ensure_canonical_env

# OPT-002: 只加载项目根目录 .env；src/.env 仅在根文件缺失时迁移一次
_project_root = Path(__file__).resolve().parent.parent
_canonical_env, _env_warnings = ensure_canonical_env(_project_root)
for _warning in _env_warnings:
    print(f"[WARN] {_warning}", file=sys.stderr)
if _canonical_env.exists():
    load_dotenv(_canonical_env)

# 初始化日志系统（在所有业务模块导入之前）
from app.logging_config import setup_logging
from app.runtime_paths import runtime_path

_logs_dir = setup_logging(runtime_path("logs"))

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import init_db
from app.middleware.auth import get_optional_user
from app.models.user import User
from app.routers import admin, agent, auth, chat, history, review, upload, workspace, pi_agent, review_request, notification, artifact, governance
from app.services.branding_config import (
    get_branding_config,
    ensure_branding_dirs,
    DEFAULT_BRANDING,
)
from app.version import APP_VERSION


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Prevent browser from caching API responses — ensures data isolation
    across different user sessions on the same browser."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # root_path 部署（子路径反代）时 url.path 带前缀，先剥离再判断
        path = request.url.path
        root_path = request.scope.get("root_path", "")
        if root_path and path.startswith(root_path):
            path = path[len(root_path):]
        if path.startswith("/api/"):
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
    # 启动 embedding 后台消费者
    from app.services.embedding_worker import start_embedding_worker, stop_embedding_worker
    await start_embedding_worker()
    try:
        yield
    finally:
        await stop_embedding_worker()
        from app.routers.review import stop_all_pipeline_tasks
        await stop_all_pipeline_tasks()
        from app.database import engine
        await engine.dispose()


# 应用版本号（唯一事实来源在 app.version；/api/health 与打包脚本均引用此处）

# 子路径反代部署时的挂载前缀（如 "/prd-review"），由 uvicorn --root-path 或 ROOT_PATH 环境变量指定
ROOT_PATH = os.environ.get("ROOT_PATH", "").rstrip("/")

app = FastAPI(
    title=DEFAULT_BRANDING["app_title"],
    description="局域网 AI 对话服务",
    version=APP_VERSION,
    lifespan=lifespan,
    root_path=ROOT_PATH,
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
    return {"status": "ok", "version": APP_VERSION}


@app.get("/api/app/branding")
async def get_branding():
    """返回合并后的品牌配置供前端使用。"""
    config = get_branding_config()
    result = dict(config)
    # 将资产文件名转换为可访问 URL（相对路径，子路径前缀部署下由浏览器相对页面解析）
    for key in ("login_logo", "topbar_logo", "favicon"):
        val = result.get(key)
        if val:
            result[key] = f"assets/branding/{val}"
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


def _render_index(root_path: str) -> str:
    """读取 index.html 并在 </head> 前注入部署前缀 window.__BASE_PATH__。

    前端 api.js 的 _base 优先读取该全局变量，确保子路径反代部署
    （如 https://host/prd-review/）下，所有 /api、/assets 请求都带正确前缀。
    root_path 为空（根路径部署）时仍注入空串，使前端行为显式且可缓存。
    """
    index_path = static_dir / "index.html"
    html = index_path.read_text(encoding="utf-8")
    # 规范化：去首尾斜杠，避免出现 // 或尾部斜杠导致前端拼接异常
    normalized = (root_path or "").strip().strip("/")
    inject = f"<script>window.__BASE_PATH__='/{normalized}';</script>" if normalized else "<script>window.__BASE_PATH__='';</script>"
    return html.replace("</head>", f"{inject}</head>", 1)


@app.get("/")
async def serve_index():
    """根入口：返回注入了 __BASE_PATH__ 的 index.html。

    显式路由注册在 app.mount("/", StaticFiles(...)) 之前，命中优先于静态挂载，
    从而获得字符串注入机会（StaticFiles(html=True) 直接返回原文件无法注入）。
    加 no-store 防止浏览器缓存住旧前缀的页面。
    """
    if not static_dir.exists() or not (static_dir / "index.html").exists():
        return Response(status_code=404)
    return HTMLResponse(_render_index(ROOT_PATH), headers={"Cache-Control": "no-store"})


if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
