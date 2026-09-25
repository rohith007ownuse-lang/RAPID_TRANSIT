#!/usr/bin/env bash
# One-click launcher for the Rapid Tracker Control Centre.
# Starts the backend API + frontend, then opens the browser automatically.
set -e
cd "$(dirname "$0")"

PORT=${PORT:-5001}
WS_PORT=${WS_PORT:-8765}
FRONT_PORT=${FRONT_PORT:-5173}
# Demo-ready defaults (override by exporting before launch).
# Binds ALL interfaces so operator laptops on the same Wi-Fi/hotspot work;
# identical behaviour with zero operators attached.
START_MODE="${START_MODE:-live}"
ASSIGN_MAX="${ASSIGN_MAX:-2}"
ASSIGN_TIMEOUT="${ASSIGN_TIMEOUT:-20}"
# Demo incident rotation (temporary "only for now" behaviour): keeps ~5
# incidents visible and cycles them every 2 minutes. Set ROTATION=0 to disable.
DEMO_ROTATION="${DEMO_ROTATION:-1}"
DEMO_MAX_ACTIVE="${DEMO_MAX_ACTIVE:-5}"
DEMO_ROTATION_SEC="${DEMO_ROTATION_SEC:-120}"
URL="http://localhost:${FRONT_PORT}"

echo "🚌 Rapid Tracker — starting Control Centre…"

# --- Backend (Flask API + fleet simulator + WebSocket) ---
# Only reuse an existing instance if it actually responds as THIS project's API
# (both markers required — a generic {"status":"ok"} from another service
# must not skip our startup).
if curl -s -m 1 "http://127.0.0.1:${PORT}/api/health" | grep -q '"status": *"ok"' \
  && curl -s -m 1 "http://127.0.0.1:${PORT}/api/health" | grep -q 'live_prototype_connected'; then
  echo "✓ Backend already running on :${PORT}"
  BACKEND_PID=""
else
  if [ -x "$PWD/control_centre/backend/venv/bin/python" ]; then
    PY="$PWD/control_centre/backend/venv/bin/python"
  else
    PY=python3
  fi
  echo "▶ Starting backend on :${PORT} (WS :${WS_PORT}, mode=${START_MODE})…"
  ( cd control_centre/backend && FLEETIQ_AUTO_ASSIGN_MAX_ATTEMPTS="$ASSIGN_MAX" FLEETIQ_AUTO_ASSIGN_TIMEOUT_SEC="$ASSIGN_TIMEOUT" FLEETIQ_DEMO_INCIDENT_ROTATION="$DEMO_ROTATION" FLEETIQ_DEMO_MAX_ACTIVE_INCIDENTS="$DEMO_MAX_ACTIVE" FLEETIQ_DEMO_ROTATION_SEC="$DEMO_ROTATION_SEC" "$PY" server.py --host 0.0.0.0 --port "$PORT" --ws-port "$WS_PORT" --start-mode "$START_MODE" >/tmp/cc_backend.log 2>&1 ) &
  BACKEND_PID=$!
fi

# --- Frontend (Vite dev server) ---
# Reuse only if the running page actually is the Control Centre index.
if curl -s -m 1 "http://127.0.0.1:${FRONT_PORT}" | grep -qi "urban intell"; then
  echo "✓ Frontend already running on :${FRONT_PORT}"
  FRONT_PID=""
else
  echo "▶ Starting frontend on :${FRONT_PORT}…"
  ( cd control_centre/frontend && npm run dev -- --host --port "$FRONT_PORT" >/tmp/cc_frontend.log 2>&1 ) &
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
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$LAN_IP" ] && echo "  Operator laptops join: http://${LAN_IP}:${FRONT_PORT}"
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
