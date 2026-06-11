"""SQLAlchemy ORM 模型定义"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils import now_cn


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    model_id: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt_template: Mapped[str | None] = mapped_column(String(50))
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")  # P4.Pre.2: chat/presentation/agent
    project_id: Mapped[int | None] = mapped_column(ForeignKey("review_projects.id"))  # P4.Pre.2: 关联审查项目
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    context_items = relationship("ContextItem", back_populates="conversation", cascade="all, delete-orphan", order_by="ContextItem.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    anchor_type: Mapped[str | None] = mapped_column(String(50))  # P4.Pre.5: artifact_draft/artifact_confirmed/review_request/review_round
    anchor_id: Mapped[int | None] = mapped_column(Integer)  # P4.Pre.5: 关联的产物/请求/轮次 ID
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    conversation = relationship("Conversation", back_populates="messages")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    user_prompt_template: Mapped[str | None] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)


class ContextItem(Base):
    __tablename__ = "chat_context_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    context_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    file_id: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(500))
    manual_text: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    conversation = relationship("Conversation", back_populates="context_items")


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    model_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="openai_compatible")
    api_base: Mapped[str] = mapped_column(String(500), nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    temperature: Mapped[float] = mapped_column(default=0.7)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    thinking_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    thinking_level: Mapped[str] = mapped_column(String(10), default="off")
    thinking_adapter: Mapped[str] = mapped_column(String(30), default="none")
    thinking_payload: Mapped[str | None] = mapped_column(Text)
    last_test_status: Mapped[str | None] = mapped_column(String(20))
    last_test_time: Mapped[datetime | None] = mapped_column(DateTime)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)


class SkillConfig(Base):
    __tablename__ = "skill_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(String(500))
    update_url: Mapped[str | None] = mapped_column(String(1000))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # P4.Pre.6: active/inactive
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # P4.Pre.6: 技能版本号
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)


class PiAgentConfig(Base):
    """Pi Agent 独立配置 — 单行记录，所有能力模块集中管理。"""
    __tablename__ = "pi_agent_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    singleton_key: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, default="default")

    # ── LLM 大模型配置 ──
    llm_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="deepseek")
    llm_api_base: Mapped[str] = mapped_column(String(500), nullable=False, default="https://api.deepseek.com/v1")
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False, default="deepseek-chat")
    llm_encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    llm_max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    llm_temperature: Mapped[float] = mapped_column(default=0.7)

    # ── Search Tool（知识库检索）配置 ──
    search_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    search_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="builtin")
    search_api_base: Mapped[str | None] = mapped_column(String(500))
    search_encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    search_max_results: Mapped[int] = mapped_column(Integer, default=5)

    # ── Vision（读图）配置 ──
    vision_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    vision_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="openai_compatible")
    vision_api_base: Mapped[str | None] = mapped_column(String(500))
    vision_encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    vision_model: Mapped[str | None] = mapped_column(String(100))

    # ── Extension 配置 ──
    extension_path: Mapped[str | None] = mapped_column(String(500))
    extension_max_tool_calls: Mapped[int] = mapped_column(Integer, default=3)
    extension_blocked_tools: Mapped[str] = mapped_column(Text, default="bash,write,edit")

    # ── Skill 安装配置 ──
    skills_install_dir: Mapped[str] = mapped_column(String(500), nullable=False, default="skills")
    skills_registry_url: Mapped[str | None] = mapped_column(String(1000))
    skills_installed_list: Mapped[str | None] = mapped_column(Text)  # JSON: ["skill_id1", ...]

    # ── System Prompt ──
    system_prompt: Mapped[str | None] = mapped_column(Text)

    # ── 通用 ──
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_test_status: Mapped[str | None] = mapped_column(String(20))
    last_test_time: Mapped[datetime | None] = mapped_column(DateTime)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)


class AgentProfile(Base):
    """个人 Agent 配置 — 每个用户拥有一个 Agent Profile。"""
    __tablename__ = "agent_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # user/team/review
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # user.id or workspace.id
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="My Agent")
    system_policy: Mapped[str | None] = mapped_column(Text)  # system prompt for this agent
    allowed_tools_json: Mapped[str | None] = mapped_column(Text)  # JSON: ["search", "rag", "skill_runner", "artifact"]
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active/disabled
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    authorizations = relationship("AgentAuthorization", back_populates="agent", cascade="all, delete-orphan")


class AgentAuthorization(Base):
    """Agent 授权条目 — 控制 Agent 在特定范围内的权限。"""
    __tablename__ = "agent_authorizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agent_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)  # 授权人
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)  # workspace/project/personal
    scope_id: Mapped[int | None] = mapped_column(Integer)  # workspace.id or project.id, null for personal
    permissions_json: Mapped[str | None] = mapped_column(Text)  # JSON: ["read", "write", "search", "execute"]
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    agent = relationship("AgentProfile", back_populates="authorizations")


class AgentRun(Base):
    """Agent 运行实例 — 一次 Agent 对话任务。"""
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agent_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    goal: Mapped[str] = mapped_column(Text, nullable=False)  # 用户目标/指令
    plan_json: Mapped[str | None] = mapped_column(Text)  # JSON: Agent 规划
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planning")  # planning/running/completed/failed
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    total_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    steps = relationship("AgentStep", back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.step_no")
    traces = relationship("ToolCallTrace", back_populates="run", cascade="all, delete-orphan")


class AgentStep(Base):
    """Agent 运行步骤 — ReAct 循环中的每一步。"""
    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)  # 步骤序号
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)  # plan/tool/observe/respond
    tool_name: Mapped[str | None] = mapped_column(String(80))
    input_ref: Mapped[str | None] = mapped_column(Text)  # 输入摘要
    output_ref: Mapped[str | None] = mapped_column(Text)  # 输出摘要
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/running/completed/failed
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    run = relationship("AgentRun", back_populates="steps")


class ToolCallTrace(Base):
    """工具调用追踪 — 记录每次工具调用的详细信息。"""
    __tablename__ = "tool_call_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("agent_steps.id", ondelete="SET NULL"))
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    input_json: Mapped[str | None] = mapped_column(Text)  # JSON: 输入参数摘要
    output_ref: Mapped[str | None] = mapped_column(Text)  # 输出摘要
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/running/completed/failed/blocked
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, default="low")  # low/medium/high
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")  # none/pending/approved/rejected
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    run = relationship("AgentRun", back_populates="traces")


class MCPServerConfig(Base):
    """MCP Server 配置 — 外部工具服务器连接信息。"""
    __tablename__ = "mcp_server_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int | None] = mapped_column(Integer, index=True)  # null = global
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    server_type: Mapped[str] = mapped_column(String(30), nullable=False, default="stdio")  # stdio/sse/http
    endpoint_ref: Mapped[str] = mapped_column(String(500), nullable=False)  # command or URL
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active/disabled
    metadata_json: Mapped[str | None] = mapped_column(Text)  # JSON: extra config
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn, onupdate=now_cn)

    policies = relationship("MCPToolPolicy", back_populates="server", cascade="all, delete-orphan")


class MCPToolPolicy(Base):
    """MCP 工具策略 — 控制工具调用权限和审批要求。"""
    __tablename__ = "mcp_tool_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("mcp_server_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    allowed_roles_json: Mapped[str | None] = mapped_column(Text)  # JSON: ["owner", "admin", "member"]
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, default="low")  # low/medium/high
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)

    server = relationship("MCPServerConfig", back_populates="policies")


class AgentApprovalRequest(Base):
    """Agent 审批请求 — 高风险操作需人工审批。"""
    __tablename__ = "agent_approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    trace_id: Mapped[int | None] = mapped_column(ForeignKey("tool_call_traces.id", ondelete="SET NULL"))
    requester_id: Mapped[int] = mapped_column(Integer, nullable=False)  # agent or user who triggered
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)  # P4.Pre.4: 指定审批人，创建时必填
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)  # tool_call/write/notify/archive
    payload_ref: Mapped[str | None] = mapped_column(Text)  # JSON: action details
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/approved/rejected
    decision_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


# ─── P4.D: 通知与评论模型 ─────────────────────────────────────────


class Notification(Base):
    """P4.D.1: 通知 — 跨 Phase 基础通知模型，覆盖审查/审批/评论/提及场景。"""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)  # review_request/review_round/agent_approval/artifact/comment
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # review_request_created/review_round_approved/review_round_rejected/artifact_confirmed/agent_approval/comment_reply/mention
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unread")  # unread/read/archived
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)


class Comment(Base):
    """P4.D.2: 评论 — 审查任务/产物页的评论，支持回复和 @提及。"""
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # review_request/review_round/artifact/knowledge_source
    object_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="SET NULL"))  # 回复
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cn)
