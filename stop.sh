#!/usr/bin/env bash
# Stop the Paper Workbench started by ./start.sh. Use PORT=... if you started it on another port.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
PIDFILE="data/workbench.pid"

# Only stop processes that are this app (uv or Python running app.py), never anything else on the port.
ours() { ps -o command= -p "$1" 2>/dev/null | grep -q "app.py"; }

pids=""
if [[ -f "$PIDFILE" ]]; then pids="$(cat "$PIDFILE")"; fi
# uv starts Python as a child; also catch the server itself, in case it was started another way
for p in $(lsof -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true); do pids="$pids $p"; done

found=0
for p in $pids; do
  if kill -0 "$p" 2>/dev/null && ours "$p"; then
    kill "$p" 2>/dev/null || true
    found=1
  fi
done

# give it 5 seconds to finish saving, then force it
for _ in $(seq 1 10); do
  left=""
  for p in $pids; do kill -0 "$p" 2>/dev/null && ours "$p" && left="$left $p"; done
  [[ -z "$left" ]] && break
  sleep 0.5
done
for p in ${left:-}; do kill -9 "$p" 2>/dev/null || true; done
rm -f "$PIDFILE"

if [[ $found == 1 ]]; then echo "Paper Workbench stopped."; else echo "Paper Workbench was not running."; fi
