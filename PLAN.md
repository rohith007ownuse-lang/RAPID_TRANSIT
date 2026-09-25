# AI-Powered Mobile Urban Intelligence Platform
## Complete Development Plan & Architecture

---

## 1. PROJECT OVERVIEW

**Concept:** Convert public-transport buses into distributed mobile sensing and intelligence nodes.

**Prototype:** A small robot car + laptop acting as ONE bus node, sending data to a web-based Control Centre dashboard.

**Core Principle:** Every bus becomes a mobile urban intelligence node collecting driver safety, cabin safety, road conditions, crash events, emergency signals, load data, and vehicle health.

---

## 2. WHAT IS COPIED FROM DDS

```
FROM DDS                              STATUS
─────────────────────────────────────────────
face_detection.py (MediaPipe)         ✅ COPY AS-IS
eye_detection.py (EAR)                ✅ COPY AS-IS
mouth_detection.py (MAR)              ✅ COPY AS-IS
head_pose.py (solvePnP)               ✅ COPY AS-IS
fatigue_engine.py (drowsiness logic)  ✅ COPY AS-IS
severity.py                           ✅ COPY AS-IS
calibration.py                        ✅ COPY AS-IS
alert_manager.py                      ✅ COPY AS-IS
audio_synth.py                        ✅ COPY AS-IS
enhanced_logger.py                    ✅ COPY AS-IS
config_manager.py                     ✅ COPY AS-IS
utils.py (drawing primitives)         ✅ COPY AS-IS
serial_communicator.py                ✅ MODIFY (remove BT, extend protocol)
arduino firmware                      ⚠️ KEEP DISABLED (behind flag)
face_landmarker.task model            ✅ COPY AS-IS
yolov8n.pt                           ✅ COPY AS-IS (for cabin/road future)
generated_audio tones                 ✅ COPY AS-IS
system_config.json                    ✅ COPY + EXTEND
```

## 3. WHAT IS REMOVED

```
REMOVED                               REASON
─────────────────────────────────────────────
Bluetooth / HC-05 code                Per requirement
Ultrasonic obstacle detection         Per requirement
Obstacle avoidance logic              Per requirement
Automatic steering control            Per requirement
Autonomous driving logic              Per requirement
Tkinter dashboard                     Replaced by web UI
Vehicle control panel                 Motor control disabled
object_detection.py (phone/bottle)    Keep file but disable in main flow
```

## 4. WHAT IS NEW

```
NEW MODULE                            PURPOSE
─────────────────────────────────────────────
Camera Manager                        3-camera slot architecture
GPS Sensor Interface                  Location tracking
IMU Sensor Interface                  Crash/impact detection
Load Cell Interface                   Weight/overload monitoring
Microphone/Siren Interface            Emergency siren detection
Cabin AI Module                       Cabin safety (future cameras)
Road AI Module                        Road condition (future cameras)
Event Fusion Engine                   Multi-sensor event correlation
Event Data Model                      Structured event format
Bus State Manager                     Real-time bus state
WebSocket Communication               Live data to Control Centre
Web Control Centre (React)            Professional white dashboard
```

---

## 5. SYSTEM ARCHITECTURE FLOW

