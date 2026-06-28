"""对话路由：SSE 流式对话 — Phase 2 真实 LLM 调用

重构后的职责边界：
- router 只处理 HTTP 入参、鉴权依赖、响应码、response schema、SSE 协议
- ChatApplicationService 负责用例编排（会话创建、消息保存、上下文装配）
- ConversationRepository 处理会话和消息持久化
- ContextItemRepository 处理上下文项 CRUD
- ChatFileStorage 处理文件读取和文本抽取
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import ModelConfig, PromptTemplate, User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.context_item_repository import ContextItemRepository, ContextItemCreateData, ContextItemPatch
from app.schemas.chat import ChatRequest, ContextItemCreate, ContextItemInfo, ContextItemUpdate, ModelInfo, PromptTemplateInfo
from app.services.chat_application_service import ChatApplicationService
from app.services.llm import stream_chat
from app.storage.chat_file_storage import ChatFileStorage

logger = logging.getLogger(__name__)
router = APIRouter()

# Resolve upload_dir from settings on each call, so test monkeypatches work
_chat_file_storage = ChatFileStorage()


@router.post("")
async def chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发起对话（SSE 流式输出）"""
    svc = ChatApplicationService(db, _chat_file_storage)

    session = await svc.prepare_chat_session(
        user_id=user.id,
        conversation_id=req.conversation_id,
        message=req.message,
        model_id=req.model_id,
        prompt_template=req.prompt_template,
        urls=req.urls,
        url_texts=req.url_texts,
        file_ids=req.file_ids,
        mention_context_item_ids=req.mention_context_item_ids,
        context_rules=req.context_rules,
        thinking_level=req.thinking_level,
        enable_knowledge=req.enable_knowledge,
        knowledge_workspace_id=req.knowledge_workspace_id,
        mode=req.mode or "chat",  # P4.Pre.2
        project_id=req.project_id,  # P4.Pre.2
    )
    if session is None:
        if req.conversation_id:
            raise HTTPException(status_code=404, detail="对话不存在")
        raise HTTPException(status_code=400, detail=f"模型不存在或已禁用: {req.model_id}")

    from app.repositories.workspace_repository import WorkspaceRepository
    from app.services.budget_guard import ensure_workspace_llm_allowed
    ws_id = req.knowledge_workspace_id
    if ws_id is None:
        ws_repo = WorkspaceRepository(db)
        default_ws = await ws_repo.get_default()
        ws_id = default_ws.id if default_ws else None
    await ensure_workspace_llm_allowed(db, ws_id)

    await db.commit()
    conv_id = session.conversation_id
    model_cfg = session.model_cfg
    llm_messages = session.llm_messages

    async def _stream(db_session: AsyncSession):
        collected = []
        reasoning_parts = []
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
                extra_body=model_cfg.get("extra_body"),
            ):
                if chunk.reasoning_content:
                    reasoning_parts.append(chunk.reasoning_content)
                    data = json.dumps({
                        "reasoning_content": chunk.reasoning_content,
                        "conversation_id": conv_id,
                    })
                    yield f"data: {data}\n\n"

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
                        stream_conv_repo = ConversationRepository(db_session)
                        await stream_conv_repo.append_message(
                            conversation_id=conv_id, role="assistant",
                            content=full_text, token_count=token_count,
                        )
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
        ModelInfo(
            id=mc.model_id, name=mc.name, enabled=mc.enabled,
            thinking_supported=mc.thinking_supported,
            thinking_level=mc.thinking_level,
        )
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
    ctx_repo = ContextItemRepository(db)
    items = await ctx_repo.list_items(conv_id, user_id=user.id)
    if not items and not await ctx_repo._verify_conversation_owner(conv_id, user.id):
        raise HTTPException(status_code=404, detail="对话不存在")

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
    ctx_repo = ContextItemRepository(db)

    extracted_text = data.extracted_text
    if data.file_id and not extracted_text:
        extracted_text = _chat_file_storage.read_text(data.file_id)

    create_data = ContextItemCreateData(
        context_type=data.context_type,
        title=data.title,
        file_id=data.file_id,
        url=data.url,
        manual_text=data.manual_text,
        extracted_text=extracted_text,
        enabled=data.enabled,
    )

    item = await ctx_repo.create_item(conv_id, user_id=user.id, data=create_data)
    if item is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    await db.commit()

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
    ctx_repo = ContextItemRepository(db)

    patch = ContextItemPatch(
        title=data.title,
        enabled=data.enabled,
    )

    item = await ctx_repo.update_item(conv_id, item_id, user_id=user.id, patch=patch)
    if item is None:
        raise HTTPException(status_code=404, detail="上下文项不存在")
    await db.commit()

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
    ctx_repo = ContextItemRepository(db)
    deleted = await ctx_repo.delete_item(conv_id, item_id, user_id=user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话或上下文项不存在")
    await db.commit()
    return {"message": "上下文项已删除"}