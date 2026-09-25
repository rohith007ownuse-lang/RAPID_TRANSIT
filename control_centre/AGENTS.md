# Rapid Transit Control Centre - Agent Instructions

## Project Overview
White-themed React/Flask dashboard for Rapid Transit.
SIMULATED demo data until bus nodes connect via WebSocket.
100-bus fleet with 10 MTC routes (Chennai), real-time risk, fatigue, ETA, demand, road risk.

## Commands (run from `control_centre/`)
```bash
# Backend
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python server.py            # REST http://127.0.0.1:5001 + WS ws://127.0.0.1:8765

# Frontend
cd frontend
npm install
npm run dev                          # http://localhost:5173 (proxies /api to :5001)
npm run build                        # production build
```

## Architecture
```
bus_node (sim or real) --WS:8765--> Control Centre backend (Flask:5001)
    sensors (GPS/IMU/load/mic/driver cam)          |
    driver FatigueEngine                           v
    Event Fusion -> structured events        shared data_store (buses, events, defects)
                                                      |
                    <---- REST /api/* <---- Flask + React (Vite:5173)
```
All data is **SIMULATED** (SimBadge on every page) until real bus nodes stream data.

## Pages (11 total)
| Route | Page | Key Features |
|-------|------|--------------|
| `/` | Dashboard | Requires-Attention (prioritized), incident summary, fleet KPIs, safety/health/occupancy/load cards, road intel, map, critical actions (Phase 8) |
| `/fleet` | Live Fleet | All buses grid, click→details |
| `/fleet/:busId` | Bus Details | Risk, timeline, ETA, demand, road threats, cameras, events |
| `/driver-safety` | Driver Safety | Per-bus EAR/MAR/pitch gauges, drowsiness history |
| `/load-management` | Load Management | GVW/payload table with status badges |
| `/incidents` | Incidents | Event log with review/ack/resolve |
| `/roads` | Road Intelligence | Defects map, risk zones, route risk index |
| `/routes` | Route Map | All MTC GTFS routes; searchable list, click route (list or map) to highlight it + its stops |
| `/health` | Vehicle Health | Anomaly + predictive degradation (tyre/vibration/energy) |
| `/analytics` | Analytics | Boarding, potholes, events, severity, vehicle mix |
| `/settings` | Settings | Sim toggle, city bounds, bus weights, detection thresholds |

## API Endpoints (30+)
- **Core**: `/api/health`, `/api/overview`, `/api/buses`, `/api/buses/<id>`, `/api/events`, `/api/road-defects`, `/api/analytics`, `/api/settings`
- **Risk**: `/api/risk`, `/api/buses/<id>/risk`
- **Actions**: `/api/actions`, `/api/actions/<id>/ack`, `/api/actions/evaluate`
- **Fatigue**: `/api/buses/<id>/timeline`
- **ETA**: `/api/eta`, `/api/buses/<id>/eta`
- **Demand**: `/api/demand`, `/api/buses/<id>/demand`
- **Road Risk**: `/api/roads/risk`, `/api/buses/<id>/road-threats`
- **GTFS**: `/api/gtfs/routes/polylines?q=&limit=` — bulk polylines for the Route Map page
- **Predictive**: `/api/health/predictive`

## WebSocket (bus_node → control centre)
`ws://127.0.0.1:8765` JSON messages:
- `hello` {bus_id} — register
- `bus_state` {bus_id, state} — upsert (adapted to dashboard schema)
- `event` {bus_id, event} — add event; ROAD_DEFECT grouped into defect map
- `heartbeat` {bus_id} — liveness; stale > 30s reverts to simulator

Live bus (`_live: true`) supersedes simulator copy.

## Key Files
- `backend/server.py` — Flask REST API
- `backend/auth.py` — authentication + authorization (Phase 5)
- `backend/ai/camera_manager.py` — multi-camera engine (Phase 6): per-slot
  `CameraSource` (driver + cabin) with independent threads, honest status
- `backend/ai/cabin/occupancy.py` — cabin occupancy intelligence (Phase 7):
  heuristic estimator + real-model slot + occupancy engine consuming the
  cabin camera at reduced cadence
