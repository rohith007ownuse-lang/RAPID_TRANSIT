# SESSION CHANGELOG — Sep 23, 2026

Gap-closure roadmap Phases 10–15: mobile urban sensing (vehicle detection +
ByteTrack counting, congestion heat map, OD analytics, pedestrian/VRU
detection, edge AI on the bus node). All source-honest (MODEL / HEURISTIC /
SIMULATION), 804/804 tests, frontend builds green.

## Phase 10 — Traffic detection verification ✅
- Verified `ai/road/traffic_detector.py` (YOLOv8n COCO + honest MODEL source),
  `ai/camera_manager.py`, `server.py`, `routes.py` compile; frontend builds.
- `yolov8n.pt` auto-downloads on first `load_model()` (network required; does
  not touch `ai/road/models/best.pt`). `/api/traffic/stats` route registered.

## Phase 11 — ByteTrack vehicle tracking ✅
- `traffic_detector.py`: `model.track(persist=True, tracker="bytetrack.yaml")`
  every 8 frames with carry-forward (`_last_tracked`), `_seen_track_ids`,
  `_total_unique_all_time`, per-class uniques, tracking-active flag.
- `server.py` `_traffic_event_callback` persists `unique_vehicles`,
  `total_unique_vehicles`, `tracking_active` onto `bus["traffic"]`.
- Live Fleet traffic card shows Unique (ByteTrack) + Cumulative Unique +
  tracking-active source label.

## Phase 12 — Congestion heat map ✅
- New `backend/congestion_heatmap.py`: singleton grid (`CELL_DEG=0.004`),
  moving=1.0 / congested(<15km/h)=3.0 weights, EMA smoothing, 300 s age-out.
- `server.py` `_start_traffic_monitor` → `congestion_heatmap.update(buses)`.
- Route `/api/traffic/heatmap`; `api.trafficHeatmap`; `FleetMap` `heatmap` prop
  renders blue→amber→red cells + tooltip; Live Fleet legend.

## Phase 13 — Origin–Destination analytics ✅
- New `backend/od_analytics.py`: `compute_od()` gravity-style downstream
  apportionment of `boarding_by_stop_hour` (HEURISTIC, honest caveat).
- Route `/api/od/analytics`; `api.odAnalytics`; Analytics page OD card
  (top-12 pairs, riders/buses/routes KPIs) polled every 15 s.

## Phase 14 — Pedestrian / vulnerable-road-user detection ✅
- New `backend/ai/road/pedestrian_detector.py`: COCO person (class 0),
  conf ≥0.35, ByteTrack on 8-frame cadence, module-level `_near_roadway`
  bbox-geometry heuristic (bottom 55% + height ≥18% of frame), honest
  PEDESTRIAN_PRESENCE events (never on absence, no age/group inference).
- `ai/camera_manager.py` runs the ROAD-slot pedestrian pass every 6 frames;
  redraw overlay splits pedestrian detections; `server.py`
  `_pedestrian_event_callback` persists `bus["pedestrians"]`.
- Route `/api/pedestrian/stats`; `api.pedestrianStats`; Live Fleet card.

## Phase 15 — Edge AI on the bus node ✅
- New `bus_node/ai_modules/edge_traffic_detector.py`: runs YOLOv8 COCO +
  ByteTrack ON the bus, streams only derived `TRAFFIC_COUNT` counts/events over
  the existing WS client (no raw frames → bandwidth-minimized), throttled to
  ~1 report / infer interval, honest no-op when the ROAD camera is a
  placeholder (never fabricates a count), `edge: True` + MODEL source labels.
- `bus_node/main.py`: `--edge-traffic` flag opens a real ROAD camera when a
  device index resolves, wires `frame_source → EDGE detector → client.send_event`,
  stops cleanly in `finally`.
- Backend WS handler (`websocket_handler.py`) already accepts `{"type":"event"}`
  with `event_type == "TRAFFIC_COUNT"` → `store.add_event` (no change needed).
