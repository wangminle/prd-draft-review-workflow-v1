"""BUG-191：URL 压缩响应解压炸弹防护。

问题：`_read_capped_response_text` 用 `httpx.aiter_bytes()` 截断，但该方法返回
解压后的数据——几 KB 的 gzip 可瞬时解压成 20MB+，512KB 上限形同虚设。

修复：压缩响应改读原始字节（aiter_raw）+ zlib 增量解压，按解压输出限流；
压缩输入累计量同样受限；不支持的编码（br/zstd）直接拒绝。
"""

import gzip
import sys
import zlib
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.routers.upload import (  # noqa: E402
    _MAX_URL_BODY_BYTES,
    _read_capped_response_text,
)


class FakeResponse:
    """模拟 httpx.Response：aiter_raw 给原始字节，aiter_bytes 给解压后字节。"""

    def __init__(self, raw: bytes, headers: dict):
        self._raw = raw
        self.headers = headers

    async def aiter_raw(self):
        # 分块吐出原始（压缩）字节，模拟网络流
        for i in range(0, len(self._raw), 1024):
            yield self._raw[i : i + 1024]

    async def aiter_bytes(self):
        enc = (self.headers.get("content-encoding") or "identity").lower()
        if enc in ("gzip", "x-gzip"):
            data = gzip.decompress(self._raw)
        elif enc == "deflate":
            data = zlib.decompress(self._raw)
        else:
            data = self._raw
        for i in range(0, len(data), 1024):
            yield data[i : i + 1024]


@pytest.mark.asyncio
async def test_gzip_bomb_truncated_at_cap():
    """压缩炸弹：20KB gzip 解压成 20MB，输出必须被截断在 512KB。"""
    # 高可压缩负载：20MB 重复字节压缩后仅约 20KB
    bomb_plain = b"A" * (20 * 1024 * 1024)
    bomb_gz = gzip.compress(bomb_plain)
    assert len(bomb_gz) < 64 * 1024  # 压缩比足够大，确实是"炸弹"形态

    resp = FakeResponse(bomb_gz, {"content-encoding": "gzip"})
    result = await _read_capped_response_text(resp)

    encoded_len = len(result.encode("utf-8", errors="replace"))
    assert encoded_len <= _MAX_URL_BODY_BYTES, (
        f"解压输出 {encoded_len} 超出上限 {_MAX_URL_BODY_BYTES}，内存炸弹防护失效"
    )


@pytest.mark.asyncio
async def test_normal_gzip_content_passes():
    """正常小体积 gzip 内容应完整解码。"""
    plain = "<html><body>你好，世界</body></html>".encode("utf-8")
    resp = FakeResponse(gzip.compress(plain), {"content-encoding": "gzip"})
    result = await _read_capped_response_text(resp)
    assert "你好，世界" in result


@pytest.mark.asyncio
async def test_identity_response_capped():
    """identity（未压缩）路径行为不变，超限截断。"""
    big = b"x" * (_MAX_URL_BODY_BYTES + 100 * 1024)
    resp = FakeResponse(big, {})
    result = await _read_capped_response_text(resp)
    assert len(result.encode()) <= _MAX_URL_BODY_BYTES


@pytest.mark.asyncio
async def test_unsupported_encoding_rejected():
    """br/zstd 等无法安全限流的编码直接 400。"""
    for enc in ("br", "zstd", "compress"):
        resp = FakeResponse(b"whatever", {"content-encoding": enc})
        with pytest.raises(HTTPException) as exc:
            await _read_capped_response_text(resp)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_deflate_supported():
    """deflate 编码（zlib 封装）可正常限流解压。"""
    plain = b"hello deflate " * 100
    resp = FakeResponse(zlib.compress(plain), {"content-encoding": "deflate"})
    result = await _read_capped_response_text(resp)
    assert result.startswith("hello deflate")


@pytest.mark.asyncio
async def test_raw_deflate_fallback():
    """裸 deflate 流（无 zlib 头）降级重试成功。"""
    plain = b"raw deflate stream " * 50
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw_deflate = compressor.compress(plain) + compressor.flush()
    resp = FakeResponse(raw_deflate, {"content-encoding": "deflate"})
    result = await _read_capped_response_text(resp)
    assert result.startswith("raw deflate stream")


@pytest.mark.asyncio
async def test_gzip_path_never_calls_aiter_bytes():
    """压缩路径必须走 aiter_raw；aiter_bytes 会先整包解压再截断。"""

    class SpyResponse(FakeResponse):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.bytes_calls = 0
            self.raw_chunks = 0

        async def aiter_raw(self):
            async for chunk in super().aiter_raw():
                self.raw_chunks += 1
                yield chunk

        async def aiter_bytes(self):
            self.bytes_calls += 1
            async for chunk in super().aiter_bytes():
                yield chunk

    bomb_gz = gzip.compress(b"A" * (20 * 1024 * 1024))
    resp = SpyResponse(bomb_gz, {"content-encoding": "gzip"})
    await _read_capped_response_text(resp)
    assert resp.bytes_calls == 0
    assert resp.raw_chunks >= 1
    # 达上限后必须停止继续读压缩流，不能把剩余压缩包都读完再丢
    total_raw_chunks = (len(bomb_gz) + 1023) // 1024
    assert resp.raw_chunks < total_raw_chunks
