// Pi Extension: Agent 运行限制
// 功能: 步数计数、工具白名单、高风险审批门控、真实 RAG 检索
// 用法: pi --mode rpc --no-session -e ./agent-limiter.ts

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

let stepCount = 0;
let toolCallCount = 0;
const MAX_STEPS = 10;
const MAX_TOOL_CALLS = 20;
const BLOCKED_TOOLS = ["write", "edit", "bash"]; // 高风险工具需审批

function parseList(envVal: string | undefined): string[] {
  if (!envVal || !envVal.trim()) return [];
  return envVal.split(",").map((s) => s.trim()).filter(Boolean);
}

const ALLOWED_TOOLS = parseList(process.env.AGENT_ALLOWED_TOOLS);
const ONE_SHOT_APPROVED = new Set(parseList(process.env.AGENT_ONE_SHOT_APPROVED));
const AGENT_API_BASE = (process.env.AGENT_API_BASE || "http://127.0.0.1:17957").replace(/\/$/, "");
const AGENT_RUN_ID = process.env.AGENT_RUN_ID || "";
const AGENT_RUN_TOKEN = process.env.AGENT_RUN_TOKEN || "";

export default function (pi: ExtensionAPI) {
  // 步数计数：每次 turn 结束后递增并检查上限
  pi.on("turn_end", async (_event, _ctx) => {
    stepCount++;
    if (stepCount >= MAX_STEPS) {
      console.error(`[agent-limiter] [EXCEEDED] 步数已达上限 ${stepCount}/${MAX_STEPS}，建议终止 Agent 运行`);
    } else {
      console.log(`[agent-limiter] 步骤 ${stepCount}/${MAX_STEPS}`);
    }
  });

  // 工具调用拦截
  pi.on("tool_call", async (event, _ctx) => {
    toolCallCount++;
    const toolName = event.toolName;

    // 1) 工具调用次数限制
    if (toolCallCount > MAX_TOOL_CALLS) {
      console.log(`[agent-limiter] BLOCKED: 工具调用次数已达上限(${MAX_TOOL_CALLS}), 当前: ${toolName}`);
      return {
        block: true,
        reason: `已达最大工具调用次数(${MAX_TOOL_CALLS})，当前工具: ${toolName}`,
      };
    }

    // 2) 白名单：若配置了 AGENT_ALLOWED_TOOLS，仅允许列表内工具（rag_search 始终可用）
    if (ALLOWED_TOOLS.length > 0 && !ALLOWED_TOOLS.includes(toolName) && toolName !== "rag_search") {
      console.log(`[agent-limiter] BLOCKED: 工具 ${toolName} 不在白名单 ${ALLOWED_TOOLS.join(",")}`);
      return {
        block: true,
        reason: `工具 ${toolName} 不在允许列表中`,
      };
    }

    // 3) 高风险工具拦截（一次性审批可放行）
    if (BLOCKED_TOOLS.includes(toolName)) {
      if (ONE_SHOT_APPROVED.has(toolName)) {
        ONE_SHOT_APPROVED.delete(toolName);
        console.log(`[agent-limiter] ALLOWED(one-shot approval): ${toolName}`);
        return {};
      }
      console.log(`[agent-limiter] BLOCKED: 高风险工具 ${toolName} 需要人工审批`);
      return {
        block: true,
        reason: `高风险工具 ${toolName} 需要人工审批`,
      };
    }

    console.log(`[agent-limiter] ALLOWED: 工具调用 #${toolCallCount}: ${toolName}`);
    return {};
  });

  pi.on("tool_result", async (event, _ctx) => {
    console.log(`[agent-limiter] 工具结果: ${event.toolName}`);
    return {};
  });

  pi.on("agent_end", async (_event, _ctx) => {
    console.log(`[agent-limiter] Agent 结束: 步骤=${stepCount}, 工具调用=${toolCallCount}`);
  });

  // 真实 RAG：调用 FastAPI /api/agent/runs/{id}/rag
  pi.registerTool({
    name: "rag_search",
    label: "RAG 检索",
    description: "检索团队/个人知识库中的资料。输入查询关键词，返回相关文档片段。",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "检索关键词" },
        workspace_id: { type: "integer", description: "团队空间 ID（可选）" },
        scope: { type: "string", description: "workspace 或 personal，默认 workspace" },
      },
      required: ["query"],
    },
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      if (!AGENT_RUN_ID || !AGENT_RUN_TOKEN) {
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              error: "rag_search 未配置 AGENT_RUN_ID/AGENT_RUN_TOKEN，无法检索",
              results: [],
              total: 0,
            }),
          }],
          details: { error: "missing_run_credentials" },
        };
      }

      const url = `${AGENT_API_BASE}/api/agent/runs/${AGENT_RUN_ID}/rag`;
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Agent-Run-Token": AGENT_RUN_TOKEN,
          },
          body: JSON.stringify({
            query: params.query,
            workspace_id: params.workspace_id ?? null,
            scope: params.scope || "workspace",
            top_k: 5,
          }),
        });
        const text = await resp.text();
        let data: any;
        try {
          data = JSON.parse(text);
        } catch {
          data = { error: text, results: [], total: 0 };
        }
        if (!resp.ok) {
          return {
            content: [{ type: "text", text: JSON.stringify({ error: data.detail || data.error || resp.statusText, results: [], total: 0 }) }],
            details: { error: "http_error", status: resp.status },
          };
        }
        return {
          content: [{ type: "text", text: JSON.stringify(data) }],
          details: { mock: false, total: data.total ?? 0 },
        };
      } catch (err: any) {
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              error: `rag_search 调用失败: ${err?.message || String(err)}`,
              results: [],
              total: 0,
            }),
          }],
          details: { error: "fetch_failed" },
        };
      }
    },
  });
}
