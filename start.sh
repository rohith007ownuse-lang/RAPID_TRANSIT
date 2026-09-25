#!/usr/bin/env bash
# One-click launcher for the Urban Intelligence Control Centre.
# Starts the backend API + frontend, then opens the browser automatically.
set -e
cd "$(dirname "$0")"

PORT=${PORT:-5001}
WS_PORT=${WS_PORT:-8765}
FRONT_PORT=${FRONT_PORT:-5173}
URL="http://localhost:${FRONT_PORT}"

echo "🚌 Urban Intelligence — starting Control Centre…"

# --- Backend (Flask API + fleet simulator + WebSocket) ---
# Only reuse an existing instance if it actually responds as THIS project's API.
if curl -s -m 1 "http://127.0.0.1:${PORT}/api/health" | grep -q '"status": *"ok"'; then
  echo "✓ Backend already running on :${PORT}"
  BACKEND_PID=""
else
  if [ -x "control_centre/backend/venv/bin/python" ]; then
    PY=control_centre/backend/venv/bin/python
  else
    PY=python3
  fi
  echo "▶ Starting backend on :${PORT} (WS :${WS_PORT})…"
  ( cd control_centre/backend && "$PY" server.py --port "$PORT" --ws-port "$WS_PORT" >/tmp/cc_backend.log 2>&1 ) &
  BACKEND_PID=$!
fi

# --- Frontend (Vite dev server) ---
# Reuse only if the running page actually is the Control Centre index.
if curl -s -m 1 "http://127.0.0.1:${FRONT_PORT}" | grep -qi "urban intell"; then
  echo "✓ Frontend already running on :${FRONT_PORT}"
  FRONT_PID=""
else
  echo "▶ Starting frontend on :${FRONT_PORT}…"
  ( cd control_centre/frontend && npm run dev >/tmp/cc_frontend.log 2>&1 ) &
  FRONT_PID=$!
fi

# --- Wait for frontend, then open browser ---
echo -n "Waiting for frontend…"
for i in $(seq 1 30); do
  if curl -s -m 1 "http://127.0.0.1:${FRONT_PORT}" >/dev/null 2>&1; then
    echo " up."
    break
  fi
  sleep 1
done

echo "🌐 Opening ${URL}"
( xdg-open "$URL" >/dev/null 2>&1 || gio open "$URL" >/dev/null 2>&1 || true ) &

echo
echo "─────────────────────────────────────────────"
echo "  Control Centre is running at:  ${URL}"
echo "  Press Ctrl+C here to stop."
echo "─────────────────────────────────────────────"

cleanup() {
  echo; echo "Stopping…"
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONT_PID" ] && kill "$FRONT_PID" 2>/dev/null || true
  echo "Done."
}
trap cleanup EXIT INT TERM

wait
