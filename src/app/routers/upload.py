"""上传路由：文件上传和 URL 抓取 — Phase 2 完整实现"""

import ipaddress
import logging
import socket
import zlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.storage.chat_file_storage import ChatFileStorage

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_URL_BODY_BYTES = 512 * 1024
_MAX_URL_TEXT_CHARS = 10000

# Resolve upload_dir from settings on each call, so test monkeypatches work
_chat_file_storage = ChatFileStorage()


def _get_upload_config() -> dict:
    from app.config import get_settings
    settings = get_settings()
    return settings.get("upload", {})


def _extract_text(content: bytes, filename: str) -> str | None:
    """Extract text content from uploaded file based on extension."""
    from app.services.file_text import extract_text_from_bytes
    return extract_text_from_bytes(content, filename)


def _is_blocked_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any([
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
    ])


def _resolves_to_blocked_network(hostname: str) -> bool:
    lowered = hostname.strip().lower()
    if lowered in {"localhost", "localhost.localdomain"}:
        return True
    if _is_blocked_ip(lowered):
        return True

    try:
        resolved = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False

    for family, _, _, _, sockaddr in resolved:
        candidate = sockaddr[0]
        if family in (socket.AF_INET, socket.AF_INET6) and _is_blocked_ip(candidate):
            return True
    return False


class _SSRFSafeTransport(httpx.AsyncBaseTransport):
    """Custom transport that checks the resolved IP after connecting,
    preventing DNS rebinding attacks where DNS resolves to a public IP
    during validation but to an internal IP during the actual request."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._transport.handle_async_request(request)
        network_stream = response.extensions.get("network_stream")

        if network_stream is None:
            return response

        peer_info = network_stream.get_extra_info("peername")
        if peer_info:
            peer_ip = peer_info[0]
            if _is_blocked_ip(peer_ip):
                await network_stream.aclose()
                raise httpx.RequestError(
                    f"连接目标 IP {peer_ip} 为内网地址，已阻止",
                    request=request,
                )

        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


def _validate_url_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="URL 格式无效，需以 http:// 或 https:// 开头")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL 格式无效")
    if _resolves_to_blocked_network(parsed.hostname):
        raise HTTPException(status_code=400, detail="不允许访问内网地址")


@router.post("/file")
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传文件并提取文本内容"""
    config = _get_upload_config()
    max_size = config.get("max_file_size_mb", 20) * 1024 * 1024
    allowed_extensions = config.get("allowed_extensions", [])

    content = await file.read()
    file_size = len(content)
    if file_size > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，最大允许 {config.get('max_file_size_mb', 20)}MB",
        )

    ext = Path(file.filename or "").suffix.lower()
    if allowed_extensions and ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，允许: {', '.join(allowed_extensions)}",
        )

    stored = await _chat_file_storage.save_upload(filename=file.filename or "upload", content=content)

    return {
        "file_id": stored.file_id,
        "filename": stored.original_filename,
        "size": stored.size,
        "extracted_text": stored.extracted_text,
        "has_content": stored.extracted_text is not None,
    }


@router.post("/url")
async def submit_url(
    req: dict,
    user: User = Depends(get_current_user),
):
    """提交 URL 进行内容抓取"""
    url = req.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="请提供 URL")

    _validate_url_target(url)

    try:
        transport = _SSRFSafeTransport()
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
        ) as client:
            current_url = url
            html_content = None
            max_redirects = 5
            for _ in range(max_redirects + 1):
                async with client.stream("GET", current_url) as resp:
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        redirect_url = resp.headers.get("location", "")
                        if not redirect_url:
                            raise HTTPException(status_code=400, detail="URL 访问失败: 重定向缺少 Location")
                        redirect_url = urljoin(str(resp.request.url), redirect_url)
                        _validate_url_target(redirect_url)
                        current_url = redirect_url
                        continue
                    if resp.status_code != 200:
                        raise HTTPException(
                            status_code=400,
                            detail=f"URL 访问失败: HTTP {resp.status_code}",
                        )
                    html_content = await _read_capped_response_text(resp)
                    break
            else:
                raise HTTPException(status_code=400, detail="重定向次数过多")

            if html_content is None:
                raise HTTPException(status_code=400, detail="重定向次数过多")

            # Simple HTML-to-text extraction
            extracted_text = _html_to_text(html_content)

            if len(extracted_text) > _MAX_URL_TEXT_CHARS:
                extracted_text = extracted_text[:_MAX_URL_TEXT_CHARS] + "\n...(内容过长，已截断)"

            return {
                "url": url,
                "extracted_text": extracted_text,
                "has_content": bool(extracted_text.strip()),
                "content_length": len(extracted_text),
            }

    except httpx.TimeoutException:
        raise HTTPException(status_code=408, detail="URL 访问超时")
    except httpx.RequestError as e:
        raise HTTPException(status_code=400, detail=f"URL 访问失败: {str(e)}")