- `backend/data_store.py` — in-memory store + mode_state
- `backend/fleet_summary.py` — pure fleet aggregation (Phase 8) building the
  `/api/fleet/summary` operator snapshot from existing subsystems
- `backend/persistence.py` — SQLite persistence (event history + users + sessions; reload on startup)
- `backend/simulator.py` — 100-bus fleet sim (routes, fatigue, boarding, health, potholes)
- `backend/risk_engine.py` — 6-segment risk (driver/vehicle/load/speed/occupancy/history)
- `backend/predictive_health.py` — tyre/vibration/braking/energy degradation + RUL
- `backend/eta.py` — dwell model + delay bands
- `backend/demand.py` — time-of-day + friction demand forecast
- `backend/road_risk.py` — defect clustering → risk zones + route index + leg threats
- `backend/recommendations.py` — rule-based AI actions with ack/escalation
- `frontend/src/pages/*.jsx` — page components (Login, Users, plus 11 operation pages)
- `frontend/src/lib/authContext.jsx` — frontend auth state (uses backend-provided role)
- `frontend/src/components/` — Layout, UI, FleetMap, CameraFeed (per-camera status strip), AlertFeed, etc.

## Authentication & Authorization (Phase 5)
Real backend security boundary — the frontend role is **display only**; the
backend independently authorizes every privileged request.

- **Passwords**: hashed with `hashlib.pbkdf2_hmac` (SHA-256, 260k iterations,
  per-user salt). Stored as `pbkdf2_sha256$<iter>$<salt>$<hash>`. Never
  plaintext, never logged.
- **Sessions**: opaque bearer tokens (`Authorization: Bearer <token>`) stored
  server-side in SQLite with expiry (default 12h, `FLEETIQ_SESSION_TTL_HOURS`).
  Logout deletes the token server-side. Inactive users are dropped.
- **Roles**: `operator` < `supervisor` < `admin`. Backend-enforced per endpoint.
- **Endpoints**:
  - Auth: `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`,
    `POST /api/auth/me/password`
  - Admin user mgmt: `GET/POST /api/auth/users`,
    `POST /api/auth/users/<id>/role|active|password` (guards the last active admin)
  - Privileged (auth required): incident `acknowledge/review` (any role),
    `resolve/status` (supervisor+), mode switch (any role), DDS controls (any
    role), camera controls (any role), `actions/evaluate/ack` (any role),
    `actions/resolve` (supervisor+), `settings` (admin+)
  - Read-only telemetry (overview/buses/events/etc.) stays open for the dashboard.
- **Frontend**: login screen, route guard (unauthenticated → `/login`), role
  gating for Settings/Users screens. Incidents page role comes from the backend
  user, NOT from localStorage (the old `aiuc_operator_role` spoofing vector is
  removed). 401 responses tear down the local session.

### Development bootstrap (admin)
On first backend start, if no `FLEETIQ_ADMIN_USER` exists, an Admin is created
idempotently. **DEVELOPMENT ONLY** default password `admin123` — override and
change it before real use:
```bash
export FLEETIQ_ADMIN_USER=admin          # default "admin"
export FLEETIQ_ADMIN_PASSWORD=JudgeMe9   # default "admin123" (dev only)
venv/bin/python server.py --start-mode simulation|live
```
The server prints a warning when the default password is in use; it never
prints the password itself.

## Multi-Camera Architecture (Phase 6)
Live mode auto-starts **two independent cameras** (driver + cabin); the road
slot remains a single-camera test target only (no cabin/occupancy AI yet).

- **Independence**: each camera is a `CameraSource` with its own capture
  thread, state, measured FPS and error channel in
  `backend/ai/camera_manager.py`. One camera failing to open or dying at
  runtime never stops the other. A camera that cannot open is reported
  honestly (`DISCONNECTED` + reason) — no synthetic frames, no fabricated
  resolution/FPS.
- **Config** (env, defaults shown): `FLEETIQ_DRIVER_CAMERA_DEVICE=0`,
  `FLEETIQ_CABIN_CAMERA_DEVICE=1` (set `none`/`off` to disable the slot →
  status `DISABLED`), `FLEETIQ_ROAD_CAMERA_DEVICE=0`,
  `FLEETIQ_CAMERA_BUS_ID=PROTO-001`.
