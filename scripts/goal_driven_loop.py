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
6. 修改 {submission_path}/ 下的文件——proposal.md、GeoJSON、metrics、matrices、图纸
7. 用 run_python 验证你的方案——调 ConstraintEngine.validate() 看还有哪些约束没过
8. 重复 6-7 直到你认为所有约束都满足

## 关键约束

- 所有 JSON/GeoJSON 必须符合 brief/site-package/schemas/ 的 schema
- proposal.md 不得声称官方批准、不得编造控规数据
- 空间数据必须使用 EPSG:4548 投影计算面积
- 图纸用 matplotlib 技术图解风格，含标题、图例、来源标注
- provisional 边界必须明确标注

## 文件读写规则

- 读：可以读 brief/、templates/、data/、docs/、{submission_path}/、schema/
- 写：只能写 {submission_path}/ 下的文件
- 不要改 manifest.json（Master 收尾时统一刷新）
- 所有 JSON 写入前用 run_python 做 json.loads 校验

## 专业知识参考

遇到你不理解的概念（如"三区三线""强制措辞""用地分类"），读这些文件：
- brief/site-package/standards/references/three-lines-knowledge.md — 国土空间规划体系
- brief/site-package/agent_taskbook.json — 任务定义、边界条款、强制措辞模板
- templates/proposal.md — 方案模板和引用格式要求
不要猜——用自己的话表达专业知识，不是复制粘贴。

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
    # Prepends the write-sandbox prologue so user code cannot edit harness-owned
    # files (constraints/, scripts/, review-panel/, .git/, .goal-driven/) or
    # manifest.json through run_python — the same policy as the write_file tool.
    tmp.write_text(_run_python_sandbox_prologue() + "\n\n" + code, encoding="utf-8")
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
    # Ollama sometimes wraps arguments differently — try value-only fallback
    for v in args.values():
        if isinstance(v, str) and len(v) < 500:
            return v
    return ""

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
# Single-model override: --model muse-glimmer:30b-mlx uses one model for everything.
MODELS = {
    "writer": os.environ.get("HAIDIAN_WRITER_MODEL", "qwen3.6:35b-a3b"),
    "coder":  os.environ.get("HAIDIAN_CODER_MODEL", "qwen3-coder:30b"),
    "agent":  os.environ.get("HAIDIAN_AGENT_MODEL", "muse-glimmer:30b-mlx"),
    "glm":    os.environ.get("HAIDIAN_GLM_MODEL", "rafw007/glm-4.7-flash-opencode:latest"),
}
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_URL = OLLAMA_BASE_URL + "/api/chat"
OLLAMA_TAGS_URL = OLLAMA_BASE_URL + "/api/tags"
MAX_TOOL_TURNS = 40

# Auto-switch fallbacks: a model that fails repeatedly (see _ollama_chat) is
# replaced by its backup for the rest of the run (coder <-> writer).
MODEL_BACKUPS = {
    MODELS["coder"]: MODELS["writer"],
    MODELS["writer"]: MODELS["coder"],
}
MAX_HOURS = 12
SANDBOX_BLOCKED_WRITES = (
    "constraints/", "scripts/", "review-panel/", ".git/", ".goal-driven/",
)

