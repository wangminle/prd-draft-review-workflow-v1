"""ChatApplicationService — 对话用例编排。

职责边界：
- 组合 ConversationRepository、ContextItemRepository、ChatFileStorage、ModelConfig 读取
- 新建/加载对话、保存消息、装配上下文、流结束后落库
- 不负责 SSE/流式协议包装、HTTPException
- 事务边界由 router 控制（service 只 flush）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Conversation, ContextItem, Message, ModelConfig, PromptTemplate, User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.context_item_repository import ContextItemRepository
from app.services.crypto import decrypt_key, mask_key
from app.services.llm import ChatMessage, PromptTemplate as LLMPromptTemplate, build_messages
from app.storage.chat_file_storage import ChatFileStorage

logger = logging.getLogger(__name__)


@dataclass
class ChatSession:
    conversation_id: int
    model_cfg: dict
    llm_messages: list[ChatMessage]


class ChatApplicationService:
    """对话用例编排：会话创建、消息保存、上下文装配、流结束后落库。"""

    def __init__(self, db: AsyncSession, file_storage: ChatFileStorage):
        self._db = db
        self._conv_repo = ConversationRepository(db)
        self._ctx_repo = ContextItemRepository(db)
        self._file_storage = file_storage

    async def create_or_load_conversation(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        message: str,
        model_id: str,
        prompt_template: str | None,
        mode: str = "chat",  # P4.Pre.2
        project_id: int | None = None,  # P4.Pre.2
    ) -> tuple[int, Conversation | None]:
        if conversation_id is None:
            conv = await self._conv_repo.create_conversation(
                user_id=user_id,
                title=message[:50] if len(message) > 50 else message,
                model_id=model_id,
                prompt_template=prompt_template,
                mode=mode,
                project_id=project_id,
            )
            await self._db.flush()
            return conv.id, conv
        else:
            conv = await self._conv_repo.get_conversation(conversation_id, user_id=user_id)
            return conv.id if conv else None, conv

    async def save_user_message(self, conversation_id: int, content: str) -> Message:
        msg = await self._conv_repo.append_message(
            conversation_id=conversation_id, role="user", content=content,
        )
        await self._db.flush()
        return msg

    async def save_assistant_message(self, conversation_id: int, content: str, token_count: int = 0) -> Message:
        msg = await self._conv_repo.append_message(
            conversation_id=conversation_id, role="assistant",
            content=content, token_count=token_count,
        )
        await self._db.flush()
        return msg

    async def load_prompt_template(self, template_name: str | None) -> LLMPromptTemplate | None:
        if not template_name:
            return None
        result = await self._db.execute(
            select(PromptTemplate).where(PromptTemplate.name == template_name)
        )
        pt = result.scalar_one_or_none()
        if pt:
            return LLMPromptTemplate(
                name=pt.name,
                description=pt.description or "",
                system_prompt=pt.system_prompt or "",
                user_prompt_template=pt.user_prompt_template or "",
            )
        return None

    async def load_conversation_history(self, conversation_id: int) -> list[ChatMessage]:
        result = await self._db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return [
            ChatMessage(role=m.role, content=m.content)
            for m in result.scalars().all()
        ][:-1]

    def build_file_url_context(
        self,
        *,
        urls: list[str] | None = None,
        url_texts: dict[str, str] | None = None,
        file_ids: list[str] | None = None,
        max_text_len: int = 8000,
    ) -> list[str]:
        parts = []
        if urls:
            texts = url_texts or {}
            for u in urls:
                text = texts.get(u, "")
                if text:
                    parts.append(f"[URL: {u}]\n{text[:max_text_len]}{'...(内容过长，已截断)' if len(text) > max_text_len else ''}")
                else:
                    parts.append(f"URL: {u}")
        if file_ids:
            for fid in file_ids:
                content = self._file_storage.read_text(str(fid))
                if content:
                    parts.append(f"[文件 {fid}]\n{content[:max_text_len]}{'...(内容过长，已截断)' if len(content) > max_text_len else ''}")
        return parts

    async def build_persisted_context(
        self,
        conversation_id: int,
        *,
        user_id: int,
        mention_ids: set[int] | None = None,
        max_text_len: int = 8000,
    ) -> list[str]:
        parts = []
        items = await self._ctx_repo.list_enabled_items(conversation_id, user_id=user_id)
        for item in items:
            if item.manual_text:
                parts.append(f"[规则] {item.manual_text}")
            elif item.file_id:
                if mention_ids and item.id not in mention_ids:
                    continue
                content = item.extracted_text
                if not content:
                    content = self._file_storage.read_text(item.file_id)
                if content:
                    parts.append(f"[文档: {item.title}]\n{content[:max_text_len]}{'...(内容过长，已截断)' if len(content) > max_text_len else ''}")
            elif item.url:
                if item.extracted_text:
                    parts.append(f"[URL: {item.url}]\n{item.extracted_text[:max_text_len]}{'...(内容过长，已截断)' if len(item.extracted_text) > max_text_len else ''}")
                else:
                    parts.append(f"[URL: {item.url}]")
        return parts

    async def get_model_config(self, model_id: str) -> dict | None:
        result = await self._db.execute(
            select(ModelConfig).where(
                ModelConfig.model_id == model_id,
                ModelConfig.deleted_by_user == False,
            )
        )
        mc = result.scalar_one_or_none()
        if mc is None or not mc.enabled:
            return None
        from app.config import get_settings
        secret = get_settings().get("auth", {}).get("secret_key", "")
        api_key = ""
        if mc.encrypted_api_key:
            try:
                api_key = decrypt_key(mc.encrypted_api_key, secret)
            except Exception:
                return None
        return {
            "model_id": mc.model_id,
            "name": mc.name,
            "api_base": mc.api_base,
            "api_key": api_key,
            "llm_model": mc.llm_model,
            "max_tokens": mc.max_tokens,
            "temperature": mc.temperature,
            "enabled": mc.enabled,
            "thinking_supported": mc.thinking_supported,
            "thinking_level": mc.thinking_level,
            "thinking_adapter": mc.thinking_adapter,
            "thinking_payload": mc.thinking_payload,
        }

    async def prepare_chat_session(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        message: str,
        model_id: str,
        prompt_template: str | None,
        urls: list[str] | None = None,
        url_texts: dict[str, str] | None = None,
        file_ids: list[str] | None = None,
        mention_context_item_ids: list[int] | None = None,
        context_rules: list[str] | None = None,
        thinking_level: str | None = None,
        enable_knowledge: bool = False,
        knowledge_workspace_id: int | None = None,
        mode: str = "chat",  # P4.Pre.2
        project_id: int | None = None,  # P4.Pre.2
    ) -> ChatSession | None:
        model_cfg = await self.get_model_config(model_id)
        if not model_cfg:
            return None

        conv_id, conv = await self.create_or_load_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
            model_id=model_id,
            prompt_template=prompt_template,
            mode=mode,  # P4.Pre.2
            project_id=project_id,  # P4.Pre.2
        )
        if conv_id is None:
            return None

        await self.save_user_message(conv_id, message)

        template = await self.load_prompt_template(prompt_template)
        history = await self.load_conversation_history(conv_id)

        context_parts = self.build_file_url_context(
            urls=urls, url_texts=url_texts, file_ids=file_ids,
        )
        persisted = await self.build_persisted_context(
            conv_id, user_id=user_id,
            mention_ids=set(mention_context_item_ids or []),
        )
        context_parts.extend(persisted)

        if context_rules:
            for rule in context_rules:
                context_parts.append(f"[规则] {rule}")

        # P2.C.1: 知识库检索上下文注入
        if enable_knowledge and knowledge_workspace_id:
            knowledge_context = await self.build_knowledge_context(
                query=message,
                workspace_id=knowledge_workspace_id,
                user_id=user_id,
            )
            if knowledge_context:
                context_parts.append(knowledge_context)

        # P4.B.3: Presentation 模式 — 自动注入快速审查结果和项目上下文
        if mode == "presentation" and project_id:
            presentation_context = await self.build_presentation_context(project_id, user_id=user_id)
            if presentation_context:
                context_parts.append(presentation_context)

        context = "\n\n".join(context_parts) if context_parts else None
        llm_messages = build_messages(template, history, message, context)

        if model_cfg.get("thinking_supported") and model_cfg.get("thinking_adapter") != "none":
            from app.services.thinking_adapter import build_thinking_payload
            extra_body = build_thinking_payload(
                thinking_level=model_cfg.get("thinking_level", "off"),
                thinking_adapter=model_cfg.get("thinking_adapter", "none"),
                thinking_payload=model_cfg.get("thinking_payload"),
                runtime_level_override=thinking_level,
            )
            model_cfg["extra_body"] = extra_body

        return ChatSession(
            conversation_id=conv_id,
            model_cfg=model_cfg,
            llm_messages=llm_messages,
        )

    async def build_knowledge_context(
        self,
        query: str,
        workspace_id: int,
        user_id: int | None = None,
        top_k: int = 5,
    ) -> str | None:
        """P2.C.1: 知识库检索上下文构建。

        调用 RetrievalService 检索知识库，将结果格式化为上下文注入对话。

        Args:
            query: 查询文本
            workspace_id: 工作空间 ID
            user_id: 用户 ID（用于权限校验和日志）
            top_k: 返回条数

        Returns:
            格式化的知识上下文字符串，如果没有结果则返回 None
        """
        # 权限校验：用户必须是 workspace 成员
        from app.repositories.workspace_repository import WorkspaceRepository
        from app.services.workspace_access import is_active_member

        ws_repo = WorkspaceRepository(self._db)
        if user_id:
            member = await ws_repo.get_member(workspace_id, user_id)
            if not is_active_member(member):
                logger.warning(f"[KNOWLEDGE] 用户 {user_id} 不是 workspace {workspace_id} 的活跃成员")
                return None

        # 检索知识库
        from app.services.retrieval_service import RetrievalService
        try:
            retrieval = RetrievalService(db_session=self._db)
            response = await retrieval.retrieve(
                query=query,
                workspace_id=workspace_id,
                top_k=top_k,
            )
        except Exception as e:
            logger.error(f"[KNOWLEDGE] 知识检索失败: {e}")
            return None

        if not response.results or all(r.rejected for r in response.results):
            return None

        # 格式化为上下文（编号连续，跳过 rejected 的条目）
        parts = ["[知识库检索结果]"]
        seq = 0
        for r in response.results:
            if r.rejected:
                continue
            seq += 1
            section_info = f"（章节: {r.section}）" if r.section else ""
            parts.append(f"{seq}. [来源ID: {r.source_id}]{section_info} {r.text_snippet}")

        if response.fallback_reason:
            parts.append(f"[检索降级: {response.fallback_reason}]")

        return "\n".join(parts)

    async def build_presentation_context(self, project_id: int, *, user_id: int | None = None) -> str | None:
        """P4.B.3: 构建讲解准备对话模式的自动上下文。

        注入快速审查结果、项目文档摘要和团队知识库上下文，
        帮助用户与 AI 反复迭代优化讲解稿/图示/动画。
        """
        from app.models.review import ReviewProject, ReviewTask, DocAnalysis, SystemReview
        parts = ["[讲解准备模式上下文]"]

        # 加载项目信息
        result = await self._db.execute(
            select(ReviewProject).where(ReviewProject.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            return None

        # 权限校验：用户必须是项目创建者
        if user_id is not None and project.created_by != user_id:
            logger.warning(f"[PRESENTATION] 用户 {user_id} 不是项目 {project_id} 的创建者，拒绝注入上下文")
            return None

        parts.append(f"项目名称: {project.name}")
        if project.description:
            parts.append(f"项目描述: {project.description}")

        # 加载最近的快速审查结果
        task_result = await self._db.execute(
            select(ReviewTask)
            .where(ReviewTask.project_id == project_id, ReviewTask.status == "completed")
            .order_by(ReviewTask.created_at.desc())
            .limit(1)
        )
        latest_task = task_result.scalar_one_or_none()
        if latest_task:
            parts.append(f"\n最近审查任务 (ID: {latest_task.id}, 模式: {latest_task.mode})")

            # 加载逐篇分析结果
            analyses_result = await self._db.execute(
                select(DocAnalysis)
                .where(DocAnalysis.task_id == latest_task.id)
                .order_by(DocAnalysis.created_at)
            )
            analyses = analyses_result.scalars().all()
            if analyses:
                parts.append(f"逐篇分析 ({len(analyses)} 篇):")
                for a in analyses[:5]:  # 最多展示 5 篇摘要
                    category = a.category or "未分类"
                    score = f"评分: {a.quality_score}" if a.quality_score else ""
                    core = a.core_problem or ""
                    parts.append(f"  - {category} {score}: {core[:200]}")

            # 加载体系评审结果
            sys_review_result = await self._db.execute(
                select(SystemReview)
                .where(SystemReview.task_id == latest_task.id)
            )
            sys_review = sys_review_result.scalar_one_or_none()
            if sys_review:
                parts.append("体系评审摘要:")
                if sys_review.business_value:
                    parts.append(f"  业务价值: {sys_review.business_value[:200]}")
                if sys_review.action_plan:
                    parts.append(f"  行动计划: {sys_review.action_plan[:200]}")

        # 加载项目知识上下文
        from app.routers.review import _load_project_knowledge_context
        try:
            knowledge_ctx = await _load_project_knowledge_context(self._db, project_id)
            if knowledge_ctx:
                parts.append(f"\n[项目知识上下文]\n{knowledge_ctx[:2000]}")
        except Exception as e:
            logger.warning(f"[PRESENTATION] 加载项目知识上下文失败: {e}")

        return "\n".join(parts)