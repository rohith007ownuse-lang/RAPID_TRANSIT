# Rapid Transit Control Centre — Implementation Plan (Overview)

10 phases, executed in priority order. One phase at a time: implement -> typecheck
(backend + frontend) -> restart backend -> curl endpoints -> screenshot -> report.
Only proceed to the next phase when the current one is verified.

Hard rules held in every phase:
1. **No breaking changes** to existing endpoints, payloads, or page behaviour.
2. **Simulation honesty** — the `SimBadge` (SIMULATION) stays on every touched page;
   every new endpoint returns `simulation: true`; the Settings sink-hole remains.
3. Deterministic, defensive code: `.get()` defaults everywhere, never crash a tick.
4. New features are **additive** — new files, new endpoints, new cards/panels.

---

## Phase 1 — Unified Risk Engine (Priority 1) ✅ **COMPLETE**

**Overview.** A single bus risk score (0–100) with segment breakdown
(driver / vehicle / load / speed / occupancy / history), a risk level
(LOW / MEDIUM / HIGH / CRITICAL), human-readable reasons, and recommended
actions — computed server-side from the live simulated bus state plus recent
events, with editable weights.

**Files**
- NEW `backend/risk_engine.py` — pure scoring functions, no Flask deps.
- `backend/server.py` — add `GET /api/risk` (fleet) + `GET /api/buses/<id>/risk`.
- `backend/data_store.py` — add default `risk` weight config to settings (additive).
- `frontend/src/api.js` — add `risk()`, `busRisk(id)`.
- `frontend/src/pages/Dashboard.jsx` — "High-Risk Buses" panel (top N by score).
- `frontend/src/pages/BusDetails.jsx` — Risk Assessment card (score, segments,
  reasons, recommended actions).
- `frontend/src/pages/Analytics.jsx` — Risk Distribution panel (count by level).
- `frontend/src/theme.css` — risk badge/bar styles (additive classes).

**Verification.** `python risk_engine.py` self-check ✅; backend typecheck ✅; curl
`/api/risk` + `/api/buses/<id>/risk` ✅; `npm run build` ✅. Existing
`/api/buses` payload untouched ✅.

## Phase 2 — Driver Drowsiness: Temporal Fatigue + PERCLOS (Priority 2) ✅ **COMPLETE**

**Overview.** Upgrade the driver simulation from a random state flip into a
continuous fatigue timeline: per-episode start time, duration, escalation grade,
and a PERCLOS-style blink index computed from EAR/closure history. Short-term
(60 s) and long-term (15 min) fatigue metrics feed the risk engine's driver
segment. Scan interval becomes configurable via settings (default 2 s), read at
tick time (no restart needed).

**Files**
- `backend/simulator.py` — driver loop rewrite: episode timeline, PERCLOS index,
  fatigue stage (WATCH / ALERT / CRITICAL), sleep-based interval.
- `backend/websocket_handler.py` — `adapt_bus_state` copies new driver fields.
- `backend/risk_engine.py` — driver segment now consumes PERCLOS + stage.
- `frontend/src/pages/BusDetails.jsx` — PERCLOS gauge, fatigue stage badge, trend.
- `backend/data_store.py` — `simulator.scan_interval_s` setting (additive).

**Verification.** Fresh startup: 2 MEDIUM / 98 LOW risk buses (seeded fatigue). After ~90s: stage spread 3 CRITICAL / 97 WATCH; model DRIVER_DROWSINESS events = 3 (one per prone escalation); cabin DRIVER_ALERT events = 10 (throttled 25-min cooldown). Frontend builds ✅; no event spam ✅.

## Phase 3 — AI Intervention / Recommendation Layer (Priority 3) ✅ **COMPLETE**

**Overview.** A rule-based supervisor (`recommendations.py`) that turns risk into
concrete, dismissible operator actions. HIGH/CRITICAL risk auto-issues actions;
critical drowsiness/overload/occupancy auto-escalate; actions log to a new
`action_store` (with `acknowledged`/`resolved` state) and write `OTHER_CC`
events on auto-escalation. Live-sink-hole preserved.

**Files**
- NEW `backend/recommendations.py` — supervisor + action store, 8 action types.
- `backend/server.py` — `GET /api/actions`, `GET /api/actions?unacked=true`,
  `POST /api/actions/<id>/ack`, `POST /api/actions/<id>/resolve`,
  `POST /api/actions/evaluate`.
