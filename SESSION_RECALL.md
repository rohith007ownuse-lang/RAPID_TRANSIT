# SESSION RECALL — AI Urban Intelligence Platform

> Durable memory file. Purpose: let a fresh session pick up instantly —
> what this project is, how it is structured, what was done in past
> sessions, and (most importantly) **what was done last time**.

---

## 1. What this project is

**AI-Powered Mobile Urban Intelligence Platform** — convert public-transport
buses into distributed mobile sensing nodes (driver safety, cabin safety,
road conditions, crash/impact, emergencies, load, vehicle health, fleet
location) that stream structured events to a **Control Centre** web dashboard.

- Everything today is **SIMULATED** (labelled `SIMULATION`) unless a live
  webcam node is streaming — the code paths for real hardware exist.
- **NOT** an automotive-certified safety system — a research/demo prototype.
- Canonical running log: `ai_urban_management.md` (phases 1–9).
- Master architecture plan: `PLAN.md`.
- Control Centre deep-dive: `URBAN_INTELLIGENCE_OVERVIEW.md`.
- Original DDS baseline is UNTOUCHED at `/home/rohith/Documents/D.D.S/DriverDrowsinessDetectionSystem`.

### Quick run commands
```bash
# Control Centre backend (REST :5001 + WS :8765)
cd control_centre/backend && venv/bin/python server.py

# Frontend (Vite dev, :5173, proxies /api to :5001)
cd control_centre/frontend && npm run dev

# Bus node (streams simulated live telemetry into dashboard)
python bus_node/main.py --headless --duration 30
```
Desktop launcher: `start.sh`. Ports: **API 5001, WS 8765, UI 5173**.

---

## 2. Repository layout (current)

```
AI_Urban_Intelligence_Platform/
├── PLAN.md / README.md / URBAN_INTELLIGENCE_OVERVIEW.md
├── ai_urban_management.md        # phase log (1–9)
├── SESSION_RECALL.md             # ← this file
├── config/system_config.json     # thresholds, sensors, cameras, bus params
├── bus_node/                     # Python code that runs "on each bus"
│   ├── main.py                   # full pipeline entry (Phase 8 integration)
│   ├── core/                     # fatigue_engine (brake RECOMMENDATION only), severity
│   ├── detectors/                # EAR, MAR, head_pose, face_detection (MediaPipe), object_detection(disabled)
│   ├── cameras/                  # camera_manager (DRIVER/CABIN/ROAD slots)
│   ├── sensors/                  # gps/imu/load_cell/microphone (simulation)
│   ├── ai_modules/               # cabin_ai, road_ai (PLANNED placeholders)
│   ├── event_fusion/             # event_fusion.py (crash/drowsy/overload/siren/pothole rules)
│   ├── data/                     # event_model.py, bus_state.py
│   ├── communication/            # websocket_client.py
│   ├── hardware/                 # serial_communicator (runtime-disabled)
│   └── utils/ models/ src/       # DDS-copied helpers + face_landmarker.task + yolov8n.pt
├── control_centre/
│   ├── backend/
│   │   ├── server.py             # Flask REST API (:5001) — mode switching + camera/AI endpoints
│   │   ├── simulator.py          # 100-bus Chennai MTC fleet sim (14 corridors)
│   │   ├── data_store.py         # in-memory thread-safe store + mode_state
│   │   ├── websocket_handler.py  # WS ingestion (:8765), adapt_bus_state, liveness watchdog
│   │   ├── risk_engine.py        # 6-segment risk score 0–100
│   │   ├── recommendations.py    # AI intervention/action layer
│   │   ├── scenarios.py          # REMOVED in Phase 3 cleanup (was: 6 scenarios w/ auto-expiry)
│   │   ├── predictive_health.py  # degradation + RUL estimates
│   │   ├── eta.py / demand.py / road_risk.py
│   │   ├── ai/                   # ★ FLEET-IQ live prototype (latest work)
│   │   │   ├── camera_manager.py # CameraManager singleton: 1 webcam → 1 AI module
│   │   │   ├── driver/driver_drowsiness.py  # MediaPipe + Haar, EAR/MAR/perclos/head-pose
│   │   │   ├── road/pothole_detector.py     # YOLO or contour fallback + temporal confirm
│   │   │   ├── cabin/cabin_detector.py      # honest placeholder (no fabricated detections)
│   │   │   └── dds/              # dds_process.py (spawn DDS subprocess), dds_log_reader.py
│   │   ├── cascades/             # haarcascade XMLs (fallback detection)
│   │   └── models/               # face_landmarker.task (MediaPipe)
│   └── frontend/                 # React 19 + Vite, react-leaflet, Recharts
│       └── src/
│           ├── App.jsx           # routes incl. /calls (Intercom, URL-only)
│           ├── api.js            # fetch client + usePoll
│           ├── lib/              # modeContext.jsx (SIMULATION↔LIVE), callCenter.js (pub/sub intercom)
│           ├── components/       # Layout, FleetMap, AlertFeed, ReviewStatus, CameraFeed,
│           │                     # CallButton, IncomingCall, BusRouteTracker, Gauge, UI
│           └── pages/            # Dashboard, LiveFleet, BusDetails, CallCenter, Incidents,
│                                 # RoadIntelligence, VehicleHealth, DriverSafety,
│                                 # LoadManagement, Analytics, Settings (11 pages)
├── arduino/                      # firmware (motor control disabled)
└── assets/ data/                 # map, audio tones, logs
```

