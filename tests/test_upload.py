"""测试上传路由"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "config.yaml"))

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport, AsyncClient

from app.routers.upload import _SSRFSafeTransport
from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    if os.path.exists(tmp_db):
        os.unlink(tmp_db)


@pytest_asyncio.fixture
async def auth_client(client):
    """已认证的客户端"""
    resp = await client.post(
        "/api/auth/register",
        json={"username": "upload_user", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.mark.asyncio
async def test_upload_txt_file(auth_client):
    """上传 txt 文件应成功并提取文本"""
    content = "这是一个测试文件的内容"
    files = {"file": ("test.txt", content.encode("utf-8"), "text/plain")}
    resp = await auth_client.post("/api/upload/file", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "test.txt"
    assert data["has_content"] is True
    assert data["extracted_text"] == content


@pytest.mark.asyncio
async def test_upload_md_file(auth_client):
    """上传 md 文件应成功并提取文本"""
    content = "# 标题\n\n这是 Markdown 内容"
    files = {"file": ("doc.md", content.encode("utf-8"), "text/markdown")}
    resp = await auth_client.post("/api/upload/file", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_content"] is True
    assert "Markdown" in data["extracted_text"]


@pytest.mark.asyncio
async def test_upload_json_file(auth_client):
    """上传 json 文件应成功并提取文本"""
    content = json.dumps({"key": "value", "list": [1, 2, 3]})
    files = {"file": ("data.json", content.encode("utf-8"), "application/json")}
    resp = await auth_client.post("/api/upload/file", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_content"] is True


@pytest.mark.asyncio
async def test_upload_unsupported_type(auth_client):
    """上传不支持的文件类型应返回 400"""
    content = b"binary data"
    files = {"file": ("test.exe", content, "application/octet-stream")}
    resp = await auth_client.post("/api/upload/file", files=files)
    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    """未认证用户上传应返回 401"""
    content = "test"
    files = {"file": ("test.txt", content.encode("utf-8"), "text/plain")}
    resp = await client.post("/api/upload/file", files=files)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_submit_url_requires_auth(client):
    """未认证用户提交 URL 应返回 401"""
    resp = await client.post("/api/upload/url", json={"url": "https://example.com"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_submit_url_invalid_format(auth_client):
    """提交无效 URL 格式应返回 400"""
    resp = await auth_client.post("/api/upload/url", json={"url": "not-a-url"})
    assert resp.status_code == 400
    assert "URL 格式无效" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_url_empty(auth_client):
    """提交空 URL 应返回 400"""
    resp = await auth_client.post("/api/upload/url", json={"url": ""})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_submit_url_rejects_loopback_targets_before_request(auth_client, monkeypatch):
    """回环地址应在发起请求前被 SSRF 防护拒绝。"""

    async def fail_get(self, *args, **kwargs):
        raise AssertionError("network request should not be attempted for loopback targets")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_get)

    resp = await auth_client.post("/api/upload/url", json={"url": "http://127.0.0.1:8000/admin"})

    assert resp.status_code == 400
    assert "不允许访问内网地址" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_url_rejects_private_network_targets_before_request(auth_client, monkeypatch):
    """私网地址应在发起请求前被 SSRF 防护拒绝。"""

    async def fail_get(self, *args, **kwargs):
        raise AssertionError("network request should not be attempted for private targets")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_get)

    resp = await auth_client.post("/api/upload/url", json={"url": "http://10.0.0.8/spec"})

    assert resp.status_code == 400
    assert "不允许访问内网地址" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_url_follows_relative_redirect_locations(auth_client, monkeypatch):
    """相对 Location 头应基于当前响应 URL 绝对化后继续请求。"""

    called_urls = []

    async def fake_get(self, url, *args, **kwargs):
        called_urls.append(url)
        request = httpx.Request("GET", url)
        if len(called_urls) == 1:
            return httpx.Response(302, headers={"location": "/docs"}, request=request)
        return httpx.Response(200, text="<html><body>redirect ok</body></html>", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    resp = await auth_client.post("/api/upload/url", json={"url": "https://example.com/start"})

    assert resp.status_code == 200
    assert resp.json()["has_content"] is True
    assert "redirect ok" in resp.json()["extracted_text"]
    assert called_urls == ["https://example.com/start", "https://example.com/docs"]


class _DummyNetworkStream:
    def __init__(self, peername):
        self._peername = peername
        self.closed = False

    def get_extra_info(self, name):
        if name == "peername":
            return self._peername
        return None

    async def aclose(self):
        self.closed = True


class _DummyAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, response):
        self.response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self.response


@pytest.mark.asyncio
async def test_ssrf_safe_transport_uses_response_network_stream_extensions():
    """自定义 transport 应从 response.extensions 读取 network_stream，而不是把 Response 当流对象。"""

    stream = _DummyNetworkStream(("93.184.216.34", 443))
    response = httpx.Response(200, text="ok", extensions={"network_stream": stream})
    transport = _SSRFSafeTransport(transport=_DummyAsyncTransport(response))
    request = httpx.Request("GET", "https://example.com")

    result = await transport.handle_async_request(request)

    assert result is response
    assert stream.closed is False


@pytest.mark.asyncio
async def test_ssrf_safe_transport_blocks_private_peer_ip_from_network_stream():
    """自定义 transport 应阻止连接后解析到私网 IP 的响应。"""

    stream = _DummyNetworkStream(("10.0.0.8", 443))
    response = httpx.Response(200, text="ok", extensions={"network_stream": stream})
    transport = _SSRFSafeTransport(transport=_DummyAsyncTransport(response))
    request = httpx.Request("GET", "https://example.com")

    with pytest.raises(httpx.RequestError) as exc_info:
        await transport.handle_async_request(request)

    assert "10.0.0.8" in str(exc_info.value)
    assert stream.closed is True