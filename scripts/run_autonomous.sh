#!/bin/bash
# Goal-Driven autonomous loop for haidian urban design
# Runs until DONE or MAX_HOURS (12h)
# Keep alive: loops restart on crash. A hung Ollama (HTTP 500s from the big
# models) is the usual crash cause, so Ollama is hard-restarted before each
# relaunch. Each restart gets its own timestamped log; only the last 10 logs
# are kept.

cd "$(dirname "$0")/.."

export HAIDIAN_MLX=true
export HAIDIAN_WRITER_MODEL="${HAIDIAN_WRITER_MODEL:-/Users/lijia/.cache/mlx/Qwen3.8-27B-4bit}"
# 工具调用专用模型(coder):ToolAgent(JSON 格式 tool_call);Qwen3.8-27B 实测
# 多轮工具调用退化(只读不写),不适合当 agent 循环里的 coder
export HAIDIAN_CODER_MODEL="${HAIDIAN_CODER_MODEL:-Indelwin/Qwen3-ToolAgent-GRPO-MLX}"
# Ollama restart no longer needed with MLX
OMIT_OLLAMA_RESTART=true

LOG_DIR="/tmp"

# Keep only the 10 most recent goal-driven logs.
prune_logs() {
    ls -1t "$LOG_DIR"/m1-autonomous-*.log 2>/dev/null | tail -n +11 | xargs -r rm -f
}

while true; do
    LOG="$LOG_DIR/m1-autonomous-$(date +%Y%m%d-%H%M%S).log"
    prune_logs
    echo "=== $(date) Starting Goal-Driven loop ===" >> "$LOG"
    python3 scripts/goal_driven_loop.py \
        --submission submissions/test/test \
        --agent-name "Autonomous" \
        >> "$LOG" 2>&1

    EXIT=$?
    if [ $EXIT -eq 0 ]; then
        echo "=== $(date) DONE — criteria met ===" >> "$LOG"
        break
    fi
    echo "=== $(date) crashed (exit=$EXIT), restarting loop ===" >> "$LOG"
    # With MLX: no Ollama to restart — just back off and retry
    if [ "${OMIT_OLLAMA_RESTART:-}" = "true" ]; then
        sleep 10
    else
        pkill -9 ollama || true
        sleep 5
        open -a Ollama || true
        sleep 15
        sleep 30
    fi
done

echo "DONE. Log: $LOG"
