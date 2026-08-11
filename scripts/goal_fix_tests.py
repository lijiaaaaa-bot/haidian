#!/usr/bin/env python3
"""Goal-Driven autonomous bug fix — 3 upgrades:
  1. Smart verifier: parses pytest output into structured failures
  2. Dual backend: local MLX (fast/free) or DeepSeek (strong debug)
  3. Git bisect helper: narrows blame with git log + diff

Usage:
    python3 scripts/goal_fix_tests.py                        # MLX local
    HAIDIAN_BACKEND=deepseek python3 scripts/goal_fix_tests.py  # DeepSeek
    HAIDIAN_VERBOSE=1 python3 scripts/goal_fix_tests.py     # Show details
"""

from __future__ import annotations

import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.mlx_client import mlx_chat

MODEL = "Indelwin/Qwen3-ToolAgent-GRPO-MLX"
BACKEND = os.environ.get("HAIDIAN_BACKEND", "mlx")
VERBOSE = os.environ.get("HAIDIAN_VERBOSE") == "1"
MAX_TURNS = 20

# ── 1. Smart Verifier ──────────────────────────────────────────
def verify_smart() -> tuple[int, str]:
    """Returns (exit_code, structured_failure_summary)."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
        cwd=ROOT, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    if r.returncode == 0:
        return 0, "全部通过 ✓"

    # Extract structured info
    failed_tests = re.findall(r'FAILED (tests/\S+)', out)
    traceback_files = re.findall(r'File "(scripts/\S+\.py)", line (\d+)', out)
    error_msgs = re.findall(r'AssertionError: (.+)', out)

    summary = []
    summary.append(f"{len(failed_tests)} 个测试失败:")
    for t in failed_tests[:10]:
        summary.append(f"  ❌ {t}")
    if traceback_files:
        summary.append(f"\n关键文件 (最可能的问题位置):")
        seen = set()
        for f, line in traceback_files[:8]:
            key = f"{f}:{line}"
            if key not in seen:
                seen.add(key)
                summary.append(f"  📍 {key}")
    if error_msgs:
        summary.append(f"\n错误信息样本:")
        for e in error_msgs[:3]:
            summary.append(f"  💬 {e[:200]}")

    return r.returncode, "\n".join(summary)


# ── 2. Git bisect helper ───────────────────────────────────────
def git_context() -> str:
    """Recent commits + diff summary to narrow blame."""
    lines = []
    r = subprocess.run(["git", "log", "--oneline", "-8"], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        lines.append("最近提交:")
        lines.append(r.stdout.strip())
    r = subprocess.run(["git", "diff", "--stat", "HEAD~1"], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        lines.append("\n最近一次提交的改动:")
        lines.append(r.stdout.strip())
    return "\n".join(lines) if lines else "(无法获取 git 信息)"


# ── 3. Dual backend ───────────────────────────────────────────
def chat(messages: list, tools: list, model: str) -> dict:
    """Routes to MLX (local) or DeepSeek (cloud) based on HAIDIAN_BACKEND."""
    if BACKEND == "deepseek":
        return _chat_deepseek(messages, tools)
    return mlx_chat(messages, tools, model)


def _chat_deepseek(messages: list, tools: list) -> dict:
    import anthropic
    key = "/tmp/.hdk"
    api_key = open(key).read().strip() if os.path.exists(key) else os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(
        base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic"),
        api_key=api_key)

    sys_msg = ""
    msgs = []
    for m in messages:
        if m["role"] == "system":
            sys_msg = m["content"]
        else:
            msgs.append({"role": m["role"], "content": str(m.get("content", ""))})

    tool_defs = []
    for t in (tools or []):
        tool_defs.append({
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        })

    resp = client.messages.create(
        model="deepseek-v4-pro", max_tokens=4096, system=sys_msg,
        messages=msgs, tools=tool_defs)

    text = ""
    calls = []
    for b in resp.content:
        if hasattr(b, "text") and b.text:
            text += b.text
        elif hasattr(b, "name"):
            calls.append({
                "id": b.id or "c0",
                "type": "function",
                "function": {"name": b.name, "arguments": b.input or {}},
            })
    return {"message": {"role": "assistant", "content": text, "tool_calls": calls}}


# ── Tools ──────────────────────────────────────────────────────
SYSTEM = """你是代码修复专家。唯一目标：让 pytest 全部通过。

工具 (XML格式): <tool_call><function=name><parameter=k>v</parameter></function></tool_call>
只改 scripts/ 和 constraints/ 下的 .py/.json 文件。每次修完跑 run_command 验证。"""


def handle(name: str, args: dict) -> str:
    if name == "read_file":
        p = (ROOT / args["path"]).resolve()
        if p.exists():
            return p.read_text()[:12000]
        return f"不存在: {args['path']}"
    if name == "write_file":
        p = (ROOT / args["path"]).resolve()
        rel = str(p.relative_to(ROOT))
        if not rel.startswith(("scripts/", "constraints/")):
            return f"禁止写: {rel}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"])
        return f"已写入 {rel}"
    if name == "run_command":
        r = subprocess.run(args["cmd"], shell=True, capture_output=True, text=True, timeout=60, cwd=ROOT)
        return f"exit={r.returncode}\n{r.stdout[-4000:]}{r.stderr[-2000:]}"
    return f"未知: {name}"


TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "读文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "写文件(只scripts/constraints/)", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "执行shell命令", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
]


def main():
    # Run smart verifier
    exit_code, summary = verify_smart()
    print(f"[verify] {exit_code} — {summary.split(chr(10))[0]}")
    if VERBOSE:
        print(summary)

    if exit_code == 0:
        print("全部通过，无需修复 ✓")
        return 0

    # Build initial prompt with git context
    git_info = git_context()
    prompt = f"""修复以下测试失败。

## 调试指南（重要！）
1. 先读失败的测试文件（如 tests/test_agent_scaffold_and_self_check.py），看它 import 了哪些模块
2. 找到被 import 的模块（如 scripts/scaffold_ai_submission.py），那里才是 bug 来源
3. 不要猜文件名，从测试代码的 import 语句追踪

{summary}

Git 上下文：
{git_info}"""
    print(f"\n[prompt] {prompt[:500]}...")

    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]

    for turn in range(MAX_TURNS):
        resp = chat(messages, TOOLS, MODEL)
        msg = resp["message"]
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            print(f"[{turn+1}t] done: {content[:150]}")
            break

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc["function"]
            name, args = fn["name"], fn.get("arguments", {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except: args = {}
            result = handle(name, args)
            preview = str(list(args.values())[:1])[:50] if args else ""
            print(f"  {name}({preview}) → {result[:100].split(chr(10))[0]}")
            messages.append({"role": "tool", "content": result, "tool_call_id": tc["id"]})
    else:
        print(f"  max {MAX_TURNS} turns")

    exit_code, summary = verify_smart()
    print(f"\n最终: {exit_code} ({'PASS ✓' if exit_code == 0 else 'FAIL ✗'})")
    if VERBOSE and exit_code != 0:
        print(summary)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
