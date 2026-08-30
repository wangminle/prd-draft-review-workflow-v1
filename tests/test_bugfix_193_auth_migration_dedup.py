"""BUG-193：agent_authorizations 存量去重迁移必须保留「最新有效」记录。

原实现保留 MIN(id)（最早记录）：
- 旧记录已过期、新记录有效 → 误留过期授权；
- 旧记录权限较宽、新记录已收窄 → 误留过宽权限。

修复：组内存在未过期记录时保留其中 id 最大者；全部过期时保留 id 最大者。
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("CONFIG_PATH", str(ROOT / "src" / "config.yaml"))

from app.database import _migrate_agent_authorization_unique  # noqa: E402
from app.utils import now_cn  # noqa: E402

TABLE_SQL = """
CREATE TABLE agent_authorizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    granted_by INTEGER NOT NULL,
    scope_type VARCHAR(20) NOT NULL,
    scope_id INTEGER,
    permissions_json TEXT,
    expires_at DATETIME,
    created_at DATETIME NOT NULL
)
"""

INSERT_SQL = """
INSERT INTO agent_authorizations
    (id, agent_id, granted_by, scope_type, scope_id, permissions_json, expires_at, created_at)
VALUES (:id, :agent_id, 1, :scope_type, :scope_id, :perms, :expires_at, :created_at)
"""


async def _seed_and_migrate(rows):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(TABLE_SQL))
        now = now_cn()
        for row in rows:
            await conn.execute(text(INSERT_SQL), {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "scope_type": row["scope_type"],
                "scope_id": row.get("scope_id"),
                "perms": row.get("perms", '["read"]'),
                "expires_at": row.get("expires_at", now + timedelta(days=30)),
                "created_at": now - timedelta(days=1),
            })
        await _migrate_agent_authorization_unique(conn)
        kept = (await conn.execute(text(
            "SELECT id FROM agent_authorizations ORDER BY id"
        ))).scalars().all()
        index = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='uq_agent_auth_scope'"
        ))).fetchone()
    await engine.dispose()
    return kept, index


@pytest.mark.asyncio
async def test_expired_old_valid_new_keeps_new():
    """旧记录过期、新记录有效 → 保留新记录。"""
    now = now_cn()
    kept, index = await _seed_and_migrate([
        {"id": 1, "agent_id": 1, "scope_type": "workspace", "scope_id": 10,
         "expires_at": now - timedelta(days=1)},
        {"id": 2, "agent_id": 1, "scope_type": "workspace", "scope_id": 10,
         "expires_at": now + timedelta(days=30)},
    ])
    assert kept == [2], f"应保留有效的新记录: {kept}"
    assert index is not None


@pytest.mark.asyncio
async def test_wide_old_narrow_new_keeps_new():
    """旧记录权限宽、新记录已收窄（均有效）→ 保留最新（收窄）记录。"""
    kept, _ = await _seed_and_migrate([
        {"id": 3, "agent_id": 1, "scope_type": "personal", "scope_id": None,
         "perms": '["read", "write", "search", "execute"]'},
        {"id": 4, "agent_id": 1, "scope_type": "personal", "scope_id": None,
         "perms": '["read"]'},
    ])
    assert kept == [4], f"应保留最新（收窄）记录: {kept}"


@pytest.mark.asyncio
async def test_all_expired_keeps_latest_as_history():
    """组内全部过期 → 保留 id 最大者（已过期，仅作历史，不授予访问）。"""
    now = now_cn()
    kept, _ = await _seed_and_migrate([
        {"id": 5, "agent_id": 2, "scope_type": "workspace", "scope_id": 20,
         "expires_at": now - timedelta(days=10)},
        {"id": 6, "agent_id": 2, "scope_type": "workspace", "scope_id": 20,
         "expires_at": now - timedelta(days=1)},
    ])
    assert kept == [6], f"全部过期时应保留最新记录: {kept}"


@pytest.mark.asyncio
async def test_no_expiry_is_valid_forever():
    """expires_at 为 NULL 视为永久有效。"""
    now = now_cn()
    kept, _ = await _seed_and_migrate([
        {"id": 7, "agent_id": 3, "scope_type": "workspace", "scope_id": 30,
         "expires_at": now - timedelta(days=5)},
        {"id": 8, "agent_id": 3, "scope_type": "workspace", "scope_id": 30,
         "expires_at": None},
    ])
    assert kept == [8]


@pytest.mark.asyncio
async def test_distinct_groups_independent():
    """不同 (agent, scope_type, scope_id) 组互不影响，单条组原样保留。"""
    kept, _ = await _seed_and_migrate([
        {"id": 9, "agent_id": 4, "scope_type": "workspace", "scope_id": 10},
        {"id": 10, "agent_id": 5, "scope_type": "workspace", "scope_id": 10},
        {"id": 11, "agent_id": 5, "scope_type": "project", "scope_id": None},
    ])
    assert kept == [9, 10, 11]


@pytest.mark.asyncio
async def test_legacy_table_without_expires_at_keeps_max_id():
    """极旧库无 expires_at 列：退化为 MAX(id) 且唯一索引仍创建。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE agent_authorizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                granted_by INTEGER NOT NULL,
                scope_type VARCHAR(20) NOT NULL,
                scope_id INTEGER,
                permissions_json TEXT,
                created_at DATETIME NOT NULL
            )
        """))
        now = now_cn()
        for rid in (1, 2):
            await conn.execute(text("""
                INSERT INTO agent_authorizations
                    (id, agent_id, granted_by, scope_type, scope_id, permissions_json, created_at)
                VALUES (:id, 1, 1, 'workspace', 10, '["read"]', :created_at)
            """), {"id": rid, "created_at": now})
        await _migrate_agent_authorization_unique(conn)
        kept = (await conn.execute(text(
            "SELECT id FROM agent_authorizations"
        ))).scalars().all()
        index = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='uq_agent_auth_scope'"
        ))).fetchone()
    await engine.dispose()
    assert kept == [2]
    assert index is not None
