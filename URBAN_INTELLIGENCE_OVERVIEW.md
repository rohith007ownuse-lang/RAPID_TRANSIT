# Urban Intelligence Control Centre

**What it is.** A full-stack, AI-flavoured **city public-transport operations & analytics platform** (SIH / "AI Urban Intelligence Platform"). It visualises a live bus fleet on a street map, streams driver/vehicle/road alerts into an operations dashboard, lets an operator review, acknowledge and resolve incidents, makes **live phone-style calls to drivers** directly from the dashboard, and produces boarding / fare / pothole analytics. Everything is currently a **realistic simulator** (labelled SIMULATION), with a WebSocket gateway ready to ingest **real bus-node hardware** later.

---

## 1. System architecture

```
                    ┌────────────────────────────────────────────┐
  Browser UI  ◄────►│  React + Vite (frontend)  :5173             │
  (react-leaflet,   │   pages / components / lib                 │
   OSM tiles)       └───────────────▲────────────────────────────┘
                                    │ JSON over HTTP (fetch poll 3–6 s)
                    ┌───────────────┴────────────────────────────┐
                    │  Flask API (backend)            :5001       │
                    │  server.py  ·  data_store.py (in-memory)     │
                    └───────────────▲────────────────────────────┘
                                    │ upsert / query
                    ┌───────────────┴────────────────────────────┐
                    │  FleetSimulator (simulator.py, thread)      │
                    │  100 buses · 14 MTC routes · 1 s tick        │
                    └─────────────────────────────────────────────┘

  Real bus nodes (bus_node hardware, later phase)
        ──── WebSocket ───►  websocket_handler  :8765  ──►  data_store
                            (hello / bus_state / event / heartbeat)
```

- **Frontend** — React 19 + Vite, `react-router`, `react-leaflet` + OpenStreetMap tiles, custom dark-blue theme CSS. Polls the API with a `usePoll(fetch, ms)` hook.
- **Backend** — Flask REST API over an in-memory thread-safe `data_store` (buses keyed by id, append-only event log, road-defect registry).
- **Simulator** — background thread ticking every second, evolving every bus (movement, passengers, energy, tyres, driver state, alerts).
- **WebSocket gateway** — accepts real/simulated bus-node connections on `ws://:8765` and maps their payload vocabulary into the dashboard schema.

Run with the desktop launcher `start.sh` (starts backend + frontend, opens browser). Ports: **API 5001**, **WS 8765**, **UI 5173**.

---

## 2. Domain model (the full model)

### 2.1 Fleet
- **100 buses** across **14 MTC corridors** (7–8 services per route), e.g. `1A`, `19D`; a second service on the same route is `1A .2`. `/api/buses/<id>` links use URL-encoding because ids contain a space.
- Each bus carries:
  - **Identity**: `bus_id`, `route_code`, `route` (name), Chennai `reg_no` (e.g. `TN-01-F-0234`).
  - **Vehicle type**: EV (battery %) or DIESEL (fuel %).
  - **Position & motion**: live lat/lon, `speed_kmh`, journey state.
  - **Driver**: `state` (`NORMAL / ATTENTION / DROWSY`), stable `name` (for "driver Rosina · 1A" style alerts), gaze metrics (`ear`, `mar`, `head_pitch_deg`, `closed_sec`) from a cabin AI model.
  - **Occupancy / load**: passengers (0–60), `pct`, crowd level; payload = passengers × 68 kg; GVW = tare (11,000) + payload, capped 17,000 kg; `CRITICAL OVERLOAD` > 90% load.
  - **Energy**: EV `kwh`/`percent`, diesel `litres`.
  - **Wheels**: 4-tyre PSI (target ~85).
  - **Vehicle health**: `NORMAL / WARNING / INSPECTION REQUIRED`, `vibration`, `braking_events`, `maintenance_priority` (LOW/MEDIUM/HIGH), `anomaly`.
  - **Ticketing**: `tickets_today`, `passengers_total`, `fare_collected`, avg fare **₹18.5**, MTC ticket-machine id.
  - **Journey** and **boarding profile** (below).

