# FLEET-IQ Control Centre — Full Engineering Audit

**Date:** 2026-09-07
**Scope:** Read-only audit. No code, config, or runtime state was modified.
**Method:** 4 parallel deep-dive inspections (Backend Core, AI/Live modules, Risk/Scenarios/Analytics, Frontend/UI) + live runtime verification against the currently running instance (API :5001, WS :8765, Vite :5173) + targeted source verification of every headline claim.

**Runtime snapshot (verified live, not simulated):**

| Probe | Verified value |
|---|---|
| `/api/mode` | `mode:live`, `is_simulation:false`, `connected_nodes:["PROTO-001"]` |
| `/api/buses` | 1 live bus `PROTO-001` |
| `/api/camera/status` | `mode:single_camera`, `driver.active:true`, `connected:true`, `system_mode:live` |
| `/api/camera/stream` | frame present, `face:true`, `ear:0.54`, `state:NORMAL` |
| `/api/dds/status` | `phase:idle`, `monitoring:false` |
| `/api/analytics` | `simulation:False`, `mode:live` |
| `/api/incidents/export?format=csv` / `pdf` | HTTP 200, valid file (PDF verified via `pdfinfo`/`pdftotext`) |
| Tests | 167/167 pass; frontend `npm run build` clean |

---

## 1. EXECUTIVE SUMMARY

FLEET-IQ is a genuinely live-capable urban bus intelligence platform with an honest simulation/live separation that is (now) correctly surfaced to the UI. It has a working real-time backbone (WebSocket push, live driver-drowsiness camera pipeline, real DDS subprocess integration), a 100-bus/10-route simulator, a 6-dimension risk engine, rule-based recommendations, scenario orchestration, and a clean PDF/CSV incident export with no third-party PDF dependency.

**Strengths (verified):** honest mode labelling restored; live driver camera produces real frames; DDS subprocess lifecycle is real (spawns PID, SIGTERM, exit-code capture); deadlock in `dds_process.py` fixed (`RLock`); incident export is production-valid; sound system has a kill-switch that actually stops stray `aplay` loops; 167 passing tests; clean production build.

**Weaknesses (verified):**
1. **No authentication** anywhere — every endpoint is unauthenticated; operator "roles" are frontend localStorage only.
2. **No persistence** — incidents, events, DDS sessions, and analytics are in-memory and lost on restart.
3. **Honesty leaks in the event layer** — synthetic passenger-boarding events are labelled `simulation:false / data_source:"live"` (`server.py:435-455`), and camera metadata `fps:30 / 640x480` is hardcoded for any active camera (`camera_manager.py:372-373`).
4. **Scenario bugs** — `ev_energy_crisis` is keyed on `affected_routes` while `dense_fog` defines unused `pothole_detection_mult`/`siren_sensitivity_boost` flags; the energy-crisis branch logic is dead in normal operation (`scenarios.py:232`).
5. **`multi_camera` is structurally unreachable** — camera manager configures it but the live/streaming path never drives a second slot.
6. **AI "models" are mostly arithmetic** — only driver drowsiness is a real CV pipeline; pothole/cabin detectors are honest placeholders; eta/demand/predictive-health are tuned heuristics presented as models.

**Maturity verdict:** Solid **Alpha** with select **Beta** components (live video, WebSocket, exports). Gaps are mostly hardening (auth, persistence, honest labelling, multi-camera), not architecture. Estimated category-weighted overall score: **~61/100**.

---

## 2. CURRENT ARCHITECTURE

