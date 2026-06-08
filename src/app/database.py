"""Database 模块：SQLAlchemy 引擎、Session 工厂、初始化"""

import json
import logging
import os
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.user import Base
from app.models.user import ContextItem, SkillConfig  # noqa: F401 — ensure tables are registered
from app.models.workspace import Workspace, WorkspaceMember, KnowledgeSource, ProjectSourceRef  # noqa: F401 — ensure workspace tables are registered
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk, RetrievalLog, AnswerFeedback  # noqa: F401 — ensure knowledge tables are registered
from app.utils import now_cn

logger = logging.getLogger(__name__)
from app.models.review import (  # noqa: F401 — ensure review tables are registered
    ReviewProject,
    ReviewDocument,
    ReviewTask,
    DocAnalysis,
    SystemReview,
    ReviewContext,
    ReviewPrompt,
)

_settings = get_settings()
_db_path = _settings["database"]["path"]

# 确保 data 目录存在
Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    f"sqlite+aiosqlite:///{_db_path}",
    echo=False,
)

async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    """FastAPI 依赖：获取数据库 session"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """初始化数据库：创建表、FTS5、默认管理员、内置 Prompt 模板、模型配置"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_review_schema(conn)

    # FTS5 虚拟表
    await _ensure_fts5()

    # 默认管理员
    await _ensure_default_admin()

    # 内置 Prompt 模板
    await _ensure_builtin_prompts()

    # 模型配置（从 config.yaml 初始化）
    await _ensure_model_configs()

    # 内置 Skills 配置
    await _ensure_skill_configs()

    # 清理僵尸任务：服务重启后遗留的 running/pending 状态
    await _cleanup_zombie_tasks()

    # 默认 workspace（兼容旧数据）
    await _ensure_default_workspace()


async def _ensure_review_schema(conn):
    """补齐轻量 schema 变更，兼容已有本地 SQLite 数据库。"""
    user_result = await conn.execute(text("PRAGMA table_info(users)"))
    user_columns = {row[1] for row in user_result.fetchall()}
    if "last_active_at" not in user_columns:
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN last_active_at DATETIME"
        ))
        await conn.execute(text(
            "UPDATE users SET last_active_at = created_at WHERE last_active_at IS NULL"
        ))

    result = await conn.execute(text("PRAGMA table_info(review_documents)"))
    columns = {row[1] for row in result.fetchall()}
    if "document_type" not in columns:
        await conn.execute(text(
            "ALTER TABLE review_documents "
            "ADD COLUMN document_type VARCHAR(20) NOT NULL DEFAULT 'requirement'"
        ))
    if "content_hash" not in columns:
        await conn.execute(text(
            "ALTER TABLE review_documents "
            "ADD COLUMN content_hash VARCHAR(64)"
        ))

    # SystemReview columns for upgraded databases
    sr_result = await conn.execute(text("PRAGMA table_info(system_reviews)"))
    sr_columns = {row[1] for row in sr_result.fetchall()}
    if "product_strategy" not in sr_columns:
        await conn.execute(text(
            "ALTER TABLE system_reviews ADD COLUMN product_strategy TEXT"
        ))
    if "tech_evolution" not in sr_columns:
        await conn.execute(text(
            "ALTER TABLE system_reviews ADD COLUMN tech_evolution TEXT"
        ))

    # ContextItem: add extracted_text column for URL content
    ctx_result = await conn.execute(text("PRAGMA table_info(chat_context_items)"))
    ctx_columns = {row[1] for row in ctx_result.fetchall()}
    if "extracted_text" not in ctx_columns:
        await conn.execute(text(
            "ALTER TABLE chat_context_items ADD COLUMN extracted_text TEXT"
        ))

    mc_result = await conn.execute(text("PRAGMA table_info(model_configs)"))
    mc_columns = {row[1] for row in mc_result.fetchall()}
    if "display_order" not in mc_columns:
        await conn.execute(text(
            "ALTER TABLE model_configs ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "UPDATE model_configs SET display_order = id WHERE display_order IS NULL OR display_order = 0"
        ))
    if "deleted_by_user" not in mc_columns:
        await conn.execute(text(
            "ALTER TABLE model_configs ADD COLUMN deleted_by_user BOOLEAN NOT NULL DEFAULT 0"
        ))
    if "thinking_supported" not in mc_columns:
        await conn.execute(text(
            "ALTER TABLE model_configs ADD COLUMN thinking_supported BOOLEAN NOT NULL DEFAULT 0"
        ))
    if "thinking_level" not in mc_columns:
        await conn.execute(text(
            "ALTER TABLE model_configs ADD COLUMN thinking_level VARCHAR(10) NOT NULL DEFAULT 'off'"
        ))
    if "thinking_adapter" not in mc_columns:
        await conn.execute(text(
            "ALTER TABLE model_configs ADD COLUMN thinking_adapter VARCHAR(30) NOT NULL DEFAULT 'none'"
        ))
    if "thinking_payload" not in mc_columns:
        await conn.execute(text(
            "ALTER TABLE model_configs ADD COLUMN thinking_payload TEXT"
        ))

    # ReviewProject: add workspace_id column for team workspace
    rp_result = await conn.execute(text("PRAGMA table_info(review_projects)"))
    rp_columns = {row[1] for row in rp_result.fetchall()}
    if "workspace_id" not in rp_columns:
        await conn.execute(text(
            "ALTER TABLE review_projects ADD COLUMN workspace_id INTEGER REFERENCES workspaces(id)"
        ))

    # Workspace: add is_default column for stable default workspace identification
    ws_result = await conn.execute(text("PRAGMA table_info(workspaces)"))
    ws_columns = {row[1] for row in ws_result.fetchall()}
    if "is_default" not in ws_columns:
        await conn.execute(text(
            "ALTER TABLE workspaces ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "UPDATE workspaces SET is_default = 1 WHERE name = '默认空间'"
        ))

    # KnowledgeSource: add file_id and extracted_text columns
    ks_result = await conn.execute(text("PRAGMA table_info(knowledge_sources)"))
    ks_columns = {row[1] for row in ks_result.fetchall()}
    if "file_id" not in ks_columns:
        await conn.execute(text(
            "ALTER TABLE knowledge_sources ADD COLUMN file_id VARCHAR(12)"
        ))
    if "extracted_text" not in ks_columns:
        await conn.execute(text(
            "ALTER TABLE knowledge_sources ADD COLUMN extracted_text TEXT"
        ))


