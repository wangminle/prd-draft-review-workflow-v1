"""P4.D: 通知与评论路由 — Notification SSE / CRUD / Comment API。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository, CommentRepository
from app.services.notification_service import get_notification_channel, clear_channel
from app.services.auth import consume_sse_ticket

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────

class CreateComment(BaseModel):
    object_type: str  # review_request/review_round/artifact/knowledge_source
    object_id: int
    body: str
    parent_id: int | None = None  # 回复评论 ID


class MarkReadRequest(BaseModel):
    notification_ids: list[int] | None = None  # 空 = 全部标记已读


# ─── Helpers ──────────────────────────────────────────────────

def _serialize_notification(n) -> dict:
    return {
        "id": n.id,
        "recipient_id": n.recipient_id,
        "actor_id": n.actor_id,
        "object_type": n.object_type,
        "object_id": n.object_id,
        "type": n.type,
        "status": n.status,
        "title": n.title,
        "body": n.body,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _serialize_comment(c) -> dict:
    return {
        "id": c.id,
        "object_type": c.object_type,
        "object_id": c.object_id,
        "author_id": c.author_id,
        "body": c.body,
        "parent_id": c.parent_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# ─── Notification Endpoints ──────────────────────────────────

@router.get("/stream")
async def notification_stream(
    ticket: str | None = Query(None),
):
    """P4.D.4: Notification SSE 端点 — 推送 unread 通知增量事件。

    使用 SSE ticket 认证（EventSource 不支持自定义 Header），
    前端先 POST /api/auth/sse-ticket 获取 ticket，再通过 query 参数传入。
    """
    if not ticket:
        # 降级：尝试 Bearer 认证（兼容非 SSE 客户端）
        raise HTTPException(status_code=401, detail="未提供认证票据")

    user_id = consume_sse_ticket(ticket)
    if user_id is None:
        raise HTTPException(status_code=401, detail="认证票据无效或已过期")

    import asyncio as _asyncio

    async def event_generator():
        channel = get_notification_channel(user_id)
        try:
            while True:
                # 发送缓冲区中的事件
                while channel:
                    event_data = channel.pop(0)
                    yield f"data: {event_data}\n\n"
                # 发送心跳
                yield f": heartbeat\n\n"
                await _asyncio.sleep(5)
        except asyncio.CancelledError:
            pass
        finally:
            clear_channel(user_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("")
async def list_notifications(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的通知。"""
    repo = NotificationRepository(db)
    notifications = await repo.list_by_recipient(
        user.id, status=status, limit=limit, offset=offset,
    )
    unread_count = await repo.count_unread(user.id)
    return {
        "items": [_serialize_notification(n) for n in notifications],
        "unread_count": unread_count,
    }


@router.get("/unread-count")
async def get_unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取未读通知数量。"""
    repo = NotificationRepository(db)
    count = await repo.count_unread(user.id)
    return {"unread_count": count}


@router.put("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """标记通知为已读。"""
    repo = NotificationRepository(db)
    notification = await repo.get_by_id(notification_id)
    if not notification:
        raise HTTPException(404, "通知不存在")
    if notification.recipient_id != user.id:
        raise HTTPException(403, "无权操作此通知")
    await repo.mark_read(notification)
    await db.commit()
    return _serialize_notification(notification)


@router.post("/batch-read")
async def batch_mark_read(
    req: MarkReadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """批量标记通知为已读。"""
    repo = NotificationRepository(db)
    if req.notification_ids:
        for nid in req.notification_ids:
            n = await repo.get_by_id(nid)
            if n and n.recipient_id == user.id:
                await repo.mark_read(n)
    else:
        count = await repo.mark_all_read(user.id)
        await db.commit()
        return {"marked_count": count}
    await db.commit()
    return {"marked_count": len(req.notification_ids or [])}


@router.put("/{notification_id}/archive")
async def archive_notification(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """归档通知。"""
    repo = NotificationRepository(db)
    notification = await repo.get_by_id(notification_id)
    if not notification:
        raise HTTPException(404, "通知不存在")
    if notification.recipient_id != user.id:
        raise HTTPException(403, "无权操作此通知")
    await repo.archive(notification)
    await db.commit()
    return _serialize_notification(notification)


# ─── Comment Endpoints ───────────────────────────────────────

@router.post("/comments")
async def create_comment(
    req: CreateComment,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P4.D.6: 创建评论。"""
    if req.object_type not in ("review_request", "review_round", "artifact", "knowledge_source"):
        raise HTTPException(422, "无效的 object_type")

    repo = CommentRepository(db)
    comment = await repo.create(
        object_type=req.object_type,
        object_id=req.object_id,
        author_id=user.id,
        body=req.body,
        parent_id=req.parent_id,
    )

    # 如果是回复，通知原评论作者
    if req.parent_id:
        parent_comment = await repo.get_by_id(req.parent_id)
        if parent_comment and parent_comment.author_id != user.id:
            from app.services.notification_service import NotificationService
            notif_service = NotificationService(db)
            await notif_service.notify_comment_reply(
                comment_id=comment.id,
                object_type=req.object_type,
                object_id=req.object_id,
                author_id=user.id,
                parent_author_id=parent_comment.author_id,
            )

    # 检测 @提及：从 body 中提取 @username 并通知
    import re
    mentions = re.findall(r'@(\w+)', req.body)
    if mentions:
        from sqlalchemy import select
        from app.models.user import User as UserModel
        from app.services.notification_service import NotificationService
        notif_service = NotificationService(db)
        for username in set(mentions):
            result = await db.execute(
                select(UserModel).where(UserModel.username == username)
            )
            mentioned_user = result.scalar_one_or_none()
            if mentioned_user and mentioned_user.id != user.id:
                await notif_service.notify_mention(
                    comment_id=comment.id,
                    object_type=req.object_type,
                    object_id=req.object_id,
                    mentioner_id=user.id,
                    mentioned_user_id=mentioned_user.id,
                )

    await db.commit()
    return _serialize_comment(comment)


@router.get("/comments")
async def list_comments(
    object_type: str,
    object_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """P4.D.6: 列出指定对象的评论。"""
    repo = CommentRepository(db)
    comments = await repo.list_by_object(object_type, object_id)
    return [_serialize_comment(c) for c in comments]


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除评论（仅作者可删除）。"""
    repo = CommentRepository(db)
    comment = await repo.get_by_id(comment_id)
    if not comment:
        raise HTTPException(404, "评论不存在")
    if comment.author_id != user.id:
        raise HTTPException(403, "仅作者可删除评论")
    await repo.delete(comment)
    await db.commit()
    return {"status": "ok"}
