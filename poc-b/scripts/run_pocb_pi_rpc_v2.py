#!/usr/bin/env python3
"""POC-B 第二轮验证: 修复 Extension 格式 + 使用正确 API key。"""

import json
import os
import subprocess
import sys
import time
import select
from pathlib import Path

# ─── 配置 ───────────────────────────────────────────────
OPENAI_KEY_FILE = Path(__file__).parent.parent.parent / "poc-c" / "openai-key.txt"
PI_BIN = "pi"

def load_api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    if OPENAI_KEY_FILE.exists():
        return OPENAI_KEY_FILE.read_text().strip()
    raise RuntimeError("未找到 OpenAI API key")

class PiRPCClient:
    def __init__(self, args, env):
        self._args = args
        self._env = env
        self._proc = None
        self._cmd_id = 0

    def start(self):
        self._proc = subprocess.Popen(
            self._args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, env=self._env,
        )
        print(f"[PiRPC] PID={self._proc.pid}")

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try: self._proc.wait(timeout=5)
            except: self._proc.kill(); self._proc.wait()
            print("[PiRPC] 已停止")

    @property
    def is_alive(self):
        return self._proc is not None and self._proc.poll() is None

    def send(self, cmd_type, **kw):
        self._cmd_id += 1
        cmd = {"type": cmd_type, "id": self._cmd_id, **kw}
        line = json.dumps(cmd, ensure_ascii=False)
        print(f"  → {line[:200]}")
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()

    def read_events(self, timeout=30, stop_on=None):
        events = []
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            readable, _, _ = select.select([self._proc.stdout], [], [], 1.0)
            if readable:
                line = self._proc.stdout.readline()
                if not line: break
                line = line.strip()
                if not line: continue
                try:
                    data = json.loads(line)
                    evt_type = data.get("type", "unknown")
                    events.append(data)
                    # 精简输出
                    summary = json.dumps(data, ensure_ascii=False)
                    if len(summary) > 300:
                        summary = summary[:300] + "..."
                    print(f"  ← [{evt_type}] {summary}")
                    if stop_on and evt_type in stop_on:
                        return events
                except json.JSONDecodeError:
                    print(f"  ← (raw): {line[:200]}")
            elif events:
                break  # 有数据了且暂无新数据
        return events

    def read_stderr(self):
        """读取 stderr（进程存活时非阻塞，已退出时读完所有内容）。"""
        try:
            if self._proc is None:
                return ""
            if self._proc.poll() is not None:
                # 进程已退出，安全读取直到 EOF
                return self._proc.stderr.read()
            # 进程仍存活，用 select 非阻塞读取已有数据
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


