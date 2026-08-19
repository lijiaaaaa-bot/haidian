#!/usr/bin/env python3
"""ARCHIVED — 6-phase FSM pipeline entry.

Canonical: program.md + scripts/acceptance.py
Run via: HAIDIAN_LEGACY_FSM=1 python3 run_pipeline.py ...

Single entry point for the haidian urban design pipeline.

This replaces the previous fragmented workflow (scaffold → manual generate →
self_check → finalize → separate constraint check → separate review) with
ONE command that drives the UrbanDesignProcedure state machine through all
6 professional phases.

Usage:
    # Full pipeline (stops at each JUDGMENT point for LLM input)
    python3 run_pipeline.py --submission submissions/<login>/<slug>

    # Resume after LLM generation for a phase
    python3 run_pipeline.py --submission submissions/<login>/<slug> --continue-after site_analysis

    # JSON status output
    python3 run_pipeline.py --submission submissions/<login>/<slug> --json

    # State machine summary (no generation)
    python3 run_pipeline.py --summary

Architecture:
    ┌──────────────────────────────────────────────────┐
    │ run_pipeline.py (this file)                      │
    │                                                  │
    │  1. Scaffold (if new submission)                 │
    │  2. UrbanDesignProcedure (6 phases)              │
    │     ├─ Phase 1: Site Analysis (CODE + JUDGMENT)  │
    │     ├─ Phase 2: Strategic Framework              │
    │     ├─ Phase 3: Detailed Design                  │
    │     ├─ Phase 4: System Integration               │
    │     ├─ Phase 5: Implementation                   │
    │     └─ Phase 6: Compliance & Packaging            │
    │  3. Constraint Engine (all 61 CODE checks)       │
    │  4. Reflection Panel (7 LLM judges)              │
    │  5. Finalize (lock package)                      │
    │                                                  │
    │  → completed / retry / escalate                  │
    └──────────────────────────────────────────────────┘
"""

import argparse
import json
import sys
from pathlib import Path

from constraints.orchestrator import Orchestrator, LoopStatus


def cmd_scaffold(submission_path: Path, repo_root: Path):
    """Scaffold a new submission if it doesn't exist."""
    if submission_path.exists():
        print(f"Submission already exists: {submission_path}")
        return True

    scaffold_script = repo_root / "scripts" / "scaffold_ai_submission.py"
    if scaffold_script.exists():
        import subprocess
        result = subprocess.run(
            ["python3", str(scaffold_script), str(submission_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Scaffold failed: {result.stderr}")
            return False
        print(f"Scaffolded: {submission_path}")
        return True
    else:
        print(f"Scaffold script not found: {scaffold_script}")
        print("Creating minimal submission structure...")
        submission_path.mkdir(parents=True, exist_ok=True)
        (submission_path / "geometry").mkdir(exist_ok=True)
        (submission_path / "assets" / "figures").mkdir(parents=True, exist_ok=True)
        (submission_path / "report").mkdir(exist_ok=True)
        (submission_path / "drawings").mkdir(exist_ok=True)
        (submission_path / "visual").mkdir(exist_ok=True)
        return True


def cmd_summary(repo_root: Path):
    """Print the state machine workflow summary."""
    from constraints.procedure import UrbanDesignProcedure
    proc = UrbanDesignProcedure.from_repo(str(repo_root))
    print(proc.print_workflow())


def cmd_status(submission_path: Path, repo_root: Path):
    """Check the status of an existing submission."""
    state_file = submission_path / ".orchestrator" / "state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        print(json.dumps(state, indent=2, ensure_ascii=False))
    else:
        orch = Orchestrator(str(submission_path), str(repo_root))
        print(json.dumps(orch.status_report(), indent=2, ensure_ascii=False))


def cmd_validate(submission_path: Path, repo_root: Path):
    """Run constraint engine validation only."""
    from constraints.engine import ConstraintEngine
    engine = ConstraintEngine(repo_root)
    results = engine.validate(str(submission_path))
    report = engine.report(results)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="haidian Urban Design Pipeline — Single Entry Point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_pipeline.py --submission submissions/my-name/my-proposal
  python3 run_pipeline.py --submission submissions/my-name/my-proposal --continue-after site_analysis
  python3 run_pipeline.py --summary
  python3 run_pipeline.py --validate submissions/my-name/my-proposal
        """,
    )
    parser.add_argument("--submission", help="Path to submission directory")
    parser.add_argument("--repo-root", default=".", help="Path to haidian repo root")
    parser.add_argument("--continue-after", metavar="PHASE_ID",
                        help="Continue pipeline after LLM generation for a phase")
    parser.add_argument("--summary", action="store_true",
                        help="Print state machine workflow summary")
    parser.add_argument("--status", action="store_true",
                        help="Check submission status")
    parser.add_argument("--validate", metavar="PATH",
                        help="Run constraint engine validation only")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON format")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    # ── Summary mode ──
    if args.summary:
        cmd_summary(repo_root)
        return

    # ── Validate-only mode ──
    if args.validate:
        cmd_validate(Path(args.validate), repo_root)
        return

    # ── Pipeline modes (need --submission) ──
    if not args.submission:
        parser.error("--submission is required (or use --summary / --validate)")

    submission_path = Path(args.submission)
    if not submission_path.is_absolute():
        submission_path = Path.cwd() / submission_path

    # ── Status mode ──
    if args.status:
        cmd_status(submission_path, repo_root)
        return

    # ── Scaffold if new ──
    if not submission_path.exists():
        if not cmd_scaffold(submission_path, repo_root):
            sys.exit(1)

    # ── Run pipeline ──
    orch = Orchestrator(str(submission_path), str(repo_root))

    if args.continue_after:
        result = orch.continue_after_llm(args.continue_after)
    else:
        result = orch.run()

    # ── Output ──
    if args.json:
        print(json.dumps(orch.status_report(), indent=2, ensure_ascii=False))
    else:
        report = orch.status_report()
        print(f"\nPipeline: {report['overall_status']}")
        print(f"Phase: {report['current_phase']}")
        print(f"Iterations: {report['total_iterations']}")
        if report['overall_status'] == 'escalated':
            sys.exit(1)


if __name__ == "__main__":
    main()
