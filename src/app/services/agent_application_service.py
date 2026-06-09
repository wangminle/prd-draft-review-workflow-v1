"""AgentApplicationService — 方案 A: 通过 PiAgentBridge 委派给 Pi 子进程 (P3.B.4)

架构变更: 不再自建 ReAct 循环，而是 spawn `pi --mode rpc` 子进程。
  - Pi agent-core 负责 ReAct 循环、LLM 调用、工具编排
  - Pi Extension (agent-limiter.ts) 负责步数限制、工具拦截、审批门控
  - Python 侧负责: 监听事件流 → 写入 AgentRun/Step/Trace → SSE 推送前端
  - Python 侧负责: 审批请求创建/查询/处理（前端审批面板）

保留的能力:
  - start_run: 创建 AgentRun 记录
  - execute_via_pi: 启动 Pi 子进程并监听事件流（SSE）
  - execute_via_pi_sync: 收集全部事件后返回
"""

import json
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AgentProfile, AgentRun, User
from app.repositories.agent_repository import AgentRunRepository
from app.services.pi_agent_bridge import PiAgentBridge

logger = logging.getLogger(__name__)


class AgentApplicationService:
    """Agent 运行服务 — 通过 PiAgentBridge 委派执行给 Pi 子进程。"""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._run_repo = AgentRunRepository(db)

    async def start_run(self, profile: AgentProfile, user: User, goal: str,
                        conversation_id: int | None = None) -> AgentRun:
        """创建 Agent Run 记录。"""
        run = await self._run_repo.create(
            agent_id=profile.id,
            user_id=user.id,
            goal=goal,
            conversation_id=conversation_id,
        )
        return run

    async def execute_via_pi(self, run: AgentRun, profile: AgentProfile,
                              db: AsyncSession) -> AsyncGenerator[dict, None]:
        """方案 A: 启动 Pi 子进程并监听事件流，通过 SSE 逐步返回。"""
        bridge = PiAgentBridge()
        started = await bridge.start(profile, run, db)
        if not started:
            await self._run_repo.update_status(run, "failed", error_message="Pi 子进程启动失败")
            yield {"type": "error", "message": "Pi Agent 子进程启动失败，请检查 pi CLI 和 API Key 配置"}
            return

        try:
            # 发送 prompt 命令
            bridge.send_command("prompt", message=run.goal)
            # 监听事件流
            async for event in bridge.stream_events(timeout=120):
                yield event
        except Exception as e:
            logger.exception("[AgentAppSvc] Pi 事件流异常")
            await self._run_repo.update_status(run, "failed", error_message=str(e))
            yield {"type": "error", "message": str(e)}
        finally:
            await bridge.cleanup()

    async def execute_via_pi_sync(self, run: AgentRun, profile: AgentProfile,
                                   db: AsyncSession) -> dict:
        """同步版本 — 收集全部事件后返回最终结果。"""
        events = []
        final_text = ""
        async for event in self.execute_via_pi(run, profile, db):
            events.append(event)
            if event.get("type") == "message_update":
                final_text += event.get("text", "")
        return {
            "run_id": run.id,
            "final_text": final_text,
            "events": events,
            "total_steps": run.total_steps,
            "total_tool_calls": run.total_tool_calls,
        }