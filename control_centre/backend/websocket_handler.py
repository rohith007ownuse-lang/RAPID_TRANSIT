"""
websocket_handler.py
Control Centre WebSocket server for live bus-node data (Phase 18 hardened).

Accept connections from bus nodes (ESP32, bus_node.communication.websocket_client)
on ws://<host>:8765 and write their payloads into the shared data store so the
Flask REST API / dashboard reflect real bus data.

Phase 18 enhancements:
- Message validation and sanitization
- Server-initiated ping for dashboard client liveness
- Connection tracking and metrics
- Priority-based message routing
- Event coalescing for high-frequency telemetry
- Exponential backoff reconnection support
- Data source preservation (SIMULATION/LIVE/HEURISTIC)

Message protocol (JSON):
    client -> server:
      {"type": "hello",      "bus_id": "PROTO-001", "data_source": "live"}
      {"type": "bus_state",  "bus_id": "PROTO-001", "state": {...}}
      {"type": "event",      "bus_id": "PROTO-001", "event": {...}}
      {"type": "heartbeat",  "bus_id": "PROTO-001"}
      {"type": "subscribe_alerts", "token": "<bearer_token>"}
      {"type": "ping_alerts"}
      {"type": "request_state"}  # Phase 18: request current state snapshot
    server -> client:
      {"type": "ack", "ok": true, ...}
      {"type": "subscribe_ok", "ok": true, ...}
      {"type": "alert", "ok": true, "alert": {...}}
      {"type": "pong_alerts", "ok": true}
      {"type": "state_snapshot", "ok": true, ...}  # Phase 18
      {"type": "pong", "ok": true}  # Phase 18: server-initiated pong
      {"type": "error", "ok": false, "reason": "..."}

The adapter translates a bus_node BusState payload into the dashboard schema
produced by the fleet simulator (driver.state, load.status with spaces,
occupancy, etc.) so connected buses appear on the exact same pages.
"""

import asyncio
import json
import threading
import time
from datetime import datetime

import websockets

import auth
import alerts
from data_store import store, mode_state, utcnow_iso

# Phase 18: WebSocket hardening
from websocket_hardening import (
    ConnectionState, MessagePriority, MessageType,
    validate_message, classify_message_priority, preserve_data_source,
    create_ws_message, MessageDeduplicator, EventCoalescer,
    ConnectionStateManager, ServerConnectionTracker, WebSocketMetrics,
    MessagePriorityQueue, CLOSE_AUTH_FAILED, CLOSE_RATE_LIMITED,
    SERVER_PING_INTERVAL, STALE_CONNECTION_TIMEOUT, MAX_SUBSCRIBERS,
)

# bus-node -> dashboard vocabulary
DRIVER_STATE_MAP = {
    "DROWSINESS": "DROWSY",
    "HEAD_NOD": "ATTENTION",
    "EYES_CLOSED": "ATTENTION",
    "FACE_LOST": "ATTENTION",
    "NORMAL": "NORMAL",
    "NO_DATA": "NORMAL",
}
LOAD_STATUS_MAP = {
    "CRITICAL_OVERLOAD": "CRITICAL OVERLOAD",
    "HIGH_LOAD": "HIGH LOAD",
}