```
┌───────────────────────────────────────────────────────────────────┐
│ bus_node/  (per-vehicle Docker-ish agent)                         │
│   agent.py, utils/alert_manager.py (muted kill-switch),           │
│   generated_audio/ (aplay tones), cascade assets                  │
└───────────────┬───────────────────────────────────────────────────┘
                │ JSON over HTTP / WebSocket (PROTO-001 connected)
┌───────────────▼───────────────────────────────────────────────────┐
│ control_centre/backend/  (single Python process, port 5001)       │
│   server.py          ~2,000-line monolith: REST + REST fallback   │
│   data_store.py      in-memory runtime (no persistence)           │
│   simulator.py       tick engine: 100 buses, 10 MTC routes        │
│   websocket_handler.py  WS push on :8765                          │
│   risk_engine.py     6-dim weighted risk (driver/vehicle/load/    │
│                      speed/occupancy/history)                     │
│   eta.py, demand.py, predictive_health.py, road_risk.py           │
│   scenarios.py       6 named scenarios + flag orchestrator        │
│   recommendations.py rule-based action generator                  │
│   incident_export.py CSV + pure-Python PDF (no deps)              │
│   ai/  camera_manager, driver/driver_drowsiness (real CV),        │
│        road/pothole_detector, cabin/cabin_detector (placeholders) │
│        dds/dds_process.py (subprocess mgr), dds/dds_log_reader.py │
└───────────────┬───────────────────────────────────────────────────┘
                │ REST (fetch API)   │ WebSocket :8765    │ subprocess SIGTERM
┌───────────────▼──────────────────┐──────────────────────▼─────────┐
│ frontend/ (React + Vite :5173)   │   /home/rohith/Documents/D.D.S  │
│ 11 pages, modeContext badge,     │   DriverDrowsinessDetectionSystem
│ api.js client, chart libs        │   (external DDS binary, live)   │
└──────────────────────────────────┴────────────────────────────────┘
```

Deployment: two processes — backend (`server.py --start-mode live|simulation`) and Vite dev server. Electron/hand-tracking and MCP-surface references exist in older root docs but are **not** part of the current running system.

---

## 3. IMPLEMENTED FEATURES (fully working)

| Feature | Where | Verification |
|---|---|---|
| Live/simulation mode switch with honest flags | `server.py`, `data_store.ModeState` | curl — sim mode reports `simulation:true`; live reports `false` |
| Live driver camera — real frame pipeline | `ai/camera_manager.py` + `ai/driver/driver_drowsiness.py` | stream shows face, EAR 0.54, NORMAL |
| Auto-start driver camera on live boot | `server.py:_auto_start_driver_camera()` | live boot → camera active/connected |
| WebSocket real-time push | `websocket_handler.py` :8765 | pushes live-mode events |
| Simulator (100 buses, 10 MTC routes, tick) | `simulator.py` | simulation mode returns full fleet |
| Risk engine (6 dims, weighted) | `risk_engine.py` | 167 tests cover scoring |
| Scenarios (6 named, orchestration) | `scenarios.py` | active scenario catalog API |
| Incident export CSV + PDF (pure Python) | `incident_export.py` + `GET /api/incidents/export` | verified 200 + valid multi-page PDF |
| Operator identity + role UI (Operator/Supervisor/Admin) | `Incidents.jsx` (localStorage) | role-gated resolve/edit |
| DDS subprocess launch/stop/status/logs | `ai/dds/dds_process.py` + `/api/dds/subprocess/*` + `/api/dds/logs` | spawned real PID, SIGTERM exit -15 |
| Stale live-node cleanup on mode switch | `ModeState.clear_live_nodes()` | sim mode no longer inherits PROTO-001 |
| Sound kill-switch (muted at request) | `alert_manager.muted=True`, `CallCenter.jsx SOUND_ENABLED=false` | 0 stray `aplay` under CRITICAL/WARNING update |
| Backend test suite (167) + clean production build | `backend/tests/`, `npm run build` | green |

---

## 4. PARTIALLY IMPLEMENTED

1. **Multi-camera mode** — camera manager *can* report `mode:multi_camera` and holds slot config, but the driver/live streaming loop only ever runs the single driver slot; the second camera never opens/streams. Effectively a config flag with no runtime path.
2. **Cabin/occupancy camera** — `cabin_detector.py` exists but is a placeholder (no live loop, no event emission wired to it).
3. **Live-mode fleet provisioning** — transitioned to live mode yields exactly one bus (`PROTO-001`); there is no documented path to attach additional physical buses.
4. **Export filters** — CSV/PDF accept severity/status/bus_id/data_source but no date-range or pagination; data is in-memory only.
5. **Operator roles** — enforced only in the frontend; backend has no role or auth layer (any client can call any endpoint).
6. **Incident ↔ analytics integration** — incidents exist and export, but do not feed risk/history analytics.
7. **DDS integration depth** — engine CALIBRATE/MONITOR buttons and subprocess LAUNCH/STOP work, but subprocess state is not fused into page-level alerts/risk (yet).