---

## 3. How it fits together (data flow)

```
bus_node (real or simulated) ──WebSocket :8765──► Control Centre backend
   cameras → driver monitoring                    websocket_handler adapts payloads
   sensors → BusState → Event Fusion               → shared data_store
                                                   (live bus _live supersedes simulator)
   Browser (React :5173) ◄──REST /api/*── Flask :5001 ◄── data_store
```

- **SIMULATION mode**: `FleetSimulator` thread ticks 1×/s, 100 buses, events,
  potholes, ticketing, fatigue episodes, health, etc.
- **LIVE mode** (latest): simulator stopped, store cleared, webcam AI runs;
  a stub `PROTO-001` bus represents the live prototype; camera frames +
  detections served as base64 JPEG over REST.

---

## 4. Control Centre backend details

### REST API highlights (~30+ endpoints)
- **Core**: `/api/health`, `/api/overview`, `/api/buses[/<id>]`, `/api/events`
  (+ ack/review/resolve/status/bulk), `/api/road-defects`, `/api/analytics`,
  `/api/settings`
- **Intelligence**: `/api/risk`, `/api/buses/<id>/risk`, `/api/actions[/<id>/ack]`,
  `/api/actions/evaluate`, `/api/buses/<id>/timeline`, `/api/eta`, `/api/buses/<id>/eta`,
  `/api/demand`, `/api/buses/<id>/demand`, `/api/roads/risk`,
  `/api/buses/<id>/road-threats`, `/api/health/predictive`
- **Mode / live**: `/api/mode`, `/api/mode/switch`, `/api/live/status`
- **★ Camera / vision AI** (FLEET-IQ live prototype):
  - `GET /api/camera/status` — camera state, test slot, available cameras
  - `POST /api/camera/test-mode` `{slot}` — route webcam to driver|road|cabin
  - `POST /api/camera/start` (non-blocking), `POST /api/camera/stop`
  - `GET /api/camera/stream/<slot>` — base64 JPEG frame + detection overlay + detections
  - `GET /api/camera/detections/<slot>`
  - `GET /api/ai/status` — camera + driver + road + cabin status
  - `GET /api/ai/driver/state`, `GET /api/ai/pothole/stats`

### Mode switching (`POST /api/mode/switch`)
- **→ live**: stops simulator, clears buses/events/road-defects, auto-starts
  camera in a background thread (driver slot).
- **→ simulation**: stops camera, builds a fresh `FleetSimulator`, restarts it.

### WebSocket protocol (bus_node → CC)
`hello` | `bus_state` | `event` | `heartbeat` on `ws://:8765`; server replies
`ack`. Live buses `_live: true` **supersede** their simulated copy
(simulator skips them); stale > 30 s revert to simulator control.

---

## 5. Frontend details

- **11 pages**: Dashboard `/`, Live Fleet `/fleet`, Bus Details `/fleet/:busId`,
  Intercom `/calls` (not in nav), Incidents `/incidents`, Road Intelligence
  `/roads`, Vehicle Health `/health`, Driver Safety `/driver-safety`,
  Load Management `/load-management`, Analytics `/analytics`, Settings `/settings`.
