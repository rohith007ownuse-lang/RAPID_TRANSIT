# SESSION CHANGELOG — Sep 6, 2026 (evening)

Complete record of every change made in this session (Original DDS embedded in
the FLEET-IQ Live Prototype + all hotfixes). Companion to `SESSION_RECALL.md`
(high-level memory) and `ai_urban_management.md` (phase log).

**Project root:** `/home/rohith/Desktop/AI_Urban_Intelligence_Platform/`

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