# Python injected ahead of any user code executed via run_python. It wraps
# builtins.open (and the other common write vectors: os.remove/unlink/rename/
# replace, pathlib.Path.write_text/write_bytes) and raises PermissionError for
# writes to harness-owned paths or manifest.json. Reads are unaffected.
_RUN_PYTHON_SANDBOX_PROLOGUE_BODY = '''
import builtins as _builtins
import os as _os
import pathlib as _pathlib

_orig_open = _builtins.open
_orig_remove = _os.remove
_orig_unlink = _os.unlink
_orig_rename = _os.rename
_orig_replace = _os.replace
_orig_write_text = _pathlib.Path.write_text
_orig_write_bytes = _pathlib.Path.write_bytes

_sandbox_blocked = ("constraints/", "scripts/", "review-panel/", ".git/", ".goal-driven/")

def _sandbox_denied(path):
    p = _os.path.abspath(str(path))
    try:
        rel = _os.path.relpath(p, _sandbox_root)
    except ValueError:
        rel = p
    if rel.startswith(".."):
        rel = p
    if _os.path.basename(rel) == "manifest.json":
        return "manifest.json"
    for blocked in _sandbox_blocked:
        if rel.startswith(blocked):
            return blocked
    return None

def _sandbox_check(path, verb):
    denied = _sandbox_denied(path)
    if denied:
        raise PermissionError("SANDBOX: " + verb + " " + str(path) + " (blocked: " + denied + ")")

def _safe_open(file, mode="r", *args, **kwargs):
    if any(flag in mode for flag in ("w", "a", "x", "+")):
        _sandbox_check(file, "禁止写")
    return _orig_open(file, mode, *args, **kwargs)

def _safe_unlink(path):
    _sandbox_check(path, "禁止删除")
    return _orig_unlink(path)

def _safe_remove(path):
    _sandbox_check(path, "禁止删除")
    return _orig_remove(path)

def _safe_rename(src, dst):
    _sandbox_check(src, "禁止移动")
    _sandbox_check(dst, "禁止移动")
    return _orig_rename(src, dst)

def _safe_replace(src, dst):
    _sandbox_check(src, "禁止替换")
    _sandbox_check(dst, "禁止替换")
    return _orig_replace(src, dst)

def _safe_write_text(self, *args, **kwargs):
    _sandbox_check(str(self), "禁止写")
    return _orig_write_text(self, *args, **kwargs)

def _safe_write_bytes(self, *args, **kwargs):
    _sandbox_check(str(self), "禁止写")
    return _orig_write_bytes(self, *args, **kwargs)

_builtins.open = _safe_open
_os.remove = _safe_remove
_os.unlink = _safe_unlink
_os.rename = _safe_rename
_os.replace = _safe_replace
_pathlib.Path.write_text = _safe_write_text
_pathlib.Path.write_bytes = _safe_write_bytes
'''.strip()


def _run_python_sandbox_prologue() -> str:
    """Build the sandbox prologue for one run_python invocation."""
    return f"_sandbox_root = {str(ROOT)!r}\n" + _RUN_PYTHON_SANDBOX_PROLOGUE_BODY


# Per-model consecutive-failure tracking.  Counters are persisted to
# .goal-driven/model-failures.json so the count survives crash/restart cycles
# (the supervisor in run_autonomous.sh restarts the whole loop on failure):
#   - +1 per failed chat call (after the in-call retries are exhausted)
#   - cleared on any successful chat call
#   - a model with >= 3 consecutive failures is switched to MODEL_BACKUPS and
#     not re-tried for the rest of this process run (_FAILED_THIS_RUN); the
#     next process run gives it one fresh chance (Ollama was hard-restarted).
_FAILED_THIS_RUN: set[str] = set()
_MODEL_FAILURES: dict[str, int] = {}
_FAILURES_LOADED = False


def _load_model_failures() -> None:
    global _FAILURES_LOADED
    if _FAILURES_LOADED:
        return
    try:
        fp = STATE_DIR / "model-failures.json"
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            _MODEL_FAILURES.update(
                {str(k): int(v) for k, v in data.items() if isinstance(v, (int, float))}
            )
    except Exception:
        pass
    _FAILURES_LOADED = True


def _save_model_failures() -> None:
    try:
        fp = STATE_DIR / "model-failures.json"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(_MODEL_FAILURES), encoding="utf-8")
    except Exception:
        pass  # in-memory counting still works; persistence is best-effort


def _record_model_failure(model: str) -> int:
    """Count one more consecutive failure for `model`; returns the new count."""
    _load_model_failures()
    count = _MODEL_FAILURES.get(model, 0) + 1
    _MODEL_FAILURES[model] = count
    _save_model_failures()
    log(f"  model {model} failed {count}x in a row")
    if count >= 3:
        _FAILED_THIS_RUN.add(model)
    return count


