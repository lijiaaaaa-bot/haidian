#!/bin/bash
# Goal-Driven autonomous loop for haidian urban design
# Runs until DONE or MAX_HOURS (12h)
# Keep alive: loops restart on crash. A hung Ollama (HTTP 500s from the big
# models) is the usual crash cause, so Ollama is hard-restarted before each
# relaunch. Each restart gets its own timestamped log; only the last 10 logs
# are kept.

cd "$(dirname "$0")/.."

export HAIDIAN_WRITER_MODEL="${HAIDIAN_WRITER_MODEL:-qwen3.6:35b-a3b}"
export HAIDIAN_CODER_MODEL="${HAIDIAN_CODER_MODEL:-qwen3-coder:30b}"

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
    echo "=== $(date) crashed (exit=$EXIT), restarting Ollama + loop ===" >> "$LOG"
    # Hard-restart Ollama before relaunching the loop (hung Ollama -> HTTP 500s).
    # `|| true`: pkill returns non-zero when no ollama process exists, which
    # must not skip the restart.
    pkill -9 ollama || true
    sleep 5
    open -a Ollama || true
    sleep 15
    sleep 30
done

echo "DONE. Log: $LOG"
