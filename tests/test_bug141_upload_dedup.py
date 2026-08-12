"""BUG-141: 上传文档去重 — 同项目同类型同名文件不应重复入库。

问题：_save_project_documents 没有去重逻辑，重复上传同名 docx 会
在 review_documents 表中产生多条记录，导致前端列表出现重复项。

修复：上传前检查同一 project_id + document_type + filename 是否已存在，
若存在则跳过并在返回值的 skipped 字段中告知前端。
"""

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import init_test_db, make_test_app


@pytest_asyncio.fixture
async def dedup_client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_maker

    await engine.dispose()
    if os.path.exists(tmp_db):
        try:
            os.unlink(tmp_db)
        except PermissionError:
            pass


async def _register(client, username):
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "test123456"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_project(client, headers, name):
    resp = await client.post(
        "/api/review/projects",
        json={"name": name, "description": ""},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# Minimal valid docx content (PK header for a zip / docx)
_MINIMAL_DOCX = (
    b"PK\x05\x06" + b"\x00" * 18  # empty zip end-of-central-directory
)


class TestUploadDedup:
    """验证文档上传去重逻辑。"""

    @pytest.mark.asyncio
    async def test_requirement_doc_upload_dedup(self, dedup_client):
        """重复上传同名 requirement 文档应跳过第二次。"""
        client, _ = dedup_client
        headers = await _register(client, "dedup_req_user")
        pid = await _create_project(client, headers, "去重测试-需求")

        # 第一次上传
        r1 = await client.post(
            f"/api/review/projects/{pid}/documents",
            files={"files": ("测试文档.docx", _MINIMAL_DOCX, "application/octet-stream")},
            headers=headers,
        )
        assert r1.status_code == 200
        assert r1.json()["uploaded"] == 1
        assert r1.json()["skipped"] == []

        # 第二次上传同名文件
        r2 = await client.post(
            f"/api/review/projects/{pid}/documents",
            files={"files": ("测试文档.docx", _MINIMAL_DOCX, "application/octet-stream")},
            headers=headers,
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["uploaded"] == 0, f"重复文件不应再上传: {data2}"
        assert len(data2["skipped"]) == 1
        assert data2["skipped"][0]["filename"] == "测试文档.docx"

        # 验证 DB 中只有一条记录
        docs_r = await client.get(
            f"/api/review/projects/{pid}/documents",
            headers=headers,
        )
        docs = docs_r.json()
        req_docs = [d for d in docs if d["document_type"] == "requirement"]
        assert len(req_docs) == 1, f"应有 1 条记录，实际 {len(req_docs)}"

    @pytest.mark.asyncio
    async def test_historical_doc_upload_dedup(self, dedup_client):
        """重复上传同名 historical 文档应跳过第二次。"""
        client, _ = dedup_client
        headers = await _register(client, "dedup_hist_user")
        pid = await _create_project(client, headers, "去重测试-历史")

        r1 = await client.post(
            f"/api/review/projects/{pid}/historical-documents",
            files={"files": ("历史文档.docx", _MINIMAL_DOCX, "application/octet-stream")},
            headers=headers,
        )
        assert r1.status_code == 200
        assert r1.json()["uploaded"] == 1

        r2 = await client.post(
            f"/api/review/projects/{pid}/historical-documents",
            files={"files": ("历史文档.docx", _MINIMAL_DOCX, "application/octet-stream")},
            headers=headers,
        )
        assert r2.status_code == 200
        assert r2.json()["uploaded"] == 0
        assert len(r2.json()["skipped"]) == 1

    @pytest.mark.asyncio
    async def test_different_names_not_deduped(self, dedup_client):
        """不同文件名的文档应各自独立上传。"""
        client, _ = dedup_client
        headers = await _register(client, "dedup_diff_user")
        pid = await _create_project(client, headers, "去重测试-不同名")

        r = await client.post(
            f"/api/review/projects/{pid}/documents",
            files=[
                ("files", ("文档A.docx", _MINIMAL_DOCX, "application/octet-stream")),
                ("files", ("文档B.docx", _MINIMAL_DOCX, "application/octet-stream")),
            ],
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["uploaded"] == 2
        assert r.json()["skipped"] == []

    @pytest.mark.asyncio
    async def test_same_name_different_type_not_deduped(self, dedup_client):
        """同名但不同类型（requirement vs historical）的文档不冲突。"""
        client, _ = dedup_client
        headers = await _register(client, "dedup_type_user")
        pid = await _create_project(client, headers, "去重测试-跨类型")

        # requirement 上传
        r1 = await client.post(
            f"/api/review/projects/{pid}/documents",
            files={"files": ("同名.docx", _MINIMAL_DOCX, "application/octet-stream")},
            headers=headers,
        )
        assert r1.json()["uploaded"] == 1

        # historical 上传同名文件 — 应该成功（类型不同）
        r2 = await client.post(
            f"/api/review/projects/{pid}/historical-documents",
            files={"files": ("同名.docx", _MINIMAL_DOCX, "application/octet-stream")},
            headers=headers,
        )
        assert r2.json()["uploaded"] == 1
        assert r2.json()["skipped"] == []

    @pytest.mark.asyncio
    async def test_mixed_upload_partial_dedup(self, dedup_client):
        """批量上传中部分重复：新文件上传，已存在的跳过。"""
        client, _ = dedup_client
        headers = await _register(client, "dedup_mixed_user")
        pid = await _create_project(client, headers, "去重测试-混合")

        # 先上传文档A
        await client.post(
            f"/api/review/projects/{pid}/documents",
            files={"files": ("文档A.docx", _MINIMAL_DOCX, "application/octet-stream")},
            headers=headers,
        )

        # 批量上传：文档A（重复）+ 文档B（新）
        r = await client.post(
            f"/api/review/projects/{pid}/documents",
            files=[
                ("files", ("文档A.docx", _MINIMAL_DOCX, "application/octet-stream")),
                ("files", ("文档B.docx", _MINIMAL_DOCX, "application/octet-stream")),
            ],
            headers=headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["uploaded"] == 1  # 只有文档B
        assert len(data["skipped"]) == 1  # 文档A被跳过
        assert data["skipped"][0]["filename"] == "文档A.docx"
