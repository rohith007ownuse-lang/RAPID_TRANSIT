# Architecture

```
                        ┌────────────────────────────────────────────┐
                        │        CONTROL CENTRE (this repo)           │
bus_node ──WS:8765──▶  │  server.py (Flask :5001)                    │
  sensors (GPS/IMU/    │    ├─ AI engines (driver / cabin / road)    │
  load/mic/driver cam) │    ├─ risk · ETA · demand · road-risk       │
  driver FatigueEngine │    ├─ incidents · analytics · actions       │
  event fusion         │    ├─ traffic hotspots · heat map           │
                       │    └─ shared data_store ──▶ SQLite          │
                       │              │                              │
                       │              ▼                              │
                       │   React console (Vite) ◀── /api/* ──┘       │
                       └────────────────────────────────────────────┘
```

## Control centre backend (`control_centre/backend/`)

`server.py` is the process: Flask REST on `:5001`, bus-ingest WebSocket on
`:8765`, camera WebSocket on `:8766`. Pure-logic modules sit behind it and
stay Flask-free so they can be unit-tested in isolation:

- `data_store.py` — in-memory fleet state + mode (simulation/live)
- `persistence.py` — SQLite: event history, users, sessions; rehydrated at boot
- `auth.py` — PBKDF2 passwords, opaque session tokens, role checks
- `simulator.py` — 100-bus Chennai MTC fleet (routes, fatigue, boarding, health)
- `traffic_engine.py` — congestion hotspots: 8+ buses inside 50 m for >60 s
- `congestion_heatmap.py` — positional intensity grid for the map overlay
- `incident_intelligence.py` — event correlation → incidents → assignment
- `analytics_intelligence.py` — historical/operational analytics from records
- `websocket_hardening.py` — reconnection, dedup, coalescing, resync
- `system_health.py` — subsystem health + freshness, degraded modes
- `risk_engine.py`, `eta.py`, `demand.py`, `road_risk.py`,
  `predictive_health.py`, `recommendations.py`, `fleet_summary.py` — the
  intelligence layer; each exposes pure functions the API projects
- `ai/driver/`, `ai/cabin/`, `ai/road/` — perception (MediaPipe, YOLOv8)

## Frontend (`control_centre/frontend/`)

React + Vite + Leaflet operator console. `src/api.js` centralises all REST
calls; `src/websocket.js` resolves the socket URL (`VITE_WS_URL` →
`VITE_WS_PATH` → dev ports) so the bundle works behind dev proxy, nginx, and
the tunnel without changes. Route guard sends unauthenticated users to
`/login`; the backend independently authorises every request.

## Bus node (`bus_node/`)

On-vehicle software: sensor interfaces, detectors, event fusion, and the
`hello` / `bus_state` / `event` / `heartbeat` protocol the backend ingests.
Not needed to run the control centre — the simulator stands in.

## Deployment (`deploy/`)

Single-host model: systemd runs the backend, nginx serves the SPA and proxies
`/api`, `/ws`, `/ws/camera` on one origin. SQLite lives at
`/var/lib/fleetiq/control_centre.db`. See [DEPLOYMENT.md](DEPLOYMENT.md).
