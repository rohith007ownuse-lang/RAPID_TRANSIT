# Rapid Transit — Consolidated Project Context

> Single-file reference for AI agents. Read this file to understand the entire project.

---

## 1. WHAT THIS PROJECT IS

**AI-Powered Mobile Urban Intelligence Platform** — converts public-transport buses into distributed mobile sensing nodes that stream structured events to a centralized **Control Centre** web dashboard.

Each bus collects: driver safety (drowsiness, distraction), cabin safety, road conditions (potholes), crash/impact, emergency signals, vehicle load, vehicle health, and fleet location. Everything streams to a white-themed operations dashboard where operators review, acknowledge, and resolve incidents.

**Status:** Everything today is a **realistic simulator** (labelled `SIMULATION`), with a WebSocket gateway ready to ingest **real bus-node hardware**. The FLEET-IQ LIVE PROTOTYPE mode runs real webcam AI perception (driver drowsiness detection) on a single laptop camera.

**Important:** This is NOT an automotive-certified safety system — it is a research/demonstration prototype.

**Original DDS baseline** (untouched): `/home/rohith/Documents/D.D.S/DriverDrowsinessDetectionSystem/`

---

## 2. TECH STACK

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + Vite, React Router, react-leaflet (OpenStreetMap tiles), Recharts, custom dark-blue theme CSS |
| Backend | Python Flask REST API + in-memory thread-safe data_store |
| WebSocket | `ws://127.0.0.1:8765` — bus-node → Control Centre ingestion |
| Fleet Simulation | `FleetSimulator` background thread: 300 vehicles, curated Chennai MTC corridors (GTFS), 1s tick |
| AI Perception | MediaPipe FaceLandmarker, YOLO (yolov8n.pt), Haar cascade fallback |
| Camera | OpenCV (cv2.VideoCapture), single webcam routed to one AI module at a time |

---

## 3. PORTS & RUN COMMANDS

```bash
# Desktop launcher (starts everything)
./start.sh

# Backend (REST :5001 + WS :8765)
cd control_centre/backend && venv/bin/python server.py

# Backend in LIVE mode (simulator off, webcam AI active)
cd control_centre/backend && venv/bin/python server.py --start-mode live

# Frontend (Vite dev, :5173, proxies /api to :5001)
cd control_centre/frontend && npm run dev

# Bus node (streams simulated live telemetry into dashboard)
python bus_node/main.py --headless --duration 30

# Restart backend in live mode (kill by port, NOT pkill -f)
fuser -k 5001/tcp
PYTHONUNBUFFERED=1 setsid venv/bin/python server.py --start-mode live </dev/null >/tmp/cc_live.log 2>&1 &
```

**Ports:** API `5001`, WebSocket `8765`, UI `5173`

---

## 4. ARCHITECTURE

```
                    ┌────────────────────────────────────────────┐
  Browser UI  ◄────►│  React + Vite (frontend)  :5173             │
  (react-leaflet,   │   pages / components / lib                 │
   OSM tiles)       └───────────────▲────────────────────────────┘
                                    │ JSON over HTTP (fetch poll 1–3 s)
                    ┌───────────────┴────────────────────────────┐
                    │  Flask API (backend)            :5001       │
                    │  server.py  ·  data_store.py (in-memory)     │
                    └───────────────▲────────────────────────────┘
                                    │ upsert / query
                    ┌───────────────┴────────────────────────────┐  │  FleetSimulator (simulator.py, thread)      │
  │  300 vehicles · MTC corridors · 1 s tick     │
                    └─────────────────────────────────────────────┘

  Real bus nodes (bus_node hardware, later phase)
        ──── WebSocket ───►  websocket_handler  :8765  ──►  data_store
                            (hello / bus_state / event / heartbeat)
```

### Data Flow (bus-node to dashboard)
```
bus_node (real or simulated) ──WebSocket :8765──► Control Centre backend
   cameras → driver monitoring                    websocket_handler adapts payloads
   sensors → BusState → Event Fusion               → shared data_store
                                                   (live bus _live supersedes simulator)
   Browser (React :5173) ◄──REST /api/*── Flask :5001 ◄── data_store
```

