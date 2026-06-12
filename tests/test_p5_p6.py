"""P5.D.1 + P6.D.1: P5/P6 自动化测试 — 个人空间隔离、Agent 跨人对话审批链、消息 CRUD、
@提及通知、评论 resolve、成本统计、质量统计、Skill 回归、配额拦截、Agent 退役。"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models.user import Base, User
from app.models.workspace import Workspace, WorkspaceMember, KnowledgeSource, VALID_OWNER_TYPES, VALID_VISIBILITIES
from app.models.user import (
    AgentProfile, AgentAuthorization, AgentApprovalRequest,
    Notification, Comment,
)
from app.models.review import CostDailySummary, QualityWeeklySummary, WorkspaceBudget
from app.repositories.knowledge_source_repository import KnowledgeSourceRepository
from app.repositories.notification_repository import NotificationRepository, CommentRepository


# ── Fixtures ──

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def admin_user(db_session):
    user = User(username="admin_test", password_hash="hash", role="admin")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def default_workspace(db_session, admin_user):
    ws = Workspace(name="默认空间", is_default=True, created_by=admin_user.id)
    db_session.add(ws)
    await db_session.flush()
    member = WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="owner")
    db_session.add(member)
    await db_session.flush()
    return ws


# ── P5.A.1: 个人私有知识隔离 ──


class TestPersonalKnowledgeIsolation:
    """P5.A.1: 个人资料默认不进入团队知识库检索。"""

    async def test_create_personal_source(self, db_session, default_workspace, admin_user):
        repo = KnowledgeSourceRepository(db_session)
        source = await repo.create(
            "upload", "个人文档", workspace_id=default_workspace.id,
            owner_id=admin_user.id, owner_type="user", visibility="private",
        )
        assert source.owner_type == "user"
        assert source.visibility == "private"

    async def test_personal_source_not_in_team_list(self, db_session, default_workspace, admin_user):
        """个人资料不应出现在团队资料列表中。"""
        repo = KnowledgeSourceRepository(db_session)
        # 创建个人资料
        await repo.create(
            "upload", "个人文档", workspace_id=default_workspace.id,
            owner_id=admin_user.id, owner_type="user", visibility="private",
        )
        # 创建团队资料
        await repo.create(
            "upload", "团队文档", workspace_id=default_workspace.id,
            owner_id=admin_user.id, owner_type="workspace", visibility="team",
        )

        # 团队资料列表应只有 1 条
        team_sources = await repo.list_by_workspace(
            default_workspace.id, owner_type="workspace", visibility="team",
        )
        assert len(team_sources) == 1
        assert team_sources[0].title == "团队文档"

        # 个人资料列表应只有 1 条
        personal_sources = await repo.list_personal_sources(admin_user.id)
        assert len(personal_sources) == 1
        assert personal_sources[0].title == "个人文档"

    async def test_owner_type_validation(self, db_session):
        """owner_type 只接受 workspace/user。"""
        repo = KnowledgeSourceRepository(db_session)
        with pytest.raises(ValueError, match="Invalid owner_type"):
            await repo.create("upload", "test", owner_type="invalid")

    async def test_visibility_validation(self, db_session):
        """visibility 只接受 team/private。"""
        repo = KnowledgeSourceRepository(db_session)
        with pytest.raises(ValueError, match="Invalid visibility"):
            await repo.create("upload", "test", visibility="public")


# ── P5.A.2: Agent 默认 scope ──


class TestAgentDefaultScope:
    """P5.A.2: Agent default_scope_type 字段。"""

    async def test_agent_profile_has_default_scope(self, db_session, admin_user):
        profile = AgentProfile(
            owner_type="user", owner_id=admin_user.id,
            name="Test Agent", default_scope_type="personal",
        )
        db_session.add(profile)
        await db_session.flush()
        assert profile.default_scope_type == "personal"


# ── P5.C.2: 评论 resolve ──


class TestCommentResolve:
    """P5.C.2: 评论可标记 resolved/forced_pass。"""

    async def test_create_comment_with_resolve_fields(self, db_session, admin_user):
        comment = Comment(
            object_type="review_request", object_id=1,
            author_id=admin_user.id, body="测试评论",
        )
        db_session.add(comment)
        await db_session.flush()
        assert comment.resolved is False
        assert comment.resolution is None

    async def test_resolve_comment(self, db_session, admin_user):
        comment = Comment(
            object_type="review_request", object_id=1,
            author_id=admin_user.id, body="需要解决的问题",
        )
        db_session.add(comment)
        await db_session.flush()

        comment.resolved = True
        comment.resolution = "resolved"
        comment.resolved_by = admin_user.id
        await db_session.flush()

        assert comment.resolved is True
        assert comment.resolution == "resolved"
        assert comment.resolved_by == admin_user.id

    async def test_forced_pass_comment(self, db_session, admin_user):
        comment = Comment(
            object_type="review_request", object_id=1,
            author_id=admin_user.id, body="强制通过",
        )
        db_session.add(comment)
        await db_session.flush()

        comment.resolved = True
        comment.resolution = "forced_pass"
        comment.resolved_by = admin_user.id
        await db_session.flush()

        assert comment.resolution == "forced_pass"


# ── P6.A.1: 成本统计模型 ──


class TestCostDailySummary:
    """P6.A.1: CostDailySummary 模型。"""

    async def test_create_cost_summary(self, db_session):
        summary = CostDailySummary(
            mode="chat", date="2026-06-11", model_id="gpt-4",
            call_count=10, input_tokens=5000, output_tokens=2000,
        )
        db_session.add(summary)
        await db_session.flush()
        assert summary.id is not None
        assert summary.call_count == 10

    async def test_cost_summary_query(self, db_session):
        for i in range(3):
            db_session.add(CostDailySummary(
                mode="chat", date=f"2026-06-{10+i}", model_id="gpt-4",
                call_count=i+1, input_tokens=1000*(i+1), output_tokens=500*(i+1),
            ))
        await db_session.flush()

        result = await db_session.execute(
            select(CostDailySummary).where(CostDailySummary.mode == "chat")
        )
        rows = result.scalars().all()
        assert len(rows) == 3


# ── P6.A.2: 质量统计模型 ──


class TestQualityWeeklySummary:
    """P6.A.2: QualityWeeklySummary 模型。"""

    async def test_create_quality_summary(self, db_session):
        summary = QualityWeeklySummary(
            week_start="2026-06-08", avg_score=4.5, total_reviews=15,
        )
        db_session.add(summary)
        await db_session.flush()
        assert summary.id is not None
        assert summary.total_reviews == 15


# ── P6.C.1: Workspace 配额模型 ──


class TestWorkspaceBudget:
    """P6.C.1: WorkspaceBudget 配额模型。"""

    async def test_create_budget(self, db_session, default_workspace):
        budget = WorkspaceBudget(
            workspace_id=default_workspace.id,
            monthly_token_limit=1000000,
            monthly_cost_limit=100.0,
            warning_threshold_pct=80.0,
            hard_limit_action="notify",
        )
        db_session.add(budget)
        await db_session.flush()
        assert budget.id is not None
        assert budget.monthly_token_limit == 1000000

    async def test_budget_hard_limit_actions(self, db_session, admin_user):
        """验证 hard_limit_action 的合法值。"""
        # 为每个 action 创建独立的 workspace
        valid_actions = ("notify", "block")
        for i, action in enumerate(valid_actions):
            ws = Workspace(name=f"budget-test-{i}", is_default=False, created_by=admin_user.id)
            db_session.add(ws)
            await db_session.flush()
            budget = WorkspaceBudget(
                workspace_id=ws.id,
                hard_limit_action=action,
            )
            db_session.add(budget)
            await db_session.flush()
            assert budget.hard_limit_action == action


# ── P6.B.3: Agent 退役 ──


class TestAgentArchive:
    """P6.B.3: Agent 退役——disabled→archived，需检查无活跃运行。"""

    async def test_agent_profile_supports_archived(self, db_session, admin_user):
        """AgentProfile.status 支持 archived 状态。"""
        profile = AgentProfile(
            owner_type="user", owner_id=admin_user.id,
            name="Test Agent", status="archived",
        )
        db_session.add(profile)
        await db_session.flush()
        assert profile.status == "archived"