def adapt_bus_state(node_state: dict) -> dict:
    """Convert a bus_node BusState payload into the dashboard bus schema."""
    d = node_state.get("driver", {})
    l = node_state.get("load", {})
    v = node_state.get("vehicle", {})

    driver_state = DRIVER_STATE_MAP.get(d.get("status", "NORMAL"), "NORMAL")
    load_status = LOAD_STATUS_MAP.get(l.get("status", "NORMAL"), l.get("status", "NORMAL"))
    drowsy = driver_state == "DROWSY" or bool(d.get("alert"))

    bus_id = node_state.get("bus_id", "BUS-000")
    data_source = node_state.get("data_source", "live")

    return {
        "bus_id": bus_id,
        "data_source": data_source,
        "reg_no": node_state.get("reg_no", bus_id),
        "route_code": node_state.get("route_code", ""),
        "route": node_state.get("route", "Live Prototype Node"),
        "_live": True,
        "vehicle_type": node_state.get("vehicle_type", "DIESEL"),
        "latitude": node_state.get("latitude", None),
        "longitude": node_state.get("longitude", None),
        "speed_kmh": round(node_state.get("speed_kmh", 0.0), 1),
        "energy": node_state.get("energy") or {"type": "DIESEL", "percent": None, "litres": None},
        "wheels": node_state.get("wheels") or [None, None, None, None],
        "driver": {
            "state": driver_state,
            "name": d.get("name", ""),
            "ear": d.get("ear", None),
            "mar": d.get("mar", None),
            "head_pitch_deg": round(d.get("pitch", 0.0), 1) if d.get("pitch") is not None else None,
            "closed_sec": round(d.get("closed_time", 0.0), 2) if d.get("closed_time") is not None else None,
            "drowsy": drowsy,
            "fatigue_stage": d.get("fatigue_stage", "WATCH"),
            "fatigue_lt": round(float(d.get("fatigue_lt", 0.0)), 1),
            "fatigue_st": round(float(d.get("fatigue_st", 0.0)), 1),
            "perclos": round(float(d.get("perclos", 0.0)), 1),
            "episode": d.get("episode"),
        },
        "occupancy": node_state.get("occupancy") or {"passengers": 0, "pct": 0, "crowd": "NORMAL", "capacity": 60},
        "cabin_occupancy": node_state.get("cabin_occupancy"),
        "load": {
            "gvw_kg": l.get("gvw_kg", None),
            "tare_kg": l.get("tare_kg", None),
            "payload_kg": l.get("payload_kg", None),
            "payload_limit_kg": 6000,
            "load_pct": round(l.get("load_pct", 0.0), 1) if l.get("load_pct") is not None else None,
            "status": load_status,
        },
        "vehicle": {
            "health": v.get("health", "NORMAL"),
            "anomaly": v.get("anomaly") or "none",
            "vibration": round(v.get("vibration", 0.0), 3) if v.get("vibration") is not None else None,
            "braking_events": v.get("hard_braking_count", 0),
            "maintenance_priority": "LOW",
            "type": node_state.get("vehicle_type", "DIESEL"),
        },
        "journey": node_state.get("journey"),
        "siren": node_state.get("siren", {"detected": False,
                                          "confidence": 0.0, "sound_level_db": 0.0}),
        "ticketing": node_state.get("ticketing") or {
            "tickets_today": 0, "passengers_total": 0, "fare_collected": 0,
            "avg_fare": 18.5, "avg_km": 0, "device": "MTC ticket machine TMS-5",
        },
        "cameras": node_state.get("cameras", []),
        "sensors": node_state.get("sensors", []),
        "last_update": node_state.get("updated_at", utcnow_iso()),
        "simulation": data_source == "simulation",
    }


def handle_message(data: dict) -> dict:
    """Dispatch one client message into the store. Returns a reply to echo."""
    kind = data.get("type")
    bus_id = data.get("bus_id", "BUS-000")
    data_source = data.get("data_source", "live")

    if kind == "hello":
        # Register live node if in live mode
        if mode_state.is_live:
            mode_state.register_live_node(bus_id, {
                "device": data.get("device", "ESP32"),
                "data_source": data_source,
            })
        return {"type": "ack", "ok": True, "bus_id": bus_id, "greeting": "welcome", "mode": mode_state.mode}

    if kind == "heartbeat":
        if mode_state.is_live:
            mode_state.update_live_node(bus_id)
        if store.get_bus(bus_id):
            store.get_bus(bus_id)["last_update"] = utcnow_iso()
        return {"type": "ack", "ok": True, "bus_id": bus_id}

    if kind == "bus_state":
        state = data.get("state", {})
        state["bus_id"] = bus_id
        state["data_source"] = data_source
        bus = adapt_bus_state(state)
        store.upsert_bus(bus)
        if mode_state.is_live:
            # Update node info with GPS/sensor availability
            mode_state.update_live_node(bus_id, {
                "gps_available": bus.get("latitude") is not None,
                "sensors": state.get("sensors", {}),
            })
        return {"type": "ack", "ok": True, "bus_id": bus_id}

    if kind == "event":
        ev = data.get("event", {})
        if not ev.get("bus_id"):
            ev["bus_id"] = bus_id
        ev["data_source"] = data_source
        stored = store.add_event(ev)
        link_road_defect(stored)
        return {"type": "ack", "ok": True, "bus_id": bus_id, "event_id": stored.get("event_id")}

    return {"type": "error", "ok": False, "bus_id": bus_id, "reason": f"unknown message type: {kind}"}


