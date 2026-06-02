"""ChatFileStorage — 智能对话上传文件保存、读取、删除。

职责边界：
- 文件名生成、目录创建、原始文件保存
- 文件正文读取和文本抽取（复用 file_text 服务）
- 不负责权限判断、业务状态流转
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.runtime_paths import runtime_path
from app.services.file_text import extract_text_from_bytes, extract_text_from_path


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

    async def save_upload(self, *, filename: str, content: bytes) -> StoredChatFile:
        ext = Path(filename).suffix.lower()
        file_id = f"{uuid.uuid4().hex}{ext}"
        upload_dir = self._resolve_upload_dir()
        saved_path = os.path.join(upload_dir, file_id)
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
        upload_dir = self._resolve_upload_dir()
        file_path = os.path.join(upload_dir, file_id)
        if not os.path.isfile(file_path):
            return None
        return extract_text_from_path(file_path, file_id)

    def delete(self, file_id: str) -> None:
        upload_dir = self._resolve_upload_dir()
        file_path = os.path.join(upload_dir, file_id)
        if os.path.isfile(file_path):
            os.unlink(file_path)

    def file_exists(self, file_id: str) -> bool:
        upload_dir = self._resolve_upload_dir()
        file_path = os.path.join(upload_dir, file_id)
        return os.path.isfile(file_path)