- `frontend/src/api.js` — `actions()`, `ackAction()`, `resolveAction()`, `evaluateActions()`.
- `frontend/src/pages/Dashboard.jsx` — Actions panel with Acknowledge buttons.
- `frontend/src/theme.css` — `.action-row` styles.

**Verification.** Fresh eval → 6 actions (3 FATIGUE_MONITOR, 2 MAINTENANCE_DISPATCH,
1 CRITICAL MAINTENANCE_DISPATCH with `auto_escalate: true`). Acknowledging an
action marks it acknowledged (removes from unacked list). Auto-escalation
emits `OTHER_CC` event with `intervention_type: AUTO_ESCALATE`. Frontend builds ✅.

## Phase 4 — Driver Recovery Detection + Safety Timeline (Priority 4) ✅ **COMPLETE**

**Overview.** The fatigue model now tracks recovery: each episode has graduated
recovery bands (driver reacts after cabin warning), producing `DRIVER_RECOVERED`
events and a `DRIVER_REFRESH_REQUIRED` state when long-term fatigue stays high.
A per-bus driver safety timeline (with per-stop 'location') is built from these
transitions.

**Files**
- `backend/simulator.py` — recovery bands, `DRIVER_RECOVERED` + `DRIVER_REFRESH_REQUIRED` events, `fatigue_timeline` list on driver (max 20 entries, each with ts, type, grade, stage, location).
- `backend/server.py` — `GET /api/buses/<id>/timeline` returns timeline + `needs_refresh` + `last_recovery`.
- `frontend/src/api.js` — `busTimeline(id)`.
- `frontend/src/pages/BusDetails.jsx` — Safety Timeline panel (reverse-chronological list with dot indicators, episode grade, stage, location, timestamp).
- `frontend/src/theme.css` — `.timeline-list`, `.timeline-item`, `.timeline-dot` styles.

**Verification.** After ~80s: 18 `DRIVER_RECOVERED` events, 2 `DRIVER_REFRESH_REQUIRED` events. Bus 18E timeline length = 20 (capped), entries show `EPISODE_START`/`RECOVERED` with grade, stage (CRITICAL), location (e.g., "Triplicane", "Chintadripet"), and timestamp. `needs_refresh: true` for high-fatigue bus. Frontend builds ✅.

## Phase 5 — Scenario Simulator (Priority 5) ⚠️ **BUILT THEN REMOVED**

> **Product decision (Phase 3 cleanup):** The Scenario system was built in this
> phase but is **no longer part of the FLEET-IQ product**. During Phase 3 cleanup
> it was removed end-to-end:
> - `backend/scenarios.py` deleted; `/api/scenarios*` routes removed.
> - Simulator scenario hooks (`apply_scenario_tick`, `_scenario_event_weights`,
>   scenario-weight event emission) removed — the generic simulator tick and
>   event feed were preserved unchanged.
> - Demand friction scenario branches removed (generic demand forecasting kept).
> - No scenario UI ever shipped in the deployed frontend (only `api.js` stubs,
>   which were removed).
> - The 10 scenario unit tests added with it were removed; remaining suite: 183 passing.

The original (historical) plan text is preserved below for the record.

**Overview (historical).** A scenario deck to exercise and demonstrate the control room:
configurable simulated scenarios (dense fog, festival rush, road closure, monsoon
flood, EV energy crisis, driver fatigue wave) toggle via `/api/scenarios`.
Each scenario applies feature flags to the live fleet (speed caps, fatigue
boosts, demand multipliers, detours, pothole surges, EV drain) for a limited
duration, auto-expiring and rolling back cleanly — live store never permanently
mutated; all changes tagged `scenario`.

**Files (historical)**
- NEW `backend/scenarios.py` — `ScenarioManager` with 6 catalogued scenarios
  (`dense_fog`, `festival_rush`, `road_closure`, `monsoon_flood`, `ev_energy_crisis`,
  `driver_fatigue_wave`), expiry watcher, flag apply/rollback.
- `backend/server.py` — `GET /api/scenarios` (catalog + active), `POST /api/scenarios/<key>/run`,
  `POST /api/scenarios/<key>/stop`.
- `backend/simulator.py` — `apply_scenario_tick` called each tick; flags injected per-bus.
- `frontend/src/api.js` — `scenarios()`, `runScenario(key)`, `stopScenario(key)`.
- `frontend/src/pages/Dashboard.jsx` — scenario deck panel (catalog buttons,
  active scenarios with countdown timers, start/stop buttons).

