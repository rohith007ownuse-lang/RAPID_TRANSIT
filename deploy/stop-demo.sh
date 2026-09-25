#!/usr/bin/env bash
# Stop the tunnel demo started by tunnel-demo.sh — backend, preview, tunnel.
# Killing the cloudflared process takes the public URL down INSTANTLY and
# PERMANENTLY: quick-tunnel URLs are single-use, so the old address can never
# come back. Starting tunnel-demo.sh again mints a brand-new URL.
#
#   ./deploy/stop-demo.sh
#
# Nothing is deleted: the demo database (~/.local/share/fleetiq-demo/, or
# $FLEETIQ_DEMO_DATA) and all users survive a stop/start cycle.
set -uo pipefail

DATA_DIR="${FLEETIQ_DEMO_DATA:-$HOME/.local/share/fleetiq-demo}"
CLOUDFLARED="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"
stopped=0

kill_match() {  # $1 = description, $2... = pkill -f pattern
    local desc="$1"; shift
    if pgrep -f "$1" >/dev/null 2>&1; then
        pkill -f "$1"
        echo "stopped: $desc"
        stopped=1
    else
        echo "not running: $desc"
    fi
}

kill_match "public tunnel (URL is now dead)" "cloudflared tunnel --url"
kill_match "frontend preview (:8080)" "vite preview --port 8080"
kill_match "demo backend (:5001)" "server.py --host 127.0.0.1 --port 5001"

if [ "$stopped" = "1" ]; then
    echo
    echo "Demo is offline. Your data and users are kept in: $DATA_DIR"
    echo "To go live again with a NEW url: FLEETIQ_ADMIN_USER=<user> FLEETIQ_ADMIN_PASSWORD='<password>' ./deploy/tunnel-demo.sh"
else
    echo "Nothing was running."
fi