- **Shared state**: `modeContext.jsx` (SIMULATION↔LIVE switcher in Layout,
  live-status polling when live) and `callCenter.js` (one in-app call store:
  operator→bus instant connect, bus→operator ringing banner on any page with
  20 s auto-timeout, transcript).
- **CameraFeed.jsx** (latest work): exports `CameraSlot`, `CameraControlPanel`
  (LIVE-only — pick Driver DDS / Pothole / Cabin, start/stop) and
  `LiveCameraGrid` (polls `camera/stream` every 2 s in live mode, shows the
  annotated frame + driver EAR/MAR/perclos/state, alert history counters).
- White/professional theme in `theme.css`; every page carries a SIMULATION
  badge (hidden/absent in live mode).

---

## 6. HISTORY — work done in earlier sessions (summary)

### bus_node phases (see ai_urban_management.md for full detail) — all ✅ DONE
1. **Phase 1** — Copied DDS driver-drowsiness stack into `bus_node/` without
   touching DDS; automatic braking removed → brake **recommendation** only.
2. **Phase 2** — Control Centre web UI (Flask + React), 10 pages, simulated.
3. **Phase 3** — Camera Manager: 3 slots, driver webcam active.
4. **Phase 4** — Sensor interfaces (GPS/IMU/load/mic) in simulation mode.
5. **Phase 5** — Event model + BusState manager.
6. **Phase 6** — Event Fusion Engine (crash, drowsy-while-moving, overload
   compound, siren edge-trigger, pothole dedup).
7. **Phase 7** — Bus-node ↔ Control Centre WebSocket link.
8. **Phase 8** — Full integration: cameras → monitoring → sensors → state →
   fusion → WS → dashboard (verified headless end-to-end).
9. **Phase 9** — Documentation & polish.

### Control Centre intelligence layers (see IMPLEMENTATION_PLAN.md) — ✅ all COMPLETE
- **Phase 1** Unified risk engine (6 segments, 0–100, editable weights)
- **Phase 2** Temporal fatigue + PERCLOS driver model
- **Phase 3** AI intervention / recommendation actions
- **Phase 4** Driver recovery detection + safety timeline
- **Phase 5** Scenario simulator (built, then REMOVED from the product in Phase 3 cleanup)
- **Phase 6** Predictive vehicle health (degradation + RUL)
- **Phase 7** ETA / delay prediction
- **Phase 8** Demand / boarding forecasting
- **Phase 9** Road risk intelligence (zones, route index, leg threats)
- **Phase 10** Polish (DriverSafety/LoadManagement wired into routes, README/AGENTS updates)

---

## 7. ★ LAST SESSION (Sep 6) — FLEET-IQ Live Prototype

**Theme:** turn the Control Centre from a pure simulator into a live
webcam-AI perception prototype ("FLEET-IQ"), switchable from the UI.

### What was added
1. **`control_centre/backend/ai/` package** (all lazy-loaded, all singletons):
   - `camera_manager.py` — `CameraManager`: opens the webcam **in the main
     process** (cv2.VideoCapture in Flask threads deadlocks), single-camera
     test mode routes frames to one AI module, background capture+detect
     thread, annotated frames, per-slot detection results, base64 JPEG frames.
   - `driver/driver_drowsiness.py` — `DriverDrowsinessDetector`: mirrors DDS —
     MediaPipe FaceLandmarker EAR/MAR/solvePnP head pose with Haar cascade
     fallback, 60 s PERCLOS, eye-closure/yawn/nod/pose-alert state machine
     (`NORMAL`…`DROWSINESS DETECTED`), drowsy/attention %, fatigue alert count.
   - `road/pothole_detector.py` — `PotholeDetector`: YOLO when model loads
     (`yolov8n.pt`), else contour fallback; 3-frame temporal confirmation,
     10 s event cooldown, stats, overlays, POTHOLE event callback stub.
   - `cabin/cabin_detector.py` — honest **placeholder**; refuses to fabricate
     detections until a real model is implemented.
   - `dds/` — `dds_process.py` (spawns the **original DDS app** as a
     subprocess with its own venv/python, PID/uptime/status, clean
     SIGTERM→SIGKILL shutdown) and `dds_log_reader.py` (parses DDS
     `src/logs/events_*.csv` + `summary_*.txt`, maps DDS events →
     `DRIVER_DROWSINESS` / `DRIVER_DISTRACTION` / `DRIVER_EMERGENCY_STOP` /
     `DDS_*`, severity assignment, `bus_id: PROTO-001`).