### Modes
- **SIMULATION mode**: `FleetSimulator` thread ticks 1×/s, 300 vehicles, events, potholes, ticketing, fatigue episodes, health.
- **LIVE mode**: simulator stopped, store cleared, webcam AI runs; a stub `PROTO-001` bus represents the live prototype; camera frames + detections served as base64 JPEG over REST.

---

## 5. PROJECT DIRECTORY STRUCTURE

```
Rapid-Tracker/
├── PLAN.md                           ← Architecture, flow diagrams, phases
├── README.md                         ← Status table, run instructions
├── URBAN_INTELLIGENCE_OVERVIEW.md    ← Deep system overview
├── SESSION_RECALL.md                 ← Session memory for continuity
├── SESSION_CHANGELOG.md              ← Detailed change log
├── ai_urban_management.md            ← Running phase log (Phases 1-11)
├── PROJECT_CONTEXT.md                ← THIS FILE (consolidated context)
├── config/system_config.json         ← Thresholds, sensors, cameras, bus params
├── bus_node/                         ← Python code that runs "on each bus"
│   ├── main.py                       ← Full pipeline entry (Phase 8 integration)
│   ├── core/                         ← FatigueEngine (brake RECOMMENDATION only), severity
│   ├── detectors/                    ← EAR, MAR, head_pose, face_detection (MediaPipe), object_detection(disabled)
│   ├── cameras/                      ← camera_manager (DRIVER/CABIN/ROAD slots)
│   ├── sensors/                      ← gps/imu/load_cell/microphone (simulation)
│   ├── ai_modules/                   ← cabin_ai, road_ai (PLANNED placeholders)
│   ├── event_fusion/                 ← event_fusion.py (crash/drowsy/overload/siren/pothole rules)
│   ├── data/                         ← event_model.py, bus_state.py
│   ├── communication/                ← websocket_client.py
│   ├── hardware/                     ← serial_communicator (runtime-disabled)
│   ├── utils/                        ← calibration, alerts, audio_synth, logging, config
│   ├── models/                       ← face_landmarker.task (MediaPipe)
│   └── src/                          ← yolov8n.pt
├── control_centre/
│   ├── AGENTS.md                     ← Agent instructions
│   ├── README.md                     ← Control centre run/API docs
│   ├── IMPLEMENTATION_PLAN.md        ← 10 intelligence phases (all COMPLETE)
│   ├── backend/
│   │   ├── server.py                 ← Flask REST API (:5001) — mode switching + camera/AI endpoints
│   │   ├── simulator.py              ← 100-bus Chennai MTC fleet sim (14 corridors)
│   │   ├── data_store.py             ← In-memory thread-safe store + mode_state
│   │   ├── websocket_handler.py      ← WS ingestion (:8765), adapt_bus_state, liveness watchdog
│   │   ├── risk_engine.py            ← 6-segment risk score 0–100
│   │   ├── recommendations.py        ← AI intervention/action layer
│   │   ├── scenarios.py              ← 6 scenarios w/ auto-expiry + rollback
│   │   ├── predictive_health.py      ← Degradation + RUL estimates
│   │   ├── eta.py / demand.py / road_risk.py
│   │   ├── ai/                       ← FLEET-IQ live prototype (latest work)
│   │   │   ├── camera_manager.py     ← CameraManager singleton: 1 webcam → 1 AI module
│   │   │   ├── driver/driver_drowsiness.py  ← MediaPipe + Haar, EAR/MAR/perclos/head-pose
│   │   │   ├── road/pothole_detector.py     ← YOLO or contour fallback + temporal confirm
│   │   │   ├── cabin/cabin_detector.py      ← Honest placeholder (no fabricated detections)
│   │   │   └── dds/                  ← dds_process.py (spawn DDS subprocess), dds_log_reader.py
│   │   ├── cascades/                 ← haarcascade XMLs (fallback detection)
│   │   ├── models/                   ← face_landmarker.task (MediaPipe)
│   │   └── requirements.txt          ← flask, flask-cors, websockets, opencv, numpy, ultralytics, mediapipe
│   └── frontend/                     ← React 19 + Vite, react-leaflet, Recharts
│       └── src/
│           ├── App.jsx               ← Routes incl. /calls (Intercom, URL-only)
│           ├── api.js                ← Fetch client + usePoll + API helpers
│           ├── lib/                  ← modeContext.jsx (SIMULATION↔LIVE), callCenter.js (pub/sub intercom)
│           ├── components/           ← Layout, FleetMap, AlertFeed, ReviewStatus, CameraFeed,
│           │                         ← CallButton, IncomingCall, BusRouteTracker, Gauge, UI
│           └── pages/                ← Dashboard, LiveFleet, BusDetails, CallCenter, Incidents,
│                                       RoadIntelligence, VehicleHealth, DriverSafety,
│                                       LoadManagement, Analytics, Settings (11 pages)
├── arduino/                          ← Firmware (motor control DISABLED)
└── assets/ data/                     ← Map, audio tones, logs
```

