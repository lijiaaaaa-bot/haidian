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
JUDGE_MODEL = os.environ.get("HAIDIAN_JUDGE_MODEL", "qwen3.6:35b-a3b")
VISUAL_JUDGE_MODEL = os.environ.get("HAIDIAN_VISUAL_JUDGE_MODEL", "qwen2.5vl:32b-q4_K_M")
JUDGE_TIMEOUT = int(os.environ.get("HAIDIAN_JUDGE_TIMEOUT", "300"))
NUM_CTX = int(os.environ.get("HAIDIAN_JUDGE_CTX", "16384"))

# Per-file evidence budget (chars). Files larger than this are shown as
# head+tail excerpt — the middle is dropped rather than the whole file.
MAX_FILE_CHARS = int(os.environ.get("HAIDIAN_EVIDENCE_CHARS", "16000"))

# Total evidence budget per statute (chars). Sized so that prefill stays
# well inside JUDGE_TIMEOUT and num_ctx (measured: qwen3.6 ~0.45 tok/char,
# ~80-100 tok/s prefill on M5 Max; qwen2.5vl ~0.56 tok/char, ~35 tok/s).
EVIDENCE_BUDGET: dict[str, int] = {
    "package_integrity": 9000,
    "spatial_quality": 10000,
    "proposal_depth": 17000,        # full proposal ~15.6K chars
    "task_coverage": 18000,         # compliance compact + proposal excerpt
    "figure_quality": 1000,         # just the figure size table; images dominate
    "metric_verifiability": 18000,  # metrics + assumptions + geometry
    "compliance_and_boundaries": 24000,
}
# Judges that need a longer per-call budget (vision + big payloads).
LONG_TIMEOUT_STATUTES = {"figure_quality"}

# Which evidence each statute actually needs. Judges 2/5/6 were previously
# pointed at geometry/figures that were never included in the prompt.
EVIDENCE_PLAN: dict[str, list[str]] = {
    "package_integrity": ["manifest.json", "self_check.json"],
    "spatial_quality": ["geometry"],
    "proposal_depth": ["proposal.md"],
    "task_coverage": ["compliance_matrix.json", "proposal.md"],
    "figure_quality": [],  # PNG images sent separately (visual model)
    "metric_verifiability": ["metrics.json", "assumptions.json", "geometry"],
    "compliance_and_boundaries": [
        "proposal.md", "assumptions.json", "sources.json", "compliance_matrix.json",
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


def _excerpt(text: str, max_chars: int = MAX_FILE_CHARS) -> str:
    """Head+tail excerpt so the middle of big files is dropped, not the ends."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n...<内容过长已省略 {len(text) - max_chars} 字符>...\n" + text[-half:]


def _geometry_evidence(submission: Path) -> dict[str, str]:
    """Compact GeoJSON features (names + attributes, coordinates clipped)."""
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
            coords = geom.get("coordinates")
            n_coords = len(coords) if isinstance(coords, list) else 0
            features.append({
                "type": gtype, "n_coords": n_coords,
                "properties": {k: props[k] for k in sorted(props)},
            })
        out[fp.name] = _excerpt(json.dumps({
            "feature_count": len(gj.get("features", [])),
            "crs": gj.get("crs"),
            "features": features,
        }, ensure_ascii=False, indent=1))
    return out


def _compact_json(text: str) -> str | None:
    """Render JSON with per-row caps so large tables stay readable.

    Returns None if the text isn't parseable JSON (caller falls back to
    markdown excerpt). List-of-dicts (requirement tables) are kept row by
    row, each row capped, so coverage checks see every entry.
    """
    try:
        obj = json.loads(text)
    except Exception:
        return None

    def cap_string(v: str) -> str:
        return v if len(v) <= 500 else v[:500] + "…"

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            rows = []
            for x in v:
                s = json.dumps(x, ensure_ascii=False)
                rows.append(s if len(s) <= 700 else s[:700] + "…")
            return rows
        if isinstance(v, str):
            return cap_string(v)
        return v

    return json.dumps(walk(obj), ensure_ascii=False, indent=1)


def _build_evidence(submission: Path, statute_name: str) -> dict[str, str]:
    """Collect the files this statute's judge actually needs, budget-capped."""
    wanted = set(EVIDENCE_PLAN.get(statute_name, TEXT_FILES))
    budget = EVIDENCE_BUDGET.get(statute_name, 16000)
    evidence: dict[str, str] = {}

    if "geometry" in wanted:
        evidence.update(_geometry_evidence(submission))
    for name in TEXT_FILES:
        if name not in wanted:
            continue
        fp = submission / name
        if not fp.exists():
            continue
        text = fp.read_text(encoding="utf-8", errors="replace")
        if name.endswith(".json"):
            compact = _compact_json(text)
            if compact is not None and len(compact) < len(text):
                text = compact
        evidence[name] = _excerpt(text, MAX_FILE_CHARS)

    # Enforce the statute budget: drop whole files (smallest last) until under.
    total = sum(len(v) for v in evidence.values())
    if total > budget:
        for name in sorted(evidence, key=lambda n: -len(evidence[n])):
            evidence[name] = _excerpt(evidence[name], max(budget // max(len(evidence), 1), 500))
            total = sum(len(v) for v in evidence.values())
            if total <= budget:
                break
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


def _call_judge(system: str, evidence: dict, statute: dict, model: str,
                images: list[str] | None = None, timeout: int = JUDGE_TIMEOUT) -> dict:
    """Single LLM judge call. `images` (base64) are only sent to the visual judge.

    Prompt order: evidence first, then statute, then output contract — if
    Ollama truncates an oversized prompt it drops from the front, so the
    judge's mandate and output format always survive.
    """
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
    """Parse LLM response into structured verdict."""
    content = resp.get("message", {}).get("content", "{}")
    try:
        # Extract JSON from possibly noisy response
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(content[start:end])
        else:
            data = {}
    except json.JSONDecodeError:
        data = {}

    refuted = data.get("refuted", statute.get("default_to_reject", True))
    blocking_str = data.get("blocking", "none") or "none"
    return JudgeVerdict(
        judge_id=statute["name"],
        statute_name=statute["title_zh"],
        refuted=bool(refuted),
        blocking=blocking_str != "none" and blocking_str != "",
        confidence=data.get("confidence", "medium"),
        reasoning=data.get("reasoning", content[:500]),
        findings=data.get("findings", []),
    )


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
                images = fig_images
            else:
                images = None
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
