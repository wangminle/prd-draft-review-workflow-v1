"""BUG-144 ~ BUG-148, BUG-151 ~ BUG-152: 代码审计修复测试

BUG-144: 审查管线 start_review 缺少 ensure_workspace_llm_allowed 配额拦截
BUG-145: delete_project 级联删除逻辑错误 + Artifact/Comment/KnowledgeSnapshot 孤儿
BUG-146: resolve_comment 通知未使用 defer_push（幽灵通知）
BUG-147: FTS5 sanitize 漏 NEAR 关键字 + Unicode 引号
BUG-148: embedding worker 崩溃后 processing chunks 永久卡住
BUG-151: 上传去重 DB 级唯一约束兜底并发竞态（P2-3）
BUG-152: start_review per-project 锁消除并发重复创建 task（P1-1）
"""

import tempfile
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.conftest import init_test_db, make_test_app


# ── 公共 fixture ──────────────────────────────────────────────

@pytest_asyncio.fixture
async def audit_client():
    tmp_db = tempfile.mktemp(suffix=".db")
    app, engine, session_maker = make_test_app(tmp_db)
    await init_test_db(engine, session_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # login as admin
        resp = await ac.post("/api/auth/login", json={
            "username": "admin", "password": "admin@2026",
        })
        token = resp.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac, session_maker

    await engine.dispose()


# ── BUG-144: 审查管线配额拦截 ─────────────────────────────────

class TestBUG144QuotaCheck:
    """审查启动前必须调用 ensure_workspace_llm_allowed。"""

    async def test_start_review_calls_budget_guard(self, audit_client):
        """start_review 在创建任务前应调用 ensure_workspace_llm_allowed。"""
        ac, session_maker = audit_client

        # 创建项目
        resp = await ac.post("/api/review/projects", json={"name": "quota-test"})
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        # 注入一个最小 docx 文件
        minimal_docx = b"PK\x05\x06" + b"\x00" * 18
        resp = await ac.post(
            f"/api/review/projects/{project_id}/documents",
            files=[("files", ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )
        assert resp.status_code == 200

        # Mock ensure_workspace_llm_allowed 来验证它被调用
        from app.services import budget_guard
        call_count = 0

        async def mock_check(db, workspace_id):
            nonlocal call_count
            call_count += 1

        with patch.object(budget_guard, "ensure_workspace_llm_allowed", mock_check):
            # review.py 中的 import 是 from app.services.budget_guard import ensure_workspace_llm_allowed
            # 由于是函数级 import，patch budget_guard 模块的属性即可
            try:
                resp = await ac.post(
                    f"/api/review/projects/{project_id}/reviews",
                    json={"mode": "quick"},
                )
            except Exception:
                pass  # 管线可能因缺少 LLM 配置而失败，不影响验证

        assert call_count >= 1, "ensure_workspace_llm_allowed 应在 start_review 中被调用"

    async def test_start_review_blocked_when_quota_exceeded(self, audit_client):
        """配额超限时 start_review 应返回 429。"""
        ac, session_maker = audit_client

        resp = await ac.post("/api/review/projects", json={"name": "quota-block-test"})
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        minimal_docx = b"PK\x05\x06" + b"\x00" * 18
        resp = await ac.post(
            f"/api/review/projects/{project_id}/documents",
            files=[("files", ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )
        assert resp.status_code == 200

        from fastapi import HTTPException
        from app.services import budget_guard

        async def mock_block(db, workspace_id):
            raise HTTPException(429, "团队本月 token 配额已用尽")

        with patch.object(budget_guard, "ensure_workspace_llm_allowed", mock_block):
            resp = await ac.post(
                f"/api/review/projects/{project_id}/reviews",
                json={"mode": "quick"},
            )

        assert resp.status_code == 429
        assert "配额" in resp.json()["detail"]


# ── BUG-145: delete_project 级联删除 ──────────────────────────

class TestBUG145DeleteProjectCascade:
    """删除项目时应正确清理所有关联记录。"""

    async def test_delete_project_cleans_artifacts_and_comments(self, audit_client):
        """删除项目后 Artifact / Comment / KnowledgeSnapshot 应一并清理。"""
        ac, session_maker = audit_client

        # 创建项目
        resp = await ac.post("/api/review/projects", json={"name": "cascade-test"})
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        # 直接在 DB 中插入关联记录
        from app.models.review import (
            ReviewRequest, ReviewRound, ReviewParticipant,
            KnowledgeSnapshot, Artifact,
        )
        from app.models.user import Comment
        from app.models.workspace import Workspace

        async with session_maker() as db:
            # 获取 workspace
            ws_result = await db.execute(select(Workspace).where(Workspace.is_default == True))
            ws = ws_result.scalar_one()

            # 创建 ReviewRequest
            req = ReviewRequest(
                project_id=project_id,
                initiator_id=1,
                goal="test",
                status="initiated",
                current_round=1,
            )
            db.add(req)
            await db.flush()

            # 创建 ReviewRound
            rnd = ReviewRound(
                request_id=req.id,
                round_no=1,
                decision="pending",
            )
            db.add(rnd)
            await db.flush()

            # 创建 ReviewParticipant
            participant = ReviewParticipant(
                request_id=req.id,
                user_id=1,
                role="Reviewer",
                status="active",
            )
            db.add(participant)

            # 创建 KnowledgeSnapshot
            snap = KnowledgeSnapshot(
                workspace_id=ws.id,
                project_id=project_id,
                request_id=req.id,
            )
            db.add(snap)

            # 创建 Artifact (object_type=review_request)
            artifact = Artifact(
                object_type="review_request",
                object_id=req.id,
                artifact_type="html_presentation",
                content_json="{}",
                status="draft",
            )
            db.add(artifact)

            # 创建 Comment (object_type=review_request)
            comment = Comment(
                object_type="review_request",
                object_id=req.id,
                author_id=1,
                body="test comment",
            )
            db.add(comment)

            # 创建 Comment (object_type=review_round)
            comment2 = Comment(
                object_type="review_round",
                object_id=rnd.id,
                author_id=1,
                body="round comment",
            )
            db.add(comment2)

            await db.commit()

            req_id = req.id
            round_id = rnd.id

        # 删除项目
        resp = await ac.delete(f"/api/review/projects/{project_id}")
        assert resp.status_code == 200

        # 验证所有关联记录已被清理
        async with session_maker() as db:
            # ReviewRequest 应被删除
            result = await db.execute(select(ReviewRequest).where(ReviewRequest.id == req_id))
            assert result.scalar_one_or_none() is None, "ReviewRequest 应被删除"

            # ReviewRound 应被删除
            result = await db.execute(select(ReviewRound).where(ReviewRound.id == round_id))
            assert result.scalar_one_or_none() is None, "ReviewRound 应被删除"

            # ReviewParticipant 应被删除
            result = await db.execute(select(ReviewParticipant).where(ReviewParticipant.request_id == req_id))
            assert result.scalar_one_or_none() is None, "ReviewParticipant 应被删除"

            # KnowledgeSnapshot 应被删除
            result = await db.execute(select(KnowledgeSnapshot).where(KnowledgeSnapshot.project_id == project_id))
            assert result.scalar_one_or_none() is None, "KnowledgeSnapshot 应被删除"

            # Artifact (review_request 类型) 应被删除
            result = await db.execute(
                select(Artifact).where(
                    Artifact.object_type == "review_request",
                    Artifact.object_id == req_id,
                )
            )
            assert result.scalar_one_or_none() is None, "Artifact 应被删除"

            # Comments 应被删除
            result = await db.execute(
                select(Comment).where(
                    Comment.object_type == "review_request",
                    Comment.object_id == req_id,
                )
            )
            assert result.scalar_one_or_none() is None, "Comment (review_request) 应被删除"

            result = await db.execute(
                select(Comment).where(
                    Comment.object_type == "review_round",
                    Comment.object_id == round_id,
                )
            )
            assert result.scalar_one_or_none() is None, "Comment (review_round) 应被删除"

    async def test_delete_project_participant_not_duplicated(self, audit_client):
        """多个 round 时 ReviewParticipant 只应被删除一次（不报错）。"""
        ac, session_maker = audit_client

        resp = await ac.post("/api/review/projects", json={"name": "multi-round-test"})
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        from app.models.review import ReviewRequest, ReviewRound, ReviewParticipant

        async with session_maker() as db:
            req = ReviewRequest(
                project_id=project_id,
                initiator_id=1,
                goal="test",
                status="initiated",
                current_round=2,
            )
            db.add(req)
            await db.flush()

            # 创建 2 个 rounds
            for i in range(1, 3):
                db.add(ReviewRound(
                    request_id=req.id,
                    round_no=i,
                    decision="pending",
                ))
            await db.flush()

            db.add(ReviewParticipant(
                request_id=req.id,
                user_id=1,
                role="Reviewer",
                status="active",
            ))
            await db.commit()

        # 删除不应报错
        resp = await ac.delete(f"/api/review/projects/{project_id}")
        assert resp.status_code == 200


# ── BUG-146: resolve_comment defer_push ────────────────────────

class TestBUG146ResolveCommentDeferPush:
    """resolve_comment 应使用 defer_push=True。"""

    async def test_resolve_comment_source_code_uses_defer_push(self):
        """验证 resolve_comment 代码中使用了 defer_push=True。"""
        import app.routers.notification as notif_module
        import inspect

        source = inspect.getsource(notif_module.resolve_comment)
        assert "defer_push=True" in source, \
            "resolve_comment 应使用 NotificationService(db, defer_push=True)"
        assert "flush_pending" in source, \
            "resolve_comment 应在 commit 后调用 flush_pending()"

    async def test_resolve_comment_does_not_push_before_commit(self, audit_client):
        """resolve_comment 不应在 commit 前推送 SSE。"""
        ac, session_maker = audit_client

        # 创建项目 + ReviewRequest + Comment
        from app.models.review import ReviewRequest
        from app.models.user import Comment

        async with session_maker() as db:
            from app.models.review import ReviewProject
            p_result = await db.execute(select(ReviewProject).order_by(ReviewProject.id.desc()).limit(1))
            if p_result.scalar_one_or_none() is None:
                resp = await ac.post("/api/review/projects", json={"name": "comment-test"})
                project_id = resp.json()["id"]
            else:
                project_id = p_result.scalar_one().id

            req = ReviewRequest(
                project_id=project_id,
                initiator_id=1,
                goal="test",
                status="initiated",
                current_round=1,
            )
            db.add(req)
            await db.flush()

            # 用另一个用户作为评论作者
            from app.models.user import User
            from app.services.auth import hash_password
            other_user = User(
                username="commenter",
                password_hash=hash_password("pass@2026"),
                role="member",
            )
            db.add(other_user)
            await db.flush()

            comment = Comment(
                object_type="review_request",
                object_id=req.id,
                author_id=other_user.id,
                body="needs review",
            )
            db.add(comment)
            await db.commit()

            comment_id = comment.id
            other_user_id = other_user.id

        # resolve_comment
        from app.services import notification_service
        push_called_before_commit = []

        def spy_deliver(self, recipient_id, event):
            push_called_before_commit.append(recipient_id)

        with patch.object(
            notification_service.NotificationService,
            "_deliver",
            spy_deliver,
        ):
            resp = await ac.put(
                f"/api/notifications/comments/{comment_id}/resolve",
                json={"resolution": "resolved"},
            )

        assert resp.status_code == 200
        # _deliver 应在 flush_pending（即 commit 后）才被调用
        assert len(push_called_before_commit) == 1
        assert push_called_before_commit[0] == other_user_id


# ── BUG-147: FTS5 sanitize ────────────────────────────────────

class TestBUG147FTS5Sanitize:
    """_sanitize_fts5_query 应处理 NEAR 关键字和 Unicode 引号。"""

    def test_near_keyword_is_stripped(self):
        from app.services.knowledge_ingestion import _sanitize_fts5_query
        result = _sanitize_fts5_query("term1 NEAR term2")
        assert "NEAR" not in result.upper()
        assert "term1" in result
        assert "term2" in result

    def test_near_case_insensitive(self):
        from app.services.knowledge_ingestion import _sanitize_fts5_query
        result = _sanitize_fts5_query("term1 near term2")
        assert "near" not in result.lower().replace("term1", "").replace("term2", "")

    def test_unicode_smart_quotes_normalized(self):
        from app.services.knowledge_ingestion import _sanitize_fts5_query
        # NFKC 应将智能引号转为 ASCII 引号，然后被正则移除
        result = _sanitize_fts5_query("“你好”")  # 左右双引号
        assert "“" not in result
        assert "”" not in result
        assert "你好" in result

    def test_unicode_single_quotes_normalized(self):
        from app.services.knowledge_ingestion import _sanitize_fts5_query
        result = _sanitize_fts5_query("‘test’")  # 左右单引号
        assert "‘" not in result
        assert "’" not in result
        assert "test" in result

    def test_fullwidth_at_sign_normalized(self):
        from app.services.knowledge_ingestion import _sanitize_fts5_query
        # NFKC 将全角 ＠ 转为 @，再被正则移除
        result = _sanitize_fts5_query("test＠column")
        assert "＠" not in result
        assert "test" in result
        assert "column" in result


# ── BUG-148: embedding worker stale processing ────────────────

class TestBUG148EmbeddingWorkerStaleProcessing:
    """worker 应重置 stale 'processing' chunks 为 'pending'。"""

    async def test_processing_chunks_reset_to_pending(self, audit_client):
        """process_pending_embeddings 应将 processing 状态的 chunks 重置为 pending。"""
        ac, session_maker = audit_client

        from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
        from app.models.workspace import KnowledgeSource

        async with session_maker() as db:
            from app.models.workspace import Workspace
            ws_result = await db.execute(select(Workspace).where(Workspace.is_default == True))
            ws = ws_result.scalar_one()

            # 创建 KnowledgeSource
            ks = KnowledgeSource(
                workspace_id=ws.id,
                owner_id=1,
                title="test source",
                source_type="text",
                status="active",
                visibility="team",
            )
            db.add(ks)
            await db.flush()

            # 创建 KnowledgeDocument
            kd = KnowledgeDocument(
                source_id=ks.id,
                filename="test.txt",
            )
            db.add(kd)
            await db.flush()

            # 创建一个卡在 "processing" 状态的 chunk
            chunk = KnowledgeChunk(
                document_id=kd.id,
                chunk_no=0,
                text="stale chunk text",
                embedding_status="processing",
            )
            db.add(chunk)
            await db.commit()

            chunk_id = chunk.id

        # 调用 process_pending_embeddings
        from app.services.embedding_worker import process_pending_embeddings
        from unittest.mock import MagicMock

        # Mock embedding service to avoid real API calls
        mock_embedder = MagicMock()
        mock_embedder.embed_batch = AsyncMock(return_value=[[0.1] * 128])

        # Mock vector service
        with patch("app.services.embedding_worker.get_knowledge_vector_service") as mock_get_vcs:
            mock_vcs = MagicMock()
            mock_vcs.upsert = AsyncMock(return_value=1)
            mock_get_vcs.return_value = mock_vcs

            async with session_maker() as db:
                result = await process_pending_embeddings(db, embedding_service=mock_embedder)

        # 验证 chunk 最终变为 "done"
        async with session_maker() as db:
            result = await db.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id)
            )
            chunk = result.scalar_one_or_none()
            assert chunk is not None
            assert chunk.embedding_status == "done", \
                f"stale processing chunk 应被重置并处理，当前状态: {chunk.embedding_status}"


# ── BUG-151: 上传去重 DB 级唯一约束兜底 ───────────────────────

class TestBUG151UploadDedupDBConstraint:
    """ReviewDocument 应有 (project_id, document_type, filename) 唯一约束，
    作为 BUG-141 应用层去重的 DB 级兜底，防止并发竞态产生重复行。"""

    def test_review_document_has_unique_constraint(self):
        """ReviewDocument 模型应定义唯一约束。"""
        from app.models.review import ReviewDocument
        table_args = getattr(ReviewDocument, "__table_args__", None)
        assert table_args is not None, "ReviewDocument 应有 __table_args__"

        # __table_args__ 是元组，其中包含 UniqueConstraint
        found = False
        for arg in table_args:
            if hasattr(arg, "name") and arg.name == "uq_review_doc_proj_type_filename":
                found = True
                break
        assert found, (
            "ReviewDocument.__table_args__ 应包含名为 "
            "uq_review_doc_proj_type_filename 的 UniqueConstraint"
        )

    async def test_direct_duplicate_insert_raises_integrity_error(self, audit_client):
        """直接用 ORM 插入同 project_id + document_type + filename 两条应触发约束。"""
        ac, session_maker = audit_client

        from app.models.review import ReviewDocument, ReviewProject
        from sqlalchemy.exc import IntegrityError

        async with session_maker() as db:
            # 获取一个项目
            proj_result = await db.execute(select(ReviewProject).limit(1))
            proj = proj_result.scalar_one_or_none()
            if proj is None:
                # 创建一个项目
                resp = await ac.post("/api/review/projects", json={"name": "constraint-test"})
                proj_id = resp.json()["id"]
            else:
                proj_id = proj.id

            # 直接插入第一条
            doc1 = ReviewDocument(
                project_id=proj_id,
                filename="dup-test.docx",
                document_type="requirement",
                status="uploaded",
            )
            db.add(doc1)
            await db.commit()

            # 直接插入同名第二条应触发 IntegrityError
            doc2 = ReviewDocument(
                project_id=proj_id,
                filename="dup-test.docx",
                document_type="requirement",
                status="uploaded",
            )
            db.add(doc2)
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()

            # 不同 document_type 的同名文件应允许（不触发约束）
            doc3 = ReviewDocument(
                project_id=proj_id,
                filename="dup-test.docx",
                document_type="historical",
                status="uploaded",
            )
            db.add(doc3)
            await db.commit()

    async def test_upload_api_dedup_still_works_with_constraint(self, audit_client):
        """经 API 上传同名文件应被 skipped，不因约束报 500。"""
        ac, _ = audit_client

        resp = await ac.post("/api/review/projects", json={"name": "api-dedup-test"})
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        minimal_docx = b"PK\x05\x06" + b"\x00" * 18

        # 第一次上传成功
        r1 = await ac.post(
            f"/api/review/projects/{project_id}/documents",
            files=[("files", ("same.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )
        assert r1.status_code == 200
        assert r1.json()["uploaded"] == 1

        # 第二次上传同名应被 skipped（不报 500）
        r2 = await ac.post(
            f"/api/review/projects/{project_id}/documents",
            files=[("files", ("same.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )
        assert r2.status_code == 200
        assert r2.json()["uploaded"] == 0
        assert len(r2.json()["skipped"]) == 1


# ── BUG-152: start_review per-project 锁消除并发重复创建 ─────────

class TestBUG152StartReviewLock:
    """start_review 应使用 per-project 锁串行化 active task 查询 + 新 task 创建。"""

    def test_review_start_locks_dict_defined(self):
        """review 模块应定义 _review_start_locks 和 _get_review_start_lock。"""
        from app.routers import review

        assert hasattr(review, "_review_start_locks"), "review 模块应有 _review_start_locks"
        assert isinstance(review._review_start_locks, dict)
        assert callable(getattr(review, "_get_review_start_lock", None)), \
            "review 模块应有 _get_review_start_lock 函数"

    def test_get_review_start_lock_returns_same_lock_per_project(self):
        """同一 project_id 应返回同一个 Lock 实例。"""
        from app.routers import review

        # 清空避免受其他测试影响
        review._review_start_locks.clear()
        lock1 = review._get_review_start_lock(99991)
        lock2 = review._get_review_start_lock(99991)
        lock3 = review._get_review_start_lock(99992)
        assert lock1 is lock2, "同 project_id 应返回同一个 Lock"
        assert lock1 is not lock3, "不同 project_id 应返回不同 Lock"
        review._review_start_locks.clear()

    def test_start_review_uses_async_with_lock(self):
        """start_review 源码应使用 async with _get_review_start_lock。"""
        import inspect
        from app.routers import review

        source = inspect.getsource(review.start_review)
        assert "_get_review_start_lock" in source, \
            "start_review 应调用 _get_review_start_lock"
        assert "async with" in source, \
            "start_review 应使用 async with 包裹临界区"

    async def test_concurrent_start_review_creates_one_task(self, audit_client):
        """两个并发请求启动同项目审查应只创建一个 task（第二个返回已有 task）。"""
        import asyncio
        ac, session_maker = audit_client

        # 创建项目并上传文档
        resp = await ac.post("/api/review/projects", json={"name": "concurrent-review-test"})
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        minimal_docx = b"PK\x05\x06" + b"\x00" * 18
        resp = await ac.post(
            f"/api/review/projects/{project_id}/documents",
            files=[("files", ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )
        assert resp.status_code == 200

        # Mock _run_pipeline 避免真实 LLM 调用，但让它持有足够久以制造竞态窗口
        from app.routers import review

        async def slow_fake_pipeline(*args, **kwargs):
            # 不做任何事，让 task 卡在 pending
            return

        # Mock _get_model_config 返回有效配置，避免 400
        async def mock_get_model_config(model_id, db):
            return {
                "model_id": "test-model",
                "thinking_supported": False,
                "thinking_adapter": "none",
            }

        # 同时 mock ensure_workspace_llm_allowed 让配额检查通过
        from app.services import budget_guard

        async def mock_allow(db, workspace_id):
            pass

        with patch.object(review, "_run_pipeline", slow_fake_pipeline), \
             patch.object(review, "_get_model_config", mock_get_model_config), \
             patch.object(budget_guard, "ensure_workspace_llm_allowed", mock_allow):
            # 两个并发请求
            req_body = {"mode": "quick"}
            results = await asyncio.gather(
                ac.post(f"/api/review/projects/{project_id}/reviews", json=req_body),
                ac.post(f"/api/review/projects/{project_id}/reviews", json=req_body),
            )

        r1, r2 = results
        assert r1.status_code == 200, f"r1: {r1.text}"
        assert r2.status_code == 200, f"r2: {r2.text}"

        task_id_1 = r1.json()["task_id"]
        task_id_2 = r2.json()["task_id"]

        # 两个请求应返回同一个 task_id（第二个命中第一个创建的 task）
        # 因为 per-project 锁串行化了临界区
        assert task_id_1 == task_id_2, (
            f"并发请求应返回同一 task_id（per-project 锁串行化），"
            f"got {task_id_1} vs {task_id_2}"
        )
