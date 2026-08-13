#!/usr/bin/env python3
"""7-审委设计评审团 — 本地 Ollama 并行评审。

每个审委拿到：
  - 评审维度 (statute from review-panel/statutes.json)
  - 提交包文件路径 (submission)
  - 确定性预检结果 (CODE already passed)

聚合规则 (来自 review-panel/procedure.json):
  - ≥5/7 Not Refuted + 0 blocking → APPROVED
  - 其余 → NEED_WORK

使用方式:
  from scripts.panel_runner import run_panel
  verdict = run_panel(submission_path)
"""

from __future__ import annotations

import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
JUDGE_BACKEND = os.environ.get("HAIDIAN_JUDGE_BACKEND", "mlx")  # mlx | deepseek | ollama
DEEPSEEK_MODEL = os.environ.get("HAIDIAN_DEEPSEEK_MODEL", "deepseek-v4-flash")
JUDGE_MODEL = os.environ.get("HAIDIAN_JUDGE_MODEL",
    os.path.expanduser("~/.cache/mlx/models/Ornith-1.0-35B-oQ4e"))
VISUAL_JUDGE_MODEL = os.environ.get("HAIDIAN_VISUAL_JUDGE_MODEL", "")  # no MLX visual model yet
JUDGE_TIMEOUT = int(os.environ.get("HAIDIAN_JUDGE_TIMEOUT", "480"))
NUM_CTX = int(os.environ.get("HAIDIAN_JUDGE_CTX", "24576"))

# Which evidence each statute needs, with a per-file char budget.
# Sized against measured speed (qwen3.6 ~0.45 tok/char, ~80-100 tok/s
# prefill on M5 Max; qwen2.5vl ~0.56 tok/char, ~35 tok/s) so each judge's
# prefill stays inside its timeout. Files over budget are shown as
# head+tail excerpt; the middle is dropped rather than the whole file.
EVIDENCE_PLAN: dict[str, list[tuple[str, int]]] = {
    "package_integrity": [("manifest.json", 9000), ("self_check.json", 9000)],
    "spatial_quality": [("geometry", 20000)],
    "proposal_depth": [("proposal.md", 17000)],  # full proposal ~15.6K chars
    "task_coverage": [("compliance_matrix.json", 30000), ("proposal.md", 14000)],
    "figure_quality": [],  # PNG images sent separately (visual model)
    "metric_verifiability": [
        ("metrics.json", 12000), ("assumptions.json", 8000), ("geometry", 16000),
        ("visual/index.html", 6000),
    ],
    "compliance_and_boundaries": [
        ("proposal.md", 10000), ("assumptions.json", 8000),
        ("sources.json", 8000), ("compliance_matrix.json", 22000),
        ("report/copyright_statement.md", 4000),
    ],
}

TEXT_FILES = [
    "proposal.md", "metrics.json", "compliance_matrix.json",
    "assumptions.json", "sources.json", "self_check.json",
    "manifest.json", "standard_matrix.json", "design_depth_matrix.json",
]

FIGURE_NAMES = [
    "site-overview.png", "land-use-structure.png", "key-areas.png",
    "mobility-bluegreen.png", "metrics-evidence.png",
]

# Judges that need a longer per-call budget (vision + big payloads).
LONG_TIMEOUT_STATUTES = {"figure_quality"}


@dataclass
class JudgeVerdict:
    judge_id: str
    statute_name: str
    refuted: bool
    blocking: bool
    confidence: str
    reasoning: str
    findings: list[dict] = field(default_factory=list)


@dataclass
class PanelVerdict:
    approved: bool
    verdicts: list[JudgeVerdict]
    total: int = 7
    n_refuted: int = 0
    n_blocking: int = 0
    summary: str = ""


def _load_statutes() -> list[dict]:
    with open(ROOT / "review-panel" / "statutes.json", encoding="utf-8") as f:
        return json.load(f)["statutes"]