async def _ensure_fts5():
    """创建 FTS5 虚拟表及其同步触发器"""
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
            USING fts5(content, content='messages', content_rowid='id', tokenize='unicode61')
        """))
        await conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages
            BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END
        """))
        await conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages
            BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
            END
        """))


async def _ensure_default_admin():
    """确保默认管理员用户存在；若使用默认密码则打印警告"""
    from app.models.user import User
    from app.services.auth import hash_password, verify_password

    async with async_session() as session:

        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one_or_none()
        if admin is None:
            import secrets as _secrets
            temp_password = _secrets.token_hex(8)
            admin = User(
                username="admin",
                password_hash=hash_password(temp_password),
                role="admin",
            )
            session.add(admin)
            await session.commit()
            logger.info("[INIT] 管理员账号已创建，请查看配置获取初始密码")
        elif verify_password("admin123", admin.password_hash):
            logger.warning("[SECURITY] 检测到默认弱口令 admin/admin123，强烈建议立即修改密码")


async def _ensure_builtin_prompts():
    """创建内置 Prompt 模板"""
    builtins = [
        {
            "name": "default",
            "description": "通用智能助手，日常对话、问答、写作",
            "system_prompt": "你是一个智能助手，请用中文回答用户的问题。回答要准确、简洁、有条理。",
            "user_prompt_template": None,
        },
        {
            "name": "code_review",
            "description": "代码审查助手，分析代码质量、发现潜在问题",
            "system_prompt": "你是一位资深软件工程师，擅长代码审查。请从代码质量、安全性、性能、可维护性等方面分析给出的代码，指出潜在问题并给出改进建议。",
            "user_prompt_template": "请审查以下 {{language}} 代码：\n```{{language}}\n{{code}}\n```\n关注：{{focus_areas}}",
        },
        {
            "name": "translator",
            "description": "中英翻译助手",
            "system_prompt": "你是专业翻译。请将输入内容准确翻译，保留原文格式和标点。如需解释术语，加括号标注。",
            "user_prompt_template": "请将以下内容翻译成{{target_language}}：\n\n{{text}}",
        },
        {
            "name": "summarizer",
            "description": "文本摘要助手，提取关键信息",
            "system_prompt": "你擅长文本摘要和信息提取。请用简洁的语言总结核心内容，提取关键要点。",
            "user_prompt_template": "请总结以下内容，提取关键信息：\n\n{{text}}",
        },
    ]

    async with async_session() as session:

        from app.models.user import PromptTemplate

        for bt in builtins:
            result = await session.execute(
                select(PromptTemplate).where(PromptTemplate.name == bt["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(PromptTemplate(
                    name=bt["name"],
                    description=bt["description"],
                    system_prompt=bt["system_prompt"],
                    user_prompt_template=bt["user_prompt_template"],
                    is_builtin=True,
                ))
        await session.commit()


async def _ensure_model_configs():
    """从 config.yaml 初始化模型配置到数据库"""
    from app.models.user import ModelConfig
    from app.services.crypto import encrypt_key

    settings = get_settings()
    jwt_secret = settings.get("auth", {}).get("secret_key")
    if not jwt_secret or jwt_secret == "change-me-in-production":
        raise RuntimeError("JWT secret 未配置或使用默认值，请设置 .env 中的 JWT_SECRET")

    async with async_session() as session:
        result = await session.execute(select(ModelConfig).order_by(ModelConfig.display_order, ModelConfig.id))
        existing_models = result.scalars().all()
        existing = {mc.model_id for mc in existing_models}
        next_order = max((mc.display_order for mc in existing_models), default=-1) + 1

        for index, mc in enumerate(existing_models):
            if mc.display_order is None:
                mc.display_order = index

        for index, m in enumerate(settings.get("models", [])):
            if m["id"] in existing:
                continue

            # Resolve API key
            raw_key = m.get("api_key", "")
            if raw_key.startswith("${") and raw_key.endswith("}"):
                env_var = raw_key[2:-1]
                raw_key = os.environ.get(env_var, "")

            encrypted_key = encrypt_key(raw_key, jwt_secret) if raw_key else None

            mc = ModelConfig(
                display_order=next_order if next_order > index else index,
                model_id=m["id"],
                name=m["name"],
                provider=m.get("adapter", "openai_compatible"),
                api_base=m["base_url"],
                encrypted_api_key=encrypted_key,
                llm_model=m.get("model", m["id"]),
                max_tokens=m.get("max_tokens", 4096),
                temperature=m.get("temperature", 0.7),
                enabled=m.get("enabled", True),
                deleted_by_user=False,
                last_test_status="unknown",
            )
            session.add(mc)
            next_order += 1

        await session.commit()


DEFAULT_SKILL_CONFIGS = [
    {
        "skill_id": "docx-to-markdown",
        "name": "DOCX 转 Markdown",
        "description": "将 Word 需求文档转换为 Markdown，提取图片并处理嵌入表格，是所有审查模式的输入预处理能力。",
        "local_path": "skills/docx-to-markdown",
        "display_order": 1,
    },
    {
        "skill_id": "prd-overview-classify",
        "name": "需求概览与分类",
        "description": "识别文档类型、版本号、演进链和文档间依赖，为后续逐篇分析和体系评审提供结构化索引。",
        "local_path": "skills/prd-overview-classify",
        "display_order": 2,
    },
    {
        "skill_id": "prd-per-analysis",
        "name": "逐篇需求分析",
        "description": "按核心问题、分类、边界、边界外问题、规范缺失、关键参数、专家意见评审和质量评分等维度审查单篇需求。",
        "local_path": "skills/prd-per-analysis",
        "display_order": 3,
    },
    {
        "skill_id": "system-review",
        "name": "体系 Review",
        "description": "对需求集进行业务价值、体系架构、竞争定位、产品策略、技术演进、PM评估和行动计划七维度审查。",
        "local_path": "skills/system-review",
        "display_order": 4,
    },
    {
        "skill_id": "requirement-insights",
        "name": "需求洞察与缺口分析",
        "description": "追踪跨版本边界外问题收敛情况，生成覆盖矩阵和下一阶段需求缺口建议。",
        "local_path": "skills/requirement-insights",
        "display_order": 5,
    },
    {
        "skill_id": "report-generator",
        "name": "报告与 PRD 生成",
        "description": "汇总上游 Skills 的结构化结果，生成审查报告、PM建议或基于缺口的 PRD 草稿。",
        "local_path": "skills/report-generator",
        "display_order": 6,
    },
]


async def _ensure_skill_configs():
    """确保管理后台可展示 6 个内置 Skills。"""
    async with async_session() as session:
        result = await session.execute(select(SkillConfig))
        existing = {skill.skill_id: skill for skill in result.scalars().all()}

        for item in DEFAULT_SKILL_CONFIGS:
            skill = existing.get(item["skill_id"])
            if skill is None:
                session.add(SkillConfig(**item, is_builtin=True))
            else:
                skill.name = item["name"]
                skill.description = item["description"]
                skill.local_path = item["local_path"]
                skill.display_order = item["display_order"]
                skill.is_builtin = True

        await session.commit()


async def _cleanup_zombie_tasks():
    """Mark running/pending tasks as failed — they can't resume after a server restart."""
    from app.models.review import ReviewTask

    async with async_session() as session:
        result = await session.execute(
            select(ReviewTask).where(ReviewTask.status.in_(["running", "pending"]))
        )
        zombies = result.scalars().all()
        if zombies:
            for z in zombies:
                _mark_zombie_task_failed(z)
            await session.commit()
            print(f"[INIT] 清理 {len(zombies)} 个僵尸任务（running/pending → failed）")


