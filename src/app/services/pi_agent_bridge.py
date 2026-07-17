"""PiAgentBridge — 方案 A: Pi Agent RPC 子进程桥接服务 (P3.B.4)

架构: FastAPI → PiAgentBridge → pi --mode rpc 子进程
职责:
  - spawn/stop Pi 子进程
  - 发送 prompt/steer/followUp/abort 命令
  - 接收 Pi 事件流 → 写入 AgentRun/Step/Trace + 创建审批请求
  - 转换为 SSE 推送前端

参考: poc-b/scripts/run_pocb_pi_rpc_v3.py (已验证的 POC 客户端)
"""

import asyncio
import json
import logging
import os
import select
import subprocess
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AgentProfile, AgentRun, PiAgentConfig
from app.repositories.agent_repository import AgentApprovalRepository, AgentRunRepository
from app.repositories.pi_agent_config_repository import PiAgentConfigRepository
from app.services.crypto import decrypt_key
from app.utils import now_cn

logger = logging.getLogger(__name__)

# 使用项目本地 node_modules/.bin/pi (由 @earendil-works/pi-coding-agent 提供 CLI)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
PI_BIN = str(_PROJECT_ROOT / "node_modules" / ".bin" / "pi")
EXT_DIR = str(_PROJECT_ROOT / "src" / "agent" / "extensions")

# 活动 bridge 注册表：审批通过后可恢复被拦截的工具调用
_active_bridges: dict[int, "PiAgentBridge"] = {}
# run_id → 一次性审批放行工具列表
_one_shot_approvals: dict[int, list[str]] = {}
# run_id → 运行期 RAG/内部 API 令牌
_run_tokens: dict[int, str] = {}


def register_active_bridge(run_id: int, bridge: "PiAgentBridge") -> None:
    _active_bridges[run_id] = bridge


def unregister_active_bridge(run_id: int) -> None:
    _active_bridges.pop(run_id, None)
    _run_tokens.pop(run_id, None)


def get_active_bridge(run_id: int) -> Optional["PiAgentBridge"]:
    return _active_bridges.get(run_id)


def get_run_token(run_id: int) -> str | None:
    return _run_tokens.get(run_id)


def set_run_token(run_id: int, token: str) -> None:
    _run_tokens[run_id] = token


def grant_one_shot_approval(run_id: int, tool_name: str) -> None:
    tools = _one_shot_approvals.setdefault(run_id, [])
    if tool_name not in tools:
        tools.append(tool_name)


def consume_one_shot_approvals(run_id: int) -> list[str]:
    return list(_one_shot_approvals.pop(run_id, []))


# Pi RPC 事件类型 → 业务映射
_KEY_EVENTS = frozenset({
    "agent_start", "agent_end", "turn_start", "turn_end",
    "message_start", "message_end", "message_update",
    "tool_execution_start", "tool_execution_end",
    "tool_call", "tool_result", "response",
    "auto_retry_start", "auto_retry_end",
})


