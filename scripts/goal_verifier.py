#!/usr/bin/env python3
"""Deterministic goal-driven verifier for haidian.

Usage:
    python3 scripts/goal_verifier.py [--submission submissions/test/test]
    python3 scripts/goal_verifier.py --full   # same as acceptance.py (default now)

Prints the number of failing constraints (the loop's target number, goal=0).
Also prints each FAIL id + detail so the driver can pick one to fix.

For the unified acceptance criteria (CODE + content + self_check), prefer:
    python3 scripts/acceptance.py --submission ...

Must be deterministic — no LLM, no network. The agent under test must NOT
edit this file, constraints/, scripts/, brief/, schema/, or templates/.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.acceptance import evaluate_acceptance, print_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", default="submissions/test/test")
    ap.add_argument(
        "--code-only",
        action="store_true",
        help="Legacy: CODE constraints only (omit content floors and self_check)",
    )
    args = ap.parse_args()

    sub = (ROOT / args.submission).resolve()
    failures, vector = evaluate_acceptance(sub, code_only=args.code_only)
    print_report(failures, vector)
    return 0 if vector.total_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
