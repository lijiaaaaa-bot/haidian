"""MLX chat client — drop-in replacement for Ollama /api/chat."""
from __future__ import annotations

import json, os, re, sys
import mlx_lm

_MODEL_DIRS = {
    # 2026-08-15: 旧 35B-A3B / 30B-A3B 已换成 Qwen3.8-27B-4bit(旧权重已删除)
    "mlx-community/Qwen3.5-35B-A3B-4bit":
        os.path.expanduser("~/.cache/mlx/Qwen3.8-27B-4bit"),
    "lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-MLX-4bit":
        os.path.expanduser("~/.cache/mlx/Qwen3.8-27B-4bit"),
    "Basher17/Ornith-1.0-35B-oQ4e":
        os.path.expanduser("~/.cache/mlx/models/Ornith-1.0-35B-oQ4e"),
    "Indelwin/Qwen3-ToolAgent-GRPO-MLX":
        os.path.expanduser("~/.cache/mlx/models/Qwen3-30B-A3B-ToolAgent-MLX-4bit"),
}
_CACHE: dict[str, tuple] = {}

def _load(model_id: str):
    if model_id not in _CACHE:
        path = _MODEL_DIRS.get(model_id, model_id)
        _CACHE[model_id] = mlx_lm.load(path)
    return _CACHE[model_id]

# Qwen3 XML parser
import re as _re
_TOOL_CALL = _re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", _re.DOTALL)
_FUNCTION = _re.compile(r"<function=(\w+)>\s*(.*?)\s*</function>", _re.DOTALL)
_PARAM = _re.compile(r"<parameter=(\w+)>\s*(.*?)\s*</parameter>", _re.DOTALL)

def _extract_json_objects(raw: str) -> list:
    """Balanced-brace scan of <tool_call> blocks, string-aware (skips escaped
    quotes and braces inside string literals). Works on truncated output too:
    the closing </tool_call> is only a bound when present. Returns JSON object
    substrings; incomplete (unbalanced) blocks are skipped."""
    out = []
    pos = 0
    while True:
        start = raw.find("<tool_call>", pos)
        if start < 0:
            break
        body = raw[start + len("<tool_call>"):]
        end_tag = body.find("</tool_call>")
        limit = end_tag if end_tag >= 0 else len(body)
        brace = body.find("{")
        if brace < 0 or brace >= limit:
            pos = start + len("<tool_call>")
            continue
        depth = 0
        in_str = False
        esc = False
        i = brace
        while i < len(body) and (end_tag < 0 or i < limit):
            c = body[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        out.append(body[brace:i + 1])
                        break
            i += 1
        pos = start + len("<tool_call>")
    return out


def _parse(raw: str, tool_names: set) -> list:
    calls = []
    # JSON format: <tool_call>{"name":"...","arguments":{...}}</tool_call>
    # strict=False tolerates unescaped newlines inside string values.
    for obj_text in _extract_json_objects(raw):
        try:
            obj = json.loads(obj_text, strict=False)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        candidates = obj.get("tool_calls") if isinstance(obj.get("tool_calls"), list) else [obj]
        for tc in candidates:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
            name = fn.get("name", "")
            if name not in tool_names:
                continue
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args, strict=False)
                except json.JSONDecodeError:
                    continue
            if not isinstance(args, dict):
                continue
            calls.append({"id": f"c{len(calls)}", "type": "function",
                          "function": {"name": name, "arguments": args}})
    if calls: return calls
    # Qwen3 XML format: <tool_call><function=name><parameter=k>v</parameter></function></tool_call>
    for tc in _TOOL_CALL.finditer(raw):
        for fn in _FUNCTION.finditer(tc.group(1)):
            name = fn.group(1)
            if name not in tool_names: continue
            args = {}
            for pm in _PARAM.finditer(fn.group(2)):
                args[pm.group(1)] = pm.group(2).strip()
            calls.append({"id": f"c{len(calls)}", "type": "function",
                          "function": {"name": name, "arguments": args}})
    if calls: return calls
    # Fallback: plain text function calls like read_file("path")
    _TEXT_CALL = _re.compile(r'(\w+)\s*\(\s*"([^"]*)"\s*\)')
    for m in _TEXT_CALL.finditer(raw):
        name = m.group(1)
        if name not in tool_names: continue
        calls.append({"id": f"c{len(calls)}", "type": "function",
                      "function": {"name": name, "arguments": {"path": m.group(2)}}})
    return calls

def _strip(raw: str) -> str:
    raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL)
    # Qwen3.8 的模板把 <think> 前缀放在 prompt 里,生成文本只有 </think> 闭合标签,
    # 思考内容会残留在输出开头:剥掉闭合标签之前的全部文本
    if "</think>" in raw:
        raw = raw.split("</think>", 1)[1]
    raw = _re.sub(r"<tool_call>.*?</tool_call>", "", raw, flags=_re.DOTALL)
    # Truncated tool call (no closing tag): drop everything from <tool_call on
    if "<tool_call>" in raw:
        raw = raw.split("<tool_call>", 1)[0]
    return raw.strip()

def _manual_fmt(msgs, tools):
    parts = []
    for m in msgs:
        r, c = m["role"], m.get("content", "")
        if r == "system": parts.append(f"<|im_start|>system\n{c}<|im_end|>")
        elif r == "user": parts.append(f"<|im_start|>user\n{c}<|im_end|>")
        elif r == "assistant":
            for tc in m.get("tool_calls", []):
                fn = tc.get("function", {})
                a = fn.get("arguments", {})
                if isinstance(a, str):
                    try: a = json.loads(a)
                    except: a = {}
                body = json.dumps({"name": fn.get("name", ""), "arguments": a},
                                  ensure_ascii=False)
                parts.append(f"<|im_start|>assistant\n<tool_call>{body}</tool_call><|im_end|>")
            if c: parts.append(f"<|im_start|>assistant\n{c}<|im_end|>")
        elif r == "tool":
            parts.append(f"<|im_start|>tool\n<tool_response>{c}</tool_response><|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)

def mlx_chat(messages: list, tools: list, model: str) -> dict:
    """Drop-in replacement for Ollama /api/chat response."""
    mlx_model, tokenizer = _load(model)
    tool_names = set()
    for t in (tools or []):
        n = t.get("function", {}).get("name") or t.get("name", "")
        if n: tool_names.add(n)
    try:
        prompt = tokenizer.apply_chat_template(
            messages, tools=tools or None, tokenize=False, add_generation_prompt=True)
    except Exception:
        prompt = _manual_fmt(messages, tools)
    raw = mlx_lm.generate(mlx_model, tokenizer, prompt=prompt, max_tokens=8192)
    return {"message": {"role": "assistant", "content": _strip(raw),
                         "tool_calls": _parse(raw, tool_names)}}
