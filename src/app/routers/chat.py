"""对话路由：SSE 流式对话 — Phase 2 真实 LLM 调用"""

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import Conversation, ContextItem, ModelConfig, Message, PromptTemplate, User
from app.schemas.chat import ChatRequest, ContextItemCreate, ContextItemInfo, ContextItemUpdate, ModelInfo, PromptTemplateInfo
from app.services.crypto import decrypt_key, mask_key
from app.services.file_text import extract_text_from_path
from app.services.llm import (
    ChatMessage,
    PromptTemplate as LLMPromptTemplate,
    build_messages,
    stream_chat,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _truncate_context_text(text: str, limit: int = 8000) -> str:
    return text[:limit] + "\n...(内容过长，已截断)" if len(text) > limit else text


def _read_uploaded_context(file_id: str, upload_dir: str) -> str | None:
    file_path = os.path.join(upload_dir, str(file_id))
    if not os.path.isfile(file_path):
        return None
    return extract_text_from_path(file_path, str(file_id))


def _get_jwt_secret() -> str:
    settings = get_settings()
    secret = settings.get("auth", {}).get("secret_key")
    if not secret or secret == "change-me-in-production":
        raise RuntimeError("JWT secret 未配置或使用默认值，请设置 .env 中的 JWT_SECRET")
    return secret


async def _get_model_config(model_id: str, db: AsyncSession) -> dict | None:
    """从 DB 读取模型配置，解密 API Key，返回调用参数"""
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.model_id == model_id,
            ModelConfig.deleted_by_user == False,
        )
    )
    mc = result.scalar_one_or_none()
    if mc is None:
        return None
    if not mc.enabled:
        return None

    secret = _get_jwt_secret()
    api_key = ""
    if mc.encrypted_api_key:
        api_key = decrypt_key(mc.encrypted_api_key, secret)

    return {
        "model_id": mc.model_id,
        "name": mc.name,
        "api_base": mc.api_base,
        "api_key": api_key,
        "llm_model": mc.llm_model,
        "max_tokens": mc.max_tokens,
        "temperature": mc.temperature,
        "enabled": mc.enabled,
    }


@router.post("")
async def chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发起对话（SSE 流式输出）"""
    # Validate model — read from DB
    model_cfg = await _get_model_config(req.model_id, db)
    if not model_cfg:
        raise HTTPException(status_code=400, detail=f"模型不存在或已禁用: {req.model_id}")

    # Create or load conversation
    if req.conversation_id is None:
        conv = Conversation(
            user_id=user.id,
            title=req.message[:50] if len(req.message) > 50 else req.message,
            model_id=req.model_id,
            prompt_template=req.prompt_template,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conv_id = conv.id
    else:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == req.conversation_id,
                Conversation.user_id == user.id,
            )
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="对话不存在")
        conv_id = conv.id

    # Save user message
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=req.message,
    )
    db.add(user_msg)
    await db.commit()

    # Load prompt template
    template = None
    if req.prompt_template:
        result = await db.execute(
            select(PromptTemplate).where(PromptTemplate.name == req.prompt_template)
        )
        pt = result.scalar_one_or_none()
        if pt:
            template = LLMPromptTemplate(
                name=pt.name,
                description=pt.description or "",
                system_prompt=pt.system_prompt or "",
                user_prompt_template=pt.user_prompt_template or "",
            )

    # Load conversation history (previous messages)
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
    )
    history_msgs = [
        ChatMessage(role=m.role, content=m.content)
        for m in history_result.scalars().all()
        # Exclude the just-saved user message (it's the last one)
    ][:-1]

    # Build file/URL context
    context_parts = []

    if req.urls:
        for u in req.urls:
            text = req.url_texts.get(u, "")
            if text:
                context_parts.append(f"[URL: {u}]\n{_truncate_context_text(text)}")
            else:
                context_parts.append(f"URL: {u}")

    if req.file_ids:
        settings = get_settings()
        upload_dir = settings.get("upload", {}).get("upload_dir", "data/uploads")
        for fid in req.file_ids:
            content = _read_uploaded_context(str(fid), upload_dir)
            if content:
                context_parts.append(f"[文件 {fid}]\n{_truncate_context_text(content)}")

    # Load persisted context items for this conversation
    if conv_id:
        ctx_result = await db.execute(
            select(ContextItem).where(
                ContextItem.conversation_id == conv_id,
                ContextItem.enabled == True,
            )
        )
        mentioned_context_item_ids = set(req.mention_context_item_ids or [])
        ctx_items = ctx_result.scalars().all()
        for item in ctx_items:
            if item.manual_text:
                context_parts.append(f"[规则] {item.manual_text}")
            elif item.file_id:
                if mentioned_context_item_ids and item.id not in mentioned_context_item_ids:
                    continue
                content = item.extracted_text
                if not content:
                    settings = get_settings()
                    upload_dir = settings.get("upload", {}).get("upload_dir", "data/uploads")
                    content = _read_uploaded_context(item.file_id, upload_dir)
                if content:
                    context_parts.append(f"[文档: {item.title}]\n{_truncate_context_text(content)}")
            elif item.url:
                if item.extracted_text:
                    context_parts.append(f"[URL: {item.url}]\n{_truncate_context_text(item.extracted_text)}")
                else:
                    context_parts.append(f"[URL: {item.url}]")

    if req.context_rules:
        for rule in req.context_rules:
            context_parts.append(f"[规则] {rule}")

    context = "\n\n".join(context_parts) if context_parts else None

    # Build messages for LLM
    llm_messages = build_messages(template, history_msgs, req.message, context)

    async def _stream(db_session: AsyncSession):
        collected = []
        token_count = 0

        try:
            async for chunk in stream_chat(
                model_id=model_cfg["model_id"],
                api_base=model_cfg["api_base"],
                api_key=model_cfg["api_key"],
                llm_model=model_cfg["llm_model"],
                messages=llm_messages,
                max_tokens=model_cfg["max_tokens"],
                temperature=model_cfg["temperature"],
            ):
                if chunk.delta:
                    collected.append(chunk.delta)
                    token_count += 1
                    data = json.dumps({
                        "content": chunk.delta,
                        "conversation_id": conv_id,
                    })
                    yield f"data: {data}\n\n"

                if chunk.finish_reason:
                    # Save assistant response to DB before sending [DONE]
                    full_text = "".join(collected)
                    if full_text:
                        ai_msg = Message(
                            conversation_id=conv_id,
                            role="assistant",
                            content=full_text,
                            token_count=token_count,
                        )
                        db_session.add(ai_msg)
                        await db_session.commit()

                    # Final stats
                    stats = chunk.usage or {}
                    data = json.dumps({
                        "content": "",
                        "conversation_id": conv_id,
                        "done": True,
                        "token_count": token_count,
                        "elapsed_seconds": stats.get("elapsed_seconds"),
                    })
                    yield f"data: {data}\n\n"
                    yield "data: [DONE]\n\n"
                    break

        except Exception as e:
            logger.error("LLM stream error: %s", e)
            error_data = json.dumps({
                "error": str(e),
                "conversation_id": conv_id,
            })
            yield f"data: {error_data}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        _stream(db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/models", response_model=list[ModelInfo])
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取可用模型列表"""
    result = await db.execute(
        select(ModelConfig)
        .where(ModelConfig.deleted_by_user == False)
        .order_by(ModelConfig.display_order, ModelConfig.name, ModelConfig.id)
    )
    models = result.scalars().all()
    return [
        ModelInfo(id=mc.model_id, name=mc.name, enabled=mc.enabled)
        for mc in models
    ]


