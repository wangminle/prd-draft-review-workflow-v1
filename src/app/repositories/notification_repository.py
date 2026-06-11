"""P4.D: 通知与评论 Repository — Notification / Comment。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Notification, Comment
from app.logging_config import now_cn


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        *,
        recipient_id: int,
        actor_id: int | None = None,
        object_type: str,
        object_id: int,
        type: str,
        title: str,
        body: str | None = None,
    ) -> Notification:
        notification = Notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            object_type=object_type,
            object_id=object_id,
            type=type,
            title=title,
            body=body,
            status="unread",
        )
        self._db.add(notification)
        await self._db.flush()
        await self._db.refresh(notification)
        return notification

    async def get_by_id(self, notification_id: int) -> Notification | None:
        result = await self._db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        return result.scalar_one_or_none()

    async def list_by_recipient(
        self,
        recipient_id: int,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        """列出用户的通知，支持按状态过滤。"""
        query = (
            select(Notification)
            .where(Notification.recipient_id == recipient_id)
            .order_by(Notification.created_at.desc())
        )
        if status:
            query = query.where(Notification.status == status)
        query = query.offset(offset).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def count_unread(self, recipient_id: int) -> int:
        """统计用户未读通知数量。"""
        result = await self._db.execute(
            select(func.count()).where(
                Notification.recipient_id == recipient_id,
                Notification.status == "unread",
            )
        )
        return result.scalar() or 0

    async def mark_read(self, notification: Notification) -> Notification:
        """标记通知为已读。"""
        notification.status = "read"
        await self._db.flush()
        await self._db.refresh(notification)
        return notification

    async def mark_all_read(self, recipient_id: int) -> int:
        """标记用户所有通知为已读，返回更新数量。"""
        result = await self._db.execute(
            select(Notification).where(
                Notification.recipient_id == recipient_id,
                Notification.status == "unread",
            )
        )
        notifications = result.scalars().all()
        for n in notifications:
            n.status = "read"
        await self._db.flush()
        return len(notifications)

    async def archive(self, notification: Notification) -> Notification:
        """归档通知。"""
        notification.status = "archived"
        await self._db.flush()
        await self._db.refresh(notification)
        return notification


class CommentRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        *,
        object_type: str,
        object_id: int,
        author_id: int,
        body: str,
        parent_id: int | None = None,
    ) -> Comment:
        comment = Comment(
            object_type=object_type,
            object_id=object_id,
            author_id=author_id,
            body=body,
            parent_id=parent_id,
        )
        self._db.add(comment)
        await self._db.flush()
        await self._db.refresh(comment)
        return comment

    async def get_by_id(self, comment_id: int) -> Comment | None:
        result = await self._db.execute(
            select(Comment).where(Comment.id == comment_id)
        )
        return result.scalar_one_or_none()

    async def list_by_object(
        self,
        object_type: str,
        object_id: int,
        *,
        limit: int = 100,
    ) -> list[Comment]:
        """列出指定对象的评论（顶级评论 + 回复）。"""
        result = await self._db.execute(
            select(Comment)
            .where(
                Comment.object_type == object_type,
                Comment.object_id == object_id,
            )
            .order_by(Comment.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_replies(self, parent_id: int) -> list[Comment]:
        """列出评论的回复。"""
        result = await self._db.execute(
            select(Comment)
            .where(Comment.parent_id == parent_id)
            .order_by(Comment.created_at)
        )
        return list(result.scalars().all())

    async def delete(self, comment: Comment) -> None:
        await self._db.delete(comment)
        await self._db.flush()
