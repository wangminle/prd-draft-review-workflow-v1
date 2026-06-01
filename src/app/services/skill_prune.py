"""Context pruning utilities — strip base64 images and truncate long content."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# Match base64 image lines: ![alt](data:image/...) — use [^)]+ to match any base64 chars
_BASE64_IMAGE_RE = re.compile(r"!\[.*?\]\(data:image/[a-z]+;base64,[^)]+\)", re.MULTILINE)

# Match inline base64 in any context (img tags, source attrs, etc.)
_BASE64_INLINE_RE = re.compile(r"data:image/[a-z]+;base64,[^\s\"]{100,}", re.MULTILINE)

# Match very long lines (> 500 chars that look like encoded content)
_LONG_LINE_RE = re.compile(r"^(.{500,})$", re.MULTILINE)


def strip_base64_images(text: str) -> str:
    """Remove base64-encoded images from markdown text.

    Replaces ![alt](data:image/...) with a placeholder like [图片: alt],
    and removes inline data:image references.
    """
    # Replace markdown image syntax with placeholder
    def _replace_image(match: re.Match) -> str:
        alt_text = match.group(0)
        # Extract alt text from ![alt](...)
        inner_match = re.match(r"!\[(.*?)\]\(", alt_text)
        alt = inner_match.group(1) if inner_match else "图片"
        return f"[图片: {alt}]"

    result = _BASE64_IMAGE_RE.sub(_replace_image, text)

    # Remove remaining inline base64 references (img tags, source attrs)
    result = _BASE64_INLINE_RE.sub("[base64图片已移除]", result)

    return result


def truncate_content(text: str, max_chars: int = 8000, suffix: str = "\n\n[内容已截断，保留前 {max_chars} 字]") -> str:
    """Truncate text to max_chars, preserving structure.

    Strategy:
    1. First strip base64 images (they bloat context)
    2. If still over max_chars, truncate at the last paragraph break within limit
    3. Append truncation notice
    """
    text = strip_base64_images(text)

    if len(text) <= max_chars:
        return text

    # Find a good truncation point: last double newline within limit
    truncation_point = max_chars
    last_break = text[:max_chars].rfind("\n\n")
    if last_break > max_chars // 2:
        truncation_point = last_break

    # Also check for single newline as fallback
    if last_break < max_chars // 2:
        last_single = text[:max_chars].rfind("\n")
        if last_single > max_chars // 2:
            truncation_point = last_single

    notice = suffix.replace("{max_chars}", str(max_chars))
    return text[:truncation_point] + notice


def truncate_for_classify(text: str) -> str:
    """Truncate content for the classify step (short excerpts only)."""
    return truncate_content(text, max_chars=2000)


def truncate_for_analysis(text: str) -> str:
    """Truncate content for per-analysis step (full content but no base64)."""
    return truncate_content(text, max_chars=8000)


def truncate_for_review_summary(text: str) -> str:
    """Truncate content for system review doc summaries (short)."""
    return truncate_content(text, max_chars=3000)