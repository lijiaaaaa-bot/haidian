#!/usr/bin/env python3
"""Deterministic goal-driven verifier for haidian.

Usage:
    python3.13 scripts/goal_verifier.py [--submission submissions/test/test]

Prints the number of failing constraints (the loop's target number, goal=0).
Also prints each FAIL id + detail so the driver can pick one to fix.
Must be deterministic — no LLM, no network. The agent under test must NOT
edit this file, constraints/, scripts/, brief/, schema/, or templates/.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from constraints.engine import CheckOutcome, ConstraintEngine  # noqa: E402
import scripts.goal_driven_loop as g  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", default="submissions/test/test")
    args = ap.parse_args()

    engine = ConstraintEngine(str(ROOT))
    engine.load_registry()
    sub = (ROOT / args.submission).resolve()

    results = engine.validate(sub.relative_to(ROOT))
    failures = [r for r in results if r.outcome in (CheckOutcome.FAIL, CheckOutcome.ERROR)]
    failures += g._missing_required_metrics(engine, sub)

    print(f"FAILURES {len(failures)}")
    for r in failures:
        print(f"FAIL {r.constraint_id} | {getattr(r, 'detail', '') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())