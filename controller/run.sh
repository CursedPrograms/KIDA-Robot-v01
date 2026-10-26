#!/bin/bash
# run.sh — launch the KIDA remote controller
#
# Usage: ./run.sh <robot-ip-or-url> [--port 5004] [--emulate]
#        ./run.sh          no robot: EMULATE, her pretend self on this PC
#    or: ROBOT_URL=http://192.168.1.50:5004 ./run.sh

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "No venv found — run ./setup_venv.sh first."
    exit 1
fi

python3 main.py "$@"