---

## 6. DOMAIN MODEL

### 6.1 Fleet
- **300 vehicles** across a curated set of MTC corridors (GTFS-derived; e.g. `1A`, `19D`; second service on same route is `1A .2`). `/api/buses/<id>` links use URL-encoding because ids contain a space.
- **Error budget**: only ~10 vehicles misbehave — 5 driver-attention (`_prone`) + 5 vehicle-attention (`_attention`) services. The other 290 stay healthy: transient blips self-heal and predictive-health counters decay to baseline (see `predictive_health.generate_health_events` gate).
- Each bus carries: Identity (bus_id, route_code, route, reg_no), Vehicle type (EV battery% or DIESEL fuel%), Position & motion (lat/lon, speed_kmh, journey state), Driver (state NORMAL/ATTENTION/DROWSY, name, gaze metrics EAR/MAR/pitch/closed_sec), Occupancy/load (0–60 passengers, pct, crowd level, GVW), Energy (kWh or litres), Wheels (4-tyre PSI), Vehicle health (NORMAL/WARNING/INSPECTION REQUIRED, vibration, braking_events, maintenance_priority), Ticketing (tickets_today, fare_collected ₹, avg fare ₹18.5).

### 6.2 Routes & Journeys
- 14 routes with realistic Chennai stop sequences (Koyambedu CMBT → Kilambakkam, Tambaram, Pallavaram, Chromepet, Broadway…); ~10–20 stops each.
- Journey state machine: `AT_STOP → MOVING → ARRIVING → AT_STOP …`
- Movement is road-aligned: grid-snapped east/west + north/south street staircase (~200 m block grid).

### 6.3 Events / Incidents
- **Types**: DRIVER_DROWSINESS, DRIVER_ALERT, POTHOLE, EMERGENCY_SIREN, OVERLOAD, VEHICLE_ANOMALY, CRASH, CABIN_FIRE/SMOKE/INCIDENT.
- **Severity**: CRITICAL / WARNING / INFO, with confidence (0–1).
- **Status lifecycle**: ACTIVE → REVIEWING → ACKNOWLEDGED → RESOLVED (operator audit trail).
- **Review workflow**: per-event inline edit, bulk button, per-bus bulk editing.

### 6.4 Road Defects (Potholes)
- Registry keyed by snapped grid coordinate; tracks detection_count, confidence, first/last_detected, detecting buses, mock image reference.
- Shown on Road Intelligence and Analytics pages — deliberately not on main dashboard.

### 6.5 Call / Intercom Model
- One shared in-app call store (pub/sub) — all pages see same call state.
- **Operator → driver**: one tap = instant direct connect.
- **Driver → operator**: in-bus CALL button rings control room → global incoming-call banner (accept/decline, 20s auto-timeout).
- Full-duplex console: operator mic (Web Speech, en-IN) → TTS to cabin + transcript.

---

## 7. DASHBOARD PAGES (11 total)

| Page | Route | What it does |
|---|---|---|
| **Operations Dashboard** | `/` | KPI cards, fleet map, pinned call card, live alerts, quick summaries |
| **Live Fleet** | `/fleet` | Street map with moving buses, fleet table with Intercom call column |
| **Bus Detail** | `/fleet/:busId` | Full telemetry, journey/stop tracker, call button, recent events with edit status |
| **Incidents** | `/incidents` | Full review center: filter, per-event status pills, bulk edit |
| **Road Intelligence** | `/roads` | Active pothole registry, risk zones, route risk index |
| **Vehicle Health** | `/health` | Per-bus health cards sorted INSPECTION REQUIRED → WARNING → NORMAL |
| **Driver Safety** | `/driver-safety` | Per-bus EAR/MAR/pitch gauges, drowsiness history |
| **Load Management** | `/load-management` | GVW/payload table with status badges |
| **Analytics** | `/analytics` | Boardings, potholes, events, severity, vehicle mix charts |
| **Settings** | `/settings` | Sim toggle, city bounds, bus weights, detection thresholds |
| **Intercom** | `/calls` (URL-only) | Bus list + dial, active call console with transcript and speech |

