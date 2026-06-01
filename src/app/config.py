"""配置加载模块：读取 config.yaml + 环境变量，解析 ${VAR} 占位符"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from app.runtime_paths import get_runtime_root

_env_var_pattern = re.compile(r"\$\{(\w+)\}")


def _resolve_env(value: Any) -> Any:
    """递归解析配置中的 ${ENV_VAR} 占位符"""
    if isinstance(value, str):
        def _replacer(match: re.Match) -> str:
            env_val = os.environ.get(match.group(1), "")
            if not env_val and match.group(1) == "JWT_SECRET":
                import secrets as _secrets
                env_val = _secrets.token_hex(32)
                os.environ["JWT_SECRET"] = env_val
            return env_val
        return _env_var_pattern.sub(_replacer, value)
    elif isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env(item) for item in value]
    return value


def _resolve_runtime_ref(path_value: Any) -> Any:
    if not isinstance(path_value, str):
        return path_value

    candidate = Path(path_value)
    if candidate.is_absolute():
        return str(candidate)

    parts = list(candidate.parts)
    while parts and parts[0] == ".":
        parts.pop(0)

    if parts[:1] == ["runtime"]:
        return str(get_runtime_root().joinpath(*parts[1:]))
    if parts[:2] == ["..", "runtime"]:
        return str(get_runtime_root().joinpath(*parts[2:]))
    return path_value


def _normalize_runtime_paths(config: dict) -> dict:
    database = config.get("database")
    if isinstance(database, dict) and "path" in database:
        database["path"] = _resolve_runtime_ref(database.get("path"))

    upload = config.get("upload")
    if isinstance(upload, dict) and "upload_dir" in upload:
        upload["upload_dir"] = _resolve_runtime_ref(upload.get("upload_dir"))

    review = config.get("review")
    if isinstance(review, dict):
        review_upload = review.get("upload")
        if isinstance(review_upload, dict) and "upload_dir" in review_upload:
            review_upload["upload_dir"] = _resolve_runtime_ref(review_upload.get("upload_dir"))

    return config


def load_config(config_path: str | Path | None = None) -> dict:
    """加载配置文件并解析环境变量占位符

    Args:
        config_path: 配置文件路径，默认取项目根目录下的 config.yaml
    """
    # Ensure .env is loaded before resolving env vars
    from dotenv import load_dotenv
    for p in [Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"]:
        if p.exists():
            load_dotenv(p, override=False)
            break

    if config_path is None:
        # 尝试多个可能的路径
        candidates = [
            Path(__file__).parent.parent / "config.yaml",  # src/config.yaml
            Path("config.yaml"),                           # 工作目录
            Path(__file__).parent.parent.parent / "config.yaml",  # 项目根目录
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break
        if config_path is None:
            raise FileNotFoundError("未找到 config.yaml 配置文件")

    config_path = Path(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return _normalize_runtime_paths(_resolve_env(config))


# 单例配置
_settings: dict | None = None


def get_settings() -> dict:
    global _settings
    if _settings is None:
        # 优先从环境变量 CONFIG_PATH 读取
        env_path = os.environ.get("CONFIG_PATH")
        _settings = load_config(env_path)
    return _settings