**Verification (historical).** Start `dense_fog` → buses receive `scenario_flags` with `speed_cap_kmh:30`,
`driver_fatigue_boost:1.5`; speed respects cap. Stop scenario → flags rolled back,
`scenario_flags` cleared, `active: {}`. Frontend builds ✅.

## Phase 6 — Predictive Vehicle Health (Priority 6) ✅ **COMPLETE**

**Overview.** Vehicle subsystem gains rolling degradation counters (tyre wear,
vibration drift, harsh braking rate, energy degradation) feeding RUL estimators
that warn early: "tyre #3 expected below threshold in ~2h". Maintenance
recommendations surface on the Vehicle Health page and flow into the risk
engine's vehicle segment. All synthetic demo data.

**Files**
- NEW `backend/predictive_health.py` — `VehicleHealthTracker` with 7 component
  health states per bus (4 tyres, vibration, harsh braking, energy degradation),
  linear trend RUL estimator, threshold-based predictions (`TYRE_REPLACEMENT`,
  `VIBRATION_INSPECTION`, `ENERGY_DEGRADATION`).
- `backend/simulator.py` — calls `tick_all()` each tick to advance degradation.
- `backend/server.py` — `GET /api/health/predictive` returns per-bus summaries
  (value, trend, RUL ticks/minutes, history) + active predictions.
- `frontend/src/api.js` — `predictiveHealth()`.
- `frontend/src/pages/VehicleHealth.jsx` — per-bus predictive degradation panel
  with component values, RUL, and prediction chips (coloured by severity).

**Verification.** After ~90s: all 100 buses have degradation summaries; 96+ buses
trigger `VIBRATION_INSPECTION` predictions (vibration > 0.75 threshold) with
RUL estimates. Frontend builds ✅.

## Phase 7 — ETA / Delay Prediction (Priority 7) ✅ **COMPLETE**

**Overview.** `eta.py` models dwell time from boarding density + route speed +
traffic-lapse factors + road friction (potholes/roadworks on the route), giving
per-bus ETA to next stop and destination with a delay banding forecast
(ON_TIME / MINOR_DELAY / SIGNIFICANT_DELAY / SEVERE_DELAY).

**Files**
- NEW `backend/eta.py` — `ETAEngine` with dwell model (base dwell by stop type,
  occupancy factor, pothole/roadwork friction), traffic lapse, Haversine
  distance; produces per-stop ETA ISO timestamps + delay bands.
- `backend/simulator.py` — imports `compute_all_etas` (called each tick via
  `eta_engine`).
- `backend/server.py` — `GET /api/eta` (fleet) + `GET /api/buses/<id>/eta`;
  delay summary counts by band.
- `frontend/src/api.js` — `eta()`, `busEta(id)`.
- `frontend/src/pages/BusDetails.jsx` — ETA card with per-stop table (stop, ETA,
  dwell, extra delay, delay band coloured by severity).
- `frontend/src/theme.css` — `.eta-list`, `.eta-row`, `.eta-stop` styles.

**Verification.** Fleet ETA endpoint returns 100 buses with delay_summary
(MINOR_DELAY 100). Per-bus ETA shows next 3 stops with ISO timestamps, dwell
18-35s, pothole friction +8s (active potholes detected), traffic lapse applied.
Delay bands computed correctly. Frontend builds ✅.

## Phase 8 — Demand / Boarding Forecasting (Priority 8) ✅ **COMPLETE**

**Overview.** `demand.py` forecasts upcoming-stop demand from the time-of-day +
weekday profile and known road friction (potholes, roadworks, detours), per
route and per stop, so dispatch can pre-position buses. Supplements (not
replaces) the existing boarding-by-hour analytics.

**Files**
- NEW `backend/demand.py` — `DemandEngine` with hourly profile, stop-type
  weights (major 7x normal), friction multipliers (pothole 0.7x, roadwork 0.5x,
  detour 0.6x); produces per-stop forecast (boardings, base, friction factor,
  confidence).
- `backend/server.py` — `GET /api/demand` (fleet) + `GET /api/buses/<id>/demand`.
- `frontend/src/api.js` — `demand()`, `busDemand(id)`.
- `frontend/src/pages/BusDetails.jsx` — Boarding Demand Forecast panel (next 5
  stops: stop name, forecast boardings, base, friction factor, confidence).
- `frontend/src/theme.css` — `.demand-list`, `.demand-row`, `.demand-stop` styles.

**Verification.** Fleet demand: 100 buses × 5 stops. Per-bus (1A): 5 stops with
base 73, forecast 20 (capped), friction 1.0x, confidence 73-93%. With
a road-friction signal present on a route: friction factor reduced → forecast
reduced. Frontend builds ✅.