### 2.2 Routes & journeys
- 14 routes with realistic Chennai stop sequences (major terminals like Koyambedu CMBT → Kilambakkam, Tambaram, Pallavaram, Chromepet, Broadway…); ~10–20 stops each; `70V` = classic CMBT→KCBT corridor.
- Each bus runs a **journey state machine**: `AT_STOP → MOVING → ARRIVING → AT_STOP …`; reaching the last stop resets to a return trip.
- Movement is **road-aligned**: between stops the bus follows a grid-snapped **east/west + north/south street staircase** (≈200 m block grid), so it never "jumps over buildings". Live speed: 24–45 km/h driving, decelerating 34→6 km/h into a stop, 0 while dwelling.
- At stops small realistic boarding pulses occur (2–3 normal, 6–10 at major terminals) that drive tickets + revenue.

### 2.3 Events / incidents
- **Types** (with sensor source): `DRIVER_DROWSINESS` (driver_ai), `DRIVER_ALERT` (cabin audio warning), `POTHOLE` (road_ai), `EMERGENCY_SIREN` (microphone), `OVERLOAD` (load cell), `VEHICLE_ANOMALY` (vehicle health), `CRASH` (imu), `CABIN_FIRE` / `CABIN_SMOKE` / `CABIN_INCIDENT` (cabin_ai).
- **Severity**: `CRITICAL / WARNING / INFO`, with a `confidence` (0–1) and optional `additional_data` (e.g. cabin warning issued).
- **Status lifecycle** (+ operator audit trail):
  `ACTIVE` (not reviewed) → `REVIEWING` → `ACKNOWLEDGED` → `RESOLVED`, tracked with `unreviewed_by / reviewed_by / acknowledged_by / resolved_by / updated_by` tags. UI: white pill = new, amber pulsing = reviewing, green ✓ = acknowledged, muted = resolved.
- **Review workflow**: per-event inline *Edit status* (Not reviewed / Reviewing / Acknowledged / Resolved), a single **bulk button** to apply one status to all events of a page, and per-bus bulk editing on the bus detail page.
- **Minimal-alert model**: only a small subset (~5) of "alert-prone" buses may raise events, at a slower cadence (150–320 s), so the live feed stays calm and believable at scale.

### 2.4 Road defects (potholes)
- Registry keyed by snapped grid co-ordinate; each defect tracks `detection_count`, `confidence` (rises with re-detections), `first/last_detected`, the list of buses that detected it, and a mock `image` reference.
- Deliberately **minimal**: a couple of seeded potholes plus slow accumulation from pothole events (only alert-prone buses).
- Shown on **Road Intelligence** and **Analytics** pages — deliberately **not on the main dashboard**.

### 2.5 Analytics model
- **Hourly boardings** fleet-wide (service day 04:00–23:00) with peak / quietest hour.
- **Date-wise + route-wise pothole detections** (last 8 days): trend anchored *today* to the live ACTIVE road-defect count; per-route split allocated by stop-count (largest-remainder, sums guaranteed).
- Drowsiness by bus, incident counts by route, event types, severity mix, occupancy per bus, fare collected per bus, vehicle mix (EV/DIESEL).
- Tickets & revenue tied to actual boarding events in the simulation.

### 2.6 Call / intercom model
- **One shared in-app call store** (pub/sub) — all pages see the same call state: `status` (`idle/calling/ringing/active`), `direction` (`out/in`), `busId`, `startedAt`, transcript lines (`you` / driver).
- **Operator → driver**: one tap = **instant direct connect** (no accept step) — "like a phone call", whoever's at the cabin just talks.
- **Driver → operator**: the in-bus **CALL button** rings the control room (simulated) → a **global incoming-call banner** pops on *any* page (accept / decline, 20 s auto-timeout).
- **Dashboard integration**: the live/ringing call is **pinned at the top of Live Alerts** as top-priority and never re-orders; clicking it opens that bus to call/act immediately.
- **Full-duplex console**: operator mic (Web Speech continuous, en-IN) → spoken to the cabin speaker (TTS) + shown as transcript, driver replies simulated; End call anytime.
- Call buttons live on the dashboard (pinned card), the Live Fleet table (Intercom column), and each bus page header.

---

## 3. Dashboard pages & capabilities