def _clear_model_failure(model: str) -> None:
    _load_model_failures()
    if _MODEL_FAILURES.pop(model, None) is not None:
        _save_model_failures()


def _ollama_health_check(max_attempts: int = 12, wait_s: float = 10.0) -> None:
    """Ping /api/tags before a chat; if Ollama is down, wait and retry.

    Absorbs startup latency (run_autonomous.sh hard-restarts Ollama before
    relaunching the loop).  Gives up after max_attempts so a dead server
    crashes the loop and triggers the supervisor's restart instead of hanging.
    """
    import httpx
    for attempt in range(1, max_attempts + 1):
        try:
            r = httpx.get(OLLAMA_TAGS_URL, timeout=10.0)
            if r.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        log(f"  ollama unhealthy (attempt {attempt}/{max_attempts}) — waiting {wait_s}s...")
        time.sleep(wait_s)
    raise RuntimeError(f"Ollama unreachable after {max_attempts} attempts")


def _warmup_model(model: str) -> None:
    """Minimal 'ping' chat so Ollama loads the model before real work."""
    log(f"  warming up {model} ...")
    _ollama_chat([{"role": "user", "content": "ping"}], [], model)
    log(f"  warmup ok: {model}")


def _ollama_chat(messages: list, tools: list, model: str) -> dict:
    """Single Ollama chat call.

    - health-checks /api/tags first (waits for Ollama to come back)
    - retries HTTP 5xx twice with a 10s pause (timeout retries as before)
    - after 3 consecutive failed calls, switches to MODEL_BACKUPS[model]
      within the same call; if the backup is already failed this run, raises
    """
    import httpx
    _ollama_health_check()
    # Model-specific defaults
    opts = {"num_ctx": 32768}
    if "muse-glimmer" in model:
        opts.update({"temperature": 0.6, "top_p": 0.95, "top_k": 64})
    elif "glm" in model:
        opts.update({"temperature": 0.2, "num_ctx": 8192, "num_predict": 1024})
    else:
        opts["temperature"] = 0.2
    payload = {
        "model": model, "messages": messages,
        "stream": False,
        "options": opts,
    }
    if tools:
        payload["tools"] = tools
    timeout_s = 120.0 if "glm" in model else 600.0
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            r = httpx.post(OLLAMA_URL, json=payload, timeout=timeout_s)
            r.raise_for_status()
            _clear_model_failure(model)
            return r.json()
        except httpx.HTTPStatusError as e:
            last_err = e
            status = e.response.status_code
            if 500 <= status < 600 and attempt < 2:
                log(f"  ollama HTTP {status} ({model}), retry {attempt+2}/3 in 10s...")
                time.sleep(10)
                continue
        except httpx.ReadTimeout as e:
            last_err = e
            if attempt < 2:
                log(f"  ollama timeout ({model}), retry {attempt+2}/3...")
                continue
        except httpx.HTTPError as e:
            last_err = e
            if attempt < 2:
                log(f"  ollama {type(e).__name__} ({model}), retry {attempt+2}/3 in 10s...")
                time.sleep(10)
                continue
        break  # non-retryable error, or all in-call retries exhausted

    count = _record_model_failure(model)
    backup = MODEL_BACKUPS.get(model)
    if count >= 3 and backup and backup not in _FAILED_THIS_RUN:
        log(f"  {model} failed {count}x consecutively — switching to backup {backup}")
        return _ollama_chat(messages, tools, backup)
    if last_err is not None:
        raise last_err
    raise RuntimeError(f"ollama chat failed for {model} after 3 attempts")