---

## 5. SIMULATION FEATURES (honest, verified)

- 100 buses, 10 MTC route graph, per-tick movement, dwell/boarding logic.
- 6 scenarios with per-flow flag fuzzing (Heatwave, Dense Fog, Major Incident, EV Energy Crisis, Replay of past incidents, Fatigue Wave).
- Simulated risk scoring, ETA, predictive health, demand, recommendations — all feeding the same UI.
- Label discipline: backend endpoints return `simulation:true` + `mode` correctly (verified in sim-mode curls). UI shows a SIM/"simulation" badge via `modeContext`.

---

## 6. LIVE FEATURES (verified against running instance)

- **Single driver camera** (webcam `/dev/video0`): face detection, eye-AR drowsiness classifier, state machine (NORMAL/BLINKING/TIRED/ASLEEP), audio curb hooks via `alert_manager`.
- **Live bus agent** `PROTO-001`: connects over HTTP; receives camera/driver state; pushes events over WS; live mode token bus cycles stops (boarding/dwell logic real).
- **DDS external system**: LAUNCH spawns the real D.D.S binary; MONITOR streams its output; STOP sends SIGTERM; session summary is parsed into FLEET-IQ incidents via `dds_log_reader.py`. Verified `phase:idle` when stopped; refused while sound is muted (409) — honest coupling.
- **Incident ingestion + export** in live mode: `data_source:"live"` incidents export correctly.

---

## 7. FRONTEND / UI INVENTORY

**Routes (11):** Dashboard `/`, LiveFleet `/fleet`, BusDetails `/fleet/:busId`, CallCenter `/calls`, Incidents `/incidents`, RoadIntelligence `/roads`, VehicleHealth `/health`, DriverSafety `/driver-safety`, LoadManagement `/load-management`, Analytics `/analytics`, Settings `/settings`.

**Key components:** `CameraFeed.jsx` (LiveCameraGrid + DdsConsole: subprocess status/pid/uptime, LAUNCH/STOP, session summary), `CallCenter.jsx` (SOUND_ENABLED kill-switch), Incidents (roles + export), `lib/modeContext.jsx` (mode/SIM badge), `api.js` (typed client; addExport/filter methods present).

**Asset tools:** chart libs for analytics; a map component; no dashboard alerting page (incidents are not surfaced on Dashboard).

**Issues found:** no auth gating anywhere; operator role is localStorage (spoofable, silently lost); translations are visible but incomplete; DdsConsole state only polls (no WS push for subprocess phase); no offline handling (server restart shows stale UI states).

---

## 8. AI / ML INVENTORY

| Module | Type | Honest? | Notes |
|---|---|---|---|
| `driver_drowsiness.py` | Real CV pipeline | Yes | face detect + eye-AR + state machine; wired to live camera; real |
| `camera_manager.py` | Manager/scheduler | Mostly | dynamic slot scheduling is real; `fps:30`/`640x480` labels are hardcoded (`:372-373`) |
| `pothole_detector.py` | Cascade + classifier + heuristics | Honest placeholder | real file I/O, but accuracy claims are heuristic; not a trained deep model |
| `cabin_detector.py` | Placeholder | Yes | stub detector, not live |
| `dds_process.py` / `dds_log_reader.py` | Subprocess integration | Yes | real external system; integration layer is live |
| `risk_engine.py` | Arith./heuristic (correctly described) | Yes | 6 dims: driver30/vehicle20/load15/speed10/occupancy10/history15 |
| `eta.py` | Heuristic ETA | Mostly | `_get_roadwork_friction` is a placeholder return; no real traffic feed |
| `demand.py`, `predictive_health.py`, `road_risk.py` | Heuristic (trends, thresholds) | Yes | deterministic arithmetic tuned on history/flags |
| `recommendations.py` | Rule-based | Yes | deterministic rules |

**Net:** 1 real DL-adjacent CV pipeline (drowsiness), 1 real external ML system (DDS), the rest is transparent first-principles engineering. Documentation should say "heuristics" not "models" to stay honest.

---

## 9. GAP ANALYSIS