## Phase 9 — Road Risk Intelligence (Priority 9) ✅ **COMPLETE**

**Overview.** Defect grouping (already deduped server-side) becomes a route risk
index: per-route pothole density, defect status, recurrence; risk zones drawn on
the Roads map; feeds the risk engine's road/history segments. Road defect threats
on a bus's current leg surface on the bus page. Projector sanitized for Enfield
only.

**Files**
- NEW `backend/road_risk.py` — `RoadRiskEngine` groups defects into risk zones
  (score 0-100, level LOW/MEDIUM/HIGH/CRITICAL), computes per-route risk index
  (avg score, zones, defects, worst level), finds threats on a bus's current
  leg (within 1 km of segment midpoint).
- `backend/server.py` — `GET /api/roads/risk` (zones + route index),
  `GET /api/buses/<id>/road-threats`.
- `frontend/src/api.js` — `roadRisk()`, `busRoadThreats(id)`.
- `frontend/src/pages/RoadIntelligence.jsx` — Risk Zones chips + Route Risk
  Index table (sorted by score).
- `frontend/src/pages/BusDetails.jsx` — Road Threats on Current Leg panel
  (threats within 1 km, with type, count, distance, risk level).
- `frontend/src/theme.css` — `.threats-list`, `.threat-row`, `.threat-info` styles.

**Verification.** Base: 2 zones (1A MEDIUM 47, 70V/M57 HIGH 62), route index 3
routes. Bus 1A road-threats: 1 pothole threat at 0.89 km, MEDIUM 47.
Frontend builds ✅.

## Phase 10 — Polish, Reconciliation & Readiness (Priority 10)

**Overview.** Final sweep: CSS grid rebalance, route/use the orphaned
`DriverSafety.jsx` + `LoadManagement.jsx`, action/ack persistence, order and
label consistency, README/AGENTS notes, full screenshot sweep of every page.

**Files**
- `frontend/src/App.jsx` — routes for DriverSafety / LoadManagement.
- `frontend/src/pages/*` + `theme.css` — layout/grammar cleanups.
- `README.md` / `AGENTS.md` — status notes + commands.

**Verification.** Full manual pass: every page renders, every endpoint 200s,
no console errors, screenshots collected per page.

## Phase 16 — Incident Intelligence, Correlation & Operational Response ✅ **COMPLETE**

**Overview.** Transform raw events into meaningful operational incidents through
correlation, deduplication, prioritization, and lifecycle management. Events are
correlated into incidents based on bus/category/time proximity, with deduplication
preventing duplicate incidents for the same bus/category within a configurable window.
Incidents track evidence, timeline, and support full lifecycle (OPEN → ACKNOWLEDGED →
INVESTIGATING → RESOLVED → CLOSED).

**Files**
- NEW `backend/incident_intelligence.py` — Incident data model (class), IncidentStore
  with thread-safe storage, correlation engine (10-min window), deduplication
  (5-min window), priority calculation (URGENT/HIGH/MEDIUM/LOW), severity
  escalation, event processing pipeline, summary/analytics.
- `backend/persistence.py` — Added `incidents` table + `save_incident()`,
  `load_incidents()`, `load_incidents_for_bus()`, `load_incident()`.
- `backend/server.py` — Added 10 new API endpoints:
  - `GET /api/incidents` (list with filters)
  - `GET /api/incidents/active` (OPEN/INVESTIGATING only)
  - `GET /api/incidents/summary` (severity/status/priority counts)
  - `GET /api/incidents/<id>` (single incident)
  - `POST /api/incidents/<id>/acknowledge` (auth required)
  - `POST /api/incidents/<id>/investigate` (auth required)
  - `POST /api/incidents/<id>/resolve` (supervisor+ required)
  - `POST /api/incidents/<id>/close` (supervisor+ required)
  - `GET /api/incidents/by-bus/<busId>` (bus-specific incidents)
  - `GET /api/incidents/by-event/<eventId>` (event→incident lookup)
- `frontend/src/api.js` — Added `incidents()`, `activeIncidents()`,
  `incidentSummary()`, `incident()`, `busIncidents()`, `incidentByEvent()`,
  `acknowledgeIncident()`, `investigateIncident()`, `resolveIncident()`,
  `closeIncident()`.
- `frontend/src/pages/Incidents.jsx` — Enhanced with dual view (Events/Incidents),
  incident summary chips, IncidentCard component with severity/priority/status
  badges, evidence display, timeline, lifecycle actions.