def _parse_inline_tool_calls(content: str, tools: list) -> list:
    """Fallback: extract tool calls from content text when Ollama doesn't parse them.

    Muse Glimmer (and many open-weight models) output tool calls as XML blocks
    in the content rather than in the native tool_calls JSON field:
      <function_calls>
      <invoke name="read_file">
      <parameter name="path">brief/design_brief.json</parameter>
      </invoke>
      </function_calls>

    Also handles Ollama's occasional rendering: <item:function_calls> etc.
    Returns a list of dicts matching Ollama's tool_call format."""
    import re
    if not content:
        return []

    # Ollama native format: {"name": "read_file", ...}
    # OpenAI format: {"type": "function", "function": {"name": "read_file", ...}}
    tool_map = {}
    for t in tools:
        name = t.get("function", {}).get("name") or t.get("name", "")
        if name:
            tool_map[name] = t
    matches = []

    # Pattern: <invoke name="NAME"> ... <parameter name="KEY">VALUE</parameter> ... </invoke>
    # Support both <invoke> and <item:invoke> (tokenizer artifact)
    invoke_pattern = re.compile(
        r'<(?:atem:)?invoke\s+name\s*=\s*"([^"]+)"\s*>(.*?)</(?:atem:)?invoke\s*>',
        re.DOTALL,
    )
    param_pattern = re.compile(
        r'<(?:atem:)?parameter\s+name\s*=\s*"([^"]+)"\s*>(.*?)</(?:atem:)?parameter\s*>',
        re.DOTALL,
    )

    for m in invoke_pattern.finditer(content):
        name = m.group(1)
        body = m.group(2)
        if name not in tool_map:
            continue
        args = {}
        for pm in param_pattern.finditer(body):
            args[pm.group(1)] = pm.group(2).strip()
        if args:
            matches.append({
                "id": f"call_{len(matches)}",
                "type": "function",
                "function": {"name": name, "arguments": args},
            })

    return matches


def _pick_model(failures: list | None, last_model: str, *, single: str = "") -> str:
    """Route: coder for code/JSON failures, writer for text/compliance.

    When `single` is set (--model flag), always returns that model — no routing."""
    if single:
        return single
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


def spawn_subagent(submission: Path, *,
                   model: str | None = None,
                   existing_msgs: list | None = None,
                   inject: str = "",
                   reasoning: str = "") -> list | None:
    """Run an Ollama tool-use session. Returns messages for reuse, or None if done.

    With existing_msgs: continues the previous session (message reuse).
    Without: starts fresh. Only resets on model switch or Gate 2 new task."""
    slug = submission.relative_to(ROOT)
    model = model or MODELS["coder"]
    if model in _FAILED_THIS_RUN and MODEL_BACKUPS.get(model):
        backup = MODEL_BACKUPS[model]
        log(f"  {model} failed repeatedly this run — using backup {backup}")
        model = backup
    fresh = existing_msgs is None
    log(f"spawning {model.split(':')[0]} subagent for {slug} {'(continued)' if not fresh else '(fresh)'}")

    if fresh:
        system_msg = SYSTEM_PROMPT.format(submission_path=str(slug), slug=submission.name)
        # Muse Glimmer reasoning strength
        if reasoning and "muse-glimmer" in model:
            system_msg = f"Reasoning strength: {reasoning}\n\n{system_msg}"
        if "muse-glimmer" in model:
            first = (
                "开始工作。你需要完成以下任务：\n"
                "1. 读 brief/site-package/design_brief.json 了解方案要求\n"
                "2. 读 {submission_path}/proposal.md 等文件了解当前脚手架状态\n"
                "3. 用 write_file 逐步修改提案文件，从 proposal.md 开始\n"
                "4. 每次修改后用 run_python 验证\n\n"
                "注意：读完关键文件后就必须开始写，不要反复读。"
            ).format(submission_path=str(slug))
        else:
            first = "开始工作。先读 brief/site-package/design_brief.json 了解任务。"
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": first},
        ]
    else:
        messages = existing_msgs
        if inject:
            messages.append({"role": "user", "content": inject})

    if fresh:
        _warmup_model(model)  # make sure the model is loaded before real work

    for turn in range(MAX_TOOL_TURNS):
        resp = _ollama_chat(messages, SUBMISSION_TOOLS, model)
        msg = resp.get("message", {})
        content = msg.get("content", "")
        is_muse = "muse-glimmer" in model

        # Clean ATEM special tokens from content (keep to=self reasoning!)
        import re as _re2
        # Only strip end-of-turn markers, NOT channel headers
        content = _re2.sub(r'<\|eot\|>|<\|eom\|>', '', content)
        content = content.strip()

        # check for tool calls (Ollama format)
        tool_calls = msg.get("tool_calls", [])
        # Fallback: parse ATEM XML-style tool calls from content (Muse Glimmer)
        if not tool_calls and content:
            tool_calls = _parse_inline_tool_calls(content, SUBMISSION_TOOLS)
            if tool_calls:
                log(f"  parsed {len(tool_calls)} inline tool call(s) from content")
                # Strip ATEM block from content stored in history
                import re as _re
                content = _re.sub(
                    r'<\s*(?:atem:)?function_calls\s*>.*?</\s*(?:atem:)?function_calls\s*>',
                    '', content, flags=_re.DOTALL,
                ).strip()
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

            # Muse Glimmer expects ATEM-format tool results
            if is_muse:
                result = f'<tool_output name="{name}">\n{result}\n</tool_output>'

            messages.append({
                "role": "tool",
                "content": result,
                "tool_call_id": tc.get("id", ""),
            })
    else:
        log(f"  subagent hit max {max_turns} turns")
    return messages  # return for reuse


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


