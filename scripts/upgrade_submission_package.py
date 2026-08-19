#!/usr/bin/env python3
"""Orchestrate submission package upgrade (no-fallback pipeline).

Geometry/data steps run on Cloud VM with --skip-ust-figures.
Full pipeline including UST figures requires UST_ROOT on local Mac.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
DEFAULT_SUB = REPO / "submissions" / "lijiaaaaa-bot" / "jingzhang-zhimai-belt"


def run_step(label: str, cmd: list[str]) -> None:
    print(f"\n==> {label}", flush=True)
    print("    ", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=REPO)
    if r.returncode != 0:
        print(f"ERROR: step failed: {label} (exit {r.returncode})", file=sys.stderr)
        sys.exit(r.returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission_dir", type=Path, nargs="?", default=DEFAULT_SUB)
    parser.add_argument("--skip-ust-figures", action="store_true",
                        help="Stop after geometry/data (Cloud VM mode)")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    sub = args.submission_dir if args.submission_dir.is_absolute() else REPO / args.submission_dir
    py = sys.executable

    if not args.skip_verify:
        verify_cmd = [py, str(SCRIPTS / "verify_submission_prerequisites.py")]
        if args.skip_ust_figures:
            verify_cmd.append("--skip-ust")
        run_step("verify prerequisites", verify_cmd)

    run_step("sync boundary", [py, str(SCRIPTS / "sync_submission_boundary.py"), str(sub)])
    run_step("sync constraints", [py, str(SCRIPTS / "sync_submission_constraints.py"), str(sub)])
    run_step("clip roads", [py, str(SCRIPTS / "clip_corridor_roads.py"), str(sub)])
    run_step("generate design geometry", [
        py, str(SCRIPTS / "generate_design_geometry.py"),
        "--submission-dir", str(sub),
    ])

    fig_script = SCRIPTS / "generate_submission_figures.py"
    if args.skip_ust_figures:
        if fig_script.is_file():
            print("\n==> skip UST figures (--skip-ust-figures); run on Mac with UST_ROOT")
        else:
            print("\n==> generate_submission_figures.py not yet present; geometry/data complete")
        print(f"\nOK: geometry/data upgrade complete for {sub}")
        return 0

    if not fig_script.is_file():
        print("ERROR: generate_submission_figures.py missing; cannot render figures", file=sys.stderr)
        return 1

    run_step("generate UST figures", [py, str(fig_script), str(sub)])

    for label, script in [
        ("render proposal html", "render_proposal_html.py"),
        ("generate drawings", "generate_drawings.py"),
        ("finalize", "finalize_submission.py"),
        ("self check", "self_check_submission.py"),
    ]:
        path = SCRIPTS / script
        if not path.is_file():
            print(f"WARN: skipping missing {script}")
            continue
        cmd = [py, str(path), str(sub)]
        if script == "self_check_submission.py":
            login = sub.parts[-2] if len(sub.parts) >= 2 else "unknown"
            cmd.extend(["--pr-author", login])
        run_step(label, cmd)

    print(f"\nOK: full upgrade pipeline complete for {sub}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
