"""项目根目录 .env 为唯一环境文件（OPT-002）。"""

from __future__ import annotations

import re
from pathlib import Path

_JWT_ASSIGN_RE = re.compile(r"^JWT_SECRET=.*$", re.MULTILINE)


def canonical_env_path(project_dir: Path) -> Path:
    return Path(project_dir) / ".env"


def legacy_src_env_path(project_dir: Path) -> Path:
    return Path(project_dir) / "src" / ".env"


def persist_jwt_secret(env_path: Path, secret: str) -> None:
    """把 JWT_SECRET 写入根目录 .env：已有赋值则替换，注释行不动。"""
    path = Path(env_path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"JWT_SECRET={secret}"
    if _JWT_ASSIGN_RE.search(text):
        text = _JWT_ASSIGN_RE.sub(lambda _m: line, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")


def ensure_canonical_env(project_dir: Path) -> tuple[Path, list[str]]:
    """确保只使用项目根目录 .env。

    - 根目录已有 .env：忽略 src/.env（若存在则警告）
    - 根目录没有、src/.env 有：复制到根目录并警告迁移
    """
    root = canonical_env_path(project_dir)
    src_env = legacy_src_env_path(project_dir)
    warnings: list[str] = []

    if root.exists():
        if src_env.exists():
            warnings.append(
                f"Ignoring {src_env}；canonical env is {root}. "
                "Merge extra keys into the root .env and delete src/.env."
            )
        return root, warnings

    if src_env.exists():
        root.write_text(src_env.read_text(encoding="utf-8"), encoding="utf-8")
        warnings.append(
            f"Legacy {src_env} copied to {root}. "
            "Use the project-root .env going forward and delete src/.env."
        )
    return root, warnings
