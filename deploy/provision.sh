#!/usr/bin/env bash
# Provision a fresh Ubuntu/Debian server for the FLEET-IQ Control Centre.
#
#   sudo ./deploy/provision.sh <ssh-user@host>
#
# Installs nginx, Python, Node, creates the fleetiq user, installs the app to
# /opt/fleetiq, builds the frontend with same-origin WebSocket paths, installs
# the systemd unit, and leaves HTTPS to `certbot --nginx`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR=/opt/fleetiq
DATA_DIR=/var/lib/fleetiq
SERVICE_USER=fleetiq

if [ $# -lt 1 ]; then
    echo "usage: sudo $0 <ssh-user@host>   # e.g. ubuntu@203.0.113.10" >&2
    exit 2
fi
TARGET="$1"

ssh "$TARGET" bash -s -- "$REPO_ROOT" "$APP_DIR" "$DATA_DIR" "$SERVICE_USER" <<'REMOTE'
set -euo pipefail
REPO_ROOT="$1"; APP_DIR="$2"; DATA_DIR="$3"; SERVICE_USER="$4"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx python3 python3-venv python3-pip curl rsync

if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
fi

id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$DATA_DIR"
chown "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"

echo "==> Syncing application to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete \
    --exclude '.git' --exclude 'graphify-out' --exclude 'venv' --exclude 'node_modules' \
    --exclude 'dist' --exclude '__pycache__' --exclude '*.db' --exclude '*.db-wal' --exclude '*.db-shm' \
    --exclude 'brag-output-*' --exclude 'generated_audio' --exclude '.env' \
    "$REPO_ROOT"/ "$APP_DIR"/

echo "==> Building frontend (same-origin WebSocket paths)"
cd "$APP_DIR/control_centre/frontend"
npm ci --no-audit --no-fund
VITE_WS_PATH=/ws npm run build

echo "==> Installing backend dependencies"
# The venv lives at the app root (the systemd unit points at it) and the
# backend package keeps its repo-relative layout under control_centre/.
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/control_centre/backend/requirements.txt"

# The trained models are large binaries that rsync already copied; confirm the
# app can actually import before the service is enabled.
(cd "$APP_DIR/control_centre/backend" && "$APP_DIR/venv/bin/python" -c "import server") \
    || { echo "Backend failed to import — check requirements and model files." >&2; exit 1; }

install -m 0644 "$APP_DIR/deploy/systemd/fleetiq.service" /etc/systemd/system/fleetiq.service
install -m 0644 "$APP_DIR/deploy/nginx/fleetiq.conf" /etc/nginx/sites-available/fleetiq
ln -sf /etc/nginx/sites-available/fleetiq /etc/nginx/sites-enabled/fleetiq
rm -f /etc/nginx/sites-enabled/default

mkdir -p /etc/fleetiq
if [ ! -f /etc/fleetiq/fleetiq.env ]; then
    install -m 0640 "$APP_DIR/deploy/fleetiq.env.example" /etc/fleetiq/fleetiq.env
    echo "!! Created /etc/fleetiq/fleetiq.env from the example."
    echo "!! Set FLEETIQ_ADMIN_PASSWORD in it, then re-run this script."
    exit 1
fi
chmod 0640 /etc/fleetiq/fleetiq.env
chown root:"$SERVICE_USER" /etc/fleetiq/fleetiq.env

chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

# Validate nginx before touching the running service, so a bad config never
# takes the site down.
nginx -t
systemctl daemon-reload
systemctl enable --now fleetiq
systemctl reload nginx

sleep 3
if ! curl -fsS --max-time 5 http://127.0.0.1:5001/api/health >/dev/null; then
    echo "!! The service started but /api/health is not answering." >&2
    echo "!! Check: journalctl -u fleetiq -n 50" >&2
    exit 1
fi

echo "==> Done. The control centre is live on http://$(hostname -I | awk '{print $1}')/"
echo "==> Next steps on the server:"
echo "    systemctl status fleetiq"
echo "    journalctl -u fleetiq -f"
echo "    certbot --nginx -d <your-domain>    # only if you have a domain"
REMOTE

echo
echo "Local repo was NOT modified. To deploy a new build later, re-run:"
echo "  sudo $0 $TARGET"
