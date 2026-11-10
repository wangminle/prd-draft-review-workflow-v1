"""上传请求的流式限长读取（CON-08）。

FastAPI/Starlette 的 ``UploadFile.read()`` 会一次性把整个请求体读入内存。
上传接口应先按块读取并在超过上限时立即拒绝，避免并发大文件耗尽进程内存。
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

_DEFAULT_CHUNK_SIZE = 1024 * 1024


async def read_upload_limited(
    upload: UploadFile,
    max_bytes: int,
    *,
    filename: str | None = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> bytes:
    """按块读取上传内容，超过 ``max_bytes`` 抛 413。"""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    data = bytearray()
    while True:
        legacy_read = False
        try:
            chunk = await upload.read(chunk_size)
        except TypeError:
            # 兼容测试桩/旧实现只接受无参 read() 的 UploadFile 替身
            chunk = await upload.read()
            legacy_read = True
        if not chunk:
            break
        data.extend(chunk)
        if legacy_read:
            break
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大: {filename or upload.filename or 'upload'}",
            )
    return bytes(data)