---

## 8. REST API REFERENCE (~30+ endpoints)

### Core
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness + simulation flag |
| GET | `/api/overview` | Fleet KPIs |
| GET | `/api/buses` | All buses (full state + journey) |
| GET | `/api/buses/<id>` | One bus + recent events |
| GET | `/api/events` | Event log (filter by `?status=` / `?type=`) |
| POST | `/api/events/<id>/acknowledge` | Acknowledge event |
| POST | `/api/events/<id>/review` | Mark being reviewed |
| POST | `/api/events/<id>/resolve` | Resolve event |
| POST | `/api/events/<id>/status` | Arbitrary status change |
| POST | `/api/events/status` | Bulk status for many events |
| GET | `/api/road-defects` | Pothole registry |
| GET | `/api/analytics` | Chart data |
| GET/POST | `/api/settings` | Read / update settings |

### Intelligence
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/risk` | Fleet risk scores |
| GET | `/api/buses/<id>/risk` | Unified risk assessment |
| GET | `/api/actions` | AI recommended actions |
| POST | `/api/actions/<id>/ack` | Acknowledge action |
| POST | `/api/actions/evaluate` | Trigger action evaluation |
| GET | `/api/buses/<id>/timeline` | Driver fatigue timeline |
| GET | `/api/eta` | Fleet ETA & delay |
| GET | `/api/buses/<id>/eta` | Per-bus ETA |
| GET | `/api/demand` | Fleet demand forecast |
| GET | `/api/buses/<id>/demand` | Per-bus demand |
| GET | `/api/roads/risk` | Road risk zones + route index |
| GET | `/api/buses/<id>/road-threats` | Road threats on current leg |
| GET | `/api/health/predictive` | Predictive vehicle health |
| GET | `/api/scenarios` | Scenario catalog + active |
| POST | `/api/scenarios/<key>/run` | Start scenario |
| POST | `/api/scenarios/<key>/stop` | Stop scenario |

### Mode / Live
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/mode` | Current mode (simulation/live) |
| POST | `/api/mode/switch` | Switch mode (stops sim or camera) |
| GET | `/api/live/status` | Live prototype status |

### Camera / Vision AI (FLEET-IQ)
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/camera/status` | Camera state, test slot, available cameras |
| POST | `/api/camera/test-mode` | Route webcam to driver/road/cabin |
| POST | `/api/camera/start` | Start camera (non-blocking) |
| POST | `/api/camera/stop` | Stop camera |
| GET | `/api/camera/stream/<slot>` | Base64 JPEG frame + detection overlay |
| GET | `/api/camera/detections/<slot>` | Detection results |
| GET | `/api/ai/status` | Camera + driver + road + cabin status |
| GET | `/api/ai/driver/state` | Driver drowsiness state |
| GET | `/api/ai/pothole/stats` | Pothole detection stats |

### DDS (Original Driver Drowsiness System)
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/dds/status` | Phase, calibration progress, thresholds, monitoring, audio |
| POST | `/api/dds/calibrate` | Start 5s baseline (auto-starts driver camera) |
| POST | `/api/dds/start` | Begin monitoring (calibrated thresholds) |
| POST | `/api/dds/stop` | Stop monitoring (audio silenced) |
| POST | `/api/dds/reset` | Idle, clears calibration + monitoring |

---

## 9. WEBSOCKET PROTOCOL (bus_node → Control Centre)

Endpoint: `ws://<host>:8765`

| Client → Server | Payload | Effect |
|---|---|---|
| `hello` | `{bus_id}` | Registers connection |
| `bus_state` | `{bus_id, state}` | Upserts bus (adapted to dashboard schema) |
| `event` | `{bus_id, event}` | Adds event; ROAD_DEFECT grouped into defect map |
| `heartbeat` | `{bus_id}` | Refreshes liveness; stale > 30s reverts to simulator |