| Page | Route | What it does |
|---|---|---|
| **Operations Dashboard** | `/` | KPI cards (active buses, driver alerts, active incidents, overloaded, emergencies, tickets, fare); fleet map; **pinned call card** (top priority); clickable live alerts → open the bus; quick summaries (driver safety, vehicle health, load, sirens). |
| **Live Fleet** | `/fleet` | Live street map with moving buses (speed + state on hover), fleet table with **Intercom call column**, driver names, occupancy, speed. |
| **Bus Detail** | `/fleet/:busId` | Full telemetry (speed, passengers, energy, tyres, driver state), journey/stop tracker with **route line + active leg** on the map, call button, recent events with per-row **edit status** + **bulk review** for the bus. |
| **Incidents** | `/incidents` | Full review center: filter by type/severity, per-event status pills + inline edit, **Open Live Feed** (opens the bus), Acknowledge / Mark Resolved, **bulk edit all incidents**, live-feed quick review. |
| **Road Intelligence** | `/roads` | Active pothole registry (confidence, detection count, detecting buses, confidence bar). |
| **Vehicle Health** | `/health` | Per-bus health cards **sorted INSPECTION REQUIRED → WARNING → NORMAL**, vibration, maintenance priority, braking events. |
| **Analytics** | `/analytics` | Hourly boardings (peak/quiet chart), drowsiness by bus, incidents by route, event/severity mix, occupancy, fare by bus, vehicle mix, **date-wise & route-wise pothole analytics**. |
| **Settings** | `/settings` | Project/app settings via `store.update_settings`. |
| **Intercom** | `/calls` (URL-only, not in nav) | Bus list + dial, simulate driver-calling-operator, active call console with transcript and speech. |

Reusable components: `FleetMap` (route `routePath` + active-leg rendering), `AlertFeed` (clickable, driver-name aware, inline review states), `ReviewStatus` (`ReviewState` / `ReviewEditor` / `BulkReviewEditor`), `CallButton`, `IncomingCall`, `BusRouteTracker`, `CameraFeed`, `Gauge`, `Layout` (sidebar nav + global banner), `UI` (StatCard, StatusBadge).

---

## 4. REST API reference

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness + simulation flag. |
| GET | `/api/overview` | Fleet KPIs: active buses, driver alerts, active incidents, overloaded, road hazards, emergencies, tickets, fare, `simulation`. |
| GET | `/api/buses` | All buses (full current state + journey). |
| GET | `/api/buses/<id>` | One bus + its recent events. |
| GET | `/api/events` | Event log (optional `status`, `type` filters). |
| POST | `/api/events/<id>/acknowledge` | Set ACKNOWLEDGED (operator). |
| POST | `/api/events/<id>/review` | Mark being reviewed (opens live feed). |
| POST | `/api/events/<id>/resolve` | Set RESOLVED (operator). |
| POST | `/api/events/<id>/status` | Arbitrary status change (with operator tags). |
| POST | `/api/events/status` | **Bulk** status for many events (per bus or all). |
| GET | `/api/road-defects` | Pothole registry. |
| GET | `/api/analytics` | Boardings, incidents, occupancy, fares, vehicle mix, pothole date/route series. |
| GET/POST | `/api/settings` | Read / update settings. |

---

## 5. WebSocket ingestion (real bus nodes)

- Endpoint `ws://<host>:8765` (`--ws-port`). Protocol:
  - client → `{"type":"hello","bus_id":...}`, `{"type":"bus_state","state":{…}}`, `{"type":"event","event":{…}}`, `{"type":"heartbeat"}`
  - server → `{"type":"ack","ok":true,…}`
- `adapt_bus_state()` maps bus-node vocabulary into dashboard schema (driver state, load status with spaces, occupancy, energy, wheels, speed, name), so connected buses appear on the exact same pages. This is the path toward **real hardware**: Esp32/Arduino bus-node units (see `arduino/`, `bus_node/`) streaming sleep-detection/overload/vehicle data live.

---

## 6. Simulation honesty & configuration

- Everything is labelled **SIMULATION** (`/api/health`, payload flags, header badge).
- Tuning knobs in `backend/simulator.py`: `NUM_BUSES` (now **100**), `AVG_FARE` (₹18.5), service window `04:00–23:00` with `+2 sim-min/tick`, movement pacing, boarding rates, alert-prone subset (≤5), event cadence, seeded/history events, road-defect seed count.
- Row/`server.py`: pothole analytics scale, cache, live-anchor to the defect registry.

## 7. Roadmap (real-data phase)

1. Replace simulated buses with live `bus_node` WebSocket feeds.
2. Real camera feeds (`CameraFeed`) / MediaPipe driver-AI on node hardware.
3. Predictive maintenance (history + model), ETA/delay prediction, demand forecast — recommended next features.
4. PDF/CSV incident report export and operator roles.