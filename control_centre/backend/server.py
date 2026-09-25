"""
server.py
Control Centre backend. Flask REST API serving the (simulated) fleet,
events, road defects, and analytics to the React frontend.

Currently all data is SIMULATED (see simulator.py). In a later phase,
real bus_node data will stream into the same store over WebSocket.
"""

import argparse
import os
import random
import signal
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS

import auth
import alerts
import persistence
from data_store import store, mode_state
from risk_engine import DEFAULT_RISK_WEIGHTS, SEVERITY_LEVELS, bus_risk, fleet_risk, get_risk_history, get_risk_trend, get_risk_coverage
from recommendations import action_store, evaluate_fleet, utcnow_iso
from predictive_health import health_tracker, tick_all, THRESHOLDS, get_health_summary, get_fleet_health_summary, DataSource
from eta import eta_engine, compute_all_etas, get_fleet_eta_summary
from demand import demand_engine, forecast_all, forecast_bus
from demand_intelligence import (
    get_capacity_model, get_occupancy_snapshot, get_demand_pattern,
    get_capacity_pressure, detect_overcrowding, get_route_demand_summary,
    get_fleet_load_summary,
)
from road_risk import road_risk_engine, rebuild_zones, get_leg_threats, get_road_summary
from simulator import FleetSimulator, ROUTES
from websocket_handler import start_websocket_server, stop_websocket_server

app = Flask(__name__)
CORS(app)

app.config["JSON_SORT_KEYS"] = False

_POTHOLE_CACHE = {"key": None, "series": None}

# Global simulator reference for mode switching
_simulator_ref = [None]

# Graceful shutdown control (SIGINT/SIGTERM)
_SHUTDOWN_EVENT = threading.Event()


def _is_shutting_down():
    return _SHUTDOWN_EVENT.is_set()


def _capture_dds_session():
    """Guarantee the final DDS session lands in the shared store.

    Dedupes on (event_type, timestamp, details) so a session only captured
    once even if the live event callback already ingested parts of it.
    """
    try:
        from ai.dds.dds_log_reader import get_dds_log_files, read_dds_events
        files = get_dds_log_files()
        if not files:
            return
        events = read_dds_events(files[0])
        if not events:
            return
        existing = set()
        for e in store.get_events(limit=5000):
            existing.add((e.get("event_type"), e.get("timestamp"), e.get("details")))
        added = 0
        for ev in events:
            key = (ev.get("event_type"), ev.get("timestamp"), ev.get("details"))
            if key in existing:
                continue
            ev.setdefault("simulation", False)
            ev.setdefault("data_source", "live")
            store.add_event(ev)
            added += 1
            existing.add(key)
        print(f"[control-centre] DDS session captured: {added} new events from {files[0]}")
    except Exception as e:
        print(f"[control-centre] DDS session capture error: {e}")


def _graceful_shutdown():
    """Ordered shutdown: stop new work -> DDS -> capture session -> camera -> WS -> exit."""
    if _SHUTDOWN_EVENT.is_set():
        return
    _SHUTDOWN_EVENT.set()
    print("[control-centre] Graceful shutdown requested.")

    # 1) Stop accepting new work (simulator loop, if running)
    try:
        sim = _get_simulator()
        if sim:
            sim.stop()
            print("[control-centre] Simulator stopped.")
    except Exception as e:
        print(f"[control-centre] Simulator stop error: {e}")

    # 2) Gracefully stop the DDS subprocess if running
    try:
        from ai.dds.dds_process import get_dds_manager
        mgr = get_dds_manager()
        if mgr.is_running:
            ok, msg = mgr.stop()
            print(f"[control-centre] DDS subprocess stopped: {msg}")
        else:
            print("[control-centre] DDS subprocess was not running.")
    except Exception as e:
        print(f"[control-centre] DDS subprocess stop error: {e}")

    # 3) Capture the DDS session state into the shared store
    _capture_dds_session()

    # 4) Release camera resources
    try:
        from ai.camera_manager import camera_manager
        camera_manager.stop()
        print("[control-centre] Camera resources released.")
    except Exception as e:
        print(f"[control-centre] Camera stop error: {e}")

    # 5) Release WebSocket server resources
    try:
        stop_websocket_server()
        time.sleep(0.3)
    except Exception as e:
        print(f"[control-centre] WebSocket stop error: {e}")

    print("[control-centre] Shutdown sequence complete.")
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _get_simulator():
    return _simulator_ref[0]


def _set_simulator(sim):
    _simulator_ref[0] = sim


def _build_pothole_analytics():
    """Date-wise pothole detections (last 8 days), broken down by bus route.

    Demo model: daily detections trend upward toward today (with a small
    weekend bump), distributed across routes by how many bus stops the route
    serves. Today is blended with the live road-defect count on the map so the
    numbers feel connected to what is being tracked right now.
    """
    today = date.today()
    if _POTHOLE_CACHE["key"] == today.isoformat():
        return _POTHOLE_CACHE["series"]

    rng = random.Random(2049)
    routes = [(r["code"], len(r["stops"])) for r in ROUTES]
    total_w = sum(s for _, s in routes)
    live = len([d for d in store.get_road_defects() if d["status"] == "ACTIVE"])

    days = [(today - timedelta(days=i)) for i in range(7, -1, -1)]
    series = []
    for i, d in enumerate(days):
        base = 4 + i * 0.6 + rng.uniform(-1.5, 1.5)          # gentle upward trend
        if d.weekday() >= 5:
            base += 1                                        # small weekend bump
        if i == len(days) - 1:
            base += live                                     # today mirrors live map
        total = max(1, int(round(base)))

        by_route = {}
        # largest-remainder allocation: floor each exact proportional share,
        # then give the leftover +1s to routes with the biggest fractional
        # parts. Guarantees sum(by_route) == count and long routes (like 70V)
        # never round down to zero on a decent-size day.
        fracs = []
        for code, stops in routes:
            part = total * stops / total_w
            by_route[code] = int(part)
            fracs.append((code, part - int(part)))
        leftover = total - sum(by_route.values())
        for code, _ in sorted(fracs, key=lambda cf: cf[1], reverse=True)[:leftover]:
            by_route[code] += 1

        series.append({
            "date": d.isoformat(),
            "label": d.strftime("%b %d"),
            "count": total,
            "by_route": by_route,
        })

    _POTHOLE_CACHE["key"] = today.isoformat()
    _POTHOLE_CACHE["series"] = series
    return series


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
        "live_prototype_connected": len(mode_state.get_connected_live_nodes()) > 0,
    })


# ---------------------------------------------------------------------------
# Authentication & authorization (Phase 5)
#
# Privileged endpoints are wrapped with @_require_auth(roles). Every request
# must resolve to an ACTIVE user via a valid bearer token before any
# privileged action runs. Read-only telemetry remains accessible so the
# dashboard keeps working for authenticated operators; privileged actions are
# backend-enforced and can never be gained by editing browser state.
# ---------------------------------------------------------------------------

