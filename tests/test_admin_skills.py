import os
import tempfile
from datetime import datetime, timedelta, timezone
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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


async def _admin_headers(client):
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_skills_lists_default_six_skills(client):
    headers = await _admin_headers(client)

    resp = await client.get("/api/admin/skills", headers=headers)

    assert resp.status_code == 200, resp.text
    skills = resp.json()
    assert [s["skill_id"] for s in skills] == [
        "docx-to-markdown",
        "prd-overview-classify",
        "prd-per-analysis",
        "system-review",
        "requirement-insights",
        "report-generator",
    ]
    per_analysis = next(s for s in skills if s["skill_id"] == "prd-per-analysis")
    assert "专家意见评审" in per_analysis["description"]
    assert all(s["name"] and s["description"] for s in skills)
    assert all("update_url" in s for s in skills)


@pytest.mark.asyncio
async def test_admin_can_update_skill_update_url(client):
    headers = await _admin_headers(client)

    resp = await client.put(
        "/api/admin/skills/prd-per-analysis",
        headers=headers,
        json={"update_url": "https://example.com/skills/prd-per-analysis.git"},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/admin/skills", headers=headers)
    assert resp.status_code == 200, resp.text
    target = next(s for s in resp.json() if s["skill_id"] == "prd-per-analysis")
    assert target["update_url"] == "https://example.com/skills/prd-per-analysis.git"


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_skills(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "normal_skill_user", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/admin/skills", headers=headers)

    assert resp.status_code == 403


def test_recent_access_records_only_include_last_7_days(tmp_path):
    from app.log_writers.audit_log_reader import AuditLogReader

    reader = AuditLogReader()
    now = datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc)
    log_file = tmp_path / "audit.jsonl"
    entries = [
        {
            "timestamp": (now - timedelta(days=1)).isoformat(),
            "action": "admin.stats.view",
            "result": "success",
            "actor": {"username": "admin"},
            "request": {"method": "GET", "path": "/api/admin/stats", "client_ip": "127.0.0.1"},
        },
        {
            "timestamp": (now - timedelta(days=8)).isoformat(),
            "action": "old.visit",
            "result": "success",
            "actor": {"username": "admin"},
            "request": {"method": "GET", "path": "/old", "client_ip": "127.0.0.1"},
        },
        {"not": "json-compatible-but-missing-timestamp"},
    ]
    log_file.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")

    records = reader.list_recent_access_records(logs_dir=tmp_path, now=now, days=7, limit=20)

    assert len(records) == 1
    assert records[0].username == "admin"
    assert records[0].action == "admin.stats.view"
    assert records[0].method == "GET"
    assert records[0].path == "/api/admin/stats"
    assert records[0].client_ip == "127.0.0.1"


def test_llm_skills_have_system_context_prompts():
    from pathlib import Path

    root = Path(__file__).parent.parent

    for skill_id in [
        "prd-overview-classify",
        "requirement-insights",
        "report-generator",
    ]:
        prompt = root / "skills" / skill_id / "prompts" / "system-context.md"
        assert prompt.exists(), f"{skill_id} 缺少 system-context.md"
        assert "JSON" in prompt.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_admin_stats_returns_recent_visits(client):
    headers = await _admin_headers(client)

    resp = await client.get("/api/admin/stats", headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "recent_visits" in data
    assert isinstance(data["recent_visits"], list)