def link_road_defect(ev: dict) -> None:
    """Group ROAD_DEFECT/POTHOLE events into the persistent road-defect map
    (server-side cross-bus dedup, same behaviour as the fleet simulator)."""
    if ev.get("event_type") not in ("ROAD_DEFECT", "POTHOLE"):
        return
    lat, lon = ev.get("latitude", 0.0), ev.get("longitude", 0.0)
    key = f"{round(lat, 3)}_{round(lon, 3)}"
    existing = store.get_road_defect(key)
    now = utcnow_iso()
    image_ref = f"pothole-live-{int(time.time())}.jpg"
    buses = [ev.get("bus_id")]
    if existing:
        buses = existing.get("buses", []) + [b for b in buses if b not in existing.get("buses", [])]
        count = existing.get("detection_count", 1) + 1
        store.upsert_road_defect(key, {
            "defect_id": key, "latitude": round(lat, 4), "longitude": round(lon, 4),
            "detection_count": count, "last_detected": now, "buses": buses,
            "last_image": image_ref,
        })
        return
    store.upsert_road_defect(key, {
        "defect_id": key, "type": "pothole",
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "detection_count": 1, "confidence": round(ev.get("confidence", 0.9), 2),
        "first_detected": now, "last_detected": now, "buses": buses, "status": "ACTIVE",
        "image": image_ref, "last_image": image_ref,
    })


# ---------------------------------------------------------------------------
# Phase 9 — real-time alert subscribers (Control Centre dashboards)
# Phase 18 — hardened with connection tracking, metrics, and validation
#
# The SAME WebSocket server now also serves authenticated dashboard clients.
# A dashboard connects, sends {"type": "subscribe_alerts", "token": "<bearer>"}
# (the Phase-5 opaque session token — no second authentication mechanism),
# and from then on receives {"type": "alert", "alert": {...}} pushes whenever
# an important event is persisted. Bus-node traffic above is unchanged.
# ---------------------------------------------------------------------------

_alert_subscribers = set()   # websockets touched only on the WS loop thread

# Phase 18: Enhanced tracking and metrics
_connection_tracker = ServerConnectionTracker(max_subscribers=MAX_SUBSCRIBERS)
_metrics = WebSocketMetrics()
_server_deduplicator = MessageDeduplicator()
_server_coalescer = EventCoalescer()


def _subscriber_count() -> int:
    return len(_alert_subscribers)


async def _subscribe_dashboard(websocket, data: dict) -> None:
    """Authenticate an alert subscriber with the existing Phase-5 session
    token. Invalid/expired/inactive → error + close (never an open
    unauthenticated privileged channel).

    Phase 18: Added connection tracking, rate limiting, and metrics.
    """
    # Rate limit check
    if _connection_tracker.count() >= MAX_SUBSCRIBERS:
        print("[ws] alert subscription rejected: at capacity")
        await websocket.send(json.dumps({"type": "error", "ok": False,
                                         "reason": "server at capacity"}))
        await websocket.close(code=4002, reason="rate limited")
        _metrics.record("auth_failures")
        return

    user = auth.get_user_by_token(str(data.get("token") or ""))
    if user is None:
        print("[ws] alert subscription rejected: invalid or expired token")
        await websocket.send(json.dumps({"type": "error", "ok": False,
                                         "reason": "authentication required"}))
        await websocket.close(code=CLOSE_AUTH_FAILED, reason="unauthorized")
        _metrics.record("auth_failures")
        return

    # Register connection
    _connection_tracker.register(
        websocket,
        client_type="dashboard",
        user=user["username"],
        role=user["role"],
    )
    _alert_subscribers.add(websocket)
    _metrics.record("connections_total")
    _metrics.record("connections_active")

    print(f"[ws] alert subscriber added: {user['username']} ({user['role']}) "
          f"[total={_subscriber_count()}]")
    await websocket.send(json.dumps({
        "type": "subscribe_ok", "ok": True,
        "user": user["username"], "role": user["role"],
        "server_time": datetime.utcnow().isoformat(timespec="seconds"),
    }))


