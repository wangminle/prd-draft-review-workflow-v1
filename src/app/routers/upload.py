"""上传路由：文件上传和 URL 抓取 — Phase 2 完整实现"""

import ipaddress
import logging
import os
import socket
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.runtime_paths import runtime_path
from app.services.file_text import extract_text_from_bytes

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_upload_config() -> dict:
    from app.config import get_settings
    settings = get_settings()
    return settings.get("upload", {})


def _extract_text(content: bytes, filename: str) -> str | None:
    """Extract text content from uploaded file based on extension."""
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
    upload_dir = config.get("upload_dir", str(runtime_path("uploads")))

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

    # Save file
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = os.path.join(upload_dir, saved_name)
    os.makedirs(upload_dir, exist_ok=True)
    with open(saved_path, "wb") as f:
        f.write(content)

    # Extract text content
    extracted_text = _extract_text(content, file.filename or saved_name)

    return {
        "file_id": saved_name,
        "filename": file.filename,
        "size": file_size,
        "extracted_text": extracted_text,
        "has_content": extracted_text is not None,
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
            resp = await client.get(url)
            max_redirects = 5
            for _ in range(max_redirects):
                if resp.status_code not in {301, 302, 303, 307, 308}:
                    break
                redirect_url = resp.headers.get("location", "")
                if not redirect_url:
                    break
                redirect_url = urljoin(str(resp.request.url), redirect_url)
                _validate_url_target(redirect_url)
                resp = await client.get(redirect_url)

            if resp.status_code not in {200, 301, 302, 303, 307, 308} and resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"URL 访问失败: HTTP {resp.status_code}",
                )
            if resp.status_code in {301, 302, 303, 307, 308}:
                raise HTTPException(status_code=400, detail="重定向次数过多")

            html_content = resp.text

            # Simple HTML-to-text extraction
            extracted_text = _html_to_text(html_content)

            # Truncate if too long
            max_chars = 10000
            if len(extracted_text) > max_chars:
                extracted_text = extracted_text[:max_chars] + "\n...(内容过长，已截断)"

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
