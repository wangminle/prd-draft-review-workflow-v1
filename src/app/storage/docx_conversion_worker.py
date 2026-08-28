"""隔离执行不可信 DOCX 转换的子进程入口。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import zipfile
from pathlib import Path


logger = logging.getLogger(__name__)
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024
MAX_SINGLE_ENTRY_UNCOMPRESSED = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


class DocxSecurityError(ValueError):
    """工作进程内置的 DOCX 安全拒绝。"""


def _validate_zip_safety(file_path: str) -> None:
    """确保没有 Skill 模块时，Mammoth 降级仍受等价 ZIP 限制。"""
    total_uncompressed = 0
    with zipfile.ZipFile(file_path, "r") as archive:
        for info in archive.infolist():
            total_uncompressed += info.file_size
            if info.file_size > MAX_SINGLE_ENTRY_UNCOMPRESSED:
                raise DocxSecurityError(f"ZIP entry 过大：{info.filename}")
            if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise DocxSecurityError(f"ZIP entry 压缩比过高：{info.filename}")
    if total_uncompressed > MAX_TOTAL_UNCOMPRESSED:
        raise DocxSecurityError("ZIP 总解压大小超限")


def _load_skill_converter(skills_dir: str):
    script_path = Path(skills_dir) / "docx-to-markdown" / "scripts" / "convert_docx.py"
    if not script_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("isolated_docx_converter", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 DOCX Skill：{script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fallback_mammoth(file_path: str, output_dir: str, original_filename: str | None) -> str:
    import mammoth

    _validate_zip_safety(file_path)
    with open(file_path, "rb") as source_file:
        result = mammoth.convert_to_markdown(source_file)
    stem = os.path.splitext(original_filename)[0] if original_filename else "output"
    safe_stem = "".join(c if c.isalnum() or c in "._- " else "_" for c in stem).strip(". ")
    output_path = Path(output_dir) / f"{safe_stem or 'output'}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.value, encoding="utf-8")
    return str(output_path)


def run_conversion(
    *, file_path: str, output_dir: str, original_filename: str | None, skills_dir: str
) -> dict:
    converter = _load_skill_converter(skills_dir) if skills_dir else None
    if converter is None:
        md_path = _fallback_mammoth(file_path, output_dir, original_filename)
        return {"status": "ok", "md_path": md_path, "engine": "mammoth"}

    kwargs = {"output_name": original_filename} if original_filename else {}
    # on_limit="skip"：含超限附件的正常文档降级继续转换（仅跳过超限资源并
    # 在输出中留下可见说明）；ZIP bomb 等恶意特征在任何模式下仍整篇拒绝
    result = converter.convert_docx_to_markdown(file_path, output_dir, on_limit="skip", **kwargs)
    if isinstance(result, dict):
        md_path = result.get("output_path") or result.get("md_path") or result.get("path") or ""
    elif isinstance(result, (str, os.PathLike)):
        md_path = str(result)
    else:
        md_path = ""
    if not md_path:
        raise RuntimeError("DOCX 转换未返回 Markdown 路径")
    return {"status": "ok", "md_path": md_path, "engine": "skill"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--original-filename", default="")
    parser.add_argument("--skills-dir", default="")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        payload = run_conversion(
            file_path=args.file_path,
            output_dir=args.output_dir,
            original_filename=args.original_filename or None,
            skills_dir=args.skills_dir,
        )
    except Exception as exc:
        payload = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 2

    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