_ALLOWED_CONTENT_ENCODINGS = ("identity", "gzip", "x-gzip", "deflate")


async def _read_capped_response_text(
    resp: httpx.Response, max_bytes: int = _MAX_URL_BODY_BYTES
) -> str:
    """流式读取响应体，超过上限即停止，避免整包载入内存。

    BUG-191：压缩响应（gzip/deflate）不能直接用 ``aiter_bytes()`` 截断：
    它返回的是解压后的数据，截断发生在解压之后——几 KB 的压缩体可瞬时解压成
    远超上限的内存占用（解压炸弹）。因此对压缩响应改读原始字节（``aiter_raw()``）
    并用 zlib 增量解压，按解压输出长度截断；压缩输入累计量同样受上限约束。
    其它压缩编码（br/zstd 等）无法安全限流，直接拒绝。
    """
    encoding = (resp.headers.get("content-encoding") or "identity").strip().lower()
    if encoding not in _ALLOWED_CONTENT_ENCODINGS:
        raise HTTPException(
            status_code=400,
            detail=f"URL 访问失败: 不支持的压缩响应（Content-Encoding: {encoding}）",
        )
    if encoding != "identity":
        return await _read_capped_compressed_text(resp, encoding, max_bytes)

    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        if total >= max_bytes:
            break
        take = chunk[: max_bytes - total]
        chunks.append(take)
        total += len(take)
        if total >= max_bytes:
            break
    return b"".join(chunks).decode("utf-8", errors="replace")


async def _read_capped_compressed_text(
    resp: httpx.Response, encoding: str, max_bytes: int
) -> str:
    """按解压输出限流读取 gzip/deflate 响应；达到上限立即中止流。"""
    wbits = 31 if encoding in ("gzip", "x-gzip") else zlib.MAX_WBITS
    decompressor = zlib.decompressobj(wbits)
    deflate_fallback_used = False
    chunks: list[bytes] = []
    total = 0        # 已接受的解压输出字节数
    compressed = 0   # 已读入的压缩字节数（同样限流，防恶意大包）
    aborted = False

    async for raw in resp.aiter_raw():
        if not raw or aborted:
            break
        compressed += len(raw)
        if compressed > max_bytes:
            raise HTTPException(status_code=400, detail="URL 响应体过大（压缩数据超限）")
        data = raw
        while data:
            if total >= max_bytes:
                aborted = True
                break
            try:
                # 多取 1 字节用于探测超限，超限部分立即丢弃
                piece = decompressor.decompress(data, max_bytes - total + 1)
            except zlib.error:
                # HTTP deflate 偶见裸流（无 zlib 头）：一次性降级重试
                if encoding == "deflate" and not deflate_fallback_used:
                    decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                    deflate_fallback_used = True
                    continue
                raise HTTPException(status_code=400, detail="URL 响应解压失败")
            data = decompressor.unconsumed_tail
            if not piece:
                break
            room = max_bytes - total
            if len(piece) > room:
                piece = piece[:room]
                total = max_bytes
                chunks.append(piece)
                aborted = True
                break
            chunks.append(piece)
            total += len(piece)

    if not aborted:
        try:
            tail = decompressor.flush()
        except zlib.error:
            tail = b""
        room = max_bytes - total
        if tail and room > 0:
            chunks.append(tail[:room])

    return b"".join(chunks).decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    """Simple HTML to plain text conversion."""
    import re

    # Remove scripts and styles
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)

    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Decode common HTML entities
    entities = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&nbsp;": " ",
        "&#39;": "'",
    }
    for entity, char in entities.items():
        text = text.replace(entity, char)

    return text