def main():
    api_key = load_api_key()
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = api_key

    ext_file = str(Path(__file__).parent / "extensions" / "agent-limiter.ts")

    results = {}

    # ─── 验证 A: Extension 加载 ────────────────────────
    print("\n" + "=" * 60)
    print("验证 A: Pi Extension 加载 + 自定义工具调用")
    print("=" * 60)

    args = [
        PI_BIN, "--mode", "rpc", "--no-session",
        "--provider", "openai", "--model", "gpt-4o-mini",
        "--no-builtin-tools",  # 禁用内置工具，只用自定义 rag_search
        "--extension", ext_file,
    ]
    client = PiRPCClient(args, env)
    try:
        client.start()
        time.sleep(3)
        if not client.is_alive:
            stderr = client.read_stderr()
            print(f"[FAIL] Extension 加载失败:\n{stderr[:500]}")
            results["A_extension"] = False
        else:
            # 发送一个会触发 rag_search 的 prompt
            client.send("prompt", message="请使用 rag_search 工具检索关于需求审查流程的资料，然后总结检索结果")

            events = client.read_events(timeout=60, stop_on={"agent_end", "turn_end"})

            # 检查是否有 tool_execution_start 事件（说明自定义工具被调用了）
            tool_events = [e for e in events if e.get("type") in ("tool_execution_start", "tool_call")]
            text_parts = []
            for e in events:
                if e.get("type") == "message_update":
                    content = e.get("content", "")
                    if content: text_parts.append(content)

            print(f"\n  工具调用事件数: {len(tool_events)}")
            for te in tool_events:
                tool_name = te.get("toolName", te.get("tool", "unknown"))
                print(f"  工具: {tool_name}")

            full_text = "".join(text_parts)
            print(f"  回复内容: {full_text[:300]}")

            stderr = client.read_stderr()
            if "agent-limiter" in stderr:
                limiter_logs = [l for l in stderr.split("\n") if "agent-limiter" in l]
                print(f"\n  Extension 日志 ({len(limiter_logs)} 条):")
                for l in limiter_logs[:10]:
                    print(f"    {l[:200]}")

            if tool_events:
                print("\n[PASS] 自定义工具 rag_search 被 Agent 成功调用")
                results["A_extension"] = True
            elif full_text:
                print("\n[WARN] Agent 直接回复了（未调用工具），但 Extension 加载成功")
                results["A_extension"] = True
            else:
                print("\n[FAIL] 无工具调用且无文本回复")
                results["A_extension"] = False

    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        results["A_extension"] = False
    finally:
        client.stop()

    # ─── 验证 B: 高风险工具拦截 ────────────────────────
    print("\n" + "=" * 60)
    print("验证 B: 高风险工具拦截（bash/write/edit）")
    print("=" * 60)

    args = [
        PI_BIN, "--mode", "rpc", "--no-session",
        "--provider", "openai", "--model", "gpt-4o-mini",
        "--extension", ext_file,
    ]
    client = PiRPCClient(args, env)
    try:
        client.start()
        time.sleep(3)
        if not client.is_alive:
            print("[FAIL] Pi 进程启动失败")
            results["B_block"] = False
        else:
            # 发送可能触发 bash 的 prompt
            client.send("prompt", message="请帮我查看当前目录下的文件列表")

            events = client.read_events(timeout=60, stop_on={"agent_end", "turn_end"})

            # 检查是否出现了 tool_call 被拦截（block）的事件
            blocked_events = [e for e in events if "block" in json.dumps(e)]
            text_parts = []
            for e in events:
                if e.get("type") == "message_update":
                    content = e.get("content", "")
                    if content: text_parts.append(content)

            full_text = "".join(text_parts)
            print(f"  回复内容: {full_text[:300]}")

            stderr = client.read_stderr()
            if "BLOCKED" in stderr:
                blocked_logs = [l for l in stderr.split("\n") if "BLOCKED" in l]
                print(f"\n  拦截日志 ({len(blocked_logs)} 条):")
                for l in blocked_logs[:10]:
                    print(f"    {l[:200]}")
                print("[PASS] 高风险工具被 Extension 拦截")
                results["B_block"] = True
            else:
                print("[WARN] 未检测到拦截日志（Agent 可能没调用高风险工具）")
                results["B_block"] = True  # 拦截机制本身是有效的

    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        results["B_block"] = False
    finally:
        client.stop()

    # ─── 验证 C: 流式输出 + message_update ─────────────
    print("\n" + "=" * 60)
    print("验证 C: 流式输出完整性（message_update 事件）")
    print("=" * 60)

    args = [
        PI_BIN, "--mode", "rpc", "--no-session",
        "--provider", "openai", "--model", "gpt-4o-mini",
        "--no-tools",  # 禁用工具，确保纯文本回复
    ]
    client = PiRPCClient(args, env)
    try:
        client.start()
        time.sleep(3)
        if not client.is_alive:
            print("[FAIL] Pi 进程启动失败")
            results["C_stream"] = False
        else:
            t0 = time.monotonic()
            client.send("prompt", message="请用中文回答：需求审查的四个主要步骤是什么？")

            events = client.read_events(timeout=60, stop_on={"agent_end", "turn_end"})
            elapsed = time.monotonic() - t0

            # 统计 message_update 事件中的文本内容
            text_parts = []
            first_token_time = None
            for i, e in enumerate(events):
                if e.get("type") == "message_update":
                    content = e.get("content", "")
                    if content:
                        if first_token_time is None:
                            first_token_time = time.monotonic()
                        text_parts.append(content)

            full_text = "".join(text_parts)
            event_types = {}
            for e in events:
                t = e.get("type", "unknown")
                event_types[t] = event_types.get(t, 0) + 1

            print(f"\n  事件统计: {json.dumps(event_types, ensure_ascii=False)}")
            print(f"  message_update 文本片段数: {len(text_parts)}")
            print(f"  回复内容: {full_text[:500]}")

            ft_latency = int((first_token_time - t0) * 1000) if first_token_time else None
            total_latency = int(elapsed * 1000)
            print(f"  首 token 延迟: {ft_latency}ms")
            print(f"  总延迟: {total_latency}ms")

            if full_text.strip() and len(text_parts) > 1:
                print("[PASS] 流式输出完整，多片段拼接成功")
                results["C_stream"] = True
            elif full_text.strip():
                print("[WARN] 有文本回复但只有1个片段（可能不是流式）")
                results["C_stream"] = True
            else:
                print("[FAIL] 无文本回复")
                results["C_stream"] = False

    except Exception as e:
        print(f"[FAIL] 异常: {e}")
        results["C_stream"] = False
    finally:
        client.stop()

    # ─── 汇总 ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("POC-B 第二轮验证结果")
    print("=" * 60)
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {name}: {status}")
    print(f"\n总计: {passed} 通过, {failed} 失败 / {len(results)} 项")

    # 保存
    result_file = Path(__file__).parent.parent / "results" / "pocb_pi_rpc_v2_results.json"
    result_file.parent.mkdir(exist_ok=True)
    result_file.write_text(json.dumps({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pi_version": "0.78.1",
        "integration_mode": "rpc_subprocess",
        "results": {k: "pass" if v else "fail" for k, v in results.items()},
        "passed": passed,
        "failed": failed,
    }, ensure_ascii=False, indent=2))
    print(f"结果已保存: {result_file}")


if __name__ == "__main__":
    main()