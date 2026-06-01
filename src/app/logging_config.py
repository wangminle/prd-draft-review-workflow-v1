"""日志配置模块 — 统一管理应用日志、LLM session日志、前端日志"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.runtime_paths import runtime_path
from app.utils import now_cn

_LOGS_DIR = None
_SECRET_KEYWORDS = ("password", "token", "api_key", "apikey", "secret", "authorization")


def _stream_points_to_path(stream, path: str | Path) -> bool:
    """Return True when a stream is already redirected to the target file."""
    try:
        stream_stat = os.fstat(stream.fileno())
        path_stat = Path(path).stat()
    except (OSError, ValueError, AttributeError):
        return False
    return stream_stat.st_dev == path_stat.st_dev and stream_stat.st_ino == path_stat.st_ino


def setup_logging(logs_dir: str | Path | None = None) -> Path:
    """初始化日志系统，所有日志写入工作区根目录 runtime/logs/

    Args:
        logs_dir: 日志目录路径，默认为工作区根目录/runtime/logs/
    """
    global _LOGS_DIR

    if logs_dir is None:
        logs_dir = runtime_path("logs")

    _LOGS_DIR = Path(logs_dir)
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # 应用日志 — 写入 app.log
    app_log_file = _LOGS_DIR / "app.log"

    # 配置根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 清除已有 handlers（避免重复）
    root_logger.handlers.clear()

    # File handler
    file_handler = logging.FileHandler(str(app_log_file), encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(file_handler)

    if not _stream_points_to_path(sys.stderr, app_log_file):
        # Console handler
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root_logger.addHandler(console)

    logging.info("日志系统初始化完成，日志目录: %s", _LOGS_DIR)
    return _LOGS_DIR


def get_logs_dir() -> Path:
    """获取日志目录路径"""
    if _LOGS_DIR is None:
        setup_logging()
    return _LOGS_DIR


def _redact(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if any(word in str(key).lower() for word in _SECRET_KEYWORDS):
                redacted[key] = "***"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _actor_to_dict(actor) -> dict | None:
    if actor is None:
        return None
    if isinstance(actor, dict):
        return _redact(actor)
    return {
        "user_id": getattr(actor, "id", None),
        "username": getattr(actor, "username", None),
        "role": getattr(actor, "role", None),
    }


def _request_to_dict(request) -> dict | None:
    if request is None:
        return None
    client = getattr(request, "client", None)
    headers = getattr(request, "headers", {}) or {}
    url = getattr(request, "url", None)
    return {
        "method": getattr(request, "method", None),
        "path": getattr(url, "path", None),
        "client_ip": getattr(client, "host", None),
        "user_agent": headers.get("user-agent"),
    }


def log_audit(
    action: str,
    *,
    actor=None,
    request=None,
    target_type: str | None = None,
    target_id: int | str | None = None,
    result: str = "success",
    detail: dict | None = None,
    level: str = "info",
) -> None:
    """记录结构化业务审计日志到 audit.jsonl。"""
    log_dir = get_logs_dir()
    entry = {
        "timestamp": now_cn().isoformat(),
        "level": level,
        "action": action,
        "result": result,
        "actor": _actor_to_dict(actor),
        "request": _request_to_dict(request),
        "target": {"type": target_type, "id": target_id} if target_type or target_id is not None else None,
        "detail": _redact(detail or {}),
    }
    with open(log_dir / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_llm_session(
    model: str,
    messages: list[dict],
    response: str | dict,
    usage: dict | None = None,
    elapsed_ms: int | None = None,
    error: str | None = None,
) -> None:
    """记录一次 LLM API 调用session到 llm_sessions.jsonl"""
    log_dir = get_logs_dir()
    entry = {
        "timestamp": now_cn().isoformat(),
        "model": model,
        "input_messages": messages,
        "response": response if isinstance(response, str) else json.dumps(response, ensure_ascii=False),
        "usage": usage,
        "elapsed_ms": elapsed_ms,
        "error": error,
    }
    with open(log_dir / "llm_sessions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_frontend(
    level: str,
    message: str,
    page: str | None = None,
    detail: dict | None = None,
) -> None:
    """记录前端日志到 frontend.jsonl"""
    log_dir = get_logs_dir()
    entry = {
        "timestamp": now_cn().isoformat(),
        "level": level,
        "page": page,
        "message": message,
        "detail": detail,
    }
    with open(log_dir / "frontend.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
