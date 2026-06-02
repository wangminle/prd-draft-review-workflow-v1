"""ReviewFileStorage — 需求审查文件存储实现。

职责边界：
- 承接 runtime/data/review_uploads/ 与 runtime/data/converted/ 的全部路径语义
- 历史路径兼容读取逻辑只保留在这里
- .source_hash、目录清理、转换缓存命中都归口到这里
- 不负责权限判断、业务状态流转
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.runtime_paths import runtime_path

logger = logging.getLogger(__name__)


@dataclass
class StoredReviewFile:
    file_id: str
    original_filename: str
    stored_path: str
    runtime_relative_path: str


@dataclass
class ConvertedDocument:
    md_path: str
    runtime_relative_md_path: str | None


class ReviewFileStorage:
    """需求审查原始 DOCX、转换产物、缓存文件、路径兼容、文件清理。

    When upload_dir is None, resolve from config on each call,
    allowing tests to inject custom upload directories.
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

    def _resolve_upload_root(self) -> str:
        if self._upload_dir is not None:
            return self._upload_dir
        from app.config import get_settings
        cfg_dir = get_settings().get("review", {}).get("upload", {}).get("upload_dir")
        if cfg_dir:
            p = Path(cfg_dir)
            if not p.is_absolute():
                return str(runtime_path(*p.parts))
            return cfg_dir
        return str(runtime_path("data", "review_uploads"))

    def _resolve_stored_file_path(self, stored_path: str | os.PathLike[str] | None) -> str | None:
        if not stored_path:
            return None

        path = Path(str(stored_path))
        if path.is_absolute():
            return str(path)

        parts = list(path.parts)
        while parts and parts[0] == ".":
            parts.pop(0)

        if "runtime" in parts:
            runtime_index = parts.index("runtime")
            return str(runtime_path(*parts[runtime_index + 1:]))

        if parts[:1] == ["data"]:
            return str(runtime_path(*parts))

        return str(path)

    def to_runtime_relative_path(self, file_path: str | os.PathLike[str] | None) -> str | None:
        if not file_path:
            return None

        path = Path(str(file_path))
        if not path.is_absolute():
            resolved = self._resolve_stored_file_path(str(path))
            path = Path(resolved) if resolved else path

        try:
            return path.resolve().relative_to(runtime_path().resolve()).as_posix()
        except ValueError:
            return str(file_path)

    async def save_uploaded_docx(
        self, *, project_id: int, document_type: str, filename: str, content: bytes
    ) -> StoredReviewFile:
        upload_root = self._resolve_upload_root()
        upload_dir = os.path.join(upload_root, str(project_id), document_type)
        saved_name = f"{uuid.uuid4().hex}.docx"
        saved_path = os.path.join(upload_dir, saved_name)
        os.makedirs(upload_dir, exist_ok=True)
        with open(saved_path, "wb") as out_f:
            out_f.write(content)

        rel_path = self.to_runtime_relative_path(saved_path)
        return StoredReviewFile(
            file_id=saved_name,
            original_filename=filename,
            stored_path=saved_path,
            runtime_relative_path=rel_path or saved_path,
        )

    async def read_markdown(self, md_path: str) -> str:
        resolved_md_path = self._resolve_stored_file_path(md_path)
        if not resolved_md_path or not os.path.exists(resolved_md_path):
            raise FileNotFoundError(f"md not found: {md_path}")
        with open(resolved_md_path, "r", encoding="utf-8") as f:
            return f.read()

    async def convert_docx(
        self, *, file_path: str, document_id: int,
        original_filename: str | None = None, force: bool = False,
        skills_dir: str | None = None,
    ) -> ConvertedDocument:
        file_path = self._resolve_stored_file_path(file_path)
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"docx not found: {file_path}")

        output_dir = str(runtime_path("data", "converted", f"doc_{document_id}"))

        if not force:
            existing_md = list(Path(output_dir).rglob("*.md"))
            if existing_md:
                source_hash = self.compute_file_hash(file_path)
                hash_file = os.path.join(output_dir, ".source_hash")
                cache_valid = False
                if os.path.exists(hash_file):
                    with open(hash_file, "r") as f:
                        stored_hash = f.read().strip()
                    if stored_hash == source_hash:
                        cache_valid = True

                if cache_valid:
                    md_path_candidate = self._pick_best_md(existing_md, original_filename)
                    logger.info("Skipping docx conversion for doc_%d (cached, hash matches)", document_id)
                    rel = self.to_runtime_relative_path(md_path_candidate)
                    return ConvertedDocument(md_path=md_path_candidate, runtime_relative_md_path=rel)

        os.makedirs(output_dir, exist_ok=True)
        source_hash = self.compute_file_hash(file_path)
        hash_file = os.path.join(output_dir, ".source_hash")

        resolved_skills = skills_dir or ""
        md_path = ""

        skill_script_dir = os.path.join(resolved_skills, "docx-to-markdown", "scripts")
        if resolved_skills and os.path.isdir(skill_script_dir):
            try:
                if skill_script_dir not in sys.path:
                    sys.path.insert(0, skill_script_dir)
                from convert_docx import convert_docx_to_markdown
                kwargs = {}
                if original_filename:
                    kwargs["output_name"] = original_filename
                result = await asyncio.to_thread(convert_docx_to_markdown, file_path, output_dir, **kwargs)
                if isinstance(result, dict):
                    md_path = result.get("output_path") or result.get("md_path") or result.get("path") or ""
                elif isinstance(result, (str, os.PathLike)):
                    md_path = str(result)
            except Exception as e:
                logger.warning("Skill docx-to-markdown failed, falling back to mammoth: %s", e)

        if not md_path:
            try:
                import mammoth
                with open(file_path, "rb") as f:
                    result = await asyncio.to_thread(mammoth.convert_to_markdown, f)
                md_content = result.value
                stem = os.path.splitext(original_filename)[0] if original_filename else "output"
                safe_stem = "".join(c if c.isalnum() or c in "._- " else "_" for c in stem).strip(". ")
                out_file = os.path.join(output_dir, f"{safe_stem}.md")
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(md_content)
                md_path = out_file
            except ImportError:
                logger.error("mammoth not installed, cannot convert docx")
                raise

        if not md_path:
            md_files = list(Path(output_dir).rglob("*.md"))
            md_path = str(md_files[0]) if md_files else ""

        self._write_source_hash(hash_file, source_hash)

        rel = self.to_runtime_relative_path(md_path)
        return ConvertedDocument(md_path=md_path, runtime_relative_md_path=rel)

    def _write_source_hash(self, hash_file: str, source_hash: str) -> bool:
        try:
            with open(hash_file, "w") as f:
                f.write(source_hash)
            return True
        except OSError as e:
            logger.warning("Failed to write source hash cache %s: %s", hash_file, e)
            return False

    def compute_file_hash(self, file_path: str) -> str:
        resolved_path = self._resolve_stored_file_path(file_path)
        if not resolved_path:
            raise FileNotFoundError(f"file not found: {file_path}")
        h = hashlib.sha256()
        with open(resolved_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    async def delete_project_files(self, project_id: int) -> None:
        upload_dir = os.path.join(self._resolve_upload_root(), str(project_id))
        if os.path.isdir(upload_dir):
            shutil.rmtree(upload_dir)

    async def delete_document_files(self, document_id: int, *, file_path: str | None = None, md_path: str | None = None) -> None:
        for stored_path in (file_path, md_path):
            resolved = self._resolve_stored_file_path(stored_path)
            if resolved and os.path.exists(resolved):
                try:
                    os.remove(resolved)
                except OSError:
                    pass
        converted_dir = str(runtime_path("data", "converted", f"doc_{document_id}"))
        if os.path.isdir(converted_dir):
            shutil.rmtree(converted_dir)

    def _pick_best_md(self, md_files: list[Path], original_filename: str | None = None) -> str:
        if len(md_files) == 1:
            return str(md_files[0])

        if original_filename:
            target_stem = os.path.splitext(original_filename)[0]
            for md in md_files:
                if md.parent.name == target_stem or md.stem == target_stem:
                    return str(md)
            safe_stem = "".join(c if c.isalnum() or c in "._- " else "_" for c in target_stem).strip(". ")
            for md in md_files:
                if md.stem == safe_stem or md.parent.name == safe_stem:
                    return str(md)

        best = max(md_files, key=lambda p: p.stat().st_size)
        return str(best)