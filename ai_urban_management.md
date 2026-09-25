# AI Urban Intelligence Management — Phase Log

Running phase-by-phase record of the **AI Urban Intelligence Platform** project.
Purpose: keep a durable summary of decisions, structure, and verification results
so work can resume cleanly even after a fresh session.

Project root: `/home/rohith/Desktop/Rapid-Tracker/`
Master plan: `PLAN.md` (architecture, flow diagrams, phases, event model, config).
Original DDS baseline (UNTOUCHED): `/home/rohith/Documents/D.D.S/DriverDrowsinessDetectionSystem/`

---

## PHASE 1 — Copy DDS + Preserve Driver Monitoring ✅ DONE

### Goal
Copy the DDS driver-drowsiness stack into the new platform without modifying DDS.

### What was copied
- `bus_node/detectors/`: face_detection, eye_detection (EAR), mouth_detection (MAR),
  head_pose (solvePnP), object_detection (yolov8n; **monitor-only**, not in main flow)
- `bus_node/core/`: fatigue_engine, severity
- `bus_node/utils/`: calibration, alert_manager, audio_synth, enhanced_logger,
  config_manager, utils
- `bus_node/hardware/`: serial_communicator (**runtime-disabled**)
- Models: `bus_node/models/face_landmarker.task`, `bus_node/src/yolov8n.pt`
- Audio tones, map asset, Arduino firmware, requirements.txt

### Key changes from DDS
1. Imports rewritten `src.*` → `bus_node.*` across all copied modules.
2. Model paths fixed:
   - `face_detection.py`: MODEL_DIR now `bus_node/` (was 2 levels up).
   - `object_detection.py`: yolov8n.pt resolved to `bus_node/src/yolov8n.pt`.
3. **Automatic braking fully removed.** `fatigue_engine.py` no longer sends
   G/R commands or latches an emergency stop. It now produces a
   `brake_recommended` flag + `brake_recommend_reason` (`eye_closure`/`face_loss`)
   that the **Control Centre** acts on after human safety review.
   - `process_frame()` and `handle_face_lost()` return `brake_recommended`,
     `total_brake_recommendations`, `total_face_loss_recommendations`.
   - `clear_emergency_stop()` → `clear_brake_recommendation()`.
4. Removed: Tkinter dashboard, vehicle control panel, autopilot/obstacle logic.
5. Excluded (never carried): Bluetooth/HC-05, ultrasonic, obstacle avoidance,
   autonomous driving.
6. Config `config/system_config.json` extended with: `system` (bus_id, mode),
   `simulation_mode`, `cameras` (driver/cabin/road, only driver active),
   `sensors` (imu/gps/load_cell/microphone, simulation), `bus`
   (tare 11000 kg, max_gvw 16200 kg, payload_limit 6000 kg), `communication`
   (websocket), `control_centre`.
   `hardware.enabled` set to `false` (motor control disabled).
7. `bus_node/main.py` — headless Phase-1 runner:
   `python bus_node/main.py` from project root (calibration + engine loop).

### Verification
- All `bus_node` modules import cleanly with the DDS venv python.
- Engine unit test (`test_bus_engine.py`): open eyes → NORMAL (no rec);
  closed 3 s → no rec; closed > 5 s (test threshold) → brake recommendation
  reason `eye_closure`; reopen → rec cleared; face-loss > 2 s → rec `face_loss`;
  summary includes new counters. **All passed.**
- `bus_node/main.py` starts and prints `[bus_node:BUS-001] ...`.
- Original DDS: verified untouched (git status + file mtimes unchanged).

### Notes for later phases
- Bus node currently runs standalone headless; WebSocket link to Control
  Centre is the integration point for later phases.
- Calibration observations still treated as dev notes, NOT validated metrics.

---

## PHASE 2 — Control Centre Web UI ✅ DONE

### Goal
Professional, white-themed web operations-dashboard (no dark/cyberpunk styling).

### Stack
- Backend: Python **Flask** REST API + in-memory simulation engine.
- Frontend: **React 18 + Vite + JavaScript**, React Router, Leaflet map, Recharts.
- All UI data is **simulated and clearly labeled** (SIMULATION banner).
- Future real data will stream from bus_node via WebSocket (Phase 6+).