| # | Gap | Priority | Effort | Detail |
|---|---|---|---|---|
| 1 | No auth/authorization | P0 | M | Every endpoint open; roles are frontend-fiction. Auth needed before any real deployment. |
| 2 | No persistence (SQLite) | P0 | M | Incidents/events/sessions lost on restart; exports therefore only capture current session. |
| 3 | Server shutdown orphans DDS subprocess | P0 | S | Backend exit takes the DDS child down violently; no graceful handler. |
| 4 | Honesty: passenger events labelled live/sim-false | P1 | S | Synthetic boarding events emit `simulation:false, data_source:"live"` (`server.py:435-455`) — violates the project's own honesty rule. |
| 5 | Honesty: hardcoded camera fps/resolution | P1 | S | `fps:30` / `640x480` reported for any active camera (`camera_manager.py:372-373`). |
| 6 | Scenario flag bugs | P1 | S | `ev_energy_crisis` keyed wrong (`affected_routes` vs scenario key) → branch dead; `dense_fog` defines unused `pothole_detection_mult`/`siren_sensitivity_boost`. |
| 7 | `multi_camera` unreachable | P1 | M | Config exists, runtime path does not; second slot never streams. |
| 8 | No incidents/driver-risk dashboard surface | P1 | M | Methods exist; Dashboard doesn't surface incident alerts (only CallCenter). |
| 9 | Sound is fully disabled | P1 | S | Kill-switch works by design; requires deliberate move to an enabled profile when user says "on". |
| 10 | DDS path hardcoded | P2 | S | Absolute `/home/rohith/Documents/D.D.S/...` path in `dds_process.py`. |
| 11 | `server.py` monolith (~2,000 lines) | P2 | M | Routes + data + logic in one file; refactor into blueprints/services. |
| 12 | No subprocess/export API tests | P2 | M | 167 tests cover scoring/sim; none cover DDS subprocess or export endpoints. |
| 13 | Duplicate/stale root docs | P2 | S | PLAN.md, ai_urban_management.md, URBAN_INTELLIGENCE_OVERVIEW.md partially superseded by PROJECT_CONTEXT.md. |
| 14 | ETA roadwork friction placeholder | P2 | S | `_get_roadwork_friction` not implemented; ETA ignores real traffic. |
| 15 | WebSocket has no auth/heartbeat | P2 | M | Open channel; no reconnection/backoff in frontend. |
| 16 | Alerts not pushed over WS to dashboard | P3 | M | Dashboard would benefit from alert_stream; currently only incident lists poll. |

---

## 10. TECHNICAL DEBT

