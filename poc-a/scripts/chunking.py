"""POC-A 切块服务 — 将样例文档切成可检索单元。

切块策略（与 WBS P2.A.4 一致）：
- 最长 chunk: 512 tokens（中文约 1 token/字，取 512 字符为近似上限）
- 重叠: 64 tokens（64 字符）
- 保留标题、章节编号、段落来源
- 每个 chunk 带元数据: source_id, section, chunk_no, source_type
"""

import re
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict

MAX_CHUNK_CHARS = 512
OVERLAP_CHARS = 64

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


@dataclass
class Chunk:
    chunk_no: int
    text: str
    section: str
    source_id: str
    source_type: str  # prd / norm / report
    source_title: str
    char_start: int
    char_end: int


def _split_by_sections(md_text: str) -> list[tuple[str, str]]:
    """按 ## 标题切分，返回 [(section_title, section_body), ...]"""
    parts = re.split(r'^##\s+', md_text, flags=re.MULTILINE)
    if len(parts) <= 1:
        return [("full", md_text)]

    sections = []
    # First part is content before any ## header (usually h1 title + intro)
    if parts[0].strip():
        # Extract h1 title if present
        h1_match = re.match(r'^#\s+(.+)', parts[0].strip(), re.MULTILINE)
        if h1_match:
            sections.append(("h1: " + h1_match.group(1).strip(), parts[0].strip()))
        else:
            sections.append(("intro", parts[0].strip()))

    for part in parts[1:]:
        lines = part.split('\n', 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if title or body:
            sections.append((title, body))

    return sections


def _chunk_section(text: str, max_chars: int = MAX_CHUNK_CHARS,
                   overlap: int = OVERLAP_CHARS) -> list[str]:
    """将一个 section 的文本切成不超过 max_chars 的 chunk，带 overlap。"""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        start = end - overlap
        if start >= len(text) - overlap:
            break
    return chunks


def chunk_document(source_id: str, source_type: str, source_title: str,
                   md_text: str) -> list[Chunk]:
    """将一篇文档切成 chunks，保留章节来源。"""
    sections = _split_by_sections(md_text)
    chunks = []
    chunk_no = 0
    char_offset = 0

    for section_title, section_body in sections:
        sub_chunks = _chunk_section(section_body)
        for sub_text in sub_chunks:
            chunk_no += 1
            chunks.append(Chunk(
                chunk_no=chunk_no,
                text=sub_text,
                section=section_title,
                source_id=source_id,
                source_type=source_type,
                source_title=source_title,
                char_start=char_offset,
                char_end=char_offset + len(sub_text),
            ))
            char_offset += len(sub_text) - OVERLAP_CHARS if len(sub_text) > MAX_CHUNK_CHARS else len(sub_text)

    return chunks


def load_all_samples() -> list[tuple[str, str, str, str]]:
    """加载所有样例文档，返回 [(source_id, source_type, title, content), ...]"""
    docs = []
    for category, dir_name in [("prd", "prds"), ("norm", "norms"), ("report", "reports")]:
        dir_path = SAMPLES_DIR / dir_name
        if not dir_path.exists():
            continue
        for f in sorted(dir_path.glob("*.md")):
            source_id = f.stem
            title = source_id.split("-", 2)[-1] if "-" in source_id else source_id
            content = f.read_text(encoding="utf-8")
            docs.append((source_id, category, title, content))
    return docs


def build_chunk_index() -> list[Chunk]:
    """加载所有样例 → 切块 → 返回全部 chunks。"""
    all_chunks = []
    for source_id, source_type, title, content in load_all_samples():
        chunks = chunk_document(source_id, source_type, title, content)
        all_chunks.extend(chunks)
    return all_chunks


if __name__ == "__main__":
    chunks = build_chunk_index()
    print(f"Total chunks: {len(chunks)}")
    for c in chunks[:5]:
        print(f"  [{c.source_id}] §{c.section} chunk#{c.chunk_no}: {c.text[:80]}...")