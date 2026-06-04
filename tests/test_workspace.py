"""P0.A.1~A.6 — Workspace 全量模型与 Repository 测试。

验收标准：
- P0.A.1: Workspace 表创建、迁移幂等、种子数据 1 条默认 workspace
- P0.A.2: WorkspaceMember 表创建、外键约束、角色枚举校验
- P0.A.3: KnowledgeSource 表创建、content_hash 自动计算、版本号递增
- P0.A.4: ReviewProject 新增 workspace_id 外键（nullable，旧数据兼容）
- P0.A.5: project_source_refs 关联表、快照版本号记录
- P0.A.6: 数据迁移脚本（旧项目自动归入默认 workspace）
"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.user import Base, User
from app.models.review import ReviewProject
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    KnowledgeSource,
    ProjectSourceRef,
    VALID_MEMBER_ROLES,
    VALID_WORKSPACE_STATUSES,
    VALID_SOURCE_TYPES,
    VALID_SOURCE_STATUSES,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.repositories.knowledge_source_repository import KnowledgeSourceRepository, ProjectSourceRefRepository
from app.services.auth import hash_password


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def admin_user(db_session):
    admin = User(username="admin", password_hash=hash_password("admin123"), role="admin")
    db_session.add(admin)
    await db_session.flush()
    await db_session.refresh(admin)
    return admin


@pytest_asyncio.fixture
async def normal_user(db_session):
    user = User(username="testuser", password_hash=hash_password("test123"), role="user")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def default_workspace(db_session, admin_user):
    ws_repo = WorkspaceRepository(db_session)
    ws = await ws_repo.create("默认空间", description="系统默认团队空间", created_by=admin_user.id)
    await ws_repo.add_member(ws.id, admin_user.id, role="owner")
    return ws


# ── P0.A.1: Workspace 表 ──


class TestWorkspaceModel:
    async def test_table_created(self, db_engine):
        async with db_engine.begin() as conn:
            await conn.execute(select(Workspace))
            await conn.execute(select(WorkspaceMember))

    async def test_create_workspace(self, db_session, admin_user):
        repo = WorkspaceRepository(db_session)
        ws = await repo.create("测试空间", description="用于测试", created_by=admin_user.id)
        assert ws.id is not None
        assert ws.name == "测试空间"
        assert ws.status == "active"

    async def test_get_by_id(self, db_session, admin_user):
        repo = WorkspaceRepository(db_session)
        ws = await repo.create("空间A", created_by=admin_user.id)
        found = await repo.get_by_id(ws.id)
        assert found is not None
        assert found.name == "空间A"

    async def test_get_by_id_not_found(self, db_session):
        repo = WorkspaceRepository(db_session)
        assert await repo.get_by_id(999) is None

    async def test_list_all(self, db_session, admin_user):
        repo = WorkspaceRepository(db_session)
        await repo.create("空间1", created_by=admin_user.id)
        await repo.create("空间2", created_by=admin_user.id)
        assert len(await repo.list_all()) == 2

    async def test_list_all_excludes_archived(self, db_session, admin_user):
        repo = WorkspaceRepository(db_session)
        ws1 = await repo.create("活跃空间", created_by=admin_user.id)
        ws2 = await repo.create("待归档空间", created_by=admin_user.id)
        await repo.archive(ws2.id)
        all_ws = await repo.list_all()
        assert len(all_ws) == 1
        assert all_ws[0].name == "活跃空间"

    async def test_archive_workspace(self, db_session, admin_user):
        repo = WorkspaceRepository(db_session)
        ws = await repo.create("待归档", created_by=admin_user.id)
        archived = await repo.archive(ws.id)
        assert archived.status == "archived"

    async def test_archive_not_found(self, db_session):
        repo = WorkspaceRepository(db_session)
        assert await repo.archive(999) is None

    async def test_get_default_workspace(self, db_session, admin_user):
        repo = WorkspaceRepository(db_session)
        await repo.create("默认空间", created_by=admin_user.id)
        default = await repo.get_default()
        assert default is not None
        assert default.name == "默认空间"

    async def test_get_default_not_exists(self, db_session):
        repo = WorkspaceRepository(db_session)
        assert await repo.get_default() is None


# ── P0.A.2: WorkspaceMember 表 ──


class TestWorkspaceMemberModel:
    async def test_add_member(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("团队空间", created_by=admin_user.id)
        member = await ws_repo.add_member(ws.id, normal_user.id, role="member")
        assert member.workspace_id == ws.id
        assert member.user_id == normal_user.id
        assert member.role == "member"
        assert member.status == "active"

    async def test_add_owner(self, db_session, admin_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("空间", created_by=admin_user.id)
        member = await ws_repo.add_member(ws.id, admin_user.id, role="owner")
        assert member.role == "owner"

    async def test_valid_roles(self):
        assert set(VALID_MEMBER_ROLES) == {"owner", "admin", "member", "viewer"}

    async def test_valid_workspace_statuses(self):
        assert set(VALID_WORKSPACE_STATUSES) == {"active", "archived"}

    async def test_get_member(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("空间", created_by=admin_user.id)
        await ws_repo.add_member(ws.id, normal_user.id, role="member")
        found = await ws_repo.get_member(ws.id, normal_user.id)
        assert found.role == "member"

    async def test_get_member_not_found(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("空间", created_by=admin_user.id)
        assert await ws_repo.get_member(ws.id, normal_user.id) is None

    async def test_list_members(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("空间", created_by=admin_user.id)
        await ws_repo.add_member(ws.id, admin_user.id, role="owner")
        await ws_repo.add_member(ws.id, normal_user.id, role="member")
        members = await ws_repo.list_members(ws.id)
        assert len(members) == 2
        assert {m.role for m in members} == {"owner", "member"}

    async def test_update_member_role(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("空间", created_by=admin_user.id)
        await ws_repo.add_member(ws.id, normal_user.id, role="member")
        updated = await ws_repo.update_member_role(ws.id, normal_user.id, role="admin")
        assert updated.role == "admin"

    async def test_update_member_role_not_found(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("空间", created_by=admin_user.id)
        assert await ws_repo.update_member_role(ws.id, normal_user.id, role="admin") is None

    async def test_remove_member_soft_delete(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("空间", created_by=admin_user.id)
        await ws_repo.add_member(ws.id, normal_user.id, role="member")
        assert await ws_repo.remove_member(ws.id, normal_user.id) is True
        assert await ws_repo.get_member(ws.id, normal_user.id) is None

    async def test_remove_member_not_found(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws = await ws_repo.create("空间", created_by=admin_user.id)
        assert await ws_repo.remove_member(ws.id, normal_user.id) is False

    async def test_get_user_workspaces(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws1 = await ws_repo.create("空间1", created_by=admin_user.id)
        ws2 = await ws_repo.create("空间2", created_by=admin_user.id)
        await ws_repo.add_member(ws1.id, normal_user.id, role="member")
        await ws_repo.add_member(ws2.id, normal_user.id, role="viewer")
        user_ws = await ws_repo.get_user_workspaces(normal_user.id)
        assert len(user_ws) == 2
        assert {ws.name for ws in user_ws} == {"空间1", "空间2"}

    async def test_get_user_workspaces_excludes_archived(self, db_session, admin_user, normal_user):
        ws_repo = WorkspaceRepository(db_session)
        ws1 = await ws_repo.create("活跃空间", created_by=admin_user.id)
        ws2 = await ws_repo.create("归档空间", created_by=admin_user.id)
        await ws_repo.add_member(ws1.id, normal_user.id, role="member")
        await ws_repo.add_member(ws2.id, normal_user.id, role="member")
        await ws_repo.archive(ws2.id)
        user_ws = await ws_repo.get_user_workspaces(normal_user.id)
        assert len(user_ws) == 1
        assert user_ws[0].name == "活跃空间"


# ── P0.A.3: KnowledgeSource 表 ──


class TestKnowledgeSourceModel:
    async def test_table_created(self, db_engine):
        async with db_engine.begin() as conn:
            await conn.execute(select(KnowledgeSource))

    async def test_valid_source_types(self):
        assert set(VALID_SOURCE_TYPES) == {"upload", "lark_url", "api"}

    async def test_valid_source_statuses(self):
        assert set(VALID_SOURCE_STATUSES) == {"active", "archived", "processing", "failed"}

    async def test_create_source(self, db_session, default_workspace, admin_user):
        repo = KnowledgeSourceRepository(db_session)
        source = await repo.create(
            workspace_id=default_workspace.id,
            source_type="upload",
            title="需求规格说明书 V1.0",
            filename="spec.docx",
            content_hash="abc123",
            owner_id=admin_user.id,
        )
        assert source.id is not None
        assert source.workspace_id == default_workspace.id
        assert source.source_type == "upload"
        assert source.title == "需求规格说明书 V1.0"
        assert source.filename == "spec.docx"
        assert source.content_hash == "abc123"
        assert source.version == 1
        assert source.owner_id == admin_user.id
        assert source.status == "active"

    async def test_create_with_metadata(self, db_session, default_workspace, admin_user):
        import json
        repo = KnowledgeSourceRepository(db_session)
        meta = json.dumps({"tags": ["PRD", "V1"], "pages": 12})
        source = await repo.create(
            workspace_id=default_workspace.id,
            source_type="upload",
            title="带标签的文档",
            metadata_json=meta,
            owner_id=admin_user.id,
        )
        assert source.metadata_json is not None
        parsed = json.loads(source.metadata_json)
        assert parsed["tags"] == ["PRD", "V1"]

    async def test_version_increments_on_update(self, db_session, default_workspace, admin_user):
        repo = KnowledgeSourceRepository(db_session)
        source = await repo.create(
            workspace_id=default_workspace.id,
            source_type="upload",
            title="V1 文档",
            content_hash="hash_v1",
            owner_id=admin_user.id,
        )
        assert source.version == 1

        updated = await repo.update_version(source.id, content_hash="hash_v2")
        assert updated.version == 2
        assert updated.content_hash == "hash_v2"

    async def test_update_version_not_found(self, db_session):
        repo = KnowledgeSourceRepository(db_session)
        assert await repo.update_version(999, content_hash="x") is None

    async def test_list_by_workspace(self, db_session, default_workspace, admin_user):
        repo = KnowledgeSourceRepository(db_session)
        await repo.create(default_workspace.id, "upload", "文档1", owner_id=admin_user.id)
        await repo.create(default_workspace.id, "upload", "文档2", owner_id=admin_user.id)
        await repo.create(default_workspace.id, "lark_url", "飞书文档", owner_id=admin_user.id)

        all_sources = await repo.list_by_workspace(default_workspace.id)
        assert len(all_sources) == 3

        uploads = await repo.list_by_workspace(default_workspace.id, source_type="upload")
        assert len(uploads) == 2
        assert all(s.source_type == "upload" for s in uploads)

    async def test_list_by_workspace_pagination(self, db_session, default_workspace, admin_user):
        repo = KnowledgeSourceRepository(db_session)
        for i in range(5):
            await repo.create(default_workspace.id, "upload", f"文档{i}", owner_id=admin_user.id)

        page1 = await repo.list_by_workspace(default_workspace.id, limit=2, offset=0)
        page2 = await repo.list_by_workspace(default_workspace.id, limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2

    async def test_count_by_workspace(self, db_session, default_workspace, admin_user):
        repo = KnowledgeSourceRepository(db_session)
        await repo.create(default_workspace.id, "upload", "文档1", owner_id=admin_user.id)
        await repo.create(default_workspace.id, "upload", "文档2", owner_id=admin_user.id)
        count = await repo.count_by_workspace(default_workspace.id)
        assert count == 2

    async def test_archive_source(self, db_session, default_workspace, admin_user):
        repo = KnowledgeSourceRepository(db_session)
        source = await repo.create(default_workspace.id, "upload", "待归档", owner_id=admin_user.id)
        archived = await repo.archive(source.id)
        assert archived.status == "archived"

        # 归档后列表不含
        active = await repo.list_by_workspace(default_workspace.id)
        assert len(active) == 0

        # 归档列表含
        archived_list = await repo.list_by_workspace(default_workspace.id, status="archived")
        assert len(archived_list) == 1

    async def test_set_status(self, db_session, default_workspace, admin_user):
        repo = KnowledgeSourceRepository(db_session)
        source = await repo.create(default_workspace.id, "upload", "处理中", owner_id=admin_user.id)
        processing = await repo.set_status(source.id, "processing")
        assert processing.status == "processing"

    async def test_get_by_id_not_found(self, db_session):
        repo = KnowledgeSourceRepository(db_session)
        assert await repo.get_by_id(999) is None


# ── P0.A.4: ReviewProject workspace_id ──


class TestReviewProjectWorkspaceId:
    async def test_project_with_workspace_id(self, db_session, default_workspace, admin_user):
        project = ReviewProject(
            name="测试项目",
            description="有 workspace 的项目",
            created_by=admin_user.id,
            workspace_id=default_workspace.id,
        )
        db_session.add(project)
        await db_session.flush()
        await db_session.refresh(project)
        assert project.workspace_id == default_workspace.id

    async def test_project_without_workspace_id_nullable(self, db_session, admin_user):
        """旧项目无 workspace 时 workspace_id 为 None，仍可正常读写。"""
        project = ReviewProject(
            name="旧项目",
            description="无 workspace 的项目",
            created_by=admin_user.id,
        )
        db_session.add(project)
        await db_session.flush()
        await db_session.refresh(project)
        assert project.workspace_id is None

    async def test_project_source_refs_relationship(self, db_session, default_workspace, admin_user):
        """ReviewProject.workspace_id 字段可正常写入和读取。"""
        project = ReviewProject(
            name="有空间的项目",
            created_by=admin_user.id,
            workspace_id=default_workspace.id,
        )
        db_session.add(project)
        await db_session.flush()
        await db_session.refresh(project)
        assert project.workspace_id == default_workspace.id


# ── P0.A.5: project_source_refs 关联表 ──


class TestProjectSourceRef:
    async def test_table_created(self, db_engine):
        async with db_engine.begin() as conn:
            await conn.execute(select(ProjectSourceRef))

    async def test_add_ref(self, db_session, default_workspace, admin_user):
        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(default_workspace.id, "upload", "资料", owner_id=admin_user.id)

        project = ReviewProject(name="项目", created_by=admin_user.id, workspace_id=default_workspace.id)
        db_session.add(project)
        await db_session.flush()
        await db_session.refresh(project)

        ref_repo = ProjectSourceRefRepository(db_session)
        ref = await ref_repo.add_ref(project.id, source.id, ref_type="context")
        assert ref.id is not None
        assert ref.project_id == project.id
        assert ref.source_id == source.id
        assert ref.ref_type == "context"
        assert ref.snapshot_version is None

    async def test_ref_types(self, db_session, default_workspace, admin_user):
        """context / reference / background 三种引用类型。"""
        ks_repo = KnowledgeSourceRepository(db_session)
        s1 = await ks_repo.create(default_workspace.id, "upload", "资料1", owner_id=admin_user.id)
        s2 = await ks_repo.create(default_workspace.id, "upload", "资料2", owner_id=admin_user.id)
        s3 = await ks_repo.create(default_workspace.id, "upload", "资料3", owner_id=admin_user.id)

        project = ReviewProject(name="项目", created_by=admin_user.id, workspace_id=default_workspace.id)
        db_session.add(project)
        await db_session.flush()
        await db_session.refresh(project)

        ref_repo = ProjectSourceRefRepository(db_session)
        await ref_repo.add_ref(project.id, s1.id, ref_type="context")
        await ref_repo.add_ref(project.id, s2.id, ref_type="reference")
        await ref_repo.add_ref(project.id, s3.id, ref_type="background")

        refs = await ref_repo.list_by_project(project.id)
        assert len(refs) == 3
        assert {r.ref_type for r in refs} == {"context", "reference", "background"}

    async def test_remove_ref(self, db_session, default_workspace, admin_user):
        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(default_workspace.id, "upload", "资料", owner_id=admin_user.id)

        project = ReviewProject(name="项目", created_by=admin_user.id, workspace_id=default_workspace.id)
        db_session.add(project)
        await db_session.flush()
        await db_session.refresh(project)

        ref_repo = ProjectSourceRefRepository(db_session)
        ref = await ref_repo.add_ref(project.id, source.id)
        assert await ref_repo.remove_ref(ref.id) is True
        assert await ref_repo.list_by_project(project.id) == []

    async def test_remove_ref_not_found(self, db_session):
        ref_repo = ProjectSourceRefRepository(db_session)
        assert await ref_repo.remove_ref(999) is False

    async def test_freeze_snapshot(self, db_session, default_workspace, admin_user):
        """审查启动时冻结引用资料的 snapshot_version。"""
        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(default_workspace.id, "upload", "资料", content_hash="h1", owner_id=admin_user.id)
        await ks_repo.update_version(source.id, content_hash="h2")
        # source 现在是 v2

        project = ReviewProject(name="项目", created_by=admin_user.id, workspace_id=default_workspace.id)
        db_session.add(project)
        await db_session.flush()
        await db_session.refresh(project)

        ref_repo = ProjectSourceRefRepository(db_session)
        await ref_repo.add_ref(project.id, source.id, ref_type="context")
        # snapshot_version is None initially

        refs = await ref_repo.freeze_snapshot(project.id)
        assert len(refs) == 1
        assert refs[0].snapshot_version == 2  # 冻结当前版本号

    async def test_freeze_snapshot_idempotent(self, db_session, default_workspace, admin_user):
        """已有 snapshot_version 的引用不再覆盖。"""
        ks_repo = KnowledgeSourceRepository(db_session)
        source = await ks_repo.create(default_workspace.id, "upload", "资料", owner_id=admin_user.id)

        project = ReviewProject(name="项目", created_by=admin_user.id, workspace_id=default_workspace.id)
        db_session.add(project)
        await db_session.flush()
        await db_session.refresh(project)

        ref_repo = ProjectSourceRefRepository(db_session)
        ref = await ref_repo.add_ref(project.id, source.id, snapshot_version=1)

        # 再次冻结，已有 snapshot_version=1 不变
        await ref_repo.freeze_snapshot(project.id)
        await db_session.refresh(ref)
        assert ref.snapshot_version == 1


# ── P0.A.6: 数据迁移（旧项目归入默认 workspace）─


class TestProjectMigration:
    async def test_migrate_unassigned_projects(self, db_engine):
        """无 workspace_id 的旧项目自动归入默认空间。"""
        session_maker = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_maker() as session:
            admin = User(username="admin", password_hash=hash_password("admin123"), role="admin")
            session.add(admin)
            await session.flush()

            # 创建默认 workspace
            ws = Workspace(name="默认空间", description="系统默认", created_by=admin.id, status="active")
            session.add(ws)
            await session.flush()
            session.add(WorkspaceMember(workspace_id=ws.id, user_id=admin.id, role="owner", status="active"))

            # 创建旧项目（无 workspace_id）
            p1 = ReviewProject(name="旧项目1", created_by=admin.id)
            p2 = ReviewProject(name="旧项目2", created_by=admin.id)
            session.add_all([p1, p2])
            await session.commit()

        # 执行迁移
        async with session_maker() as session:
            result = await session.execute(
                select(ReviewProject).where(ReviewProject.workspace_id.is_(None))
            )
            unassigned = result.scalars().all()
            assert len(unassigned) == 2

            for p in unassigned:
                p.workspace_id = ws.id
            await session.commit()

        # 验证
        async with session_maker() as session:
            result = await session.execute(select(ReviewProject))
            projects = result.scalars().all()
            assert all(p.workspace_id == ws.id for p in projects)

    async def test_already_assigned_projects_not_affected(self, db_engine):
        """已有 workspace_id 的项目不受迁移影响。"""
        session_maker = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_maker() as session:
            admin = User(username="admin", password_hash=hash_password("admin123"), role="admin")
            session.add(admin)
            await session.flush()

            ws1 = Workspace(name="空间A", created_by=admin.id, status="active")
            ws2 = Workspace(name="空间B", created_by=admin.id, status="active")
            session.add_all([ws1, ws2])
            await session.flush()

            # 已有 workspace 的项目
            p1 = ReviewProject(name="已有空间项目", created_by=admin.id, workspace_id=ws1.id)
            p2 = ReviewProject(name="无空间项目", created_by=admin.id)
            session.add_all([p1, p2])
            await session.commit()

        # 迁移
        async with session_maker() as session:
            result = await session.execute(
                select(ReviewProject).where(ReviewProject.workspace_id.is_(None))
            )
            for p in result.scalars().all():
                p.workspace_id = ws2.id
            await session.commit()

        # 验证
        async with session_maker() as session:
            result = await session.execute(select(ReviewProject).where(ReviewProject.name == "已有空间项目"))
            p = result.scalar_one()
            assert p.workspace_id == ws1.id  # 未被改变


# ── 默认 workspace 种子数据 ──


class TestDefaultWorkspaceSeed:
    async def test_ensure_default_workspace_creates_seed(self, db_engine):
        session_maker = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_maker() as session:
            session.add(User(username="admin", password_hash=hash_password("admin123"), role="admin"))
            await session.commit()

        async with session_maker() as session:
            result = await session.execute(select(Workspace).where(Workspace.name == "默认空间"))
            ws = result.scalar_one_or_none()
            if ws is None:
                admin_result = await session.execute(select(User).where(User.role == "admin"))
                admin = admin_result.scalar_one_or_none()
                ws = Workspace(
                    name="默认空间",
                    description="系统默认团队空间，旧项目自动归入此处",
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

        async with session_maker() as session:
            result = await session.execute(select(Workspace).where(Workspace.name == "默认空间"))
            ws = result.scalar_one_or_none()
            assert ws is not None
            assert ws.status == "active"

            result = await session.execute(
                select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id)
            )
            members = result.scalars().all()
            assert len(members) == 1
            assert members[0].role == "owner"

    async def test_ensure_default_workspace_idempotent(self, db_engine):
        session_maker = async_sessionmaker(db_engine, expire_on_commit=False)

        async with session_maker() as session:
            session.add(User(username="admin", password_hash=hash_password("admin123"), role="admin"))
            await session.commit()

        async def run_seed():
            async with session_maker() as session:
                result = await session.execute(select(Workspace).where(Workspace.name == "默认空间"))
                ws = result.scalar_one_or_none()
                if ws is None:
                    admin_result = await session.execute(select(User).where(User.role == "admin"))
                    admin = admin_result.scalar_one_or_none()
                    ws = Workspace(
                        name="默认空间",
                        description="系统默认团队空间",
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

        await run_seed()
        await run_seed()

        async with session_maker() as session:
            result = await session.execute(select(Workspace).where(Workspace.name == "默认空间"))
            workspaces = list(result.scalars().all())
            assert len(workspaces) == 1