2. **server.py**:
   - `--start-mode simulation|live` CLI flag; camera pre-open at startup.
   - Mode switch endpoint wiring (stop sim vs stop camera + fresh sim).
   - Full camera/AI REST surface (see §4) + `PROTO-001` stub bus with
     `data_source: "live"`, `live: true`.
   - `_is_proto()` guards so risk/other endpoints return sensible live stubs.
3. **frontend**:
   - `lib/modeContext.jsx` — global SIMULATION↔LIVE mode state, `switchMode()`,
     live-status polling (3 s) when live.
   - `Layout.jsx` — mode switcher pill in the header (DATA SOURCE: Simulation | Live).
   - `CameraFeed.jsx` — `CameraControlPanel` (choose Driver/Pothole/Cabin,
     start/stop) + `LiveCameraGrid` (2 s polling of `/api/camera/stream/<slot>`,
     annotated frame display, driver metrics, alert history: eyeClosures /
     yawns / fatigueAlerts / avgAttention / perclosAvg).
   - `api.js` — `getMode`, `switchMode`, `cameraStatus`, `setTestMode`,
     `startCamera`, `stopCamera`, `cameraStream`, `liveStatus`, `aiStatus`.
   - `LiveFleet.jsx` — shows PROTO-001 camera system section in live mode.
