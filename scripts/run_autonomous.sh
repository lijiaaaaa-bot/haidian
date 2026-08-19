#!/bin/bash
# haidian autoresearch — canonical single-run acceptance check
#
# Default: run acceptance once and print next steps (program.md + Cursor).
# Legacy MLX master loop: HAIDIAN_LEGACY_LOOP=1 bash scripts/run_autonomous.sh

set -euo pipefail
cd "$(dirname "$0")/.."

SUBMISSION="${HAIDIAN_SUBMISSION:-submissions/test/autoresearch}"

if [ "${HAIDIAN_LEGACY_LOOP:-}" = "1" ]; then
    echo "DEPRECATED: legacy goal_driven_loop (MLX). Prefer program.md + acceptance.py." >&2
    export HAIDIAN_MLX="${HAIDIAN_MLX:-true}"
    export HAIDIAN_WRITER_MODEL="${HAIDIAN_WRITER_MODEL:-/Users/lijia/.cache/mlx/Qwen3.8-27B-4bit}"
    export HAIDIAN_CODER_MODEL="${HAIDIAN_CODER_MODEL:-Indelwin/Qwen3-ToolAgent-GRPO-MLX}"
    exec python3 scripts/goal_driven_loop.py \
        --submission "${SUBMISSION}" \
        --agent-name "${HAIDIAN_AGENT_NAME:-Autonomous}" \
        "$@"
fi

echo "=== haidian autoresearch (canonical) ==="
echo "Submission: ${SUBMISSION}"
echo ""
python3 scripts/acceptance.py --submission "${SUBMISSION}"
echo ""
echo "Next: follow program.md — pick ONE failure, fix, git commit, re-run acceptance."
echo "  Cursor/Cloud Agent: read program.md in repo root."
echo ""
echo "Legacy MLX loop (deprecated): HAIDIAN_LEGACY_LOOP=1 bash scripts/run_autonomous.sh"
