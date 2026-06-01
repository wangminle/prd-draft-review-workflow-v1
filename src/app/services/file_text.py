"""文件正文抽取工具，供上传和聊天上下文复用。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".tsv",
    ".log",
    ".py",
    ".js",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".xml",
    ".sql",
}

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_text_from_bytes(content: bytes, filename: str) -> str | None:
    """根据文件名后缀从字节内容中抽取可注入 LLM 的正文。"""
    ext = Path(filename or "").suffix.lower()

    if ext in TEXT_EXTENSIONS:
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            return None

    if ext == ".docx":
        return _extract_docx_text(content)

    if ext == ".pdf":
        return "[PDF 文件内容提取需要额外库支持，当前仅保存文件]"

    if ext == ".doc":
        return "[Word .doc 文件内容提取需要额外库支持，当前仅保存文件]"

    return None


def extract_text_from_path(file_path: str | Path, filename: str | None = None) -> str | None:
    path = Path(file_path)
    if not path.is_file():
        return None
    return extract_text_from_bytes(path.read_bytes(), filename or path.name)


def _extract_docx_text(content: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as docx:
            xml_bytes = docx.read("word/document.xml")
    except Exception:
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    paragraphs: list[str] = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_NS}t":
                parts.append(node.text or "")
            elif node.tag == f"{WORD_NS}tab":
                parts.append("\t")
            elif node.tag in {f"{WORD_NS}br", f"{WORD_NS}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    return "\n".join(paragraphs) or None