```
┌─────────────────────────────────────────────────────────┐
│                    PHYSICAL BUS NODE                     │
│                  (Laptop + Robot Car)                    │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ CAMERA 1 │  │ CAMERA 2 │  │ CAMERA 3 │              │
│  │ Driver   │  │ Cabin    │  │ Front    │              │
│  │ (ACTIVE) │  │(FUTURE)  │  │(FUTURE)  │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                    │
│       ▼              ▼              ▼                    │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐               │
│  │ Driver  │   │ Cabin   │   │ Road    │               │
│  │ AI      │   │ AI      │   │ AI      │               │
│  │(ACTIVE) │   │(PLANNED)│   │(PLANNED)│               │
│  └────┬────┘   └────┬────┘   └────┬────┘               │
│       │              │              │                    │
│       ▼              ▼              ▼                    │
│  ┌──────────────────────────────────────────┐           │
│  │           SENSOR INTERFACES              │           │
│  │                                          │           │
│  │  ┌─────┐ ┌─────┐ ┌──────┐ ┌──────────┐ │           │
│  │  │ IMU │ │ GPS │ │ Load │ │ Micro-   │ │           │
│  │  │     │ │     │ │ Cell │ │ phone    │ │           │
│  │  └──┬──┘ └──┬──┘ └──┬───┘ └────┬─────┘ │           │
│  │     │       │       │          │         │           │
│  │  [SIM]   [SIM]    [SIM]     [SIM]       │           │
│  └─────┬───────┬───────┬──────────┬─────────┘           │
│        │       │       │          │                     │
│        ▼       ▼       ▼          ▼                     │
│  ┌──────────────────────────────────────────┐           │
│  │         EVENT FUSION ENGINE              │           │
│  │                                          │           │
│  │  Correlates all sensor events            │           │
│  │  Assigns severity                        │           │
│  │  Creates fused incident events           │           │
│  │  Deduplicates repeated detections        │           │
│  └──────────────────┬───────────────────────┘           │
│                     │                                   │
│                     ▼                                   │
│  ┌──────────────────────────────────────────┐           │
│  │       BUS STATE MANAGER                  │           │
│  │                                          │           │
│  │  bus_id, location, speed, driver_state,  │           │
│  │  load_status, health_status, events[]    │           │
│  └──────────────────┬───────────────────────┘           │
│                     │                                   │
└─────────────────────┼───────────────────────────────────┘
                      │
                      │  WebSocket / USB Serial
                      │  (SIMULATED for now)
                      ▼
┌─────────────────────────────────────────────────────────┐
│                  CONTROL CENTRE                         │
│              (Web Dashboard - React)                    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │                TOP NAVIGATION                    │   │
│  │  Dashboard | Fleet | Incidents | Road | Safety   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ Active   │ │ Driver   │ │ Active   │               │
│  │ Buses    │ │ Alerts   │ │ Incidents│               │
│  └──────────┘ └──────────┘ └──────────┘               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │Overloaded│ │ Road     │ │Emergency │               │
│  │ Buses    │ │ Hazards  │ │ Events   │               │
│  └──────────┘ └──────────┘ └──────────┘               │
│                                                         │
│  ┌───────────────────┐  ┌───────────────────┐          │
│  │                   │  │                   │          │
│  │   FLEET MAP       │  │  LIVE ALERTS      │          │
│  │   (Interactive)   │  │  (Scrolling Feed) │          │
│  │                   │  │                   │          │
│  └───────────────────┘  └───────────────────┘          │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ Driver   │ │ Vehicle  │ │ Load     │               │
│  │ Safety   │ │ Health   │ │ Status   │               │
│  │ Cards    │ │ Cards    │ │ Cards    │               │
│  └──────────┘ └──────────┘ └──────────┘               │
└─────────────────────────────────────────────────────────┘
```

---

## 6. DATA FLOW — DRIVER MONITORING (ACTIVE)

```
Laptop Webcam
     │
     ▼
cv2.VideoCapture(0)
     │
     ▼
MediaPipe FaceLandmarker
     │
     ├──→ EAR Calculation ──→ eye_closed? ──→ closed_duration
     │
     ├──→ MAR Calculation ──→ yawn? ──→ yawn_count
     │
     ├──→ Head Pose (solvePnP) ──→ pitch/yaw/roll ──→ nod/pose alert
     │
     └──→ PERCLOS (sliding 60s window)
              │
              ▼
     FatigueEngine (combines all)
              │
              ├──→ Status: NORMAL / EYES_CLOSED / HEAD_NOD / DROWSINESS
              ├──→ Severity: None / WARNING / CRITICAL
              ├──→ Drowsiness %: 0-100
              └──→ Hardware Command: "G" (gradual brake) / "R" (reset)
                          │
                          ▼
              ┌───────────────────────┐
              │   EVENT FUSION ENGINE │
              │                       │
              │ Creates event:        │
              │  type: DRIVER_DROWSY  │
              │  bus_id: BUS-001      │
              │  severity: CRITICAL   │
              │  gps: (lat, lon)      │
              │  timestamp: now       │
              └───────────┬───────────┘
                          │
                          ▼
              WebSocket → Control Centre Dashboard
                          │
                          ▼
              Dashboard shows:
              - Live camera feed
              - EAR/MAR/Head pose values
              - Drowsiness status
              - Alert in incident feed
```