- 6 new tests in `tests/test_traffic_pedestrian_od.py` (source honesty,
  heatmap weights, OD empty-source honesty, pedestrian geometry).

## Verification
- Backend: `venv/bin/python -m pytest -q` → **804 passed**.
- Frontend: `npm run build` → green.
- All new modules compile (`traffic_detector`, `pedestrian_detector`,
  `congestion_heatmap`, `od_analytics`, `bus_node/main.py`,
  `edge_traffic_detector`); road detectors linked OK.
- Endpoints return 200: `/api/traffic/stats`, `/api/traffic/heatmap`,
  `/api/pedestrian/stats`, `/api/od/analytics` (content populates on sim
  warm-up; heatmap/OD content needs running simulator data).

# SESSION CHANGELOG — Sep 13, 2026

Fleet error budget (10 of 300 vehicles) + traffic red-alert water-drop ripples
with 500 m super-hotspot merge + patent doc refresh + orphaned-alarm audio fix.

## Audio: "sound plays without starting Rapid Transit" — ROOT-CAUSED & FIXED
- Symptom: `bash -c while true; do aplay tone_critical.wav; done` loops kept
  playing after Rapid Transit exited (orphaned alarms).
- Root causes: (a) alarm is an infinite bash loop; when the backend died the
  daemon thread that would call stop() died silently, leaving the loop;
  (b) `feature_toggles.json` had `audio_alerts: true`, overriding the
  documented `AlertManager.muted = True` kill-switch at runtime; (c) stray-
  loop cleanup only ran when muted, so (b) also disabled the cleanup.
- Fixes: `feature_toggles.json`/`feature_toggles.py` → `audio_alerts: false`
  (default OFF); `alert_manager.py` hardened — stray-loop sweep at EVERY
  construction + 15 s daemon watchdog + process-group kill (SIGTERM→SIGKILL,
  `start_new_session=True`) in `stop()`.
- Verified: 45 s of running server with DDS firing WARNING/CRITICAL → 82 mute
  decisions logged, zero `aplay`/loop processes; 754/754 tests pass.

## Backend
- `simulator.py` — `NUM_BUSES = 300`; error budget: `DRIVER_ATTENTION_MAX = 5` +
  `VEHICLE_ATTENTION_MAX = 5` (`_prone` / `_attention` sets, every 30th service,
  no overlap). Non-attention vehicles stay `NORMAL` (transient warnings
  self-heal, vibration mean-reverts); `_attention` marker stored on each bus.
- `predictive_health.py` — wear-rate budget: healthy-vehicle tyre/vibration/
  energy counters decay to healthy baseline (attention vehicles still degrade);
  harsh-braking increment scaled to its thresholds (was +1.0 → instant CRITICAL
  on every vehicle — the root cause of fleet-wide anomaly spam); healthy rate
  0.01/0.04 vs decay −0.02. `generate_health_events()` gated to attention
  vehicles + live nodes; per-(bus, component) 10-min alert cooldown map.
- `traffic_engine.py` — 500 m super-hotspot merge: ≥3 active hotspots within
  500 m (union-find on centroids) → ONE CRITICAL zone (unioned buses, peak
  duration, `radius_m: 500`, member ids); `analytics()` exposes
  `super_hotspots`/`super_count`.
- `server.py`, `routes.py`, `data_source_manager.py` — "300 buses" strings.

## Frontend
- `FleetMap.jsx` — red alerts render as water-drop ripples (drop core + 3
  staggered expanding circular rings, CSS transform keyframes); merged
  super-hotspots render as one big red circular waveform (500 m zone circle +
  3 large slow waves + glowing core, CRITICAL tooltip).
- `Layout.jsx` (ESTIMATED · 300 buses), `FeatureToggles.jsx`.

## Docs
- `patent/generate_rapid_tracker_doc.py` + regenerated `.docx` — 300-vehicle
  scale, 10-vehicle error budget, super-hotspot merge + ripple visualisation
  (§14.20, §14.23, objectives, observations, config tables).