- `backend/tests/test_phase16_incident_intelligence.py` — 62 tests covering
  data model, store, event processing, correlation, deduplication, priority,
  persistence, API endpoints, edge cases.

**Key Design Decisions**
- Events are the atomic trigger; incidents are the operational intelligence layer
- Correlation window: 10 minutes (same bus, same category)
- Deduplication window: 5 minutes (same bus, same category → update existing)
- Priority: URGENT (CRITICAL+2 events), HIGH (HIGH+2 events or CRITICAL risk),
  MEDIUM (MEDIUM+), LOW (default)
- Lifecycle: OPEN → ACKNOWLEDGED → INVESTIGATING → RESOLVED → CLOSED
- Data source classification: LIVE/SIMULATION/HEURISTIC/MODEL/UNKNOWN

**Verification.** 549/549 backend tests pass ✅. Frontend builds ✅.
62 new Phase 16 tests cover all core functionality. API endpoints return
proper JSON with simulation/mode flags. Incident persistence survives restarts.

## Phase 17 — Analytics, Historical Intelligence & Operational Performance ✅ **COMPLETE**

**Overview.** Upgraded the analytics functionality from real-time snapshots to
historical intelligence. Added time-range filtering, trend analysis, cross-domain
insights, route analytics, bus analytics, and operational insights — all based on
actual persisted data with strict data-source honesty (SIMULATION/LIVE/HEURISTIC/UNKNOWN).

**Files**
- NEW `backend/analytics_intelligence.py` — Historical analytics module:
  - Time range parsing (1h/6h/24h/7d/30d/all/custom)
  - Trend analysis (linear regression, INCREASING/STABLE/DECREASING/UNKNOWN)
  - Event analytics (type, severity, bus, route, hourly distribution, timeline)
  - Incident analytics (category, severity, status, priority, avg duration)
  - Risk analytics (level, transitions, high/critical counts, avg score)
  - ETA/delay analytics (delay distribution, severe delays, on-time performance)
  - Load/occupancy analytics (utilization, overloaded, high occupancy)
  - Road intelligence analytics (events, zones, clusters, affected routes)
  - Driver safety analytics (drowsiness events, repeated offenders)
  - Route cross-domain analytics (events, incidents, risk, load per route)
  - Bus cross-domain analytics (events, incidents, risk, delays per bus)
  - Cross-domain insights (patterns, recommendations, correlation-not-causation)
  - Fleet KPI summary (active buses, incidents, risk, delays)
  - Comprehensive dashboard endpoint (all domains combined)
- `backend/server.py` — Added 12 new API endpoints:
  - `GET /api/analytics/historical` (comprehensive dashboard)
  - `GET /api/analytics/kpis` (fleet KPI summary)
  - `GET /api/analytics/events` (event analytics with filters)
  - `GET /api/analytics/incidents` (incident analytics with filters)
  - `GET /api/analytics/risk` (risk analytics)
  - `GET /api/analytics/eta` (delay analytics)
  - `GET /api/analytics/load` (load/occupancy analytics)
  - `GET /api/analytics/road` (road intelligence analytics)
  - `GET /api/analytics/driver-safety` (driver safety analytics)
  - `GET /api/analytics/routes` (route cross-domain analytics)
  - `GET /api/analytics/buses` (bus cross-domain analytics)
  - `GET /api/analytics/insights` (cross-domain insights)
- `frontend/src/api.js` — Added 12 new API client functions.
- `frontend/src/pages/Analytics.jsx` — Complete rewrite with dual view:
  - **Snapshot View** (existing real-time analytics preserved)
  - **Historical Intelligence View** with:
    - Time range selector (1h/6h/24h/7d/30d/all)
    - Domain tabs (Overview/Incidents/Risk/Delays/Load/Road/Safety/Routes/Buses)
    - KPI cards with trend badges
    - Timeline charts for trend visualization
    - Distribution tables (by category/severity/status/bus/route)
    - Cross-domain insights cards
    - Data source badges (SIMULATION/LIVE/HEURISTIC/UNKNOWN/INSUFFICIENT)
- `backend/tests/test_phase17_analytics_intelligence.py` — 75 tests covering:
  - Time range parsing and filtering
  - Trend analysis (increasing/stable/decreasing/insufficient)
  - Time bucketing
  - Event/incident/risk/ETA/load/road/safety analytics
  - Route and bus cross-domain analytics
  - Cross-domain insights
  - Fleet KPIs
  - API endpoints
  - Edge cases and data honesty

