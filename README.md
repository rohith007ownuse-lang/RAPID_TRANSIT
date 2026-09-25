# FLEET-IQ — AI-Powered Mobile Urban Intelligence Platform

[![CI](https://github.com/rohith007ownuse-lang/fleet-iq/actions/workflows/ci.yml/badge.svg)](https://github.com/rohith007ownuse-lang/fleet-iq/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](control_centre/backend/requirements.txt)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](control_centre/frontend/package.json)

Convert public-transport buses into distributed mobile sensing and intelligence nodes.

Each bus continuously collects driver safety, cabin safety, road conditions, crash /
impact events, emergency situations, vehicle load, vehicle health, and fleet location,
then sends structured events to a centralized Control Centre / Urban Intelligence Dashboard.

> **Research & demonstration prototype.** This is NOT an automotive-certified safety system.
> Every value on screen carries a source label — `SIMULATION`, `MODEL`, `HEURISTIC`, or `LIVE`
> — and the platform never presents estimates as measurements. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

---

## What it does

| Capability | Where |
|---|---|
| Operator dashboard: fleet KPIs, incidents, attention queue, maps | `control_centre/frontend` (React + Vite + Leaflet) |
| REST API + real-time bus ingest over WebSockets | `control_centre/backend` (Flask) |
| Driver drowsiness (EAR/MAR/head-pose, MediaPipe) | `control_centre/backend/ai/driver` |
| Cabin fire & smoke detection (trained YOLOv8n, D-Fire) | `control_centre/backend/ai/cabin` |
| Cabin occupancy intelligence (heuristic + optional real model) | `control_centre/backend/ai/cabin/occupancy.py` |
| Pothole / road-defect detection (trained YOLOv8n) | `control_centre/backend/ai/road` |
| Traffic detection + ByteTrack counting, congestion heat map | `control_centre/backend/traffic_engine.py`, `congestion_heatmap.py` |
| Congestion hotspots → red map alert at **8+ buses inside 50 m** | `control_centre/backend/traffic_engine.py` |
| Risk engine, AI actions, predictive health, ETA, demand, road risk | `control_centre/backend/*.py` |
| Incident correlation, assignment & lifecycle | `control_centre/backend/incident_intelligence.py` |
| Historical & operational analytics | `control_centre/backend/analytics_intelligence.py` |
| System health, degraded modes, resilience | `control_centre/backend/system_health.py` |
| Bus-side node: sensors, event fusion, alerts | `bus_node/` |
| One-command demo deployment (server or tunnel) | `deploy/` |

## Status legend

| Label | Meaning |
|---|---|
| **IMPLEMENTED** | Functionality currently working. |
| **PROTOTYPE** | Working in simulation/demo only; real hardware pending. |
| **PLANNED** | Architecture reserved; not yet functional. |

| Module | Status |
|---|---|
| Driver monitoring (EAR/MAR/head-pose/drowsiness) | **IMPLEMENTED** |
| Calibration | **IMPLEMENTED** |
| Audio alert tones | **IMPLEMENTED** |
| Event logging + SQLite persistence | **IMPLEMENTED** |
| Control Centre web UI (map + live fleet + operator console) | **IMPLEMENTED** (simulated data, clearly labeled) |
| 100-bus Chennai MTC fleet simulator | **IMPLEMENTED** (simulated data) |
| Per-bus ticket machine counters (tickets sold, fare collected ₹) | **IMPLEMENTED** (simulated) |
| Operator intercom (call driver / transcript) | **IMPLEMENTED** (simulated) |
| Risk engine · AI actions · predictive health · ETA · demand · road risk | **IMPLEMENTED** (simulated) |
| Traffic hotspots (8+ buses in 50 m for >60 s → red dot) | **IMPLEMENTED** (simulated) |
| Camera manager: driver + cabin live, road test slot | **IMPLEMENTED** (DRIVER + CABIN live; ROAD planned) |
| LIVE PROTOTYPE mode (webcam AI: driver DDS / pothole / cabin) | **IMPLEMENTED** (live webcam; sim/live switchable in UI) |
| Cabin fire/smoke detection (trained D-Fire model) | **IMPLEMENTED** (live webcam) |
| Sensor interfaces (GPS / IMU / load / mic) | **IMPLEMENTED** (simulation only, clearly labeled) |
| Public deployment (single-host VPS or tunnel) | **IMPLEMENTED** — see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |

## Repository layout

```
fleet-iq/
├── control_centre/
│   ├── backend/        # Flask REST API, WebSocket ingest, AI engines, simulator
│   └── frontend/       # React operator console (Vite)
├── bus_node/           # On-bus node: sensors, detectors, event fusion, alerts
├── deploy/             # Production deployment: systemd, nginx, VPS provisioner, tunnel demo
├── docs/               # Architecture, API, deployment, data-source honesty, dev guide
├── scripts/            # GIS / facility-pin helpers
├── arduino/            # Drowsiness-guard car prototype firmware
├── config/             # system_config.json
├── assets/ branding/   # Images and brand material
└── data/               # Alert tones
```

## Quickstart

Prerequisites: Python 3.12+, Node 20+.

```bash
# Backend — REST on :5001, bus WebSocket on :8765, camera WebSocket on :8766
cd control_centre/backend
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python server.py            # simulation mode by default

# Frontend — operator console (proxies /api to the backend)
cd ../frontend
npm install
npm run dev                          # http://localhost:5173
```

Open http://localhost:5173, log in (`admin` / `admin123` — development only,
change it before any real use), and explore the dashboard. Every page shows a
`SIMULATION` badge until real bus nodes connect. Full developer guide:
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Put it on the internet

Free options, no card drama — permanent server or an instant tunnel URL:

```bash
# A) Real server (permanent URL): needs a free VPS + SSH access
sudo ./deploy/provision.sh ubuntu@<server-ip>

# B) Instant demo URL from this machine (no server, no account)
FLEETIQ_ADMIN_PASSWORD='<strong-password>' ./deploy/tunnel-demo.sh
```

Details, trade-offs and judge-demo checklist: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## API

30+ endpoints under `/api/*` plus two WebSocket channels. Overview and the
auth model: [docs/API.md](docs/API.md).

## Testing

```bash
cd control_centre/backend && venv/bin/python -m pytest -q   # 800+ tests, isolated per-test DBs
cd control_centre/frontend && npm test && npm run build
```

CI runs both on every push and pull request.

## Security

Production mode (`FLEETIQ_ENV=production`) requires authentication for reads,
refuses default passwords at startup, and gates every privileged action
backend-side (the frontend role is display-only). See [SECURITY.md](SECURITY.md).

## Contributing

Issues and pull requests are welcome — start with [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) — free for anyone to use, including judges and evaluators.

## Acknowledgements

- Chennai MTC network data (GTFS) for routes and stops
- [D-Fire dataset](https://github.com/rabahdev) for the cabin fire/smoke model
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) for detection backbones
- [MediaPipe](https://developers.google.com/mediapipe) for driver face mesh
