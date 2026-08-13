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
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.runtime_paths import runtime_path

logger = logging.getLogger(__name__)
DEFAULT_DOCX_CONVERSION_TIMEOUT_SECONDS = 60.0


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

    def _docx_conversion_timeout_seconds(self) -> float:
        from app.config import get_settings

        review_cfg = get_settings().get("review", {})
        raw_timeout = (
            review_cfg.get("docx_conversion_timeout_seconds")
            or review_cfg.get("docx", {}).get("timeout_seconds")
        )
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = DEFAULT_DOCX_CONVERSION_TIMEOUT_SECONDS
        return timeout if timeout > 0 else DEFAULT_DOCX_CONVERSION_TIMEOUT_SECONDS

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

    def _build_conversion_worker_command(
        self, *, file_path: str, output_dir: str,
        original_filename: str | None, skills_dir: str,
    ) -> list[str]:
        worker_path = Path(__file__).with_name("docx_conversion_worker.py")
        command = [
            sys.executable,
            str(worker_path),
            "--file-path", file_path,
            "--output-dir", output_dir,
            "--skills-dir", skills_dir,
        ]
        if original_filename:
            command.extend(["--original-filename", original_filename])
        return command

    async def _terminate_conversion_worker(self, process: asyncio.subprocess.Process) -> None:
        """终止转换进程及其进程组，并等待操作系统完成回收。"""
        if process.returncode is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
            return
        except asyncio.TimeoutError:
            pass
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            return
        await process.wait()

    async def _run_conversion_worker(
        self, command: list[str], *, timeout: float, document_id: int
    ) -> dict:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
        communicate_task = asyncio.create_task(process.communicate())
        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.shield(communicate_task), timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            await self._terminate_conversion_worker(process)
            await communicate_task
            raise TimeoutError(
                f"DOCX 转换超时（>{timeout:.0f}s），工作进程已终止"
            ) from exc
        except asyncio.CancelledError:
            await self._terminate_conversion_worker(process)
            await communicate_task
            raise

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        try:
            payload = json.loads(stdout_text.splitlines()[-1]) if stdout_text else {}
        except (json.JSONDecodeError, IndexError) as exc:
            raise RuntimeError(
                f"DOCX 转换工作进程返回无效结果（doc_{document_id}）：{stderr_text or stdout_text}"
            ) from exc

        if process.returncode != 0 or payload.get("status") != "ok":
            error_type = payload.get("error_type", "RuntimeError")
            error_message = payload.get("error") or stderr_text or "未知错误"
            if error_type == "DocxSecurityError":
                raise ValueError(f"DOCX 安全拒绝：{error_message}")
            raise RuntimeError(f"DOCX 转换失败（{error_type}）：{error_message}")
        return payload

    def _publish_converted_directory(self, staging_dir: str, output_dir: str) -> None:
        """将完整临时产物作为一个目录发布，失败时恢复旧目录。"""
        backup_dir = f"{output_dir}.backup-{uuid.uuid4().hex}"
        had_existing = os.path.exists(output_dir)
        if had_existing:
            os.replace(output_dir, backup_dir)
        try:
            os.replace(staging_dir, output_dir)
        except Exception:
            if had_existing and os.path.exists(backup_dir):
                os.replace(backup_dir, output_dir)
            raise
        if had_existing and os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)

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

        source_hash = self.compute_file_hash(file_path)
        resolved_skills = skills_dir or ""
        conversion_timeout = self._docx_conversion_timeout_seconds()
        output_parent = os.path.dirname(output_dir)
        os.makedirs(output_parent, exist_ok=True)
        staging_dir = tempfile.mkdtemp(prefix=f".doc_{document_id}-", dir=output_parent)
        try:
            command = self._build_conversion_worker_command(
                file_path=file_path,
                output_dir=staging_dir,
                original_filename=original_filename,
                skills_dir=resolved_skills,
            )
            payload = await self._run_conversion_worker(
                command, timeout=conversion_timeout, document_id=document_id
            )
            worker_md_path = Path(str(payload["md_path"]))
            relative_md_path = worker_md_path.resolve().relative_to(Path(staging_dir).resolve())
            self._publish_converted_directory(staging_dir, output_dir)
            staging_dir = ""
        finally:
            if staging_dir and os.path.isdir(staging_dir):
                shutil.rmtree(staging_dir)

        md_path = str(Path(output_dir) / relative_md_path)
        hash_file = os.path.join(output_dir, ".source_hash")
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
        if document_id > 0:
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