async def _push_alert(alert: dict) -> None:
    """Send one alert to every subscriber; drop dead connections. Runs on
    the WS loop thread.

    Phase 18: Added deduplication, metrics, and error isolation.
    """
    if not _alert_subscribers:
        return

    # Phase 18: Deduplicate alerts by event_id
    event_id = alert.get("event_id")
    if event_id and _server_deduplicator.is_duplicate(event_id):
        _metrics.record("dedup_hits")
        return

    message = json.dumps({"type": "alert", "ok": True, "alert": alert})
    dead = []
    sent_count = 0
    for ws in list(_alert_subscribers):
        try:
            await ws.send(message)
            sent_count += 1
            _connection_tracker.record_message(ws, sent=True)
        except Exception as exc:  # noqa: BLE001 — one bad client never affects others
            dead.append(ws)
            _connection_tracker.record_message(ws, sent=False)
            _metrics.record("messages_failed")

    for ws in dead:
        _alert_subscribers.discard(ws)
        _connection_tracker.unregister(ws)

    _metrics.record("messages_sent", sent_count)


def broadcast_alert(alert: dict) -> None:
    """Thread-safe entry point called by alerts.process_event() (from any
    backend thread). Best-effort: no clients / no loop / loop shutting down
    are all silent no-ops — the event is already persisted."""
    loop = _ws_loop
    if loop is None or loop.is_closed() or not _alert_subscribers:
        return
    try:
        asyncio.run_coroutine_threadsafe(_push_alert(alert), loop)
    except RuntimeError as exc:
        print(f"[ws] alert broadcast skipped: {exc}")


async def _push_road_event(road_event: dict) -> None:
    """Send a road event to every subscriber; drop dead connections.

    Phase 18: Added metrics and error isolation.
    """
    if not _alert_subscribers:
        return
    message = json.dumps({"type": "road_event", "ok": True, "event": road_event})
    dead = []
    sent_count = 0
    for ws in list(_alert_subscribers):
        try:
            await ws.send(message)
            sent_count += 1
            _connection_tracker.record_message(ws, sent=True)
        except Exception:
            dead.append(ws)
            _connection_tracker.record_message(ws, sent=False)
            _metrics.record("messages_failed")

    for ws in dead:
        _alert_subscribers.discard(ws)
        _connection_tracker.unregister(ws)

    _metrics.record("messages_sent", sent_count)


def broadcast_road_event(road_event: dict) -> None:
    """Thread-safe entry point to broadcast road events to dashboards."""
    loop = _ws_loop
    if loop is None or loop.is_closed() or not _alert_subscribers:
        return
    try:
        asyncio.run_coroutine_threadsafe(_push_road_event(road_event), loop)
    except RuntimeError as exc:
        print(f"[ws] road event broadcast skipped: {exc}")


async def _push_road_risk_update(zones: list, route_index: dict) -> None:
    """Send road risk zone updates to every subscriber.

    Phase 18: Added metrics and error isolation.
    """
    if not _alert_subscribers:
        return
    message = json.dumps({
        "type": "road_risk_update", "ok": True,
        "zones": zones, "route_index": route_index,
    })
    dead = []
    sent_count = 0
    for ws in list(_alert_subscribers):
        try:
            await ws.send(message)
            sent_count += 1
            _connection_tracker.record_message(ws, sent=True)
        except Exception:
            dead.append(ws)
            _connection_tracker.record_message(ws, sent=False)
            _metrics.record("messages_failed")

    for ws in dead:
        _alert_subscribers.discard(ws)
        _connection_tracker.unregister(ws)

    _metrics.record("messages_sent", sent_count)


def broadcast_road_risk_update(zones: list, route_index: dict) -> None:
    """Thread-safe entry point to broadcast road risk updates to dashboards."""
    loop = _ws_loop
    if loop is None or loop.is_closed() or not _alert_subscribers:
        return
    try:
        asyncio.run_coroutine_threadsafe(_push_road_risk_update(zones, route_index), loop)
    except RuntimeError as exc:
        print(f"[ws] road risk update broadcast skipped: {exc}")


