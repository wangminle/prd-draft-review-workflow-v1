"""历史记录路由"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import Conversation, Message, User
from app.schemas.history import (
    ConversationDetail,
    ConversationInfo,
    MessageInfo,
    PaginatedConversations,
    SearchResult,
    SearchResults,
)

router = APIRouter()


@router.get("/conversations", response_model=PaginatedConversations)
async def list_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的对话列表（分页）"""
    offset = (page - 1) * page_size

    # 总数
    count_q = select(func.count(Conversation.id)).where(
        Conversation.user_id == user.id
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # 对话列表 + 消息数
    rows = await db.execute(
        select(
            Conversation,
            func.count(Message.id).label("msg_count"),
        )
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    conversations = []
    for conv, msg_count in rows:
        conversations.append(
            ConversationInfo(
                id=conv.id,
                title=conv.title,
                model_id=conv.model_id,
                created_at=conv.created_at.isoformat() if conv.created_at else "",
                updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
                message_count=msg_count,
            )
        )

    return PaginatedConversations(
        conversations=conversations,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取对话详情（含所有消息）"""
    from fastapi import HTTPException

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
    )
    messages = msg_result.scalars().all()

    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        model_id=conv.model_id,
        messages=[
            MessageInfo(
                id=m.id,
                role=m.role,
                content=m.content,
                token_count=m.token_count,
                created_at=m.created_at.isoformat() if m.created_at else "",
            )
            for m in messages
        ],
    )


@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除对话"""
    from fastapi import HTTPException

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    await db.delete(conv)
    await db.commit()
    return {"message": "对话已删除"}


@router.get("/search", response_model=SearchResults)
async def search_messages(
    q: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """全文搜索消息内容"""
    from sqlalchemy import text

    # FTS5 搜索，仅搜索当前用户的消息
    sql = text("""
        SELECT m.id, m.conversation_id, m.role, m.content, m.created_at
        FROM messages m
        JOIN messages_fts fts ON m.id = fts.rowid
        JOIN conversations c ON m.conversation_id = c.id
        WHERE messages_fts MATCH :query
        AND c.user_id = :user_id
        ORDER BY rank
        LIMIT 50
    """)

    rows = await db.execute(sql, {"query": q, "user_id": user.id})
    results = [
        SearchResult(
            conversation_id=row.conversation_id,
            message_id=row.id,
            role=row.role,
            content=row.content[:200],  # 只返回前200字作为预览
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]

    return SearchResults(results=results, total=len(results))
