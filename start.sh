#!/usr/bin/env bash
# Start Paper Workbench in the background. Stop it with ./stop.sh.
# Use another port with: PORT=8766 ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
PIDFILE="data/workbench.pid"
LOG="data/workbench.log"
URL="http://127.0.0.1:$PORT"
mkdir -p data

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Paper Workbench is already running: $URL"
  exit 0
fi
rm -f "$PIDFILE"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it from https://docs.astral.sh/uv/ and try again."
  exit 1
fi
if lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Port $PORT is already in use. Stop that program, or run: PORT=8766 ./start.sh"
  exit 1
fi

echo "--- start $(date '+%Y-%m-%d %H:%M:%S') ---" >>"$LOG"
PORT="$PORT" nohup uv run app.py >>"$LOG" 2>&1 &
echo $! >"$PIDFILE"

# wait up to 60 s (the first run installs the Python packages)
for _ in $(seq 1 120); do
  if curl -fs "$URL/" >/dev/null 2>&1; then
    echo "Paper Workbench is running: $URL"
    echo "Log: $LOG. Stop it with ./stop.sh"
    exit 0
  fi
  if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Paper Workbench did not start. The end of $LOG:"
    tail -n 20 "$LOG"
    rm -f "$PIDFILE"
    exit 1
  fi
  sleep 0.5
done
echo "Still starting after 60 seconds. Check $LOG"