- `PROJECT_CONTEXT.md` — fleet scale + error budget documented.

## Verification
- 754/754 backend tests pass; `npm run build` clean.
- Live run: 300 buses; all new events over 90 s came ONLY from the 10
  attention vehicles; super-hotspot merge unit-verified (4 zones → 1 CRITICAL).

---

# SESSION CHANGELOG — Sep 6, 2026 (evening)

Complete record of every change made in this session (Original DDS embedded in
the FLEET-IQ Live Prototype + all hotfixes). Companion to `SESSION_RECALL.md`
(high-level memory) and `ai_urban_management.md` (phase log).

**Project root:** `/home/rohith/Desktop/Rapid-Tracker/`

---

## 1. Mission (user requirement, verbatim summary)

**NO new DDS page / nav item / route / dashboard.** The ORIGINAL DDS driver-
monitoring engine must live INSIDE the existing Live Prototype view
(`/fleet` in live mode and `/fleet/PROTO-001`), directly on the existing
camera feed — with real calibration, monitoring, audio warning and events all
on that one view. Simulation mode stays untouched.

---

## 2. Files changed

### Backend — `control_centre/backend/`

| File | Change |
|---|---|
| `ai/driver/driver_drowsiness.py` | **Rewritten** into a real DDS engine (see §3). |
| `ai/camera_manager.py` | 4 fixes: link shared module singletons (was private instances → calibration state never reached frames); frame overlay shows real calibrated thresholds; annotated frame copied AFTER detection so the face mesh appears in the stream; capture loop rate-capped ~30 fps. |
| `server.py` | `_proto_bus()` + `PROTO_STOPS` (fully valid stub bus); `_setup_live_proto()` (store upsert + live-node registry + DDS event callback + 10 s heartbeat); `_dds_event_callback()`; `GET /api/dds/status` + `POST /api/dds/calibrate\|start\|stop\|reset`; `main()` live path clears the store (simulator never seeds in live mode). |
| `eta.py` | Defensive guard: empty `journey.stops` → `{"etas": [], "delay_summary": "NO_ROUTE"}`; `None` `next_index` → `current_index + 1`. |
| `demand.py` | Defensive guard: empty stops → `[]`; `None` `next_index` → `current_index + 1`. |
| `road_risk.py` | Defensive guard: empty stops or bad `next_index` → `[]`. |

### Frontend — `control_centre/frontend/src/`

| File | Change |
|---|---|
| `api.js` | Added `ddsStatus`, `ddsCalibrate`, `ddsStart`, `ddsStop`, `ddsReset`. |
| `components/CameraFeed.jsx` | Added `DdsControlStrip` (embedded under the camera tile: phase pill + calibration progress + Calibrate / Start Monitoring / Stop / Reset), `ProtoEventFeed` (reads existing `/api/events?data_source=live` for PROTO-001); `DDSLeftPanel` → real EAR/MAR with calibrated thresholds + head pose/eye closure/PERCLOS/fatigue/attention/yawns/gaze (fake Phone/Drink/Smoke chips removed, `—` until real data); `DDSRightPanel` → real engine/audio/event status (fake tire/fuel/speed block removed); `LiveCameraGrid` polls stream + DDS status every **1 s** (was 2 s). |
| `pages/LiveFleet.jsx` | Renders `<ProtoEventFeed />` in the Live Prototype block. |
| `pages/BusDetails.jsx` | Renders `<ProtoEventFeed />` in both PROTO-001 camera sections. |

### Docs

| File | Change |
|---|---|
| `SESSION_RECALL.md` | Created + updated with all phases/hotfixes. |
| `ai_urban_management.md` | Added Interlude (CC intelligence layers + Intercom), PHASE 10 (FLEET-IQ live prototype), PHASE 11 (DDS embedded in the feed) + hotfix notes. |
| `README.md` (root) | Status table (live prototype + DDS rows), layout (`backend/ai/`), LIVE PROTOTYPE run section. |
| `SESSION_CHANGELOG.md` | **This file.** |