---

## 7. DATA FLOW — SIMULATED SENSORS (FUTURE HARDWARE)

```
┌─────────────────────────────────────────────────────┐
│              SIMULATION MODE (CURRENT)               │
│                                                     │
│  IMU Simulator ──→ Random realistic acceleration    │
│  GPS Simulator ──→ Fixed location or slow drift     │
│  Load Simulator ──→ Gradual weight change pattern   │
│  Mic Simulator ──→ Random siren detection events    │
│                                                     │
│  ALL DATA CLEARLY LABELED: [SIMULATION]             │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│              REAL HARDWARE MODE (FUTURE)             │
│                                                     │
│  MPU6050 (I2C) ──→ Real accelerometer/gyro data    │
│  NEO-6M (Serial) ──→ Real GPS coordinates           │
│  HX711 (GPIO) ──→ Real load cell weight             │
│  USB Mic ──→ Real audio → siren classification      │
│                                                     │
│  Switch via config: "simulation_mode": true/false   │
└─────────────────────────────────────────────────────┘
```

---

## 8. EVENT FUSION ENGINE FLOW

```
         ┌──────────────┐
         │ Driver AI    │──→ DRIVER_DROWSINESS event
         └──────────────┘
         ┌──────────────┐
         │ Cabin AI     │──→ CABIN_FIRE / SMOKE / INCIDENT event
         └──────────────┘         (PLANNED)
         ┌──────────────┐
         │ Road AI      │──→ POTHOLE / ROAD_DEFECT event
         └──────────────┘         (PLANNED)
         ┌──────────────┐
         │ IMU          │──→ CRASH / IMPACT event
         └──────────────┘
         ┌──────────────┐
         │ GPS          │──→ location data (enriches all events)
         └──────────────┘
         ┌──────────────┐
         │ Microphone   │──→ EMERGENCY_SIREN event
         └──────────────┘
         ┌──────────────┐
         │ Load Cell    │──→ OVERLOAD event
         └──────────────┘
         ┌──────────────┐
         │ Vehicle      │──→ VEHICLE_ANOMALY event
         │ Health       │
         └──────────────┘
                │
                ▼
    ┌───────────────────────┐
    │   EVENT FUSION        │
    │                       │
    │ 1. Collect all events │
    │ 2. Check correlations │
    │    Example:           │
    │    IMU: major impact  │
    │    + Cabin: incident  │
    │    + Speed: > 30km/h  │
    │    = MAJOR INCIDENT   │
    │ 3. Assign severity    │
    │ 4. Deduplicate        │
    │ 5. Create fused event │
    └───────────┬───────────┘
                │
                ▼
    ┌───────────────────────┐
    │   CONTROL CENTRE      │
    │                       │
    │ • Incident card       │
    │ • Live camera feed    │
    │ • Location on map     │
    │ • Severity banner     │
    │ • Acknowledge button  │
    └───────────────────────┘
```

---

## 9. EVENT DATA MODEL

```python
Event {
    event_id: string          # UUID
    bus_id: string            # "BUS-001"
    event_type: enum          # DRIVER_DROWSINESS | POTHOLE | CRASH | 
                              # CABIN_FIRE | EMERGENCY_SIREN | OVERLOAD | 
                              # VEHICLE_ANOMALY
    timestamp: datetime       # ISO 8601
    latitude: float           # GPS lat
    longitude: float          # GPS lon
    severity: enum            # INFO | WARNING | CRITICAL
    confidence: float         # 0.0 - 1.0
    sensor_source: string     # "driver_ai" | "imu" | "gps" | etc.
    status: enum              # ACTIVE | ACKNOWLEDGED | RESOLVED
    additional_data: dict     # sensor-specific details
    fusion_events: list       # correlated events (for fused incidents)
}
```

---

## 10. PROJECT FILE STRUCTURE

