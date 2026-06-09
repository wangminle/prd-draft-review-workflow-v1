// Pi Extension: Agent 运行限制
// 功能: 步数计数、工具调用拦截、审批模拟
// 用法: pi --mode rpc --no-session -e ./agent-limiter.ts

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

let stepCount = 0;
let toolCallCount = 0;
const MAX_STEPS = 10;
const MAX_TOOL_CALLS = 3;
const BLOCKED_TOOLS = ["write", "edit", "bash"]; // 高风险工具（模拟审批拦截）

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
        reason: `已达最大工具调用次数(${MAX_TOOL_CALLS})，当前工具: ${toolName}`
      };
    }

    // 2) 高风险工具拦截（模拟审批挂起）
    if (BLOCKED_TOOLS.includes(toolName)) {
      console.log(`[agent-limiter] BLOCKED: 高风险工具 ${toolName} 需要人工审批`);
      return {
        block: true,
        reason: `高风险工具 ${toolName} 需要人工审批（当前为自动拦截模式）`
      };
    }

    console.log(`[agent-limiter] ALLOWED: 工具调用 #${toolCallCount}: ${toolName}`);
    return {}; // 不拦截
  });

  // 工具结果回调（审计日志）
  pi.on("tool_result", async (event, _ctx) => {
    const toolName = event.toolName;
    console.log(`[agent-limiter] 工具结果: ${toolName}`);
    return {};
  });

  // Agent 结束时输出统计
  pi.on("agent_end", async (_event, _ctx) => {
    console.log(`[agent-limiter] Agent 结束: 步骤=${stepCount}, 工具调用=${toolCallCount}`);
  });

  // 注册一个自定义工具（模拟 RAG 检索）
  pi.registerTool({
    name: "rag_search",
    label: "RAG 检索",
    description: "检索团队知识库中的资料。输入查询关键词，返回相关文档片段。",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "检索关键词" },
        workspace_id: { type: "integer", description: "团队空间 ID" },
      },
      required: ["query"],
    },
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      // 模拟 RAG 检索结果（真实集成时调用 FastAPI 的 RetrievalService）
      const mockResults = [
        { title: "需求评审流程规范", snippet: "需求评审应遵循分类→逐篇分析→体系评审→报告生成四步流程...", score: 0.95 },
        { title: "PRD写作规范", snippet: "PRD 应包含目标、用户场景、功能需求、非功能需求...", score: 0.82 },
      ];
      return {
        content: [{ type: "text", text: JSON.stringify({ results: mockResults, query: params.query, total: mockResults.length }) }],
        details: { mock: true, real_integration_needed: true },
      };
    },
  });
}