**Key Design Decisions**
- All analytics computed from actual persisted records (no fabricated data)
- Time ranges: 1h/6h/24h/7d/30d/all/custom (unbounded queries avoided)
- Trend analysis: linear regression with slope threshold (±5% = trend)
- Data source labels on every chart/metric (SIMULATION/LIVE/HEURISTIC/UNKNOWN/INSUFFICIENT)
- Cross-domain insights use correlation language ("occurred together" not "caused")
- No CSV/PDF export (explicitly out of scope)
- No real-time WebSocket streaming for historical analytics

**Data Availability (Honest Audit)**
- Events: FULLY PERSISTED (events table with timestamps)
- Incidents: FULLY PERSISTED (incidents table with created_at)
- Risk: PARTIALLY PERSISTED (risk_events for transitions; full history in-memory only)
- ETA: PERSISTED (eta_snapshots with delay_summary)
- Load: PERSISTED (load_snapshots with utilization_pct)
- Road: PERSISTED (road_clusters + road_risk_zones + events)
- Driver Safety: VIA EVENTS ONLY (DRIVER_DROWSINESS events)
- Vehicle Health: NOT PERSISTED (in-memory only, INSUFFICIENT_DATA shown)

**Verification.** 624/624 backend tests pass ✅ (75 new Phase 17 tests).
Frontend builds ✅. All API endpoints return proper JSON with simulation/mode flags.
Historical analytics show INSUFFICIENT_DATA when no records exist (not zero-filled).

## Phase 18 — WebSocket Reliability, Reconnection & Real-Time Communication Hardening ✅ **COMPLETE**

**Overview.** Hardened the WebSocket system with connection lifecycle management, exponential
backoff reconnection, message deduplication, heartbeat/ping mechanism, message priority
queuing, event coalescing, server-side connection tracking, and state resynchronization
after reconnect. Added a frontend WebSocket client with automatic reconnection and a
connection status indicator component.

**Files**
- NEW `backend/websocket_hardening.py` — WebSocket hardening module (~876 lines):
  - `ConnectionState` enum (DISCONNECTED/CONNECTING/CONNECTED/AUTHENTICATING/READY/RECONNECTING/ERROR)
  - `MessagePriority` enum (CRITICAL/IMPORTANT/NORMAL/TRANSIENT)
  - `MessageType` constants for full WebSocket message protocol
  - `MessageDeduplicator`: thread-safe event ID deduplication with configurable window (5 min default)
  - `EventCoalescer`: coalesce high-frequency telemetry (health/ETA/load updates), pass through discrete events
  - `ConnectionStateManager`: connection state with listeners, staleness detection
  - `MessagePriorityQueue`: bounded priority queue (max 100), critical messages never dropped
  - `validate_message()`: JSON validation, required field checks per message type
  - `classify_message_priority()`: route messages to priority levels based on type/severity
  - `calculate_backoff()`: exponential backoff with jitter (1-30s range)
  - `ReconnectionManager`: attempt tracking, backoff, max attempts configuration
  - `ServerConnectionTracker`: server-side connection registry (max 100 subscribers)
  - `StateResynchronizer`: REST API sync plan for reconnect recovery
  - `WebSocketMetrics`: messages sent/received/failed/dropped, connections, dedup hits
  - `preserve_data_source()`: prevent LIVE↔SIMULATION/HEURISTIC/UNKNOWN conversion
  - Close codes (1000, 1001, 1002, 1003, 1008, 1011, 4001, 4002, 4003)
- `backend/websocket_handler.py` — Updated with Phase 18 hardening:
  - Enhanced `_conn_handler()` with message validation, error isolation, metrics collection
  - Added `_send_state_snapshot()` for state recovery after reconnect
  - Enhanced `_push_alert()` with deduplication and metrics
  - Enhanced `_push_road_event()` and `_push_road_risk_update()` with metrics
  - Added `_ping_dashboard_clients()` for server-initiated heartbeat
  - Added `_cleanup_stale_connections()` for connection health management
  - Added `get_ws_metrics()`, `get_ws_connections()`, `get_ws_status()` public APIs
  - Updated `_subscribe_dashboard()` with connection tracking and rate limiting
- `backend/server.py` — Added 2 new API endpoints:
  - `GET /api/websocket/status` — WebSocket server status and metrics
  - `GET /api/websocket/metrics` — WebSocket performance metrics
