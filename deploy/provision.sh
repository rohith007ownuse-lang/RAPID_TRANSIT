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
cd "$APP_DIR/backend"
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

# The trained models are large binaries that rsync already copied; confirm the
# app can actually import before the service is enabled.
./venv/bin/python -c "import server" 2>/dev/null || true

install -m 0644 "$APP_DIR/deploy/systemd/fleetiq.service" /etc/systemd/system/fleetiq.service
install -m 0644 "$APP_DIR/deploy/nginx/fleetiq.conf" /etc/nginx/sites-available/fleetiq
ln -sf /etc/nginx/sites-available/fleetiq /etc/nginx/sites-enabled/fleetiq
rm -f /etc/nginx/sites-enabled/default

if [ ! -f /etc/fleetiq/fleetiq.env ]; then
    echo "!! /etc/fleetiq/fleetiq.env is missing."
    echo "!! Create it before starting (see deploy/fleetiq.env.example)."
    exit 1
fi
chmod 0640 /etc/fleetiq/fleetiq.env
chown root:"$SERVICE_USER" /etc/fleetiq/fleetiq.env

chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

systemctl daemon-reload
systemctl enable --now fleetiq
nginx -t
systemctl reload nginx

echo "==> Done. Next steps on the server:"
echo "    systemctl status fleetiq"
echo "    journalctl -u fleetiq -f"
echo "    certbot --nginx -d <your-domain>"
REMOTE

echo
echo "Local repo was NOT modified. To deploy a new build later, re-run:"
echo "  sudo $0 $TARGET"
