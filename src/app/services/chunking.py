"""文本切块策略：将文档正文按章节和 token 限制切分成 KnowledgeChunk。

切块规则：
- 保留标题、章节、段落来源信息
- 最长 chunk 512 tokens（中文约 512 字符），重叠 64 tokens
- 与 POC-A MAX_CHUNK_CHARS=512, OVERLAP_CHARS=64 一致
- 切块后每个 chunk 可追溯到来源 section
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ChunkResult:
    """切块结果。"""
    chunk_no: int
    text: str
    section: str | None = None
    source_ref: str | None = None
    metadata_json: str | None = None


# 切块参数（与 POC-A 一致）
MAX_CHUNK_CHARS = 512
OVERLAP_CHARS = 64

# Markdown 标题正则
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def chunk_text(
    text: str,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
    source_ref: str | None = None,
) -> list[ChunkResult]:
    """将文本按章节和长度切块。

    策略：
    1. 按 Markdown 标题（## 等）拆分章节
    2. 如果单个章节超过 max_chars，按段落边界二次拆分
    3. 如果段落仍超长，按字符数硬切（带重叠）
    4. 每个块记录所属 section 标题

    Args:
        text: 文档正文
        max_chars: 单块最大字符数
        overlap_chars: 重叠字符数
        source_ref: 来源标识（如文件名）

    Returns:
        切块结果列表
    """
    # 参数校验
    if max_chars <= 0:
        raise ValueError(f"max_chars 必须大于 0，当前值: {max_chars}")
    if overlap_chars < 0:
        raise ValueError(f"overlap_chars 不能为负，当前值: {overlap_chars}")
    if overlap_chars >= max_chars:
        raise ValueError(f"overlap_chars 必须小于 max_chars，当前值: overlap={overlap_chars}, max={max_chars}")

    if not text or not text.strip():
        return []

    # Step 1: 按标题拆分章节
    sections = _split_by_headings(text)

    # Step 2: 对每个章节按长度切分
    chunks: list[ChunkResult] = []
    chunk_no = 0

    for section_title, section_text in sections:
        section_text = section_text.strip()
        if not section_text:
            continue

        # 如果章节不长，直接作为一个 chunk
        if len(section_text) <= max_chars:
            chunk_no += 1
            chunks.append(ChunkResult(
                chunk_no=chunk_no,
                text=section_text,
                section=section_title,
                source_ref=source_ref,
            ))
            continue

        # 按段落边界拆分
        paragraphs = _split_by_paragraphs(section_text)
        current_text = ""

        for para in paragraphs:
            # 如果单段落超长，需要硬切
            if len(para) > max_chars:
                # 先把已累积的内容输出
                if current_text:
                    chunk_no += 1
                    chunks.append(ChunkResult(
                        chunk_no=chunk_no,
                        text=current_text.strip(),
                        section=section_title,
                        source_ref=source_ref,
                    ))
                    current_text = ""

                # 硬切长段落
                hard_chunks = _hard_split(para, max_chars, overlap_chars)
                for hc in hard_chunks:
                    chunk_no += 1
                    chunks.append(ChunkResult(
                        chunk_no=chunk_no,
                        text=hc,
                        section=section_title,
                        source_ref=source_ref,
                    ))
                continue

            # 尝试加入当前 chunk
            candidate = (current_text + "\n\n" + para).strip() if current_text else para
            if len(candidate) <= max_chars:
                current_text = candidate
            else:
                # 输出当前 chunk
                if current_text:
                    chunk_no += 1
                    chunks.append(ChunkResult(
                        chunk_no=chunk_no,
                        text=current_text.strip(),
                        section=section_title,
                        source_ref=source_ref,
                    ))
                current_text = para

        # 输出剩余内容
        if current_text:
            chunk_no += 1
            chunks.append(ChunkResult(
                chunk_no=chunk_no,
                text=current_text.strip(),
                section=section_title,
                source_ref=source_ref,
            ))

    return chunks


def _split_by_headings(text: str) -> list[tuple[str | None, str]]:
    """按 Markdown 标题拆分章节。

    Returns:
        [(section_title, section_text), ...] 列表
    """
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        # 无标题，整个文本作为一个 section
        return [(None, text)]

    sections: list[tuple[str | None, str]] = []

    # 标题之前的文本
    if matches[0].start() > 0:
        pre_text = text[:matches[0].start()].strip()
        if pre_text:
            sections.append((None, pre_text))

    # 每个标题到下一个标题之间的文本
    for i, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if section_text:
            sections.append((title, section_text))

    return sections


def _split_by_paragraphs(text: str) -> list[str]:
    """按双换行拆分段落。"""
    paras = re.split(r"\n{2,}", text)
    return [p.strip() for p in paras if p.strip()]


def _hard_split(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """按字符数硬切，带重叠。"""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start = end - overlap_chars
        if start >= len(text):
            break
        # 避免无限循环
        if start <= end - max_chars:
            start = end

    return chunks
