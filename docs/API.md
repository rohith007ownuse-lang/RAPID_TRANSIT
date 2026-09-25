# API reference

Base: same origin as the UI. In local dev the Vite proxy forwards `/api` to
`http://127.0.0.1:5001`; in production nginx does the same.

## Auth

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/auth/login` | POST | open | `{username, password}` → opaque bearer token |
| `/api/auth/me` | GET | token | current user |
| `/api/auth/logout` | POST | token | revoke the token server-side |
| `/api/auth/me/password` | POST | token | change own password |
| `/api/auth/users` | GET/POST | admin | list / create users |
| `/api/auth/users/<id>/role\|active\|password` | POST | admin | manage users (last active admin is guarded) |

Send `Authorization: Bearer <token>`. Roles: `operator` < `supervisor` < `admin`.

In **production mode** every read endpoint requires a token. Only
`/api/health` and `/api/auth/login` stay open. In development, read-only
telemetry (overview, buses, events…) is open for the dashboard.

## Core telemetry (representative)

- `GET /api/health` — `{status, simulation, …}` — the liveness probe
- `GET /api/overview` — fleet KPIs
- `GET /api/buses`, `GET /api/buses/<id>` — fleet list and per-bus detail
- `GET /api/events`, `GET /api/fleet/summary` — event log, operator snapshot
- `GET /api/traffic/hotspots` — active congestion red dots; each carries
  `bus_count`, `bus_ids`, `radius_m`, `min_buses`, `duration_sec`

## Intelligence

- `/api/risk`, `/api/buses/<id>/risk` — six-segment risk
- `/api/actions`, `/api/actions/<id>/ack`, `/api/actions/evaluate` — AI actions
- `/api/buses/<id>/timeline` — fatigue timeline
- `/api/eta`, `/api/demand`, `/api/roads/risk`, `/api/buses/<id>/road-threats`
- `/api/gtfs/routes/polylines` — bulk MTC route polylines for the route map
- `/api/health/predictive` — degradation + remaining useful life
- `/api/analytics`, `/api/analytics/operations`, `/api/analytics/incidents-drilldown`
- `/api/system/health`, `/api/system/health/<name>` — subsystem health

## Incidents (lifecycle)

- `/api/incidents`, `/api/incidents/active`, `/api/incidents/summary`
- `/api/incidents/<id>` + `acknowledge` / `investigate` / `resolve` / `close`
  (POST). Acknowledge: any role. Resolve/close: supervisor+.

## Cameras & cabin

- `GET /api/camera/status` — per-slot status (`CONNECTED` / `DISCONNECTED` /
  `DISABLED` / `ERROR`), FPS, errors. Auth required.
- `GET /api/camera/stream/<slot>` — annotated frame for one camera.
- `GET /api/cabin/occupancy` — occupancy estimate; unknown renders as `null`,
  never `0`.
- Camera controls (`test-mode`, `multi-camera`, `start`, `stop`): any role, auth.

## WebSockets

### Bus ingest — `ws://host:8765` (public: `wss://host/ws`)

Bus → server JSON messages: `hello {bus_id}` · `bus_state {bus_id, state}` ·
`event {bus_id, event}` · `heartbeat {bus_id}`. A live bus (`_live: true`)
supersedes its simulated copy; stale >30 s reverts to the simulator. Phase-18
hardening adds reconnection, deduplication, and state resync.

### Camera — `ws://host:8766` (public: `wss://host/ws/camera`)

Token-gated; the subscribe payload carries the token. Streams per-camera
status and frames.

## Response conventions

Every JSON response includes `simulation: true/false` and `mode`. Unknown
values are `null`; loading states render `…`/`—`, never fabricated zeroes.