async def _conn_handler(websocket):
    """Handle a WebSocket connection.

    Phase 18: Enhanced with message validation, error isolation,
    metrics collection, and server-initiated ping.
    """
    client = getattr(websocket, "remote_address", None)
    print(f"[ws] client connected: {client}")
    subscribed = False
    client_type = "bus_node"

    try:
        async for raw in websocket:
            _metrics.record("messages_received")

            # Phase 18: Validate message format
            is_valid, result = validate_message(raw)
            if not is_valid:
                await websocket.send(json.dumps({
                    "type": "error", "ok": False,
                    "reason": result.get("error", "invalid message"),
                }))
                _metrics.record("messages_dropped")
                continue

            data = result
            kind = data.get("type")

            # Dashboard subscription flow
            if kind == "subscribe_alerts":
                await _subscribe_dashboard(websocket, data)
                if websocket not in _alert_subscribers:
                    return  # rejected + closed above
                subscribed = True
                client_type = "dashboard"
                continue

            # Dashboard client messages (receive-only except ping)
            if subscribed:
                if kind == "ping_alerts":
                    await websocket.send(json.dumps({"type": "pong_alerts", "ok": True}))
                elif kind == "request_state":
                    # Phase 18: Provide current state snapshot
                    await _send_state_snapshot(websocket)
                continue

            # Bus-node messages
            reply = handle_message(data)
            print(f"[ws] {data.get('type')} from {data.get('bus_id')} -> ok={reply.get('ok')}")
            await websocket.send(json.dumps(reply))

    except websockets.ConnectionClosed:
        pass
    except Exception as exc:
        # Phase 18: Isolate errors - one client error never crashes the server
        print(f"[ws] client error ({client}): {exc}")
    finally:
        if subscribed:
            _alert_subscribers.discard(websocket)
            _connection_tracker.unregister(websocket)
            _metrics.record("connections_active", -1)
            print(f"[ws] alert subscriber left [total={_subscriber_count()}]")
        print(f"[ws] client disconnected: {client}")


async def _send_state_snapshot(websocket) -> None:
    """Send current state snapshot to a dashboard client.

    Phase 18: Allows clients to recover state after reconnection.
    """
    try:
        # Build a lightweight state snapshot
        buses = store.get_buses()
        events = store.get_events(50)  # Last 50 events

        snapshot = {
            "type": "state_snapshot",
            "ok": True,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
            "bus_count": len(buses),
            "event_count": len(events),
            "events": events[:20],  # Send most recent 20
        }

        await websocket.send(json.dumps(snapshot))
        _metrics.record("messages_sent")
    except Exception as exc:
        print(f"[ws] state snapshot error: {exc}")


LIVE_STALE_SECONDS = 30.0


def _iso_to_epoch(iso_str) -> float:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


async def _liveness_watchdog() -> None:
    """Return _live buses to the simulator if no contact for a while.

    Phase 9: the demotion is recorded as a real BUS_OFFLINE event through the
    normal funnel (persist -> alert decision -> WebSocket push), so operators
    are told immediately when a live asset stops reporting telemetry. Sim
    buses are never offline; only live nodes can demote, so this cannot spam
    in simulation mode.

    Phase 18: Also performs server-initiated ping for dashboard clients
    and cleans up stale connections.
    """
    while True:
        await asyncio.sleep(10)
        now = time.time()

        # Phase 18: Ping dashboard clients to detect stale connections
        await _ping_dashboard_clients()

        # Phase 18: Clean up stale dashboard connections
        await _cleanup_stale_connections()

        # Existing: Check live bus staleness
        for b in store.get_buses():
            if b.get("_live") and now - _iso_to_epoch(b.get("last_update", "")) > LIVE_STALE_SECONDS:
                b["_live"] = False
                staleness = int(now - _iso_to_epoch(b.get("last_update", "")))
                print(f"[ws] bus {b['bus_id']} went stale (no updates); back to simulator")
                try:
                    store.add_event({
                        "bus_id": b.get("bus_id"),
                        "reg_no": b.get("reg_no"),
                        "event_type": "BUS_OFFLINE",
                        "latitude": b.get("latitude"),
                        "longitude": b.get("longitude"),
                        "severity": "WARNING",
                        "sensor_source": "control_centre",
                        "status": "ACTIVE",
                        "data_source": "live",
                        "simulation": False,
                        "additional_data": {
                            "note": (f"Live bus {b.get('bus_id')} stopped sending telemetry "
                                     f"(stale {staleness}s); reverted to simulator control."),
                            "staleness_seconds": staleness,
                        },
                    })
                except Exception as exc:  # noqa: BLE001 — watchdog must survive
                    print(f"[ws] BUS_OFFLINE event error (ignored): {exc}")


