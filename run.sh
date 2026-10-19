#!/bin/bash

# Project directory: wherever this script is (it was fixed to /home/kida-01/Desktop/Kida-Robot)
PROJECT_DIR="$(dirname "$(readlink -f "$0")")"
cd "$PROJECT_DIR" || exit 1

# Activate her virtual environment: venv/ in the repo, else ~/kida-venv (the old service's)
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "$HOME/kida-venv" ]; then
    source "$HOME/kida-venv/bin/activate"
fi

mkdir -p "$PROJECT_DIR/logs"
LOG_FILE="$PROJECT_DIR/logs/kida_run.log"

# HailoRT's own client-side log (hailort.log/hailort.1.log) defaults to CWD
# otherwise, littering the project root.
export HAILORT_LOGGER_PATH="$PROJECT_DIR/logs"

# Infinite loop to restart on crash
while true; do
    echo "Starting main.py at $(date)" | tee -a "$LOG_FILE"
    python3 -u scripts/main.py 2>&1 | tee -a "$LOG_FILE"
    code=${PIPESTATUS[0]}
    if [ "$code" -eq 99 ]; then
        echo "main.py exited via hard quit (Q) — not restarting." | tee -a "$LOG_FILE"
        break
    fi
    echo "main.py crashed with exit code $code — restarting in 5 seconds..." | tee -a "$LOG_FILE"
    sleep 5
done