def _snapshot_dir(submission: Path) -> Path:
    return STATE_DIR / "snapshots" / "-".join(submission.relative_to(ROOT).parts)


def _save_snapshot(submission: Path) -> None:
    """Save submission snapshot for ratchet restore."""
    import shutil
    dst = _snapshot_dir(submission)
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(submission, dst)


def _restore_snapshot(submission: Path) -> None:
    """Restore best-known submission state."""
    import shutil
    src = _snapshot_dir(submission)
    if not src.exists():
        return
    shutil.rmtree(submission)
    shutil.copytree(src, submission)


STATE_DIR = ROOT / ".goal-driven"


def _iter_geom_coords(geom):
    """Yield every [x, y] position in a GeoJSON geometry (pure Python)."""
    if not isinstance(geom, dict):
        return
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "GeometryCollection":
        for g in c:
            yield from _iter_geom_coords(g)
    elif t == "Point":
        yield c
    elif t in ("LineString", "MultiPoint"):
        for p in c:
            yield p
    elif t in ("Polygon", "MultiLineString"):
        for ring in c:
            for p in ring:
                yield p
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                for p in ring:
                    yield p


def _geojson_bbox(gj: dict) -> tuple[float, float, float, float] | None:
    """Bounding box of all features' coordinates, or None if no coordinates."""
    xs: list[float] = []
    ys: list[float] = []
    for f in gj.get("features", []):
        for x, y in _iter_geom_coords(f.get("geometry")):
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _count_full_span_rects(land_use_gj: dict) -> int:
    """Count land_use features that are axis-aligned rectangles spanning the
    full site extent (the scaffold's 'repeated rectangular partition' pattern:
    a few full-height/full-width strips cut from the site bbox)."""
    site_box = _geojson_bbox(land_use_gj)
    if site_box is None:
        return 0
    sx0, sy0, sx1, sy1 = site_box
    sw, sh = sx1 - sx0, sy1 - sy0
    if sw <= 0 or sh <= 0:
        return 0

    count = 0
    for f in land_use_gj.get("features", []):
        geom = f.get("geometry") or {}
        polys = []
        if geom.get("type") == "MultiPolygon":
            polys = [[ring for ring in poly] for poly in geom.get("coordinates", [])]
        elif geom.get("type") == "Polygon":
            polys = [geom.get("coordinates", [])]
        for rings in polys:
            if not rings:
                continue
            ring = rings[0]  # exterior ring
            # Closed axis-aligned rectangle: 5 positions, every edge horizontal
            # or vertical.
            if len(ring) != 5 or ring[0] != ring[-1]:
                continue
            if not all(
                (a[0] == b[0]) or (a[1] == b[1])
                for a, b in zip(ring[:-1], ring[1:])
            ):
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            height = max(ys) - min(ys)
            width = max(xs) - min(xs)
            if height >= 0.99 * sh or width >= 0.99 * sw:
                count += 1
    return count


