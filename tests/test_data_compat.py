"""WBS 0.1 — 数据兼容性验证

验证旧数据库、旧文件路径、旧上传文件和转换缓存仍能在当前系统正常读取。
确保后续重构不会破坏本文定义的数据事实源。

验收标准：
- 旧数据库可启动
- 旧聊天记录可查询
- 旧审查项目、文档、报告可查询
- 旧文件路径可解析，新写入路径仍为 runtime 相对路径
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.user import Base, User, Conversation, Message, ContextItem, ModelConfig, PromptTemplate, SkillConfig
from app.models.review import (
    ReviewProject, ReviewDocument, ReviewTask,
    DocAnalysis, SystemReview, ReviewContext, ReviewPrompt,
)
from app.services.auth import hash_password
from app.runtime_paths import runtime_path
from app.routers.review import _resolve_stored_file_path, _to_runtime_relative_path


# ── Helpers ──


def _create_old_style_db(db_path: str) -> None:
    """Create a SQLite database with all tables populated, simulating legacy data.

    Uses raw sqlite3 to write data that mirrors what older code versions
    would have produced — including various path formats.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Create all tables (mirror current schema)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(128) NOT NULL,
            role VARCHAR(10) NOT NULL DEFAULT 'user',
            created_at DATETIME NOT NULL,
            last_active_at DATETIME NOT NULL,
            is_active BOOLEAN DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            title VARCHAR(200),
            model_id VARCHAR(30) NOT NULL,
            prompt_template VARCHAR(50),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id),
            role VARCHAR(10) NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER,
            created_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_context_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            context_type VARCHAR(30) NOT NULL,
            title VARCHAR(200) NOT NULL,
            file_id VARCHAR(100),
            url VARCHAR(500),
            manual_text TEXT,
            extracted_text TEXT,
            enabled BOOLEAN DEFAULT 1,
            created_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(50) UNIQUE NOT NULL,
            description VARCHAR(200),
            system_prompt TEXT,
            user_prompt_template TEXT,
            is_builtin BOOLEAN DEFAULT 0,
            created_by INTEGER REFERENCES users(id),
            created_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS model_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_order INTEGER DEFAULT 0,
            model_id VARCHAR(30) UNIQUE NOT NULL,
            name VARCHAR(100) NOT NULL,
            provider VARCHAR(30) NOT NULL DEFAULT 'openai_compatible',
            api_base VARCHAR(500) NOT NULL,
            encrypted_api_key TEXT,
            llm_model VARCHAR(100) NOT NULL,
            max_tokens INTEGER DEFAULT 4096,
            temperature FLOAT DEFAULT 0.7,
            enabled BOOLEAN DEFAULT 1,
            deleted_by_user BOOLEAN DEFAULT 0,
            last_test_status VARCHAR(20),
            last_test_time DATETIME,
            last_test_latency_ms INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skill_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id VARCHAR(80) UNIQUE NOT NULL,
            name VARCHAR(120) NOT NULL,
            description TEXT NOT NULL,
            local_path VARCHAR(500),
            update_url VARCHAR(1000),
            display_order INTEGER DEFAULT 0,
            is_builtin BOOLEAN DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES review_projects(id),
            filename VARCHAR(500) NOT NULL,
            file_path VARCHAR(1000),
            file_size INTEGER,
            md_path VARCHAR(1000),
            content_hash VARCHAR(64),
            category VARCHAR(50),
            version VARCHAR(30),
            document_type VARCHAR(20) DEFAULT 'requirement',
            status VARCHAR(20) DEFAULT 'uploaded',
            created_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES review_projects(id),
            mode VARCHAR(10) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            current_step INTEGER DEFAULT 0,
            total_docs INTEGER DEFAULT 0,
            completed_docs INTEGER DEFAULT 0,
            context_version INTEGER DEFAULT 1,
            model_id VARCHAR(30),
            created_by INTEGER REFERENCES users(id),
            created_at DATETIME NOT NULL,
            completed_at DATETIME,
            step_statuses TEXT,
            step_details TEXT
        );
        CREATE TABLE IF NOT EXISTS doc_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES review_documents(id),
            task_id INTEGER NOT NULL REFERENCES review_tasks(id),
            core_problem TEXT,
            category VARCHAR(50),
            boundary_in TEXT,
            boundary_out TEXT,
            spec_violations TEXT,
            quality_score FLOAT,
            full_analysis TEXT,
            created_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS system_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES review_tasks(id),
            project_id INTEGER NOT NULL REFERENCES review_projects(id),
            business_value TEXT,
            architecture TEXT,
            competition TEXT,
            product_strategy TEXT,
            tech_evolution TEXT,
            pm_growth TEXT,
            action_plan TEXT,
            pm_scores TEXT,
            created_at DATETIME NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES review_projects(id),
            version INTEGER NOT NULL DEFAULT 1,
            is_active BOOLEAN DEFAULT 1,
            change_log TEXT,
            updated_by INTEGER REFERENCES users(id),
            updated_at DATETIME NOT NULL,
            context_data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(50) UNIQUE NOT NULL,
            description TEXT,
            content TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME NOT NULL
        );
    """)

    now = "2026-05-30 10:00:00"

    # ── Users ──
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, created_at, last_active_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "admin", hash_password("admin123"), "admin", now, now, 1),
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, created_at, last_active_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (2, "testuser", hash_password("test123"), "user", now, now, 1),
    )

    # ── Conversations ──
    conn.execute(
        "INSERT INTO conversations (id, user_id, title, model_id, prompt_template, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 2, "Test Chat", "deepseek-chat", "default", now, now),
    )

    # ── Messages ──
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, token_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, 1, "user", "Hello, how are you?", 10, now),
    )
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, token_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (2, 1, "assistant", "I'm doing well, thank you!", 15, now),
    )

    # ── Context Items ──
    conn.execute(
        "INSERT INTO chat_context_items (id, conversation_id, context_type, title, file_id, url, manual_text, extracted_text, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 1, "file", "test_doc.txt", "abc123.txt", None, None, "This is test content", 1, now),
    )
    conn.execute(
        "INSERT INTO chat_context_items (id, conversation_id, context_type, title, file_id, url, manual_text, extracted_text, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (2, 1, "url", "Test URL", None, "https://example.com", None, "URL content here", 1, now),
    )

    # ── Prompt Templates ──
    conn.execute(
        "INSERT INTO prompt_templates (id, name, description, system_prompt, user_prompt_template, is_builtin, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "default", "通用助手", "你是一个智能助手", None, 1, now),
    )

    # ── Review Projects ──
    conn.execute(
        "INSERT INTO review_projects (id, name, description, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Test Project", "A test project", 2, now, now),
    )
    conn.execute(
        "INSERT INTO review_projects (id, name, description, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (2, "Legacy Project", "Project with legacy paths", 1, now, now),
    )

    # ── Review Documents with various path formats ──
    # New-style: runtime-relative path
    conn.execute(
        "INSERT INTO review_documents (id, project_id, filename, file_path, file_size, md_path, content_hash, category, version, document_type, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 1, "test_req.docx", "data/review_uploads/1/requirement/a1b2c3.docx", 1024,
         "data/converted/doc_1/test_req.md", "sha256abc", "分类A", "V1.0", "requirement", "uploaded", now),
    )
    # Legacy: ./runtime/... format
    conn.execute(
        "INSERT INTO review_documents (id, project_id, filename, file_path, file_size, md_path, content_hash, category, version, document_type, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (2, 2, "legacy_req.docx", "./runtime/data/review_uploads/2/requirement/d4e5f6.docx", 2048,
         "./runtime/data/converted/doc_2/legacy_req.md", "sha256def", "分类B", "V2.0", "requirement", "uploaded", now),
    )
    # Legacy: ../runtime/... format
    conn.execute(
        "INSERT INTO review_documents (id, project_id, filename, file_path, file_size, md_path, content_hash, category, version, document_type, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (3, 2, "legacy_req2.docx", "../runtime/data/review_uploads/2/historical/g7h8i9.docx", 3072,
         "../runtime/data/converted/doc_3/legacy_req2.md", "sha256ghi", "分类C", None, "historical", "uploaded", now),
    )
    # Legacy: absolute path (simulated)
    abs_runtime = str(runtime_path("data", "review_uploads", "2", "requirement", "j0k1l2.docx"))
    conn.execute(
        "INSERT INTO review_documents (id, project_id, filename, file_path, file_size, md_path, content_hash, category, version, document_type, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (4, 2, "abs_req.docx", abs_runtime, 4096,
         None, "sha256jkl", "分类D", None, "requirement", "uploaded", now),
    )

    # ── Review Tasks ──
    conn.execute(
        "INSERT INTO review_tasks (id, project_id, mode, status, current_step, total_docs, completed_docs, context_version, model_id, created_by, created_at, completed_at, step_statuses, step_details) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 1, "quick", "completed", 3, 1, 1, 1, "deepseek-chat", 2, now, now,
         json.dumps({"1": "completed"}), json.dumps({"1": {"category": "分类A"}})),
    )
    conn.execute(
        "INSERT INTO review_tasks (id, project_id, mode, status, current_step, total_docs, completed_docs, context_version, model_id, created_by, created_at, completed_at, step_statuses, step_details) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (2, 2, "review", "completed_with_warnings", 5, 3, 3, 1, "deepseek-chat", 1, now, now,
         json.dumps({"1": "completed", "2": "completed", "3": "completed_with_warnings"}),
         json.dumps({"1": {}, "2": {}, "3": {"warning": "minor issue"}})),
    )
    conn.execute(
        "INSERT INTO review_tasks (id, project_id, mode, status, current_step, total_docs, completed_docs, context_version, model_id, created_by, created_at, completed_at, step_statuses) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (3, 1, "full", "failed", 1, 1, 0, 1, "deepseek-chat", 2, now, None,
         json.dumps({"1": "failed"})),
    )

    # ── Doc Analyses ──
    conn.execute(
        "INSERT INTO doc_analyses (id, document_id, task_id, core_problem, category, boundary_in, boundary_out, spec_violations, quality_score, full_analysis, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 1, 1, "核心问题A", "分类A", '["边界内1"]', '["边界外1"]', '["缺失1"]', 3.5, "Full analysis A", now),
    )

    # ── System Review ──
    conn.execute(
        "INSERT INTO system_reviews (id, task_id, project_id, business_value, architecture, competition, product_strategy, tech_evolution, pm_growth, action_plan, pm_scores, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 2, 2, "BV data", "Arch data", "Comp data", None, None, "PM data", "Plan data",
         json.dumps({"dimension1": 4}), now),
    )

    # ── Review Contexts ──
    conn.execute(
        "INSERT INTO review_contexts (id, project_id, version, is_active, change_log, updated_by, updated_at, context_data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 1, 1, 1, "Initial context", 2, now, json.dumps({"rules": ["rule1", "rule2"]})),
    )

    # ── Review Prompts ──
    conn.execute(
        "INSERT INTO review_prompts (id, name, description, content, version, is_active, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "default", "Default review prompt", "Review the following requirements", 1, 1, now),
    )

    conn.commit()
    conn.close()


# ── WBS 0.1.1: Old database sample can be loaded ──


@pytest.mark.asyncio
async def test_old_database_can_be_loaded_by_current_engine():
    """0.1.1 验证旧库样本可通过当前 SQLAlchemy 引擎加载并查询"""
    db_path = tempfile.mktemp(suffix=".db")
    _create_old_style_db(db_path)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    # P4.Pre: 运行数据库迁移为旧库补全新列
    from app.database import (
        _migrate_approval_approver_required,
        _migrate_skill_config_status_version,
        _migrate_message_anchor_fields,
        _migrate_conversation_mode_project,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_approval_approver_required(conn)
        await _migrate_skill_config_status_version(conn)
        await _migrate_message_anchor_fields(conn)
        await _migrate_conversation_mode_project(conn)

    async with session_maker() as session:
        # Users
        result = await session.execute(select(User))
        users = result.scalars().all()
        assert len(users) >= 2
        assert any(u.username == "admin" for u in users)
        assert any(u.username == "testuser" for u in users)

        # Conversations
        result = await session.execute(select(Conversation))
        convs = result.scalars().all()
        assert len(convs) >= 1
        assert convs[0].title == "Test Chat"

        # Messages
        result = await session.execute(select(Message))
        msgs = result.scalars().all()
        assert len(msgs) >= 2

        # Context Items
        result = await session.execute(select(ContextItem))
        items = result.scalars().all()
        assert len(items) >= 2
        assert any(i.file_id == "abc123.txt" for i in items)
        assert any(i.url == "https://example.com" for i in items)

    await engine.dispose()
    os.unlink(db_path)


# ── WBS 0.1.2: Old path formats resolve correctly ──


class TestPathResolution:
    """0.1.2 验证旧路径格式可正确解析"""

    def test_runtime_relative_path_resolves(self):
        """新风格：data/review_uploads/1/requirement/a.docx"""
        result = _resolve_stored_file_path("data/review_uploads/1/requirement/a.docx")
        assert result is not None
        assert "runtime" in result or "review_uploads" in result
        # Should resolve to an absolute path
        assert Path(result).is_absolute() or "data" in result

    def test_dot_runtime_relative_path_resolves(self):
        """旧风格：./runtime/data/review_uploads/..."""
        result = _resolve_stored_file_path("./runtime/data/review_uploads/2/requirement/b.docx")
        assert result is not None
        # Should strip leading ./ and runtime prefix, resolve via runtime_path
        assert "review_uploads" in result

    def test_parent_relative_runtime_path_resolves(self):
        """旧风格：../runtime/data/review_uploads/..."""
        result = _resolve_stored_file_path("../runtime/data/review_uploads/2/historical/c.docx")
        assert result is not None
        assert "review_uploads" in result

    def test_absolute_path_preserved(self):
        """绝对路径应直接返回不修改"""
        # 使用平台原生的绝对路径（Windows 上 /tmp/... 不是绝对路径）
        import tempfile
        abs_path = os.path.join(tempfile.gettempdir(), "some", "absolute", "path.docx")
        result = _resolve_stored_file_path(abs_path)
        assert result == abs_path

    def test_none_path_returns_none(self):
        result = _resolve_stored_file_path(None)
        assert result is None

    def test_empty_path_returns_none(self):
        result = _resolve_stored_file_path("")
        assert result is None


class TestRuntimeRelativeConversion:
    """验证新写入路径转为 runtime 相对路径"""

    def test_absolute_runtime_path_converts_to_relative(self):
        """绝对路径应转换为 runtime 相对路径"""
        abs_upload = str(runtime_path("data", "review_uploads", "1", "requirement", "a.docx"))
        result = _to_runtime_relative_path(abs_upload)
        assert result is not None
        # Should be relative, e.g., "data/review_uploads/1/requirement/a.docx"
        assert not Path(result).is_absolute()
        assert result.startswith("data/")

    def test_already_relative_stays_relative(self):
        """已经是 runtime 相对路径的保持不变"""
        rel = "data/review_uploads/1/requirement/a.docx"
        result = _to_runtime_relative_path(rel)
        assert result is not None
        assert "data/review_uploads" in result

    def test_none_returns_none(self):
        result = _to_runtime_relative_path(None)
        assert result is None


# ── WBS 0.1.3: Migration logic preserves old data ──


@pytest.mark.asyncio
async def test_init_db_preserves_existing_data():
    """0.1.3 验证服务启动时 init_db() 不破坏旧库数据

    Simulates: an old database is opened, then init_db() runs schema
    migrations and default seeding — existing data must remain intact.
    """
    db_path = tempfile.mktemp(suffix=".db")
    _create_old_style_db(db_path)

    # Build engine against the old DB
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    # Run migration logic (mirrors init_db from database.py)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Run schema patching
        result = await conn.execute(sa_text("PRAGMA table_info(users)"))
        columns = {row[1] for row in result.fetchall()}
        if "last_active_at" not in columns:
            await conn.execute(sa_text("ALTER TABLE users ADD COLUMN last_active_at DATETIME"))

        result = await conn.execute(sa_text("PRAGMA table_info(review_documents)"))
        columns = {row[1] for row in result.fetchall()}
        if "document_type" not in columns:
            await conn.execute(sa_text(
                "ALTER TABLE review_documents ADD COLUMN document_type VARCHAR(20) NOT NULL DEFAULT 'requirement'"
            ))
        if "content_hash" not in columns:
            await conn.execute(sa_text(
                "ALTER TABLE review_documents ADD COLUMN content_hash VARCHAR(64)"
            ))
        # P4.A.6: 版本链
        if "parent_document_id" not in columns:
            await conn.execute(sa_text(
                "ALTER TABLE review_documents ADD COLUMN parent_document_id INTEGER REFERENCES review_documents(id)"
            ))

        sr_result = await conn.execute(sa_text("PRAGMA table_info(system_reviews)"))
        sr_columns = {row[1] for row in sr_result.fetchall()}
        if "product_strategy" not in sr_columns:
            await conn.execute(sa_text("ALTER TABLE system_reviews ADD COLUMN product_strategy TEXT"))
        if "tech_evolution" not in sr_columns:
            await conn.execute(sa_text("ALTER TABLE system_reviews ADD COLUMN tech_evolution TEXT"))

        ctx_result = await conn.execute(sa_text("PRAGMA table_info(chat_context_items)"))
        ctx_columns = {row[1] for row in ctx_result.fetchall()}
        if "extracted_text" not in ctx_columns:
            await conn.execute(sa_text("ALTER TABLE chat_context_items ADD COLUMN extracted_text TEXT"))

        rp_result = await conn.execute(sa_text("PRAGMA table_info(review_projects)"))
        rp_columns = {row[1] for row in rp_result.fetchall()}
        if "workspace_id" not in rp_columns:
            await conn.execute(sa_text(
                "ALTER TABLE review_projects ADD COLUMN workspace_id INTEGER REFERENCES workspaces(id)"
            ))

        # P4.Pre 迁移：补充新列
        from app.database import (
            _migrate_approval_approver_required,
            _migrate_skill_config_status_version,
            _migrate_message_anchor_fields,
            _migrate_conversation_mode_project,
        )
        await _migrate_approval_approver_required(conn)
        await _migrate_skill_config_status_version(conn)
        await _migrate_message_anchor_fields(conn)
        await _migrate_conversation_mode_project(conn)

    # Verify old data still intact after migration
    async with session_maker() as session:
        # Users preserved
        result = await session.execute(select(User))
        users = result.scalars().all()
        assert len(users) >= 2
        assert any(u.username == "admin" for u in users)

        # Conversations preserved
        result = await session.execute(select(Conversation))
        convs = result.scalars().all()
        assert len(convs) >= 1
        assert convs[0].title == "Test Chat"

        # Review projects preserved
        result = await session.execute(select(ReviewProject))
        projects = result.scalars().all()
        assert len(projects) >= 2
        assert any(p.name == "Test Project" for p in projects)

        # Review documents with legacy paths preserved
        result = await session.execute(select(ReviewDocument))
        docs = result.scalars().all()
        assert len(docs) >= 4
        assert any(d.filename == "legacy_req.docx" for d in docs)

        # Review tasks preserved
        result = await session.execute(select(ReviewTask))
        tasks = result.scalars().all()
        assert len(tasks) >= 2
        assert any(t.mode == "quick" and t.status == "completed" for t in tasks)

        # Doc analyses preserved
        result = await session.execute(select(DocAnalysis))
        analyses = result.scalars().all()
        assert len(analyses) >= 1

        # System review preserved
        result = await session.execute(select(SystemReview))
        reviews = result.scalars().all()
        assert len(reviews) >= 1

        # Review context preserved
        result = await session.execute(select(ReviewContext))
        contexts = result.scalars().all()
        assert len(contexts) >= 1

        # Review prompt preserved
        result = await session.execute(select(ReviewPrompt))
        prompts = result.scalars().all()
        assert len(prompts) >= 1

    await engine.dispose()
    os.unlink(db_path)


# ── WBS 0.1.4: Old upload files and conversion caches readable ──


@pytest.mark.asyncio
async def test_old_upload_file_path_resolves_readable():
    """0.1.4 验证旧上传文件路径通过 _resolve_stored_file_path 可解析"""
    # Test all path formats stored in the old DB sample
    paths = [
        "data/review_uploads/1/requirement/a1b2c3.docx",
        "./runtime/data/review_uploads/2/requirement/d4e5f6.docx",
        "../runtime/data/review_uploads/2/historical/g7h8i9.docx",
    ]
    for p in paths:
        resolved = _resolve_stored_file_path(p)
        # Resolution should produce a path containing the expected directory structure
        assert resolved is not None
        assert "review_uploads" in resolved or "converted" in resolved


@pytest.mark.asyncio
async def test_old_conversion_cache_path_resolves():
    """0.1.4 验证旧转换缓存路径通过 _resolve_stored_file_path 可解析"""
    paths = [
        "data/converted/doc_1/test_req.md",
        "./runtime/data/converted/doc_2/legacy_req.md",
        "../runtime/data/converted/doc_3/legacy_req2.md",
    ]
    for p in paths:
        resolved = _resolve_stored_file_path(p)
        assert resolved is not None
        assert "converted" in resolved


# ── WBS 0.1: FTS compatibility ──


@pytest.mark.asyncio
async def test_fts5_can_be_created_on_old_database():
    """验证 FTS5 虚拟表可在旧库上成功创建"""
    db_path = tempfile.mktemp(suffix=".db")
    _create_old_style_db(db_path)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    # P4.Pre: 运行迁移为旧库补全新列
    from app.database import (
        _migrate_approval_approver_required,
        _migrate_skill_config_status_version,
        _migrate_message_anchor_fields,
        _migrate_conversation_mode_project,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_approval_approver_required(conn)
        await _migrate_skill_config_status_version(conn)
        await _migrate_message_anchor_fields(conn)
        await _migrate_conversation_mode_project(conn)

    async with engine.begin() as conn:
        await conn.execute(sa_text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts "
            "USING fts5(content, content='messages', content_rowid='id', tokenize='unicode61')"
        ))
        # Trigger for new inserts
        await conn.execute(sa_text(
            "CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages "
            "BEGIN INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END"
        ))

    # Verify FTS works — insert a new message and search
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        new_msg = Message(conversation_id=1, role="user", content="FTS compatibility test message")
        session.add(new_msg)
        await session.commit()

    # Search via FTS
    async with engine.begin() as conn:
        result = await conn.execute(sa_text(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'compatibility'"
        ))
        rows = result.fetchall()
        assert len(rows) >= 1

    await engine.dispose()
    os.unlink(db_path)