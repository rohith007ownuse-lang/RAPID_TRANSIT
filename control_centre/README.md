# Control Centre — Urban Intelligence Dashboard

White-themed, professional operations dashboard for the AI Urban Intelligence Platform.

> **All dashboard data is SIMULATED demo data** until bus nodes stream real data
> over WebSocket (a later phase). Every page shows a `SIMULATION` badge.

## Stack
- **Backend:** Python Flask REST API + in-memory simulation engine + WebSocket
  ingestion server (`backend/`)
- **Frontend:** React 18 + Vite, React Router, Leaflet map, Recharts (`frontend/`)

## Architecture
```
bus_node (laptop/robot bus)  --WebSocket:8765-->  Control Centre backend
  sensors (GPS/IMU/load/mic)                      (websocket_handler.py adapts
  driver + cabin cameras                         payloads into dashboard schema,
  driver FatigueEngine                           writes into shared data store)
  Event Fusion -> structured events                       |
          ^                                               |
          '---------------- REST /api/* <-- Flask:5001 <--'
```

## Multi-camera (Phase 6)
Live prototype mode auto-starts the **driver** and **cabin** cameras as
independent sources (`backend/ai/camera_manager.py`). Each camera has its own
capture thread/state; a camera that cannot open is reported honestly
(`DISCONNECTED` + reason) without affecting the other. Configure via env:

```bash
export FLEETIQ_DRIVER_CAMERA_DEVICE=0   # default "0"
export FLEETIQ_CABIN_CAMERA_DEVICE=1    # default "1"; "none"/"off" = disabled
export FLEETIQ_CAMERA_BUS_ID=PROTO-001  # default "PROTO-001"
venv/bin/python server.py --start-mode live
```

`GET /api/camera/status` reports per-camera `status` (CONNECTED / DISCONNECTED /
DISABLED), real resolution + measured FPS, plus a `cameras` map. Streams:
`GET /api/camera/stream/driver|cabin|road`. Camera controls
(`/api/camera/multi-camera`, `/api/camera/test-mode`, ...) require
authentication. The driver feed continues to drive the DDS engine. The CIS
`cabin_detector.py` remains a placeholder (no fabricated events); the cabin
camera itself now feeds the Phase-7 occupancy intelligence below.

## Cabin & Occupancy Intelligence (Phase 7)
The cabin camera is consumed by a low-rate occupancy engine
(`backend/ai/cabin/occupancy.py`) that turns it into a real FLEET-IQ input:
cabin perception → occupancy estimate → REST telemetry + dashboard.

- `GET /api/cabin/occupancy` (open, read-only) — current cabin snapshot:
  `occupancy_count`, `occupancy_percentage`, `capacity`,
  `crowding_level` (`NORMAL <60 / MODERATE 60–74 / HIGH 75–89 /
  CRITICAL ≥90`), `confidence`, `source`, `estimator`, `system_mode` +
  honesty fields (`real_model_available`, `estimator_in_use`,
  `inference_count`, `inference_fps`).
- **Source labelling**: the default estimator is a development heuristic
  (foreground-density grid proxy) — always reported as
  `estimator="heuristic"`, `estimator_type="development"`, `confidence=null`.
  It is **not** ML. A real Ultralytics person-model engages only when
  `FLEETIQ_CABIN_MODEL_PATH` is set and loadable.
- **Honesty contract**: when the cabin camera is unavailable the payload
  reports `occupancy_count/percentage/crowding_level/confidence` as
  **null — never 0** ("unknown" ≠ "empty"). The engine runs only in live
  mode and drops the bus `cabin_occupancy` field in simulation. Per-tick
  and per-slot isolation mean a cabin camera or estimator failure cannot
  reach the driver camera, the DDS pipeline, or the backend.
- **Config** (env, defaults): `FLEETIQ_CABIN_INFERENCE_INTERVAL_SEC=2.0`,
  `FLEETIQ_CABIN_DEFAULT_CAPACITY=40` (fallback; per-bus
  `occupancy.capacity` wins), `FLEETIQ_CABIN_MODEL_PATH` (unset),
  `FLEETIQ_CABIN_CAMERA_ID=CAM-CAB-001`.