def _mark_zombie_task_failed(task) -> dict:
    """Mark a task interrupted by process restart as a terminal failed task."""
    try:
        step_statuses = json.loads(task.step_statuses) if task.step_statuses else {}
    except (TypeError, json.JSONDecodeError):
        step_statuses = {}

    current_step = getattr(task, "current_step", None)
    if current_step is not None:
        step_statuses[str(current_step)] = "failed"

    task.status = "failed"
    task.completed_at = now_cn()
    task.step_statuses = json.dumps(step_statuses, ensure_ascii=False)
    return step_statuses


async def _ensure_default_workspace():
    """确保默认 workspace 存在，并将 admin 加入为 owner；将旧项目归入默认空间。"""
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember

    async with async_session() as session:
        result = await session.execute(
            select(Workspace).where(Workspace.is_default == True)
        )
        ws = result.scalar_one_or_none()

        # 兼容旧数据：如果按 is_default 找不到，尝试按旧名称查找并标记
        if ws is None:
            legacy_result = await session.execute(
                select(Workspace).where(Workspace.name == "默认空间")
            )
            ws = legacy_result.scalar_one_or_none()
            if ws is not None:
                ws.is_default = True
                await session.flush()
                logger.info("[INIT] 旧默认 workspace 已标记 is_default=True")

        if ws is None:
            admin_result = await session.execute(select(User).where(User.role == "admin"))
            admin = admin_result.scalar_one_or_none()
            ws = Workspace(
                name="默认空间",
                description="系统默认团队空间，旧项目自动归入此处",
                is_default=True,
                created_by=admin.id if admin else None,
                status="active",
            )
            session.add(ws)
            await session.flush()
            if admin:
                session.add(WorkspaceMember(
                    workspace_id=ws.id,
                    user_id=admin.id,
                    role="owner",
                    status="active",
                ))
            await session.commit()
            logger.info("[INIT] 默认 workspace 已创建")

        # 将所有无 workspace_id 的旧项目归入默认空间
        await _migrate_projects_to_default_workspace(ws.id)


async def _migrate_projects_to_default_workspace(default_workspace_id: int):
    """为所有现有 ReviewProject 自动归入默认 workspace。"""
    from app.models.review import ReviewProject

    async with async_session() as session:
        result = await session.execute(
            select(ReviewProject).where(ReviewProject.workspace_id.is_(None))
        )
        unassigned = result.scalars().all()
        if unassigned:
            for p in unassigned:
                p.workspace_id = default_workspace_id
            await session.commit()
            logger.info(f"[INIT] {len(unassigned)} 个旧项目已归入默认 workspace")