```
Rapid-Tracker/
│
├── PLAN.md                          ← THIS FILE
├── README.md
├── requirements.txt
├── .gitignore
│
├── config/
│   └── system_config.json           ← Extended from DDS
│
├── bus_node/                        ← PYTHON CODE (runs on bus/laptop)
│   ├── __init__.py
│   ├── main.py                      ← New entry point
│   │
│   ├── core/                        ← FROM DDS (modified)
│   │   ├── __init__.py
│   │   ├── fatigue_engine.py        ← COPY from DDS
│   │   └── severity.py             ← COPY from DDS
│   │
│   ├── detectors/                   ← FROM DDS (modified)
│   │   ├── __init__.py
│   │   ├── face_detection.py        ← COPY from DDS
│   │   ├── eye_detection.py         ← COPY from DDS
│   │   ├── mouth_detection.py       ← COPY from DDS
│   │   ├── head_pose.py             ← COPY from DDS
│   │   └── object_detection.py      ← KEEP but disabled in main
│   │
│   ├── cameras/                     ← NEW
│   │   ├── __init__.py
│   │   ├── camera_manager.py        ← Manages 3 camera slots
│   │   ├── driver_camera.py         ← ACTIVE (webcam)
│   │   ├── cabin_camera.py          ← PLACEHOLDER (future)
│   │   └── road_camera.py           ← PLACEHOLDER (future)
│   │
│   ├── sensors/                     ← NEW
│   │   ├── __init__.py
│   │   ├── imu_sensor.py            ← MPU6050 interface (SIM ready)
│   │   ├── gps_sensor.py            ← NEO-6M interface (SIM ready)
│   │   ├── load_cell.py             ← HX711 interface (SIM ready)
│   │   └── microphone.py            ← Audio/siren detection (SIM ready)
│   │
│   ├── ai_modules/                  ← NEW
│   │   ├── __init__.py
│   │   ├── cabin_ai.py              ← PLANNED (future cameras)
│   │   └── road_ai.py               ← PLANNED (future cameras)
│   │
│   ├── event_fusion/                ← NEW
│   │   ├── __init__.py
│   │   └── event_fusion.py          ← Event correlation engine
│   │
│   ├── data/                        ← NEW
│   │   ├── __init__.py
│   │   ├── event_model.py           ← Event data class
│   │   └── bus_state.py             ← Bus state manager
│   │
│   ├── communication/               ← NEW
│   │   ├── __init__.py
│   │   └── websocket_client.py      ← Sends data to Control Centre
│   │
│   ├── hardware/                    ← FROM DDS (disabled)
│   │   ├── __init__.py
│   │   └── serial_communicator.py   ← KEEP but disabled
│   │
│   ├── utils/                       ← FROM DDS
│   │   ├── __init__.py
│   │   ├── calibration.py           ← COPY from DDS
│   │   ├── enhanced_logger.py       ← COPY from DDS
│   │   ├── alert_manager.py         ← COPY from DDS
│   │   ├── audio_synth.py           ← COPY from DDS
│   │   └── utils.py                 ← COPY from DDS
│   │
│   ├── models/                      ← FROM DDS
│   │   └── face_landmarker.task     ← COPY from DDS
│   │
│   └── src/                         ← FROM DDS (models)
│       └── yolov8n.pt               ← COPY from DDS
│
├── arduino/                         ← FROM DDS (DISABLED)
│   └── drowsi_guard_car/
│       └── drowsi_guard_car.ino     ← KEEP but behind flag
│
├── control_centre/                  ← NEW - WEB DASHBOARD
│   ├── backend/                     ← Python API server
│   │   ├── __init__.py
│   │   ├── server.py                ← Flask/FastAPI server
│   │   ├── websocket_handler.py     ← Real-time WebSocket
│   │   └── data_store.py            ← In-memory + SQLite storage
│   │
│   └── frontend/                    ← React (white theme)
│       ├── package.json
│       ├── index.html
│       ├── vite.config.js
│       └── src/
│           ├── main.jsx
│           ├── App.jsx
│           ├── App.css
│           │
│           ├── components/          ← Reusable UI components
│           │   ├── Layout.jsx
│           │   ├── Sidebar.jsx
│           │   ├── Header.jsx
│           │   ├── MapWidget.jsx
│           │   ├── AlertFeed.jsx
│           │   ├── StatusCard.jsx
│           │   ├── GaugeChart.jsx
│           │   ├── BusMarker.jsx
│           │   └── CameraFeed.jsx
│           │
│           └── pages/               ← Page components
│               ├── Dashboard.jsx    ← Home with summary + map
│               ├── LiveFleet.jsx    ← Fleet map view
│               ├── BusDetails.jsx   ← Individual bus detail
│               ├── DriverSafety.jsx ← Driver monitoring page
│               ├── Incidents.jsx    ← Incident management
│               ├── RoadIntelligence.jsx ← Road conditions
│               ├── LoadManagement.jsx  ← Weight/load status
│               ├── VehicleHealth.jsx   ← Health monitoring
│               ├── Analytics.jsx    ← Charts and trends
│               └── Settings.jsx     ← Configuration
│
├── assets/
│   └── map.png                      ← COPY from DDS
│
└── data/
    ├── audio/
    │   └── (tone files)             ← COPY from DDS
    └── logs/
        └── (session logs)
```

