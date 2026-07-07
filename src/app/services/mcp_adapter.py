"""MCP Adapter — 轻量 MCP Server 客户端 (P3.C.4)

支持 stdio 和 SSE 两种传输模式连接外部 MCP Server。
工具调用前检查 MCPToolPolicy。
"""

import asyncio
import json
import logging
import os
import subprocess
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import MCPServerConfig, MCPToolPolicy

logger = logging.getLogger(__name__)


class MCPClient:
    """MCP Server 客户端 — 管理与外部 MCP Server 的连接。"""

    def __init__(self, server_config: MCPServerConfig):
        self._config = server_config
        self._proc: subprocess.Popen | None = None
        self._connected = False
        self._tools: list[dict] = []

    async def connect(self) -> bool:
        """连接到 MCP Server。"""
        try:
            if self._config.server_type == "stdio":
                return await self._connect_stdio()
            elif self._config.server_type in ("sse", "http"):
                return await self._connect_sse()
            else:
                logger.error("[MCP] 不支持的 server_type: %s", self._config.server_type)
                return False
        except Exception as e:
            logger.exception("[MCP] 连接失败: %s", e)
            return False

    async def _connect_stdio(self) -> bool:
        """通过 stdio 连接 MCP Server。"""
        try:
            self._proc = subprocess.Popen(
                self._config.endpoint_ref.split(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            # 发送 initialize 请求
            init_msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ai-review-agent", "version": "0.3.3"},
                },
            })
            self._proc.stdin.write(init_msg + "\n")
            self._proc.stdin.flush()
            # 读取响应（非阻塞）
            import select as _select
            ready, _, _ = _select.select([self._proc.stdout], [], [], 5.0)
            if ready:
                line = self._proc.stdout.readline()
                if line:
                    resp = json.loads(line.strip())
                    if resp.get("result"):
                        self._connected = True
                        logger.info("[MCP] stdio 连接成功: %s", self._config.name)
                        return True
            logger.warning("[MCP] stdio 连接超时或无响应")
            return False
        except Exception as e:
            logger.exception("[MCP] stdio 连接失败")
            return False

    async def _connect_sse(self) -> bool:
        """通过 SSE/HTTP 连接 MCP Server。"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._config.endpoint_ref}/health")
                if resp.status_code == 200:
                    self._connected = True
                    logger.info("[MCP] SSE 连接成功: %s", self._config.name)
                    return True
        except Exception as e:
            logger.warning("[MCP] SSE 连接失败: %s", e)
        return False

    async def list_tools(self) -> list[dict]:
        """获取 MCP Server 提供的工具列表。"""
        if not self._connected:
            return []
        if self._config.server_type == "stdio":
            return await self._list_tools_stdio()
        return self._tools

    async def _list_tools_stdio(self) -> list[dict]:
        """通过 stdio 获取工具列表。"""
        try:
            msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            })
            self._proc.stdin.write(msg + "\n")
            self._proc.stdin.flush()
            import select as _select
            ready, _, _ = _select.select([self._proc.stdout], [], [], 5.0)
            if ready:
                line = self._proc.stdout.readline()
                if line:
                    resp = json.loads(line.strip())
                    tools = resp.get("result", {}).get("tools", [])
                    self._tools = tools
                    return tools
        except Exception:
            pass
        return []

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """调用 MCP Server 上的工具。"""
        if not self._connected:
            return {"error": "Not connected to MCP server"}
        if self._config.server_type == "stdio":
            return await self._call_tool_stdio(tool_name, arguments)
        return {"error": f"Tool call not implemented for {self._config.server_type}"}

    async def _call_tool_stdio(self, tool_name: str, arguments: dict) -> dict:
        """通过 stdio 调用工具。"""
        try:
            import select as _select
            msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            })
            self._proc.stdin.write(msg + "\n")
            self._proc.stdin.flush()
            ready, _, _ = _select.select([self._proc.stdout], [], [], 30.0)
            if ready:
                line = self._proc.stdout.readline()
                if line:
                    resp = json.loads(line.strip())
                    return resp.get("result", {"error": "No result"})
            return {"error": "Tool call timeout"}
        except Exception as e:
            return {"error": str(e)}

    async def disconnect(self):
        """断开连接。"""
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None
        self._connected = False


class MCPAdapterManager:
    """MCP 适配器管理器 — 管理所有 MCP Server 连接。"""

    def __init__(self):
        self._clients: dict[int, MCPClient] = {}

    async def get_or_connect(self, db: AsyncSession, server_id: int) -> Optional[MCPClient]:
        """获取已连接的客户端，或建立新连接。"""
        if server_id in self._clients and self._clients[server_id]._connected:
            return self._clients[server_id]

        result = await db.execute(
            select(MCPServerConfig).where(MCPServerConfig.id == server_id)
        )
        config = result.scalar_one_or_none()
        if not config:
            return None

        client = MCPClient(config)
        if await client.connect():
            self._clients[server_id] = client
            return client
        return None

    async def check_policy(self, db: AsyncSession, server_id: int,
                           tool_name: str, user_role: str = "member") -> dict:
        """检查工具调用策略。返回 {allowed, requires_approval, risk_level}。"""
        result = await db.execute(
            select(MCPToolPolicy).where(
                MCPToolPolicy.server_id == server_id,
                MCPToolPolicy.tool_name == tool_name,
            )
        )
        policy = result.scalar_one_or_none()
        if not policy:
            return {"allowed": True, "requires_approval": False, "risk_level": "low"}

        allowed_roles = []
        if policy.allowed_roles_json:
            try:
                allowed_roles = json.loads(policy.allowed_roles_json)
            except (json.JSONDecodeError, TypeError):
                allowed_roles = None
            if not isinstance(allowed_roles, list):
                allowed_roles = None

        if allowed_roles is None:
            allowed = False
        else:
            allowed = not allowed_roles or user_role in allowed_roles

        return {
            "allowed": allowed,
            "requires_approval": policy.requires_approval,
            "risk_level": policy.risk_level,
        }

    async def disconnect_all(self):
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()


# 全局实例
mcp_adapter = MCPAdapterManager()
