// Pi Extension: Agent 运行限制
// 功能: 步数计数、工具白名单（默认拒绝）、授权范围校验、高风险审批门控、真实 RAG 检索
// 用法: pi --mode rpc --no-session -e ./agent-limiter.ts

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

let stepCount = 0;
let toolCallCount = 0;
const MAX_STEPS = 10;
const MAX_TOOL_CALLS = 20;
// 高风险工具：文件系统读/写与 shell，一律需一次性审批
const BLOCKED_TOOLS = ["write", "edit", "bash", "read"];
const DEFAULT_SAFE_TOOLS = ["rag_search"];

function parseList(envVal: string | undefined): string[] {
  if (!envVal || !envVal.trim()) return [];
  return envVal.split(",").map((s) => s.trim()).filter(Boolean);
}

type AgentScope = {
  default_scope_type: string;
  authorizations: Array<{
    scope_type: string;
    scope_id: number | null;
    permissions: string[];
  }>;
};

function parseScope(envVal: string | undefined): AgentScope {
  const fallback: AgentScope = { default_scope_type: "personal", authorizations: [] };
  if (!envVal || !envVal.trim()) return fallback;
  try {
    const parsed = JSON.parse(envVal);
    if (!parsed || typeof parsed !== "object") return fallback;
    return {
      default_scope_type: typeof parsed.default_scope_type === "string"
        ? parsed.default_scope_type
        : "personal",
      authorizations: Array.isArray(parsed.authorizations) ? parsed.authorizations : [],
    };
  } catch {
    return fallback;
  }
}

function isWorkspaceAuthorized(scope: AgentScope, workspaceId: number): boolean {
  return scope.authorizations.some(
    (a) => a.scope_type === "workspace" && Number(a.scope_id) === workspaceId,
  );
}

// 空白名单 = 仅默认安全工具（deny-by-default），不再放行全部工具
const configuredTools = parseList(process.env.AGENT_ALLOWED_TOOLS);
const effectiveAllowed = configuredTools.length > 0 ? configuredTools : DEFAULT_SAFE_TOOLS;
const ONE_SHOT_APPROVED = new Set(parseList(process.env.AGENT_ONE_SHOT_APPROVED));
const AGENT_SCOPE = parseScope(process.env.AGENT_SCOPE_JSON);
const AGENT_API_BASE = (process.env.AGENT_API_BASE || "http://127.0.0.1:17957").replace(/\/$/, "");
const AGENT_RUN_ID = process.env.AGENT_RUN_ID || "";
const AGENT_RUN_TOKEN = process.env.AGENT_RUN_TOKEN || "";
const ONE_SHOT_FILE = ".agent_one_shot_approved";

/** 消费一次审批：先看启动时 env，再看 Bridge 运行时写入的 sidecar 文件。 */
function consumeOneShot(toolName: string): boolean {
  if (ONE_SHOT_APPROVED.has(toolName)) {
    ONE_SHOT_APPROVED.delete(toolName);
    return true;
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const fs = require("node:fs") as typeof import("node:fs");
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const path = require("node:path") as typeof import("node:path");
    const filePath = path.resolve(process.cwd(), ONE_SHOT_FILE);
    if (!fs.existsSync(filePath)) return false;
    const lines = fs.readFileSync(filePath, "utf8")
      .split("\n")
      .map((s: string) => s.trim())
      .filter(Boolean);
    const idx = lines.indexOf(toolName);
    if (idx < 0) return false;
    lines.splice(idx, 1);
    fs.writeFileSync(filePath, lines.length ? `${lines.join("\n")}\n` : "", "utf8");
    return true;
  } catch {
    return false;
  }
}

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

    // 2) 一次性审批优先于白名单（否则审批后仍被白名单拦死）
    if (consumeOneShot(toolName)) {
      console.log(`[agent-limiter] ALLOWED(one-shot approval): ${toolName}`);
      return {};
    }

    // 3) 白名单强制执行（deny-by-default）；rag_search 始终可用
    if (!effectiveAllowed.includes(toolName) && toolName !== "rag_search") {
      console.log(`[agent-limiter] BLOCKED: 工具 ${toolName} 不在白名单 ${effectiveAllowed.join(",")}`);
      return {
        block: true,
        reason: `工具 ${toolName} 不在允许列表中`,
      };
    }

    // 4) 高风险工具拦截（需人工审批；审批后走 one-shot）
    if (BLOCKED_TOOLS.includes(toolName)) {
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

  // 真实 RAG：调用 FastAPI /api/agent/runs/{id}/rag，并按 AGENT_SCOPE_JSON 校验范围
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

      const requestedScope = (params.scope as string) || (
        AGENT_SCOPE.default_scope_type === "personal" ? "personal" : "workspace"
      );
      const workspaceId = params.workspace_id ?? null;

      if (requestedScope === "workspace" && workspaceId != null) {
        if (!isWorkspaceAuthorized(AGENT_SCOPE, Number(workspaceId))) {
          return {
            content: [{
              type: "text",
              text: JSON.stringify({
                error: `workspace_id=${workspaceId} 不在 Agent 授权范围内`,
                results: [],
                total: 0,
              }),
            }],
            details: { error: "scope_denied", workspace_id: workspaceId },
          };
        }
      }

      // 默认 personal：禁止擅自指定未授权 workspace
      if (
        AGENT_SCOPE.default_scope_type === "personal"
        && requestedScope === "workspace"
        && workspaceId != null
        && !isWorkspaceAuthorized(AGENT_SCOPE, Number(workspaceId))
      ) {
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              error: "当前 Agent 默认仅个人资料范围，未授权该 workspace",
              results: [],
              total: 0,
            }),
          }],
          details: { error: "scope_denied" },
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
            workspace_id: workspaceId,
            scope: requestedScope,
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
