#!/bin/bash
# Quick start: canonical acceptance check (see program.md for the full loop)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export HAIDIAN_SUBMISSION="${HAIDIAN_SUBMISSION:-submissions/test/autoresearch}"
bash scripts/run_autonomous.sh "$@"
