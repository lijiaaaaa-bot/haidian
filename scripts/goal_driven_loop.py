#!/usr/bin/env python3
"""Goal-Driven entry for haidian urban design open call.

Pattern: lidangzzz goal-driven (github.com/lidangzzz/goal-driven)

  Master has exactly 3 jobs:
    1. create a subagent
    2. check if the subagent is still alive
    3. when subagent claims done, verify criteria

  Master does NOT pass feedback, does NOT format failures, does NOT tell
  the subagent what to fix.  The subagent reads the repo state itself and
  decides what to change.

Usage:
  python3 scripts/goal_driven_loop.py --submission submissions/<login>/<slug>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from constraints.engine import CheckOutcome, ConstraintEngine  # noqa: E402

POLL_SECONDS = 5 * 60  # lidangzzz: check every 5 minutes

# --- tools the subagent can use ---

TOOL_READ_FILE = {
    "name": "read_file",
    "description": "读取仓库内任意文件的全文。可以读 brief/site-package/、submission 文件、schema、templates。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对于仓库根目录的文件路径"}
        },
        "required": ["path"],
    },
}

TOOL_WRITE_FILE = {
    "name": "write_file",
    "description": "写一个文件到你的 submission 目录下。JSON/GeoJSON 会被预校验。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对于仓库根目录的文件路径，必须在 submissions/<slug>/ 下"},
            "content": {"type": "string", "description": "文件完整内容"},
        },
        "required": ["path", "content"],
    },
}

TOOL_RUN_PYTHON = {
    "name": "run_python",
    "description": "运行一段 Python 代码。可以调 ConstraintEngine 验证你的提交、做空间计算。cwd 锁在仓库内、禁网络、30s 超时。",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要执行的 Python 代码"},
        },
        "required": ["code"],
    },
}

SYSTEM_PROMPT = textwrap.dedent("""\
你是百年京张AI创新带城市设计的方案生成者。你是全权工作者——Master 不告诉你
哪里错了，你自己读、自己判断、自己改、自己验证。

## 你的目标

在 {submission_path}/ 下生成完整的 formal 城市设计方案包。

## 工作方式

1. 先读 brief/site-package/design_brief.json 了解任务
2. 读 brief/site-package/agent_taskbook.json 了解六大 agent 任务和边界条款
3. 读 brief/site-package/schemas/ 了解各 JSON 的 schema
4. 读 templates/proposal.md 了解方案模板
5. 读 data/source_registry.json 了解可用资料来源
6. 修改 submissions/{slug}/ 下的文件——proposal.md、GeoJSON、metrics、matrices、图纸
7. 用 run_python 验证你的方案——调 ConstraintEngine.validate() 看还有哪些约束没过
8. 重复 6-7 直到你认为所有约束都满足

## 关键约束

- 所有 JSON/GeoJSON 必须符合 brief/site-package/schemas/ 的 schema
- proposal.md 不得声称官方批准、不得编造控规数据
- 空间数据必须使用 EPSG:4548 投影计算面积
- 图纸用 matplotlib 技术图解风格，含标题、图例、来源标注
- provisional 边界必须明确标注

## 文件读写规则

- 读：可以读 brief/、templates/、data/、docs/、submissions/{slug}/、schema/
- 写：只能写 submissions/{slug}/ 下的文件
- 不要改 manifest.json（Master 收尾时统一刷新）
- 所有 JSON 写入前用 run_python 做 json.loads 校验

## 完成