4. **requirements.txt** (backend) — added optional AI vision deps:
   opencv-python, numpy, ultralytics, mediapipe (marked "optional, for live
   prototype").

### Key gotchas recorded for next time
- `cv2.VideoCapture(0)` must be opened in the **main process** (via
  `open_shared_camera()`) or Flask threads deadlock — CameraManager reuses
  that pre-opened capture.
- Driver detector hard-codes paths to `/home/rohith/Desktop/AI_Urban_Intelligence_Platform/...`
  for cascades + `models/face_landmarker.task` — these match this machine
  but are NOT portable.
- Cabin AI deliberately returns no detections until a real model is wired in
  (honesty rule: no fabricated accuracy).
- DDS subprocess spawn + log-reader only work if the DDS project exists at
  its hard-coded path; both fail gracefully otherwise.
- Mode switch clears simulated data — switching back to simulation builds a
  fresh `FleetSimulator` (deterministic seed).

### Status
- Backend + frontend compile (verified via earlier typecheck/build passes).
- Live camera endpoints are wired but **not yet re-verified in this session**
  — natural next step is to boot backend with `--start-mode live` (or flip
  the UI switcher), confirm `/api/camera/status`, `/api/camera/stream/driver`,
  `/api/ai/status` return real frames, and screenshot the Live Camera Grid.

---

## 7b. ★ THIS SESSION (Sep 6, late) — Original DDS embedded in the Live Prototype feed

**Requirement:** NO new DDS page / nav item / route / dashboard. The ORIGINAL DDS
engine must live INSIDE the existing Live Prototype view (`/fleet` in live mode,
and `/fleet/PROTO-001`), directly on the existing camera feed, with real
calibration + monitoring + audio warning + events. Simulation stays untouched.

### Backend
- **`ai/driver/driver_drowsiness.py`** rewritten into a real DDS engine:
  - **Fixed bugs:** `mediapipe` was never imported while `mp.Image` was used
    (MediaPipe path silently died); cascade/model paths were hard-coded to
    `/home/rohith/Desktop/...` — now computed relative to `__file__`.
  - **Phases:** `idle → calibrating → ready → monitoring`.
  - **Calibration** (original DDS math): 5 s / 15 samples; collects real
    EAR/MAR/pitch from the live pipeline;
    `ear_thr = clamp(median_ear*0.75, 0.15, 0.30)`, `mar_thr = clamp(median_mar+0.20, 0.40, 0.90)`.
  - **Monitoring** uses the calibrated thresholds (real values, never hard-coded).
  - **Events** (edge-triggered, into the existing event system):
    `DRIVER_DROWSINESS` (CRITICAL on drowsy start, WARNING for head nod/pose
    alert) + `DRIVER_ALERT` (CRITICAL, once per episode) with
    `bus_id: PROTO-001`, `camera_id: driver`, `data_source: live`,
    `simulation: False`, real measurements in `additional_data`.
  - **Audio:** loads the ACTUAL original DDS `bus_node.utils.alert_manager`
    (same tones/player detection, loops while drowsy, stops on recovery).
  - `get_status()` drives the UI (phase, calibration progress, thresholds,
    monitoring seconds, audio state, event count).
- **`server.py`:** `_proto_bus()` stub helper; `_setup_live_proto()` registers
  PROTO-001 in the store + live-node registry + wires the DDS event callback;
  `main()` live path clears the store (simulator never seeds in live mode);
  new endpoints `GET /api/dds/status`, `POST /api/dds/calibrate|start|stop|reset`
  (all live-mode-only; auto-start the driver camera if needed).
- **`ai/camera_manager.py`:** frame overlay now prints real calibrated
  EAR/MAR thresholds instead of hard-coded 0.23.

### Frontend (no new pages/routes — all inside the existing components)
- **`api.js`:** `ddsStatus / ddsCalibrate / ddsStart / ddsStop / ddsReset`.
- **`CameraFeed.jsx`:**
  - `DdsControlStrip` — embedded under the camera tile in the driver view:
    DDS STATUS pill (NOT CALIBRATED / CALIBRATING… with samples+countdown /
    READY / MONITORING), real calibrated thresholds, and
    `[⚙ Calibrate] [▶ Start Monitoring] [■ Stop] [↺ Reset]`.
  - `DDSLeftPanel` — real EAR/MAR (with calibrated thresholds), head pose,
    eye closure, PERCLOS, fatigue/attention, yawns, gaze; fake `Phone/Drink/Smoke`
    chips removed; `—` shown until the engine produces real data.
  - `DDSRightPanel` — fake `Tire Pressure 32 PSI / Fuel 100% / Speed 0` block
    replaced with real DDS engine status (phase, monitoring seconds, original
    audio-warning state, events emitted, calibrated thresholds).
  - `ProtoEventFeed` — reads the EXISTING FLEET-IQ event system
    (`/api/events?data_source=live`, filtered to PROTO-001); shows latest
    drowsiness events with severity/note/time.
- **`LiveFleet.jsx` + `BusDetails.jsx`:** `ProtoEventFeed` rendered in the
  Live Prototype sections (`/fleet` live block + both PROTO-001 camera
  sections in BusDetails). No new routes, no nav changes.

### Verification
- Backend `py_compile` OK; engine lifecycle smoke-tested (calibrate/start/stop/
  reset); server started with `--start-mode live` returns only `PROTO-001` in
  `/api/buses`; `/api/dds/*` all respond correctly; events endpoint live-filter
  works. Frontend `npm run build` passes.

### Laptop webcam run (VERIFIED, Sep 6 23:1x)
- **Bug found + fixed:** `CameraManager._ensure_ai_modules()` created PRIVATE
  detector instances while the API controls the module singletons — calibration
  state never reached the frames (`engine_phase: idle` after calibrate). Fixed:
  camera manager now links the shared `driver_detector` / `pothole_detector` /
  `cabin_detector` singletons.
- Added a 10 s heartbeat in `_setup_live_proto()` so PROTO-001 stays
  "connected" in the header even off the prototype page.
- `audio_triggered` now counts severity TRANSITIONS, not frames.
- Live verification on the HP True Vision HD camera:
  - Calibration: **78 real samples → CALIBRATION COMPLETE, EAR thr 0.30**
    (0.75 × baseline), MAR thr 0.40 (default floor).
  - Monitoring: real EAR 0.40–0.52, MAR ~0.02–0.05, pitch/PERCLOS live,
    `state NORMAL`, `engine_phase: monitoring`.
  - Real event emitted: `DRIVER_DROWSINESS` (WARNING, HEAD POSE ALERT) appeared
    in `/api/events?data_source=live` when the driver looked away.
  - Audio: original DDS `AlertManager` enabled; `tone_warning.wav` /
    `tone_critical.wav` regenerated in `bus_node/generated_audio/`; `aplay`
    speaker playback confirmed; warning loop triggered on real head-pose
    alerts (counter went 0→3 during the test).
- Server runs detached (`setsid ... --start-mode live`) on 5001/8765 and
  survives; Vite still on 5173. Restart recipe: kill by port
  (`fuser -k 5001/tcp`), then
  `setsid venv/bin/python server.py --start-mode live </dev/null >/tmp/cc_live.log 2>&1 &`
  (do NOT `pkill -f` a pattern that appears in the shell's own command line).

### Hotfix (same evening): "no face mesh / not smooth" complaint
- **Root cause:** when the FaceLandmarker found no face in a frame, the code
  fell back to **Haar per-frame** — and Haar hallucinates faces from the
  background, producing constant fake EAR (0.35), noisy MAR, pitch locked at
  0.0, and false `DROWSINESS (PERCLOS)` events. The unthrottled capture loop
  also pegged the CPU at ~193% → stutter.
- **Fix (driver_drowsiness.py):** MediaPipe is now the PRIMARY and ONLY
  detector when available — no face → honest `NO FACE` (never Haar garbage);
  Haar is used only when MediaPipe is genuinely unavailable. `NO FACE` also
  wipes the PERCLOS window so stale closure flags can't fire false alarms.
- **Fix (camera_manager.py):** capture loop rate-capped (~30 fps max) — CPU
  dropped 193% → ~40% idle / ~84% monitoring.
- **Fix (CameraFeed.jsx):** stream polling 2 s → 1 s for a smoother feed.
- Restart with `PYTHONUNBUFFERED=1` so engine prints are visible in the log.
- Verified on the webcam: real mesh path (`eyes_detected: 2`, real pitch/yaw),
  calibration 79 samples → EAR thr 0.271, live EAR 0.46 / MAR 0.01 / pitch
  −3.6 / PERCLOS 0.008, monitoring clean, 0 false events.

### Hotfix 2: mesh not visible in the streamed frame
- **Root cause:** `CameraManager._run_detection` copied the display frame
  BEFORE running detection, so the mesh the detector drew on the raw frame
  never landed on the displayed copy (only the text overlay did).
- **Fix:** copy the frame AFTER detection so detector overlays (mesh, mouth
  points) appear in `/api/camera/stream/<slot>`; mesh lines thickness 1 → 2
  so they survive JPEG compression.
- **Verified pixel-level:** streamed frame now contains ~2,900 green mesh
  pixels + ~290 red mouth-point pixels (was 0); EAR 0.42–0.47 / MAR
  0.02–0.05 stable across samples.

### Hotfix 3: pages "not opening" (500s from the PROTO-001 stub)
- **Root cause:** the PROTO-001 stub bus was schema-invalid → `/api/risk`,
  `/api/eta`, `/api/demand`, `/api/buses/PROTO-001/{risk,eta,demand,
  road-threats}` all 500'd (Dashboard/BusDetails broke): wheels were dicts
  but the risk engine + BusDetails expect PSI **numbers**; `journey.next_index`
  was `None` (demand/road-risk slice with None → TypeError); `journey.stops`
  was empty (eta `stops[-1]` → IndexError).
- **Fix:** `_proto_bus()` now returns a fully valid bus — numeric wheels,
  real 4-stop PROTO journey (Koyambedu CMBT → Saidapet), int next_index,
  `route_code`, `vehicle` dict; plus defensive guards in `eta.py` /
  `demand.py` / `road_risk.py` (empty stops → empty result, None next_index
  → current+1) per the "never crash a tick" rule.
- **Verified:** all 21 live-mode endpoints return 200.

## 8. Honesty rules (always)

1. Simulated values are **never** presented as real measurements; `SIMULATION`
   badge + `simulation: true` everywhere.
2. No accuracy/precision/F1/FPS/dataset claims unless measured.
3. Load/weight values (tare 11 t, GVW ~16–17 t, payload 6 t) are project
   assumptions, not legal/validated figures.
4. Real-HW features stay labelled PLANNED until actually implemented.

## 9. Where to pick up next time
- **Run it on the laptop with the webcam** (this shell had no camera):
  `venv/bin/python server.py --start-mode live` + `npm run dev`, flip to
  LIVE PROTOTYPE, click CALIBRATE (face in frame 5 s), START MONITORING,
  confirm EAR/MAR/perclos move in real time and the original audio warning
  plays on a simulated drowsy state; screenshot the page.
- Optional: expose the DDS subprocess control + log-reader (`ai/dds/*`) as UI
  buttons/panel, and wire a `DRIVER_DISTRACTION` path if phone/drink detection
  is ever implemented (cabin/road modules remain honest placeholders).
- Update `ai_urban_management.md` / READMEs with the FLEET-IQ live-prototype
  phase (both the camera/AI endpoints work and this DDS-embedding pass).