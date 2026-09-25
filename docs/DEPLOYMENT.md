# Deployment

Two supported ways to put the control centre on the internet. Both serve the
SPA, the REST API, and both WebSockets on **one origin**, so judges open a
single URL and everything works.

## Option A — real server (permanent URL, recommended for judging)

Any Ubuntu 22.04+ box with SSH. Free tier that fits: Oracle Cloud Always Free
(ARM) or GCP e2-micro.

```bash
# from this repo, on your own machine:
sudo ./deploy/provision.sh ubuntu@<server-ip>
```

The script installs nginx/Python/Node, syncs the app to `/opt/fleetiq`, builds
the frontend with same-origin socket paths, installs a systemd unit, validates
nginx, and health-checks the API. If `/etc/fleetiq/fleetiq.env` does not exist
yet, it seeds one from the example and stops so you can set the password:

```bash
# on the server:
sudo nano /etc/fleetiq/fleetiq.env   # set FLEETIQ_ADMIN_PASSWORD
sudo ./deploy/provision.sh ubuntu@<server-ip>   # re-run to finish
```

What runs where:

| Piece | Location |
|---|---|
| App code | `/opt/fleetiq` |
| systemd service | `fleetiq` (`systemctl status fleetiq`, logs via `journalctl -u fleetiq -f`) |
| SQLite | `/var/lib/fleetiq/control_centre.db` (survives redeploys and restarts) |
| nginx | serves the SPA, proxies `/api`, `/ws`, `/ws/camera` on port 80 |

With a domain, add HTTPS:

```bash
sudo certbot --nginx -d demo.example.com
```

Without a domain the site works on `http://<server-ip>/`. The backend runs in
**simulation mode**: cameras/ML stay on your local machine (a cloud box has no
cameras), and every page shows its `SIMULATION` badge.

## Option B — instant tunnel URL (no server, no account)

```bash
FLEETIQ_ADMIN_PASSWORD='<strong-password>' ./deploy/tunnel-demo.sh
```

Starts the backend (isolated demo database in `~/.local/share/fleetiq-demo/`),
serves the production build with same-origin proxies, and opens a Cloudflare
quick tunnel. The public `https://….trycloudflare.com` URL is printed in the
log. Stops cleanly on Ctrl-C.

Limits: the URL changes every run, and this machine must stay awake and online
for the whole demo. Use it when a server is not ready yet.

## Judge-demo checklist

1. Set a strong `FLEETIQ_ADMIN_PASSWORD`.
2. Create a separate `operator` account (Users page) for the judges — never
   hand out `admin`.
3. Confirm the `SIMULATION` badge is visible — it is honest and deliberate.
4. Open the URL on your own phone once and walk one full flow
   (dashboard → fleet → bus detail → incidents).
5. Keep laptop plugged in, sleep disabled, if you are on Option B.

## Watching access and killing the URL (tunnel demo)

**Who opened it:** every login attempt is recorded with time, username,
success/failure, IP and browser. As admin:

```bash
curl -s -H "Authorization: Bearer <your-token>" https://<your-url>/api/auth/access \
  | python3 -m json.tool
```

`log` is the newest-first attempt history; `active_sessions` is who holds a
live login right now and where they logged in from.

**Stop it any time:** `./deploy/stop-demo.sh` kills the tunnel, the preview
and the backend. The public URL dies instantly and permanently — quick-tunnel
addresses are single-use and can never come back. Nothing is deleted: users
and the demo database survive, and re-running `tunnel-demo.sh` mints a brand-
new URL.