Server → Client: `{type: "ack", ok: true, ...}`

A connected (live) bus **supersedes** its simulated copy: the fleet simulator skips `_live` buses.

---

## 10. PHASE HISTORY (ALL COMPLETE)

### Bus-Node Phases (ai_urban_management.md)
| Phase | What | Status |
|-------|------|--------|
| **Phase 1** | Copy DDS driver-drowsiness stack into `bus_node/` (no braking, recommendation only) | ✅ DONE |
| **Phase 2** | Control Centre web UI (Flask + React), 10 pages, simulated | ✅ DONE |
| **Phase 3** | Camera Manager: 3 slots, driver webcam active | ✅ DONE |
| **Phase 4** | Sensor interfaces (GPS/IMU/load/mic) in simulation mode | ✅ DONE |
| **Phase 5** | Event model + BusState manager | ✅ DONE |
| **Phase 6** | Event Fusion Engine (crash, drowsy-while-moving, overload compound, siren, pothole dedup) | ✅ DONE |
| **Phase 7** | Bus-node ↔ Control Centre WebSocket link | ✅ DONE |
| **Phase 8** | Full integration: cameras → monitoring → sensors → state → fusion → WS → dashboard | ✅ DONE |
| **Phase 9** | Documentation & polish | ✅ DONE |

### Control Centre Intelligence Phases (IMPLEMENTATION_PLAN.md)
| Phase | What | Status |
|-------|------|--------|
| **Phase 1** | Unified risk engine (6 segments, 0–100, editable weights) | ✅ COMPLETE |
| **Phase 2** | Temporal fatigue + PERCLOS driver model | ✅ COMPLETE |
| **Phase 3** | AI intervention / recommendation actions | ✅ COMPLETE |
| **Phase 4** | Driver recovery detection + safety timeline | ✅ COMPLETE |
| **Phase 5** | Scenario simulator (fog, festival, closure, monsoon, EV crisis, fatigue wave) | ✅ COMPLETE |
| **Phase 6** | Predictive vehicle health (degradation + RUL) | ✅ COMPLETE |
| **Phase 7** | ETA / delay prediction | ✅ COMPLETE |
| **Phase 8** | Demand / boarding forecasting | ✅ COMPLETE |
| **Phase 9** | Road risk intelligence (zones, route index, leg threats) | ✅ COMPLETE |
| **Phase 10** | Polish (DriverSafety/LoadManagement wired, README/AGENTS updates) | ✅ COMPLETE |

### FLEET-IQ Live Prototype
| Phase | What | Status |
|-------|------|--------|
| **Phase 10** | FLEET-IQ Live Prototype: webcam AI perception + mode switch | ✅ DONE |
| **Phase 11** | Original DDS embedded in the Live Prototype camera feed | ✅ DONE |

---

## 11. FLEET-IQ LIVE PROTOTYPE — DDS ENGINE DETAILS

### How it works
1. Switch UI to **LIVE PROTOTYPE** mode (header DATA SOURCE pill)
2. On `/fleet` or `/fleet/PROTO-001`: assign webcam to **Driver DDS**
3. Press **Calibrate** (5s personal baseline, 15 samples)
4. Press **Start Monitoring** — real EAR/MAR/head-pose/PERCLOS + audio warning + events

### DDS Engine Phases
`idle → calibrating → ready → monitoring`

### Calibration Math (original DDS)
- 5 seconds / 15 samples
- `ear_thr = clamp(median_ear × 0.75, 0.15, 0.30)`
- `mar_thr = clamp(median_mar + 0.20, 0.40, 0.90)`

### Events Emitted
- `DRIVER_DROWSINESS` (CRITICAL on drowsy start, WARNING for head nod/pose alert)
- `DRIVER_ALERT` (CRITICAL, once per episode, with AUDIO_WARNING)
- All with `bus_id: PROTO-001`, `data_source: live`, `simulation: False`

### Audio Warning
- Uses original DDS `bus_node.utils.alert_manager`
- `tone_warning.wav` / `tone_critical.wav` in `bus_node/generated_audio/`
- Loops while drowsy, stops on recovery