def _require_auth(*roles):
    """Decorator. If roles given, the authenticated user must hold one of them.

    Shutdown-first: while the server is stopping, ALL work (even with valid
    auth) is refused with 503, matching the historical graceful-shutdown
    contract.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if _is_shutting_down():
                return jsonify({"error": "server is shutting down"}), 503
            user = auth.require_auth(request)
            if user is None:
                return jsonify({"error": "authentication required"}), 401
            if roles and user["role"] not in roles:
                return jsonify({"error": "forbidden: insufficient permissions"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def _current_role_permissions(roles):
    """Human-readable label used for role-gating messages in error responses."""
    return "+".join(roles) if roles else "any-authenticated"


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    """Exchange username+password for a bearer token + user record.

    Failure responses are identical for unknown user, wrong password, and
    inactive account so the endpoint never reveals which was wrong.
    """
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = auth.authenticate(username, password)
    if user is None:
        return jsonify({"error": "invalid username or password"}), 401
    token, expires_at = auth.create_session(user["id"])
    return jsonify({
        "token": token,
        "expires_at": expires_at,
        "user": auth.user_payload(user),
    })


@app.route("/api/auth/me", methods=["GET"])
@_require_auth()
def auth_me():
    return jsonify({"user": auth.user_payload(auth.require_auth(request))})


@app.route("/api/auth/logout", methods=["POST"])
@_require_auth()
def auth_logout():
    """Invalidate the current bearer token server-side (real logout, not a
    localStorage delete)."""
    token = auth.token_from_request(request)
    if token:
        auth.revoke_session(token)
    return jsonify({"success": True})


@app.route("/api/auth/me/password", methods=["POST"])
@_require_auth()
def auth_change_own_password():
    """Let an authenticated user change their own password (requires the
    current password, so a stolen token alone cannot hijack an account)."""
    user = auth.require_auth(request)
    body = request.get_json(silent=True) or {}
    current = body.get("current_password") or ""
    new_password = body.get("new_password") or ""
    if not new_password or len(new_password) < 6:
        return jsonify({"error": "new password must be at least 6 characters"}), 400
    from persistence import _conn
    c = _conn()
    try:
        row = c.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
        stored = row["password_hash"] if row else None
    finally:
        c.close()
    if stored is None or not auth.verify_password(current, stored):
        return jsonify({"error": "current password is incorrect"}), 403
    if auth.update_password(user["id"], new_password):
        return jsonify({"success": True})
    return jsonify({"error": "password update failed"}), 400


@app.route("/api/auth/users", methods=["GET"])
@_require_auth("admin")
def admin_list_users():
    users = [auth.user_payload(u) for u in auth.list_users()]
    return jsonify({"users": users})


@app.route("/api/auth/users", methods=["POST"])
@_require_auth("admin")
def admin_create_user():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    role = (body.get("role") or "").strip().lower()
    if not username or not password or role not in auth.ROLES:
        return jsonify({"error": "username, password and a valid role are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400
    user = auth.create_user(username, password, role)
    if user is None:
        return jsonify({"error": "username already exists or could not be created"}), 409
    return jsonify({"user": auth.user_payload(user)}), 201


@app.route("/api/auth/users/<int:user_id>/role", methods=["POST"])
@_require_auth("admin")
def admin_change_role(user_id):
    role = ((request.get_json(silent=True) or {}).get("role") or "").strip().lower()
    ok, msg = auth.update_user_role(user_id, role)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"success": True, "user": auth.user_payload(auth.get_user_by_id(user_id))})


@app.route("/api/auth/users/<int:user_id>/active", methods=["POST"])
@_require_auth("admin")
def admin_set_active(user_id):
    body = request.get_json(silent=True) or {}
    ok, msg = auth.set_user_active(user_id, bool(body.get("active")))
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"success": True, "user": auth.user_payload(auth.get_user_by_id(user_id))})


@app.route("/api/auth/users/<int:user_id>/password", methods=["POST"])
@_require_auth("admin")
def admin_reset_password(user_id):
    new_password = (request.get_json(silent=True) or {}).get("password") or ""
    if not new_password or len(new_password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400
    target = auth.get_user_by_id(user_id)
    if target is None:
        return jsonify({"error": "user not found"}), 404
    if not auth.update_password(user_id, new_password):
        return jsonify({"error": "password update failed"}), 400
    return jsonify({"success": True})


@app.route("/api/fleet/summary")
def fleet_summary():
    """Operator-oriented fleet-level aggregation for the command dashboard.

    One call replaces N per-domain calls for the dashboard: fleet status
    counts (normal/warning/critical/offline), risk aggregate, incident
    summary, driver-safety / vehicle-health / load / occupancy / road-risk
    distributions and a prioritised REQUIRES-ATTENTION list. Every attention
    reason carries its originating source (risk / driver_safety /
    vehicle_health / load / occupancy / cabin_camera / fleet). No intelligence
    is invented here — it is repackaged from the same engines the rest of the
    product uses.
    """
    from fleet_summary import build_fleet_summary

    buses = store.get_buses()
    events = store.get_events(500)
    risk_items = fleet_risk(buses, events, risk_weights=_risk_weights())
    zones = road_risk_engine.get_zones()
    route_index = road_risk_engine.get_route_risk_index()
    defects = store.get_road_defects()
    eta_summary = get_fleet_eta_summary(buses)
    demand_summary = get_fleet_load_summary(buses)
    summary = build_fleet_summary(
        buses, events, risk_items,
        mode={
            "mode": mode_state.mode,
            "simulation": mode_state.is_simulation,
            "connected_nodes": mode_state.get_connected_live_nodes(),
        },
        zones=zones,
        route_index=route_index,
        defects=defects,
        eta_summary=eta_summary,
        demand_summary=demand_summary,
    )
    return jsonify(summary)


@app.route("/api/overview")
def overview():
    buses = store.get_buses()
    events = [e for e in store.get_events(500) if e["status"] == "ACTIVE"]
    defects = store.get_road_defects()
    active = len(buses)
    driver_alerts = sum(1 for b in buses if b["driver"]["state"] in ("ATTENTION", "DROWSY"))
    active_incidents = len(events)
    overloaded = sum(1 for b in buses if b["load"]["status"] in ("OVERLOAD", "CRITICAL OVERLOAD"))
    road_hazards = sum(1 for d in defects if d["status"] == "ACTIVE")
    emergency = sum(1 for e in events if e["event_type"] == "EMERGENCY_SIREN")
    tickets_today = sum((b.get("ticketing") or {}).get("tickets_today", 0) for b in buses)
    fare_collected = round(sum((b.get("ticketing") or {}).get("fare_collected", 0) for b in buses), 2)

    # Mode-specific counts
    live_nodes = mode_state.get_connected_live_nodes()
    live_count = len(live_nodes)

    return jsonify({
        "active_buses": active,
        "driver_alerts": driver_alerts,
        "active_incidents": active_incidents,
        "overloaded_buses": overloaded,
        "road_hazards": road_hazards,
        "emergency_events": emergency,
        "tickets_today": tickets_today,
        "fare_collected": fare_collected,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
        "live_nodes": live_count,
    })


@app.route("/api/buses")
def get_buses():
    buses = store.get_buses()
    return jsonify({
        "buses": buses,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


PROTO_STOPS = [
    {"stop": "Koyambedu", "lat": 13.0697, "lon": 80.2070, "major": True},
    {"stop": "Vadapalani", "lat": 13.0650, "lon": 80.2150, "major": False},
    {"stop": "T.Nagar", "lat": 13.0410, "lon": 80.2340, "major": True},
    {"stop": "Kilambakkam", "lat": 13.0210, "lon": 80.2230, "major": True},
]


def _proto_bus():
    """Stub bus for the FLEET-IQ live prototype node (70V).

    Must be a fully valid bus (same schema as the simulated fleet) so EVERY
    endpoint works in live mode — risk engine, ETA, demand, road threats,
    analytics. Wheels are PSI numbers, journey has real stops (never empty),
    next_index is an int (never None).

    Internal ID stays PROTO-001 for architecture compatibility; the operator
    sees "70V" and the route "Koyambedu <-> Kilambakkam".
    """
    return {
        "bus_id": "PROTO-001",
        "route_id": "PROTO",
        "route_code": "70V",
        "route": "70V — Koyambedu \u2194 Kilambakkam",
        "name": "70V",
        "reg_no": "TN-01-70V-001",
        "vehicle_type": "ELECTRIC",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "lat": 13.0827,
        "lon": 80.2707,
        "speed_kmh": 0,
        "heading": 0,
        "driver": {"state": "NORMAL", "ear": 0.0, "mar": 0.0, "fatigue_stage": "WATCH", "perclos": 0.0, "pitch": 0.0},
        "battery_pct": 100,
        "fuel_pct": 100,
        "load_kg": 0,
        "occupancy": {"passengers": 0, "pct": 0, "capacity": 40},
        "load": {"status": "NORMAL", "gvw_kg": 11000, "payload_kg": 0},
        "vehicle": {"health": "NORMAL", "vibration": 0.2, "braking_events": 0, "maintenance_priority": "LOW"},
        "wheels": [85.0, 84.5, 85.5, 83.8, 86.2, 84.9],
        "ticketing": {"boarding": 0, "alighting": 0, "revenue": 0},
        "energy": {"type": "ELECTRIC", "percent": 100},
        "journey": {
            "route_id": "PROTO",
            "stops": [{**s, "boarded": 0} for s in PROTO_STOPS],
            "current_index": 0,
            "next_index": 1,
            "total_stops": len(PROTO_STOPS),
            "state": "AT_STOP",
            "progress": 0.0,
            "start": PROTO_STOPS[0]["stop"],
            "destination": PROTO_STOPS[-1]["stop"],
        },
        "boarding_by_hour": {str(h): 0 for h in range(24)},
        "boarding_by_stop_hour": {},
        "daily_boarding_total": 0,
        "boarding_peak_hour": 8,
        "health": "NORMAL",
        "cabin_alert": None,
        "cabin_occupancy": None,
        "gps_fix": "3D",
        "data_source": "live",
        "live": True,
        "last_update": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _dds_event_callback(event):
    """Live DDS events land in the shared event system + keep the node alive."""
    store.add_event(event)
    mode_state.update_live_node("PROTO-001", {
        "gps_available": True,
        "sensors": {"driver_ai": "active", "camera": "driver"},
    })


def _passenger_event(bus, event_type, severity, confidence, note, pax, occ, extra=None):
    """Build a passenger-counter event for the LIVE demo bus.

    These boarding/overload events are produced by the demo passenger
    model (randomized), never measured by a real passenger counter — so
    they are always labelled simulation, never live measurements.
    """
    data = {
        "bus_id": "PROTO-001",
        "event_type": event_type,
        "latitude": bus.get("latitude", 13.07),
        "longitude": bus.get("longitude", 80.27),
        "severity": severity,
        "confidence": round(confidence, 2),
        "sensor_source": "passenger_counter",
        "status": "ACTIVE",
        "simulation": True,
        "data_source": "simulation",
        "additional_data": {
            "note": note,
            "passengers": pax,
            "crowd": occ.get("crowd", "NORMAL"),
        },
    }
    if extra:
        data["additional_data"].update(extra)
    return data


def _setup_live_proto():
    """Register PROTO-001 in the store/node registry + wire the DDS engine."""
    store.upsert_bus(_proto_bus())
    mode_state.register_live_node("PROTO-001", {
        "gps_available": True,
        "sensors": {"driver_ai": "active", "camera": "driver"},
    })
    try:
        from ai.driver.driver_drowsiness import driver_detector
        driver_detector.set_event_callback(_dds_event_callback)
        driver_detector.reset()
    except Exception as e:
        print(f"[control-centre] DDS engine setup failed: {e}")

    # Heartbeat: keep the prototype node marked connected while the backend is
    # up (last_seen must be < 30 s for the header to show LIVE).
    def _proto_heartbeat():
        while True:
            try:
                if mode_state.is_live:
                    mode_state.update_live_node("PROTO-001", {
                        "gps_available": True,
                        "sensors": {"driver_ai": "active", "camera": "driver"},
                    })
            except Exception:
                pass
            time.sleep(10)

    threading.Thread(target=_proto_heartbeat, daemon=True).start()

    # Passenger moments: simulate realistic boarding/alighting, occupancy
    # changes, route progression, and passenger-related events on 70V.
    def _passenger_moments():
        import math
        time.sleep(5)  # let the system settle before first tick
        tick_count = 0
        while True:
            try:
                if not mode_state.is_live:
                    time.sleep(3)
                    continue
                bus = store.get_bus("PROTO-001")
                if not bus:
                    time.sleep(3)
                    continue

                rng = random.Random()
                tick_count += 1

                # --- Route progression ---
                j = bus.get("journey", {})
                stops = j.get("stops") or []
                if not stops:
                    time.sleep(3)
                    continue

                state = j.get("state", "AT_STOP")
                current_idx = j.get("current_index", 0)
                next_idx = j.get("next_index", 1)
                progress = j.get("progress", 0.0)

                if state == "AT_STOP":
                    bus["speed_kmh"] = 0.0
                    # Random boarding pulse at stops
                    if rng.random() < 0.35:
                        stop = stops[current_idx]
                        major = stop.get("major", False)
                        boarded = rng.randint(5, 10) if major else rng.randint(1, 4)
                        occ = bus["occupancy"]
                        cap = occ.get("capacity", 40)
                        old_pax = occ["passengers"]
                        occ["passengers"] = max(0, min(cap, occ["passengers"] + boarded))
                        actual = occ["passengers"] - old_pax
                        occ["pct"] = round(100 * occ["passengers"] / cap) if cap else 0
                        if occ["pct"] >= 85:
                            occ["crowd"] = "OVERCROWDED"
                        elif occ["pct"] >= 60:
                            occ["crowd"] = "CROWDED"
                        elif occ["pct"] >= 30:
                            occ["crowd"] = "MODERATE"
                        else:
                            occ["crowd"] = "NORMAL"
                        # Ticketing
                        tkt = bus.get("ticketing") or {}
                        fare_per = 8 + rng.randint(0, 12)
                        tkt["tickets_today"] = tkt.get("tickets_today", 0) + actual
                        tkt["passengers_total"] = tkt.get("passengers_total", 0) + actual
                        tkt["fare_collected"] = round(tkt.get("fare_collected", 0) + actual * fare_per, 2)
                        bus["ticketing"] = tkt
                        bus["daily_boarding_total"] = bus.get("daily_boarding_total", 0) + actual
                        # Load update
                        bus["load"] = _make_live_load(occ["passengers"])
                        bus["last_update"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                        store.upsert_bus(bus)

                    # Depart after dwell
                    if rng.random() < 0.3:
                        if current_idx >= len(stops) - 1:
                            # Reached terminus — reverse direction
                            j["current_index"] = 0
                            j["next_index"] = 1
                            j["state"] = "MOVING"
                            j["progress"] = 0.0
                        else:
                            j["state"] = "MOVING"
                            j["progress"] = 0.0
                elif state == "MOVING":
                    progress += rng.uniform(0.08, 0.15)
                    bus["speed_kmh"] = round(rng.uniform(22, 42), 1)
                    if progress >= 0.5:
                        j["state"] = "ARRIVING"
                    j["progress"] = progress
                    # Interpolate position between stops
                    if current_idx < len(stops) and next_idx < len(stops):
                        a, b = stops[current_idx], stops[next_idx]
                        t = min(1.0, progress)
                        bus["latitude"] = round(a["lat"] + (b["lat"] - a["lat"]) * t, 6)
                        bus["longitude"] = round(a["lon"] + (b["lon"] - a["lon"]) * t, 6)
                    store.upsert_bus(bus)
                elif state == "ARRIVING":
                    progress += rng.uniform(0.06, 0.12)
                    bus["speed_kmh"] = round(max(5.0, 35 - progress * 25), 1)
                    if progress >= 1.0:
                        j["state"] = "AT_STOP"
                        j["current_index"] = next_idx
                        j["next_index"] = min(next_idx + 1, len(stops) - 1)
                        j["progress"] = 0.0
                        dest = stops[j["current_index"]]
                        bus["latitude"] = dest["lat"]
                        bus["longitude"] = dest["lon"]
                        bus["speed_kmh"] = 0.0
                    else:
                        j["progress"] = progress
                        if current_idx < len(stops) and next_idx < len(stops):
                            a, b = stops[current_idx], stops[next_idx]
                            t = min(1.0, progress)
                            bus["latitude"] = round(a["lat"] + (b["lat"] - a["lat"]) * t, 6)
                            bus["longitude"] = round(a["lon"] + (b["lon"] - a["lon"]) * t, 6)
                    store.upsert_bus(bus)

                # --- Alighting (passengers getting off) ---
                if state == "AT_STOP" and rng.random() < 0.25:
                    occ = bus["occupancy"]
                    if occ["passengers"] > 0:
                        alighting = rng.randint(1, max(1, occ["passengers"] // 3))
                        occ["passengers"] = max(0, occ["passengers"] - alighting)
                        cap = occ.get("capacity", 40)
                        occ["pct"] = round(100 * occ["passengers"] / cap) if cap else 0
                        if occ["pct"] >= 85:
                            occ["crowd"] = "OVERCROWDED"
                        elif occ["pct"] >= 60:
                            occ["crowd"] = "CROWDED"
                        elif occ["pct"] >= 30:
                            occ["crowd"] = "MODERATE"
                        else:
                            occ["crowd"] = "NORMAL"
                        bus["load"] = _make_live_load(occ["passengers"])
                        store.upsert_bus(bus)

                # --- Random passenger moment events ---
                if tick_count % 8 == 0 and rng.random() < 0.4:
                    occ = bus["occupancy"]
                    pax = occ.get("passengers", 0)
                    pct = occ.get("pct", 0)
                    stop_name = stops[current_idx]["stop"] if current_idx < len(stops) else "en route"
                    current_time = datetime.now(timezone.utc).hour

                    # Time-based moment selection
                    if pct >= 80:
                        event_type = "PASSENGER_MOMENT"
                        note = f"Bus crowded at {stop_name} — {pax}/{occ.get('capacity', 40)} seats occupied"
                        severity = "WARNING"
                    elif pct <= 15 and tick_count % 20 == 0:
                        event_type = "PASSENGER_MOMENT"
                        note = f"Quiet ride — only {pax} passenger{'s' if pax != 1 else ''} on board near {stop_name}"
                        severity = "INFO"
                    elif 40 <= current_time <= 50 and rng.random() < 0.3:
                        event_type = "PASSENGER_MOMENT"
                        peak = "morning rush" if current_time < 10 else "evening rush"
                        note = f"{peak.title()} surge — {pax} passengers, route busy"
                        severity = "INFO"
                    else:
                        event_type = "PASSENGER_MOMENT"
                        actions = [
                            f"Passengers boarding at {stop_name} — fare collected ₹{bus.get('ticketing', {}).get('fare_collected', 0):.0f}",
                            f"Bus {pax}/{occ.get('capacity', 40)} — smooth ride through {stop_name}",
                            f"{pax} passengers on board, next stop: {stops[min(current_idx+1, len(stops)-1)]['stop']}",
                        ]
                        note = rng.choice(actions)
                        severity = "INFO"

                    event = _passenger_event(
                        bus, event_type, severity, rng.uniform(0.85, 0.99), note, pax, occ
                    )
                    store.add_event(event)

                # --- Overload event ---
                if tick_count % 12 == 0:
                    occ = bus["occupancy"]
                    if occ.get("pct", 0) >= 90:
                        note = f"Overload: {occ['passengers']}/{occ.get('capacity', 40)} passengers ({occ['pct']}% capacity)"
                        event = _passenger_event(
                            bus, "OVERLOAD", "CRITICAL", 0.95, note, occ["passengers"], occ
                        )
                        store.add_event(event)

            except Exception as e:
                print(f"[control-centre] passenger_moments error: {e}")
            time.sleep(3)

    threading.Thread(target=_passenger_moments, daemon=True).start()


def _make_live_load(passengers):
    """Build a load dict from passenger count (realistic 68 kg/pax + luggage)."""
    payload_kg = passengers * 68 + random.randint(100, 800)
    payload_kg = max(0.0, min(float(payload_kg), 6000.0))
    gvw = 11000 + payload_kg
    pct = round(100 * payload_kg / 6000)
    status = "CRITICAL OVERLOAD" if pct > 100 else "HIGH LOAD" if pct > 90 else "NORMAL"
    return {
        "gvw_kg": round(gvw), "tare_kg": 11000, "payload_kg": round(payload_kg),
        "payload_limit_kg": 6000, "load_pct": pct, "status": status,
    }


@app.route("/api/buses/<bus_id>")
def get_bus(bus_id):
    bus = store.get_bus(bus_id)

    # PROTO-001 stub for live prototype (also upserted into the store in live mode)
    if not bus and bus_id == "PROTO-001":
        bus = _proto_bus()

    if not bus:
        return jsonify({"error": "bus not found"}), 404

    recent = [e for e in store.get_events(500) if e["bus_id"] == bus_id]
    return jsonify({
        "bus": bus,
        "recent_events": recent,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


def _risk_weights():
    """User-tuned risk weights from settings (never overrides the whole key)."""
    sink = store.get_settings().get("risk") or {}
    weights = dict(DEFAULT_RISK_WEIGHTS)
    if isinstance(sink, dict):
        for k, v in sink.items():
            if k in weights:
                try:
                    weights[k] = max(0.0, float(v))
                except (TypeError, ValueError):
                    pass
    return weights


def _is_proto(bus_id):
    return bus_id == "PROTO-001"


@app.route("/api/risk")
def risk():
    events = store.get_events(1000)
    weights = _risk_weights()
    buses = store.get_buses()
    # Compute road exposure for each bus to integrate into risk
    exposures = {}
    for b in buses:
        exp = road_risk_engine.compute_bus_exposure(b)
        exposures[b["bus_id"]] = exp.to_dict()
    items = fleet_risk(buses, events, risk_weights=weights)
    # Merge road exposure into risk results
    for item in items:
        bid = item["bus_id"]
        if bid in exposures:
            item["road_exposure"] = exposures[bid].get("exposure_state")
            item["road_zone"] = exposures[bid].get("nearby_zone_id")
    by_level = {lvl: sum(1 for r in items if r["risk_level"] == lvl) for lvl in SEVERITY_LEVELS}
    return jsonify({
        "buses": items,
        "risk_weights": weights,
        "by_level": by_level,
        "avg_score": round(sum(r["risk_score"] for r in items) / len(items), 1) if items else 0,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/buses/<bus_id>/risk")
def bus_risk_endpoint(bus_id):
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "risk_score": 0, "risk_level": "NORMAL", "risk_factors": [], "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    events = [e for e in store.get_events(1000) if e["bus_id"] == bus_id]
    return jsonify(bus_risk(bus, events, risk_weights=_risk_weights()))


@app.route("/api/buses/<bus_id>/risk/history")
def bus_risk_history(bus_id):
    """Phase 15: Get risk history for a bus."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "history": [], "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    limit = request.args.get("limit", 20, type=int)
    history = get_risk_history(bus_id, limit=limit)
    # Convert tuples to dicts for JSON
    history_list = [{"timestamp": h[0], "score": h[1], "state": h[2]} for h in history]
    return jsonify({
        "bus_id": bus_id,
        "history": history_list,
        "count": len(history_list),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/buses/<bus_id>/risk/trend")
def bus_risk_trend(bus_id):
    """Phase 15: Get risk trend for a bus."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "trend": "UNKNOWN", "coverage": 0, "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    trend = get_risk_trend(bus_id)
    coverage = get_risk_coverage(bus_id)
    return jsonify({
        "bus_id": bus_id,
        "trend": trend,
        "coverage": coverage,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/risk/events")
def risk_events():
    """Phase 15: Get risk events (state transitions, critical risk, etc.)."""
    bus_id = request.args.get("bus_id")
    limit = request.args.get("limit", 100, type=int)
    events = persistence.load_risk_events(bus_id=bus_id, limit=limit)
    return jsonify({
        "events": events,
        "count": len(events),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/buses/<bus_id>/timeline")
def bus_timeline(bus_id):
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "timeline": [], "needs_refresh": False, "last_recovery": None, "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    timeline = bus.get("driver", {}).get("fatigue_timeline", [])
    needs_refresh = bus.get("driver", {}).get("needs_refresh", False)
    last_recovery = bus.get("driver", {}).get("recovered_at")
    return jsonify({
        "bus_id": bus_id,
        "timeline": timeline,
        "needs_refresh": needs_refresh,
        "last_recovery": last_recovery,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/actions")
def get_actions():
    bus_id = request.args.get("bus_id")
    unacked = request.args.get("unacked", "false").lower() == "true"
    acts = action_store.get_actions(bus_id=bus_id, unacked_only=unacked)
    return jsonify({"actions": acts, "simulation": mode_state.is_simulation, "mode": mode_state.mode})


@app.route("/api/actions/<action_id>/ack", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def ack_action(action_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    act = action_store.ack_action(action_id, operator)
    if not act:
        return jsonify({"error": "action not found"}), 404
    return jsonify({"action": act})


@app.route("/api/actions/<action_id>/resolve", methods=["POST"])
@_require_auth("supervisor", "admin")
def resolve_action(action_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    act = action_store.resolve_action(action_id, operator)
    if not act:
        return jsonify({"error": "action not found"}), 404
    return jsonify({"action": act})


@app.route("/api/actions/evaluate", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def evaluate_actions():
    evaluate_fleet(store.get_buses(), store.get_events(1000))
    return jsonify({"evaluated": True, "simulation": mode_state.is_simulation, "mode": mode_state.mode})


@app.route("/api/events")
def get_events():
    status = request.args.get("status")
    etype = request.args.get("type")
    data_source = request.args.get("data_source")
    events = store.get_events(500)
    if status:
        events = [e for e in events if e["status"] == status]
    if etype:
        events = [e for e in events if e["event_type"] == etype]
    if data_source:
        events = [e for e in events if e.get("data_source") == data_source]
    return jsonify({
        "events": events,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/alerts")
def get_alerts():
    """Recent real-time alerts — a PROJECTION of the existing event store,
    not a second store (Phase 9). Same decision logic as the WebSocket push
    (alerts.is_alertworthy), used by the frontend to fill its alert centre
    and to reconcile by event_id after a reconnect so no alert is missed and
    none is duplicated."""
    limit = min(int(request.args.get("limit", 50) or 50), 200)
    items = alerts.project_alerts(store.get_events(1000))[:limit]
    return jsonify({
        "alerts": items,
        "count": len(items),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/events/<event_id>/acknowledge", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def acknowledge(event_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    ev = store.acknowledge_event(event_id, operator)
    if not ev:
        return jsonify({"error": "event not found"}), 404
    return jsonify({"event": ev})


@app.route("/api/events/<event_id>/review", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def review(event_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    ev = store.review_event(event_id, operator)
    if not ev:
        return jsonify({"error": "event not found"}), 404
    return jsonify({"event": ev})


@app.route("/api/events/<event_id>/resolve", methods=["POST"])
@_require_auth("supervisor", "admin")
def resolve(event_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    ev = store.resolve_event(event_id, operator)
    if not ev:
        return jsonify({"error": "event not found"}), 404
    return jsonify({"event": ev})


@app.route("/api/events/<event_id>/status", methods=["POST"])
@_require_auth("supervisor", "admin")
def set_status(event_id):
    body = request.get_json(silent=True) or {}
    ev = store.set_event_status(event_id, body.get("status"), body.get("operator"))
    if not ev:
        return jsonify({"error": "event not found or invalid status"}), 404
    return jsonify({"event": ev})


@app.route("/api/events/status", methods=["POST"])
@_require_auth("supervisor", "admin")
def bulk_status():
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in ("ACTIVE", "REVIEWING", "ACKNOWLEDGED", "RESOLVED"):
        return jsonify({"error": "invalid status"}), 400
    count = store.set_event_status_many(status, operator=body.get("operator"), bus_id=body.get("bus_id"))
    return jsonify({"updated": count})


@app.route("/api/road-defects")
def road_defects():
    defects = store.get_road_defects()
    return jsonify({
        "defects": defects,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/health/predictive")
def predictive_health():
    """Vehicle health intelligence with component health, anomalies, and maintenance recommendations.

    All values are simulation-derived (heuristic rolling counters) and clearly labeled.
    No trained ML models are used; RUL is a linear trend estimate.
    """
    data_source = DataSource.SIMULATION if mode_state.is_simulation else DataSource.LIVE
    buses = store.get_buses()

    summaries = {}
    all_predictions = {}
    all_recommendations = {}
    anomalies = {}

    for bus in buses:
        bid = bus["bus_id"]
        vh = health_tracker.get_vehicle_health(bid, data_source)
        summaries[bid] = vh.to_dict()

        # Extract predictions for backward compatibility
        preds = []
        for name, comp in vh.components.items():
            if name.startswith("tyre") and comp.value >= THRESHOLDS["tyre_wear_pct"]:
                if comp.rul_ticks and comp.rul_ticks <= 50:
                    preds.append({"type": "TYRE_REPLACEMENT", "component": name,
                                  "current": round(comp.value, 1), "rul_ticks": comp.rul_ticks,
                                  "severity": "WARNING" if comp.rul_ticks > 20 else "CRITICAL",
                                  "data_source": comp.data_source.value})
            elif name == "vibration" and comp.value >= THRESHOLDS["vibration_rms"]:
                preds.append({"type": "VIBRATION_INSPECTION", "component": "chassis_suspension",
                              "current": round(comp.value, 3), "rul_ticks": comp.rul_ticks, "severity": "WARNING",
                              "data_source": comp.data_source.value})
            elif name == "energy_degradation" and comp.value >= THRESHOLDS["energy_degradation_pct"]:
                preds.append({"type": "ENERGY_DEGRADATION",
                              "component": "battery" if (store.get_bus(bid) or {}).get("energy", {}).get("type") == "EV" else "fuel_system",
                              "current": round(comp.value, 1), "rul_ticks": comp.rul_ticks, "severity": "INFO",
                              "data_source": comp.data_source.value})
        if preds:
            all_predictions[bid] = preds

        if vh.maintenance_recommendations:
            all_recommendations[bid] = vh.maintenance_recommendations

        if vh.anomalies:
            anomalies[bid] = vh.anomalies

    return jsonify({
        "summaries": summaries,
        "predictions": all_predictions,
        "recommendations": all_recommendations,
        "anomalies": anomalies,
        "fleet_summary": get_fleet_health_summary(data_source),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
        "data_source": data_source.value,
        "note": "All values are heuristic estimates from rolling synthetic counters. No trained ML models. RUL is linear trend projection.",
    })


@app.route("/api/health/fleet")
def fleet_health():
    """Fleet-wide vehicle health summary for dashboard."""
    data_source = DataSource.SIMULATION if mode_state.is_simulation else DataSource.LIVE
    return jsonify({
        "fleet": get_fleet_health_summary(data_source),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
        "data_source": data_source.value,
    })


@app.route("/api/eta")
def fleet_eta():
    """Fleet-wide ETA with deterministic RNG for consistency."""
    rng = random.Random(42)  # deterministic seed
    all_etas = compute_all_etas(store.get_buses(), rng)
    delay_counts = {"ON_TIME": 0, "EARLY": 0, "MINOR_DELAY": 0,
                    "SIGNIFICANT_DELAY": 0, "SEVERE_DELAY": 0, "NO_ROUTE": 0}
    for bus_id, e in all_etas.items():
        state = e.get("delay_summary", "UNKNOWN")
        delay_counts[state] = delay_counts.get(state, 0) + 1
        # Persist meaningful snapshots (skip empty results)
        if e.get("etas") and state not in ("NO_ROUTE", "UNKNOWN"):
            try:
                from persistence import persist_eta_snapshot
                persist_eta_snapshot(
                    bus_id=bus_id,
                    delay_summary=state,
                    total_remaining_distance_km=e.get("total_remaining_distance_km", 0),
                    total_remaining_time_sec=e.get("total_remaining_time_sec", 0),
                    delay_causes=e.get("delay_causes", []),
                    source=e.get("source", "HEURISTIC"),
                    simulation=mode_state.is_simulation,
                )
            except Exception:
                pass
    return jsonify({
        "buses": list(all_etas.values()),
        "delay_summary": delay_counts,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/eta/summary")
def fleet_eta_summary():
    """Fleet-level ETA KPI for the dashboard."""
    summary = get_fleet_eta_summary(store.get_buses())
    summary["simulation"] = mode_state.is_simulation
    summary["mode"] = mode_state.mode
    return jsonify(summary)


@app.route("/api/buses/<bus_id>/eta")
def bus_eta(bus_id):
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "eta_minutes": 0, "delay_summary": "No route",
                            "delay_causes": [], "source": "UNKNOWN",
                            "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    rng = random.Random(hash(bus_id) % 10000)  # deterministic per bus
    result = compute_all_etas([bus], rng).get(bus_id, {"error": "no route"})
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/demand")
def fleet_demand():
    rng = random.Random()
    all_fc = forecast_all(store.get_buses(), rng, 5)
    return jsonify({
        "buses": all_fc,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/buses/<bus_id>/demand")
def bus_demand(bus_id):
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "forecast": [], "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    rng = random.Random()
    return jsonify({
        "bus_id": bus_id,
        "forecast": forecast_bus(bus_id, rng, 5),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


# ---- Phase 14: Demand Intelligence endpoints ----

@app.route("/api/demand/intelligence")
def demand_intelligence():
    """Fleet-level demand intelligence summary."""
    buses = store.get_buses()
    summary = get_fleet_load_summary(buses)
    summary["simulation"] = mode_state.is_simulation
    summary["mode"] = mode_state.mode
    return jsonify(summary)


@app.route("/api/demand/routes")
def route_demand():
    """Route-level demand summary."""
    buses = store.get_buses()
    routes = get_route_demand_summary(buses)
    return jsonify({
        "routes": routes,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/buses/<bus_id>/capacity")
def bus_capacity(bus_id):
    """Bus capacity model."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "load_state": "UNKNOWN", "source": "UNKNOWN"})
        return jsonify({"error": "bus not found"}), 404
    model = get_capacity_model(bus)
    model["simulation"] = mode_state.is_simulation
    model["mode"] = mode_state.mode
    return jsonify(model)


@app.route("/api/buses/<bus_id>/occupancy")
def bus_occupancy(bus_id):
    """Bus occupancy snapshot with source tracking."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "crowd_level": "UNKNOWN", "source": "UNKNOWN"})
        return jsonify({"error": "bus not found"}), 404
    snap = get_occupancy_snapshot(bus)
    snap["simulation"] = mode_state.is_simulation
    snap["mode"] = mode_state.mode
    return jsonify(snap)


@app.route("/api/buses/<bus_id>/pressure")
def bus_pressure(bus_id):
    """Bus capacity pressure from forecast demand."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "pressure_level": "UNKNOWN"})
        return jsonify({"error": "bus not found"}), 404
    # Get forecast for next stop
    rng = random.Random(42)
    fc = forecast_bus(bus_id, rng, 3)
    forecast_boardings = sum(f.get("forecast_boardings", 0) for f in fc)
    pressure = get_capacity_pressure(bus, forecast_boardings)
    pressure["simulation"] = mode_state.is_simulation
    pressure["mode"] = mode_state.mode
    return jsonify(pressure)


@app.route("/api/roads/risk")
def roads_risk():
    rebuild_zones()
    return jsonify({
        "zones": road_risk_engine.get_zones(),
        "clusters": road_risk_engine.get_clusters(),
        "route_index": road_risk_engine.get_route_risk_index(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/roads/summary")
def roads_summary():
    """Road intelligence summary for the dashboard."""
    rebuild_zones()
    summary = get_road_summary()
    summary["simulation"] = mode_state.is_simulation
    summary["mode"] = mode_state.mode
    return jsonify(summary)


@app.route("/api/buses/<bus_id>/road-threats")
def bus_road_threats(bus_id):
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "threats": [], "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    return jsonify({
        "bus_id": bus_id,
        "threats": get_leg_threats(bus),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/buses/<bus_id>/road-exposure")
def bus_road_exposure(bus_id):
    """Get a specific bus's exposure to road risk zones."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "exposure": get_bus_exposure(bus) if bus else {"exposure_state": "UNKNOWN"}, "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    return jsonify({
        "bus_id": bus_id,
        "exposure": get_bus_exposure(bus),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/roads/exposures")
def roads_exposures():
    """Get all buses' exposure to road risk zones."""
    return jsonify({
        "exposures": get_all_bus_exposures(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/analytics")
def analytics():
    events = store.get_events(1000)
    buses = store.get_buses()

    drowsiness_by_bus = Counter(e["bus_id"] for e in events if e["event_type"] == "DRIVER_DROWSINESS")
    incidents_by_route = Counter(b.get("route_code", b["route"]) for b in buses if self_has_incident(b, events))
    potholes_by_road = Counter(d["type"] for d in store.get_road_defects())
    event_types = Counter(e["event_type"] for e in events)
    severity = Counter(e["severity"] for e in events)
    occupancy = [{"bus": b["bus_id"], "passengers": b["occupancy"]["passengers"],
                  "pct": b["occupancy"]["pct"]} for b in buses]
    fare_by_bus = {
        b["bus_id"]: {"tickets": (b.get("ticketing") or {}).get("tickets_today", 0),
                      "fare": round((b.get("ticketing") or {}).get("fare_collected", 0), 2)}
        for b in buses
    }
    vehicle_mix = Counter(b.get("vehicle_type", "DIESEL") for b in buses)

    # boardings by hour-of-day across the whole fleet (morning/evening peaks)
    hours = list(range(4, 23))
    hourly = Counter()
    for b in buses:
        for h, v in (b.get("boarding_by_hour") or {}).items():
            hourly[h] += v
    peak_h = max(hours, key=lambda h: hourly[h])
    quiet_h = min(hours, key=lambda h: hourly[h])

    def h12(h):
        return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"

    # ---- date-wise pothole analytics (by day + by route) ----
    pothole_series = _build_pothole_analytics()
    potholes_by_route = Counter()
    for s in pothole_series:
        for code, n in s["by_route"].items():
            potholes_by_route[code] += n

    return jsonify({
        "drowsiness_by_bus": dict(drowsiness_by_bus),
        "incidents_by_route": dict(incidents_by_route),
        "potholes_by_road": dict(potholes_by_road),
        "event_types": dict(event_types),
        "severity": dict(severity),
        "occupancy": occupancy,
        "fare_by_bus": fare_by_bus,
        "vehicle_mix": dict(vehicle_mix),
        "hourly_boardings": [
            {"hour": h, "label": h12(h), "boardings": hourly[h]} for h in hours
        ],
        "boarding_peak": {"hour": peak_h, "label": h12(peak_h), "boardings": hourly[peak_h]},
        "boarding_quietest": {"hour": quiet_h, "label": h12(quiet_h), "boardings": hourly[quiet_h]},
        "potholes_by_date": [
            {"date": s["date"], "label": s["label"], "count": s["count"]} for s in pothole_series
        ],
        "potholes_by_date_route": [
            {"date": s["date"], "label": s["label"], "by_route": s["by_route"]} for s in pothole_series
        ],
        "potholes_by_route": dict(potholes_by_route),
        "potholes_today": pothole_series[-1]["count"],
        "potholes_total": sum(s["count"] for s in pothole_series),
        "routes": [{"code": r["code"], "name": r["name"]} for r in ROUTES],
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


def self_has_incident(bus, events):
    return any(e["bus_id"] == bus["bus_id"] and e["severity"] in ("CRITICAL", "WARNING") for e in events)


@app.route("/api/settings")
def settings():
    s = store.get_settings()
    s["system_mode"] = mode_state.mode
    s["live_prototype_connected"] = len(mode_state.get_connected_live_nodes()) > 0
    s["live_bus_id"] = list(mode_state.get_connected_live_nodes().keys())
    return jsonify(s)


@app.route("/api/settings", methods=["POST"])
@_require_auth("admin")
def update_settings():
    body = request.get_json(silent=True) or {}
    updated = store.update_settings(body)
    return jsonify(updated)


# ---- Mode switching endpoints ----

@app.route("/api/mode", methods=["GET"])
def get_mode():
    """Get current system mode and live status."""
    connected = mode_state.get_connected_live_nodes()
    return jsonify({
        "mode": mode_state.mode,
        "is_simulation": mode_state.is_simulation,
        "is_live": mode_state.is_live,
        "connected_nodes": list(connected.keys()),
        "connected_count": len(connected),
    })


@app.route("/api/mode/switch", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def switch_mode():
    """Switch between simulation and live modes."""
    body = request.get_json(silent=True) or {}
    new_mode = body.get("mode")

    if not new_mode:
        return jsonify({"error": "Missing 'mode' field. Use 'simulation' or 'live'."}), 400

    success, message = mode_state.switch_mode(new_mode)

    if not success:
        return jsonify({"error": message}), 400

    sim = _get_simulator()

    if new_mode == "live":
        # Switching to LIVE: stop simulator, drop transient simulated state.
        # The event/incident history (SQLite-backed) is intentionally kept so
        # the operational log survives mode changes and restarts.
        if sim:
            sim._stop = True
        # Clear simulated buses/defects from store
        store.buses.clear()
        store.road_defects.clear()
        # Register the PROTO-001 prototype node + wire the DDS engine
        _setup_live_proto()
        # Auto-start the driver + cabin cameras in a background thread
        _auto_start_live_cameras()
        return jsonify({
            "success": True,
            "mode": "live",
            "message": "Switched to LIVE PROTOTYPE mode. Cameras starting...",
        })
    else:
        # Switching to SIMULATION: stop camera, create fresh simulator
        try:
            from ai.camera_manager import camera_manager
            camera_manager.stop()
        except Exception as e:
            print(f"[mode] Camera manager stop error: {e}")
        mode_state.clear_live_nodes()
        try:
            new_sim = FleetSimulator()
            _set_simulator(new_sim)
            new_sim.start()
        except Exception as e:
            print(f"[mode] Error starting simulator: {e}")
        return jsonify({
            "success": True,
            "mode": "simulation",
            "message": "Switched to SIMULATION mode. 100 buses active.",
        })


@app.route("/api/live/status", methods=["GET"])
def live_status():
    """Get live prototype connection status."""
    connected = mode_state.get_connected_live_nodes()
    all_nodes = mode_state.get_live_nodes()

    node_details = []
    for bus_id, node in all_nodes.items():
        elapsed = time.time() - node.get("last_seen", 0)
        node_details.append({
            "bus_id": bus_id,
            "connected": elapsed < 30,
            "last_seen_ago": round(elapsed, 1),
            "gps_available": node.get("gps_available", False),
            "sensors": node.get("sensors", {}),
        })

    return jsonify({
        "mode": mode_state.mode,
        "is_live": mode_state.is_live,
        "nodes": node_details,
        "connected_count": len(connected),
    })


# ---- DDS engine endpoints (original DDS inside the Live Prototype view) ----

@app.route("/api/dds/status", methods=["GET"])
def dds_status():
    """Full DDS engine status: phase, calibration, thresholds, monitoring."""
    from ai.driver.driver_drowsiness import driver_detector
    status = driver_detector.get_status()
    # Keep the prototype node marked connected while the page polls this.
    mode_state.update_live_node("PROTO-001", {
        "gps_available": True,
        "sensors": {"driver_ai": status.get("phase", "idle"), "camera": "driver"},
    })
    return jsonify({
        **status,
        "mode": mode_state.mode,
        "simulation": mode_state.is_simulation,
    })


def _require_live():
    if not mode_state.is_live:
        return jsonify({"error": "DDS prototype is available only in LIVE PROTOTYPE mode"}), 400
    return None


@app.route("/api/dds/calibrate", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_calibrate():
    """Start the 5 s personal-baseline calibration (original DDS flow)."""
    blocked = _require_live()
    if blocked:
        return blocked
    from ai.camera_manager import camera_manager
    from ai.driver.driver_drowsiness import driver_detector
    # Ensure the driver camera slot is feeding the DDS engine.
    if not camera_manager.is_slot_active("driver"):
        threading.Thread(
            target=lambda: camera_manager.set_single_camera_test_mode("driver"),
            daemon=True,
        ).start()
        time.sleep(0.8)
    ok, msg = driver_detector.start_calibration()
    return jsonify({"success": ok, "message": msg, "status": driver_detector.get_status()})


@app.route("/api/dds/start", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_start():
    """Start real DDS monitoring (uses calibrated thresholds)."""
    blocked = _require_live()
    if blocked:
        return blocked
    from ai.camera_manager import camera_manager
    from ai.driver.driver_drowsiness import driver_detector
    if not camera_manager.is_slot_active("driver"):
        threading.Thread(
            target=lambda: camera_manager.set_single_camera_test_mode("driver"),
            daemon=True,
        ).start()
        time.sleep(0.8)
    ok, msg = driver_detector.start_monitoring()
    return jsonify({"success": ok, "message": msg, "status": driver_detector.get_status()})


@app.route("/api/dds/stop", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_stop():
    """Stop DDS monitoring (audio warning silenced, camera stays on)."""
    from ai.driver.driver_drowsiness import driver_detector
    ok, msg = driver_detector.stop_monitoring()
    return jsonify({"success": ok, "message": msg, "status": driver_detector.get_status()})


@app.route("/api/dds/reset", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_reset():
    """Reset the DDS engine to idle (clears calibration + monitoring)."""
    from ai.driver.driver_drowsiness import driver_detector
    ok, msg = driver_detector.reset()
    return jsonify({"success": ok, "message": msg, "status": driver_detector.get_status()})


# ---- Original DDS: subprocess control + log reader (fails gracefully) ----

@app.route("/api/dds/subprocess/status", methods=["GET"])
def dds_subprocess_status():
    """Status of the ORIGINAL DDS application (separate desktop window)."""
    from ai.dds.dds_process import get_dds_manager, DDS_ENTRY_POINT
    mgr = get_dds_manager()
    st = mgr.get_status()
    st["available"] = os.path.exists(DDS_ENTRY_POINT)
    st["simulation"] = mode_state.is_simulation
    st["mode"] = mode_state.mode
    return jsonify(st)


@app.route("/api/dds/subprocess/start", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_subprocess_start():
    """Launch the original DDS application as a subprocess (own window)."""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from bus_node.utils.alert_manager import AlertManager
    if AlertManager.muted:
        return jsonify({
            "success": False,
            "error": "Sound is disabled (AlertManager.muted). The original DDS plays its own "
                     "alarm audio, so it will not launch while muted.",
        }), 409
    from ai.dds.dds_process import get_dds_manager
    mgr = get_dds_manager()
    ok, msg = mgr.start()
    return jsonify({"success": ok, "message": msg, "status": mgr.get_status()})


@app.route("/api/dds/subprocess/stop", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_subprocess_stop():
    """Stop the original DDS subprocess."""
    from ai.dds.dds_process import get_dds_manager
    mgr = get_dds_manager()
    ok, msg = mgr.stop()
    return jsonify({"success": ok, "message": msg, "status": mgr.get_status()})


@app.route("/api/dds/logs", methods=["GET"])
def dds_logs():
    """Read the latest DDS session logs (events CSV + summary text)."""
    from ai.dds.dds_log_reader import get_dds_log_files, read_dds_events, get_latest_dds_session
    files = get_dds_log_files()
    events = read_dds_events(files[0]) if files else []
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return jsonify({
        "available": bool(files),
        "log_file": files[0] if files else None,
        "events": events[:50],
        "summary": get_latest_dds_session(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


# ---- Camera / Vision AI endpoints ----

@app.route("/api/camera/status", methods=["GET"])
def camera_status():
    """Get camera status and available cameras."""
    from ai.camera_manager import camera_manager
    return jsonify(camera_status_data(camera_manager))


@app.route("/api/camera/test-mode", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def set_test_mode():
    """Set single-camera test mode for a specific slot."""
    from ai.camera_manager import camera_manager
    body = request.get_json(silent=True) or {}
    slot = body.get("slot")

    if not slot:
        return jsonify({"error": "Missing 'slot' field. Use: driver, cabin, road"}), 400

    success, message = camera_manager.set_single_camera_test_mode(slot)
    return jsonify({"success": success, "message": message, "mode": camera_manager.mode})


@app.route("/api/camera/multi-camera", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def set_multi_camera():
    """Set multi-camera mode (requires 3 cameras)."""
    from ai.camera_manager import camera_manager
    success, message = camera_manager.set_multi_camera_mode()
    return jsonify({"success": success, "message": message, "mode": camera_manager.mode})


@app.route("/api/camera/start", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def start_camera():
    """Start camera in test mode (non-blocking)."""
    from ai.camera_manager import camera_manager
    body = request.get_json(silent=True) or {}
    slot = body.get("slot", "driver")
    if slot not in ("driver", "cabin", "road"):
        return jsonify({"error": "Invalid slot"}), 400

    import threading

    def _start():
        try:
            result = camera_manager.set_single_camera_test_mode(slot)
            print(f"[control-centre] Camera start result for {slot}: {result}")
        except Exception as e:
            import traceback
            print(f"[control-centre] Camera start failed for {slot}: {e}")
            traceback.print_exc()

    t = threading.Thread(target=_start, daemon=True)
    t.start()
    return jsonify({"success": True, "message": f"Camera starting for {slot}..."})


@app.route("/api/camera/stop", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def stop_camera():
    """Stop camera manager and all cameras."""
    from ai.camera_manager import camera_manager
    camera_manager.stop()
    return jsonify({"success": True, "mode": "stopped"})


@app.route("/api/camera/stream/<slot>", methods=["GET"])
def camera_stream(slot):
    """Get a single frame as base64 JPEG with AI detection overlay."""
    from ai.camera_manager import camera_manager
    if slot not in ("driver", "cabin", "road"):
        return jsonify({"error": "Invalid slot"}), 400

    frame_b64 = camera_manager.get_frame_as_base64(slot)
    detections = camera_manager.get_detection_results(slot)
    return jsonify({
        "frame": frame_b64,
        "detections": detections,
        "slot": slot,
    })


@app.route("/api/camera/detections/<slot>", methods=["GET"])
def camera_detections(slot):
    """Get current AI detection results for a slot."""
    from ai.camera_manager import camera_manager
    if slot not in ("driver", "cabin", "road"):
        return jsonify({"error": "Invalid slot"}), 400

    results = camera_manager.get_detection_results(slot)
    return jsonify({"slot": slot, "detections": results})


@app.route("/api/cabin/occupancy", methods=["GET"])
def cabin_occupancy():
    """Cabin occupancy intelligence (Phase 7).

    Read-only telemetry (open like /api/camera/status). Consults the cabin
    occupancy engine, which consumes the Phase-6 cabin camera source at a
    reduced cadence. When the cabin camera is unavailable the payload reports
    occupancy_count/occupancy_percentage/crowding_level/confidence as null —
    it never reports a fabricated 0.
    """
    from ai.cabin.occupancy import get_cabin_engine
    return jsonify(get_cabin_engine().public_state(system_mode=mode_state.mode))


@app.route("/api/ai/status", methods=["GET"])
def ai_status():
    """Get status of all AI perception modules."""
    from ai.camera_manager import camera_manager
    from ai.driver.driver_drowsiness import driver_detector
    from ai.road.pothole_detector import pothole_detector
    from ai.cabin.cabin_detector import cabin_detector

    return jsonify({
        "camera": camera_status_data(camera_manager),
        "driver": {
            "status": driver_detector.get_current_state(),
            "running": camera_manager.is_slot_active("driver"),
        },
        "road": {
            "stats": pothole_detector.get_stats(),
            "running": camera_manager.is_slot_active("road"),
        },
        "cabin": {
            "stats": cabin_detector.get_stats(),
            "running": camera_manager.is_slot_active("cabin"),
        },
        "mode": mode_state.mode,
        "simulation": mode_state.is_simulation,
    })


@app.route("/api/ai/pothole/stats", methods=["GET"])
def pothole_stats():
    """Get pothole detection statistics."""
    from ai.road.pothole_detector import pothole_detector
    return jsonify(pothole_detector.get_stats())


@app.route("/api/ai/driver/state", methods=["GET"])
def driver_state():
    """Get current driver drowsiness state."""
    from ai.driver.driver_drowsiness import driver_detector
    return jsonify(driver_detector.get_current_state())


def camera_status_data(camera_manager):
    """Helper to build camera status response."""
    status = camera_manager.get_camera_status()
    status["simulation"] = mode_state.is_simulation
    status["system_mode"] = mode_state.mode
    return status


def _auto_start_live_cameras():
    """Start the live prototype cameras (driver + cabin) in a background thread.

    Uses multi-camera mode so each camera has an independent lifecycle; a missing
    cabin camera honestly reports DISCONNECTED without stopping the driver feed.
    """
    import time as _time
    import threading

    def _runner():
        _time.sleep(0.5)
        try:
            from ai.camera_manager import camera_manager
            result = camera_manager.set_multi_camera_mode()
            print(f"[control-centre] Live cameras auto-start: {result}")
        except Exception as e:
            print(f"[control-centre] Camera auto-start failed: {e}")

    threading.Thread(target=_runner, daemon=True).start()


def _load_persisted_history():
    """Re-hydrate the in-memory event log from SQLite at startup."""
    import persistence
    persistence.init_db()
    loaded = persistence.load_events()
    for ev in loaded:
        store.add_event(ev)
    # Load Phase 16 incidents
    from incident_intelligence import load_incidents_from_persistence
    load_incidents_from_persistence()
    print(f"[control-centre] Persistence: loaded {len(loaded)} events from history.")


# ---------------------------------------------------------------------------
# Phase 16 — Incident Intelligence API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/incidents")
def get_incidents():
    """List incidents with optional filters."""
    from incident_intelligence import incident_store
    status = request.args.get("status")
    severity = request.args.get("severity")
    priority = request.args.get("priority")
    bus_id = request.args.get("bus_id")
    category = request.args.get("category")
    source = request.args.get("source")
    limit = min(int(request.args.get("limit", 50) or 50), 200)
    incidents = incident_store.get_incidents(
        status=status, severity=severity, priority=priority,
        bus_id=bus_id, category=category, source=source, limit=limit
    )
    return jsonify({
        "incidents": [i.to_dict() for i in incidents],
        "count": len(incidents),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/incidents/active")
def get_active_incidents():
    """List active (OPEN/INVESTIGATING) incidents."""
    from incident_intelligence import incident_store
    incidents = incident_store.get_active_incidents()
    return jsonify({
        "incidents": [i.to_dict() for i in incidents],
        "count": len(incidents),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/incidents/summary")
def get_incident_summary():
    """Get incident summary statistics."""
    from incident_intelligence import get_incident_summary
    summary = get_incident_summary()
    return jsonify({
        "summary": summary,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/incidents/<incident_id>")
def get_incident(incident_id):
    """Get a single incident by ID."""
    from incident_intelligence import incident_store
    incident = incident_store.get_incident(incident_id)
    if not incident:
        return jsonify({"error": "incident not found"}), 404
    return jsonify({
        "incident": incident.to_dict(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/incidents/<incident_id>/acknowledge", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def acknowledge_incident(incident_id):
    """Acknowledge an incident."""
    from incident_intelligence import incident_store
    body = request.get_json(silent=True) or {}
    operator = body.get("operator", "unknown")
    incident = incident_store.acknowledge_incident(incident_id, operator)
    if not incident:
        return jsonify({"error": "incident not found or invalid status"}), 404
    return jsonify({"incident": incident.to_dict()})


@app.route("/api/incidents/<incident_id>/investigate", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def investigate_incident(incident_id):
    """Mark an incident as under investigation."""
    from incident_intelligence import incident_store
    body = request.get_json(silent=True) or {}
    operator = body.get("operator", "unknown")
    notes = body.get("notes")
    incident = incident_store.investigate_incident(incident_id, operator, notes)
    if not incident:
        return jsonify({"error": "incident not found or invalid status"}), 404
    return jsonify({"incident": incident.to_dict()})


@app.route("/api/incidents/<incident_id>/resolve", methods=["POST"])
@_require_auth("supervisor", "admin")
def resolve_incident(incident_id):
    """Resolve an incident."""
    from incident_intelligence import incident_store
    body = request.get_json(silent=True) or {}
    operator = body.get("operator", "unknown")
    notes = body.get("notes")
    incident = incident_store.resolve_incident(incident_id, operator, notes)
    if not incident:
        return jsonify({"error": "incident not found or invalid status"}), 404
    return jsonify({"incident": incident.to_dict()})


@app.route("/api/incidents/<incident_id>/close", methods=["POST"])
@_require_auth("supervisor", "admin")
def close_incident(incident_id):
    """Close a resolved incident."""
    from incident_intelligence import incident_store
    body = request.get_json(silent=True) or {}
    operator = body.get("operator", "unknown")
    incident = incident_store.close_incident(incident_id, operator)
    if not incident:
        return jsonify({"error": "incident not found or invalid status"}), 404
    return jsonify({"incident": incident.to_dict()})


@app.route("/api/incidents/by-bus/<bus_id>")
def get_incidents_by_bus(bus_id):
    """Get incidents for a specific bus."""
    from incident_intelligence import get_bus_incidents
    limit = min(int(request.args.get("limit", 20) or 20), 100)
    incidents = get_bus_incidents(bus_id, limit=limit)
    return jsonify({
        "incidents": [i.to_dict() for i in incidents],
        "count": len(incidents),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@app.route("/api/incidents/by-event/<event_id>")
def get_incident_by_event(event_id):
    """Get the incident associated with an event."""
    from incident_intelligence import get_incident_for_event_id
    incident = get_incident_for_event_id(event_id)
    if not incident:
        return jsonify({"incident": None, "found": False})
    return jsonify({
        "incident": incident.to_dict(),
        "found": True,
    })


# ---------------------------------------------------------------------------
# Phase 17 — Historical Analytics Intelligence API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/analytics/historical")
def get_historical_analytics():
    """Comprehensive historical analytics dashboard.

    Query params:
      - time_range: "1h", "6h", "24h", "7d", "30d", "all" (default: "24h")
      - custom_start: ISO timestamp (optional, for custom range)
      - custom_end: ISO timestamp (optional, for custom range)
    """
    from analytics_intelligence import get_analytics_dashboard
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    result = get_analytics_dashboard(time_range, custom_start, custom_end)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/kpis")
def get_analytics_kpis():
    """Fleet KPI summary from persisted data."""
    from analytics_intelligence import get_fleet_kpis
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    result = get_fleet_kpis(time_range, custom_start, custom_end)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/events")
def get_analytics_events():
    """Historical event analytics."""
    from analytics_intelligence import get_event_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    bus_id = request.args.get("bus_id")
    route_code = request.args.get("route_code")
    result = get_event_analytics(time_range, custom_start, custom_end, bus_id, route_code)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/incidents")
def get_analytics_incidents():
    """Historical incident analytics."""
    from analytics_intelligence import get_incident_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    bus_id = request.args.get("bus_id")
    category = request.args.get("category")
    result = get_incident_analytics(time_range, custom_start, custom_end, bus_id, category)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/risk")
def get_analytics_risk():
    """Historical risk analytics."""
    from analytics_intelligence import get_risk_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    bus_id = request.args.get("bus_id")
    result = get_risk_analytics(time_range, custom_start, custom_end, bus_id)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/eta")
def get_analytics_eta():
    """Historical ETA/delay analytics."""
    from analytics_intelligence import get_eta_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    bus_id = request.args.get("bus_id")
    result = get_eta_analytics(time_range, custom_start, custom_end, bus_id)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/load")
def get_analytics_load():
    """Historical load/occupancy analytics."""
    from analytics_intelligence import get_load_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    bus_id = request.args.get("bus_id")
    route_code = request.args.get("route_code")
    result = get_load_analytics(time_range, custom_start, custom_end, bus_id, route_code)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/road")
def get_analytics_road():
    """Historical road intelligence analytics."""
    from analytics_intelligence import get_road_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    result = get_road_analytics(time_range, custom_start, custom_end)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/driver-safety")
def get_analytics_driver_safety():
    """Historical driver safety analytics."""
    from analytics_intelligence import get_driver_safety_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    bus_id = request.args.get("bus_id")
    result = get_driver_safety_analytics(time_range, custom_start, custom_end, bus_id)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/routes")
def get_analytics_routes():
    """Cross-domain route analytics."""
    from analytics_intelligence import get_route_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    result = get_route_analytics(time_range, custom_start, custom_end)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/buses")
def get_analytics_buses():
    """Cross-domain bus analytics."""
    from analytics_intelligence import get_bus_analytics
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    bus_id = request.args.get("bus_id")
    result = get_bus_analytics(time_range, custom_start, custom_end, bus_id)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@app.route("/api/analytics/insights")
def get_analytics_insights():
    """Cross-domain operational insights."""
    from analytics_intelligence import get_cross_domain_insights
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    result = get_cross_domain_insights(time_range, custom_start, custom_end)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


# ---------------------------------------------------------------------------
# Phase 18 — WebSocket Status API endpoint
# ---------------------------------------------------------------------------

@app.route("/api/websocket/status")
def get_websocket_status():
    """WebSocket server status and metrics (Phase 18)."""
    from websocket_handler import get_ws_status, get_ws_metrics, get_ws_connections
    status = get_ws_status()
    status["simulation"] = mode_state.is_simulation
    status["mode"] = mode_state.mode
    return jsonify(status)


@app.route("/api/websocket/metrics")
def get_websocket_metrics():
    """WebSocket performance metrics (Phase 18)."""
    from websocket_handler import get_ws_metrics
    metrics = get_ws_metrics()
    return jsonify({
        "metrics": metrics,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


def main():
    parser = argparse.ArgumentParser(description="Control Centre backend (FLEET-IQ).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--ws-port", type=int, default=8765)
    parser.add_argument("--no-ws", action="store_true",
                        help="skip the WebSocket server (buses then feed REST only)")
    parser.add_argument("--start-mode", choices=["simulation", "live"], default="simulation",
                        help="initial operating mode (default: simulation)")
    args = parser.parse_args()

    # Set initial mode (simulator is only constructed in simulation mode so
    # live mode never seeds simulated buses into the shared store). Historical
    # events are always reloaded from SQLite so incident history survives restarts.
    _load_persisted_history()
    # Bootstrap the development Admin (idempotent; safe, dev-only default).
    auth.ensure_bootstrap_admin()
    if args.start_mode == "live":
        mode_state.switch_mode("live")
        store.buses.clear()
        store.road_defects.clear()
        _setup_live_proto()
        # Auto-start the driver + cabin cameras (matches mode-switch behaviour)
        _auto_start_live_cameras()
        print("[control-centre] Starting in LIVE PROTOTYPE mode.")
    else:
        sim = FleetSimulator()
        _set_simulator(sim)
        sim.start()
        print("[control-centre] Starting in SIMULATION mode (100 buses).")

    if not args.no_ws:
        start_websocket_server(host=args.host, port=args.ws_port)
    else:
        print("[control-centre] WebSocket server disabled (--no-ws).")

    # Start the cabin occupancy intelligence engine (Phase 7): consumes the
    # cabin camera's frames at a reduced cadence and reports UNAVAILABLE
    # honestly when the camera is disconnected — it never fabricates passengers.
    try:
        from ai.cabin.occupancy import get_cabin_engine
        get_cabin_engine().start()
    except Exception as e:
        print(f"[control-centre] Cabin intelligence engine start failed: {e}")

    # Pre-open camera in main process (cv2.VideoCapture deadlocks in Flask threads)
    try:
        from ai.camera_manager import camera_manager
        camera_manager.open_shared_camera()
    except Exception as e:
        print(f"[control-centre] Camera preload failed: {e}")

    print(f"[control-centre] API ready at http://{args.host}:{args.port}")
    print(f"[control-centre] Mode: {mode_state.mode}")

    # Graceful shutdown: SIGINT / SIGTERM -> ordered cleanup -> exit cleanly.
    def _signal_handler(signum, frame):
        print(f"[control-centre] Received signal {signum}")
        _graceful_shutdown()
        os._exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()