- **Status**: `GET /api/camera/status` returns backwards-compatible `slots`
  (with new `status/camera_id/enabled/last_frame_time/error` fields) plus a
  `cameras` map. Legacy fields (`test_mode`, `test_slot`, `available_cameras`,
  `_cap/_frame/_annotated_frame`, single-camera test mode) are preserved.
- **Controls (auth required, any role)**: `POST /api/camera/test-mode`,
  `/api/camera/multi-camera`, `/api/camera/start`, `/api/camera/stop`.
- **Streams**: `GET /api/camera/stream/<slot>` serves each camera's own
  annotated frame; absent cameras return a null `frame` honestly.
- The driver camera continues to feed DDS; cabin occupancy AI (Phase 7) is
  covered by `ai/cabin/occupancy.py` below; the CIS `cabin_detector.py`
  remains a placeholder that never fabricates events.

## Cabin & Occupancy Intelligence (Phase 7)
Live mode's cabin camera is turned into a real occupancy-intelligence
foundation: cabin perception → occupancy estimate → REST telemetry +
dashboard. It is an honest foundation — no fake passengers, no fake
confidence, no implied production AI.

- **Data model** (bus field `cabin_occupancy` + `GET /api/cabin/occupancy`,
  open, read-only): `bus_id`, `camera_id`, `timestamp`, `status`
  (`CONNECTED`/`DISCONNECTED`/`DISABLED`/`ERROR`/`UNAVAILABLE`),
  `occupancy_count`, `occupancy_percentage`, `capacity`,
  `crowding_level`, `confidence`, `source`, `estimator`, plus
  `real_model_available`, `estimator_in_use`, `inference_count`,
  `inference_fps`, `system_mode`, `privacy`.
- **Capacity source**: per-bus `occupancy.capacity` wins
  (`FLEETIQ_CABIN_DEFAULT_CAPACITY` default `40` is a documented fallback,
  never claimed as real). Percentage clamps to 100.
- **Crowding mapping** (aligned with risk-engine thresholds — risk treats
  ≥75% as high, ≥90% as critical): `NORMAL <60`, `MODERATE 60–74`,
  `HIGH 75–89`, `CRITICAL ≥90`. This is the cabin-intelligence vocabulary;
  legacy simulated `occupancy.crowd` labels are untouched.
- **Estimators**: `CabinHeuristicEstimator` (default) is an 8×6 foreground-
  density grid proxy over the frame — label is always
  `estimator="heuristic"`, `estimator_type="development"`, `confidence=None`.
  `CabinMLPersonDetector` engages only when `FLEETIQ_CABIN_MODEL_PATH` points
  to a loadable Ultralytics model (COCO class 0 = person); otherwise reported
  honestly as `real_model_available=false`. Nothing is downloaded or invented.
- **Engine**: daemon loop ticks at `FLEETIQ_CABIN_INFERENCE_INTERVAL_SEC`
  (default `2.0`) — the cabin infer cadence is deliberate and far below
  camera FPS (15.2 fps driver / camera actual). Each tick consumes the
  cabin source's latest frame via `camera_manager.get_latest_frame(slot)`
  (no extra capture thread); sub-second estimator cost (≈0.35 ms/frame
  synthetic benchmark) plus a 2 s schedule → negligible CPU.
  `inference_fps` is measured over successful inferences only and is
  `null` when none happened (never a bogus tick-rate artifact).
- **Honesty rules**: disconnected/disabled/error → `occupancy_count`/
  `percentage`/`crowding_level`/`confidence` are **null, never 0**;
  "unknown" is not "empty bus". Engine runs only in live mode; in
  simulation it clears its snapshot AND removes the `cabin_occupancy` bus
  field. Failure in the estimator or a camera cannot reach the backend
  (per-tick isolation) or the driver camera (per-slot isolation).
  Never label the heuristic as ML/AI-with-confidence; never green-light
  safety or dispatch decisions on the heuristic.
- **Config** (env): `FLEETIQ_CABIN_INFERENCE_INTERVAL_SEC=2.0`,
  `FLEETIQ_CABIN_DEFAULT_CAPACITY=40`, `FLEETIQ_CABIN_MODEL_PATH` (unset),
  `FLEETIQ_CAMERA_BUS_ID=PROTO-001`, `FLEETIQ_CABIN_CAMERA_ID=CAM-CAB-001`.