- NEW `frontend/src/websocket.js` — Frontend WebSocket client (~380 lines):
  - `FleetWebSocketClient` class with connection lifecycle management
  - Exponential backoff reconnection (1-30s, configurable max attempts)
  - Message deduplication (5-minute window)
  - Heartbeat/ping mechanism (15s interval)
  - State resynchronization via REST APIs after reconnect
  - Connection state listeners for UI updates
  - Message queue for messages sent while disconnected
  - Singleton pattern for shared connection across components
- `frontend/src/api.js` — Added 2 new API client functions:
  - `websocketStatus()` — Get WebSocket server status
  - `websocketMetrics()` — Get WebSocket performance metrics
- NEW `frontend/src/components/ConnectionStatus.jsx` — Connection status indicator:
  - Compact and full display modes
  - Color-coded state (green/amber/red)
  - Stale data warning (60s timeout)
  - Connect/disconnect toggle
- `backend/tests/test_phase18_websocket_hardening.py` — 80 tests covering:
  - MessageDeduplicator (8 tests): basic, duplicates, window expiry, clear, size, thread safety
  - EventCoalescer (5 tests): non-coalesced pass-through, coalescing, different bus IDs, clear
  - ConnectionStateManager (9 tests): initial state, set state, listeners, staleness, reconnect attempts
  - MessagePriorityQueue (7 tests): put/get, priority ordering, max size, critical never dropped
  - ServerConnectionTracker (6 tests): register/unregister, capacity, stale connections, thread safety
  - ReconnectionManager (5 tests): should reconnect, max attempts, success resets, delay calculation
  - StateResynchronizer (3 tests): needs sync, record sync, sync plan
  - WebSocketMetrics (4 tests): record, get all, reset, negative values
  - validate_message (11 tests): valid/invalid JSON, missing fields, message types
  - classify_message_priority (8 tests): alerts, events, bus state, heartbeat
  - calculate_backoff (2 tests): increasing delay, max delay cap
  - preserve_data_source (3 tests): valid/invalid overrides
  - create_ws_message (2 tests): basic message, with source
  - Constants (4 tests): non-coalesced types, coalesced types, close codes, config values
  - Integration (3 tests): full dedup workflow, full priority workflow, connection lifecycle

**Key Design Decisions**
- WebSocket is the real-time delivery mechanism, NOT the source of truth
- After reconnect, recover state from REST APIs (fleet, buses, alerts, incidents, risk, events)
- Never fabricate events or timestamps
- Preserve LIVE/SIMULATION/HEURISTIC/UNKNOWN data sources
- Critical events (incidents, alerts) are never coalesced
- High-frequency telemetry (health, ETA, load) can be coalesced safely
- Server-side deduplication prevents duplicate alert delivery
- Dashboard clients receive server-initiated pings for connection health
- Stale connections (60s no messages) are automatically cleaned up
- Rate limiting: max 100 dashboard subscribers

**Data Flow (Post Phase 18)**
```
Bus Node → WS:8765 → websocket_handler → store → alerts.py → _push_alert() → dashboard
                            ↓
                    websocket_hardening
                    (dedup, validate, metrics)
                            ↓
                    ServerConnectionTracker
                    (connection health, stale cleanup)
```

**Verification.** 80/80 Phase 18 tests pass ✅. All existing tests continue to pass.
Frontend builds ✅. WebSocket server status endpoint returns proper JSON.
Connection status indicator available for frontend integration.

## Phase 19 — Offline, Failure Detection, Degraded Modes & System Resilience ✅ **COMPLETE**

**Overview.** Added comprehensive system health monitoring, failure detection, degraded mode
support, and data freshness tracking. The control centre now clearly distinguishes between
healthy, degraded, disconnected, unavailable, stale, recovering, failed, and unknown states.
A missing subsystem must never silently appear healthy.

**Files**
- NEW `backend/system_health.py` — System health module (~450 lines):
  - `HealthState` enum (HEALTHY/DEGRADED/DISCONNECTED/STARTING/STOPPING/FAILED/RECOVERING/UNKNOWN)
  - `DataFreshness` enum (FRESH/STALE/UNAVAILABLE/UNKNOWN)
  - `SubsystemHealth` class: per-subsystem health tracking with:
    - State transitions with debounce (prevents recovery flapping)
    - Data freshness tracking
    - Error counting and last error
    - Success counting
    - State change listeners
    - Thread-safe operations
  - `SystemHealthManager` class: manages all subsystems with:
    - Overall health calculation
    - Freshness updates
    - State change notifications
    - Serialization for API
  - `initialize_health_tracking()`: registers all known subsystems
  - Convenience functions: `record_subsystem_success()`, `record_subsystem_failure()`, `get_subsystem_health()`, `get_system_health()`
  - Staleness thresholds per subsystem type
  - Recovery flapping prevention (10s debounce)
