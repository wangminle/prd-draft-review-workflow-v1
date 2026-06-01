"""统一解析工作区级 runtime 目录。"""

from __future__ import annotations

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]


def get_runtime_root() -> Path:
    configured = os.environ.get("RUNTIME_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (APP_ROOT / "runtime").resolve()


def runtime_path(*parts: str | os.PathLike[str]) -> Path:
    return get_runtime_root().joinpath(*parts)