### Structure created
```
control_centre/
├── backend/
│   ├── server.py            # Flask app + REST API
│   ├── simulator.py         # Simulated fleet/event/road-defect generator
│   └── data_store.py        # In-memory bus/event/defect store
└── frontend/
    ├── package.json, vite.config.js, index.html
    └── src/
        ├── App.jsx          # Router + layout
        ├── api.js           # fetch client
        ├── theme.css        # white/professional theme variables
        ├── components/      # Layout, StatusCard, AlertFeed, MapWidget,
        │                    # CameraFeed, Gauge, SimBadge, etc.
        └── pages/           # Dashboard, LiveFleet, BusDetails,
                             # DriverSafety, Incidents, RoadIntelligence,
                             # LoadManagement, VehicleHealth, Analytics, Settings
```

### Pages
1. **Dashboard** — 6 summary cards (Active Buses, Driver Alerts, Active Incidents,
   Overloaded Buses, Road Hazards, Emergency Events), fleet map + live alert feed,
   lower row of Driver Safety / Vehicle Health / Load / Road / Emergency cards.
2. **Live Fleet** — all bus markers on map + fleet table (bus, route, status,
   driver, load, vehicle, last update). Click → BusDetails.
3. **Bus Details** — 3-camera layout (Driver live / Cabin / Front) with only
   Driver active (Cabin/Front show PLANNED placeholders), plus driver status,
   load/GVW, vehicle health, GPS, recent events.
4. **Driver Safety** — live driver camera, EAR, MAR, head pose, closed duration,
   driver state (NORMAL/ATTENTION/DROWSY/CRITICAL), warning history.
5. **Incidents** — incident cards (Crash, Fire/Smoke, Drowsiness, Road Hazard,
   Siren, Overload, Vehicle Health) with severity, bus, time, GPS, status,
   [Open Live Feed] [Acknowledge].
6. **Road Intelligence** — pothole/defect map + grouped persistent road defects
   (detection count, confidence, last detected, detecting buses), time filters
   (Today / 7 days / 30 days).
7. **Load Management** — table: Bus, GVW, Tare, Payload, Limit, Load %, Status,
   Location, Last Update. Statuses NORMAL / HIGH LOAD / OVERLOAD / CRITICAL OVERLOAD.
8. **Vehicle Health** — bus health cards: status (NORMAL/WARNING/INSPECTION
   REQUIRED), vibration/impact/braking anomalies, maintenance priority.
9. **Analytics** — charts: drowsiness by bus, incidents by route, potholes by
   road, overload events, crashes, siren events, health warnings, occupancy trend.
10. **Settings** — config display/editing surface (simulation mode toggle,
    bus params, thresholds), marked experimental.

### Simulated demo data rules
- Every page shows a `SIMULATION` badge where data is synthetic.
- No fabricated accuracy/precision/F1/FPS claims anywhere.

### How to run (from control_centre/backend, after creating venv)
```bash
python3 -m venv venv
venv/bin/pip install flask flask-cors
venv/bin/python server.py            # serves API at http://localhost:5001
# frontend:
cd ../frontend && npm install && npm run dev   # http://localhost:5173
```

### Files created
- `control_centre/backend/`: `data_store.py` (thread-safe bus/event/defect store),
  `simulator.py` (FleetSimulator: 8 demo buses, events, grouped potholes, seeded
  history), `server.py` (Flask REST API, CORS).
- `control_centre/frontend/`: Vite+React app. `src/theme.css` (white theme),
  `src/api.js` (fetch client + `usePoll` 3s polling hook),
  `components/`: Layout (sidebar nav), UI (StatusBadge/StatCard), AlertFeed,
  FleetMap (react-leaflet, divIcon bus/defect markers), CameraFeed (3-slot),
  Gauge (SVG); `pages/`: the 10 dashboard pages listed above.
- `control_centre/README.md` run/API docs.

### Verification
- Backend endpoints all respond: /api/health, /api/overview, /api/buses,
  /api/buses/<id>, /api/events, /api/road-defects, /api/analytics, /api/settings.