---

## 11. UI DESIGN SPECIFICATION

### Color Theme — WHITE / PROFESSIONAL
```
Background:       #FFFFFF (white)
Card Background:  #F8F9FA (light grey)
Card Border:      #E9ECEF (subtle grey)
Text Primary:     #212529 (near black)
Text Secondary:   #6C757D (grey)
Accent Blue:      #2196F3 (primary action)
Accent Green:     #28A745 (normal/safe)
Accent Amber:     #FFC107 (warning)
Accent Red:       #DC3545 (critical/danger)
Border Radius:    12px (cards)
Shadow:           0 2px 8px rgba(0,0,0,0.08) (minimal)
Font:             Inter (clean, modern)
```

### Page Layout Structure
```
┌──────────────────────────────────────────────────────────┐
│ ☰  Rapid Transit Control Centre    🔔 3  ⚙️  👤    │
├──────┬───────────────────────────────────────────────────┤
│      │                                                   │
│ 📊   │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐       │
│ 🚌   │  │Active│ │Driver│ │Active│ │Over-│ │ Road │      │
│ 🚨   │  │Buses │ │Alerts│ │Inci- │ │load │ │Hazard│     │
│ 🛣️   │  │  12  │ │  3   │ │dents │ │  2  │ │  5   │     │
│ ⚖️   │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘       │
│ 🔧   │                                                   │
│ 📈   │  ┌──────────────────┐  ┌──────────────────┐      │
│ ⚙️   │  │                  │  │  LIVE ALERTS      │      │
│      │  │    FLEET MAP     │  │                  │      │
│      │  │   (Interactive)  │  │  ● Drowsy BUS-03 │      │
│      │  │                  │  │  ● Pothole BUS-07│      │
│      │  │                  │  │  ● Overload BUS-1│      │
│      │  └──────────────────┘  └──────────────────┘      │
│      │                                                   │
│      │  ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│      │  │  Driver  │ │ Vehicle  │ │   Load   │         │
│      │  │  Safety  │ │  Health  │ │  Status  │         │
│      │  │  Summary │ │  Summary │ │  Summary │         │
│      │  └──────────┘ └──────────┘ └──────────┘         │
└──────┴───────────────────────────────────────────────────┘
```

---

## 12. PHASE-BY-PHASE IMPLEMENTATION

> **Phase order (canonical):** the running log `ai_urban_management.md` records
> actual completion order/status and supersedes the ordering below if they differ.
> Deviation made by user direction: the Control Centre was built early as
> **Phase 2** (below it is merged from the former "backend" + "frontend" phases).
> Phases with ✅ were completed and verified; the remaining sections describe the
> work units still ahead.

