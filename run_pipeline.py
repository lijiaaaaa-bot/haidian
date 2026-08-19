#!/usr/bin/env python3
"""DEPRECATED — FSM pipeline entry (archived).

Canonical autoresearch loop: ``program.md`` + ``scripts/acceptance.py``.

Legacy implementation: ``archive/run_pipeline.py`` (still runnable via
``HAIDIAN_LEGACY_FSM=1``).
"""

from __future__ import annotations

import os
import sys
import warnings


def _print_canonical_hint() -> None:
    print(
        "DEPRECATED: run_pipeline.py (6-phase FSM) is archived.\n"
        "  Canonical: program.md + scripts/acceptance.py\n"
        "  Legacy FSM: HAIDIAN_LEGACY_FSM=1 python3 run_pipeline.py ...\n",
        file=sys.stderr,
    )


def main() -> None:
    _print_canonical_hint()
    if os.environ.get("HAIDIAN_LEGACY_FSM") == "1":
        warnings.warn(
            "Running archived FSM pipeline from archive/run_pipeline.py",
            DeprecationWarning,
            stacklevel=1,
        )
        from archive.run_pipeline import main as legacy_main

        legacy_main()
        return

    submission = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--submission" and i < len(sys.argv) - 1:
            submission = sys.argv[i + 1]
            break
        if arg.startswith("--submission="):
            submission = arg.split("=", 1)[1]
            break

    if submission:
        from pathlib import Path

        repo = Path(__file__).resolve().parent
        cmd = [
            sys.executable,
            str(repo / "scripts" / "acceptance.py"),
            "--submission",
            submission,
        ]
        raise SystemExit(__import__("subprocess").call(cmd, cwd=repo))

    print("Pass --submission or set HAIDIAN_LEGACY_FSM=1 for the archived FSM.")
    raise SystemExit(2)


if __name__ == "__main__":
    main()
