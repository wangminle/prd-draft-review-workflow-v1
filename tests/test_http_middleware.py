"""HTTP 中间件回归测试。"""

import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("CONFIG_PATH", str(SRC / "config.yaml"))

from main import app


@pytest.mark.asyncio
async def test_api_responses_disable_cache():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"