#!/usr/bin/env bash
# Provision a fresh Ubuntu server for the FLEET-IQ Control Centre.
#
#   ./deploy/provision.sh ubuntu@<server-ip> [branch]
#
# No sudo needed on YOUR machine — it SSHes in as ubuntu and uses sudo on the
# server. The app is cloned from the public GitHub repo, so the server needs
# no credentials and your laptop never uploads anything.
#
# First run seeds /etc/fleetiq/fleetiq.env from the example and STOPS so you
# can set FLEETIQ_ADMIN_PASSWORD; re-run to finish. Re-running later pulls the
# latest branch and redeploys (database in /var/lib/fleetiq is untouched).
set -euo pipefail

REPO_URL="${FLEETIQ_REPO_URL:-https://github.com/rohith007ownuse-lang/fleet-iq.git}"
APP_DIR=/opt/fleetiq
DATA_DIR=/var/lib/fleetiq
SERVICE_USER=fleetiq

if [ $# -lt 1 ]; then
    echo "usage: $0 <ssh-user@host> [branch]   # e.g. ubuntu@203.0.113.10" >&2
    exit 2
fi
TARGET="$1"
BRANCH="${2:-main}"

ssh -o StrictHostKeyChecking=accept-new "$TARGET" bash -s -- "$REPO_URL" "$BRANCH" "$APP_DIR" "$DATA_DIR" "$SERVICE_USER" <<'REMOTE'
set -euo pipefail
REPO_URL="$1"; BRANCH="$2"; APP_DIR="$3"; DATA_DIR="$4"; SERVICE_USER="$5"

export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq nginx python3 python3-venv git curl ca-certificates

if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
    sudo apt-get install -y -qq nodejs
fi

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    sudo useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
sudo mkdir -p "$DATA_DIR"
sudo chown "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"

echo "==> Fetching application into $APP_DIR ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
    sudo git -C "$APP_DIR" fetch -q origin
    sudo git -C "$APP_DIR" checkout -q "$BRANCH"
    sudo git -C "$APP_DIR" pull -q --ff-only origin "$BRANCH"
else
    sudo git clone -q --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

echo "==> Building frontend (same-origin WebSocket paths)"
sudo -u "$SERVICE_USER" bash -lc "cd '$APP_DIR/control_centre/frontend' && npm ci --no-audit --no-fund && VITE_WS_PATH=/ws npm run build"

echo "==> Installing backend dependencies (server runtime only)"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/control_centre/backend/requirements-server.txt"

# Confirm the app actually imports before the service is enabled.
(cd "$APP_DIR/control_centre/backend" && sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/python" -c "import server") \
    || { echo "Backend failed to import — check the logs above." >&2; exit 1; }

sudo install -m 0644 "$APP_DIR/deploy/systemd/fleetiq.service" /etc/systemd/system/fleetiq.service
sudo install -m 0644 "$APP_DIR/deploy/nginx/fleetiq.conf" /etc/nginx/sites-available/fleetiq
sudo ln -sf /etc/nginx/sites-available/fleetiq /etc/nginx/sites-enabled/fleetiq
sudo rm -f /etc/nginx/sites-enabled/default

sudo mkdir -p /etc/fleetiq
if [ ! -f /etc/fleetiq/fleetiq.env ]; then
    sudo install -m 0640 -o root -g "$SERVICE_USER" "$APP_DIR/deploy/fleetiq.env.example" /etc/fleetiq/fleetiq.env
    echo "!! Created /etc/fleetiq/fleetiq.env from the example."
    echo "!! Set FLEETIQ_ADMIN_PASSWORD in it, then re-run this script."
    exit 1
fi
sudo chmod 0640 /etc/fleetiq/fleetiq.env
sudo chown root:"$SERVICE_USER" /etc/fleetiq/fleetiq.env

# Validate nginx before touching the running service, so a bad config never
# takes the site down.
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now fleetiq
sudo systemctl reload nginx

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
echo "  $0 $TARGET $BRANCH"
