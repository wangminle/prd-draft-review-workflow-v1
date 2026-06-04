"""Repositories — 结构化数据查询和写入层。

职责边界：
- 结构化数据查询和写入
- 不负责文件系统访问、日志落盘、HTTPException
"""

from app.repositories.conversation_repository import ConversationRepository
from app.repositories.context_item_repository import ContextItemRepository, ContextItemCreateData, ContextItemPatch
from app.repositories.user_repository import UserRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.prompt_template_repository import PromptTemplateRepository
from app.repositories.skill_config_repository import SkillConfigRepository

from app.repositories.review_task_repository import (
    ReviewTaskRepository,
    NewReviewTask,
    TaskProgressPatch,
    DocAnalysisPayload,
    SystemReviewPayload,
)

from app.repositories.review_project_repository import (
    ReviewProjectRepository,
    ProjectInfoRow,
)
from app.repositories.review_context_repository import (
    ReviewContextRepository,
    ContextCreateData,
    ContextPatch,
)
from app.repositories.review_prompt_repository import (
    ReviewPromptRepository,
    ReviewPromptCreateData,
    ReviewPromptPatch,
)

from app.repositories.workspace_repository import WorkspaceRepository
from app.repositories.knowledge_source_repository import KnowledgeSourceRepository, ProjectSourceRefRepository

__all__ = [
    "ConversationRepository",
    "ContextItemRepository",
    "ContextItemCreateData",
    "ContextItemPatch",
    "UserRepository",
    "ModelConfigRepository",
    "PromptTemplateRepository",
    "SkillConfigRepository",
    "WorkspaceRepository",
    "KnowledgeSourceRepository",
    "ProjectSourceRefRepository",
    "ReviewTaskRepository",
    "NewReviewTask",
    "TaskProgressPatch",
    "DocAnalysisPayload",
    "SystemReviewPayload",
    "ReviewProjectRepository",
    "ProjectInfoRow",
    "ReviewContextRepository",
    "ContextCreateData",
    "ContextPatch",
    "ReviewPromptRepository",
    "ReviewPromptCreateData",
    "ReviewPromptPatch",
]