### PHASE 1: Project Setup & DDS Core Copy ✅ DONE
```
ACTIONS:
1. Create Rapid-Tracker/ directory
2. Copy DDS core files (detectors, core, utils, models, audio)
3. Remove: Tkinter UI, vehicle control panel, Bluetooth refs
4. Disable: serial_communicator (behind config flag)
5. Disable: object_detection in main flow
6. Create new main.py entry point
7. Create extended system_config.json
8. Verify: driver monitoring still works standalone
```

### PHASE 2: Control Centre — Backend + Frontend ✅ DONE
```
ACTIONS:
1. Create Flask backend: REST endpoints /api/buses, /api/events,
   /api/road-defects, /api/overview, /api/analytics, /api/settings
2. In-memory data store + fleet simulator (simulated, clearly labeled)
3. Initialize React project with Vite
4. Create Layout with sidebar + header
5. Pages: Dashboard, Live Fleet, Bus Details, Driver Safety, Incidents,
   Road Intelligence, Load Management, Vehicle Health, Analytics, Settings
6. White professional theme throughout
7. Verify: all pages render correctly with demo data
```

### PHASE 3: Camera Manager & Multi-Camera Architecture ✅ DONE
```
ACTIONS:
1. Create camera_manager.py with 3 slots (DRIVER, CABIN, ROAD)
2. driver_camera.py → wraps cv2.VideoCapture(0)
3. cabin_camera.py → placeholder, returns labeled "NO CAMERA" frame
4. road_camera.py → placeholder, returns labeled "NO CAMERA" frame
5. Camera status tracking (OFF/ACTIVE/ERROR/PLANNED/DISABLED)
6. Verify: single webcam still works through camera_manager
```

### PHASE 4: Sensor Interfaces (Simulation Mode) ✅ DONE
```
ACTIONS:
1. Create imu_sensor.py → simulation: realistic acceleration patterns
2. Create gps_sensor.py → simulation: fixed location with drift
3. Create load_cell.py → simulation: gradual weight changes
4. Create microphone.py → simulation: random siren events
5. All sensors have: init(), read(), get_status(), enable/disable
6. Config flag: "simulation_mode": true
7. Each sensor output clearly labeled [SIMULATION]
8. Verify: sensors generate realistic demo data
```

### PHASE 5: Event Model & Bus State ✅ DONE
```
ACTIONS:
1. Create event_model.py → Event dataclass with all fields
2. Create bus_state.py → BusState with all sensor states
3. Event types enum: DRIVER_DROWSINESS, POTHOLE, CRASH, etc.
4. Severity enum: INFO, WARNING, CRITICAL
5. Status enum: ACTIVE, ACKNOWLEDGED, RESOLVED
6. Bus state: id, location, speed, driver_status, load, health
7. Verify: events can be created and stored
```

### PHASE 6: Event Fusion Engine ✅ DONE
```
ACTIONS:
1. Create event_fusion.py
2. Collect events from all sources
3. Correlation rules:
   - IMU crash + Cabin incident + Speed > threshold = MAJOR INCIDENT
   - Driver drowsy + Speed > 0 = HIGH ALERT
   - Overload + Harsh braking = COMPOUND RISK
4. Severity escalation logic
5. Deduplication (same pothole detected by multiple buses)
6. Fused event creation
7. Verify: fusion rules trigger correctly with simulated data
```

### PHASE 7: WebSocket Communication ✅ DONE
```
ACTIONS:
1. Create websocket_client.py (bus side)
2. Create websocket_handler.py (control centre side)
3. Protocol: JSON messages over WebSocket
4. Message types: SENSOR_UPDATE, EVENT, BUS_STATE, HEARTBEAT
5. Reconnection logic
6. Verify: bus node can send data, control centre receives it
```

### PHASE 8: Integration & Testing ✅ DONE
```
ACTIONS:
1. Connect bus_node → WebSocket → Control Centre
2. Verify driver monitoring data flows to dashboard
3. Verify simulated sensor data appears on dashboard
4. Verify event fusion triggers correctly
5. Verify incident alerts show on dashboard
6. Test camera feed display
7. Test all pages with live data
8. Verify DDS original project still works unchanged
```

### PHASE 9: Documentation & Polish ✅ DONE
```
ACTIONS:
1. Write README.md with setup instructions
2. Document simulation vs real hardware modes
3. Add "PROTOTYPE" / "PLANNED" labels where appropriate
4. Clean up code, remove debug prints
5. Final verification of all features
```

