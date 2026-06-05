"""Workspace 权限集中化服务 — P1.B.1

将 workspace.py 的 _MANAGE_ROLES / _WRITE_ROLES / _READ_ROLES
和 review.py 的零散角色判断统一收口到本模块。
"""

import logging

from fastapi import HTTPException

from app.models.workspace import WorkspaceMember

logger = logging.getLogger(__name__)

# 角色 → 允许的动作类别
ROLE_ACTION_MAP: dict[str, set[str]] = {
    "owner":  {"manage", "write", "read"},
    "admin":  {"manage", "write", "read"},
    "member": {"write", "read"},
    "viewer": {"read"},
}

# 动作类别 → 中文描述
ACTION_LABELS: dict[str, str] = {
    "manage": "管理",
    "write": "写入",
    "read": "读取",
}


def can(member: WorkspaceMember | None, action: str) -> bool:
    """判断成员是否有指定动作权限。"""
    if member is None:
        return False
    if member.status != "active":
        return False
    return action in ROLE_ACTION_MAP.get(member.role, set())


def require_action(
    member: WorkspaceMember | None,
    action: str,
    target_desc: str = "",
) -> None:
    """校验成员动作权限，不满足则抛 403 并写审计日志。

    Args:
        member: WorkspaceMember 实例（可为 None）
        action: "manage" / "write" / "read"
        target_desc: 操作描述，用于 403 消息和审计日志
    """
    if member is None:
        _log_deny(None, action, target_desc, "不是该空间的成员")
        raise HTTPException(403, "你不是该空间的成员")
    if member.status != "active":
        _log_deny(member, action, target_desc, f"成员状态为 {member.status}")
        raise HTTPException(403, f"你的成员状态({member.status})不允许执行{ACTION_LABELS.get(action, action)}操作")
    allowed = ROLE_ACTION_MAP.get(member.role, set())
    if action not in allowed:
        _log_deny(member, action, target_desc, f"角色 {member.role} 不允许")
        raise HTTPException(403, f"你的角色({member.role})不允许执行{target_desc or ACTION_LABELS.get(action, action)}操作")


def is_active_member(member: WorkspaceMember | None) -> bool:
    """判断成员是否为 active 状态的合法成员。"""
    return member is not None and member.status == "active"


def _log_deny(member: WorkspaceMember | None, action: str, target_desc: str, reason: str) -> None:
    user_id = member.user_id if member else None
    role = member.role if member else None
    logger.warning(
        "workspace_access.deny user_id=%s role=%s action=%s target=%s reason=%s",
        user_id, role, action, target_desc, reason,
    )
