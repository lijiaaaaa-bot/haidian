"""MLX chat client — drop-in replacement for Ollama /api/chat."""
from __future__ import annotations

import json, os, re, sys
import mlx_lm

_MODEL_DIRS = {
    "mlx-community/Qwen3.5-35B-A3B-4bit":
        os.path.expanduser("~/.cache/mlx/models/Qwen3.6-35B-A3B-OptiQ-4bit"),
    "lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-MLX-4bit":
        os.path.expanduser("~/.cache/mlx/models/Qwen3-Coder-30B-A3B-Instruct-4bit"),
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

def _parse(raw: str, tool_names: set) -> list:
    calls = []
    # JSON format: <tool_call>{"name":"...","arguments":{...}}</tool_call>
    _JSON_CALL = _re.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', _re.DOTALL)
    for m in _JSON_CALL.finditer(raw):
        try:
            obj = json.loads(m.group(1))
            name = obj.get("name", "")
            if name in tool_names:
                calls.append({"id": f"c{len(calls)}", "type": "function",
                              "function": {"name": name, "arguments": obj.get("arguments", {})}})
        except json.JSONDecodeError:
            pass
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
    raw = _re.sub(r"<tool_call>.*?</tool_call>", "", raw, flags=_re.DOTALL)
    raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL)
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
                ps = "".join(f"<parameter={k}>{v}</parameter>" for k, v in a.items())
                parts.append(f"<|im_start|>assistant\n<tool_call><function={fn.get('name','')}>{ps}</function></tool_call><|im_end|>")
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
    raw = mlx_lm.generate(mlx_model, tokenizer, prompt=prompt, max_tokens=4096)
    return {"message": {"role": "assistant", "content": _strip(raw),
                         "tool_calls": _parse(raw, tool_names)}}
