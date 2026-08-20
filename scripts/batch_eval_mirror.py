#!/usr/bin/env python3
"""Batch-evaluate mirrored packages using goal-driven gates.

Integrates with scripts/goal_driven_loop.py:
  - Gate 1: criteria_met(ConstraintEngine) — deterministic CODE constraints
  - Gate 2 stub: gate2_review(use_panel=False) — template/placeholder heuristics
  - Gate 2 panel: gate2_review(use_panel=True) — 7 LLM judges via panel_runner

Cloud VM: run gate1 + gate2-stub for all packages (fast).
Local Mac (MLX/Ollama): add --panel for full 7-judge review on all packages.

Usage:
  python3 scripts/batch_eval_mirror.py --stages gate1,gate2-stub
  python3 scripts/batch_eval_mirror.py --stages gate2-panel --resume
  HAIDIAN_JUDGE_BACKEND=mlx python3 scripts/batch_eval_mirror.py --stages gate2-panel
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MIRROR = REPO / "data" / "benchmark" / "mirror"
DEFAULT_OUT = REPO / "data" / "benchmark" / "eval_results.jsonl"
DEFAULT_SUMMARY = REPO / "data" / "benchmark" / "eval_summary.json"

# Import goal-driven gates
sys.path.insert(0, str(REPO))
from constraints.engine import ConstraintEngine, CheckOutcome  # noqa: E402
from scripts.goal_driven_loop import criteria_met, gate2_review  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pkg_key(login: str, slug: str) -> str:
    return f"{login}/{slug}"


def mirror_pkg_path(mirror_root: Path, login: str, slug: str) -> Path:
    return mirror_root / "packages" / login / slug


def rel_to_repo(path: Path) -> Path:
    return path.relative_to(REPO)


def load_done_keys(out_path: Path, stage: str) -> set[str]:
    if not out_path.is_file():
        return set()
    done = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("stage") == stage and row.get("status") == "ok":
            done.add(row.get("package", ""))
    return done


def append_result(out_path: Path, row: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_gate1(engine: ConstraintEngine, pkg: Path) -> dict:
    rel = rel_to_repo(pkg)
    ok, failures = criteria_met(engine, pkg)
    fail_summaries = []
    for f in failures[:10]:
        detail = getattr(f, "detail", str(f))
        cid = getattr(f, "constraint_id", "?")
        fail_summaries.append(f"{cid}: {detail[:120]}")
    return {
        "passed": ok,
        "failure_count": len(failures),
        "failures": fail_summaries,
    }


def run_gate2_stub(pkg: Path) -> dict:
    ok, msg = gate2_review(pkg, use_panel=False)
    return {"passed": ok, "message": msg[:500] if msg else ""}


def run_gate2_panel(pkg: Path) -> dict:
    ok, msg = gate2_review(pkg, use_panel=True)
    return {"passed": ok, "message": msg[:500] if msg else ""}


def discover_packages(mirror_root: Path) -> list[tuple[str, str, Path]]:
    packages_dir = mirror_root / "packages"
    out = []
    for login_dir in sorted(packages_dir.iterdir()):
        if not login_dir.is_dir():
            continue
        for slug_dir in sorted(login_dir.iterdir()):
            if slug_dir.is_dir() and (slug_dir / "manifest.json").is_file():
                out.append((login_dir.name, slug_dir.name, slug_dir))
    return out


def write_summary(out_path: Path, summary_path: Path) -> None:
    by_pkg: dict[str, dict] = {}
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        pk = row.get("package", "")
        stage = row.get("stage", "")
        by_pkg.setdefault(pk, {})[stage] = row

    def _stage_passed(pkg_stages: dict, stage: str) -> bool:
        row = pkg_stages.get(stage, {})
        return bool(row.get("result", {}).get("passed"))

    gate1_pass = sum(1 for v in by_pkg.values() if _stage_passed(v, "gate1"))
    g2_stub_pass = sum(1 for v in by_pkg.values() if _stage_passed(v, "gate2-stub"))
    g2_panel_pass = sum(1 for v in by_pkg.values() if _stage_passed(v, "gate2-panel"))
    summary = {
        "generated_at": utc_now(),
        "packages_evaluated": len(by_pkg),
        "gate1_pass": gate1_pass,
        "gate2_stub_pass": g2_stub_pass,
        "gate2_panel_pass": g2_panel_pass,
        "judge_backend": os.environ.get("HAIDIAN_JUDGE_BACKEND", "mlx"),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--stages",
        default="gate1,gate2-stub",
        help="Comma-separated: gate1, gate2-stub, gate2-panel",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-packages", type=int, default=0)
    parser.add_argument("--login", default="", help="Filter to one login")
    parser.add_argument("--slug", default="", help="Filter to one slug")
    args = parser.parse_args()

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    valid = {"gate1", "gate2-stub", "gate2-panel"}
    bad = set(stages) - valid
    if bad:
        print(f"Unknown stages: {bad}", file=sys.stderr)
        return 1

    if "gate2-panel" in stages:
        backend = os.environ.get("HAIDIAN_JUDGE_BACKEND", "mlx")
        print(
            f"WARNING: gate2-panel runs 7 LLM judges per package. "
            f"Backend={backend}. Expect days for 923 packages on local MLX.",
            flush=True,
        )

    packages = discover_packages(args.mirror_root)
    if args.login:
        packages = [p for p in packages if p[0] == args.login]
    if args.slug:
        packages = [p for p in packages if p[1] == args.slug]
    if args.max_packages:
        packages = packages[: args.max_packages]

    print(f"Evaluating {len(packages)} packages, stages={stages}", flush=True)
    engine = ConstraintEngine(REPO)
    engine.load_registry()

    for stage in stages:
        done = load_done_keys(args.out, stage) if args.resume else set()
        t0 = time.time()
        for i, (login, slug, pkg) in enumerate(packages, 1):
            pk = pkg_key(login, slug)
            if pk in done:
                continue
            row = {
                "at": utc_now(),
                "package": pk,
                "login": login,
                "slug": slug,
                "path": str(rel_to_repo(pkg)),
                "stage": stage,
                "status": "ok",
            }
            try:
                if stage == "gate1":
                    row["result"] = run_gate1(engine, pkg)
                elif stage == "gate2-stub":
                    row["result"] = run_gate2_stub(pkg)
                elif stage == "gate2-panel":
                    row["result"] = run_gate2_panel(pkg)
            except Exception as e:
                row["status"] = "error"
                row["error"] = str(e)[:300]

            append_result(args.out, row)
            if i % 50 == 0:
                elapsed = time.time() - t0
                print(f"  [{stage}] {i}/{len(packages)} ({elapsed:.0f}s)", flush=True)

        print(f"Stage {stage} done.", flush=True)

    if args.out.is_file():
        write_summary(args.out, args.summary)
        print(f"Summary → {args.summary.relative_to(REPO)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
