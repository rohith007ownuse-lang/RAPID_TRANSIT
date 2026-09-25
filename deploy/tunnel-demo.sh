#!/usr/bin/env bash
# Last-minute demo URL with no server, no card, and no credit check.
# Runs the app on this machine and exposes it over HTTPS via a Cloudflare
# Tunnel (trycloudflare.com gives a public URL instantly, no account needed).
#
#   ./deploy/tunnel-demo.sh            # tunnel + backend + frontend preview
#
# Use this when a provisioned server is not ready. The URL changes every run,
# and this machine must stay awake for the whole demo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/control_centre/backend"
FRONTEND="$REPO_ROOT/control_centre/frontend"
DATA_DIR="${FLEETIQ_DEMO_DATA:-$HOME/.local/share/fleetiq-demo}"

if ! command -v cloudflared >/dev/null 2>&1; then
    echo "==> Installing cloudflared"
    tmp="$(mktemp -d)"
    arch="$(uname -m)"
    case "$arch" in
        x86_64) bin=cloudflared-linux-amd64 ;;
        aarch64|arm64) bin=cloudflared-linux-arm64 ;;
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
    esac
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/$bin" -o "$tmp/cloudflared"
    sudo install -m 0755 "$tmp/cloudflared" /usr/local/bin/cloudflared
    rm -rf "$tmp"
fi

mkdir -p "$DATA_DIR"

echo "==> Starting backend (simulation mode, demo database)"
(
    cd "$BACKEND"
    FLEETIQ_ENV=production \
    FLEETIQ_SAME_ORIGIN=1 \
    FLEETIQ_ADMIN_USER="${FLEETIQ_ADMIN_USER:-admin}" \
    FLEETIQ_ADMIN_PASSWORD="${FLEETIQ_ADMIN_PASSWORD:?set FLEETIQ_ADMIN_PASSWORD to your demo password}" \
    FLEETIQ_DB="$DATA_DIR/control_centre.db" \
    ./venv/bin/python server.py --host 127.0.0.1 --port 5001 --ws-port 8765 --start-mode simulation
) &

if [ ! -d "$FRONTEND/node_modules" ]; then
    (cd "$FRONTEND" && npm install --no-audit --no-fund)
fi

echo "==> Building frontend for same-origin sockets behind the tunnel"
(cd "$FRONTEND" && VITE_WS_PATH=/ws npm run build)

echo "==> Building backend + websocket proxy for the tunnel"
(cd "$REPO_ROOT/deploy" && CLOUDFLARED_TUNNEL_DIR="$DATA_DIR" bash -c '
set -euo pipefail
printf "%s\n" \
  "ingress:" \
  "  - hostname: {*}" \
  "    path: ^/api/.*" \
  "    service: http://127.0.0.1:5001" \
  "  - hostname: {*}" \
  "    path: ^/ws.*" \
  "    service: http://127.0.0.1:8765" \
  "  - service: http://127.0.0.1:8080" > "$CLOUDFLARED_TUNNEL_DIR/config.yml"
cloudflared tunnel --url http://127.0.0.1:8080 --config "$CLOUDFLARED_TUNNEL_DIR/config.yml"
')

echo
echo "Static preview on http://127.0.0.1:8080 (started separately):"
echo "  cd '$FRONTEND' && npx vite preview --port 8080 --host 127.0.0.1"
echo "The public trycloudflare.com URL is printed above. Press Ctrl-C to stop."
wait