def _png_placeholder_flags(fp: Path) -> list[str]:
    """Deterministic placeholder-image heuristics for one PNG.

    Returns a list of findings (empty = looks real). No LLM involved:
      - tiny file (< 10KB) — near-empty placeholder
      - exact 78,378-byte fingerprint observed on scaffold placeholders
      - dominant solid color > 80% of pixels — near-blank image
      - scaffold signature: 1640x840 canvas + scaffold palette
        (bg #f8fafc plus >= 2 pastel blocks at >= 5% share each)
    """
    flags = []
    size = fp.stat().st_size
    if size < 10000:
        flags.append(f"{fp.name} 太小 ({size}B) — 可能是占位图")
        return flags
    if size == 78378:
        flags.append(f"{fp.name} 命中脚手架占位图特征（78,378 字节指纹）")
        return flags

    try:
        from PIL import Image
    except ImportError:
        return flags

    try:
        img = Image.open(fp).convert("RGB")
    except Exception:
        return flags  # unreadable image is not a placeholder signal by itself
    width, height = img.size
    pixels = list(img.getdata())
    total = len(pixels)
    if total == 0:
        return flags

    counts: dict = {}
    for px in pixels:
        counts[px] = counts.get(px, 0) + 1
    top1 = max(counts.values()) / total
    if top1 > 0.80:
        flags.append(f"{fp.name} 纯色块占比 {top1:.0%} — 疑似空白/占位图")
        return flags

    if width == 1640 and height == 840:
        pastels = ["#e0f2fe", "#dcfce7", "#fef3c7"]
        share = [
            counts.get((int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16)), 0) / total
            for hexc in pastels
        ]
        if sum(1 for s in share if s >= 0.05) >= 2:
            flags.append(f"{fp.name} 命中脚手架占位图特征（1640×840 + 脚手架配色）")
    return flags


