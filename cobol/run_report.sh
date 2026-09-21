#!/bin/bash
# run_report.sh — clean logs/kida_run.log's occasional embedded binary
# (leftover NUL bytes from mid-session serial-port debugging) into a
# plain-text temp file, then hand that to the compiled kida-report COBOL
# program. See kida-report.cob's header for why the extract step exists.
set -euo pipefail
cd "$(dirname "$0")"

LOG="${1:-../logs/kida_run.log}"
BIN="./kida-report"

if [ ! -x "$BIN" ]; then
    echo "kida-report not built yet — run: cobc -x -o kida-report kida-report.cob" >&2
    exit 1
fi

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
grep -a . "$LOG" > "$TMP"
"$BIN" "$TMP"