class PiAgentBridge:
    """Pi Agent RPC 桥接 — 管理 pi --mode rpc 子进程的生命周期和事件流。"""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._cmd_id = 0
        self._all_events: list[dict] = []
        self._start_time: float | None = None
        self._profile: AgentProfile | None = None
        self._run: AgentRun | None = None
        self._run_repo: AgentRunRepository | None = None
        self._approval_repo: AgentApprovalRepository | None = None
        self._db: AsyncSession | None = None
        self._run_token: str | None = None
        self._approval_event: asyncio.Event | None = None
        self._pending_approved_tools: list[str] = []

    @staticmethod
    def _build_extension_env(
        *,
        base_env: dict,
        allowed_tools: list[str],
        scope_json: str,
        user_id: int,
        run_id: int,
        run_token: str,
        api_base: str,
        one_shot_approved: list[str] | None = None,
    ) -> dict:
        """构造传给 Pi Extension 的环境变量（工具白名单/授权范围/RAG 凭证）。"""
        env = dict(base_env)
        env["AGENT_ALLOWED_TOOLS"] = ",".join(allowed_tools) if allowed_tools else ""
        env["AGENT_SCOPE_JSON"] = scope_json
        env["AGENT_USER_ID"] = str(user_id)
        env["AGENT_RUN_ID"] = str(run_id)
        env["AGENT_RUN_TOKEN"] = run_token
        env["AGENT_API_BASE"] = api_base
        env["AGENT_ONE_SHOT_APPROVED"] = ",".join(one_shot_approved or [])
        return env

    def _resolve_extension_path(self, configured_path: str | None) -> str:
        """解析 Extension 路径。

        兼容旧配置：历史 POC 路径 `poc-b/scripts/extensions/agent-limiter.ts`
        不应继续作为生产默认值；若配置为空、指向旧 POC 路径或文件不存在，统一回退到正式目录。
        """
        default_path = os.path.join(EXT_DIR, "agent-limiter.ts")
        if not configured_path:
            return default_path
        normalized = configured_path.replace("\\", "/")
        if "poc-b/scripts/extensions/agent-limiter.ts" in normalized:
            return default_path
        path = Path(configured_path)
        if not path.is_absolute():
            path = _PROJECT_ROOT / configured_path
        if not path.exists():
            logger.warning("[PiAgentBridge] Extension 不存在，回退默认路径: %s -> %s", configured_path, default_path)
            return default_path
        return str(path)

    async def start(self, profile: AgentProfile, run: AgentRun, db: AsyncSession) -> bool:
        """启动 Pi 子进程，绑定到指定的 AgentRun。"""
        self._profile = profile
        self._run = run
        self._db = db
        self._run_repo = AgentRunRepository(db)
        self._approval_repo = AgentApprovalRepository(db)

        # 从 pi_agent_config 读取 LLM 配置
        pi_config_repo = PiAgentConfigRepository(db)
        pi_config = await pi_config_repo.get_or_create()

        # 解密 API Key
        from app.config import get_settings
        settings = get_settings()
        jwt_secret = settings.get("auth", {}).get("secret_key", os.environ.get("JWT_SECRET", ""))
        api_key = decrypt_key(pi_config.llm_encrypted_api_key, jwt_secret) if pi_config.llm_encrypted_api_key else ""

        if not api_key:
            logger.error("[PiAgentBridge] API Key 缺失，无法启动 Pi 子进程")
            return False

        # 构建启动参数
        provider = pi_config.llm_provider  # deepseek / openai / openai_compatible
        model = pi_config.llm_model
        ext_path = self._resolve_extension_path(pi_config.extension_path)
        system_prompt = profile.system_policy or pi_config.system_prompt

        # 确定环境变量
        env = dict(os.environ)
        if provider == "deepseek":
            env["DEEPSEEK_API_KEY"] = api_key
        else:
            env["OPENAI_API_KEY"] = api_key
            if pi_config.llm_api_base:
                env["OPENAI_API_BASE"] = pi_config.llm_api_base

        args = [
            PI_BIN, "--mode", "rpc", "--no-session",
            "--provider", provider, "--model", model,
            "--extension", ext_path,
        ]
        if system_prompt:
            args.extend(["--system-prompt", system_prompt])

        # 解析 profile 工具白名单 + 授权范围，注入 Extension 环境变量
        allowed_tools: list[str] = []
        if profile.allowed_tools_json:
            try:
                parsed = json.loads(profile.allowed_tools_json)
                if isinstance(parsed, list):
                    allowed_tools = [str(t) for t in parsed]
            except (json.JSONDecodeError, TypeError):
                pass

        from app.repositories.agent_repository import AgentAuthorizationRepository
        auth_repo = AgentAuthorizationRepository(db)
        auths = await auth_repo.list_by_agent(profile.id)
        scope_payload = {
            "default_scope_type": profile.default_scope_type or "personal",
            "authorizations": [],
        }
        for a in auths:
            perms: list = []
            if a.permissions_json:
                try:
                    parsed_perms = json.loads(a.permissions_json)
                    if isinstance(parsed_perms, list):
                        perms = parsed_perms
                except (json.JSONDecodeError, TypeError):
                    perms = []
            scope_payload["authorizations"].append({
                "scope_type": a.scope_type,
                "scope_id": a.scope_id,
                "permissions": perms,
            })
        import secrets
        self._run_token = secrets.token_urlsafe(24)
        api_base = os.environ.get(
            "AGENT_API_BASE",
            f"http://127.0.0.1:{os.environ.get('SERVER_PORT', '17957')}",
        )
        one_shot = consume_one_shot_approvals(run.id)
        env = self._build_extension_env(
            base_env=env,
            allowed_tools=allowed_tools,
            scope_json=json.dumps(scope_payload, ensure_ascii=False),
            user_id=run.user_id,
            run_id=run.id,
            run_token=self._run_token,
            api_base=api_base,
            one_shot_approved=one_shot,
        )
        set_run_token(run.id, self._run_token)
        # 不用 --no-tools，让 Pi 默认加载内置工具，Extension 负责限制

        try:
            self._proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1, env=env,
            )
            self._start_time = time.monotonic()
            register_active_bridge(run.id, self)
            logger.info("[PiAgentBridge] PID=%d, provider=%s, model=%s, ext=%s, allowed_tools=%s",
                        self._proc.pid, provider, model, ext_path, allowed_tools)
            # 等待进程稳定
            await asyncio.sleep(3)
            if not self.is_alive:
                stderr = self._read_stderr()
                logger.error("[PiAgentBridge] 进程启动失败: %s", stderr[:500])
                unregister_active_bridge(run.id)
                return False
            return True
        except Exception as e:
            logger.exception("[PiAgentBridge] 启动异常")
            unregister_active_bridge(run.id)
            return False

    def resume_after_approval(self, tool_name: str) -> bool:
        """审批通过后通知活动子进程继续（followUp），并记录一次性放行。"""
        self._pending_approved_tools.append(tool_name)
        if self._approval_event is not None:
            self._approval_event.set()
        if not self.is_alive:
            return False
        try:
            self.send_command(
                "followUp",
                message=f"[approval] 工具 {tool_name} 已批准，请继续完成目标。",
            )
            return True
        except Exception:
            logger.exception("[PiAgentBridge] followUp after approval failed")
            return False

    def stop(self):
        """停止 Pi 子进程。"""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        logger.info("[PiAgentBridge] 已停止")

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def send_command(self, cmd_type: str, **kwargs) -> int:
        """向 Pi 子进程发送 JSONL 命令。返回命令 ID。"""
        self._cmd_id += 1
        cmd = {"type": cmd_type, "id": self._cmd_id, **kwargs}
        line = json.dumps(cmd, ensure_ascii=False)
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        logger.info("[PiAgentBridge] → %s (id=%d)", cmd_type, self._cmd_id)
        return self._cmd_id

    async def stream_events(self, timeout: int = 120) -> AsyncGenerator[dict, None]:
        """读取 Pi 事件流，同时写入 DB 和推送 SSE。

        这是方案 A 的核心：Python 侧监听 Pi 事件 → 写入 AgentRun/Step/Trace + 创建审批。
        """
        start = time.monotonic()
        step_no = 0
        tool_call_count = 0

        # 更新 run 状态
        await self._run_repo.update_status(self._run, "running")
        yield {"type": "agent_start", "run_id": self._run.id, "goal": self._run.goal}

        while time.monotonic() - start < timeout and self.is_alive:
            # 非阻塞读取 stdout
            readable, _, _ = select.select([self._proc.stdout], [], [], 1.0)
            if readable:
                line = self._proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("[PiAgentBridge] 非JSON行: %s", line[:200])
                    continue

                evt_type = data.get("type", "unknown")
                self._all_events.append(data)

                # ── 事件 → DB + SSE 转换 ──
                if evt_type == "turn_start":
                    step_no += 1
                    yield {"type": "turn_start", "step_no": step_no,
                            "max_steps": 10, "run_id": self._run.id}

                elif evt_type == "turn_end":
                    yield {"type": "turn_end", "step_no": step_no, "run_id": self._run.id}
                    # 更新 run 统计
                    self._run.total_steps = step_no
                    self._run.total_tool_calls = tool_call_count

                elif evt_type == "message_update":
                    content = data.get("content", "")
                    if content:
                        yield {"type": "message_update", "text": content, "run_id": self._run.id}

                elif evt_type == "message_start":
                    yield {"type": "message_start", "run_id": self._run.id}

                elif evt_type == "message_end":
                    yield {"type": "message_end", "run_id": self._run.id}

                elif evt_type == "tool_call" or evt_type == "tool_execution_start":
                    tool_name = data.get("toolName", data.get("tool_name", "?"))
                    tool_call_count += 1
                    # 写入 ToolCallTrace
                    trace = await self._run_repo.add_trace(
                        run_id=self._run.id,
                        tool_name=tool_name,
                        input_json=json.dumps(data.get("input", data.get("arguments", {})), ensure_ascii=False)[:1000],
                        risk_level="high" if tool_name in {"bash", "write", "edit"} else "low",
                    )
                    yield {"type": "tool_call", "tool_name": tool_name,
                            "trace_id": trace.id, "step_no": step_no, "run_id": self._run.id}

                elif evt_type == "tool_result" or evt_type == "tool_execution_end":
                    tool_name = data.get("toolName", "?")
                    output = data.get("output", data.get("result", ""))
                    yield {"type": "tool_result", "tool_name": tool_name,
                            "result": output, "run_id": self._run.id}

                elif evt_type == "agent_end":
                    # 收尾 — 更新 run
                    self._run.total_steps = step_no
                    self._run.total_tool_calls = tool_call_count
                    await self._run_repo.update_status(self._run, "completed")
                    yield {"type": "agent_end", "run_id": self._run.id,
                            "steps": step_no, "tool_calls": tool_call_count}
                    break

                elif evt_type == "auto_retry_start":
                    attempt = data.get("attempt", "?")
                    yield {"type": "auto_retry", "attempt": attempt, "run_id": self._run.id}

                elif evt_type == "response":
                    # Pi RPC 协议的 response 事件（命令执行确认）
                    pass

            # 非阻塞读取 stderr（Extension 日志 / 审批拦截）
            stderr_data = self._read_stderr()
            if stderr_data:
                for line in stderr_data.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    # 检查 Extension 审批拦截日志
                    if "[EXCEEDED]" in line:
                        yield {"type": "step_limit_exceeded", "message": line, "run_id": self._run.id}
                    elif "BLOCKED" in line:
                        # Extension 拦截了高风险工具 → 创建审批请求
                        yield {"type": "tool_blocked", "message": line, "run_id": self._run.id}
                        # 从日志提取工具名
                        for blocked_tool in ["bash", "write", "edit"]:
                            if blocked_tool in line:
                                approval = await self._approval_repo.create(
                                    run_id=self._run.id,
                                    requester_id=self._run.user_id,
                                    approver_id=self._run.user_id,  # P4.Pre.4: Agent 所有者作为默认审批人
                                    action_type=f"tool_call:{blocked_tool}",
                                    payload_ref=line[:1000],
                                )
                                yield {"type": "approval_required", "approval_id": approval.id,
                                        "tool_name": blocked_tool, "run_id": self._run.id}

        # 如果循环结束但未收到 agent_end
        if self.is_alive and step_no > 0:
            # 超时但进程仍在运行
            self._run.total_steps = step_no
            self._run.total_tool_calls = tool_call_count
            await self._run_repo.update_status(self._run, "completed",
                                                error_message="Stream timeout, no agent_end received")
            yield {"type": "agent_end", "run_id": self._run.id,
                    "steps": step_no, "tool_calls": tool_call_count, "timeout": True}

    def _read_stderr(self) -> str:
        """非阻塞读取 stderr。"""
        try:
            if self._proc is None:
                return ""
            if self._proc.poll() is not None:
                return self._proc.stderr.read()
            chunks = []
            fd = self._proc.stderr.fileno()
            while True:
                ready, _, _ = select.select([fd], [], [], 0)
                if not ready:
                    break
                data = os.read(fd, 65536)
                if not data:
                    break
                chunks.append(data.decode('utf-8', errors='replace'))
            return "".join(chunks) if chunks else ""
        except Exception:
            return ""

    async def cleanup(self):
        """清理：停止子进程，确保 run 状态最终化。"""
        if self._run is not None:
            unregister_active_bridge(self._run.id)
        self.stop()
        if self._run and self._run_repo and self._run.status in ("planning", "running"):
            await self._run_repo.update_status(self._run, "failed",
                                                error_message="Pi subprocess terminated unexpectedly")