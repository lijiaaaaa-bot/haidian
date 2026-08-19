#!/usr/bin/env python3
"""Unified acceptance criteria for haidian goal-driven loops.

Merges three gates into one failure count — the number agents optimize:

  1. CODE constraints (ConstraintEngine + metric declaration gaps)
  2. Content floors (proposal depth, placeholders — formerly Gate 2 stub)
  3. Self-check chain (deterministic + spatial + visual + professional)

Usage:
    python3 scripts/acceptance.py [--submission submissions/test/test]
    python3 scripts/acceptance.py --code-only   # legacy goal_verifier behaviour

The agent under test must NOT edit this file, constraints/, scripts/, brief/,
schema/, or templates/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from constraints.engine import CheckOutcome, ConstraintEngine, ConstraintResult  # noqa: E402

STATE_DIR = ROOT / ".goal-driven"
ANCHOR_RE = re.compile(r"\[(metric|depth|data|standard):[^\]]+\]")
MIN_PROPOSAL_H2 = 8
MIN_LAND_USE_FEATURES = 5
CONTENT_REGRESSION_RATIO = 0.8


@dataclass(frozen=True)
class AcceptanceFailure:
    failure_id: str
    detail: str
    source: str  # code | content | self_check

    @property
    def constraint_id(self) -> str:
        """Alias for goal_driven_loop / format_feedback compatibility."""
        return self.failure_id

    @property
    def severity(self) -> str:
        return {"code": "critical", "content": "high", "self_check": "high"}.get(self.source, "high")


@dataclass(frozen=True)
class AcceptanceVector:
    total_failures: int
    code_failures: int
    content_failures: int
    self_check_failures: int
    proposal_bytes: int
    h2_count: int
    anchor_count: int
    land_use_features: int

    def dominates(self, other: AcceptanceVector) -> bool:
        """True when self is strictly better than other (lower failures, no content regression)."""
        if self.total_failures < other.total_failures:
            if other.proposal_bytes > 0 and self.proposal_bytes < other.proposal_bytes * CONTENT_REGRESSION_RATIO:
                return False
            if self.h2_count < other.h2_count:
                return False
            return True
        if self.total_failures > other.total_failures:
            return False
        # Equal failure count — reject visible content collapse.
        if other.proposal_bytes > 0 and self.proposal_bytes < other.proposal_bytes * CONTENT_REGRESSION_RATIO:
            return False
        if self.h2_count < other.h2_count:
            return False
        if self.anchor_count < other.anchor_count:
            return False
        if self.land_use_features < other.land_use_features:
            return False
        return True


def _declared_metric_keys(submission: Path) -> set[str]:
    mf = submission / "metrics.json"
    if not mf.is_file():
        return set()
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    keys: set[str] = set()
    if isinstance(data, dict):
        keys |= {k for k in data if k not in ("schema_version", "units", "metrics")}
        inner = data.get("metrics")
        if isinstance(inner, dict):
            keys |= set(inner.keys())
        elif isinstance(inner, list):
            keys |= {str(m.get("metric")) for m in inner if isinstance(m, dict) and m.get("metric")}
    elif isinstance(data, list):
        keys |= {str(m.get("metric")) for m in data if isinstance(m, dict) and m.get("metric")}
    return keys


def _required_metric_keys(engine: ConstraintEngine) -> set[str]:
    keys: set[str] = set()
    for c in getattr(engine, "registry", {}).get("constraints", []):
        if str(c.get("constraint_id", "")).startswith("C-SANITY"):
            k = (c.get("params") or {}).get("metric_key")
            if k:
                keys.add(k)
    return keys


def collect_metric_gaps(engine: ConstraintEngine, submission: Path) -> list[AcceptanceFailure]:
    """Engine SKIP traps + unverifiable known-metric claims."""
    failures: list[AcceptanceFailure] = []
    declared = _declared_metric_keys(submission)
    for key in sorted(_required_metric_keys(engine) - declared):
        failures.append(AcceptanceFailure(
            failure_id=f"C-SANITY-{key}",
            detail=f"metrics.json 未声明必需指标 {key}(即使值未知也需以 status=unknown 声明)",
            source="code",
        ))

    mf = submission / "metrics.json"
    if not mf.is_file():
        return failures
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return failures
    inner = data.get("metrics") if isinstance(data, dict) else data
    if isinstance(inner, dict):
        entries = inner.items()
    elif isinstance(inner, list):
        entries = ((m.get("metric"), m) for m in inner if isinstance(m, dict))
    else:
        return failures

    for key, entry in entries:
        if not isinstance(entry, dict) or entry.get("status") != "known":
            continue
        formula = (entry.get("formula") or "").strip()
        sources = entry.get("source_files") or []
        if not formula:
            failures.append(AcceptanceFailure(
                failure_id=f"C-CLAIM-{key}",
                detail=f"metrics.json 的 {key} 声明为 known 但缺少 formula",
                source="code",
            ))
        if not sources:
            failures.append(AcceptanceFailure(
                failure_id=f"C-CLAIM-{key}-sources",
                detail=f"metrics.json 的 {key} 声明为 known 但缺少 source_files",
                source="code",
            ))
            continue
        missing_files = [
            s for s in sources
            if not (submission / s).is_file() and not (ROOT / s).is_file()
        ]
        if missing_files:
            failures.append(AcceptanceFailure(
                failure_id=f"C-CLAIM-{key}-files",
                detail=f"metrics.json 的 {key} 声明为 known 但 source_files 指向不存在的文件",
                source="code",
            ))
    return failures


def collect_code_failures(engine: ConstraintEngine, submission: Path) -> list[AcceptanceFailure]:
    rel = submission.relative_to(ROOT) if submission.is_relative_to(ROOT) else submission
    results = engine.validate(rel)
    failures = [
        AcceptanceFailure(
            failure_id=r.constraint_id,
            detail=r.detail or r.name,
            source="code",
        )
        for r in results
        if r.outcome in (CheckOutcome.FAIL, CheckOutcome.ERROR)
    ]
    failures.extend(collect_metric_gaps(engine, submission))
    return failures


def _geojson_bbox(gj: dict) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords: Any) -> None:
        if isinstance(coords, (list, tuple)):
            if coords and isinstance(coords[0], (int, float)):
                xs.append(float(coords[0]))
                ys.append(float(coords[1]))
            else:
                for c in coords:
                    walk(c)

    for feat in gj.get("features", []):
        walk((feat.get("geometry") or {}).get("coordinates"))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _count_full_span_rects(land_use_gj: dict) -> int:
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
        polys: list = []
        if geom.get("type") == "MultiPolygon":
            polys = geom.get("coordinates", [])
        elif geom.get("type") == "Polygon":
            polys = [geom.get("coordinates", [])]
        for rings in polys:
            if not rings:
                continue
            ring = rings[0]
            if len(ring) != 5 or ring[0] != ring[-1]:
                continue
            if not all((a[0] == b[0]) or (a[1] == b[1]) for a, b in zip(ring[:-1], ring[1:])):
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            if (max(ys) - min(ys)) >= 0.99 * sh or (max(xs) - min(xs)) >= 0.99 * sw:
                count += 1
    return count


def _png_placeholder_flags(fp: Path) -> list[str]:
    flags: list[str] = []
    size = fp.stat().st_size
    if size < 10000:
        return [f"{fp.name} 太小 ({size}B) — 可能是占位图"]
    if size == 78378:
        return [f"{fp.name} 命中脚手架占位图特征（78,378 字节指纹）"]
    try:
        from PIL import Image
    except ImportError:
        return flags
    try:
        img = Image.open(fp).convert("RGB")
    except Exception:
        return flags
    pixels = list(img.getdata())
    total = len(pixels)
    if total == 0:
        return flags
    counts: dict[tuple[int, int, int], int] = {}
    for px in pixels:
        counts[px] = counts.get(px, 0) + 1
    if max(counts.values()) / total > 0.80:
        return [f"{fp.name} 纯色块占比过高 — 疑似空白/占位图"]
    w, h = img.size
    if w == 1640 and h == 840:
        pastels = ["#e0f2fe", "#dcfce7", "#fef3c7"]
        share = [
            counts.get((int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16)), 0) / total
            for hexc in pastels
        ]
        if sum(1 for s in share if s >= 0.05) >= 2:
            return [f"{fp.name} 命中脚手架占位图特征（1640×840 + 脚手架配色）"]
    return flags


def collect_content_failures(submission: Path) -> list[AcceptanceFailure]:
    """Deterministic content floors (formerly Gate 2 stub heuristics)."""
    failures: list[AcceptanceFailure] = []
    proposal = submission / "proposal.md"
    if proposal.exists():
        text = proposal.read_text(encoding="utf-8")
        h2s = [line for line in text.split("\n") if line.startswith("## ")]
        if len(h2s) < MIN_PROPOSAL_H2:
            failures.append(AcceptanceFailure(
                failure_id="CONTENT-proposal-h2",
                detail=f"proposal.md 只有 {len(h2s)} 个章节（期望 ≥{MIN_PROPOSAL_H2}）",
                source="content",
            ))
        if "agent.6" not in text and "运营" not in text:
            failures.append(AcceptanceFailure(
                failure_id="CONTENT-proposal-ops",
                detail="agent.6 运营机制缺失",
                source="content",
            ))
        template_phrases = [
            "方案应", "需要进一步", "应统筹考虑", "应加强", "应结合",
            "需进一步", "应突出", "应注重", "建议应",
        ]
        hits = sum(text.count(p) for p in template_phrases)
        if hits > 5:
            failures.append(AcceptanceFailure(
                failure_id="CONTENT-proposal-template",
                detail=f"proposal.md 有 {hits} 处空洞套话（'方案应''需要进一步'等）",
                source="content",
            ))
        anchors = len(ANCHOR_RE.findall(text))
        if anchors < 3:
            failures.append(AcceptanceFailure(
                failure_id="CONTENT-proposal-anchors",
                detail=f"proposal.md 证据锚点过少（[metric:/depth:/data:/standard:] 仅 {anchors} 处，期望 ≥3）",
                source="content",
            ))
    else:
        failures.append(AcceptanceFailure(
            failure_id="CONTENT-proposal-missing",
            detail="proposal.md 不存在",
            source="content",
        ))

    land_use = submission / "geometry" / "land_use.geojson"
    if land_use.exists():
        try:
            gj = json.loads(land_use.read_text(encoding="utf-8"))
            n_feat = len(gj.get("features", []))
            if n_feat <= 4:
                failures.append(AcceptanceFailure(
                    failure_id="CONTENT-land-use-count",
                    detail=f"land_use.geojson 只有 {n_feat} 个 feature — 像脚手架占位",
                    source="content",
                ))
            rect_count = _count_full_span_rects(gj)
            if rect_count >= 2:
                failures.append(AcceptanceFailure(
                    failure_id="CONTENT-land-use-scaffold",
                    detail=f"land_use.geojson 有 {rect_count} 个整跨矩形分区 — 像脚手架占位",
                    source="content",
                ))
        except (json.JSONDecodeError, OSError):
            pass

    fig_dir = submission / "assets" / "figures"
    if fig_dir.is_dir():
        pngs = sorted(fig_dir.glob("*.png"))
        if not pngs:
            failures.append(AcceptanceFailure(
                failure_id="CONTENT-figures-missing",
                detail="assets/figures/ 无 PNG 图纸",
                source="content",
            ))
        for fp in pngs:
            for flag in _png_placeholder_flags(fp):
                failures.append(AcceptanceFailure(
                    failure_id=f"CONTENT-figure-{fp.stem}",
                    detail=flag,
                    source="content",
                ))
    return failures


def _issues_from_review(stdout: dict[str, Any], prefix: str) -> list[AcceptanceFailure]:
    failures: list[AcceptanceFailure] = []
    for issue in stdout.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        severity = issue.get("severity")
        if severity not in {"blocking", "major"}:
            continue
        check_id = str(issue.get("check_id") or "ISSUE")
        message = str(issue.get("message") or "")
        failures.append(AcceptanceFailure(
            failure_id=f"{prefix}-{check_id}",
            detail=message,
            source="self_check",
        ))
    return failures


def collect_self_check_failures(
    submission: Path,
    repo_root: Path,
    pr_author: str = "test",
) -> list[AcceptanceFailure]:
    from scripts.self_check_submission import build_self_check

    report = build_self_check(repo_root, submission, pr_author)
    failures: list[AcceptanceFailure] = []

    det = report.get("deterministic_validation") or {}
    det_stdout = det.get("stdout") if isinstance(det, dict) else {}
    if isinstance(det_stdout, dict):
        for error in det_stdout.get("errors") or []:
            failures.append(AcceptanceFailure(
                failure_id="SELF-CHECK-DETERMINISTIC",
                detail=str(error),
                source="self_check",
            ))
    elif isinstance(det, dict) and not det.get("ok"):
        stderr = str(det.get("stderr") or "deterministic validation failed")
        failures.append(AcceptanceFailure(
            failure_id="SELF-CHECK-DETERMINISTIC",
            detail=stderr,
            source="self_check",
        ))

    for key, prefix in (
        ("spatial_review", "SELF-CHECK-SPATIAL"),
        ("visual_review", "SELF-CHECK-VISUAL"),
        ("professional_review", "SELF-CHECK-PROFESSIONAL"),
    ):
        block = report.get(key) or {}
        stdout = block.get("stdout") if isinstance(block, dict) else {}
        if isinstance(stdout, dict):
            failures.extend(_issues_from_review(stdout, prefix))

    return failures


def measure_submission(submission: Path) -> tuple[int, int, int, int]:
    proposal = submission / "proposal.md"
    proposal_bytes = proposal.stat().st_size if proposal.is_file() else 0
    h2_count = 0
    anchor_count = 0
    if proposal.is_file():
        text = proposal.read_text(encoding="utf-8")
        h2_count = sum(1 for line in text.split("\n") if line.startswith("## "))
        anchor_count = len(ANCHOR_RE.findall(text))
    land_use_features = 0
    lu = submission / "geometry" / "land_use.geojson"
    if lu.is_file():
        try:
            land_use_features = len(json.loads(lu.read_text(encoding="utf-8")).get("features", []))
        except (json.JSONDecodeError, OSError):
            pass
    return proposal_bytes, h2_count, anchor_count, land_use_features


def evaluate_acceptance(
    submission: Path,
    *,
    repo_root: Path | None = None,
    pr_author: str = "test",
    code_only: bool = False,
    skip_self_check: bool = False,
) -> tuple[list[AcceptanceFailure], AcceptanceVector]:
    repo_root = repo_root or ROOT
    engine = ConstraintEngine(str(repo_root))
    engine.load_registry()

    code_failures = collect_code_failures(engine, submission)
    content_failures: list[AcceptanceFailure] = []
    self_check_failures: list[AcceptanceFailure] = []

    if not code_only:
        content_failures = collect_content_failures(submission)
        if not skip_self_check:
            self_check_failures = collect_self_check_failures(submission, repo_root, pr_author)

    all_failures = code_failures + content_failures + self_check_failures
    pb, h2, anchors, lu = measure_submission(submission)
    vector = AcceptanceVector(
        total_failures=len(all_failures),
        code_failures=len(code_failures),
        content_failures=len(content_failures),
        self_check_failures=len(self_check_failures),
        proposal_bytes=pb,
        h2_count=h2,
        anchor_count=anchors,
        land_use_features=lu,
    )
    return all_failures, vector


def load_ratchet_vector(submission_key: str) -> AcceptanceVector | None:
    fp = STATE_DIR / "loop-state.json"
    try:
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            sub = data.get(submission_key) if isinstance(data, dict) else None
            if isinstance(sub, dict) and "best_vector" in sub:
                raw = sub["best_vector"]
                if isinstance(raw, AcceptanceVector):
                    return raw
                if isinstance(raw, dict):
                    return AcceptanceVector(**raw)
            if isinstance(sub, dict) and isinstance(sub.get("best_failures"), int):
                return AcceptanceVector(
                    total_failures=sub["best_failures"],
                    code_failures=sub["best_failures"],
                    content_failures=0,
                    self_check_failures=0,
                    proposal_bytes=0,
                    h2_count=0,
                    anchor_count=0,
                    land_use_features=0,
                )
    except Exception:
        pass
    return None


def save_ratchet_vector(submission_key: str, vector: AcceptanceVector) -> None:
    fp = STATE_DIR / "loop-state.json"
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if fp.exists():
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                pass
        if not isinstance(data, dict):
            data = {}
        data[submission_key] = {
            "best_failures": vector.total_failures,
            "best_vector": asdict(vector),
        }
        fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def criteria_met_legacy(engine: ConstraintEngine, submission: Path) -> tuple[bool, list[ConstraintResult]]:
    """Backward-compatible CODE-only check returning ConstraintResult objects."""
    rel = submission.relative_to(ROOT) if submission.is_relative_to(ROOT) else submission
    results = engine.validate(rel)
    failures = [r for r in results if r.outcome in (CheckOutcome.FAIL, CheckOutcome.ERROR)]
    for gap in collect_metric_gaps(engine, submission):
        failures.append(ConstraintResult(
            constraint_id=gap.failure_id,
            name=gap.failure_id,
            outcome=CheckOutcome.FAIL,
            severity="high",
            category="metric",
            detail=gap.detail,
        ))
    return len(failures) == 0, failures


def print_report(failures: list[AcceptanceFailure], vector: AcceptanceVector) -> None:
    print(f"FAILURES {vector.total_failures}")
    print(
        f"# breakdown: code={vector.code_failures} "
        f"content={vector.content_failures} self_check={vector.self_check_failures} | "
        f"proposal={vector.proposal_bytes}B h2={vector.h2_count} "
        f"anchors={vector.anchor_count} land_use={vector.land_use_features}"
    )
    for f in failures:
        print(f"FAIL {f.failure_id} | {f.detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Unified haidian acceptance criteria")
    ap.add_argument("--submission", default="submissions/test/test")
    ap.add_argument("--code-only", action="store_true", help="CODE constraints only (legacy verifier)")
    ap.add_argument("--skip-self-check", action="store_true", help="Skip spatial/visual/professional chain")
    ap.add_argument("--pr-author", default="test")
    args = ap.parse_args()

    submission = (ROOT / args.submission).resolve()
    failures, vector = evaluate_acceptance(
        submission,
        pr_author=args.pr_author,
        code_only=args.code_only,
        skip_self_check=args.skip_self_check,
    )
    print_report(failures, vector)
    return 0 if vector.total_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