- `backend/persistence.py` — Added health tracking for persistence operations:
  - `save_event()` now records success/failure for health tracking
  - `_record_persistence_success()` and `_record_persistence_failure()` helpers
  - Persistence failures are caught and logged without breaking event pipeline
- `backend/data_store.py` — Enhanced `add_event()` with failure isolation:
  - Persistence failures are now caught and logged
  - Events remain in memory even if persistence fails
  - Health tracking integrated for persistence subsystem
- `backend/server.py` — Added 2 new API endpoints:
  - `GET /api/system/health` — Full system health status with all subsystems
  - `GET /api/system/health/<subsystem_name>` — Per-subsystem health status
  - Health tracking initialized at server startup
- `backend/ai/camera_manager.py` — Enhanced camera failure handling:
  - Capture loop now updates source state to ERROR on exception
  - Health tracking integrated for driver/cabin cameras
  - Camera recovery recorded on successful frame capture
- `backend/ai/cabin/occupancy.py` — Enhanced cabin occupancy failure handling:
  - Health tracking integrated for cabin occupancy subsystem
  - Failures recorded for estimator errors and camera unavailability
  - Success recorded on successful occupancy estimation
- `frontend/src/api.js` — Added 2 new API client functions:
  - `systemHealth()` — Get full system health status
  - `subsystemHealth(name)` — Get per-subsystem health
- NEW `frontend/src/components/SystemHealth.jsx` — System health panel (~280 lines):
  - Overall system health indicator
  - Per-subsystem health status with color-coded badges
  - Data freshness indicators
  - Error counts and last success time
  - Compact and full display modes
  - Auto-refresh every 10 seconds
- `backend/tests/test_phase19_system_health.py` — 35 tests covering:
  - SubsystemHealth (13 tests): initial state, success, failure, critical failure, consecutive failures, disconnect, starting, stopping, recovery, freshness, serialization, listeners, thread safety
  - SystemHealthManager (8 tests): register, get, get_all, overall health, freshness updates, serialization
  - Convenience functions (4 tests): success, failure, get health, get system health
  - Initialize health tracking (2 tests): initialization, staleness thresholds
  - Integration (4 tests): full lifecycle, independent subsystems, serialization, recovery debounce
  - Constants (4 tests): health states, freshness states, recovery debounce

**Key Design Decisions**
- A missing subsystem must never silently appear healthy
- UNKNOWN/UNAVAILABLE/STALE are honest representations, not fallback values
- Recovery flapping prevention via debounce (10s window)
- Persistence failures are non-blocking but observable
- Camera failures are isolated per-slot (one camera failing doesn't affect another)
- Cabin occupancy uses null values (not 0) when unavailable
- Health state transitions are logged and observable via API
- Frontend shows system health with clear visual indicators

**Subsystem Health Model**
```
HEALTHY      → Subsystem operational, data fresh
DEGRADED     → Subsystem partially operational or experiencing errors
DISCONNECTED → Subsystem not connected (camera unplugged, WebSocket down)
STARTING     → Subsystem initializing
STOPPING     → Subsystem shutting down
FAILED       → Subsystem not operational (critical error or 3+ failures)
RECOVERING   → Subsystem recovering from failure
UNKNOWN      → Subsystem state cannot be determined
```

**Data Freshness Model**
```
FRESH        → Recent valid data (< threshold)
STALE        → Last known data exists but older than threshold
UNAVAILABLE  → No valid data currently available
UNKNOWN      → System cannot determine current state
```

**Failure Isolation**
- Camera failures: isolated per-slot (driver/cabin independent)
- Persistence failures: caught and logged, events remain in memory
- WebSocket failures: isolated per-client, server continues
- Alert processing failures: logged, events still created
- Background thread failures: caught, thread continues or exits gracefully

**Degraded Mode Examples**
- Driver camera unavailable → Driver safety: UNAVAILABLE
- Cabin camera unavailable → Occupancy: UNKNOWN
- Vehicle telemetry stale → Vehicle health: STALE
- WebSocket disconnected → REST APIs still available
- Persistence failed → Events in memory, will persist on recovery

**Verification.** 35/35 Phase 19 tests pass ✅. All existing tests continue to pass.
Frontend builds ✅. System health endpoints return proper JSON with all subsystems.
Health tracking integrated into persistence, cameras, and cabin occupancy.