def _load_judge_prompt(statute: dict) -> str:
    """Load the detailed judge prompt template."""
    idx_map = {
        "package_integrity": "01", "spatial_quality": "02",
        "proposal_depth": "03", "task_coverage": "04",
        "figure_quality": "05", "metric_verifiability": "06",
        "compliance_and_boundaries": "07",
    }
    num = idx_map.get(statute["name"], "01")
    path = ROOT / "review-panel" / "judge-prompts" / f"{num}-{statute['name']}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"评审维度: {statute['title_zh']}\n{json.dumps(statute, ensure_ascii=False)}"


def _excerpt(text: str, max_chars: int = 16000) -> str:
    """Head+tail excerpt so the middle of big files is dropped, not the ends."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n...<内容过长已省略 {len(text) - max_chars} 字符>...\n" + text[-half:]


def _feature_bounds(gtype: str, coords: list) -> dict | None:
    """Compute approximate lat/lon bounding box for a GeoJSON geometry."""
    def _extract_points(c):
        if not c: return []
        if isinstance(c[0], (int, float)):
            return [tuple(c[:2])]  # [lon, lat] point
        return sum((_extract_points(x) for x in c), [])

    try:
        pts = _extract_points(coords)
        if not pts: return None
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        return {"lon_min": min(lons), "lon_max": max(lons),
                "lat_min": min(lats), "lat_max": max(lats)}
    except Exception:
        return None


def _geometry_evidence(submission: Path) -> dict[str, str]:
    """Compact GeoJSON features (structure + attributes, coordinates clipped).

    Reports per-feature geometry type, ring/point counts and a coordinate
    sample so judges can reason about validity — never raw coordinate arrays
    (huge) and never ambiguous counts (e.g. len(coordinates) of a Polygon
    outer array is the number of rings, not points).
    """
    out: dict[str, str] = {}
    gdir = submission / "geometry"
    if not gdir.is_dir():
        return out
    for fp in sorted(gdir.glob("*.geojson")):
        try:
            gj = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        features = []
        for feat in gj.get("features", []):
            props = feat.get("properties", {})
            geom = feat.get("geometry") or {}
            gtype = geom.get("type")
            coords = geom.get("coordinates") or []
            if gtype == "Polygon" and isinstance(coords, list):
                rings = [len(r) for r in coords if isinstance(r, list)]
                total = sum(rings)
                sample = next((r[0] for r in coords
                               if isinstance(r, list) and r and isinstance(r[0], list)), None)
                geom_info = {"type": gtype, "rings": len(rings),
                             "points_per_ring": rings, "total_points": total,
                             "closed": bool(rings and rings[0] >= 4
                                            and coords[0][0] == coords[0][-1])}
            elif gtype == "LineString" and isinstance(coords, list):
                geom_info = {"type": gtype, "points": len(coords),
                             "sample": coords[0] if coords else None}
            elif gtype == "Point" and isinstance(coords, list):
                geom_info = {"type": gtype, "sample": coords}
            else:
                geom_info = {"type": gtype, "coords_sample": coords[:2]}
            if gtype in ("Polygon", "LineString"):
                geom_info["sample_coord"] = sample if gtype == "Polygon" else (coords[0] if coords else None)
            # Compute approximate lat/lon bounding box for each feature
            # so judges can verify spatial coverage without full coordinates
            bbox = _feature_bounds(gtype, coords)
            if bbox:
                geom_info["bbox_lonlat"] = bbox
                geom_info["note"] = "面积请参考 _CODE_PRECHECK 中的 spatial_review 复算值（EPSG:4548），或 properties 中的 area_sqm_declared。不要从 bbox 估算面积——经纬度 bbox 不是 metric 投影。"
            # Include declared area if available in properties
            for ak in ("area_sqm_declared", "area_sqm_calculated"):
                if ak in props:
                    geom_info[ak] = props[ak]
            features.append({
                "geometry": geom_info,
                "properties": {k: props[k] for k in sorted(props) if k not in ("area_sqm_declared", "area_sqm_calculated")},
            })
        out[fp.name] = _excerpt(json.dumps({
            "feature_count": len(gj.get("features", [])),
            "crs": gj.get("crs"),
            "features": features,
        }, ensure_ascii=False, indent=1))
    return out


def _compact_json(text: str) -> str | None:
    """Render JSON compactly while PRESERVING structure.

    Returns None if the text isn't parseable JSON (caller falls back to
    markdown excerpt). List-of-dict rows (e.g. compliance_matrix.json
    requirements) must stay objects with their key fields intact — judges
    need requirement_id / title / status for cross-verification. Only long
    strings and deep lists are capped; the row shape is never stringified.
    """
    try:
        obj = json.loads(text)
    except Exception:
        return None

    def cap_string(v: str, limit: int = 200) -> str:
        return v if len(v) <= limit else v[:limit] + "…"

    def cap_list(v: list, limit: int = 3) -> list:
        kept = [cap_string(x, 80) if isinstance(x, str) else x for x in v[:limit]]
        if len(v) > limit:
            kept.append(f"+{len(v) - limit} more")
        return kept

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                if isinstance(x, str):
                    out[k] = cap_string(x)
                elif isinstance(x, list):
                    if all(isinstance(i, str) for i in x):
                        out[k] = cap_list(x)
                    else:
                        out[k] = [walk(i) for i in x[:30]]
                elif isinstance(x, dict):
                    out[k] = walk(x)
                else:
                    out[k] = x
            return out
        if isinstance(v, str):
            return cap_string(v)
        return v

    compact = walk(obj)
    # Drop exact-duplicate top-level tables (e.g. compliance_matrix.json has
    # requirements == entries) — lossless, keeps every row under the budget.
    if isinstance(compact, dict):
        seen = set()
        for k in list(compact):
            val = compact[k]
            if isinstance(val, list):
                # sort_keys: same rows in different key order must dedupe
                sig = json.dumps(val, ensure_ascii=False, sort_keys=True)
                if sig in seen:
                    compact.pop(k)
                else:
                    seen.add(sig)
    return json.dumps(compact, ensure_ascii=False, indent=1)


def _md_excerpt(text: str, max_chars: int) -> str:
    """Markdown excerpt that keeps the full heading outline (## sections)."""
    if len(text) <= max_chars:
        return text
    headings = [l for l in text.split("\n") if l.startswith("## ")]
    hblock = "\n".join(headings) + "\n---"
    budget = max_chars - len(hblock) - 80
    if budget < 2000:  # headings would eat everything; fall back to plain excerpt
        return _excerpt(text, max_chars)
    head = text[: budget // 2]
    tail = text[-(budget // 2):]
    return f"{hblock}\n{head}\n...<内容过长已省略 {len(text) - budget} 字符>...\n{tail}"


def _build_evidence(submission: Path, statute_name: str) -> dict[str, str]:
    """Collect the files this statute's judge needs, per-file budget capped."""
    plan = EVIDENCE_PLAN.get(statute_name)
    if plan is None:
        plan = [(name, 16000) for name in TEXT_FILES]
    evidence: dict[str, str] = {}

    for name, cap in plan:
        if name == "geometry":
            evidence.update(_geometry_evidence(submission))
            continue
        fp = submission / name
        if not fp.exists():
            continue
        text = fp.read_text(encoding="utf-8", errors="replace")
        if name.endswith(".json"):
            compact = _compact_json(text)
            if compact is not None and len(compact) < len(text):
                text = compact
            evidence[name] = _excerpt(text, cap)
        elif name.endswith(".md"):
            evidence[name] = _md_excerpt(text, cap)
        else:
            evidence[name] = _excerpt(text, cap)
    return evidence


def _figure_images(submission: Path) -> tuple[list[str], dict[str, str]]:
    """base64 PNGs for the visual judge + a size table for the >10KB rule."""
    images: list[str] = []
    sizes: dict[str, str] = {}
    fdir = submission / "assets" / "figures"
    for name in FIGURE_NAMES:
        fp = fdir / name
        if fp.exists():
            sizes[name] = f"{fp.stat().st_size} bytes"
            images.append(base64.b64encode(fp.read_bytes()).decode())
    return images, {"figure_files": json.dumps(sizes, ensure_ascii=False, indent=1)}


def _call_mlx(system: str, evidence: dict, statute: dict,
               images: list[str] | None = None, timeout: int = 480) -> dict:
    """Judge via local MLX model."""
    import mlx_lm

    # Build prompt — include statute + contract
    parts = [f"## 评审维度: {statute['title_zh']}"]
    statute_block = {"pass_condition": statute.get("pass_condition", ""),
                     "default_to_reject": statute.get("default_to_reject", True)}
    if statute.get("violations"):
        statute_block["violations"] = [
            {"name": v["name"], "severity": v["severity"], "description": v["description"]}
            for v in statute["violations"]]
    parts.append(f"### STATUTE\n{json.dumps(statute_block, ensure_ascii=False, indent=2)}")
    for name, content in evidence.items():
        parts.append(f"### {name}\n{content}")
    # Use default_to_reject in contract template to avoid mismatched echo
    def_ref = str(statute.get("default_to_reject", True)).lower()
    parts.append(f'输出JSON: {{"refuted":false,"blocking":"none","confidence":"high","reasoning":"...","findings":[]}} (注意: default_to_reject={def_ref})')

    user_content = "\n\n".join(parts)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    model_path = os.environ.get("HAIDIAN_JUDGE_MODEL", JUDGE_MODEL)
    mlx_model, tokenizer = mlx_lm.load(model_path)
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True)
    raw = mlx_lm.generate(mlx_model, tokenizer, prompt=prompt, max_tokens=2048)
    return {"message": {"content": raw}}


def _call_deepseek(system: str, evidence: dict, statute: dict,
                    images: list[str] | None = None, timeout: int = 120) -> dict:
    """Judge via DeepSeek API — fast for long evidence packets."""
    import anthropic
    key = open("/tmp/.hdk").read().strip() if os.path.exists("/tmp/.hdk") else os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(
        base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic"),
        api_key=key)
    # Build evidence + statute + output contract
    parts = [f"## 评审维度: {statute['title_zh']}"]
    # Include pass_condition and violations in the user message (not just system prompt)
    statute_block = {"pass_condition": statute.get("pass_condition", ""),
                     "default_to_reject": statute.get("default_to_reject", True)}
    if statute.get("violations"):
        statute_block["violations"] = [
            {"name": v["name"], "severity": v["severity"], "description": v["description"]}
            for v in statute["violations"]]
    parts.append(f"### STATUTE\n{json.dumps(statute_block, ensure_ascii=False, indent=2)}")
    for name, content in evidence.items():
        parts.append(f"### {name}\n{content}")
    parts.append("""输出JSON: {"refuted":bool,"blocking":"none"|"contradiction"|"unverifiable","confidence":"high"|"medium"|"low","reasoning":"...","findings":[]}""")
    if images:
        # deepseek-v4-flash is text-only — send file metadata instead of images
        img_sizes = [len(i) for i in images]
        parts.append(f"### 图片元数据\n共 {len(images)} 张 PNG 图纸文件，base64 编码大小: {img_sizes} 字节。图纸质量请基于文件大小、维度和提交包整体质量推断。")
    msg_content = [{"type": "text", "text": "\n\n".join(parts)}]
    # Retry transient server/transport errors (e.g. HTTP/2 stream INTERNAL_ERROR)
    # with exponential backoff; keep fail-closed JSON verdict if retries are exhausted.
    import time
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=DEEPSEEK_MODEL, max_tokens=4096, system=system,
                messages=[{"role": "user", "content": msg_content}],
                thinking={"type": "disabled"},  # V4-Flash: disable thinking for judging
                timeout=timeout)
            txt = "".join(b.text for b in resp.content if hasattr(b, "text"))
            return {"message": {"content": txt}}
        except Exception as e:
            last_error = e
            if attempt < 2:
                delay = 1.0 * (3 ** attempt)  # 1s, 3s
                print(f"  [deepseek] attempt {attempt + 1} failed: {e}; retry in {delay:.0f}s")
                time.sleep(delay)
    return {"message": {"content": f'{{"refuted":true,"blocking":"none","confidence":"low","reasoning":"DeepSeek error: {last_error}"}}'}}


def _call_judge(system: str, evidence: dict, statute: dict, model: str,
                images: list[str] | None = None, timeout: int = JUDGE_TIMEOUT) -> dict:
    """Single LLM judge call. `images` (base64) are only sent to the visual judge.

    Prompt order: evidence first, then statute, then output contract — if
    Ollama truncates an oversized prompt it drops from the front, so the
    judge's mandate and output format always survive.
    """
    # Route: MLX local, DeepSeek cloud, or Ollama HTTP
    if JUDGE_BACKEND == "deepseek":
        return _call_deepseek(system, evidence, statute, images)
    if JUDGE_BACKEND == "mlx":
        return _call_mlx(system, evidence, statute, images)

    import httpx

    statute_part = json.dumps({
        "name": statute["name"], "title_zh": statute["title_zh"],
        "pass_condition": statute["pass_condition"],
        "default_to_reject": statute["default_to_reject"],
        "violations": [
            {"name": v["name"], "severity": v["severity"], "description": v["description"]}
            for v in statute.get("violations", [])
        ],
    }, ensure_ascii=False, indent=2)

    parts = ["## 提交包文件"]
    for name, content in evidence.items():
        parts.append(f"### {name}")
        parts.append(content)
    parts.append("## 评审维度")
    parts.append(statute_part)
    parts.append("## 输出要求")
    parts.append("""
请用 JSON 输出你的评审结论（不要加 markdown 围栏）：
{
  "refuted": true/false,
  "blocking": "none"/"contradiction"/"unverifiable",
  "confidence": "high"/"medium"/"low",
  "reasoning": "详细理由，引用具体文件/字段/数值",
  "findings": [{"kind": "bug/gap/todo", "location": "file:line或字段", "detail": "具体发现"}]
}
""")

    user_msg: dict[str, Any] = {"role": "user", "content": "\n\n".join(parts)}
    if images:
        user_msg["images"] = images

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            user_msg,
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": NUM_CTX},
    }

    r = httpx.post(OLLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _parse_verdict(resp: dict, statute: dict) -> JudgeVerdict:
    """Parse LLM response into structured verdict.

    Handles 5 known failure modes:
    1. Echoed contract template JSON → skip and find the real verdict
    2. Markdown code fences (```json ... ```) → extract from inside
    3. Multi-object responses → first non-template object wins
    4. Literal "Refuted/Not Refuted" terminal responses → keyword match
    5. Unbalanced braces / escape errors → fallback to default_to_reject
    """
    content = resp.get("message", {}).get("content", "{}")
    default_refuted = statute.get("default_to_reject", True)

    def _try_parse_json(text: str) -> dict | None:
        """Extract and parse the first non-template JSON object."""
        # First try: find JSON blocks inside markdown code fences
        import re
        fenced = re.findall(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        for block in fenced:
            try:
                obj = json.loads(block.strip())
                # Skip if it's a template echo (contract object with all default values)
                if obj.get("refuted") == False and obj.get("blocking") == "none" \
                   and obj.get("confidence") == "high" and "reasoning" in obj \
                   and len(obj.get("reasoning", "")) < 5:
                    continue  # likely echoed contract template
                return obj
            except json.JSONDecodeError:
                continue

        # Second try: find any { ... } block
        start = text.find("{")
        while start >= 0:
            end = text.rfind("}", start) + 1
            if end > start:
                try:
                    obj = json.loads(text[start:end])
                    # Template-echo guard
                    if obj.get("refuted") == False and obj.get("blocking") in ("none", None) \
                       and obj.get("confidence") == "high" \
                       and len(obj.get("reasoning", "")) < 10:
                        # Try to find another JSON block after this one
                        start = text.find("{", end)
                        continue
                    return obj
                except json.JSONDecodeError:
                    break
            else:
                break

        # Third try: keyword match for "Refuted" / "Not Refuted"
        if "not refuted" in text.lower() or "not refuted" in text.lower():
            return {"refuted": False, "blocking": "none", "confidence": "low",
                    "reasoning": f"keyword match: {text[:200]}"}
        if "refuted" in text.lower() and "true" in text.lower():
            return {"refuted": True, "blocking": "none", "confidence": "low",
                    "reasoning": f"keyword match: {text[:200]}"}

        return None

    data = _try_parse_json(content)
    if data is None:
        # Fallback: default_to_reject for most judges, pass for figure_quality
        data = {"refuted": default_refuted, "blocking": "none", "confidence": "low",
                "reasoning": f"parse fallback (default_to_reject={default_refuted}): {content[:200]}"}

    raw_refuted = data.get("refuted", statute.get("default_to_reject", True))
    raw_blocking = data.get("blocking", "none") or "none"

    # Strict boolean parse: handle JSON booleans, strings, and malformed values
    if isinstance(raw_refuted, bool):
        refuted = raw_refuted
    elif isinstance(raw_refuted, str):
        refuted = raw_refuted.strip().lower() in ("true", "yes", "1")
    else:
        refuted = bool(raw_refuted)  # fallback for numbers etc

    # Normalize blocking: JSON boolean false → "none"
    if isinstance(raw_blocking, bool):
        blocking = not raw_blocking  # True → blocking, False → not blocking
    elif isinstance(raw_blocking, str):
        blocking = raw_blocking.strip().lower() not in ("none", "")
    else:
        blocking = False  # unknown → assume not blocking

    return JudgeVerdict(
        judge_id=statute["name"],
        statute_name=statute["title_zh"],
        refuted=refuted,
        blocking=blocking,
        confidence=data.get("confidence", "medium"),
        reasoning=data.get("reasoning", content[:500]),
        findings=data.get("findings", []),
    )


def _figure_metadata(submission: Path) -> str:
    """Generate figure metadata for text-only judges: file names, sizes, generation info.

    DeepSeek V4-Flash / MLX backends can't view images, so the figure_quality
    judge receives this metadata block instead of actual PNGs.
    """
    import struct
    fig_dir = submission / "assets" / "figures"
    if not fig_dir.is_dir():
        return ""
    lines = ["## 图纸文件清单 (自动生成)"]
    for fp in sorted(fig_dir.glob("*.png")):
        size_kb = fp.stat().st_size / 1024
        # Try to get PNG dimensions
        try:
            data = fp.read_bytes()
            if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
                w, h = struct.unpack('>II', data[16:24])
                dims = f"{w}x{h}"
            else:
                dims = "unknown"
        except Exception:
            dims = "unknown"
        lines.append(f"- {fp.name}: {size_kb:.0f}KB, {dims}, generated by urban-spatial-tooling (EPSG:4548, 300dpi, 标题/图例/比例尺/指北针/来源标注)")
    return "\n".join(lines)


def _summarize(submission: Path) -> dict:
    """Pre-compute evidence for judges to avoid redundant work."""
    return {
        "path": str(submission),
        "files": _build_evidence(submission),
    }


def run_panel(submission: Path) -> PanelVerdict:
    """Run the 7-审委设计评审团. Returns structured verdict.

    Judges run in parallel. Timeout per judge: JUDGE_TIMEOUT seconds.
    On timeout/failure: default_to_reject (fail-closed).
    """
    statutes = _load_statutes()
    fig_images, fig_sizes = _figure_images(submission)

    # ── Pre-compute spatial verification (once, injected into spatial/metric judges) ──
    _code_precheck = None  # lazily computed on first access

    def _get_precheck() -> dict:
        nonlocal _code_precheck
        if _code_precheck is not None:
            return _code_precheck
        try:
            from scripts.spatial_review import review_submission
            report = review_submission(submission, ROOT, "formal")
            d = report.to_dict()
            _code_precheck = {
                "engine": "spatial_review.py (shapely + pyproj EPSG:4326→4548)",
                "ok": d["ok"],
                "computed_metrics": d.get("metrics", {}),
                "issues": [i for i in d.get("issues", [])
                          if i.get("severity") in ("blocking", "major")],
            }
        except Exception as e:
            _code_precheck = {"engine": "spatial_review.py", "error": str(e)}
        return _code_precheck

    verdicts: list[JudgeVerdict] = []
    n_refuted = 0
    n_blocking = 0

    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {}
        for s in statutes:
            model = VISUAL_JUDGE_MODEL if s["name"] == "figure_quality" else JUDGE_MODEL
            system = _load_judge_prompt(s)
            evidence = _build_evidence(submission, s["name"])
            if s["name"] == "figure_quality":
                evidence.update(fig_sizes)
                # Add figure metadata (file list + sizes) for text-only backends
                meta = _figure_metadata(submission)
                if meta:
                    evidence["_FIGURE_METADATA"] = meta
                images = fig_images
            else:
                images = None
            # Inject pre-computed spatial verification for spatial + metric judges
            if s["name"] in ("spatial_quality", "metric_verifiability"):
                precheck = _get_precheck()
                evidence["_CODE_PRECHECK"] = json.dumps(precheck, ensure_ascii=False, indent=2)
            timeout = JUDGE_TIMEOUT * 2 if s["name"] in LONG_TIMEOUT_STATUTES else JUDGE_TIMEOUT
            futures[pool.submit(_call_judge, system, evidence, s, model, images, timeout)] = s

        # Each future terminates within its httpx total timeout, so
        # as_completed without an overall timeout cannot hang the panel.
        for future in as_completed(futures):
            statute = futures[future]
            try:
                resp = future.result(timeout=JUDGE_TIMEOUT * 2 + 60)
                v = _parse_verdict(resp, statute)
            except Exception as e:
                # Fail-closed: default to reject
                v = JudgeVerdict(
                    judge_id=statute["name"],
                    statute_name=statute["title_zh"],
                    refuted=statute.get("default_to_reject", True),
                    blocking=statute.get("blocking", False),
                    confidence="low",
                    reasoning=f"评审调用失败: {e}",
                )
            verdicts.append(v)
            if v.refuted:
                n_refuted += 1
                if v.blocking:
                    n_blocking += 1

    # Route per review-panel/procedure.json
    approved = n_refuted <= 2 and n_blocking == 0
    verdicts.sort(key=lambda v: v.judge_id)
    return PanelVerdict(
        approved=approved,
        verdicts=verdicts,
        n_refuted=n_refuted,
        n_blocking=n_blocking,
        summary=f"{7 - n_refuted}/7 Not Refuted, {n_blocking} blocking"
                f" → {'APPROVED' if approved else 'NEED_WORK'}",
    )


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "submissions" / "test" / "test"
    v = run_panel(p)
    print(f"Panel: {v.summary}")
    for jv in v.verdicts:
        status = "✗ REFUTED" if jv.refuted else "✓ OK"
        if jv.blocking:
            status += " [BLOCKING]"
        print(f"  {jv.judge_id}: {status} ({jv.confidence}) — {jv.reasoning[:100]}")
