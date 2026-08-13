#!/bin/bash
export HAIDIAN_MLX=true
export HAIDIAN_JUDGE_BACKEND=deepseek
export HAIDIAN_DEEPSEEK_MODEL=deepseek-v4-flash
export HAIDIAN_WRITER_MODEL=Basher17/Ornith-1.0-35B-oQ4e
export HAIDIAN_CODER_MODEL=Indelwin/Qwen3-ToolAgent-GRPO-MLX
cd /Users/lijia/Projects/haidian
bash scripts/run_autonomous.sh