- **Frontend**: `CabinIntelligencePanel` (live camera page) + cabin-card
  occupancy line + a conditional "Cabin Occupancy" column on Load
  Management (shown only when a bus carries `cabin_occupancy`). Unknown is
  displayed as `—`, never as 0.
- **Privacy**: aggregate occupancy only; frames consumed then discarded;
  no raw images/faces stored, no facial recognition, no occupancy persisted.

## Fleet Intelligence Dashboard (Phase 8)
The operator view turns the existing dashboard into a "what needs attention
across my fleet right now" command view. One aggregate endpoint powers it —
pulling `all buses + all events + risk + roads` at once instead of many
round-trips.

- `GET /api/fleet/summary` (open, read-only) — single aggregated snapshot
  computed from the *existing* subsystems (never a parallel model of the
  truth): `fleet_counts` (total/active/normal/warning/critical/offline),
  `fleet` (id lists per tier), `risk` (avg + per-level), `incidents`
  (severity + status counts incl. open/acknowledged/resolved over the
  persistent event log), `driver_safety`, `vehicle_health` (faithful keys
  `NORMAL` / `WARNING` / `INSPECTION REQUIRED` / unknown), `occupancy`
  (camera-based vs simulated split — camera-based only when the cabin
  camera is `CONNECTED`; simulated otherwise; unavailable when offline),
  `load`, `road` (risky routes, zones, active defects, affected buses),
  and `attention[]` — the prioritized alert list the dashboard renders first.
- **Attention prioritization** reuses the existing severity vocabulary
  CRITICAL > HIGH > WARNING > OFFLINE > INFO. Every reason carries its
  source (risk / driver_safety / vehicle_health / load / occupancy /
  cabin_camera / fleet) and per-bus reasons are deduped (≤4). No new alert
  conditions are invented — only intelligence already in the store.
- **Offline** = a live asset (`_live`/`data_source` live) that is not
  connected or whose `last_update` is stale (>30 s). Sim buses are never
  offline. Staleness is reported in seconds, never fabricated.
- **Realtime** stays on the existing polling model (`/api/live/status` in
  modeContext + 4 s summary/buses polls on the dashboard). No new WS system.
- **Frontend**: the Dashboard now renders in priority tiers — Level 1
  "Requires Attention" (worst-first, severity chips with colour + text,
  STALE tags, click → bus details), Incident summary, fleet KPI stat grid
  (Total/Active/Normal/Warning/Critical/Offline/Avg Fleet Risk + hints),
  4 summary cards (Driver Safety, Vehicle Health, Occupancy incl.
  camera-vs-simulated, Load), and Road Intelligence. Loading shows `…`/`—`
  (never fake 0), live/sim labelling comes from the summary itself, and the
  existing FleetMap / call-pin / AlertFeed / siren / Critical Actions
  (backend-guarded) widgets are preserved.
- **Role safety**: dashboards actions stay role-aware (quick nav for all;
  privileged ack/evaluate controls remain backend-guarded as before).

## Run

### 1. Backend
```bash
cd control_centre/backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python server.py            # REST http://127.0.0.1:5001 + WS ws://127.0.0.1:8765
```
`--port <p>` changes REST, `--ws-port <p>` changes WebSocket, `--no-ws` disables it.

### 2. Frontend
```bash
cd control_centre/frontend
npm install
npm run dev                          # http://localhost:5173
```
Vite proxies `/api` to the backend (see `vite.config.js`).

### 3. Bus node (optional — streams simulated live data into the dashboard)
```bash
cd AI_Urban_Intelligence_Platform
python bus_node/main.py --headless --duration 30   # streams to ws://localhost:8765
```