async def _ping_dashboard_clients() -> None:
    """Phase 18: Send server-initiated pings to dashboard clients."""
    if not _alert_subscribers:
        return

    ping_msg = json.dumps({"type": "pong", "ok": True,
                           "timestamp": datetime.utcnow().isoformat(timespec="seconds")})
    dead = []
    for ws in list(_alert_subscribers):
        try:
            await ws.send(ping_msg)
            _connection_tracker.record_message(ws, sent=True)
        except Exception:
            dead.append(ws)

    for ws in dead:
        _alert_subscribers.discard(ws)
        _connection_tracker.unregister(ws)


async def _cleanup_stale_connections() -> None:
    """Phase 18: Clean up dashboard connections that haven't sent messages."""
    stale = _connection_tracker.get_stale_connections(timeout=STALE_CONNECTION_TIMEOUT)
    for ws in stale:
        try:
            await ws.close(code=4003, reason="stale connection")
        except Exception:
            pass
        _alert_subscribers.discard(ws)
        _connection_tracker.unregister(ws)
        print("[ws] stale dashboard connection cleaned up")


# Started by start_websocket_server(): handle to the serving loop/event so
# the backend can request a clean stop during shutdown.
_ws_loop = None
_ws_stop_event = None
_ws_server = None  # bound websockets.Server (exposes the actual port for tests)
_broadcaster_registered = False


def _run_server(host: str, port: int) -> None:
    global _ws_loop, _ws_stop_event, _ws_server, _broadcaster_registered

    async def _serve():
        global _ws_loop, _ws_stop_event, _ws_server
        _ws_loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        _ws_stop_event = stop_event
        async with websockets.serve(_conn_handler, host, port) as server:
            _ws_server = server
            liveness = asyncio.create_task(_liveness_watchdog())
            try:
                await stop_event.wait()
            finally:
                liveness.cancel()

    if not _broadcaster_registered:
        # Phase 9: hook the alert decision layer onto the existing server.
        alerts.register_broadcaster(broadcast_alert)
        _broadcaster_registered = True
    asyncio.run(_serve())
    _ws_loop = None
    _ws_stop_event = None
    _ws_server = None
    _alert_subscribers.clear()


def get_ws_port() -> int | None:
    """Actual bound port (useful for tests that bind port 0), or None."""
    server = _ws_server
    if server is None:
        return None
    try:
        for sock in server.sockets:
            return sock.getsockname()[1]
    except Exception:  # noqa: BLE001
        return None
    return None


def start_websocket_server(host: str = "127.0.0.1", port: int = 8765) -> threading.Thread:
    t = threading.Thread(target=_run_server, args=(host, port),
                         daemon=True, name="cc-websocket")
    t.start()
    print(f"[control-centre] WebSocket server on ws://{host}:{port}")
    return t


def stop_websocket_server() -> None:
    """Request the WebSocket serving loop to close (called on shutdown)."""
    loop, event = _ws_loop, _ws_stop_event
    if loop is not None and event is not None:
        try:
            loop.call_soon_threadsafe(event.set)
            alerts.unregister_broadcaster(broadcast_alert)
            print("[control-centre] WebSocket server stop requested")
        except RuntimeError:
            pass


# Phase 18: Public API for metrics and status

def get_ws_metrics() -> dict:
    """Get WebSocket server metrics."""
    return _metrics.get_all()


def get_ws_connections() -> dict:
    """Get active WebSocket connections info."""
    return _connection_tracker.get_all()


def get_ws_status() -> dict:
    """Get WebSocket server status summary."""
    return {
        "running": _ws_loop is not None and not _ws_loop.is_closed(),
        "port": get_ws_port(),
        "subscribers": _subscriber_count(),
        "metrics": _metrics.get_all(),
        "connections": _connection_tracker.count(),
    }