---

## 13. CONFIGURATION STRUCTURE

```json
{
  "system": {
    "name": "Rapid Transit",
    "version": "0.1.0",
    "mode": "simulation",
    "bus_id": "BUS-001"
  },
  "simulation_mode": true,
  "cameras": {
    "driver": {"index": 0, "active": true, "resolution": [640, 480]},
    "cabin":  {"index": 1, "active": false, "resolution": [640, 480]},
    "road":   {"index": 2, "active": false, "resolution": [640, 480]}
  },
  "detection": {
    "ear_threshold": 0.23,
    "mar_threshold": 0.40,
    "eye_closed_duration": 1.3,
    "yawn_duration": 1.0,
    "head_pitch_threshold": 15.0,
    "perclos_window": 60.0,
    "perclos_threshold": 0.15
  },
  "sensors": {
    "imu": {"type": "MPU6050", "simulation": true, "i2c_address": "0x68"},
    "gps": {"type": "NEO-6M", "simulation": true, "serial_port": "/dev/ttyUSB0"},
    "load_cell": {"type": "HX711", "simulation": true, "calibration_factor": -7050},
    "microphone": {"simulation": true, "siren_confidence_threshold": 0.7}
  },
  "bus": {
    "tare_weight_kg": 11000,
    "max_gvw_kg": 16200,
    "payload_limit_kg": 6000,
    "route": "Route 42 - Central District"
  },
  "communication": {
    "type": "websocket",
    "server_url": "ws://localhost:8765",
    "reconnect_delay": 2.0,
    "max_reconnect_attempts": 5
  },
  "hardware": {
    "enabled": false,
    "serial_port": "/dev/ttyACM0",
    "baud_rate": 9600
  },
  "control_centre": {
    "host": "0.0.0.0",
    "port": 5000,
    "websocket_port": 8765
  }
}
```

---

## 14. KEY DESIGN DECISIONS

| Decision | Choice | Reason |
|----------|--------|--------|
| UI Framework | React + Vite | Modern, fast, professional white theme |
| Communication | WebSocket | Real-time bidirectional data flow |
| Backend | Flask | Lightweight, easy to extend |
| Database | SQLite | Simple, no external deps |
| Sensor Data | Simulation by default | No hardware yet, demo-ready |
| Camera Architecture | 3-slot manager | Future-proof, only 1 active now |
| Motor Control | Disabled behind flag | Kept for reference, not in main flow |
| Event Model | Structured dataclass | Enables fusion, analytics, persistence |
| DDS Code | Copied, not moved | Original project untouched |
| Arduino Code | Copied but disabled | Reference for future hardware |

---

## 15. WHAT TO VERIFY AFTER EACH PHASE

```
PHASE 1:  python main.py → camera opens, face detected, EAR/MAR computed
PHASE 2:  Dashboard renders all pages correctly (see Control Centre)
PHASE 3:  Camera manager handles 1 active + 2 inactive cameras
PHASE 4:  Sensors produce labeled simulation data
PHASE 5:  Events created with correct structure
PHASE 6:  Fusion engine correlates multi-sensor events
PHASE 7:  WebSocket connects, messages received
PHASE 8:  End-to-end data flow works (verified: live bus-node BUS-001 streams
           driver/sensors/fusion into Control Centre; simulator does not overwrite)
PHASE 9:  Documentation complete, no broken features
```

---

## 16. RISKS & MITIGATIONS

| Risk | Mitigation |
|------|-----------|
| Breaking DDS functionality | Copy, don't move. Test DDS after copy. |
| Web UI too complex | Start with minimal Dashboard page, add pages incrementally |
| Simulation data looks fake | Clearly label all simulation data as [SIMULATION] |
| WebSocket instability | Add reconnection + offline mode |
| Camera conflicts | Only open active cameras, manage resources carefully |
| Too many files at once | Phase-by-phase, verify each before moving on |

---

*This plan will be reviewed and approved before any code is written.*
*Last updated: 2026-09-05*