- **Frontend**: `CabinIntelligencePanel` (live camera page) + cabin-card
  occupancy line + Load Management "Cabin Occupancy" column (column shown
  only when a bus carries `cabin_occupancy`). `—` means unknown — nothing
  ever shows 0 for unknown.
- **Privacy**: aggregate occupancy only; frames consumed then discarded;
  no raw images/faces stored; no facial recognition; snapshots are never
  persisted (the events table stores neither images nor occupancy).

## Fleet Intelligence Dashboard (Phase 8)
The operator dashboard becomes a "what is happening across my fleet right
now, what needs attention" command view. A pure aggregator
(`backend/fleet_summary.py`, no Flask imports) builds ONE aggregate snapshot
from the *existing* subsystems — it is a projection, never a parallel model
of the truth.

- `GET /api/fleet/summary` (open, read-only; lazily imported in `server.py`).
  Payload: `fleet_counts` (total/active/normal/warning/critical/offline),
  `fleet` (bus-id lists per tier), `risk` (avg + by_level from
  `risk_engine.fleet_risk`), `incidents` (severity/status counts over the
  persistent event log — same page cap as `/api/events`), `driver_safety`,
  `vehicle_health` (faithful keys NORMAL / WARNING / INSPECTION REQUIRED /
  unknown), `occupancy` (camera-based vs simulated; camera-based only when
  `cabin_occupancy.status == CONNECTED`; offline → unavailable), `load`,
  `road` (`get_zones()`/`get_route_risk_index()`/`get_road_defects()` +
  affected buses via `route_code`), `attention[]` (prioritized), plus
  `mode`/`simulation`/`live_prototype_connected`/`connected_nodes`/
  `generated_at`.
- Attention severity vocabulary REUSED: CRITICAL > HIGH > WARNING > OFFLINE
  > INFO (same order as `risk_engine.level_for_score`). HIGH → fleet
  "warning" tier, CRITICAL → "critical", OFFLINE → "offline" category.
  Each reason carries its source (risk / driver_safety / vehicle_health /
  load / occupancy / cabin_camera / fleet); per-bus reasons deduped to ≤4.
  Never invent conditions — only intelligence already present in the store.
- Offline = live asset (`_live`/`live`/`data_source=="live"`) that is not
  connected or stale (>30 s, `last_update`). Sim buses are never offline.
  `staleness_seconds` reported. (Known pre-existing quirk: switching live →
  simulation leaves the live PROTO-001 bus in the store — shown in totals
  until a process restart, which clears it.)
- Realtime is the existing polling model (modeContext `/api/live/status`
  3 s; Dashboard 4 s `fleetSummary` + 4 s `buses`). No new WS system.
- Frontend `Dashboard.jsx`: priority tiers (Level 1 Requires Attention →
  Level 5 low-level details), Severity chips coloured + worded (never
  colour-only), IncidentSummary (severity + Open/Ack/Resolved), KPI stat
  grid, 4 summary cards, Road Intelligence card, preserved FleetMap /
  call-pin / AlertFeed / siren / Critical Actions (backend-guarded). Loading
  = `…`/`—`, never fake 0. Quick actions role-aware for display; privileged
  backend endpoints unchanged and still auth-guarded.

## Simulation Honesty Rules
- **Never** present simulated values as real measurements.
- **No** accuracy/precision/F1/FPS/dataset claims.
- Load/weight assumptions (tare 11t, GVW 17t, payload 6t) are project assumptions.
- Every page shows `SIMULATION` badge; every endpoint returns `simulation: true`.

## Testing
- `venv/bin/python -m py_compile backend/*.py` — typecheck
- `cd backend && venv/bin/python -m pytest -q` — 299 tests (auth, persistence,
  camera, multi-camera, cabin occupancy, fleet summary, DDS, integration,
  hardening). Tests use an isolated per-test SQLite DB (see
  `backend/tests/conftest.py`); the real `control_centre.db` is never touched.
- `cd frontend && npm run build` — compile
- Backend runs → `curl /api/health` → `{"status":"ok","simulation":true}`
- Frontend dev → login as admin, all pages render, no console errors