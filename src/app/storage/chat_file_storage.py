"""ChatFileStorage — 智能对话上传文件保存、读取、删除。

职责边界：
- 文件名生成、目录创建、原始文件保存
- 文件正文读取和文本抽取（复用 file_text 服务）
- 不负责权限判断、业务状态流转
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.runtime_paths import runtime_path
from app.services.file_text import extract_text_from_bytes, extract_text_from_path

# 仅允许安全 basename（生产为 UUID hex+后缀）；拒绝路径分隔与穿越
_SAFE_FILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


@dataclass
class StoredChatFile:
    file_id: str
    original_filename: str
    size: int
    extracted_text: str | None


class ChatFileStorage:
    """智能对话上传文件存储实现。

    When upload_dir is None, resolve from config on each call via
    _settings_resolver, allowing tests to inject custom settings.
    """

    def __init__(self, upload_dir: str | None = None):
        self._upload_dir = self._resolve_config_dir(upload_dir)

    def _resolve_config_dir(self, upload_dir: str | None) -> str | None:
        if upload_dir:
            p = Path(upload_dir)
            if not p.is_absolute():
                return str(runtime_path(*p.parts))
            return upload_dir
        return None

    def _resolve_upload_dir(self) -> str:
        if self._upload_dir is not None:
            return self._upload_dir
        from app.config import get_settings
        cfg_dir = get_settings().get("upload", {}).get("upload_dir")
        if cfg_dir:
            p = Path(cfg_dir)
            if not p.is_absolute():
                return str(runtime_path(*p.parts))
            return cfg_dir
        return str(runtime_path("uploads"))

    def _resolve_safe_path(self, file_id: str) -> str | None:
        """将 file_id 解析为上传根目录内的绝对路径；非法或越界返回 None。"""
        if not file_id or not isinstance(file_id, str):
            return None
        # 拒绝任何路径成分（含 ..、/、\\）
        if "/" in file_id or "\\" in file_id or file_id in (".", ".."):
            return None
        if Path(file_id).name != file_id:
            return None
        if not _SAFE_FILE_ID_RE.match(file_id):
            return None

        upload_dir = Path(self._resolve_upload_dir()).resolve()
        candidate = (upload_dir / file_id).resolve()
        try:
            candidate.relative_to(upload_dir)
        except ValueError:
            return None
        return str(candidate)

    async def save_upload(self, *, filename: str, content: bytes) -> StoredChatFile:
        ext = Path(filename).suffix.lower()
        if ext and not re.match(r"^\.[A-Za-z0-9]{1,16}$", ext):
            ext = ""
        file_id = f"{uuid.uuid4().hex}{ext}"
        upload_dir = self._resolve_upload_dir()
        saved_path = self._resolve_safe_path(file_id)
        if saved_path is None:
            raise ValueError("invalid generated file_id")
        os.makedirs(upload_dir, exist_ok=True)
        with open(saved_path, "wb") as f:
            f.write(content)

        extracted_text = extract_text_from_bytes(content, filename)
        return StoredChatFile(
            file_id=file_id,
            original_filename=filename,
            size=len(content),
            extracted_text=extracted_text,
        )

    def read_text(self, file_id: str) -> str | None:
        file_path = self._resolve_safe_path(file_id)
        if not file_path or not os.path.isfile(file_path):
            return None
        return extract_text_from_path(file_path, file_id)

    def delete(self, file_id: str) -> None:
        file_path = self._resolve_safe_path(file_id)
        if file_path and os.path.isfile(file_path):
            os.unlink(file_path)

    def file_exists(self, file_id: str) -> bool:
        file_path = self._resolve_safe_path(file_id)
        return bool(file_path and os.path.isfile(file_path))