## API endpoints
| Endpoint | Purpose |
|----------|---------|
| `/api/health` | liveness + simulation flag |
| `/api/overview` | summary card numbers |
| `/api/buses` | full fleet state |
| `/api/buses/<id>` | single bus + recent events |
| `/api/buses/<id>/risk` | unified risk assessment |
| `/api/buses/<id>/timeline` | driver fatigue timeline |
| `/api/buses/<id>/eta` | ETA & delay prediction |
| `/api/buses/<id>/demand` | boarding demand forecast |
| `/api/buses/<id>/road-threats` | road threats on current leg |
| `/api/risk` | fleet risk scores |
| `/api/events` | event log (filter by `?status=` / `?type=`) |
| `/api/events/<id>/acknowledge` | acknowledge event (POST) |
| `/api/events/<id>/resolve` | resolve event (POST) |
| `/api/actions` | AI recommended actions |
| `/api/actions/<id>/ack` | acknowledge action (POST) |
| `/api/actions/evaluate` | trigger action evaluation (POST) |
| `/api/health/predictive` | predictive vehicle health |
| `/api/eta` | fleet ETA & delay |
| `/api/demand` | fleet demand forecast |
| `/api/roads/risk` | road risk zones + route index |
| `/api/road-defects` | grouped/persistent road defects |
| `/api/analytics` | chart data |
| `/api/settings` | config assumptions (read/write) |

## WebSocket protocol (bus node -> control centre)
JSON messages on `ws://127.0.0.1:8765`:
| type | payload | effect |
|------|---------|--------|
| `hello` | `{bus_id}` | registers connection |
| `bus_state` | `{bus_id, state}` | upserts bus (adapted to dashboard schema) |
| `event` | `{bus_id, event}` | adds event; ROAD_DEFECT/POTHOLE events are grouped into the persistent road-defect map |
| `heartbeat` | `{bus_id}` | refreshes liveness; buses stale > 30 s revert to simulator control |

A connected (live) bus **supersedes** its simulated copy: the fleet simulator
skips `_live` buses so real-node data is never overwritten.

## Authentication & Authorization (Phase 5)

The backend is the source of truth for identity and role. Passwords are hashed
(`hashlib.pbkdf2_hmac`, SHA-256, 260k iterations, per-user salt) and never
stored or logged in plaintext. Sessions are opaque server-side bearer tokens
(`Authorization: Bearer <token>`) stored in SQLite with a 12-hour expiry.

Roles: `operator` < `supervisor` < `admin`. Privileged backend operations are
independently authorized per request — changing a browser `localStorage` value
cannot grant privileges.

| Auth endpoint | Purpose |
|---------------|---------|
| `POST /api/auth/login` | sign in → `{token, user}` (same 401 for bad user / bad password / inactive) |
| `GET /api/auth/me` | current authenticated user + role |
| `POST /api/auth/logout` | invalidate the token server-side |
| `POST /api/auth/me/password` | change own password (requires current) |
| `GET/POST /api/auth/users` | admin: list / create users |
| `POST /api/auth/users/<id>/role` | admin: change role (guards last active admin) |
| `POST /api/auth/users/<id>/active` | admin: enable/disable (guards last active admin) |
| `POST /api/auth/users/<id>/password` | admin: reset a user's password |

Read-only telemetry stays open. Privileged actions (incident ack/review:
any role; resolve/status: supervisor+; settings: admin) require auth.

### Initial Admin (development)
On first startup the backend idempotently creates an Admin if
`FLEETIQ_ADMIN_USER` (default `admin`) does not exist. **The default password
`admin123` is DEVELOPMENT ONLY** and a warning is printed when it is used.
Override before real deployment:
```bash
export FLEETIQ_ADMIN_USER=admin
export FLEETIQ_ADMIN_PASSWORD=changeMe#
venv/bin/python server.py --start-mode simulation|live
```
Users and event history persist across restarts in the same
`backend/data/control_centre.db`.

## Pages
Dashboard · Live Fleet · Bus Details · Incidents · Road Intelligence ·
Driver Safety · Load Management · Vehicle Health · Analytics · Settings

## Honesty rules
- Simulated values are never presented as real measurements.
- No accuracy/precision/F1/FPS/dataset claims.
- Load/weight values (tare 11 t, GVW 16.2 t, payload limit 6 t) are project
  assumptions until the applicable vehicle category and legal regulation are verified.