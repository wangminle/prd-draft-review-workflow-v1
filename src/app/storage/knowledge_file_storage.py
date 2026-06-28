"""KnowledgeFileStorage — 团队资料库上传文件保存、读取、删除。

职责边界：
- 文件名生成、目录创建、原始文件保存
- 文件正文读取和文本抽取（复用 file_text 服务）
- content_hash 计算
- 不负责权限判断、业务状态流转
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.runtime_paths import runtime_path
from app.services.file_text import extract_text_from_bytes


@dataclass
class StoredKnowledgeFile:
    file_id: str
    original_filename: str
    size: int
    content_hash: str
    extracted_text: str | None


class KnowledgeFileStorage:
    """团队资料库文件存储实现。"""

    def __init__(self, upload_dir: str | None = None):
        self._upload_dir = upload_dir

    def _resolve_upload_root(self) -> Path:
        if self._upload_dir:
            p = Path(self._upload_dir)
            if not p.is_absolute():
                return runtime_path(*p.parts)
            return p
        return runtime_path("data", "knowledge_sources")

    def save_upload(self, filename: str, content: bytes) -> StoredKnowledgeFile:
        root = self._resolve_upload_root()
        root.mkdir(parents=True, exist_ok=True)

        file_id = uuid.uuid4().hex[:12]
        ext = Path(filename).suffix.lower() if filename else ""
        stored_name = f"{file_id}{ext}" if ext else f"{file_id}"
        dest = root / stored_name
        dest.write_bytes(content)

        content_hash = hashlib.sha256(content).hexdigest()
        extracted_text = extract_text_from_bytes(content, filename)

        return StoredKnowledgeFile(
            file_id=file_id,
            original_filename=filename,
            size=len(content),
            content_hash=content_hash,
            extracted_text=extracted_text,
        )

    def read_file(self, file_id: str) -> bytes | None:
        root = self._resolve_upload_root()
        for candidate in root.iterdir():
            if candidate.name.startswith(file_id):
                return candidate.read_bytes()
        return None

    def delete_file(self, file_id: str) -> bool:
        root = self._resolve_upload_root()
        for candidate in root.iterdir():
            if candidate.name.startswith(file_id):
                candidate.unlink()
                return True
        return False