---

## 3. The DDS engine (`ai/driver/driver_drowsiness.py`)

- **Phases:** `idle → calibrating → ready → monitoring` (start/stop/reset via API).
- **Detection (original DDS):** MediaPipe FaceLandmarker EAR/MAR/solvePnP head
  pose (mesh drawn on the frame, thickness 2), 60 s PERCLOS window, eye
  closure / yawn / head nod / head-pose alert state machine, severity per
  `fatigue_engine.py`.
- **Calibration (original DDS math):** 5 s / 15 samples, collects real
  EAR/MAR/pitch; `ear_thr = clamp(median_ear × 0.75, 0.15, 0.30)`,
  `mar_thr = clamp(median_mar + 0.20, 0.40, 0.90)`.
- **Monitoring** uses the calibrated thresholds (never hard-coded values).
- **Events** (edge-triggered, into the EXISTING FLEET-IQ event system):
  `DRIVER_DROWSINESS` (CRITICAL on drowsy start, WARNING for head nod/pose
  alert) + `DRIVER_ALERT` (CRITICAL, once per episode, `cabin_action:
  AUDIO_WARNING`) with `bus_id: PROTO-001`, `camera_id: driver`,
  `data_source: live`, `simulation: False`, real measurements in
  `additional_data`.
- **Audio warning:** loads the ACTUAL original DDS
  `bus_node.utils.alert_manager` (same tones + player detection; loops while
  drowsy, stops on recovery; `audio_triggered` counts severity transitions).
- **Fixed bugs found along the way:**
  1. `mediapipe` was never imported while `mp.Image` was used → the MediaPipe
     path silently died (Haar-only). Fixed.
  2. Cascade/model paths were hard-coded to `/home/rohith/Desktop/...` →
     now resolved relative to `__file__`.
  3. Haar per-frame fallback **hallucinated faces** from the background
     (constant fake EAR 0.35, noisy MAR, pitch 0.0, false DROWSINESS
     (PERCLOS)). MediaPipe is now the PRIMARY AND ONLY detector when
     available; no face → honest `NO FACE`; Haar only if MediaPipe is
     genuinely missing. `NO FACE` also wipes the PERCLOS window.

### API (all live-mode-only except status)

```
GET  /api/dds/status          # phase, calibration progress, thresholds, monitoring, audio
POST /api/dds/calibrate       # start 5 s baseline (auto-starts driver camera)
POST /api/dds/start           # begin monitoring (calibrated thresholds)
POST /api/dds/stop            # stop monitoring (audio silenced, camera stays)
POST /api/dds/reset           # idle, clears calibration + monitoring
```

---

## 4. Verification results (real webcam run)

- **Calibration:** 79 real samples → `CALIBRATION COMPLETE`, **EAR thr 0.271**
  (0.75 × personal baseline), MAR thr 0.40.
- **Face mesh in the streamed frame:** pixel-verified — ~2,900 green mesh px +
  ~290 red mouth-point px (was 0 before the copy-after-detection fix).
- **Stable real values:** EAR 0.420–0.472, MAR 0.021–0.046, pitch ±real
  values, `eyes_detected: 2`, state NORMAL.
- **Real event emitted:** `DRIVER_DROWSINESS` (WARNING, HEAD POSE ALERT) in
  `/api/events?data_source=live` when the driver looked away.
- **Audio:** original AlertManager enabled; `tone_warning.wav` /
  `tone_critical.wav` regenerated in `bus_node/generated_audio/`; `aplay`
  speaker playback confirmed; warning loop triggered 3× on real head-pose
  alerts.
- **All 21 live-mode endpoints return 200** (risk, eta, demand, road-threats,
  bus detail, camera, ai, dds …) — after the PROTO-001 stub schema fix.
- **CPU:** 193% → ~32% idle / ~84% during monitoring (throttled capture loop).
- **Frontend:** `npm run build` passes; Vite dev server on :5173.

---

## 5. How to run / restart