当你认为方案满足所有约束后，告诉 Master 你完成了。Master 会独立验证；
如果还有问题，你会被重新叫起来继续改。""")

SUBMISSION_TOOLS = [TOOL_READ_FILE, TOOL_WRITE_FILE, TOOL_RUN_PYTHON]


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# --- tool handlers ---

def _handle_read_file(path: str) -> str:
    target = (ROOT / path).resolve()
    if ROOT not in target.parents and target != ROOT:
        return f"错误：路径 {path} 不在仓库内"
    if not target.is_file():
        return f"错误：文件不存在 {path}"
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > 30_000:
        text = text[:15_000] + "\n\n... (truncated) ...\n\n" + text[-15_000:]
    return text


def _handle_write_file(path: str, content: str) -> str:
    target = (ROOT / path).resolve()
    if ROOT not in target.parents and target != ROOT:
        return f"错误：路径 {path} 不在仓库内"
    allowed = ROOT / "submissions"
    if allowed not in target.parents:
        return f"错误：只能写 submissions/ 下的文件，不能写 {path}"
    rel = str(target.relative_to(ROOT))
    for blocked in SANDBOX_BLOCKED_WRITES:
        if rel.startswith(blocked):
            return f"错误：禁止写 {blocked} — 这不是你的提交包，不能改裁判"
    if "manifest.json" in target.name:
        return f"错误：不要改 manifest.json"
    # JSON 预校验
    if target.suffix in (".json", ".geojson"):
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return f"错误：{target.suffix} 格式无效 — {e}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"已写入 {path} ({len(content)} 字符)"


def _handle_run_python(code: str) -> str:
    tmp = ROOT / ".goal-driven" / "_tmp_script.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(code, encoding="utf-8")
    try:
        r = subprocess.run(
            [sys.executable, str(tmp)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        out = r.stdout
        if r.stderr:
            out += "\n[stderr]\n" + r.stderr[-2000:]
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return "超时（30s）"
    finally:
        tmp.unlink(missing_ok=True)


def _tool_input(args: dict, *keys: str) -> str:
    for k in keys:
        if k in args:
            return args[k]
    return args.get(list(args.keys())[0], "") if args else ""

TOOL_HANDLERS = {
    "read_file": lambda a: _handle_read_file(_tool_input(a, "path", "file_path")),
    "write_file": lambda a: _handle_write_file(
        _tool_input(a, "path", "file_path"),
        _tool_input(a, "content", "contents", "text"),
    ),
    "run_python": lambda a: _handle_run_python(_tool_input(a, "code", "python_code", "script")),
}


# --- Ollama subagent ---

# Dual-model: writer (Chinese prose) + coder (JSON/GeoJSON/code)
MODELS = {
    "writer": os.environ.get("HAIDIAN_WRITER_MODEL", "qwen3.6:35b-a3b"),
    "coder": os.environ.get("HAIDIAN_CODER_MODEL", "qwen3-coder:30b"),
}
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MAX_TOOL_TURNS = 40
MAX_HOURS = 12
SANDBOX_BLOCKED_WRITES = (
    "constraints/", "scripts/", "review-panel/", ".git/", ".goal-driven/",
)


def _ollama_chat(messages: list, tools: list, model: str) -> dict:
    """Single Ollama chat call with retry on timeout."""
    import httpx
    payload = {
        "model": model, "messages": messages, "tools": tools,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 32768},
    }
    for attempt in range(3):
        try:
            r = httpx.post(OLLAMA_URL, json=payload, timeout=600.0)
            r.raise_for_status()
            return r.json()
        except httpx.ReadTimeout:
            if attempt < 2:
                log(f"  ollama timeout, retry {attempt+2}/3...")
                continue
            raise


def _pick_model(failures: list | None, last_model: str) -> str:
    """Route: coder for code/JSON failures, writer for text/compliance."""
    if not failures:
        return MODELS["coder"]
    cats = {r.category for r in failures}
    code_cats = {"spatial", "metric", "attributes", "package"}
    text_cats = {"compliance"}
    if cats & code_cats and not cats & text_cats:
        return MODELS["coder"]
    if cats & text_cats and not cats & code_cats:
        return MODELS["writer"]
    # mixed: alternate
    return MODELS["writer"] if last_model == MODELS["coder"] else MODELS["coder"]


def spawn_subagent(submission: Path, round_memory: str = "",
                   model: str | None = None) -> None:
    """Run an Ollama tool-use session. Blocks until subagent claims done."""
    slug = submission.relative_to(ROOT)
    model = model or MODELS["coder"]
    log(f"spawning {model.split(':')[0]} subagent for {slug}")

    system_msg = SYSTEM_PROMPT.format(submission_path=str(slug), slug=submission.name)
    first_msg = "开始工作。先读 brief/site-package/design_brief.json 了解任务。"
    if round_memory:
        first_msg = round_memory + first_msg

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": first_msg},
    ]

    for turn in range(MAX_TOOL_TURNS):
        resp = _ollama_chat(messages, SUBMISSION_TOOLS, model)
        msg = resp.get("message", {})
        content = msg.get("content", "")

        # check for tool calls (Ollama format)
        tool_calls = msg.get("tool_calls", [])
        if not tool_calls:
            log(f"  subagent finished after {turn+1}t (no tool calls): {content[:100]}")
            break

        # append assistant message
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

        # execute tools
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            handler = TOOL_HANDLERS.get(name)
            if handler:
                result = handler(args)
                arg_preview = str(list(args.values())[0])[:60] if args else ""
                log(f"  {name}({arg_preview}...) → {result[:80].split(chr(10))[0]}")
            else:
                result = f"未知工具: {name}"

            messages.append({
                "role": "tool",
                "content": result,
                "tool_call_id": tc.get("id", ""),
            })
    else:
        log(f"  subagent hit max {MAX_TOOL_TURNS} turns")


# --- Master ---

def scaffold(submission: Path, args: argparse.Namespace) -> None:
    cmd = [
        sys.executable, str(ROOT / "scripts" / "scaffold_ai_submission.py"),
        str(submission), "--stage", "formal",
        "--agent-id", args.agent_id, "--agent-name", args.agent_name,
        "--proposal-title", args.title,
    ]
    log(f"scaffolding {submission.relative_to(ROOT)}")
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        log("scaffold failed:\n" + r.stderr)
        raise SystemExit(1)


def criteria_met(engine: ConstraintEngine, submission: Path) -> tuple[bool, list]:
    results = engine.validate(submission.relative_to(ROOT))
    failures = [r for r in results if r.outcome in (CheckOutcome.FAIL, CheckOutcome.ERROR)]
    return len(failures) == 0, failures


def gate2_review(submission: Path) -> tuple[bool, str]:
    """v1 stub: Gate 2 (7-judge panel) — returns (passed, findings).
    TODO: parallel DeepSeek calls per review-panel/statutes.json"""
    slug = submission.relative_to(ROOT)
    # Check for common quality failures the CODE constraints miss
    issues = []

    # Check proposal has real content (not just scaffold)
    proposal = submission / "proposal.md"
    if proposal.exists():
        text = proposal.read_text(encoding="utf-8")
        h2s = [l for l in text.split("\n") if l.startswith("## ")]
        if len(h2s) < 8:
            issues.append(f"proposal.md 只有 {len(h2s)} 个章节（期望 ≥8） — 内容不完整")
        if "agent.6" not in text and "运营" not in text:
            issues.append("agent.6 运营机制缺失")

    # Check GeoJSON are not scaffold placeholders
    land_use = submission / "geometry" / "land_use.geojson"
    if land_use.exists():
        import json as _json
        gj = _json.loads(land_use.read_text(encoding="utf-8"))
        if len(gj.get("features", [])) <= 4:
            issues.append(f"land_use.geojson 只有 {len(gj.get('features',[]))} 个feature — 像脚手架占位")

    # Check figures are real (not 118-byte scaffold)
    for fig in ["site-overview.png", "land-use-structure.png", "key-areas.png"]:
        fp = submission / "assets" / "figures" / fig
        if fp.exists() and fp.stat().st_size < 10000:
            issues.append(f"{fig} 太小 ({fp.stat().st_size}B) — 可能是占位图")

    if not issues:
        return True, ""
    return False, "; ".join(issues)


def main():
    p = argparse.ArgumentParser(description="Goal-Driven entry for haidian urban design")
    p.add_argument("--submission", required=True,
                   help="submission dir, e.g. submissions/<login>/<slug>")
    p.add_argument("--agent-id", default="goal-driven-agent")
    p.add_argument("--agent-name", default="Goal-Driven Agent")
    p.add_argument("--title", default="AI 城市设计方案")
    p.add_argument("--dry-run", action="store_true",
                   help="validate once and exit")
    args = p.parse_args()

    submission = (ROOT / args.submission).resolve()
    if (ROOT / "submissions").resolve() not in submission.parents:
        p.error(f"--submission must be inside {ROOT / 'submissions'}")

    if not submission.exists():
        scaffold(submission, args)

    engine = ConstraintEngine(ROOT)
    engine.load_registry()

    if args.dry_run:
        ok, failures = criteria_met(engine, submission)
        print(f"dry-run: {len(failures)} failures")
        for r in failures:
            print(f"  {r.constraint_id}  {r.detail}")
        return 0 if ok else 1

    # --- lidangzzz loop ---
    started_at = time.time()
    last_failures = None
    last_model = MODELS["coder"]

    while True:
        # 1. check time
        if (time.time() - started_at) / 3600 > MAX_HOURS:
            log(f"MAX_HOURS ({MAX_HOURS}h) reached — escalating")
            return 1

        # 2. criteria check — Gate 1 (CODE)
        ok, failures = criteria_met(engine, submission)
        if ok:
            log("Gate 1 PASS — running Gate 2")
            ok2, findings = gate2_review(submission)
            if ok2:
                log("Gate 2 PASS — criteria met, DONE")
                return 0
            log(f"Gate 2: {findings} — fixing with writer model")
            spawn_subagent(submission, model=MODELS["writer"],
                           round_memory=f"Gate 1 全部通过但 Gate 2 审查发现：\n{findings}\n\n请修复。")
            last_failures = None
            continue

        # 3. pick model + round memory
        model = _pick_model(failures, last_model)
        memory = ""
        if last_failures:
            ids = {r.constraint_id for r in last_failures}
            mem_ids = {r.constraint_id for r in failures}
            fixed = ids - mem_ids
            still = ids & mem_ids
            memory = f"上一轮({last_model.split(':')[0]})你修复后：已解决 {len(fixed)} 条，仍失败 {len(still)} 条。"
            if fixed:
                memory += f" 已修复: {', '.join(sorted(fixed)[:5])}."
            if still:
                memory += f" 仍失败: {', '.join(sorted(still)[:5])}."
            memory += "\n\n"

        # 4. spawn subagent
        log(f"criteria not met ({len(failures)} failures){' — fixed '+str(len(fixed)) if last_failures and fixed else ''}, "
            f"model={model.split(':')[0]}")
        spawn_subagent(submission, round_memory=memory, model=model)
        last_failures = failures
        last_model = model
        last_failures = failures


if __name__ == "__main__":
    raise SystemExit(main())
