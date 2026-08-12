"""DOCX 不可信资源隔离的真实行为回归测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from docx import Document
from PIL import Image

from app.storage.review_file_storage import ReviewFileStorage


ROOT = Path(__file__).resolve().parent.parent
CONVERT_SCRIPT = ROOT / "skills" / "docx-to-markdown" / "scripts" / "convert_docx.py"


def _load_convert_module():
    spec = importlib.util.spec_from_file_location("convert_docx_resource_test", CONVERT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_mammoth_callback_never_rewrites_oversized_image(tmp_path):
    """ZIP 提取阶段跳过的超限图片不能从 Mammoth 回调重新落盘。"""
    convert_docx = _load_convert_module()
    image_path = tmp_path / "oversized.png"
    Image.new("RGB", (1, 1), "white").save(image_path)
    with image_path.open("ab") as image_file:
        image_file.write(os.urandom(convert_docx.MAX_SINGLE_IMAGE_SIZE + 1024))

    document = Document()
    document.add_picture(str(image_path))
    docx_path = tmp_path / "oversized-image.docx"
    document.save(docx_path)

    md_path = Path(
        convert_docx.convert_docx_to_markdown(str(docx_path), str(tmp_path / "output"))
    )
    assets = [path for path in (md_path.parent / "assets").iterdir() if path.is_file()]

    assert all(path.stat().st_size <= convert_docx.MAX_SINGLE_IMAGE_SIZE for path in assets)


@pytest.mark.asyncio
async def test_conversion_timeout_terminates_worker_without_delayed_write(tmp_path, monkeypatch):
    """超时必须终止工作进程，不能在返回后继续写入转换目录。"""
    marker_path = tmp_path / "late-write.txt"
    source_path = tmp_path / "source.docx"
    source_path.write_bytes(b"placeholder")

    worker_code = (
        "import pathlib,sys,time; "
        "time.sleep(1); "
        "pathlib.Path(sys.argv[1]).write_text('late', encoding='utf-8')"
    )
    storage = ReviewFileStorage(upload_dir=str(tmp_path / "uploads"))
    monkeypatch.setattr(storage, "_docx_conversion_timeout_seconds", lambda: 0.05)
    monkeypatch.setattr(
        storage,
        "_build_conversion_worker_command",
        lambda **_kwargs: [sys.executable, "-c", worker_code, str(marker_path)],
    )

    with pytest.raises(TimeoutError, match="转换超时"):
        await storage.convert_docx(
            file_path=str(source_path),
            document_id=99101,
            original_filename="source.docx",
            skills_dir=str(ROOT / "skills"),
        )

    await asyncio.sleep(1.1)
    assert not marker_path.exists()


@pytest.mark.asyncio
async def test_conversion_cancellation_terminates_worker_without_delayed_write(tmp_path, monkeypatch):
    """调用方取消任务时也必须终止工作进程，不能留下孤儿转换。"""
    marker_path = tmp_path / "cancelled-late-write.txt"
    source_path = tmp_path / "source.docx"
    source_path.write_bytes(b"placeholder")
    worker_code = (
        "import pathlib,sys,time; "
        "time.sleep(1); "
        "pathlib.Path(sys.argv[1]).write_text('late', encoding='utf-8')"
    )
    storage = ReviewFileStorage(upload_dir=str(tmp_path / "uploads"))
    monkeypatch.setattr(storage, "_docx_conversion_timeout_seconds", lambda: 5.0)
    monkeypatch.setattr(
        storage,
        "_build_conversion_worker_command",
        lambda **_kwargs: [sys.executable, "-c", worker_code, str(marker_path)],
    )

    conversion_task = asyncio.create_task(
        storage.convert_docx(
            file_path=str(source_path),
            document_id=99102,
            original_filename="source.docx",
            skills_dir=str(ROOT / "skills"),
        )
    )
    await asyncio.sleep(0.05)
    conversion_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await conversion_task

    await asyncio.sleep(1.1)
    assert not marker_path.exists()