```bash
# Frontend (already running, hot-reloads)
cd control_centre/frontend && npm run dev          # :5173

# Backend (live prototype mode; detached so it survives)
cd control_centre/backend
fuser -k 5001/tcp                                   # kill old instance by port
PYTHONUNBUFFERED=1 setsid venv/bin/python server.py --start-mode live \
    </dev/null >/tmp/cc_live.log 2>&1 &

# In the UI: DATA SOURCE → ● LIVE PROTOTYPE → Live Fleet
# (or /fleet/PROTO-001) → driver feed → ⚙ Calibrate → ▶ Start Monitoring
```

**Operational notes:**
- Restart by port (`fuser -k 5001/tcp`), NOT `pkill -f` — a pattern that
  appears in the invoking shell's own command line kills the shell itself.
- `PYTHONUNBUFFERED=1` so `[driver_dds]` prints are visible in the log
  (redirected stdout is block-buffered otherwise).
- Single webcam = one perception slot at a time (Driver DDS / Pothole / Cabin)
  from the existing Camera AI Perception panel.
- Browser hard-refresh (`Ctrl+Shift+R`) after backend restarts.

---

## 6. Honesty rules (unchanged)

- Simulated values are never presented as real; `simulation: false` on all
  live DDS events/data.
- Cabin AI remains an honest placeholder (never fabricates detections).
- No accuracy/precision/F1/FPS claims unless measured.
---

## 7. Pothole detection — trained YOLO model (Option A)

- Added trained pothole model `ai/road/models/best.pt` (YOLOv8s, fine-tuned on
  pothole datasets, from `peterhdd/pothole-detection-yolov8` on Hugging Face,
  AGPL-3.0).
- Installed `ultralytics` + CPU torch in the backend venv.
- `pothole_detector.py`: `POTHOLE_MODEL_PATH` now points at the local trained
  model; detection source is `MODEL` when it loads (contour HEURISTIC remains
  the fallback); added `set_event_callback()` / `set_gps_source()`; event
  confidence is always a real number; pothole class label always shown as
  "pothole".
- `server.py`: `_road_event_callback()` wired in `_setup_live_proto()` —
  confirmed potholes now land in the event system, the road-defect map
  (`link_road_defect`), Road Intelligence zones, and alert subscribers.
- `websocket_handler.py`: `link_road_defect` tolerates `confidence=None`.
- Verified: 739/739 tests pass; real pothole image → 1 detection (MODEL,
  conf 0.461); no-road image → 0 detections; temporal confirmation fires the
  POTHOLE event. Backend restarted; live mode switch in the UI activates the
  engine.

---

## 8. Cabin hazard detection — fire & smoke (trained D-Fire model)

- Added trained fire/smoke model `ai/cabin/models/best.pt` (YOLOv8n,
  fine-tuned on the D-Fire dataset, from `rabahdev/fire-smoke-yolov8n` on
  Hugging Face).
- `cabin_detector.py` rewritten from an honest stub into a real detector:
  fire + smoke detection with temporal confirmation (2 frames fire, 3
  smoke), 10 s per-type cooldown, `CABIN_FIRE` (CRITICAL) and `CABIN_SMOKE`
  (HIGH) events, red/slate bounding-box overlay, `set_event_callback()`.
  No fabricated detections when the model is unavailable.
- `server.py`: `_cabin_event_callback()` wired in `_setup_live_proto()` —
  confirmed hazards land in the event system with bus GPS and keep the node
  alive.
- `camera_manager.py`: cabin branch now draws the detector overlay on the
  stream (fire/smoke boxes visible on the live feed), matching the road
  branch.
- `CameraFeed.jsx`: cabin panel shows a live hazard banner (FIRE / SMOKE /
  no hazards) above the occupancy stats.
- Verified: real fire image → `fire` conf 0.452, CRITICAL CABIN_FIRE event on
  2nd frame; non-fire image → 0 detections; 739/739 tests pass; backend +
  frontend rebuilt and healthy.
