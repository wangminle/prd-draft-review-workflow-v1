"""品牌与本地个性化配置服务。

优先级：
  runtime/config/ui-branding.yaml（yaml 中的非空值优先）
  → runtime/assets/branding/ 自动发现（填充 yaml 中为空的资产字段）
  → src/config.yaml ui_branding 段
  → 代码默认值

资产目录：runtime/assets/branding/，只允许该目录内文件名或安全相对路径。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from app.runtime_paths import get_runtime_root, runtime_path

logger = logging.getLogger(__name__)

# ── 代码侧默认品牌配置 ──

DEFAULT_BRANDING: dict = {
    "app_title": "AI产品需求初审",
    "app_version": "0.2.13",
    "login_title": "AI产品需求初审",
    "login_subtitle": "AI 驱动的需求审查工作流平台",
    "login_notice": "",
    "topbar_title": "AI产品需求初审",
    "review_workspace_label": "需求审查工作台",
    "admin_label": "管理后台",
    "theme": {
        "primary": "#005AAA",
        "primary_hover": "#2E7CC0",
        "accent": "#23C343",
    },
    "login_logo": "",
    "topbar_logo": "",
    "favicon": "",
}


_LEGACY_FIELD_ALIASES = {
    "login_notice_text": "login_notice",
}


def _normalize_branding_aliases(data: dict) -> dict:
    """兼容旧版 runtime/config/ui-branding.yaml 字段名。"""
    normalized = dict(data)
    for legacy_key, current_key in _LEGACY_FIELD_ALIASES.items():
        legacy_val = normalized.get(legacy_key)
        current_val = normalized.get(current_key)
        if not current_val and legacy_val and isinstance(legacy_val, str):
            normalized[current_key] = legacy_val
        normalized.pop(legacy_key, None)
    return normalized


def _validate_asset_path(path_str: str) -> str | None:
    """校验资产路径，只允许 runtime/assets/branding/ 下的文件名或安全相对路径。

    拒绝：绝对路径、.. 穿越、外部 URL。
    返回通过校验的路径（相对于 runtime/assets/branding/），或 None 表示非法。
    """
    if not path_str:
        return None

    # 拒绝 URL
    if path_str.startswith(("http://", "https://", "ftp://", "//")):
        logger.warning("branding asset path rejected: external URL not allowed (%s)", path_str)
        return None

    p = Path(path_str)

    # 拒绝绝对路径
    if p.is_absolute():
        logger.warning("branding asset path rejected: absolute path not allowed (%s)", path_str)
        return None

    # 拒绝 .. 穿越
    if ".." in p.parts:
        logger.warning("branding asset path rejected: path traversal not allowed (%s)", path_str)
        return None

    return path_str


def _load_runtime_branding() -> dict | None:
    """从 runtime/config/ui-branding.yaml 加载本地覆盖配置。"""
    yaml_path = runtime_path("config", "ui-branding.yaml")
    if not yaml_path.exists():
        return None
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning("ui-branding.yaml is not a dict, ignoring")
            return None
        return _normalize_branding_aliases(data)
    except Exception:
        logger.warning("failed to load ui-branding.yaml, using defaults")
        return None


def _load_config_yaml_branding() -> dict | None:
    """从 src/config.yaml 的 ui_branding 段加载配置。"""
    from app.config import get_settings
    settings = get_settings()
    branding = settings.get("ui_branding")
    if not isinstance(branding, dict):
        return None
    return _normalize_branding_aliases(branding)


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".svg", ".ico", ".gif", ".webp")


def _discover_branding_assets() -> dict | None:
    """从 runtime/assets/branding/ 自动发现品牌资产。

    当 runtime/config/ui-branding.yaml 不存在时，扫描 branding 目录下的文件名，
    按"favicon"/"logo"关键词推断 login_logo、topbar_logo、favicon 字段值。
    通用 logo 默认只用于登录页；只有显式的顶栏/图标命名资产才会填充 topbar_logo。
    返回推断的配置 dict（只含资产字段），或 None 表示无可发现资产。
    """
    branding_dir = runtime_path("assets", "branding")
    if not branding_dir.exists():
        return None

    discovered: dict = {}
    logo_candidates: list[str] = []
    favicon_candidate: str = ""

    for f in branding_dir.iterdir():
        if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in _IMAGE_EXTENSIONS:
            name_lower = f.name.lower()
            if "favicon" in name_lower:
                favicon_candidate = f.name
            elif "logo" in name_lower or "brand" in name_lower:
                logo_candidates.append(f.name)

    if favicon_candidate:
        validated = _validate_asset_path(favicon_candidate)
        if validated is not None:
            discovered["favicon"] = validated

    if logo_candidates:
        # 通用 logo 优先用于登录页；顶栏 logo 只接受显式 topbar/icon 命名。
        login_logo = ""
        topbar_logo = ""
        for name in logo_candidates:
            name_lower = name.lower()
            if any(keyword in name_lower for keyword in ("topbar", "header", "nav", "icon", "mark", "symbol")):
                if not topbar_logo:
                    v = _validate_asset_path(name)
                    if v is not None:
                        topbar_logo = v
            elif "login" in name_lower or "brand" in name_lower:
                if not login_logo:
                    v = _validate_asset_path(name)
                    if v is not None:
                        login_logo = v

        # 如果没有专门的 login_logo，用第一个通用候选作为登录页 logo。
        if not login_logo and logo_candidates:
            v = _validate_asset_path(logo_candidates[0])
            if v is not None:
                login_logo = v

        # 单文件兜底：若只有一个 logo 被识别，回退填充到另一处
        # （登录页与顶栏允许不同尺寸，但用户通常只放一张通用图）
        if login_logo and not topbar_logo:
            topbar_logo = login_logo
        elif topbar_logo and not login_logo:
            login_logo = topbar_logo

        if login_logo:
            discovered["login_logo"] = login_logo
        if topbar_logo:
            discovered["topbar_logo"] = topbar_logo

    return discovered if discovered else None


def _merge_branding(base: dict, override: dict) -> dict:
    """合并品牌配置，override 中非空、合法的值覆盖 base。"""
    result = dict(base)
    override = _normalize_branding_aliases(override)

    # 简单字符串字段直接覆盖
    for key in ("app_title", "app_version", "login_title", "login_subtitle", "login_notice",
                "topbar_title", "review_workspace_label", "admin_label"):
        val = override.get(key)
        if val and isinstance(val, str):
            result[key] = val

    # 资产路径字段需校验 — 非法值不覆盖已有合法值
    for key in ("login_logo", "topbar_logo", "favicon"):
        val = override.get(key)
        if val and isinstance(val, str):
            validated = _validate_asset_path(val)
            if validated is not None:
                result[key] = validated
            else:
                # 非法值不替换已有合法值，只记录警告
                logger.warning("branding config: invalid asset path ignored, keeping existing value (%s=%s)", key, val)

    # 主题色字段
    theme_override = override.get("theme")
    if isinstance(theme_override, dict):
        base_theme = result.get("theme", {})
        merged_theme = dict(base_theme)
        for tk in ("primary", "primary_hover", "accent"):
            tv = theme_override.get(tk)
            if tv and isinstance(tv, str):
                merged_theme[tk] = tv
        result["theme"] = merged_theme

    return result


def get_branding_config() -> dict:
    """获取合并后的品牌配置。

    优先级：runtime/config/ui-branding.yaml（非空值优先）
    → runtime/assets/branding/ 自动发现（填充 yaml 中为空的资产字段）
    → config.yaml ui_branding
    → DEFAULT_BRANDING
    """
    base = dict(DEFAULT_BRANDING)

    config_yaml = _load_config_yaml_branding()
    if config_yaml:
        base = _merge_branding(base, config_yaml)

    runtime = _load_runtime_branding()
    if runtime:
        base = _merge_branding(base, runtime)
    else:
        base = _merge_branding(base, {})  # 触发 normalize，但不覆盖

    # yaml 优先，但自动发现可填充 yaml 中为空的资产字段
    discovered = _discover_branding_assets()
    if discovered:
        for asset_key in ("login_logo", "topbar_logo", "favicon"):
            if not base.get(asset_key) and discovered.get(asset_key):
                base[asset_key] = discovered[asset_key]
        if not runtime:
            logger.info("branding: no ui-branding.yaml found, auto-discovered assets from runtime/assets/branding/")
        else:
            filled = [k for k in ("login_logo", "topbar_logo", "favicon")
                      if not runtime.get(k) and discovered.get(k)]
            if filled:
                logger.info("branding: auto-discovered assets filled empty yaml fields: %s", filled)

    return base


def resolve_branding_asset(relative_path: str) -> Path:
    """将校验通过的相对资产路径解析为 runtime/assets/branding/ 下的绝对路径。"""
    validated = _validate_asset_path(relative_path)
    if validated is None:
        return runtime_path("assets", "branding")  # fallback to dir itself
    return runtime_path("assets", "branding", validated)


def ensure_branding_dirs() -> None:
    """确保 runtime 配置目录和资产目录存在（不创建文件）。"""
    runtime_path("config").mkdir(parents=True, exist_ok=True)
    runtime_path("assets", "branding").mkdir(parents=True, exist_ok=True)
