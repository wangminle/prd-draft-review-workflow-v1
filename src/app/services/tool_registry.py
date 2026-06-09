"""ToolRegistry — 注册和管理 Agent 可调用的工具 (P3.C.1)

方案 A 变更: 工具编排由 Pi agent-core 负责，Python 侧只提供工具定义（schema）供 API 查询。
  - 内置工具不再有 Python handler，而是注册为 Pi Skills
  - ToolRegistry 只保留 schema 信息，用于前端展示和 API 端点
  - 实际工具调用发生在 Pi 子进程内部（LLM 决策 → Extension 检查 → 执行）
"""

import logging

logger = logging.getLogger(__name__)


class ToolDefinition:
    """工具定义 — schema 信息，不含 handler（方案 A）。"""
    def __init__(self, name: str, label: str, description: str,
                 parameters: dict, risk_level: str = "low",
                 requires_approval: bool = False, skill_id: str | None = None):
        self.name = name
        self.label = label
        self.description = description
        self.parameters = parameters
        self.risk_level = risk_level
        self.requires_approval = requires_approval
        self.skill_id = skill_id  # 对应的 Pi Skill 或内置 Skill

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "parameters": self.parameters,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "skill_id": self.skill_id,
        }


class ToolRegistry:
    """全局工具注册表 — schema 信息注册，不含执行逻辑。"""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool
        logger.info("[ToolRegistry] 注册工具 schema: %s (risk=%s)", tool.name, tool.risk_level)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self, allowed_tools: list[str] | None = None) -> list[ToolDefinition]:
        tools = list(self._tools.values())
        if allowed_tools is not None:
            tools = [t for t in tools if t.name in allowed_tools]
        return tools

    def list_schemas(self, allowed_tools: list[str] | None = None) -> list[dict]:
        return [t.to_schema() for t in self.list_tools(allowed_tools)]


# ─── 全局实例 ──────────────────────────────────────────────

_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _registry


def register_builtin_tools():
    """注册内置工具 schema（应用启动时调用一次）。

    方案 A: 这些工具由 Pi agent-core 内置 Skills 提供，
    Python 侧只记录 schema 信息供 API 查询和前端展示。
    """
    _registry.register(ToolDefinition(
        name="search",
        label="知识检索",
        description="检索团队知识库中的资料。输入查询关键词，返回相关文档片段。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "top_k": {"type": "integer", "description": "返回结果数量", "default": 5},
            },
            "required": ["query"],
        },
        risk_level="low",
    ))

    _registry.register(ToolDefinition(
        name="rag",
        label="RAG 检索",
        description="检索知识库并构建上下文，用于增强回答。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "workspace_id": {"type": "integer", "description": "团队空间 ID"},
                "top_k": {"type": "integer", "description": "返回结果数量", "default": 5},
            },
            "required": ["query"],
        },
        risk_level="low",
    ))

    _registry.register(ToolDefinition(
        name="skill_runner",
        label="Skill 运行",
        description="运行指定的 Skill（如需求分类、逐篇分析等）。",
        parameters={
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Skill ID"},
                "input_text": {"type": "string", "description": "输入文本"},
            },
            "required": ["skill_id"],
        },
        risk_level="medium",
        requires_approval=True,  # 高风险，需要 Extension 审批门控
    ))

    _registry.register(ToolDefinition(
        name="artifact",
        label="产物生成",
        description="生成审查讲解产物（摘要、对比表、问答卡等）。",
        parameters={
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "产物类型: summary/comparison/qa_card"},
                "content": {"type": "string", "description": "输入内容"},
            },
            "required": ["type", "content"],
        },
        risk_level="low",
    ))

    # Pi 内置高风险工具（由 Extension agent-limiter.ts 拦截）
    _registry.register(ToolDefinition(
        name="bash",
        label="Shell 命令",
        description="执行 Shell 命令。",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
        risk_level="high",
        requires_approval=True,
    ))

    _registry.register(ToolDefinition(
        name="write",
        label="文件写入",
        description="写入文件。",
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
        risk_level="high",
        requires_approval=True,
    ))

    _registry.register(ToolDefinition(
        name="edit",
        label="文件编辑",
        description="编辑文件。",
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}},
        risk_level="high",
        requires_approval=True,
    ))

    logger.info("[ToolRegistry] 内置工具 schema 注册完成: %s", list(_registry._tools.keys()))