- Deterministic seed (Random(7)) gives initial events + 3 grouped potholes;
  live ticks add events/defects over time (duplicate pothole detections from
  different buses increment one grouped defect's count/confidence).
- Frontend `npm run build` passes; Vite dev server serves the app; `/api` proxy
  to Flask verified end-to-end (dashboard 200, events flow through proxy).
- Backend was started with `setsid`/`disown` to survive shell termination, on
  port 5001 (note: earlier logs show a transient ECONNREFUSED in Vite proxy only
  while the backend was briefly down before restart — resolved).

### Notes / decisions
- All data is labeled SIMULATION via the purple `◈ SIMULATION` badge.
- No fabrications: no accuracy/precision/F1/FPS claims.
- react-leaflet uses divIcon markers (no default-icon asset issues).
- Recharts + Leaflet make the JS bundle >500 kB (build warning only).
- `usePoll` polls every 3 s. Real-time push (WebSocket) is reserved for the
  bus-node integration phase, keeping this phase decoupled and testable.
- Camera tiles: Driver = LIVE placeholder; Cabin/Front = PLANNED (hardware and
  frame streaming to be added later). Matches the "1 camera now, 3 slots" plan.

---
## PHASE 3 — Camera Manager & Multi-Camera Architecture ✅ DONE

### Goal
3-slot camera architecture (DRIVER / CABIN / ROAD) behind one uniform API,
with only the driver webcam active; CABIN/ROAD as clearly-labeled placeholders.

### What was created (`bus_node/cameras/`)
- `camera_manager.py` — `CameraManager`: builds the 3 slots from
  `config/system_config.json -> cameras.*`, exposes `start_active()`,
  `get_frame(slot)`, `release_all()`, `status_matrix()`, `summary()`.
- `driver_camera.py` — `DriverCamera`: wraps `cv2.VideoCapture(index)`, sets
  resolution, tracks status (OFF/ACTIVE/ERROR), recovers from transient frame
  failures, exposes `.read()` so `run_calibration()` can consume it unchanged.
- `placeholder_camera.py` — shared `PlaceholderCamera`: same
  `start()/read()/release()/info()` contract; `read()` returns a BGR frame
  labeled `[NO CAMERA] <SLOT> slot - PLANNED` for the future UI.
- `cabin_camera.py` / `road_camera.py` — thin `CABIN` / `ROAD` subclasses.
- `__init__.py` re-exports the public API.

### Integration
- `bus_node/main.py` now opens cameras via `CameraManager` (driver slot only),
  prints the per-slot status line, feeds the 5 s calibration from the driver
  camera, and releases all slots on exit. `--camera-index` overrides the
  driver camera index.

### Verification
- All camera modules import cleanly with the DDS venv python (cv2 5.0, numpy 2.5).
- Headless smoke test: manager started, status matrix shows
  `DRIVER=ACTIVE | CABIN=DISABLED | ROAD=DISABLED`; driver `get_frame()` returned
  `(True, 480x640x3)` and a real **514 KB PNG** was written/validated; placeholders
  returned labeled frames with status DISABLED/PLANNED; `release_all()` clean.
- `main.py` + cameras package `py_compile` pass.

### Notes / decisions
- Placeholders never open hardware; they exist so the control-centre camera tiles
  and future fusion pipeline can assume a uniform API.
- CABIN/ROAD stay DISABLED unless their `active` flag is set in config; even then
  status reports PLANNED (capability doesn't exist yet) — never a fake "LIVE".
- Status "ACTIVE" for the webcam means genuinely streaming, verified by a real
  frame read, not merely opened.

---

## PHASE 4 — Sensor Interfaces (Simulation Mode) ✅ DONE

### Goal
Simulated IMU / GPS / load-cell / microphone interfaces with realistic demo data,
each reading clearly labeled [SIMULATION], behind one uniform sensor contract.

### What was created (`bus_node/sensors/`)
- `base_sensor.py` — `BaseSensor`: `init()/read()/get_status()/enable()/disable()`
  contract; `read()` always injects `sensor`, `source`, and `simulation` labels.
- `gps_sensor.py` — `GPSSensor`: follows the Route 42 waypoint loop in Central
  Bengaluru with a drive cycle (STOPPED → ACCELERATE → CRUISE → DECELERATE),
  fix noise, speed/heading/odometer. Report is source+simulation labeled.
- `imu_sensor.py` — `IMUSensor`: ax/ay/az in g and m/s² with brake/accelerate/
  bump events; flags `hard_braking` (ax < −0.5 g) and `impact`
  (resultant > impact_g_threshold = 3.0 g).
- `load_cell.py` — `LoadCellSensor`: GVW = tare (11,000 kg) + payload with
  boarding/alighting groups bounded by payload limit (6,000 kg); emits
  NORMAL / HIGH LOAD / OVERLOAD / CRITICAL_OVERLOAD.
- `microphone.py` — `MicrophoneSensor`: ambient dB + occasional siren detection
  when confidence ≥ threshold (0.7).
- `sensor_manager.py` — `SensorManager`: builds all four from config
  (`sensors.*`, `bus.*`), `init_all()/read_all()/status_matrix()/summary()`,
  plus a `--demo/--ticks/--dt` headless runner.

### Verification
- `python -m bus_node.sensors.sensor_manager --ticks 40`: all 4 sensors
  INIT → ACTIVE:SIM; GPS in Bounds (12.90–13.02 N, 77.5–77.7 E), IMU shows a
  brake spike (−0.54 g) and bumps (a_z 1.4–1.9 g), load stable at 35% NORMAL,
  mic LISTENING. Everything labeled [SIM].
- GPS drive-cycle test: stopped (0 km/h) → accelerates → cruises ~19 km/h,
  reaches waypoint 1, odometer increments; stays in bounds. Initial stop dwell
  shortened to 2 s so the demo visibly moves.

### Notes / decisions
- Real hardware branches (MPU6050 / NEO-6M / HX711 / USB mic) are NOT
  implemented: hardware not mounted; `init()` reports ERROR for non-simulation.
- All outputs carry `simulation: true` + `source`, so downstream consumers
  (bus state, fusion, Control Centre) can never present them as real telemetry.
- Tare/payload values remain project assumptions, not legal/validated figures.

---

## PHASE 5 — Event Model & Bus State ✅ DONE

### Goal
Structured event model + a BusState manager that aggregates every bus-node
source into one snapshot ready for later phases (fusion, WebSocket, CC).

### What was created (`bus_node/data/`)
- `event_model.py` — `Event` dataclass (event_id UUID, bus_id, event_type,
  timestamp, lat/lon, severity, confidence, sensor_source, status,
  additional_data, fusion_events, simulation) + `EventType` / `Severity` /
  `EventStatus` enums and `new_event()` factory. Values are aligned with the
  Control Centre simulator's event types (DRIVER_DROWSINESS, POTHOLE, CRASH,
  EMERGENCY_SIREN, OVERLOAD, VEHICLE_ANOMALY, CABIN_*).
- `bus_state.py` — `BusState`: absorbs driver frame results (status/EAR/MAR/
  drowsy/brake recommendation), labeled sensor readings (GPS/IMU/load/mic),
  camera + sensor status matrices, and `record_event()` (bounded list,
  max 200). Exposes `snapshot()`/`to_dict()` in a control-centre-friendly shape.

### Verification
- Event model: IDs, string enum values, ACTIVE default, simulation flag all OK.
- BusState absorbed a DROWSINESS frame (brake recommend `eye_closure`), GPS,
  load (13,100 kg, 35% NORMAL), and microphone readings; snapshot correct.
- Single-instance SensorManager accumulation drives GPS to motion (5.7 km/h
  after 3 s); a forced IMU impact flips health to INSPECTION REQUIRED with
  anomaly "crash/impact detected" and impact_count=1.

### Notes / decisions
- `simulation: True` is set on every event and the snapshot until real bus-node
  data exists — no fabricated telemetry.
- Recent-event store is purely in-memory on the bus node; persistence lives on
  the Control Centre side.

---

## PHASE 6 — Event Fusion Engine ✅ DONE

### Goal
Turn raw bus-node detections (driver frame results, sensor readings) into
structured, de-duplicated incident events before any Control Centre upload.

### What was created (`bus_node/event_fusion/`)
- `event_fusion.py` — `FusionEngine(bus_id)` with rule-based fusion:
  - **CRASH**: IMU impact (resultant ≥ 3.0 g) while speed < 30 km/h →
    severe CRASH; at higher speed → VEHICLE_ANOMALY. TWICE cooldown, non-persistent
    PERIODIC cooldown for periodic anomalies (e.g. load spikes).
  - **DRIVER_DROWSINESS**: drowsy state / brake recommendation while the bus is
    moving (speed > 3 km/h) → WARNING, edge-triggered (re-arms only after the
    driver returns to NORMAL, so a sustained episode emits one event).
  - **OVERLOAD (compound)**: hard braking (IMU ax < −0.5 g) while load status is
    OVERLOAD/CRITICAL_OVERLOAD → OVERLOAD with `compound: true`, factors listed.
  - **EMERGENCY_SIREN**: microphone siren edge-trigger (LISTENING→siren) with a
    45 s re-arm, so repeated detections in one pass do not spam.
  - **POTHOLE dedup**: repeated IMU bump/heavy-brake cycles near the same GPS
    location converge to a single ROAD_DEFECT (pothole) with rising
    detection_count; cooldown 60 s; battery/health anomalies suppressed during
    a persistent period (rate limiting).
- `__init__.py` re-exports `FusionEngine`.

### Verification
- `python -m bus_node.event_fusion.event_fusion --demo --ticks 300`:
  **ALL FUSION CHECKS PASSED** — crash (impact + 15 km/h), drowsy-while-moving
  (single event from a sustained episode), overload compound factor, siren
  edge-trigger (one event), pothole convergence (one ROAD_DEFECT with
  detection_count growing from several bumps at one site).

### Notes / decisions
- Fusion produces events with `simulation: True` and `sensor_source` set — the
  Control Centre can always distinguish synthetic incidents from future real
  ones.
- Cooldowns/edge-triggers exist to prevent event flooding; thresholds come from
  `config/system_config.json`.

---

## PHASE 7 — Bus-Node ↔ Control Centre WebSocket Link ✅ DONE

### Goal
Stream bus-node state and fused events into the Control Centre over WebSocket so
the dashboard shows live (simulated) telemetry rather than only pre-seeded data.

### What was created
- `control_centre/backend/websocket_handler.py` — async WS server (default port
  `8765`, `start_websocket_server()` runs it on a daemon thread):
  - `handle_message()` dispatches `hello` / `bus_state` / `event` / `heartbeat`.
  - `adapt_bus_state()` converts a bus-node snapshot into the dashboard schema
    (driver.state from the frame status, load.status/GVW, vehicle.health +
    anomaly list, occupancy 0/0, cameras/sensors statuses, `last_update`) and
    marks the bus `_live: True`.
  - `link_road_defect()` merges ROAD_DEFECT/POTHOLE/CABIN events into the
    persistent grouped road-defect map (increments detection_count/confidence,
    adds detecting buses).
  - `_liveness_watchdog()` reverts `_live` buses to the simulator after 30 s
    without contact, so stale nodes don't pin dead data on the map.
- `control_centre/backend/data_store.py` — added thread-safe `get_road_defect`.
- `control_centre/backend/server.py` — `--ws-port` (default 8765), `--no-ws`
  flag; starts the WS server in `main()`.
- `bus_node/communication/websocket_client.py` — `WebSocketClient(url, bus_id)`
  with async reconnect/backoff (writes to a thread-safe outbound queue),
  `send_hello()/send_bus_state()/send_event()/send_heartbeat()`, and a `demo()`
  runner. `communication/__init__.py` exports it.
- `bus_node/main.py` — full Phase-8 integration (see PHASE 8) includes the client.
- `control_centre/backend/requirements.txt` — flask, flask-cors, websockets.

### Simulator supersede rule (important)
A connected bus node **supersedes** its simulated copy: `adapt_bus_state()` sets
`_live: True` and `FleetSimulator._tick()` skips `_live` buses (no random-walk,
no occupancy overwrite, no simulator-emitted events). This keeps dashboard data
consistent when a real (simulated) node is streaming.

### Verification (round trip, headless)
- Rediscovered `state` vs `loop` mapping names while the server was down, fixed
  imports, and confirmed server start from `control_centre/backend`.
- Backend restarted with WS (5001 + 8765); old process doggedly kept the port
  after `pkill`, so it was killed by explicit PID.
- Bus-node demo client connected and round-tripped 20 messages. REST then showed
  the bus-node BUS-001 as `_live` with driver DROWSY, occupancy 0/0 (not
  simulator-mutated), and 3 bus-node DRIVER_DROWSINESS events + 1 ROAD_DEFECT
  (UUID 36-char, grouped at its own lat/lon, count=1, buses=[BUS-001]) in the
  store.
- Confirmed `FleetSimulator` did not overwrite the live bus after the `_live`
  skip was added.

### Notes / decisions
- Reconnect backoff is capped (2 s → 30 s, max attempts before give-up); the
  client logs per-attempt so a missing Control Centre is obvious, not silent.
- The WS handler prints a line per accepted/closed connection and per message
  type for operational visibility (dev logging only).

---

## PHASE 8 — Full Integration & End-to-End Test ✅ DONE

### Goal
Wire all bus-node subsystems into one process that behaves like a real sensing
node: cameras → driver monitoring → sensors → BusState → fusion → WebSocket →
Control Centre dashboard (all data simulated and labeled).

### What changed
- `bus_node/main.py` rewritten around a single loop:
  1. `CameraManager` (DRIVER webcam ACTIVE; CABIN/ROAD placeholders DISABLED).
  2. 5 s calibration GUI only when a display is available and not `--headless`;
     otherwise default thresholds (headless-safe).
  3. Per-iteration driver monitoring via `face_mesh` + `FatigueEngine` (with
     face-loss handling), folded into `BusState` via `update_driver()`.
  4. `SensorManager.read_all()` each iteration → `update_sensor()`; status
     matrices pushed to the snapshot.
  5. `FusionEngine.evaluate()` → fused events recorded locally and pushed over WS.
  6. `WebSocketClient` streams `bus_state` ~1×/s + events + hello; flush + clean
     shutdown on stop.
  7. `--duration` auto-stop for testable runs.
- Added `websockets>=14.0` to root `requirements.txt`.

### Verification (end-to-end, headless, 6 s run)
- Console: webcam streaming (real EAR ~0.34–0.52, MAR ~0.01–0.08, driver
  NORMAL→NO FACE as the test subject left), GPS climbed 0→19.3 km/h on the
  Route 42 drive cycle, load_cell NORMAL 13.1 t with passengers boarding,
  microphone LISTENING, WS connected to `ws://localhost:8765`.
- Control Centre REST after the run: BUS-001 `_live`, `route: Route 42 - Central
  District`, driver state NORMAL / ear 0.518 / mar 0.058 / pitch −5.1 (real
  webcam), GPS 12.971702/77.594664 at 21.3 km/h, load NORMAL 13,340 kg, health
  NORMAL, cameras [ACTIVE, DISABLED, DISABLED], sensor statuses streamed, and
  `simulation: True`.
- Confirmed the DDS original is untouched by this project (DDS git status/mtimes
  pre-date this session; our edits live only in `bus_node/`).

---

## PHASE 9 — Documentation & Polish ✅ DONE

### What changed
- `control_centre/README.md`: rewritten with architecture diagram, run steps for
  backend (venv + `requirements.txt`), frontend, and bus node; API endpoint
  table; WebSocket protocol table (hello/bus_state/event/heartbeat + supersede
  rule); page list; honesty rules.
- `README.md`: updated run section (full bus-node pipeline command, Control
  Centre with WS port) and status table — Sensor interfaces, Event model,
  Fusion, and Bus-node↔CC link marked IMPLEMENTED; real-HW rows stay PLANNED.
- `control_centre/backend/requirements.txt` added (flask, flask-cors,
  websockets) for reproducible venvs.
- Root `requirements.txt` gained `websockets>=14.0`.
- `PLAN.md` phases reconciled to canonical order (1–9, see header) and section
  15 statuses marked per phase completion.

### Final verification status
- `npm run build` passes; Vite dev server on :5173, Flask on :5001, WS on :8765
  all serving (services started via `setsid`/`disown`).
- Bus-node → WS → store → REST → dashboard-ready data path verified live.
- Remaining real-HW work tracked as PLANNED (never claimed implemented).

### Notes / decisions
- Camera frame streaming into the web UI (binary/video over WS) is deferred:
  the Bus Details camera tiles show live driver status/PLANNED placeholders only.
- DDS modifications observed in `git status` are the user's own pre-existing
  work; this project never writes into the DDS directory.

---

## INTERLUDE — Control Centre intelligence layers + Intercom (after Phase 9)

Between the bus-node phases and the FLEET-IQ live prototype, the Control
Centre grew substantially. Fully documented phase-by-phase in
`control_centre/IMPLEMENTATION_PLAN.md` (all ✅ COMPLETE):

- **Operator Intercom / call center** (Sep 5): shared in-app call store
  (`lib/callCenter.js` pub/sub), `CallButton` (instant direct connect to a
  bus), global `IncomingCall` banner on any page (accept/decline, 20 s
  auto-timeout), `CallCenter` page (`/calls`, URL-only), Web Speech (en-IN)
  + TTS full-duplex console, pinned call card on the dashboard.
- **10 intelligence phases** (Sep 5–6, see IMPLEMENTATION_PLAN.md): unified
  risk engine (6 segments, 0–100), temporal fatigue + PERCLOS driver model,
  AI intervention/actions layer, driver recovery + safety timeline, scenario
  simulator (6 scenarios, auto-expiry + rollback), predictive vehicle health
  (degradation + RUL), ETA/delay prediction, demand/boarding forecast, road
  risk intelligence (zones, route index, leg threats), polish.
- Fleet grew to **100 buses / 14 MTC corridors** (Chennai, e.g. `1A`, `70V`),
  tickets/revenue, boarding analytics, per-event operator review workflow.

---

## PHASE 10 — FLEET-IQ Live Prototype: webcam AI perception + mode switch ✅ DONE

### Goal
Turn the Control Centre from a pure simulator into a live webcam-AI
perception prototype ("FLEET-IQ"), switchable from the UI — simulation and
live prototype stay cleanly separated.

### What was created (`control_centre/backend/ai/` + frontend)
- `ai/camera_manager.py` — `CameraManager` singleton: opens the webcam **in the
  main process** (cv2.VideoCapture in Flask threads deadlocks), routes one
  webcam to one AI module at a time (driver/road/cabin), background
  capture+detect thread, annotated frames, base64 JPEG frames, per-slot
  detection results.
- `ai/driver/driver_drowsiness.py` — MediaPipe FaceLandmarker EAR/MAR/solvePnP
  head pose with Haar fallback, 60 s PERCLOS, eye closure/yawn/nod/pose-alert
  states (DDS logic).
- `ai/road/pothole_detector.py` — YOLO (`yolov8n.pt`) or contour fallback,
  3-frame temporal confirmation, 10 s event cooldown.
- `ai/cabin/cabin_detector.py` — honest placeholder; never fabricates
  detections until a real model exists.
- `ai/dds/` — `dds_process.py` (spawns the ORIGINAL DDS app as a subprocess,
  PID/uptime/status, clean shutdown) + `dds_log_reader.py` (parses DDS
  `src/logs/events_*.csv` / `summary_*.txt` → FLEET-IQ events).
- `server.py`: `--start-mode simulation|live`, `POST /api/mode/switch`
  (live: stop sim, clear store, auto-start camera; simulation: stop camera,
  fresh `FleetSimulator`), `/api/camera/*` + `/api/ai/*` endpoints, PROTO-001
  stub bus.
- Frontend: `lib/modeContext.jsx` (SIMULATION ↔ LIVE switcher in the header,
  live-status polling), `CameraFeed.jsx` `CameraControlPanel` (choose Driver
  DDS / Pothole / Cabin, start/stop) + `LiveCameraGrid` (2 s polling of
  `/api/camera/stream/<slot>`, annotated frame + metrics), `LiveFleet.jsx` /
  `BusDetails.jsx` PROTO-001 live sections.

### Verification
- Endpoints respond: `/api/camera/status`, `/api/camera/start`, `/api/camera/stream/<slot>`,
  `/api/ai/status`, `/api/mode`, `/api/live/status`. Frontend `npm run build`
  passes; live mode returns only PROTO-001 (simulator stopped).

---

## PHASE 11 — Original DDS embedded in the Live Prototype camera feed ✅ DONE

### Goal (explicit user requirement)
**NO new DDS page / nav item / route / dashboard.** The ORIGINAL DDS engine
must live INSIDE the existing Live Prototype view (`/fleet` in live mode and
`/fleet/PROTO-001`), directly on the existing camera feed — calibration,
monitoring, audio warning and events all on that one view. Simulation is
untouched.

### What changed
- `ai/driver/driver_drowsiness.py` — rewritten into a full DDS engine:
  - **Fixed bugs:** `mediapipe` was never imported while `mp.Image` was used
    (MediaPipe path silently failed → Haar only); cascade/model paths were
    hard-coded to `/home/rohith/Desktop/...` → now resolved relative to the
    file.
  - Phases `idle → calibrating → ready → monitoring`; **calibration** uses the
    original DDS math (5 s / 15 samples; `ear_thr = clamp(median_ear × 0.75,
    0.15, 0.30)`, `mar_thr = clamp(median_mar + 0.20, 0.40, 0.90)`); monitoring
    runs on real camera values with the calibrated thresholds.
  - Edge-triggered events into the existing FLEET-IQ event system:
    `DRIVER_DROWSINESS` (CRITICAL on drowsy start, WARNING for head nod/pose
    alert) + `DRIVER_ALERT` (CRITICAL, once per episode) with `bus_id:
    PROTO-001`, `camera_id: driver`, `data_source: live`, `simulation: False`.
  - **Audio warning:** loads the ACTUAL original DDS
    `bus_node.utils.alert_manager` (same tones/player detection, loops while
    drowsy, stops on recovery); `audio_triggered` counts severity transitions.
- `server.py`: `_proto_bus()` helper; `_setup_live_proto()` (PROTO-001 in the
  store + live-node registry + DDS event callback + 10 s heartbeat); `main()`
  live path clears the store (simulator never seeds); new endpoints
  `GET /api/dds/status`, `POST /api/dds/calibrate|start|stop|reset`
  (live-mode-only, auto-start the driver camera if needed).
- `ai/camera_manager.py`: now links the **shared** module singletons (API and
  capture loop act on the same engine instances — private instances meant
  calibration state never reached the frames); frame overlay shows real
  calibrated thresholds.
- Frontend (no new routes/nav): `api.js` DDS helpers; `CameraFeed.jsx`
  `DdsControlStrip` embedded under the camera tile (NOT CALIBRATED /
  CALIBRATING… samples+countdown / READY / MONITORING + Calibrate / Start
  Monitoring / Stop / Reset), left panel real EAR/MAR with calibrated
  thresholds + head pose/PERCLOS (fake Phone/Drink/Smoke chips removed),
  right panel real engine/audio/event status (fake tire/fuel/speed block
  removed), `ProtoEventFeed` reading the existing event system; wired into
  `LiveFleet.jsx` + both PROTO-001 sections of `BusDetails.jsx`.

### Verification (laptop webcam, real run)
- Calibration: **78 real samples → CALIBRATION COMPLETE, EAR thr 0.30**
  (0.75 × baseline), MAR thr 0.40.
- Monitoring: real EAR 0.40–0.52, MAR ~0.02–0.05, pitch/PERCLOS live,
  `engine_phase: monitoring`.
- A real `DRIVER_DROWSINESS` (WARNING, HEAD POSE ALERT) event was emitted to
  `/api/events?data_source=live` when the driver looked away.
- Audio: original AlertManager enabled; `tone_warning.wav` / `tone_critical.wav`
  regenerated in `bus_node/generated_audio/`; `aplay` speaker playback
  confirmed; warning loop triggered 3× on real head-pose alerts.
- Server runs detached (`setsid venv/bin/python server.py --start-mode live`)
  on 5001/8765, survives sessions; Vite on 5173.

### Notes / decisions
- The audible warning fires on a real drowsy episode (eyes closed > 1.3 s or
  PERCLOS breach); can be demoed by closing the eyes ~2 s in front of the
  camera.
- Cabin AI stays an honest placeholder; single webcam is assigned to one slot
  at a time until a 3-camera rig exists (Camera 0 → Driver, 1 → Cabin,
  2 → Road planned).
- Restart recipe (do NOT `pkill -f` a pattern that also appears in the
  invoking shell's own command line): `fuser -k 5001/tcp`, then
  `setsid venv/bin/python server.py --start-mode live </dev/null >/tmp/cc_live.log 2>&1 &`.

### Hotfix (same evening): "no face mesh / not smooth"
- **Root cause:** per-frame fallback to Haar when the FaceLandmarker missed a
  face → Haar hallucinates faces from the background (constant fake EAR 0.35,
  noisy MAR, pitch 0.0) and produced false `DROWSINESS (PERCLOS)` events;
  the unthrottled capture loop pegged CPU at ~193%.
- **Fix:** MediaPipe is now the primary AND only detector when available
  (no face → honest `NO FACE`; Haar only if MediaPipe is genuinely missing);
  `NO FACE` wipes the PERCLOS window; capture loop rate-capped (~30 fps,
  CPU 193% → ~40-84%); frontend stream polling 2 s → 1 s; server restarted
  with `PYTHONUNBUFFERED=1` so engine logs are visible.
- **Verified:** real mesh path (eyes 2, real pitch/yaw), calibration 79
  samples → EAR thr 0.271, live EAR 0.46 / MAR 0.01 / PERCLOS 0.008, no false
  events.

---
