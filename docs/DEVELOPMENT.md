# Development guide

Get from `git clone` to a running dashboard in about five minutes.

## Prerequisites

- Python 3.12+
- Node.js 20+
- A webcam is optional (only for LIVE PROTOTYPE camera feeds)

## 1. Backend

```bash
cd control_centre/backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python server.py
```

What you get:

| Service | Address |
|---|---|
| REST API | http://127.0.0.1:5001 |
| Bus telemetry WebSocket | ws://127.0.0.1:8765 |
| Camera WebSocket | ws://127.0.0.1:8766 |

Defaults: simulation mode, 100-bus Chennai fleet, dev database at
`control_centre/backend/data/control_centre.db`.

## 2. Frontend

```bash
cd control_centre/frontend
npm install
npm run dev     # http://localhost:5173 (proxies /api to :5001)
```

Log in with `admin` / `admin123` (development only). Switch data source between
simulation and live prototype from the UI when you have a webcam.

## 3. Verify

```bash
curl http://127.0.0.1:5001/api/health          # {"status":"ok","simulation":true}
cd control_centre/backend && venv/bin/python -m pytest -q
cd control_centre/frontend && npm test && npm run build
```

## Environment knobs (backend)

| Variable | Default | Meaning |
|---|---|---|
| `FLEETIQ_ENV` | `development` | `production` = auth-required reads, no default passwords |
| `FLEETIQ_SAME_ORIGIN` | `1` | browser access without a CORS allowlist |
| `FLEETIQ_DB` | bundled dev DB | SQLite path (deployments point it at `/var/lib/fleetiq/...`) |
| `FLEETIQ_ADMIN_USER` / `FLEETIQ_ADMIN_PASSWORD` | `admin` / `admin123` | bootstrap admin (production refuses the default) |
| `FLEETIQ_DRIVER_CAMERA_DEVICE` | `0` | `none` disables the driver slot |
| `FLEETIQ_CABIN_CAMERA_DEVICE` | `1` | `none` disables the cabin slot |
| `FLEETIQ_ROAD_CAMERA_DEVICE` | `0` | road test slot |
| `FLEETIQ_CABIN_MODEL_PATH` | unset | Ultralytics model for real person detection |

## Simulated vs live

Everything runs on the simulator until a real bus node streams `hello` /
`bus_state` / `event` / `heartbeat` messages to `ws://…:8765`, or you switch
the UI to LIVE PROTOTYPE for webcam perception. Live data supersedes the
simulated copy per bus; a bus stale for >30 s falls back to simulation.
