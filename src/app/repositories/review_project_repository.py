"""ReviewProjectRepository — 审查项目与文档的结构化持久化。

职责边界：
- 结构化数据查询和写入（ReviewProject, ReviewDocument）
- 不负责文件系统访问、日志落盘、HTTPException
- 事务边界由 router/service 控制，方法内只 flush 不 commit
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import ReviewDocument, ReviewProject

logger = logging.getLogger(__name__)


@dataclass
class ProjectInfoRow:
    project: ReviewProject
    doc_count: int
    report_count: int
    context_version: int | None


class ReviewProjectRepository:
    """审查项目与文档的结构化持久化层。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create_project(self, *, name: str, description: str | None, created_by: int, workspace_id: int | None = None) -> ReviewProject:
        p = ReviewProject(name=name, description=description, created_by=created_by, workspace_id=workspace_id)
        self._db.add(p)
        await self._db.flush()
        await self._db.refresh(p)
        return p

    async def list_projects(self, *, user_id: int) -> list[ProjectInfoRow]:
        result = await self._db.execute(
            select(ReviewProject)
            .where(ReviewProject.created_by == user_id)
            .order_by(ReviewProject.updated_at.desc())
        )
        projects = result.scalars().all()
        out = []
        for p in projects:
            dc = await self._db.execute(
                select(func.count()).where(ReviewDocument.project_id == p.id)
            )
            doc_count = dc.scalar() or 0
            from app.models.review import ReviewTask
            rc = await self._db.execute(
                select(func.count()).where(
                    ReviewTask.project_id == p.id,
                    ReviewTask.status.in_(("completed", "completed_with_warnings")),
                )
            )
            report_count = rc.scalar() or 0
            from app.models.review import ReviewContext
            cv = await self._db.execute(
                select(ReviewContext.version)
                .where(ReviewContext.project_id == p.id, ReviewContext.is_active == True)
                .order_by(ReviewContext.version.desc())
                .limit(1)
            )
            ctx_ver = cv.scalar_one_or_none()
            out.append(ProjectInfoRow(project=p, doc_count=doc_count, report_count=report_count, context_version=ctx_ver))
        return out

    async def get_project(self, project_id: int) -> ReviewProject | None:
        result = await self._db.execute(
            select(ReviewProject).where(ReviewProject.id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_project_with_owner_check(self, project_id: int, user_id: int) -> ReviewProject | None:
        result = await self._db.execute(
            select(ReviewProject).where(ReviewProject.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None or project.created_by != user_id:
            return None
        return project

    async def delete_project(self, project_id: int) -> None:
        result = await self._db.execute(
            select(ReviewProject).where(ReviewProject.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project:
            await self._db.delete(project)
            await self._db.flush()

    # ── Documents ──

    async def list_documents(self, project_id: int, *, document_type: str | None = None) -> list[ReviewDocument]:
        query = select(ReviewDocument).where(ReviewDocument.project_id == project_id)
        if document_type:
            query = query.where(ReviewDocument.document_type == document_type)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def get_document(self, document_id: int) -> ReviewDocument | None:
        result = await self._db.execute(
            select(ReviewDocument).where(ReviewDocument.id == document_id)
        )
        return result.scalar_one_or_none()

    async def add_document(self, doc: ReviewDocument) -> ReviewDocument:
        self._db.add(doc)
        await self._db.flush()
        return doc

    async def delete_document(self, document_id: int) -> None:
        result = await self._db.execute(
            select(ReviewDocument).where(ReviewDocument.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc:
            await self._db.delete(doc)
            await self._db.flush()