def gate2_review(submission: Path, use_panel: bool = False) -> tuple[bool, str]:
    if use_panel:
        from scripts.panel_runner import run_panel
        v = run_panel(submission)
        if v.approved: return True, ""
        findings = [f"[{jv.statute_name}] {jv.reasoning[:200]}" for jv in v.verdicts if jv.refuted]
        return False, "; ".join(findings[:5])
    # fall through to stub below
    """Gate 2 — deterministic heuristics, no LLM judge.

    Catches scaffold placeholders that slip past the CODE constraints:
      - proposal is a template skeleton ('方案应…' imperative meta-phrases)
      - land_use is the scaffold's repeated full-span rectangular partition
      - figures are near-blank, tiny, or scaffold-signed placeholders
    """
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

        # Template imperative meta-phrases: the scaffold skeleton writes
        # instructions ("方案应…"), a real design describes the place.
        template_phrases = [
            "方案应", "需要进一步", "应统筹考虑", "应加强", "应结合",
            "需进一步", "应突出", "应注重", "建议应",
        ]
        hits = sum(text.count(p) for p in template_phrases)
        if hits > 5:
            issues.append(
                f"proposal.md 有 {hits} 处空洞套话（'方案应''需要进一步'等）。"
                f"请用 write_file 重写 proposal.md，把每处'方案应…'改成具体的已完成设计描述。"
                f"例如'方案应构建创新生态'改写为'本方案构建了由8个创新节点组成的AI生态网络'。"
            )

    # Check GeoJSON are not scaffold placeholders
    land_use = submission / "geometry" / "land_use.geojson"
    if land_use.exists():
        import json as _json
        gj = _json.loads(land_use.read_text(encoding="utf-8"))
        if len(gj.get("features", [])) <= 4:
            issues.append(f"land_use.geojson 只有 {len(gj.get('features',[]))} 个feature — 像脚手架占位")
        rect_count = _count_full_span_rects(gj)
        if rect_count >= 2:
            issues.append(
                f"land_use.geojson 有 {rect_count} 个整跨矩形分区 — 像脚手架的重复矩形分区"
            )

    # Check figures are real (not placeholders)
    fig_dir = submission / "assets" / "figures"
    if fig_dir.is_dir():
        pngs = sorted(fig_dir.glob("*.png"))
        if not pngs:
            issues.append("assets/figures/ 无 PNG 图纸")
        for fp in pngs:
            issues.extend(_png_placeholder_flags(fp))

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
    p.add_argument("--model", default="",
                   help="Single model override (e.g. 'muse-glimmer:30b-mlx'). "
                        "Disables dual-model routing — one model does everything.")
    p.add_argument("--reasoning", default="high",
                   choices=["low", "medium", "high", "xhigh"],
                   help="Reasoning strength for Muse Glimmer (default: high)")
    args = p.parse_args()

    single_model = args.model  # empty string = use dual-model routing

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
    last_model = ""
    msgs = {}  # per-model message state for session reuse
    stall_count = 0
    STALL_MAX = 3  # reset session after N identical rounds

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
            log(f"Gate 2: {findings}")
            # Continue existing session — don't clear, just inject findings
            gate2_model = single_model or MODELS["writer"]
            inject = f"Gate 2 审查发现以下问题，请只修复这些问题，不要重写其他文件：\n{findings}"
            spawn_subagent(submission, model=gate2_model,
                           existing_msgs=msgs.get(gate2_model), inject=inject,
                           reasoning=args.reasoning)
            last_failures = None
            continue

        # 3. stall detection
        if last_failures is not None:
            prev_ids = {r.constraint_id for r in last_failures}
            curr_ids = {r.constraint_id for r in failures}
            if prev_ids == curr_ids:
                stall_count += 1
            else:
                stall_count = 0
            if stall_count >= STALL_MAX:
                log(f"stall detected ({stall_count} identical rounds) — resetting session")
                msgs.clear()
                stall_count = 0

        # 3. pick model
        model = _pick_model(failures, last_model or MODELS["coder"], single=single_model)
        switched = model != last_model and not single_model  # never switch in single-model mode
        if switched:
            log(f"model switch: {last_model.split(':')[0] if last_model else 'none'} → {model.split(':')[0]}")
            msgs.pop(last_model, None) if last_model else None  # old model's context is stale

        # 4. build inject
        inject = ""
        if last_failures is not None:
            ids = {r.constraint_id for r in last_failures}
            now = {r.constraint_id for r in failures}
            fixed = ids - now
            still = ids & now
            if fixed or still or single_model:
                parts = ["本轮验证结果（你必须修复以下每一项失败）："]
                for r in failures:
                    parts.append(f"  FAIL {r.constraint_id} [{r.severity}] {r.name}: {r.detail}")
                    if r.evidence:
                        parts.append(f"    证据: {r.evidence}")
                if fixed:
                    parts.insert(1, f"✓ 已修复 {len(fixed)} 条，继续保持。")
                # Muse Glimmer: always give full failure context
                inject = "\n".join(parts)
        elif single_model and failures:
            # First round: show what needs fixing
            parts = ["验证发现以下失败项，请逐一修复："]
            for r in failures:
                parts.append(f"  FAIL {r.constraint_id} [{r.severity}] {r.name}: {r.detail}")
                if r.evidence:
                    parts.append(f"    证据: {r.evidence}")
            inject = "\n".join(parts)

        # 5. spawn (new or continued)
        existing = None if switched else msgs.get(model)
        m = spawn_subagent(submission, model=model, existing_msgs=existing, inject=inject,
                           reasoning=args.reasoning)
        if m is not None:
            msgs[model] = m  # save for next round
        last_failures = failures
        last_model = model
        last_failures = failures


if __name__ == "__main__":
    raise SystemExit(main())
