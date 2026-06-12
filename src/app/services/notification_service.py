"""P4.D.3: NotificationService — 审查事件和 Agent 审批事件 → 创建通知 → SSE 推送。

职责边界：
- 接收业务事件（审查请求创建/通过/驳回、物料确认、Agent 审批、评论回复）
- 创建 Notification 记录
- 通过内存 SSE channel 推送实时通知
- 不负责 SSE 连接管理（由 router 层管理）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)

# 内存通知 channel：recipient_id → list[str]（JSON 事件）
# 每个 SSE 连接会订阅自己的 channel
_notification_channels: dict[int, list[str]] = {}


def get_notification_channel(recipient_id: int) -> list[str]:
    """获取用户的通知 channel（用于 SSE 推送）。"""
    if recipient_id not in _notification_channels:
        _notification_channels[recipient_id] = []
    return _notification_channels[recipient_id]


def clear_channel(recipient_id: int) -> None:
    """清理用户的通知 channel。"""
    _notification_channels.pop(recipient_id, None)


@dataclass
class NotificationEvent:
    """通知事件 — 用于 SSE 推送。"""
    type: str  # new_notification / notification_read / notification_archived
    notification_id: int
    data: dict


class NotificationService:
    """通知服务：创建通知 + SSE 推送。"""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = NotificationRepository(db)

    async def notify_review_request_created(
        self,
        *,
        request_id: int,
        project_id: int,
        initiator_id: int,
        approver_ids: list[int],
        goal: str | None = None,
    ) -> list[int]:
        """P4.A.4: 协作审查请求创建 → 通知 Approver。"""
        notification_ids = []
        title = f"新的协作审查请求"
        body = goal or "请审查此协作审查请求"

        for approver_id in approver_ids:
            notification = await self._repo.create(
                recipient_id=approver_id,
                actor_id=initiator_id,
                object_type="review_request",
                object_id=request_id,
                type="review_request_created",
                title=title,
                body=body,
            )
            notification_ids.append(notification.id)
            self._push_event(approver_id, NotificationEvent(
                type="new_notification",
                notification_id=notification.id,
                data={
                    "id": notification.id,
                    "type": "review_request_created",
                    "title": title,
                    "body": body,
                    "object_type": "review_request",
                    "object_id": request_id,
                },
            ))

        return notification_ids

    async def notify_review_round_decided(
        self,
        *,
        request_id: int,
        round_no: int,
        decision: str,
        comment: str | None,
        initiator_id: int,
        approver_id: int,
    ) -> int:
        """P4.A.5: 审查轮次决策 → 通知发起人。"""
        decision_text = "通过" if decision == "approved" else "驳回"
        title = f"审查轮次 {round_no} 已{decision_text}"
        body = comment or f"审查员已{decision_text}第 {round_no} 轮审查"

        notification = await self._repo.create(
            recipient_id=initiator_id,
            actor_id=approver_id,
            object_type="review_round",
            object_id=request_id,
            type=f"review_round_{decision}",
            title=title,
            body=body,
        )

        self._push_event(initiator_id, NotificationEvent(
            type="new_notification",
            notification_id=notification.id,
            data={
                "id": notification.id,
                "type": f"review_round_{decision}",
                "title": title,
                "body": body,
                "object_type": "review_round",
                "object_id": request_id,
            },
        ))

        return notification.id

    async def notify_artifact_confirmed(
        self,
        *,
        artifact_id: int,
        object_type: str,
        object_id: int,
        confirmer_id: int,
        recipient_ids: list[int],
    ) -> list[int]:
        """P4.B.4: 物料确认 → 通知相关人员。"""
        notification_ids = []
        title = "物料已确认"
        body = "讲解物料已确认冻结"

        for recipient_id in recipient_ids:
            notification = await self._repo.create(
                recipient_id=recipient_id,
                actor_id=confirmer_id,
                object_type="artifact",
                object_id=artifact_id,
                type="artifact_confirmed",
                title=title,
                body=body,
            )
            notification_ids.append(notification.id)
            self._push_event(recipient_id, NotificationEvent(
                type="new_notification",
                notification_id=notification.id,
                data={
                    "id": notification.id,
                    "type": "artifact_confirmed",
                    "title": title,
                    "body": body,
                    "object_type": object_type,
                    "object_id": object_id,
                },
            ))

        return notification_ids

    async def notify_agent_approval(
        self,
        *,
        approval_id: int,
        approver_id: int,
        requester_id: int,
        action_type: str,
    ) -> int:
        """P3 Agent 审批 → 通知审批人。"""
        title = "Agent 操作待审批"
        body = f"有一个 {action_type} 操作需要您的审批"

        notification = await self._repo.create(
            recipient_id=approver_id,
            actor_id=requester_id,
            object_type="agent_approval",
            object_id=approval_id,
            type="agent_approval",
            title=title,
            body=body,
        )

        self._push_event(approver_id, NotificationEvent(
            type="new_notification",
            notification_id=notification.id,
            data={
                "id": notification.id,
                "type": "agent_approval",
                "title": title,
                "body": body,
                "object_type": "agent_approval",
                "object_id": approval_id,
            },
        ))

        return notification.id

    async def notify_comment_reply(
        self,
        *,
        comment_id: int,
        object_type: str,
        object_id: int,
        author_id: int,
        parent_author_id: int,
    ) -> int | None:
        """P4.D.6: 评论回复 → 通知原评论作者。"""
        if author_id == parent_author_id:
            return None  # 不通知自己

        title = "评论收到回复"
        body = "您的评论收到了新回复"

        notification = await self._repo.create(
            recipient_id=parent_author_id,
            actor_id=author_id,
            object_type="comment",
            object_id=comment_id,
            type="comment_reply",
            title=title,
            body=body,
        )

        self._push_event(parent_author_id, NotificationEvent(
            type="new_notification",
            notification_id=notification.id,
            data={
                "id": notification.id,
                "type": "comment_reply",
                "title": title,
                "body": body,
                "object_type": object_type,
                "object_id": object_id,
            },
        ))

        return notification.id

    async def notify_mention(
        self,
        *,
        comment_id: int,
        object_type: str,
        object_id: int,
        mentioner_id: int,
        mentioned_user_id: int,
    ) -> int | None:
        """P4.D.6: @提及 → 通知被提及用户。"""
        if mentioner_id == mentioned_user_id:
            return None

        title = "您被 @提及"
        body = "有评论 @提及了您"

        notification = await self._repo.create(
            recipient_id=mentioned_user_id,
            actor_id=mentioner_id,
            object_type="comment",
            object_id=comment_id,
            type="mention",
            title=title,
            body=body,
        )

        self._push_event(mentioned_user_id, NotificationEvent(
            type="new_notification",
            notification_id=notification.id,
            data={
                "id": notification.id,
                "type": "mention",
                "title": title,
                "body": body,
                "object_type": object_type,
                "object_id": object_id,
            },
        ))

        return notification.id

    async def notify_agent_conversation(
        self,
        target_user_id: int,
        actor_user_id: int,
        agent_profile_id: int,
        conversation_id: int,
        summary: str,
    ) -> int:
        """P5.A.3: 他人与你的 Agent 对话后，通知你有人提问，需确认/回复。

        Args:
            target_user_id: Agent 所有者（被通知人）
            actor_user_id: 向 Agent 提问的人
            agent_profile_id: 被调用的 Agent Profile ID
            conversation_id: 对话 ID
            summary: 提问摘要

        Returns:
            notification.id
        """
        title = "Agent 对话请求"
        body = f"有人向您的 Agent 提问了：{summary[:100]}"
        notification = await self._repo.create(
            recipient_id=target_user_id,
            actor_id=actor_user_id,
            object_type="agent_conversation",
            object_id=conversation_id,
            type="agent_conversation",
            title=title,
            body=body,
        )

        self._push_event(target_user_id, NotificationEvent(
            type="new_notification",
            notification_id=notification.id,
            data={
                "id": notification.id,
                "type": "agent_conversation",
                "title": title,
                "body": body,
                "object_type": "agent_conversation",
                "object_id": conversation_id,
            },
        ))

        return notification.id

    def _push_event(self, recipient_id: int, event: NotificationEvent) -> None:
        """将通知事件推送到用户的 SSE channel。"""
        channel = get_notification_channel(recipient_id)
        event_json = json.dumps({
            "type": event.type,
            "notification_id": event.notification_id,
            "data": event.data,
        }, ensure_ascii=False)
        channel.append(event_json)
        # 限制 channel 缓冲区大小，防止内存泄漏
        if len(channel) > 100:
            channel[:] = channel[-50:]
