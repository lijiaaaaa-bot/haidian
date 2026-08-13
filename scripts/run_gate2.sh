#!/bin/bash
export HAIDIAN_JUDGE_BACKEND=deepseek
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 scripts/panel_runner.py submissions/test/test