### Verification Results (real webcam)
- Calibration: 79 samples → EAR thr 0.271 (0.75 × baseline), MAR thr 0.40
- Live: EAR 0.42–0.47, MAR 0.02–0.05, real pitch/yaw, PERCLOS 0.008
- Real `DRIVER_DROWSINESS` events emitted on head-pose alerts
- Audio warning loop confirmed (aplay speaker playback)
- CPU: 193% → ~32% idle / ~84% monitoring (rate-capped capture loop)
- Face mesh visible in streamed frame (~2,900 green mesh pixels)

### Known Gotchas
- `cv2.VideoCapture(0)` must be opened in the **main process** (Flask threads deadlock)
- Cascade/model paths resolved relative to `__file__` (not hard-coded)
- MediaPipe is PRIMARY AND ONLY detector when available; Haar only if MediaPipe missing
- `NO FACE` wipes PERCLOS window to prevent stale false alarms
- Single webcam = one perception slot at a time (Driver DDS / Pothole / Cabin)
- Restart by port (`fuser -k 5001/tcp`), NOT `pkill -f` pattern

---

## 12. INTELLIGENCE LAYERS (Control Centre)

### Risk Engine (`risk_engine.py`)
6-segment risk score 0–100: driver / vehicle / load / speed / occupancy / history
Risk levels: LOW / MEDIUM / HIGH / CRITICAL with human-readable reasons and recommended actions.

### Scenario Simulator (`scenarios.py`)
6 scenarios with auto-expiry & rollback: dense_fog, festival_rush, road_closure, monsoon_flood, ev_energy_crisis, driver_fatigue_wave. Apply feature flags (speed caps, fatigue boosts, demand multipliers, detours, pothole surges, EV drain) for limited duration.

### Predictive Health (`predictive_health.py`)
Per-bus degradation counters: tyre wear, vibration drift, harsh braking rate, energy degradation. Linear trend RUL estimators. Predictions: TYRE_REPLACEMENT, VIBRATION_INSPECTION, ENERGY_DEGRADATION.

### ETA Engine (`eta.py`)
Dwell model (base dwell by stop type + occupancy factor + pothole/roadwork friction) + traffic lapse + Haversine distance. Delay bands: ON_TIME / MINOR_DELAY / SIGNIFICANT_DELAY / SEVERE_DELAY.

### Demand Engine (`demand.py`)
Time-of-day + weekday profile + road friction. Per-route, per-stop boarding forecasts with confidence.

### Road Risk (`road_risk.py`)
Defect clustering → risk zones (0–100 score, levels) + per-route risk index + leg threats (within 1 km of segment midpoint).

---

## 13. CONFIGURATION

`config/system_config.json` — all thresholds, sensors, cameras, bus params:
- System: bus_id, mode, simulation_mode
- Cameras: driver (index 0, active), cabin (disabled), road (disabled)
- Detection: ear_threshold 0.23, mar_threshold 0.40, eye_closed_duration 1.3s, perclos_window 60s
- Sensors: IMU/GPS/load_cell/microphone (all simulation mode)
- Bus: tare 11,000 kg, max_gvw 16,200 kg, payload_limit 6,000 kg
- Communication: websocket, server_url ws://localhost:8765
- Hardware: enabled false

---

## 14. HONESTY RULES (ALWAYS)

1. Simulated values are **never** presented as real measurements; `SIMULATION` badge + `simulation: true` everywhere.
2. No accuracy/precision/F1/FPS/dataset claims unless measured.
3. Load/weight values (tare 11t, GVW ~16–17t, payload 6t) are project assumptions, not legal/validated figures.
4. Real-HW features stay labelled PLANNED until actually implemented.
5. Cabin AI remains an honest placeholder (never fabricates detections).

---

## 15. STATUS TABLE

