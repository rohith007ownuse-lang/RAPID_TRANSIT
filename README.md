# AI-Powered Mobile Urban Intelligence Platform

Convert public-transport buses into distributed mobile sensing and intelligence nodes.

Each bus continuously collects driver safety, cabin safety, road conditions, crash/
impact events, emergency situations, vehicle load, vehicle health, and fleet location,
then sends structured events to a centralized Control Centre / Urban Intelligence Dashboard.

> **Research & demonstration prototype.** This is NOT an automotive-certified safety system.

---

## Status Legend

| Label | Meaning |
|-------|---------|
| **IMPLEMENTED** | Functionality currently working. |
| **PROTOTYPE** | Working in simulation/demo only; real hardware pending. |
| **PLANNED** | Architecture reserved; not yet functional. |

## Current Status

| Module | Status |
|--------|--------|
| Driver monitoring (EAR/MAR/head-pose/drowsiness) | **IMPLEMENTED** (ported from DDS) |
| Calibration | **IMPLEMENTED** |
| Audio alert tones | **IMPLEMENTED** |
| Event logging | **IMPLEMENTED** |
| Control Centre web UI (map + live fleet, per-bus ticketing/fare) | **IMPLEMENTED** (simulated data, clearly labeled) |
| 100-bus Chennai MTC fleet simulator (TN registration no's, 14 corridors) | **IMPLEMENTED** (simulated data) |
| Per-bus ticket machine counters (tickets sold, fare collected ₹) | **IMPLEMENTED** (simulated MTC ticket-machine data) |
| Cabin driver drowsiness alert (audio warning + Control Centre notify) | **IMPLEMENTED** (simulated DROWSY → DRIVER_ALERT event) |
| Operator Intercom (call driver / driver calls operator, transcript, speech) | **IMPLEMENTED** (in-app call store; simulated) |
| Risk engine · AI actions · predictive health · ETA · demand · road risk | **IMPLEMENTED** (simulated; see `control_centre/IMPLEMENTATION_PLAN.md`) |
| Backend REST API + fleet simulation | **IMPLEMENTED** (simulated data) |
| Camera Manager (3 slots, 1 active) | **IMPLEMENTED** (DRIVER webcam live; CABIN/ROAD planned placeholders) |
| FLEET-IQ LIVE PROTOTYPE mode (webcam AI perception: driver DDS / pothole / cabin) | **IMPLEMENTED** (live webcam; sim/live switchable from the UI) |
| Original DDS embedded in the Live Prototype camera feed (calibration, monitoring, audio warning, events) | **IMPLEMENTED** (live webcam, verified — see `ai_urban_management.md` PHASE 11) |
| Sensor interfaces (GPS / IMU / load / mic) | **IMPLEMENTED** (simulation only; clearly labeled) |
| Event model + bus state manager | **IMPLEMENTED** |
| Event Fusion Engine | **IMPLEMENTED** (crash/drowsy/overload/siren rules, pothole dedup) |
| Bus-node ↔ Control Centre link | **IMPLEMENTED** (WebSocket; simulated payloads) |
| GPS / IMU / Load / Microphone interfaces (real HW) | **PLANNED** (hardware not mounted) |
| Event Fusion Engine (real-HW inputs) | **PLANNED** |
| Event Fusion Engine | **PLANNED** |
| Bus-node ↔ Control Centre live link | **PLANNED** |
| Automatic braking | **DISABLED** — drowsiness only produces a brake *recommendation*; the Control Centre decides after human review |

See `ai_urban_management.md` for the running phase log.

---

## Project Layout

```
AI_Urban_Intelligence_Platform/
├── PLAN.md                     ← Architecture, flow diagrams, phases
├── config/system_config.json   ← All thresholds + bus/sensor settings
├── bus_node/                   ← Python code that runs on each bus
│   ├── main.py                 ← Entry point (driver monitoring)
│   ├── core/                   ← FatigueEngine, severity
│   ├── detectors/              ← EAR, MAR, head pose, face landmarker
│   ├── cameras/  sensors/  ai_modules/  event_fusion/  data/
│   ├── communication/          ← Future WebSocket link to Control Centre
│   ├── hardware/               ← Serial communicator (disabled)
│   └── utils/                  ← Calibration, alerts, config, logging
├── control_centre/             ← Web dashboard (React + Flask) [Phase 2+]
│   ├── backend/                ← Flask API, fleet simulator, risk/ETA/demand engines
│   │   └── ai/                 ← FLEET-IQ live prototype: camera_manager, driver DDS,
│   │                             pothole, cabin placeholder, DDS subprocess bridge
│   └── frontend/               ← React pages incl. Live Prototype (PROTO-001) view
├── arduino/                    ← Vehicle firmware (motor control disabled)
└── assets/  data/              ← Map, audio tones, logs
```

---

## Running the Bus Node (Phase 1)

From the project root:

```bash
# Using the same Python environment as DDS (deps already installed):
/home/rohith/Documents/D.D.S/DriverDrowsinessDetectionSystem/venv/bin/python bus_node/main.py

# Or with a custom camera index:
.../venv/bin/python bus_node/main.py --camera-index 1
```

Run from `AI_Urban_Intelligence_Platform/` so `config/system_config.json` is found.

The full bus-node pipeline (Phase 8): cameras + driver monitoring + simulated
sensors + event fusion + WebSocket stream to the Control Centre:

```bash
python bus_node/main.py                      # interactive (calibration window)
python bus_node/main.py --headless --duration 60   # no GUI, auto-stop
# --no-ws runs offline; --ws-url ws://HOST:PORT overrides the default
```

---

## Control Centre (web dashboard)

```bash
# Backend (simulated fleet + REST API + WebSocket ingestion)
cd control_centre/backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python server.py            # REST http://127.0.0.1:5001, WS ws://127.0.0.1:8765

# Frontend (React dashboard)
cd ../frontend
npm install
npm run dev                          # http://localhost:5173
```

Open http://localhost:5173 . All dashboard data is simulated and labeled as such.
Run `bus_node/main.py` after the backend to see the bus node stream live
(simulated) telemetry into the dashboard. See `control_centre/README.md`.

### LIVE PROTOTYPE mode (webcam AI perception — PROTO-001)

Start the backend directly in live mode (simulator off, only the PROTO-001
prototype node is shown):

```bash
cd control_centre/backend
venv/bin/python server.py --start-mode live     # REST :5001 + WS :8765
```

Then in the UI switch **DATA SOURCE → ● LIVE PROTOTYPE** (or start with
`--start-mode live`). On the **Live Fleet** page (or `/fleet/PROTO-001`):

1. Assign the webcam to a perception system — **Driver DDS / Pothole / Cabin**
   (one webcam, one module at a time).
2. In the driver camera feed, press **⚙ Calibrate** — 5 s personal baseline
   (EAR/MAR thresholds are computed from your real face).
3. Press **▶ Start Monitoring** — the original DDS engine runs on the live
   camera: real EAR/MAR/head pose/eye closure/PERCLOS/driver state, the
   original DDS audio warning on drowsiness, and `DRIVER_DROWSINESS` /
   `DRIVER_ALERT` events land in the existing event feed with
   `bus_id: PROTO-001`, `data_source: live`.

`GET /api/dds/status` and `POST /api/dds/calibrate|start|stop|reset` drive
this flow; see `control_centre/README.md`.

## Development Notes

- These are **development/calibration observations, NOT validated thresholds**:
  EAR ≈ 0.300 (one calibration), EAR threshold explored ≈ 0.23,
  MAR ≈ 0.400 (one calibration), head pitch ≈ 3.6°, prolonged eye closure ≈ 1.3 s.
  No accuracy/precision/F1/FPS/dataset claims are made unless measured.
- Simulation data is always labeled as `[SIMULATION]`; it is never presented as real measurement.