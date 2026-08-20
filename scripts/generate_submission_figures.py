#!/usr/bin/env python3
"""Generate 5 core submission figures — UST if available, else goal-driven geopandas renderer.

Fail-fast only when BOTH UST and geopandas renderer fail (no empty/PIL placeholders).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.goal_driven_loop import (  # noqa: E402
    FIGURE_TYPE_TO_FILENAME,
    _handle_generate_figure,
    _import_ust,
)

FIGURE_TYPES = ["site_overview", "land_use", "key_areas", "mobility", "metrics"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission_dir", type=Path, nargs="?",
                        default=REPO / "submissions/lijiaaaaa-bot/jingzhang-zhimai-belt")
    parser.add_argument("--ust-root", type=Path, default=None,
                        help="Override UST_ROOT (default: env or /Users/lijia/Projects/urban-spatial-tooling)")
    args = parser.parse_args()

    sub = args.submission_dir if args.submission_dir.is_absolute() else REPO / args.submission_dir
    if not sub.is_dir():
        print(f"ERROR: submission not found: {sub}", file=sys.stderr)
        return 1

    if args.ust_root:
        os.environ["UST_ROOT"] = str(args.ust_root)
        import scripts.goal_driven_loop as gdl
        gdl.UST_ROOT = args.ust_root.resolve()

    ust = _import_ust()
    engine = "urban-spatial-tooling" if ust else "goal-driven geopandas (300dpi)"
    print(f"Figure engine: {engine}", flush=True)

    total_kb = 0.0
    for ftype in FIGURE_TYPES:
        msg = _handle_generate_figure(ftype, [], str(sub.relative_to(REPO)))
        print(msg, flush=True)
        if msg.startswith("错误"):
            print(f"ERROR: figure generation failed for {ftype}", file=sys.stderr)
            return 1
        out = sub / "assets" / "figures" / FIGURE_TYPE_TO_FILENAME[ftype]
        if not out.is_file() or out.stat().st_size < 50_000:
            print(f"ERROR: {out.name} missing or too small (<50KB)", file=sys.stderr)
            return 1
        total_kb += out.stat().st_size / 1024

    print(f"OK: 5 figures, total {total_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