| Module | Status |
|--------|--------|
| Driver monitoring (EAR/MAR/head-pose/drowsiness) | **IMPLEMENTED** (ported from DDS) |
| Calibration | **IMPLEMENTED** |
| Audio alert tones | **IMPLEMENTED** |
| Event logging | **IMPLEMENTED** |
| Control Centre web UI (map + live fleet) | **IMPLEMENTED** (simulated data, clearly labeled) |
| 300-vehicle Chennai MTC fleet simulator | **IMPLEMENTED** (simulated data, 10-vehicle error budget) |
| Per-bus ticket machine counters | **IMPLEMENTED** (simulated MTC ticket-machine data) |
| Operator Intercom | **IMPLEMENTED** (in-app call store; simulated) |
| Risk engine / AI actions / scenarios / predictive health / ETA / demand / road risk | **IMPLEMENTED** (simulated) |
| Backend REST API + fleet simulation | **IMPLEMENTED** (simulated data) |
| Camera Manager (3 slots, 1 active) | **IMPLEMENTED** (DRIVER webcam live) |
| FLEET-IQ LIVE PROTOTYPE mode | **IMPLEMENTED** (live webcam; sim/live switchable from UI) |
| Original DDS embedded in Live Prototype | **IMPLEMENTED** (live webcam, verified) |
| Sensor interfaces (GPS/IMU/load/mic) | **IMPLEMENTED** (simulation only) |
| Event model + bus state manager | **IMPLEMENTED** |
| Event Fusion Engine | **IMPLEMENTED** (crash/drowsy/overload/siren rules, pothole dedup) |
| Bus-node ↔ Control Centre link | **IMPLEMENTED** (WebSocket; simulated payloads) |
| GPS/IMU/Load/Microphone (real HW) | **PLANNED** (hardware not mounted) |
| Event Fusion Engine (real-HW inputs) | **PLANNED** |
| Bus-node ↔ Control Centre live link | **PLANNED** |
| Automatic braking | **DISABLED** — brake recommendation only; Control Centre decides after human review |

---

## 16. ROADMAP (NEXT STEPS)

1. Replace simulated buses with live `bus_node` WebSocket feeds.
2. Real camera feeds / MediaPipe driver-AI on node hardware.
3. Predictive maintenance (history + model), ETA/delay prediction, demand forecast — **DONE** (`predictive_health.py`, `eta.py`, `demand.py`).
4. PDF/CSV incident report export and operator roles — **DONE** (Sep 7, 2026): `backend/incident_export.py` (CSV + pure-Python PDF, no deps), `GET /api/incidents/export?format=csv|pdf&severity=&status=&bus_id=&data_source=`; Incidents page has Export CSV/PDF buttons honoring the active filter and a persistent Operator identity + role (Operator/Supervisor/Admin; resolve + status edits require Supervisor/Admin).
5. Expose DDS subprocess control + log-reader as UI buttons/panel — **DONE**: `GET /api/dds/subprocess/status`, `POST /api/dds/subprocess/start|stop`, `GET /api/dds/logs`; the Live Camera Grid driver view adds a DDS Console card (CALIBRATE/MONITOR/STOP/RESET engine buttons + subprocess launch/stop + latest session summary). Note `dds_process.py` had a non-reentrant `threading.Lock` deadlock in `start()/stop()` — fixed with `threading.RLock()` (Sep 7, 2026).
6. Wire `DRIVER_DISTRACTION` path if phone/drink detection is implemented.

## 17. SOUND SYSTEM STATUS (IMPORTANT)

Sound is **OFF** until the user says "sound on" (disabled per user request, Sep 7, 2026).
- The DDS drowsiness alarm lives in `bus_node/utils/alert_manager.py` and loops `tone_critical.wav`/`tone_warning.wav` via `aplay` whenever monitoring hits CRITICAL/WARNING. Alarm loops ORPHANED in the past (≈50 zombie `aplay` loops) — **fixed Sep 13, 2026** with a 3-layer defense:
  1. `feature_toggles.json` → `audio_alerts: false` (default OFF, matches the standing user decision); `update()` refuses to start sound while it is false.
  2. `_silence_stray_loops()` runs at EVERY `AlertManager` construction (not only when muted) — any leftover `aplay` loop on our tones is killed before a new one can start; a daemon watchdog re-sweeps every 15 s.
  3. `stop()` kills the alarm's whole process group (bash loop + `aplay` child, SIGTERM then SIGKILL, own session via `start_new_session=True`) — a parent dying can no longer leave a playing loop behind.
- Kill-switches to re-enable sound deliberately:
  - Feature Toggles page (or `feature_toggles.json`) → `audio_alerts: true` (AlertManager unmutes via runtime toggle).
  - `control_centre/frontend/src/pages/CallCenter.jsx` → `SOUND_ENABLED` (currently `false`) gates the Web-Speech TTS `say()`.

---

*Last updated: Sep 7, 2026*
