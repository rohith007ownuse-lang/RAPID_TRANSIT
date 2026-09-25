#!/usr/bin/env bash
# Last-minute demo URL with no server, no card, and no credit check.
# Runs the app on this machine and exposes it over HTTPS via a Cloudflare
# Tunnel (trycloudflare.com gives a public URL instantly, no account needed).
#
#   FLEETIQ_ADMIN_PASSWORD='your-password' ./deploy/tunnel-demo.sh
#
# This starts all three pieces: the Flask backend, `vite preview` serving the
# production build (which proxies /api and both WebSockets on the same origin,
# exactly like nginx does on a real server), and the tunnel. Everything is
# loopback-only except the tunnel itself.
#
# Use this when a provisioned server is not ready. The URL changes every run,
# and this machine must stay awake for the whole demo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/control_centre/backend"
FRONTEND="$REPO_ROOT/control_centre/frontend"
DATA_DIR="${FLEETIQ_DEMO_DATA:-$HOME/.local/share/fleetiq-demo}"
CLOUDFLARED="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"

cleanup() {
    echo
    echo "==> Stopping demo (backend, preview, tunnel)"
    [ -n "${TUNNEL_PID:-}" ] && kill "$TUNNEL_PID" 2>/dev/null || true
    [ -n "${PREVIEW_PID:-}" ] && kill "$PREVIEW_PID" 2>/dev/null || true
    [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if ! command -v cloudflared >/dev/null 2>&1 && [ ! -x "$CLOUDFLARED" ]; then
    echo "==> Installing cloudflared into $(dirname "$CLOUDFLARED") (no sudo needed)"
    tmp="$(mktemp -d)"
    arch="$(uname -m)"
    case "$arch" in
        x86_64) bin=cloudflared-linux-amd64 ;;
        aarch64|arm64) bin=cloudflared-linux-arm64 ;;
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
    esac
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/$bin" -o "$tmp/cloudflared"
    mkdir -p "$(dirname "$CLOUDFLARED")"
    install -m 0755 "$tmp/cloudflared" "$CLOUDFLARED"
    rm -rf "$tmp"
fi
[ -x "$CLOUDFLARED" ] || CLOUDFLARED="$(command -v cloudflared)"

: "${FLEETIQ_ADMIN_PASSWORD:?set FLEETIQ_ADMIN_PASSWORD to your demo password}"
mkdir -p "$DATA_DIR"

# Reuse an existing demo database so created users and settings survive restarts.
DB_PATH="$DATA_DIR/control_centre.db"

echo "==> Starting backend (simulation mode, isolated demo database: $DB_PATH)"
(
    cd "$BACKEND"
    exec env \
        FLEETIQ_ENV=production \
        FLEETIQ_SAME_ORIGIN=1 \
        FLEETIQ_ADMIN_USER="${FLEETIQ_ADMIN_USER:-admin}" \
        FLEETIQ_ADMIN_PASSWORD="$FLEETIQ_ADMIN_PASSWORD" \
        FLEETIQ_DB="$DB_PATH" \
        FLEETIQ_DRIVER_CAMERA_DEVICE=none \
        FLEETIQ_CABIN_CAMERA_DEVICE=none \
        FLEETIQ_ROAD_CAMERA_DEVICE=none \
        ./venv/bin/python server.py --host 127.0.0.1 --port 5001 --ws-port 8765 --start-mode simulation
) &
BACKEND_PID=$!

echo "==> Waiting for the API"
for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 http://127.0.0.1:5001/api/health >/dev/null 2>&1; then break; fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "Backend exited during startup. Re-run without the tunnel to see the error." >&2
        exit 1
    fi
    sleep 1
done
curl -fsS --max-time 2 http://127.0.0.1:5001/api/health >/dev/null || {
    echo "Backend did not become healthy in time." >&2; exit 1; }

if [ ! -d "$FRONTEND/node_modules" ]; then
    (cd "$FRONTEND" && npm install --no-audit --no-fund)
fi

# VITE_WS_PATH makes the built bundle talk to /ws on its own origin, so the
# frontend, the REST API and both WebSockets are all one origin — which is what
# the tunnel (and nginx, in a real deployment) needs.
echo "==> Building frontend for same-origin sockets behind the tunnel"
(cd "$FRONTEND" && VITE_WS_PATH=/ws npm run build)

echo "==> Serving the production build on 127.0.0.1:8080 (proxying /api and /ws)"
(cd "$FRONTEND" && exec npx vite preview --port 8080 --host 127.0.0.1) &
PREVIEW_PID=$!

for _ in $(seq 1 30); do
    curl -fsS --max-time 2 http://127.0.0.1:8080/ >/dev/null 2>&1 && break
    sleep 1
done

echo "==> Opening the tunnel (public URL appears below)"
"$CLOUDFLARED" tunnel --url http://127.0.0.1:8080 --no-autoupdate &
TUNNEL_PID=$!

echo
echo "Login for the judges:  ${FLEETIQ_ADMIN_USER:-admin} / $FLEETIQ_ADMIN_PASSWORD"
echo "Local check:           http://127.0.0.1:8080"
echo "The public URL is printed above. Press Ctrl-C to stop everything."
wait