@router.get("/prompts", response_model=list[PromptTemplateInfo])
async def list_prompts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取可用的 Prompt 模板列表"""
    result = await db.execute(
        select(PromptTemplate).order_by(PromptTemplate.name)
    )
    templates = result.scalars().all()
    return [
        PromptTemplateInfo(
            id=t.id, name=t.name, description=t.description
        )
        for t in templates
    ]


@router.get("/conversations/{conv_id}/context", response_model=list[ContextItemInfo])
async def list_context_items(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取对话的上下文项列表"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    ctx_result = await db.execute(
        select(ContextItem).where(ContextItem.conversation_id == conv_id).order_by(ContextItem.created_at)
    )
    items = ctx_result.scalars().all()
    return [
        ContextItemInfo(
            id=item.id,
            context_type=item.context_type,
            title=item.title,
            file_id=item.file_id,
            url=item.url,
            manual_text=item.manual_text,
            extracted_text=item.extracted_text,
            enabled=item.enabled,
            created_at=item.created_at.isoformat() if item.created_at else "",
        )
        for item in items
    ]


@router.post("/conversations/{conv_id}/context", response_model=ContextItemInfo)
async def create_context_item(
    conv_id: int,
    data: ContextItemCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """为对话添加上下文项"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    extracted_text = data.extracted_text
    if data.file_id and not extracted_text:
        settings = get_settings()
        upload_dir = settings.get("upload", {}).get("upload_dir", "data/uploads")
        extracted_text = _read_uploaded_context(data.file_id, upload_dir)

    item = ContextItem(
        conversation_id=conv_id,
        context_type=data.context_type,
        title=data.title,
        file_id=data.file_id,
        url=data.url,
        manual_text=data.manual_text,
        extracted_text=extracted_text,
        enabled=data.enabled,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return ContextItemInfo(
        id=item.id,
        context_type=item.context_type,
        title=item.title,
        file_id=item.file_id,
        url=item.url,
        manual_text=item.manual_text,
        extracted_text=item.extracted_text,
        enabled=item.enabled,
        created_at=item.created_at.isoformat() if item.created_at else "",
    )


@router.put("/conversations/{conv_id}/context/{item_id}", response_model=ContextItemInfo)
async def update_context_item(
    conv_id: int,
    item_id: int,
    data: ContextItemUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新上下文项"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    ctx_result = await db.execute(
        select(ContextItem).where(
            ContextItem.id == item_id,
            ContextItem.conversation_id == conv_id,
        )
    )
    item = ctx_result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="上下文项不存在")

    if data.title is not None:
        item.title = data.title
    if data.enabled is not None:
        item.enabled = data.enabled
    await db.commit()
    await db.refresh(item)

    return ContextItemInfo(
        id=item.id,
        context_type=item.context_type,
        title=item.title,
        file_id=item.file_id,
        url=item.url,
        manual_text=item.manual_text,
        extracted_text=item.extracted_text,
        enabled=item.enabled,
        created_at=item.created_at.isoformat() if item.created_at else "",
    )


@router.delete("/conversations/{conv_id}/context/{item_id}")
async def delete_context_item(
    conv_id: int,
    item_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除上下文项"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    ctx_result = await db.execute(
        select(ContextItem).where(
            ContextItem.id == item_id,
            ContextItem.conversation_id == conv_id,
        )
    )
    item = ctx_result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="上下文项不存在")

    await db.delete(item)
    await db.commit()
    return {"message": "上下文项已删除"}
