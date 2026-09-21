#!/bin/bash
# run_map_summary.sh — concatenate every mapper/output/*_stats.txt and
# hand the stream to the compiled map-summary COBOL program.
set -euo pipefail
cd "$(dirname "$0")"

STATS_DIR="${1:-../mapper/output}"
BIN="./map-summary"

if [ ! -x "$BIN" ]; then
    echo "map-summary not built yet — run: cobc -x -o map-summary map-summary.cob" >&2
    exit 1
fi

shopt -s nullglob
FILES=("$STATS_DIR"/*_stats.txt)
if [ ${#FILES[@]} -eq 0 ]; then
    echo "No *_stats.txt files found in $STATS_DIR — run mapper/build_3d_map.py first." >&2
    exit 1
fi

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
cat "${FILES[@]}" > "$TMP"
"$BIN" "$TMP"