1. **Frozen search space:** `server.py` grows organically; `camera_status_data` (line ~1298) rebuilds schema with hardcoded metadata instead of reading real sensor metadata.
2. **Deadlock regression risk:** `dds_process.py` RLock fix resolved `start/stop` hangs; endpoint tests are missing so a regression could silently hang again.
3. **Mutable global state:** `data_store`/`ModeState` singletons mutate across mode switches; `clear_live_nodes()` mitigates the known case but future globals can leak stale live nodes.
4. **Hardcoded paths:** DDS project path, device `/dev/video0` assumption, generated-audio tones.
5. **Frontend identity fiction:** operator role/name in localStorage is the only "auth".
6. **Un-versioned schema:** WS event payload shape has no version field; future UI/backend skew is undetectable.
7. **Scenario flag table mismatch:** flags declared (dense_fog's `pothole_detection_mult`, `siren_sensitivity_boost`) vs flag consumers (`scenarios.py:223` writes `pothole_surge_mult` from a different key) — dead config.

---

## 11. DUPLICATION / OLD CODE

- **Root docs overlap:** `PLAN.md`, `ai_urban_management.md`, `URBAN_INTELLIGENCE_OVERVIEW.md`, `SESSION_RECALL.md`, `SESSION_CHANGELOG.md` — several describe an older Electron/ORB/hand-tracking/MCP vision that is NOT the running system; `PROJECT_CONTEXT.md` is the only current source of truth.
- **Sound control duplicated:** `alert_manager.py` (backend/bus_node) and `CallCenter.jsx` both own mute state; two switches must stay in sync (currently both intentionally off).
- **Event-build duplication:** passenger moments and generic event builders still construct `data_source`/`simulation` inline in server.py rather than via the unified honest-labelling helper used elsewhere.
- **Camera slot logic:** slot activation/teardown logic repeated in camera_manager spots vs the single `_auto_start_driver_camera()` path in server.py.
- **Unused scenario flags** (section 10.7) are dead code awaiting cleanup.

---

## 12. PRIORITY ROADMAP (ranked)

1. **P0 — Hardening for real use:** add lightweight auth (token/session); add SQLite persistence for incidents/events/last-DDS-session; graceful SIGINT/SIGTERM handler in `server.py` that SIGTERMs the DDS child.
2. **P1 — Honesty fixes (small, high-value):** relabel synthetic passenger events (`simulation:true` if generated); source real fps/resolution from the capture backend instead of hardcoding; fix `ev_energy_crisis` keying + act on dense-fog flags.
3. **P1 — Multi-camera landing:** wire the second slot into the live streaming path so `mode:multi_camera` is genuinely reachable.
4. **P1 — Dashboard incident surface:** push incidents/alerts over WS to Dashboard with severity chips.
5. **P1 — Sound profile:** when you say "sound on", move both switches to a profile where they stay in sync (still silent by default).
6. **P2 — Monolith refactor:** split `server.py` into blueprints (fleet/camera/incidents/dds/analytics) + shared labels helper.
7. **P2 — Test coverage:** add endpoint tests for export (CSV/PDF bytes), DDS subprocess lifecycle, camera mode transitions, scenario flag application.
8. **P2 — Docs consolidation:** fold PLAN/OVERVIEW/changelog facts into `PROJECT_CONTEXT.md`; delete or archive superseded docs; rename "model" language to "heuristics" where applicable.
9. **P3 — WS hardening:** auth + heartbeat + reconnection in the frontend client; version the event schema.

---

## 13. SCORECARD (0–100)

| Category | Score | Rationale |
|---|---|---|
| Real-time infrastructure (WS, live streams) | 75 | Working WS + real video; no heartbeat/reconnect/auth |
| Simulation fidelity | 80 | 100 buses/10 routes, scenarios, honest labels |
| Risk & analytics engine | 70 | 6-dim scoring + rule recommendations; heuristic not ML |
| Live AI/vision | 55 | 1 real CV pipeline (drowsiness) + real DDS; placeholders elsewhere |
| Scenario system | 62 | Orchestrates well; flag bugs and dead branches |
| Frontend/UX | 68 | 11 polished pages, mode badge, exports; no alerts page, no auth |
| API design | 60 | Consistent JSON; monolith, unversioned, unauthenticated |
| Data persistence | 20 | Everything in-memory |
| Security | 25 | Zero auth; roles are UX fiction |
| Testing | 65 | 167 unit tests; zero integration tests for live/export/subprocess paths |
| Documentation | 72 | PROJECT_CONTEXT current; stale/dead docs remain |
| **Overall (weighted)** | **~61** | Solid alpha; hardening of auth/persistence/labels closes the gap |

---

## 14. WHAT WE SHOULD DO NEXT (recommended, in order)

1. **Add a lightweight auth layer** and enforce it on all `/api/*` routes (token issued at boot or via `/api/auth/login` with a per-user key). Do this before anything public-facing.
2. **Introduce SQLite persistence** for incidents + events (+ optional last-session snapshot) so CSV/PDF exports and analytics survive restarts.
3. **Add a server shutdown handler** that cleanly SIGTERMs the DDS subprocess and flushes state.
4. **Fix the honesty leaks:** synthetic passenger events → `simulation:true`; camera fps/resolution read from the capture loop, not constants.
5. **Fix scenario flag plumbing** (`ev_energy_crisis`, dense-fog multipliers) and add a scenario unit test asserting each flag has an applied effect.
6. **Land `multi_camera`** for real (second live slot) or remove the mode to avoid dead UI states.
7. **Surface incidents/alerts on the Dashboard** via the existing WS channel.
8. **Consolidate docs** into `PROJECT_CONTEXT.md`, filter out pre-2.0 (Electron/ORB/MCP) prose, and rename heuristic "models" to "heuristics".

*Audit is read-only; no files were changed. Waiting for your direction on which of the above to execute next.*