"""
routes.py
Flask API route handlers for the FLEET-IQ Control Centre.

This module contains the HTTP endpoint definitions that were previously
mixed with business logic in server.py. Each route handler focuses on
HTTP request/response handling and delegates business logic to
appropriate service modules.

PRESERVES: All existing API endpoints, HTTP methods, request/response
formats, and authentication requirements.
"""

import os
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from flask import Blueprint, jsonify, request

import auth
import alerts
import persistence
from data_store import store, mode_state
from risk_engine import DEFAULT_RISK_WEIGHTS, SEVERITY_LEVELS, bus_risk, fleet_risk, get_risk_history, get_risk_trend, get_risk_coverage
from recommendations import action_store, evaluate_fleet, utcnow_iso
from predictive_health import health_tracker, tick_all, THRESHOLDS, get_health_summary, get_fleet_health_summary, get_fleet_maintenance_risk, DataSource
from eta import eta_engine, compute_all_etas, get_fleet_eta_summary
from demand import demand_engine, forecast_all, forecast_bus
from demand_intelligence import (
    get_capacity_model, get_occupancy_snapshot, get_demand_pattern,
    get_capacity_pressure, detect_overcrowding, get_route_demand_summary,
    get_fleet_load_summary,
)
from road_risk import road_risk_engine, rebuild_zones, get_leg_threats, get_road_summary
from simulator import _ensure_gtfs_loaded


def _get_routes_for_analytics():
    """Get ROUTES list, loading GTFS lazily if needed."""
    _ensure_gtfs_loaded()
    from simulator import ROUTES
    return ROUTES or []


# Create a Blueprint for API routes
api = Blueprint('api', __name__)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

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


def _require_live():
    if not mode_state.is_live:
        return jsonify({"error": "DDS prototype is available only in LIVE PROTOTYPE mode"}), 400
    return None


def camera_status_data(camera_manager):
    """Helper to build camera status response."""
    status = camera_manager.get_camera_status()
    status["simulation"] = mode_state.is_simulation
    status["system_mode"] = mode_state.mode
    return status


def self_has_incident(bus, events):
    return any(e["bus_id"] == bus["bus_id"] and e["severity"] in ("CRITICAL", "WARNING") for e in events)


# ---------------------------------------------------------------------------
# Authentication & authorization (Phase 5)
# ---------------------------------------------------------------------------

def _require_auth(*roles):
    """Decorator. If roles given, the authenticated user must hold one of them.
    
    Shutdown-first: while the server is stopping, ALL work (even with valid
    auth) is refused with 503, matching the historical graceful-shutdown
    contract.
    """
    from functools import wraps
    from lifecycle import is_shutting_down
    
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if is_shutting_down():
                return jsonify({"error": "server is shutting down"}), 503
            user = auth.require_auth(request)
            if user is None:
                return jsonify({"error": "authentication required"}), 401
            if roles and user["role"] not in roles:
                return jsonify({"error": "forbidden: insufficient permissions"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Core API endpoints
# ---------------------------------------------------------------------------

@api.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
        "live_prototype_connected": len(mode_state.get_connected_live_nodes()) > 0,
    })


@api.route("/api/system/health")
def system_health():
    """System health status with all subsystems (Phase 19)."""
    try:
        from system_health import get_system_health, get_overall_health
        health_data = get_system_health()
        health_data["simulation"] = mode_state.is_simulation
        health_data["mode"] = mode_state.mode
        return jsonify(health_data)
    except ImportError:
        return jsonify({
            "overall": "UNKNOWN",
            "subsystems": {},
            "error": "system_health module not available",
            "simulation": mode_state.is_simulation,
            "mode": mode_state.mode,
        })


@api.route("/api/system/health/<subsystem_name>")
def subsystem_health(subsystem_name):
    """Get health status for a specific subsystem (Phase 19)."""
    try:
        from system_health import get_subsystem_health
        health = get_subsystem_health(subsystem_name)
        if health is None:
            return jsonify({"error": f"subsystem '{subsystem_name}' not found"}), 404
        health["simulation"] = mode_state.is_simulation
        health["mode"] = mode_state.mode
        return jsonify(health)
    except ImportError:
        return jsonify({"error": "system_health module not available"}), 503


# ---------------------------------------------------------------------------
# Authentication endpoints
# ---------------------------------------------------------------------------

@api.route("/api/auth/login", methods=["POST"])
def auth_login():
    """Exchange username+password for a bearer token + user record."""
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    ip = auth.client_ip(request)
    ua = request.headers.get("User-Agent", "")
    user = auth.authenticate(username, password)
    if user is None:
        auth.log_access(username, False, ip, ua)
        return jsonify({"error": "invalid username or password"}), 401
    token, expires_at = auth.create_session(user["id"], ip=ip, user_agent=ua)
    auth.log_access(username, True, ip, ua)
    return jsonify({
        "token": token,
        "expires_at": expires_at,
        "user": auth.user_payload(user),
    })


@api.route("/api/auth/access", methods=["GET"])
@_require_auth("admin")
def auth_access():
    """Owner view: who has been opening this deployment, and who is on now.

    `log` = newest-first login attempts (user, time, success, IP, browser).
    `active_sessions` = unexpired logins with their login origin.
    Admin-only: this is exactly the information an attacker would want.
    """
    return jsonify({
        "log": auth.get_access_log(limit=request.args.get("limit", 100)),
        "active_sessions": auth.get_active_sessions(),
    })


@api.route("/api/auth/demo-credentials", methods=["GET"])
def auth_demo_credentials():
    """Railway demo link helper: pre-fill login so visitors just press Enter.

    ONLY active when FLEETIQ_DEMO_AUTOFILL=1 (set on the Railway backend
    service, never locally). Otherwise 404 — no credentials are exposed.
    Anyone with the link can read these, by design for judge demos.
    """
    import os
    if os.environ.get("FLEETIQ_DEMO_AUTOFILL", "0").strip() != "1":
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "enabled": True,
        "username": os.environ.get("FLEETIQ_ADMIN_USER", "admin").strip() or "admin",
        "password": os.environ.get("FLEETIQ_ADMIN_PASSWORD", "admin123"),
    })


@api.route("/api/auth/me", methods=["GET"])
@_require_auth()
def auth_me():
    return jsonify({"user": auth.user_payload(auth.require_auth(request))})


@api.route("/api/auth/logout", methods=["POST"])
@_require_auth()
def auth_logout():
    """Invalidate the current bearer token server-side."""
    token = auth.token_from_request(request)
    if token:
        auth.revoke_session(token)
    return jsonify({"success": True})


@api.route("/api/auth/me/password", methods=["POST"])
@_require_auth()
def auth_change_own_password():
    """Let an authenticated user change their own password."""
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


@api.route("/api/auth/users", methods=["GET"])
@_require_auth("admin")
def admin_list_users():
    users = [auth.user_payload(u) for u in auth.list_users()]
    return jsonify({"users": users})


@api.route("/api/auth/users", methods=["POST"])
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


@api.route("/api/auth/users/<int:user_id>/role", methods=["POST"])
@_require_auth("admin")
def admin_change_role(user_id):
    role = ((request.get_json(silent=True) or {}).get("role") or "").strip().lower()
    ok, msg = auth.update_user_role(user_id, role)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"success": True, "user": auth.user_payload(auth.get_user_by_id(user_id))})


@api.route("/api/auth/users/<int:user_id>/active", methods=["POST"])
@_require_auth("admin")
def admin_set_active(user_id):
    body = request.get_json(silent=True) or {}
    ok, msg = auth.set_user_active(user_id, bool(body.get("active")))
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"success": True, "user": auth.user_payload(auth.get_user_by_id(user_id))})


@api.route("/api/auth/users/<int:user_id>/password", methods=["POST"])
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


# ---------------------------------------------------------------------------
# Fleet & bus endpoints
# ---------------------------------------------------------------------------

@api.route("/api/fleet/summary")
def fleet_summary():
    """Operator-oriented fleet-level aggregation for the command dashboard."""
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


@api.route("/api/overview")
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


@api.route("/api/buses")
def get_buses():
    buses = store.get_buses()
    return jsonify({
        "buses": buses,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/buses/<bus_id>")
def get_bus(bus_id):
    bus = store.get_bus(bus_id)

    if not bus and bus_id == "PROTO-001":
        from server import _proto_bus
        bus = _proto_bus()

    if not bus:
        return jsonify({"error": "bus not found"}), 404

    recent = [e for e in store.get_events(500) if e["bus_id"] == bus_id]
    # incidents for the header watch-dot (who is watching / acknowledged)
    try:
        from incident_intelligence import get_bus_incidents
        bus_incidents = [i.to_dict() for i in get_bus_incidents(bus_id, limit=10)]
    except Exception:
        bus_incidents = []
    return jsonify({
        "bus": bus,
        "recent_events": recent,
        "bus_incidents": bus_incidents,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/buses/<bus_id>/health")
def bus_health(bus_id):
    """Per-bus predictive health: maintenance decision + days-until-failure per component."""
    data_source = DataSource.SIMULATION if mode_state.is_simulation else DataSource.LIVE
    if not store.get_bus(bus_id) and bus_id != "PROTO-001":
        return jsonify({"error": "bus not found"}), 404
    vh = health_tracker.get_vehicle_health(bus_id, data_source)
    payload = vh.to_dict()
    payload["simulation"] = mode_state.is_simulation
    payload["mode"] = mode_state.mode
    return jsonify(payload)


# ---------------------------------------------------------------------------
# Risk endpoints
# ---------------------------------------------------------------------------

@api.route("/api/risk")
def risk():
    events = store.get_events(1000)
    weights = _risk_weights()
    buses = store.get_buses()
    exposures = {}
    for b in buses:
        exp = road_risk_engine.compute_bus_exposure(b)
        exposures[b["bus_id"]] = exp.to_dict()
    items = fleet_risk(buses, events, risk_weights=weights)
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


@api.route("/api/buses/<bus_id>/risk")
def bus_risk_endpoint(bus_id):
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "risk_score": 0, "risk_level": "NORMAL", "risk_factors": [], "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    events = [e for e in store.get_events(1000) if e["bus_id"] == bus_id]
    return jsonify(bus_risk(bus, events, risk_weights=_risk_weights()))


@api.route("/api/buses/<bus_id>/risk/history")
def bus_risk_history(bus_id):
    """Phase 15: Get risk history for a bus."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "history": [], "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    limit = request.args.get("limit", 20, type=int)
    history = get_risk_history(bus_id, limit=limit)
    history_list = [{"timestamp": h[0], "score": h[1], "state": h[2]} for h in history]
    return jsonify({
        "bus_id": bus_id,
        "history": history_list,
        "count": len(history_list),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/buses/<bus_id>/risk/trend")
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


@api.route("/api/risk/events")
def risk_events():
    """Phase 15: Get risk events."""
    bus_id = request.args.get("bus_id")
    limit = request.args.get("limit", 100, type=int)
    events = persistence.load_risk_events(bus_id=bus_id, limit=limit)
    return jsonify({
        "events": events,
        "count": len(events),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


# ---------------------------------------------------------------------------
# Timeline & actions endpoints
# ---------------------------------------------------------------------------

@api.route("/api/buses/<bus_id>/timeline")
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


@api.route("/api/actions")
def get_actions():
    bus_id = request.args.get("bus_id")
    unacked = request.args.get("unacked", "false").lower() == "true"
    acts = action_store.get_actions(bus_id=bus_id, unacked_only=unacked)
    return jsonify({"actions": acts, "simulation": mode_state.is_simulation, "mode": mode_state.mode})


@api.route("/api/actions/<action_id>/ack", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def ack_action(action_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    act = action_store.ack_action(action_id, operator)
    if not act:
        return jsonify({"error": "action not found"}), 404
    return jsonify({"action": act})


@api.route("/api/actions/<action_id>/resolve", methods=["POST"])
@_require_auth("supervisor", "admin")
def resolve_action(action_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    act = action_store.resolve_action(action_id, operator)
    if not act:
        return jsonify({"error": "action not found"}), 404
    return jsonify({"action": act})


@api.route("/api/actions/evaluate", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def evaluate_actions():
    evaluate_fleet(store.get_buses(), store.get_events(1000))
    return jsonify({"evaluated": True, "simulation": mode_state.is_simulation, "mode": mode_state.mode})


# ---------------------------------------------------------------------------
# Events & alerts endpoints
# ---------------------------------------------------------------------------

@api.route("/api/events")
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


@api.route("/api/alerts")
def get_alerts():
    """Recent real-time alerts."""
    limit = min(int(request.args.get("limit", 50) or 50), 200)
    items = alerts.project_alerts(store.get_events(1000))[:limit]
    return jsonify({
        "alerts": items,
        "count": len(items),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/events/<event_id>/acknowledge", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def acknowledge(event_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    ev = store.acknowledge_event(event_id, operator)
    if not ev:
        return jsonify({"error": "event not found"}), 404
    return jsonify({"event": ev})


@api.route("/api/events/<event_id>/review", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def review(event_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    ev = store.review_event(event_id, operator)
    if not ev:
        return jsonify({"error": "event not found"}), 404
    return jsonify({"event": ev})


@api.route("/api/events/<event_id>/resolve", methods=["POST"])
@_require_auth("supervisor", "admin")
def resolve(event_id):
    operator = (request.get_json(silent=True) or {}).get("operator")
    ev = store.resolve_event(event_id, operator)
    if not ev:
        return jsonify({"error": "event not found"}), 404
    return jsonify({"event": ev})


@api.route("/api/events/<event_id>/status", methods=["POST"])
@_require_auth("supervisor", "admin")
def set_status(event_id):
    body = request.get_json(silent=True) or {}
    ev = store.set_event_status(event_id, body.get("status"), body.get("operator"))
    if not ev:
        return jsonify({"error": "event not found or invalid status"}), 404
    return jsonify({"event": ev})


@api.route("/api/events/status", methods=["POST"])
@_require_auth("supervisor", "admin")
def bulk_status():
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in ("ACTIVE", "REVIEWING", "ACKNOWLEDGED", "RESOLVED"):
        return jsonify({"error": "invalid status"}), 400
    count = store.set_event_status_many(status, operator=body.get("operator"), bus_id=body.get("bus_id"))
    return jsonify({"updated": count})


# ---------------------------------------------------------------------------
# Road defects endpoints
# ---------------------------------------------------------------------------

@api.route("/api/road-defects")
def road_defects():
    defects = store.get_road_defects()
    return jsonify({
        "defects": defects,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/roads/risk")
def roads_risk():
    rebuild_zones()
    return jsonify({
        "zones": road_risk_engine.get_zones(),
        "clusters": road_risk_engine.get_clusters(),
        "route_index": road_risk_engine.get_route_risk_index(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/roads/summary")
def roads_summary():
    """Road intelligence summary for the dashboard."""
    rebuild_zones()
    summary = get_road_summary()
    summary["simulation"] = mode_state.is_simulation
    summary["mode"] = mode_state.mode
    return jsonify(summary)


@api.route("/api/buses/<bus_id>/road-threats")
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


@api.route("/api/buses/<bus_id>/road-exposure")
def bus_road_exposure(bus_id):
    """Get a specific bus's exposure to road risk zones."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            from road_risk import get_bus_exposure
            return jsonify({"bus_id": bus_id, "exposure": get_bus_exposure(bus) if bus else {"exposure_state": "UNKNOWN"}, "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    from road_risk import get_bus_exposure
    return jsonify({
        "bus_id": bus_id,
        "exposure": get_bus_exposure(bus),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/roads/exposures")
def roads_exposures():
    """Get all buses' exposure to road risk zones."""
    from road_risk import get_all_bus_exposures
    return jsonify({
        "exposures": get_all_bus_exposures(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


# ---------------------------------------------------------------------------
# Vehicle health endpoints
# ---------------------------------------------------------------------------

@api.route("/api/health/predictive")
def predictive_health():
    """Vehicle health intelligence with component health, anomalies, and maintenance recommendations."""
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

        # Sticky flag: once a bus needs maintenance it stays listed until
        # an operator reviews it (review-to-clear), even if its counters
        # decay back under threshold on a later tick.
        decision = vh.maintenance_decision or {}
        if decision.get("status") and decision.get("status") != "CAN_CONTINUE":
            days = decision.get("days_to_failure")
            store.flag_maintenance(bid, days=days, status=decision.get("status"))

    # Re-inject flagged-but-unreviewed buses whose live counters have
    # decayed: they keep their last-known snapshot, marked sticky.
    reviews = store.get_maintenance_reviews()
    flagged = store.get_maintenance_flagged()
    for bid, flag in flagged.items():
        if bid in reviews:
            continue
        live = summaries.get(bid)
        live_decision = (live or {}).get("maintenance_decision") or {}
        if live_decision.get("status") and live_decision.get("status") != "CAN_CONTINUE":
            continue  # already listed from live data
        summaries[bid] = {
            "overall_state": (live or {}).get("overall_state", "WARNING"),
            "overall_score": (live or {}).get("overall_score", 0),
            "components": (live or {}).get("components", {}),
            "maintenance_decision": {
                "status": flag.get("last_status") or "PLAN_MAINTENANCE",
                "days_to_failure": flag.get("last_days"),
                "reason": "Previously flagged — awaiting operator review (sticky).",
                "sticky": True,
            },
            "maintenance_recommendations": (live or {}).get("maintenance_recommendations", []),
            "sticky": True,
            "first_flagged_at": flag.get("first_flagged_at"),
        }

    return jsonify({
        "summaries": summaries,
        "predictions": all_predictions,
        "recommendations": all_recommendations,
        "anomalies": anomalies,
        "maintenance_reviews": reviews,
        "fleet_summary": get_fleet_health_summary(data_source),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
        "data_source": data_source.value,
        "note": "All values are heuristic estimates from rolling synthetic counters. No trained ML models. RUL is linear trend projection.",
    })


@api.route("/api/health/maintenance/review", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def review_maintenance():
    """Review-to-clear: acknowledge a vehicle's maintenance entry so it
    leaves the Vehicles Needing Maintenance list."""
    body = request.get_json(silent=True) or {}
    bus_id = body.get("bus_id")
    if not bus_id:
        return jsonify({"error": "bus_id required"}), 400
    operator = body.get("operator")
    record = store.review_maintenance(bus_id, operator=operator, note=body.get("note"))
    store.clear_maintenance_flag(bus_id)
    try:
        health_tracker.reset_bus(bus_id)
    except Exception:
        pass
    return jsonify({"review": record})


@api.route("/api/health/fleet")
def fleet_health():
    """Fleet-wide vehicle health summary for dashboard."""
    data_source = DataSource.SIMULATION if mode_state.is_simulation else DataSource.LIVE
    return jsonify({
        "fleet": get_fleet_health_summary(data_source),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
        "data_source": data_source.value,
    })


# ---------------------------------------------------------------------------
# ETA endpoints
# ---------------------------------------------------------------------------

@api.route("/api/traffic/hotspots")
def traffic_hotspots():
    """Active high-traffic hotspots for the map overlay (5+ buses / 150 m / >60 s)."""
    from traffic_engine import traffic_monitor
    return jsonify({
        "hotspots": traffic_monitor.get_hotspots(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/traffic/analytics")
def traffic_analytics():
    """Congestion analytics derived from the traffic heat-map engine."""
    from traffic_engine import traffic_monitor
    data = traffic_monitor.analytics()
    data["simulation"] = mode_state.is_simulation
    data["mode"] = mode_state.mode
    return jsonify(data)


@api.route("/api/traffic/heatmap")
def traffic_heatmap():
    """Discretized congestion heat-map cells (from current bus positions)."""
    from congestion_heatmap import congestion_heatmap
    data = congestion_heatmap.get_heat()
    data["simulation"] = mode_state.is_simulation
    data["mode"] = mode_state.mode
    return jsonify(data)


@api.route("/api/od/analytics")
def od_analytics_endpoint():
    """Origin-Destination flows estimated from boarding-by-stop data."""
    from od_analytics import compute_od
    data = compute_od()
    data["simulation"] = mode_state.is_simulation
    data["mode"] = mode_state.mode
    return jsonify(data)


@api.route("/api/traffic/stats")
def traffic_stats():
    """Vehicle detection & counting stats from the road camera (YOLOv8 COCO)."""
    try:
        from ai.road.traffic_detector import traffic_detector
        stats = traffic_detector.get_stats()
    except Exception as e:
        stats = {"error": str(e)}
    stats["simulation"] = mode_state.is_simulation
    stats["mode"] = mode_state.mode
    return jsonify(stats)


@api.route("/api/pedestrian/stats")
def pedestrian_stats():
    """Pedestrian (vulnerable road user) detection stats from the road camera."""
    try:
        from ai.road.pedestrian_detector import pedestrian_detector
        stats = pedestrian_detector.get_stats()
    except Exception as e:
        stats = {"error": str(e)}
    stats["simulation"] = mode_state.is_simulation
    stats["mode"] = mode_state.mode
    return jsonify(stats)


@api.route("/api/analytics/operations")
def operations_analytics_endpoint():
    """Operations analytics: maintenance risk, traffic, road quality, punctuality, demand."""
    from operations_analytics import operations_analytics
    return jsonify(operations_analytics())


@api.route("/api/eta")
def fleet_eta():
    """Fleet-wide ETA with deterministic RNG for consistency."""
    rng = random.Random(42)
    all_etas = compute_all_etas(store.get_buses(), rng)
    delay_counts = {"ON_TIME": 0, "EARLY": 0, "MINOR_DELAY": 0,
                    "SIGNIFICANT_DELAY": 0, "SEVERE_DELAY": 0, "NO_ROUTE": 0}
    for bus_id, e in all_etas.items():
        state = e.get("delay_summary", "UNKNOWN")
        delay_counts[state] = delay_counts.get(state, 0) + 1
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


@api.route("/api/eta/summary")
def fleet_eta_summary():
    """Fleet-level ETA KPI for the dashboard."""
    summary = get_fleet_eta_summary(store.get_buses())
    summary["simulation"] = mode_state.is_simulation
    summary["mode"] = mode_state.mode
    return jsonify(summary)


@api.route("/api/buses/<bus_id>/eta")
def bus_eta(bus_id):
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "eta_minutes": 0, "delay_summary": "No route",
                            "delay_causes": [], "source": "UNKNOWN",
                            "simulation": False, "mode": "live"})
        return jsonify({"error": "bus not found"}), 404
    rng = random.Random(hash(bus_id) % 10000)
    result = compute_all_etas([bus], rng).get(bus_id, {"error": "no route"})
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


# ---------------------------------------------------------------------------
# Demand endpoints
# ---------------------------------------------------------------------------

@api.route("/api/demand")
def fleet_demand():
    rng = random.Random()
    all_fc = forecast_all(store.get_buses(), rng, 5)
    return jsonify({
        "buses": all_fc,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/buses/<bus_id>/demand")
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


@api.route("/api/demand/intelligence")
def demand_intelligence():
    """Fleet-level demand intelligence summary."""
    buses = store.get_buses()
    summary = get_fleet_load_summary(buses)
    summary["simulation"] = mode_state.is_simulation
    summary["mode"] = mode_state.mode
    return jsonify(summary)


@api.route("/api/demand/routes")
def route_demand():
    """Route-level demand summary."""
    buses = store.get_buses()
    routes = get_route_demand_summary(buses)
    return jsonify({
        "routes": routes,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/buses/<bus_id>/capacity")
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


@api.route("/api/buses/<bus_id>/occupancy")
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


@api.route("/api/buses/<bus_id>/pressure")
def bus_pressure(bus_id):
    """Bus capacity pressure from forecast demand."""
    bus = store.get_bus(bus_id)
    if not bus:
        if _is_proto(bus_id):
            return jsonify({"bus_id": bus_id, "pressure_level": "UNKNOWN"})
        return jsonify({"error": "bus not found"}), 404
    rng = random.Random(42)
    fc = forecast_bus(bus_id, rng, 3)
    forecast_boardings = sum(f.get("forecast_boardings", 0) for f in fc)
    pressure = get_capacity_pressure(bus, forecast_boardings)
    pressure["simulation"] = mode_state.is_simulation
    pressure["mode"] = mode_state.mode
    return jsonify(pressure)


# ---------------------------------------------------------------------------
# Analytics endpoints
# ---------------------------------------------------------------------------

@api.route("/api/analytics")
def analytics():
    events = store.get_events(1000)
    buses = store.get_buses()

    from collections import Counter
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

    # service day 5 AM → 11 PM (matches simulator HOURLY_DEMAND window)
    hours = list(range(5, 24))
    hourly = Counter()
    for b in buses:
        for h, v in (b.get("boarding_by_hour") or {}).items():
            hourly[h] += v
    peak_h = max(hours, key=lambda h: hourly[h])
    quiet_h = min(hours, key=lambda h: hourly[h])

    def h12(h):
        return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"

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
        "routes": _get_routes_for_analytics(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/analytics/incidents-drilldown")
def analytics_incidents_drilldown():
    """Drill-down detail for the analytics KPI tiles (Potholes Today,
    Road Hazards, Crash Detected).

    For each tile this returns the underlying detections with: when each was
    detected, where (lat/lon + nearest route), which bus found it, how many
    buses detected the same spot today, and which bus detected it FIRST
    (the followers repeat-detected it). Crash rows additionally carry the
    clip reference and driver/conductor details for a legal incident report.
    """
    buses = {b["bus_id"]: b for b in store.get_buses()}
    events = store.get_events(1000)
    today = date.today().isoformat()

    def _bus_meta(bus_id):
        b = buses.get(bus_id) or {}
        return {
            "bus_id": bus_id,
            "route": b.get("route_code") or b.get("route") or "—",
            "driver": (b.get("driver") or {}).get("name") or "Unknown",
            "conductor": (b.get("crew") or {}).get("conductor") or (b.get("crew") or {}).get("name") or "Not recorded",
            "reg_no": b.get("reg_no") or "—",
        }

    def _same_day(ts):
        return (ts or "")[:10] == today

    # ---- group POTHOLE / ROAD_DEFECT events by rounded location (a "spot")
    # so repeat detections of the same pothole by following buses aggregate.
    def _group(etype_keys):
        spots = {}
        for e in events:
            if (e.get("event_type") or "").upper() not in etype_keys:
                continue
            lat = e.get("latitude") or 0
            lon = e.get("longitude") or 0
            key = (round(lat, 3), round(lon, 3))  # ~100 m bucket
            sp = spots.setdefault(key, {
                "lat": lat, "lon": lon, "detections": [],
            })
            sp["detections"].append({
                "event_id": e.get("event_id"),
                "time": e.get("timestamp"),
                "bus_id": e.get("bus_id"),
                "severity": e.get("severity"),
                "status": e.get("status"),
                "reviewed": e.get("status") != "ACTIVE",
            })
        out = []
        for sp in spots.values():
            dets = sorted(sp["detections"], key=lambda d: d["time"] or "")
            todays = [d for d in dets if _same_day(d["time"])]
            if not todays:
                continue
            bus_ids = []
            for d in dets:
                if d["bus_id"] not in bus_ids:
                    bus_ids.append(d["bus_id"])
            first = _bus_meta(dets[0]["bus_id"])
            followers = [_bus_meta(b) for b in bus_ids[1:6]]
            out.append({
                "lat": round(sp["lat"], 5),
                "lon": round(sp["lon"], 5),
                "first_time": dets[0]["time"],
                "last_time": dets[-1]["time"],
                "today_count": len(todays),
                "total_detections": len(dets),
                "bus_count": len(bus_ids),
                "detected_by": first,
                "repeat_detected_by": followers,
                "severity": dets[-1]["severity"],
                "reviewed": all(d["reviewed"] for d in todays),
                "review_status": "reviewed" if all(d["reviewed"] for d in todays) else "awaiting review",
            })
        out.sort(key=lambda s: (s["today_count"], s["total_detections"]), reverse=True)
        return out

    pothole_spots = _group({"POTHOLE", "POTHOLE_CLUSTER", "ROAD_DEFECT"})

    # Road hazards = active road-defect records from the store (clustered
    # defects), joined with today's detections for time/place/bus detail.
    hazard_spots = []
    for d in store.get_road_defects():
        if d.get("status") != "ACTIVE":
            continue
        hazard_spots.append({
            "lat": round(d.get("latitude") or 0, 5),
            "lon": round(d.get("longitude") or 0, 5),
            "first_time": d.get("first_detected"),
            "last_time": d.get("last_detected"),
            "today_count": 1 if _same_day(d.get("last_detected")) else 0,
            "total_detections": d.get("detection_count", 1),
            "bus_count": len(d.get("detected_by_buses") or []) or 1,
            "detected_by": _bus_meta((d.get("detected_by_buses") or [d.get("reported_by_bus") or "—"])[0]),
            "repeat_detected_by": [_bus_meta(b) for b in (d.get("detected_by_buses") or [])[1:6]],
            "severity": d.get("severity", "WARNING"),
            "type": d.get("type", "ROAD_DEFECT"),
            "reviewed": d.get("status") == "RESOLVED",
            "review_status": "reviewed" if d.get("status") == "RESOLVED" else "awaiting review",
        })
    hazard_spots.sort(key=lambda s: (s["today_count"], s["total_detections"]), reverse=True)

    # Crashes — full detail for a police/legal incident report.
    crashes = []
    for e in events:
        if (e.get("event_type") or "").upper() != "CRASH":
            continue
        meta = _bus_meta(e.get("bus_id"))
        ad = e.get("additional_data") or {}
        crashes.append({
            "event_id": e.get("event_id"),
            "time": e.get("timestamp"),
            "lat": e.get("latitude"),
            "lon": e.get("longitude"),
            "severity": e.get("severity"),
            "status": e.get("status"),
            "route": meta["route"],
            "detected_by": meta,
            "clip_url": ad.get("clip_url") or f"/clips/{e.get('event_id')}.mp4",
            "clip_available": bool(ad.get("clip_url")),
            "location_description": ad.get("location") or ad.get("note") or "See GPS on map",
            "impact_detected_by": ad.get("source") or e.get("sensor_source") or "accelerometer",
            "confidence": e.get("confidence"),
        })
    crashes.sort(key=lambda c: c["time"] or "", reverse=True)

    return jsonify({
        "potholes": pothole_spots,
        "road_hazards": hazard_spots,
        "crashes": crashes,
        "potholes_today": sum(1 for _ in pothole_spots),
        "road_hazards_today": len(hazard_spots),
        "crashes_today": sum(1 for c in crashes if _same_day(c["time"])),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


def _build_pothole_analytics():
    """Date-wise pothole detections (last 8 days), broken down by bus route."""
    today = date.today()
    rng = random.Random(2049)
    routes = [(r["code"], len(r["stops"])) for r in _get_routes_for_analytics()]
    total_w = sum(s for _, s in routes)
    live = len([d for d in store.get_road_defects() if d["status"] == "ACTIVE"])

    days = [(today - timedelta(days=i)) for i in range(7, -1, -1)]
    series = []
    for i, d in enumerate(days):
        base = 4 + i * 0.6 + rng.uniform(-1.5, 1.5)
        if d.weekday() >= 5:
            base += 1
        if i == len(days) - 1:
            base += live
        total = max(1, int(round(base)))

        by_route = {}
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

    return series


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------

@api.route("/api/settings")
def settings():
    s = store.get_settings()
    s["system_mode"] = mode_state.mode
    s["live_prototype_connected"] = len(mode_state.get_connected_live_nodes()) > 0
    s["live_bus_id"] = list(mode_state.get_connected_live_nodes().keys())
    return jsonify(s)


@api.route("/api/settings", methods=["POST"])
@_require_auth("admin")
def update_settings():
    body = request.get_json(silent=True) or {}
    updated = store.update_settings(body)
    return jsonify(updated)


# ---------------------------------------------------------------------------
# Feature Toggles endpoints
# ---------------------------------------------------------------------------

@api.route("/api/features", methods=["GET"])
def get_features():
    """Get all feature toggle states."""
    from feature_toggles import feature_toggles
    return jsonify(feature_toggles.get_all())


@api.route("/api/features", methods=["POST"])
def update_features():
    """Update feature toggle states."""
    from feature_toggles import feature_toggles
    body = request.get_json(silent=True) or {}
    if "features" in body:
        # Batch update: {"features": {"audio_alerts": true, ...}}
        changed = feature_toggles.update(body["features"])
    else:
        # Single update: {"key": "audio_alerts", "enabled": true}
        key = body.get("key")
        enabled = body.get("enabled")
        if key is None or enabled is None:
            return jsonify({"error": "Missing 'key' or 'enabled'"}), 400
        changed = 1 if feature_toggles.set(key, enabled) else 0
    return jsonify({
        "ok": True,
        "changed": changed,
        "features": feature_toggles.get_all(),
    })


@api.route("/api/features/<key>", methods=["PUT"])
def toggle_feature(key):
    """Toggle a single feature."""
    from feature_toggles import feature_toggles
    body = request.get_json(silent=True) or {}
    enabled = body.get("enabled")
    if enabled is None:
        return jsonify({"error": "Missing 'enabled' field"}), 400
    changed = feature_toggles.set(key, enabled)
    return jsonify({
        "ok": True,
        "changed": changed,
        "key": key,
        "enabled": feature_toggles.get(key),
    })


# ---------------------------------------------------------------------------
# Test Audio endpoint
# ---------------------------------------------------------------------------

@api.route("/api/test-audio", methods=["POST"])
def test_audio():
    """Test audio playback. Plays a warning tone for 2 seconds.

    Gated by audio_alerts: refuses to play while the toggle is OFF so
    startup stays silent. Enable Audio Alerts in Feature Toggles first.
    """
    import sys
    import os
    import threading
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    try:
        from feature_toggles import feature_toggles
        if not feature_toggles.get("audio_alerts"):
            return jsonify({
                "ok": False,
                "error": "Audio Alerts is OFF. Enable it in Feature Toggles first.",
            }), 409
        from bus_node.utils.alert_manager import AlertManager
        # Sync with toggle (do NOT force-unmute)
        AlertManager.muted = not feature_toggles.get("audio_alerts")
        am = AlertManager()
        am.update("WARNING")
        def stop_test():
            import time
            time.sleep(2)
            am.stop()
        threading.Thread(target=stop_test, daemon=True).start()
        return jsonify({"ok": True, "message": "Playing test tone", "muted": AlertManager.muted})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Mode switching endpoints
# ---------------------------------------------------------------------------

@api.route("/api/mode", methods=["GET"])
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


@api.route("/api/mode/switch", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def switch_mode():
    """Switch between simulation and live modes."""
    from server import _get_simulator, _set_simulator, _setup_live_proto, _auto_start_live_cameras, _auto_start_dds
    from simulator import FleetSimulator
    
    body = request.get_json(silent=True) or {}
    new_mode = body.get("mode")

    if not new_mode:
        return jsonify({"error": "Missing 'mode' field. Use 'simulation' or 'live'."}), 400

    success, message = mode_state.switch_mode(new_mode)

    if not success:
        return jsonify({"error": message}), 400

    sim = _get_simulator()

    if new_mode == "live":
        if sim:
            sim._stop = True
        store.buses.clear()
        store.road_defects.clear()
        _setup_live_proto()
        _auto_start_live_cameras()
        _auto_start_dds()
        return jsonify({
            "success": True,
            "mode": "live",
            "message": "Switched to LIVE PROTOTYPE mode. Cameras starting...",
        })
    else:
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
            "message": "Switched to SIMULATION mode. 300 buses active.",
        })


@api.route("/api/live/status", methods=["GET"])
def live_status():
    """Get live prototype connection status."""
    connected = mode_state.get_connected_live_nodes()
    all_nodes = mode_state.get_live_nodes()

    node_details = []
    for bus_id, node in all_nodes.items():
        import time
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


# ---------------------------------------------------------------------------
# DDS endpoints
# ---------------------------------------------------------------------------

@api.route("/api/dds/status", methods=["GET"])
def dds_status():
    """Full DDS engine status."""
    from ai.driver.driver_drowsiness import driver_detector
    status = driver_detector.get_status()
    mode_state.update_live_node("PROTO-001", {
        "gps_available": True,
        "sensors": {"driver_ai": status.get("phase", "idle"), "camera": "driver"},
    })
    return jsonify({
        **status,
        "mode": mode_state.mode,
        "simulation": mode_state.is_simulation,
    })


@api.route("/api/dds/calibrate", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_calibrate():
    """Start the 5 s personal-baseline calibration."""
    blocked = _require_live()
    if blocked:
        return blocked
    from ai.camera_manager import camera_manager
    from ai.driver.driver_drowsiness import driver_detector
    import threading
    import time
    
    if not camera_manager.is_slot_active("driver"):
        threading.Thread(
            target=lambda: camera_manager.set_single_camera_test_mode("driver"),
            daemon=True,
        ).start()
        time.sleep(0.8)
    ok, msg = driver_detector.start_calibration()
    return jsonify({"success": ok, "message": msg, "status": driver_detector.get_status()})


@api.route("/api/dds/start", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_start():
    """Start real DDS monitoring."""
    blocked = _require_live()
    if blocked:
        return blocked
    from ai.camera_manager import camera_manager
    from ai.driver.driver_drowsiness import driver_detector
    import threading
    import time
    
    if not camera_manager.is_slot_active("driver"):
        threading.Thread(
            target=lambda: camera_manager.set_single_camera_test_mode("driver"),
            daemon=True,
        ).start()
        time.sleep(0.8)
    ok, msg = driver_detector.start_monitoring()
    return jsonify({"success": ok, "message": msg, "status": driver_detector.get_status()})


@api.route("/api/dds/stop", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_stop():
    """Stop DDS monitoring."""
    from ai.driver.driver_drowsiness import driver_detector
    ok, msg = driver_detector.stop_monitoring()
    return jsonify({"success": ok, "message": msg, "status": driver_detector.get_status()})


@api.route("/api/dds/reset", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_reset():
    """Reset the DDS engine to idle."""
    from ai.driver.driver_drowsiness import driver_detector
    ok, msg = driver_detector.reset()
    return jsonify({"success": ok, "message": msg, "status": driver_detector.get_status()})


@api.route("/api/dds/subprocess/status", methods=["GET"])
def dds_subprocess_status():
    """Status of the ORIGINAL DDS application."""
    from ai.dds.dds_process import get_dds_manager, DDS_ENTRY_POINT
    mgr = get_dds_manager()
    st = mgr.get_status()
    st["available"] = os.path.exists(DDS_ENTRY_POINT)
    st["simulation"] = mode_state.is_simulation
    st["mode"] = mode_state.mode
    return jsonify(st)


@api.route("/api/dds/subprocess/start", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_subprocess_start():
    """Launch the original DDS application as a subprocess."""
    import os
    import sys
    
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


@api.route("/api/dds/subprocess/stop", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def dds_subprocess_stop():
    """Stop the original DDS subprocess."""
    from ai.dds.dds_process import get_dds_manager
    mgr = get_dds_manager()
    ok, msg = mgr.stop()
    return jsonify({"success": ok, "message": msg, "status": mgr.get_status()})


@api.route("/api/dds/logs", methods=["GET"])
def dds_logs():
    """Read the latest DDS session logs."""
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


# ---------------------------------------------------------------------------
# Camera / Vision AI endpoints
# ---------------------------------------------------------------------------

@api.route("/api/camera/status", methods=["GET"])
def camera_status():
    """Get camera status and available cameras."""
    from ai.camera_manager import camera_manager
    return jsonify(camera_status_data(camera_manager))


@api.route("/api/camera/test-mode", methods=["POST"])
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


@api.route("/api/camera/multi-camera", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def set_multi_camera():
    """Set multi-camera mode."""
    from ai.camera_manager import camera_manager
    success, message = camera_manager.set_multi_camera_mode()
    return jsonify({"success": success, "message": message, "mode": camera_manager.mode})


@api.route("/api/camera/start", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def start_camera():
    """Start camera in test mode (non-blocking)."""
    from ai.camera_manager import camera_manager
    import threading
    
    body = request.get_json(silent=True) or {}
    slot = body.get("slot", "driver")
    if slot not in ("driver", "cabin", "road"):
        return jsonify({"error": "Invalid slot"}), 400

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


@api.route("/api/camera/stop", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def stop_camera():
    """Stop camera manager and all cameras."""
    from ai.camera_manager import camera_manager
    camera_manager.stop()
    return jsonify({"success": True, "mode": "stopped"})


@api.route("/api/camera/stream/<slot>", methods=["GET"])
@_require_auth("operator", "supervisor", "admin")
def camera_stream(slot):
    """Get a single frame as base64 JPEG with AI detection overlay.

    Auth required: this is live driver/cabin imagery and must never be
    served to an unauthenticated client.
    """
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


@api.route("/api/camera/detections/<slot>", methods=["GET"])
@_require_auth("operator", "supervisor", "admin")
def camera_detections(slot):
    """Get current AI detection results for a slot (auth required)."""
    from ai.camera_manager import camera_manager
    if slot not in ("driver", "cabin", "road"):
        return jsonify({"error": "Invalid slot"}), 400

    results = camera_manager.get_detection_results(slot)
    return jsonify({"slot": slot, "detections": results})


@api.route("/api/cabin/occupancy", methods=["GET"])
def cabin_occupancy():
    """Cabin occupancy intelligence (Phase 7)."""
    from ai.cabin.occupancy import get_cabin_engine
    return jsonify(get_cabin_engine().public_state(system_mode=mode_state.mode))


@api.route("/api/ai/status", methods=["GET"])
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


@api.route("/api/ai/pothole/stats", methods=["GET"])
def pothole_stats():
    """Get pothole detection statistics."""
    from ai.road.pothole_detector import pothole_detector
    return jsonify(pothole_detector.get_stats())


@api.route("/api/ai/driver/state", methods=["GET"])
def driver_state():
    """Get current driver drowsiness state."""
    from ai.driver.driver_drowsiness import driver_detector
    return jsonify(driver_detector.get_current_state())


# ---------------------------------------------------------------------------
# Incident intelligence endpoints (Phase 16)
# ---------------------------------------------------------------------------

@api.route("/api/incidents")
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
    dicts = [i.to_dict() for i in incidents]
    # Alert-policy ordering (mirrors alerts.py): CRITICAL first, then WARNING,
    # then everything else (vehicle-health / anomaly style items sink to the
    # bottom as INFO). Unfinished work always outranks finished work.
    _sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    _st_rank = {"OPEN": 0, "ACTIVE": 0, "REVIEWING": 1, "INVESTIGATING": 2,
                "ACKNOWLEDGED": 3, "RESPONDING": 2, "RESOLVED": 4, "CLOSED": 5}
    dicts.sort(key=lambda d: (
        _sev_rank.get(d.get("severity"), 4),
        _st_rank.get(d.get("status"), 4),
        str(d.get("created_at") or ""),
    ))
    return jsonify({
        "incidents": dicts,
        "count": len(dicts),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/incidents/active")
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


@api.route("/api/incidents/summary")
def get_incident_summary():
    """Get incident summary statistics."""
    from incident_intelligence import get_incident_summary
    summary = get_incident_summary()
    return jsonify({
        "summary": summary,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/incidents/<incident_id>")
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


@api.route("/api/incidents/<incident_id>/acknowledge", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def acknowledge_incident(incident_id):
    """Acknowledge an incident (accepts the acknowledge-popup payload:
    issue_type / cause / note alongside the operator)."""
    from incident_intelligence import incident_store
    body = request.get_json(silent=True) or {}
    operator = body.get("operator", "unknown")
    incident = incident_store.acknowledge_incident(
        incident_id, operator,
        issue_type=body.get("issue_type") or body.get("ackIssueType"),
        cause=body.get("cause") or body.get("ackCause"),
        note=body.get("note") or body.get("ackNote"),
    )
    if not incident:
        return jsonify({"error": "incident not found or invalid status"}), 404
    # Keep the linked raw events in sync so the events view and workflow
    # counters update in the same instant the operator acknowledges.
    try:
        for ev_id in incident.related_event_ids or []:
            ev = store.acknowledge_event(ev_id, operator)
            if ev is None:
                store.set_event_status(ev_id, "ACKNOWLEDGED", operator)
    except Exception:
        pass
    return jsonify({"incident": incident.to_dict()})


@api.route("/api/incidents/<incident_id>/investigate", methods=["POST"])
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


@api.route("/api/incidents/<incident_id>/resolve", methods=["POST"])
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


@api.route("/api/incidents/<incident_id>/close", methods=["POST"])
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


@api.route("/api/incidents/by-bus/<bus_id>")
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


@api.route("/api/incidents/by-event/<event_id>")
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
# Historical Analytics endpoints (Phase 17)
# ---------------------------------------------------------------------------

@api.route("/api/analytics/historical")
def get_historical_analytics():
    """Comprehensive historical analytics dashboard."""
    from analytics_intelligence import get_analytics_dashboard
    time_range = request.args.get("time_range", "24h")
    custom_start = request.args.get("custom_start")
    custom_end = request.args.get("custom_end")
    result = get_analytics_dashboard(time_range, custom_start, custom_end)
    result["simulation"] = mode_state.is_simulation
    result["mode"] = mode_state.mode
    return jsonify(result)


@api.route("/api/analytics/kpis")
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


@api.route("/api/analytics/events")
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


@api.route("/api/analytics/incidents")
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


@api.route("/api/analytics/risk")
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


@api.route("/api/analytics/eta")
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


@api.route("/api/analytics/load")
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


@api.route("/api/analytics/road")
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


@api.route("/api/analytics/driver-safety")
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


@api.route("/api/analytics/routes")
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


@api.route("/api/analytics/buses")
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


@api.route("/api/analytics/insights")
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
# WebSocket status endpoints (Phase 18)
# ---------------------------------------------------------------------------

@api.route("/api/websocket/status")
def get_websocket_status():
    """WebSocket server status and metrics (Phase 18)."""
    from websocket_handler import get_ws_status, get_ws_metrics, get_ws_connections
    status = get_ws_status()
    status["simulation"] = mode_state.is_simulation
    status["mode"] = mode_state.mode
    return jsonify(status)


@api.route("/api/websocket/metrics")
def get_websocket_metrics():
    """WebSocket performance metrics (Phase 18)."""
    from websocket_handler import get_ws_metrics
    metrics = get_ws_metrics()
    return jsonify({
        "metrics": metrics,
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


# ---------------------------------------------------------------------------
# GTFS / MTC Transit Data endpoints
# ---------------------------------------------------------------------------

@api.route("/api/gtfs/summary")
def gtfs_summary():
    """Summary of loaded GTFS transit data."""
    try:
        from simulator import _ensure_gtfs_loaded, mtc_provider
        _ensure_gtfs_loaded()
        if mtc_provider is None:
            return jsonify({"error": "GTFS data not loaded", "loaded": False}), 200
        return jsonify({
            "loaded": True,
            **mtc_provider.summary(),
            "simulation": mode_state.is_simulation,
        })
    except ImportError:
        return jsonify({"error": "GTFS module not available", "loaded": False}), 200


@api.route("/api/gtfs/routes")
def gtfs_routes():
    """List all MTC bus routes (GTFS-sourced)."""
    try:
        from simulator import _ensure_gtfs_loaded, mtc_provider
        _ensure_gtfs_loaded()
        if mtc_provider is None:
            return jsonify({"routes": [], "count": 0})
        routes = mtc_provider.get_routes()
        result = []
        for r in routes:
            result.append({
                "route_id": r.get("route_id", ""),
                "route_short_name": r.get("route_short_name", ""),
                "route_long_name": r.get("route_long_name", ""),
                "route_type": r.get("route_type", ""),
                "agency_id": r.get("agency_id", ""),
                "stop_count": len(mtc_provider.get_route_stops(r.get("route_id", ""))),
            })
        return jsonify({"routes": result, "count": len(result)})
    except ImportError:
        return jsonify({"routes": [], "count": 0})


@api.route("/api/gtfs/routes/<route_id>")
def gtfs_route_detail(route_id):
    """Detail for a single MTC route including its stops."""
    try:
        from simulator import _ensure_gtfs_loaded, mtc_provider
        _ensure_gtfs_loaded()
        if mtc_provider is None:
            return jsonify({"error": "GTFS data not loaded"}), 404
        route = mtc_provider.get_route(route_id) if hasattr(mtc_provider, 'get_route') else None
        if not route:
            # Try finding by route_id in the routes list
            for r in mtc_provider.get_routes():
                if r.get("route_id") == route_id:
                    route = r
                    break
        if not route:
            return jsonify({"error": f"Route {route_id} not found"}), 404
        stops = mtc_provider.get_route_stops(route_id)
        polyline = mtc_provider.get_route_polyline(route_id)
        return jsonify({
            "route_id": route_id,
            "route_short_name": route.get("route_short_name", ""),
            "route_long_name": route.get("route_long_name", ""),
            "stops": stops,
            "polyline": polyline,
            "stop_count": len(stops),
        })
    except ImportError:
        return jsonify({"error": "GTFS module not available"}), 500


@api.route("/api/gtfs/routes/polylines")
def gtfs_route_polylines():
    """Polylines for many MTC routes at once (for the route-map browsing page).

    Query params:
        q     — optional filter on route short/long name or id
        limit — max routes returned (default 60, max 200)
    """
    try:
        from simulator import _ensure_gtfs_loaded, mtc_provider
        _ensure_gtfs_loaded()
        if mtc_provider is None:
            return jsonify({"polylines": [], "count": 0})
        q = (request.args.get("q") or "").strip().lower()
        try:
            limit = max(1, min(int(request.args.get("limit", 60)), 5000))
        except ValueError:
            limit = 60
        result = []
        for r in mtc_provider.get_routes():
            short = r.get("route_short_name", "")
            long = r.get("route_long_name", "")
            rid = r.get("route_id", "")
            if q and q not in short.lower() and q not in long.lower() and q not in rid.lower():
                continue
            pts = mtc_provider.get_route_polyline(rid)
            if len(pts) < 2:
                continue
            result.append({
                "route_id": rid,
                "route_short_name": short,
                "route_long_name": long,
                "polyline": pts,
            })
            if len(result) >= limit:
                break
        return jsonify({"polylines": result, "count": len(result)})
    except ImportError:
        return jsonify({"polylines": [], "count": 0}), 200


@api.route("/api/gtfs/stops")
def gtfs_stops():
    """List all MTC bus stops."""
    try:
        from simulator import _ensure_gtfs_loaded, mtc_provider
        _ensure_gtfs_loaded()
        if mtc_provider is None:
            return jsonify({"stops": [], "count": 0})
        stops = mtc_provider.get_stops()
        result = []
        for s in stops:
            result.append({
                "stop_id": s.get("stop_id", ""),
                "stop_name": s.get("stop_name", ""),
                "lat": float(s.get("stop_lat", 0)),
                "lon": float(s.get("stop_lon", 0)),
                "routes": mtc_provider.get_routes_serving_stop(s.get("stop_id", "")),
            })
        return jsonify({"stops": result, "count": len(result)})
    except ImportError:
        return jsonify({"stops": [], "count": 0})


@api.route("/api/gtfs/stops/<stop_id>")
def gtfs_stop_detail(stop_id):
    """Detail for a single bus stop."""
    try:
        from simulator import _ensure_gtfs_loaded, mtc_provider
        _ensure_gtfs_loaded()
        if mtc_provider is None:
            return jsonify({"error": "GTFS data not loaded"}), 404
        stop = mtc_provider.get_stop_info(stop_id)
        if not stop:
            return jsonify({"error": f"Stop {stop_id} not found"}), 404
        routes = mtc_provider.get_routes_serving_stop(stop_id)
        return jsonify({
            "stop_id": stop_id,
            "stop_name": stop.get("stop_name", ""),
            "lat": float(stop.get("stop_lat", 0)),
            "lon": float(stop.get("stop_lon", 0)),
            "routes": routes,
        })
    except ImportError:
        return jsonify({"error": "GTFS module not available"}), 500


@api.route("/api/gtfs/search")
def gtfs_search():
    """Search MTC routes and stops by name or ID."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"routes": [], "stops": []})
    try:
        from simulator import _ensure_gtfs_loaded, mtc_provider
        _ensure_gtfs_loaded()
        if mtc_provider is None:
            return jsonify({"routes": [], "stops": []})
        return jsonify(mtc_provider.search(query))
    except ImportError:
        return jsonify({"routes": [], "stops": []})


# ---------------------------------------------------------------------------
# Emergency / Public Safety Intelligence endpoints
# ---------------------------------------------------------------------------

@api.route("/api/emergency/summary")
def emergency_summary():
    """Summary of loaded emergency facility data."""
    from emergency_data import emergency_store
    return jsonify({
        "loaded": True,
        **emergency_store.summary(),
        "simulation": mode_state.is_simulation,
    })


@api.route("/api/emergency/facilities")
def emergency_facilities():
    """List all emergency facilities with optional type filter.

    Query params:
        type: hospital | fire | police | traffic_police (optional)
    """
    from emergency_data import emergency_store
    facility_type = request.args.get("type", "").strip() or None
    facilities = emergency_store.get_all(facility_type)
    return jsonify({
        "facilities": facilities,
        "count": len(facilities),
        "type_filter": facility_type,
    })


@api.route("/api/emergency/facilities/<facility_id>")
def emergency_facility_detail(facility_id):
    """Get a specific emergency facility by ID."""
    from emergency_data import emergency_store
    all_facilities = emergency_store.get_all()
    for f in all_facilities:
        if f.get("facility_id") == facility_id:
            return jsonify(f)
    return jsonify({"error": f"Facility {facility_id} not found"}), 404


@api.route("/api/emergency/nearby")
def emergency_nearby():
    """Find nearest emergency facilities to a GPS coordinate.

    Query params:
        lat: latitude (required)
        lon: longitude (required)
        type: hospital | fire | police | traffic_police (optional, all if omitted)
        max_results: max per category (default 5)
        max_distance: max search radius in km (default 25)
    """
    from emergency_engine import emergency_engine
    try:
        lat = float(request.args.get("lat", 0))
        lon = float(request.args.get("lon", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "lat and lon are required numeric parameters"}), 400

    if lat == 0 and lon == 0:
        return jsonify({"error": "lat and lon are required"}), 400

    facility_type = request.args.get("type", "").strip() or None
    max_results = int(request.args.get("max_results", 5))
    max_distance = float(request.args.get("max_distance", 25.0))

    result = emergency_engine.nearby_facilities(
        lat, lon, facility_type, max_results, max_distance
    )
    return jsonify({
        "location": {"lat": lat, "lon": lon},
        "facilities": result,
        "note": "Distances are straight-line (haversine). Actual response time depends on road network and traffic.",
    })


@api.route("/api/emergency/incident-response", methods=["POST"])
def emergency_incident_response():
    """Generate emergency response recommendation for an incident.

    POST body:
        incident_type: ACCIDENT | FIRE | MEDICAL_EMERGENCY | ...
        lat: latitude
        lon: longitude
        severity: LOW | MEDIUM | HIGH | CRITICAL (default MEDIUM)
        affected_routes: [route_code, ...] (optional)
        affected_buses: [bus_id, ...] (optional)
    """
    from emergency_engine import emergency_engine
    data = request.get_json(silent=True) or {}

    incident_type = data.get("incident_type", "OTHER")
    lat = data.get("lat")
    lon = data.get("lon")
    severity = data.get("severity", "MEDIUM")
    affected_routes = data.get("affected_routes", [])
    affected_buses = data.get("affected_buses", [])

    if lat is None or lon is None:
        return jsonify({"error": "lat and lon are required"}), 400

    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return jsonify({"error": "lat and lon must be numeric"}), 400

    result = emergency_engine.incident_response(
        incident_type, lat, lon, severity, affected_routes, affected_buses
    )
    result["simulation"] = mode_state.is_simulation
    return jsonify(result)


@api.route("/api/emergency/incident-response/<incident_id>", methods=["POST"])
def emergency_incident_response_by_id(incident_id):
    """Generate emergency response for an existing incident by ID."""
    from emergency_engine import emergency_engine
    from incident_intelligence import get_incident

    incident = get_incident(incident_id)
    if not incident:
        return jsonify({"error": f"Incident {incident_id} not found"}), 404

    location = incident.get("location", {})
    lat = location.get("lat") or location.get("latitude")
    lon = location.get("lon") or location.get("longitude")
    if lat is None or lon is None:
        return jsonify({"error": "Incident has no valid coordinates"}), 400

    # Find affected routes/buses from incident context
    buses = store.get_buses()
    transport_info = emergency_engine.find_affected_routes(
        float(lat), float(lon), buses, radius_km=3.0
    )

    result = emergency_engine.incident_response(
        incident.get("category", "OTHER"),
        float(lat), float(lon),
        incident.get("severity", "MEDIUM"),
        transport_info.get("affected_routes", []),
        [b["bus_id"] for b in transport_info.get("affected_buses", [])[:10]],
    )
    result["incident_id"] = incident_id
    result["incident_title"] = incident.get("title", "")
    result["transport_impact"] = transport_info
    result["simulation"] = mode_state.is_simulation
    return jsonify(result)


@api.route("/api/emergency/transport-impact")
def emergency_transport_impact():
    """Find MTC routes and buses near a GPS location.

    Query params:
        lat, lon: location
        radius: search radius in km (default 3)
    """
    from emergency_engine import emergency_engine
    try:
        lat = float(request.args.get("lat", 0))
        lon = float(request.args.get("lon", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "lat and lon are required numeric parameters"}), 400

    if lat == 0 and lon == 0:
        return jsonify({"error": "lat and lon are required"}), 400

    radius = float(request.args.get("radius", 3.0))
    buses = store.get_buses()
    result = emergency_engine.find_affected_routes(lat, lon, buses, radius)
    return jsonify(result)


@api.route("/api/emergency/search")
def emergency_search():
    """Search emergency facilities by name, type, address, or jurisdiction.

    Query params:
        q: search query (required)
    """
    from emergency_data import emergency_store
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"hospitals": [], "fire_stations": [], "police_stations": [], "traffic_police": []})
    return jsonify(emergency_store.search(query))


@api.route("/api/emergency/contacts")
def emergency_contacts():
    """List all emergency contact numbers."""
    from emergency_data import emergency_store
    return jsonify({"contacts": emergency_store.get_contacts()})


# ---------------------------------------------------------------------------
# AI Insights (New)
# ---------------------------------------------------------------------------

@api.route("/api/ai/insights")
def ai_insights():
    """Get AI-generated insights from system data.

    Aggregates data from fleet, safety, road, incident, and emergency
    systems to produce human-readable intelligence summaries.
    """
    from ai_insights_generator import ai_insights_generator
    from fleet_summary import build_fleet_summary
    from risk_engine import fleet_risk

    buses = store.get_buses()
    events = store.get_events(limit=50)
    risk_items = fleet_risk(buses)
    mode = {
        "mode": mode_state.mode,
        "simulation": mode_state.is_simulation,
        "connected_nodes": list(mode_state.get_connected_live_nodes().keys()),
    }

    fleet = build_fleet_summary(buses, events, risk_items, mode)
    incidents = events

    # Get driver safety summary
    driver_safety = {
        "drowsy_count": sum(1 for b in store.get_buses()
                           if b.get("driver", {}).get("state") in ("DROWSY", "EYES_CLOSED")),
        "fatigued_count": sum(1 for b in store.get_buses()
                             if b.get("driver", {}).get("fatigue_stage") in ("FATIGUE", "CRITICAL")),
        "alert_count": sum(1 for b in store.get_buses()
                          if b.get("driver", {}).get("state") == "ALERT"),
    }

    # Get road summary
    from road_risk import get_road_summary
    road = get_road_summary()

    insights = ai_insights_generator.generate_all_insights(
        fleet_summary=fleet,
        driver_safety=driver_safety,
        road_summary=road,
        incidents=incidents,
    )

    return jsonify(insights)


# ---------------------------------------------------------------------------
# Data Source Management (New)
# ---------------------------------------------------------------------------

@api.route("/api/data-sources")
def data_sources_status():
    """Get status of all data sources."""
    from data_source_manager import data_source_manager
    return jsonify(data_source_manager.get_status_summary())


@api.route("/api/data-sources/switch", methods=["POST"])
def switch_data_source():
    """Switch between simulation and live modes."""
    from data_source_manager import data_source_manager
    body = request.get_json(force=True, silent=True) or {}
    mode = body.get("mode", "")
    success, message = data_source_manager.switch_mode(mode)
    if success:
        return jsonify({"success": True, "message": message})
    return jsonify({"success": False, "error": message}), 400


# ---------------------------------------------------------------------------
# Traffic Patterns (New)
# ---------------------------------------------------------------------------

@api.route("/api/traffic/pattern")
def traffic_pattern():
    """Get current traffic pattern based on time of day.

    Query params:
        hour: hour of day (0-23), defaults to current UTC hour
        area: area type (cbd, commercial, residential, highway, suburban)
    """
    from traffic_pattern import traffic_pattern_engine

    hour = request.args.get("hour", type=int)
    area = request.args.get("area", "residential")

    conditions = traffic_pattern_engine.get_traffic_conditions(hour=hour, area_type=area)
    return jsonify(conditions)


@api.route("/api/traffic/route-congestion/<route_code>")
def route_congestion(route_code):
    """Get congestion summary for an entire route."""
    from traffic_pattern import traffic_pattern_engine
    from simulator import _ensure_gtfs_loaded, ROUTES

    _ensure_gtfs_loaded()

    # Find the route
    route = None
    if ROUTES:
        for r in ROUTES:
            if r.get("code") == route_code:
                route = r
                break

    if not route:
        return jsonify({"error": f"Route {route_code} not found"}), 404

    stops = route.get("stops", [])
    summary = traffic_pattern_engine.get_route_congestion(route_code, stops)
    return jsonify(summary)


# ---------------------------------------------------------------------------
# Incident Accumulation (New)
# ---------------------------------------------------------------------------

@api.route("/api/incidents/summary")
def incident_accumulation_summary():
    """Get accumulated incident statistics."""
    from incident_accumulator import incident_accumulator

    # Add current events to accumulator
    events = store.get_events(limit=200)
    for event in events:
        if event.get("severity") in ("CRITICAL", "HIGH", "WARNING"):
            incident_accumulator.add_incident(event)

    return jsonify(incident_accumulator.get_incident_summary())


@api.route("/api/incidents/hotspots")
def incident_hotspots():
    """Get incident hotspot areas."""
    from incident_accumulator import incident_accumulator

    events = store.get_events(limit=200)
    for event in events:
        incident_accumulator.add_incident(event)

    hotspots = incident_accumulator.get_hotspot_areas()
    return jsonify({"hotspots": hotspots})


# ---------------------------------------------------------------------------
# Enhanced Emergency Response (New)
# ---------------------------------------------------------------------------

@api.route("/api/emergency/severity-response")
def emergency_severity_response():
    """Get severity-based emergency response recommendations.

    Query params:
        lat, lon: incident location
        severity: incident severity (CRITICAL, HIGH, MEDIUM, LOW)
        type: incident type (ACCIDENT, FIRE, MEDICAL_EMERGENCY, etc.)
    """
    from emergency_engine import emergency_engine

    try:
        lat = float(request.args.get("lat", 0))
        lon = float(request.args.get("lon", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "lat and lon are required numeric parameters"}), 400

    severity = request.args.get("severity", "MEDIUM")
    incident_type = request.args.get("type", "ACCIDENT")

    result = emergency_engine.incident_response(
        incident_type, lat, lon, severity, [], []
    )

    return jsonify(result)


@api.route("/api/emergency/response-estimate")
def emergency_response_estimate():
    """Estimate response time for emergency at a location.

    Query params:
        lat, lon: incident location
        facility_type: type of facility (hospital, fire, police)
    """
    from emergency_engine import emergency_engine

    try:
        lat = float(request.args.get("lat", 0))
        lon = float(request.args.get("lon", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "lat and lon are required numeric parameters"}), 400

    facility_type = request.args.get("facility_type")

    nearby = emergency_engine.nearby_facilities(
        lat, lon, facility_type=facility_type, max_results=3
    )

    # Estimate response times
    estimates = []
    for fac in nearby.get("facilities", []):
        dist_km = fac.get("distance_km", 0)
        # Rough estimate: 2 min/km in city traffic
        est_minutes = max(3, round(dist_km * 2))
        estimates.append({
            "facility_id": fac.get("facility_id"),
            "name": fac.get("name"),
            "type": fac.get("type"),
            "distance_km": dist_km,
            "estimated_response_minutes": est_minutes,
            "phone": fac.get("phone"),
        })

    return jsonify({
        "location": {"lat": lat, "lon": lon},
        "estimates": estimates,
        "note": "Response times are estimates based on distance. Actual times may vary.",
    })


# ---------------------------------------------------------------------------
# Risk Prediction (New)
# ---------------------------------------------------------------------------

@api.route("/api/risk/predict/<bus_id>")
def risk_predict_bus(bus_id):
    """Predict risk for a specific bus.

    Query params:
        minutes: minutes ahead to predict (default 30)
    """
    from risk_predictor import risk_predictor

    minutes = request.args.get("minutes", 30, type=int)
    prediction = risk_predictor.predict_risk(bus_id, minutes)
    return jsonify(prediction)


@api.route("/api/risk/predict/fleet")
def risk_predict_fleet():
    """Predict risk for the entire fleet."""
    from risk_predictor import risk_predictor

    minutes = request.args.get("minutes", 30, type=int)
    predictions = risk_predictor.predict_fleet_risk(minutes)
    return jsonify(predictions)


# =========================================================================
# V2 INTELLIGENCE ENDPOINTS
# =========================================================================

# ---------------------------------------------------------------------------
# V2: Predictive Incident Intelligence
# ---------------------------------------------------------------------------

@api.route("/api/v2/incident-prediction/bus/<bus_id>")
def v2_incident_prediction_bus(bus_id):
    """Predict incident probability for a single bus.

    Returns multi-signal incident probability with factor chain,
    early warnings, and preventive recommendations.
    """
    from predictive_incident_engine import predictive_incident_engine

    bus = store.get_bus(bus_id)
    if not bus:
        return jsonify({"error": f"Bus {bus_id} not found"}), 404

    events = store.get_events(limit=200)

    # Get road risk data if available
    road_risk_data = {}
    try:
        from road_risk import get_road_risk_data
        road_risk_data = get_road_risk_data()
    except Exception:
        pass

    prediction = predictive_incident_engine.evaluate_bus(
        bus, events, road_risk_data
    )
    return jsonify(prediction)


@api.route("/api/v2/incident-prediction/fleet")
def v2_incident_prediction_fleet():
    """Predict incident probability for the entire fleet."""
    from predictive_incident_engine import predictive_incident_engine

    buses = store.get_buses()
    events = store.get_events(limit=200)

    road_risk_data = {}
    try:
        from road_risk import get_road_risk_data
        road_risk_data = get_road_risk_data()
    except Exception:
        pass

    result = predictive_incident_engine.evaluate_fleet(
        buses, events, road_risk_data
    )
    return jsonify(result)


# ---------------------------------------------------------------------------
# V2: Fleet Decision Intelligence
# ---------------------------------------------------------------------------

@api.route("/api/v2/fleet/decisions")
def v2_fleet_decisions():
    """Get fleet-level decision recommendations.

    Returns rebalancing, deployment, route adjustment, and
    spacing recommendations. Feeds the engine live demand, ETA and
    road payloads (in the exact shapes it consumes) plus per-bus risk
    enrichment, so the deployment / delay-mitigation / congestion /
    risk-intervention branches actually fire instead of seeing {}.
    """
    from fleet_decision_engine import fleet_decision_engine

    buses = store.get_buses()
    events = store.get_events(limit=100)

    risk_data = {}
    bus_risk_map = {}
    try:
        from risk_engine import fleet_risk
        risk_items = fleet_risk(buses)
        risk_data = {"risk_items": risk_items}
        bus_risk_map = {r.get("bus_id"): r for r in risk_items}
    except Exception:
        pass

    # Enrich COPIES (never mutate the store) so _analyze_risk_intervention,
    # which reads bus["risk"]{score,level}, sees live scores.
    enriched = []
    for b in buses:
        r = bus_risk_map.get(b.get("bus_id"), {})
        if r:
            b = {**b, "risk": {"score": r.get("risk_score", 0),
                               "level": r.get("risk_level", "LOW")}}
        enriched.append(b)

    # Demand payload: predicted vs current capacity per route, from the
    # live route summary plus short-horizon boarding forecasts.
    demand_data = {}
    try:
        from demand_intelligence import get_route_demand_summary
        from demand import forecast_all
        route_demand = get_route_demand_summary(enriched) or {}
        forecast_boardings = {}
        try:
            for bus_id, stops in forecast_all(enriched, random.Random(42)).items():
                forecast_boardings[bus_id] = sum(
                    (s.get("forecast_boardings", 0) or 0) for s in (stops or []))
        except Exception:
            pass
        shaped = {}
        for route_code, info in route_demand.items():
            predicted = info.get("total_passengers", 0) + sum(
                forecast_boardings.get(b.get("bus_id"), 0) for b in enriched
                if b.get("route_code") == route_code)
            shaped[route_code] = {
                "predicted_demand": predicted,
                "current_capacity": info.get("total_capacity", 0),
            }
        demand_data = {"route_demand": shaped}
    except Exception:
        pass

    # ETA payload: delayed share per route, from live ETA computation.
    eta_data = {}
    try:
        from eta import compute_all_etas
        bus_route = {b.get("bus_id"): b.get("route_code", "UNKNOWN")
                     for b in enriched}
        route_states = {}
        try:
            for bus_id, eta in compute_all_etas(enriched, random.Random(42)).items():
                route_states.setdefault(
                    bus_route.get(bus_id, "UNKNOWN"), []).append(
                        eta.get("delay_summary", "UNKNOWN"))
        except Exception:
            pass
        route_summary = {}
        for route_code, states in route_states.items():
            delayed = sum(1 for s in states
                          if s in ("SIGNIFICANT_DELAY", "SEVERE_DELAY"))
            route_summary[route_code] = {
                "delayed_percentage": round(100 * delayed / max(1, len(states)), 1),
            }
        eta_data = {"route_summary": route_summary}
    except Exception:
        pass

    # Road payload: live zones adapted to the engine's key vocabulary
    # (affected_routes / detection_count).
    road_data = {}
    try:
        from road_risk import get_zones
        zones = []
        for z in get_zones() or []:
            zones.append({
                "zone_id": z.get("zone_id", ""),
                "risk_level": z.get("risk_level", "LOW"),
                "affected_routes": z.get("affected_routes",
                                         z.get("routes_affected", [])),
                "detection_count": z.get("detection_count",
                                         z.get("total_detections", 0)),
            })
        road_data = {"zones": zones}
    except Exception:
        pass

    result = fleet_decision_engine.analyze_fleet(
        enriched, events, risk_data,
        demand_data=demand_data, eta_data=eta_data, road_data=road_data,
    )
    return jsonify(result)


# ---------------------------------------------------------------------------
# V2: Decision Intelligence (per-event)
# ---------------------------------------------------------------------------

@api.route("/api/v2/decision/<event_id>")
def v2_decision_for_event(event_id):
    """Get full decision intelligence for a specific event.

    Returns EVENT → CONTEXT → RISK → PREDICTION → RECOMMENDATION → RESPONSE.
    """
    from decision_intelligence import decision_intelligence

    events = store.get_events(limit=500)
    event = next((e for e in events if e.get("event_id") == event_id), None)

    if not event:
        return jsonify({"error": f"Event {event_id} not found"}), 404

    bus_id = event.get("bus_id", "")
    bus = store.get_bus(bus_id) or {}

    # Get risk data
    risk_data = {}
    try:
        from risk_engine import bus_risk
        risk_data = bus_risk(bus, events)
    except Exception:
        pass

    # Get incident prediction
    incident_prediction = {}
    try:
        from predictive_incident_engine import predictive_incident_engine
        incident_prediction = predictive_incident_engine.evaluate_bus(bus, events)
    except Exception:
        pass

    result = decision_intelligence.analyze_event(
        event, bus, risk_data=risk_data,
        incident_prediction=incident_prediction
    )
    return jsonify(result)


@api.route("/api/v2/decision/bus/<bus_id>")
def v2_decision_for_bus(bus_id):
    """Get decision intelligence summary for a bus."""
    from decision_intelligence import decision_intelligence

    bus = store.get_bus(bus_id)
    if not bus:
        return jsonify({"error": f"Bus {bus_id} not found"}), 404

    events = store.get_events(limit=200)

    risk_data = {}
    try:
        from risk_engine import bus_risk
        risk_data = bus_risk(bus, events)
    except Exception:
        pass

    incident_prediction = {}
    try:
        from predictive_incident_engine import predictive_incident_engine
        incident_prediction = predictive_incident_engine.evaluate_bus(bus, events)
    except Exception:
        pass

    result = decision_intelligence.analyze_bus(
        bus, events, risk_data=risk_data,
        incident_prediction=incident_prediction
    )
    return jsonify(result)


# ---------------------------------------------------------------------------
# V2: Road Corridor Intelligence
# ---------------------------------------------------------------------------

@api.route("/api/v2/roads/corridors")
def v2_road_corridors():
    """Get dynamic road risk corridor intelligence."""
    from road_corridor_intelligence import road_corridor_intelligence

    defects = store.get_road_defects()
    events = store.get_events(limit=100)
    buses = store.get_buses()

    risk_zones = []
    route_index = {}
    try:
        from road_risk import get_zones, get_route_risk
        risk_zones = get_zones()
        route_index = get_route_risk()
    except Exception:
        pass

    result = road_corridor_intelligence.compute_corridors(
        defects, events, risk_zones, buses, route_index
    )
    return jsonify(result)


@api.route("/api/v2/roads/corridor/<corridor_id>")
def v2_road_corridor_detail(corridor_id):
    """Get details for a specific road corridor."""
    from road_corridor_intelligence import road_corridor_intelligence

    corridor = road_corridor_intelligence.get_corridor(corridor_id)
    if not corridor:
        return jsonify({"error": f"Corridor {corridor_id} not found"}), 404

    return jsonify(corridor)


# ---------------------------------------------------------------------------
# V2: Explainability
# ---------------------------------------------------------------------------

@api.route("/api/v2/explain/risk/<bus_id>")
def v2_explain_risk(bus_id):
    """Get explainable risk assessment for a bus."""
    from explainability_engine import explainability_engine

    bus = store.get_bus(bus_id)
    if not bus:
        return jsonify({"error": f"Bus {bus_id} not found"}), 404

    events = store.get_events(limit=200)
    risk_data = {}
    try:
        from risk_engine import bus_risk
        risk_data = bus_risk(bus, events)
    except Exception:
        pass

    result = explainability_engine.explain_risk(bus_id, risk_data)
    return jsonify(result)


@api.route("/api/v2/explain/incident-prediction/<bus_id>")
def v2_explain_incident_prediction(bus_id):
    """Get explainable incident prediction for a bus."""
    from explainability_engine import explainability_engine
    from predictive_incident_engine import predictive_incident_engine

    bus = store.get_bus(bus_id)
    if not bus:
        return jsonify({"error": f"Bus {bus_id} not found"}), 404

    events = store.get_events(limit=200)
    prediction = predictive_incident_engine.evaluate_bus(bus, events)

    result = explainability_engine.explain_incident_prediction(bus_id, prediction)
    return jsonify(result)


@api.route("/api/v2/explain/decision/<event_id>")
def v2_explain_decision(event_id):
    """Get explainable decision for a specific event."""
    from explainability_engine import explainability_engine
    from decision_intelligence import decision_intelligence

    events = store.get_events(limit=500)
    event = next((e for e in events if e.get("event_id") == event_id), None)

    if not event:
        return jsonify({"error": f"Event {event_id} not found"}), 404

    bus_id = event.get("bus_id", "")
    bus = store.get_bus(bus_id) or {}

    decision = decision_intelligence.analyze_event(event, bus)
    result = explainability_engine.explain_decision(bus_id, decision)
    return jsonify(result)


# ---------------------------------------------------------------------------
# V2: Incident Timeline & Replay
# ---------------------------------------------------------------------------

@api.route("/api/v2/incident-replay/timeline/<bus_id>")
def v2_incident_timeline(bus_id):
    """Get incident timeline for a bus.

    Query params:
        minutes: time window in minutes (default 60)
    """
    from incident_replay import incident_replay

    minutes = request.args.get("minutes", 60, type=int)
    events = store.get_events(limit=500)
    incidents = []
    try:
        from persistence import db
        incidents = db.get_incidents(bus_id=bus_id, limit=50)
    except Exception:
        pass

    result = incident_replay.build_timeline(
        bus_id, events, incidents=incidents,
        time_window_minutes=minutes
    )
    return jsonify(result)


@api.route("/api/v2/incident-replay/<incident_id>")
def v2_incident_replay(incident_id):
    """Get step-by-step replay of an incident."""
    from incident_replay import incident_replay

    events = store.get_events(limit=500)
    incidents = []
    try:
        from persistence import db
        incidents = db.get_incidents(limit=100)
    except Exception:
        pass

    result = incident_replay.build_incident_replay(
        incident_id, events, incidents
    )
    return jsonify(result)


# ---------------------------------------------------------------------------
# V2: Demand Prediction
# ---------------------------------------------------------------------------

@api.route("/api/v2/demand/predict")
def v2_demand_predict():
    """Predict passenger demand for the fleet.

    Query params:
        minutes: minutes ahead to predict (default 30)
    """
    from demand_predictor import demand_predictor

    minutes = request.args.get("minutes", 30, type=int)
    buses = store.get_buses()

    result = demand_predictor.predict_demand(buses, minutes_ahead=minutes)
    return jsonify(result)


@api.route("/api/v2/demand/overcrowding")
def v2_demand_overcrowding():
    """Predict overcrowding risk per route."""
    from demand_predictor import demand_predictor

    buses = store.get_buses()
    result = demand_predictor.predict_overcrowding(buses)
    return jsonify(result)


# ---------------------------------------------------------------------------
# V2: AI Copilot
# ---------------------------------------------------------------------------

@api.route("/api/v2/copilot/query", methods=["POST"])
def v2_copilot_query():
    """Process a natural language query from the operator.

    POST body:
        question: natural language question
        context: optional context dict
    """
    from ai_copilot import ai_copilot

    data = request.get_json(force=True, silent=True) or {}
    question = data.get("question", "")
    context = data.get("context", {})

    if not question:
        return jsonify({"error": "question is required"}), 400

    result = ai_copilot.query(question, context)
    return jsonify(result)


@api.route("/api/v2/copilot/suggestions")
def v2_copilot_suggestions():
    """Get suggested queries for the copilot."""
    from ai_copilot import ai_copilot

    return jsonify({
        "suggestions": ai_copilot._get_suggestions(),
    })


# ---------------------------------------------------------------------------
# Phase B: Multi-Source Fusion Engine
# ---------------------------------------------------------------------------

@api.route("/api/fusion/events")
def fusion_events():
    """Get recent fused events from the multi-source fusion engine."""
    from fusion_engine import fusion_engine

    limit = request.args.get("limit", 50, type=int)
    bus_id = request.args.get("bus_id")
    severity = request.args.get("severity")

    events = fusion_engine.get_fused_events(limit=limit, bus_id=bus_id, severity=severity)
    return jsonify({"events": events, "count": len(events)})


@api.route("/api/fusion/stats")
def fusion_stats():
    """Get fusion engine statistics."""
    from fusion_engine import fusion_engine

    return jsonify(fusion_engine.get_stats())


@api.route("/api/fusion/evaluate", methods=["POST"])
def fusion_evaluate():
    """Manually trigger fusion evaluation for a bus."""
    from fusion_engine import fusion_engine

    data = request.get_json(force=True, silent=True) or {}
    bus_id = data.get("bus_id")

    if not bus_id:
        return jsonify({"error": "bus_id is required"}), 400

    buses = store.get_buses()
    bus = next((b for b in buses if b.get("bus_id") == bus_id), None)
    if not bus:
        return jsonify({"error": f"Bus {bus_id} not found"}), 404

    events = store.get_events()
    traffic_data = data.get("traffic_data")
    road_risk_data = data.get("road_risk_data")

    fused = fusion_engine.evaluate_bus(bus, events=events,
                                       traffic_data=traffic_data,
                                       road_risk_data=road_risk_data)
    return jsonify({
        "bus_id": bus_id,
        "fused_events": [f.to_dict() for f in fused],
        "count": len(fused),
    })


# ---------------------------------------------------------------------------
# Phase D: Route-Level Intelligence
# ---------------------------------------------------------------------------

@api.route("/api/routes/intelligence")
def routes_intelligence():
    """Get intelligence for all routes."""
    from route_intelligence import route_intelligence_engine

    buses = store.get_buses()
    events = store.get_events()
    defects = store.get_road_defects()

    # Get incidents
    try:
        from incident_intelligence import incident_store
        incidents = [inc.to_dict() for inc in incident_store.get_incidents(limit=500)]
    except Exception:
        incidents = []

    # Get ETA summary
    try:
        from eta import eta_engine
        eta_summary = eta_engine.get_fleet_eta_summary()
    except Exception:
        eta_summary = None

    # Get risk zones
    try:
        from road_risk import get_zones, get_route_risk
        risk_zones = get_zones()
        route_index = get_route_risk()
    except Exception:
        risk_zones = None
        route_index = None

    result = route_intelligence_engine.compute_route_intelligence(
        buses=buses,
        events=events,
        incidents=incidents,
        eta_summary=eta_summary,
        road_defects=defects,
        risk_zones=risk_zones,
        route_index=route_index,
    )

    return jsonify({
        "routes": result,
        "count": len(result),
    })


@api.route("/api/routes/intelligence/<route_code>")
def route_intelligence_detail(route_code):
    """Get intelligence for a specific route."""
    from route_intelligence import route_intelligence_engine

    buses = store.get_buses()
    events = store.get_events()
    defects = store.get_road_defects()

    # Filter to this route
    route_buses = [b for b in buses if b.get("route_code") == route_code]
    if not route_buses:
        return jsonify({"error": f"Route {route_code} not found"}), 404

    try:
        from incident_intelligence import incident_store
        all_incidents = [inc.to_dict() for inc in incident_store.get_incidents(limit=5000)]
        route_incidents = [i for i in all_incidents if i.get("route") and route_code in i["route"]]
    except Exception:
        route_incidents = []

    try:
        from eta import eta_engine
        eta_summary = eta_engine.get_fleet_eta_summary()
    except Exception:
        eta_summary = None

    try:
        from road_risk import get_route_risk
        route_index = get_route_risk()
    except Exception:
        route_index = None

    result = route_intelligence_engine._compute_single_route(
        route_code=route_code,
        buses=route_buses,
        events=[e for e in events if e.get("route_code") == route_code],
        incidents=route_incidents,
        all_buses=buses,
        all_events=events,
        road_defects=defects,
        risk_zones=None,
        traffic_data=None,
        route_index=route_index,
    )

    return jsonify(result)


@api.route("/api/routes/city-overview")
def city_overview():
    """Get city-level intelligence summary."""
    from route_intelligence import route_intelligence_engine

    buses = store.get_buses()
    events = store.get_events()
    defects = store.get_road_defects()

    try:
        from incident_intelligence import incident_store
        incidents = [inc.to_dict() for inc in incident_store.get_incidents(limit=500)]
    except Exception:
        incidents = []

    try:
        from eta import eta_engine
        eta_summary = eta_engine.get_fleet_eta_summary()
    except Exception:
        eta_summary = None

    try:
        from road_risk import get_route_risk
        route_index = get_route_risk()
    except Exception:
        route_index = None

    route_intel = route_intelligence_engine.compute_route_intelligence(
        buses=buses,
        events=events,
        incidents=incidents,
        eta_summary=eta_summary,
        road_defects=defects,
        route_index=route_index,
    )

    overview = route_intelligence_engine.get_city_overview(route_intel)
    return jsonify(overview)


@api.route("/api/routes/recommendations")
def route_recommendations():
    """Get operational recommendations for all routes."""
    from route_intelligence import route_intelligence_engine

    buses = store.get_buses()
    events = store.get_events()
    defects = store.get_road_defects()

    try:
        from incident_intelligence import incident_store
        incidents = [inc.to_dict() for inc in incident_store.get_incidents(limit=500)]
    except Exception:
        incidents = []

    try:
        from eta import eta_engine
        eta_summary = eta_engine.get_fleet_eta_summary()
    except Exception:
        eta_summary = None

    try:
        from road_risk import get_route_risk
        route_index = get_route_risk()
    except Exception:
        route_index = None

    route_intel = route_intelligence_engine.compute_route_intelligence(
        buses=buses,
        events=events,
        incidents=incidents,
        eta_summary=eta_summary,
        road_defects=defects,
        route_index=route_index,
    )

    # Collect all recommendations
    all_recs = []
    for route_code, intel in route_intel.items():
        for rec in intel.get("recommendations", []):
            all_recs.append({
                "route_code": route_code,
                "route_name": intel.get("route_name"),
                **rec,
            })

    # Sort by priority
    priority_order = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    all_recs.sort(key=lambda x: priority_order.get(x.get("priority", "LOW"), 3))

    return jsonify({"recommendations": all_recs[:20], "count": len(all_recs)})


# ---------------------------------------------------------------------------
# Phase E: Historical Intelligence
# ---------------------------------------------------------------------------

def _historical_sim_topup(window, events=None, buses=None, defects=None):
    """Sim-only top-up rows so no historical leg renders empty.

    Live in-memory events all carry today's timestamp, which can never
    satisfy the multi-day recurring-hotspot rule. When an analysis leg
    comes back empty, the caller merges these deterministic simulated
    rows (live rows are preserved first) and re-runs the analysis.
    Returns (sim_events, sim_incidents, sim_risk, sim_eta).
    """
    from historical_intelligence import historical_intelligence_engine
    buses = buses if buses is not None else store.get_buses()
    if not buses:
        return [], [], [], []
    synth = historical_intelligence_engine.synthesize_inputs(
        buses=buses, events=[], road_defects=defects or store.get_road_defects(),
        window=window)
    sim_events = [e for e in synth["events"] if e.get("simulation")]
    return sim_events, synth["incidents"], synth["risk_events"], synth["eta_snapshots"]


@api.route("/api/historical/hotspots")
def historical_hotspots():
    """Get recurring hotspot analysis."""
    from historical_intelligence import historical_intelligence_engine

    window = request.args.get("window", "7d")
    events = store.get_events()

    try:
        from incident_intelligence import incident_store
        incidents = [inc.to_dict() for inc in incident_store.get_incidents(limit=5000)]
    except Exception:
        incidents = []

    defects = store.get_road_defects()
    simulated = False

    # Simulation fallback: in-memory events only cover the current session,
    # so below ~20 rows there is no multi-day structure for hotspot
    # analysis. Top up with deterministic pseudo-history synthesized from
    # the live fleet snapshot (live rows are preserved first).
    if len(events) + len(incidents) < 20:
        synth = historical_intelligence_engine.synthesize_inputs(
            buses=store.get_buses(), events=events, road_defects=defects, window=window)
        events, incidents, simulated = synth["events"], synth["incidents"], True

    result = historical_intelligence_engine.analyze_recurring_hotspots(
        events=events,
        incidents=incidents,
        road_defects=defects,
        window=window,
    )
    if result.get("recurring_count", 0) == 0:
        # Same-day live events can never form multi-day hotspots — top up
        # with simulated anchor repeats and re-run so the page is not empty.
        sim_events, sim_incidents, _, _ = _historical_sim_topup(
            window, buses=store.get_buses(), defects=defects)
        if sim_events:
            result = historical_intelligence_engine.analyze_recurring_hotspots(
                events=events + sim_events,
                incidents=incidents + sim_incidents,
                road_defects=defects,
                window=window,
            )
            simulated = True
    result["simulation"] = simulated or mode_state.is_simulation

    return jsonify(result)


@api.route("/api/historical/patterns")
def historical_patterns():
    """Get time-of-day and day-of-week patterns."""
    from historical_intelligence import historical_intelligence_engine

    window = request.args.get("window", "7d")
    events = store.get_events()

    try:
        from incident_intelligence import incident_store
        incidents = [inc.to_dict() for inc in incident_store.get_incidents(limit=5000)]
    except Exception:
        incidents = []

    simulated = False
    if len(events) + len(incidents) < 20:
        synth = historical_intelligence_engine.synthesize_inputs(
            buses=store.get_buses(), events=events, road_defects=store.get_road_defects(), window=window)
        events, incidents, simulated = synth["events"], synth["incidents"], True

    result = historical_intelligence_engine.analyze_peak_periods(
        events=events,
        incidents=incidents,
        window=window,
    )
    result["simulation"] = simulated or mode_state.is_simulation

    return jsonify(result)


@api.route("/api/historical/routes")
def historical_routes():
    """Get route delay patterns."""
    from historical_intelligence import historical_intelligence_engine

    window = request.args.get("window", "7d")

    try:
        import persistence
        eta_snapshots = persistence.load_eta_snapshots(limit=5000)
    except Exception:
        eta_snapshots = []

    simulated = False
    if not eta_snapshots:
        synth = historical_intelligence_engine.synthesize_inputs(
            buses=store.get_buses(), events=store.get_events(),
            road_defects=store.get_road_defects(), window=window)
        eta_snapshots, simulated = synth["eta_snapshots"], True

    result = historical_intelligence_engine.analyze_route_delay_patterns(
        eta_snapshots=eta_snapshots,
        window=window,
    )
    result["simulation"] = simulated or mode_state.is_simulation

    return jsonify(result)


@api.route("/api/historical/vehicles")
def historical_vehicles():
    """Get vehicle health trends."""
    from historical_intelligence import historical_intelligence_engine

    window = request.args.get("window", "30d")

    try:
        import persistence
        risk_events = persistence.load_risk_events(limit=5000)
    except Exception:
        risk_events = []

    simulated = False
    if not risk_events:
        synth = historical_intelligence_engine.synthesize_inputs(
            buses=store.get_buses(), events=store.get_events(),
            road_defects=store.get_road_defects(), window=window)
        risk_events, simulated = synth["risk_events"], True

    result = historical_intelligence_engine.analyze_vehicle_health_trends(
        risk_events=risk_events,
        window=window,
    )
    result["simulation"] = simulated or mode_state.is_simulation

    return jsonify(result)


@api.route("/api/historical/comprehensive")
def historical_comprehensive():
    """Get comprehensive historical analysis."""
    from historical_intelligence import historical_intelligence_engine

    window = request.args.get("window", "7d")
    events = store.get_events()

    try:
        from incident_intelligence import incident_store
        incidents = [inc.to_dict() for inc in incident_store.get_incidents(limit=5000)]
    except Exception:
        incidents = []

    defects = store.get_road_defects()

    try:
        import persistence
        risk_events = persistence.load_risk_events(limit=5000)
        eta_snapshots = persistence.load_eta_snapshots(limit=5000)
    except Exception:
        risk_events = []
        eta_snapshots = []

    simulated = False
    if not events and not incidents and not risk_events and not eta_snapshots:
        synth = historical_intelligence_engine.synthesize_inputs(
            buses=store.get_buses(), events=events, road_defects=defects, window=window)
        events = synth["events"]
        incidents = synth["incidents"]
        risk_events = synth["risk_events"]
        eta_snapshots = synth["eta_snapshots"]
        simulated = True
    else:
        # Per-leg top-up: ETA snapshots and risk history are never
        # persisted, so those legs are synthesized from the fleet snapshot
        # even when the event legs have live rows.
        buses = store.get_buses()
        if not eta_snapshots and buses:
            synth = historical_intelligence_engine.synthesize_inputs(
                buses=buses, events=[], road_defects=defects, window=window)
            eta_snapshots, simulated = synth["eta_snapshots"], True
        if not risk_events and buses:
            synth = historical_intelligence_engine.synthesize_inputs(
                buses=buses, events=[], road_defects=defects, window=window)
            risk_events, simulated = synth["risk_events"], True
        if len(events) + len(incidents) < 20 and buses:
            synth = historical_intelligence_engine.synthesize_inputs(
                buses=buses, events=events, road_defects=defects, window=window)
            events, incidents, simulated = synth["events"], synth["incidents"], True

    result = historical_intelligence_engine.get_comprehensive_history(
        events=events,
        incidents=incidents,
        road_defects=defects,
        risk_events=risk_events,
        eta_snapshots=eta_snapshots,
        window=window,
    )
    if not result.get("recurring_hotspots", {}).get("recurring_hotspots"):
        # Same-day live events can never form multi-day hotspots — top up
        # with simulated anchor repeats and re-run so the page is not empty.
        sim_events, sim_incidents, _, _ = _historical_sim_topup(
            window, buses=store.get_buses(), defects=defects)
        if sim_events:
            result["recurring_hotspots"] = (
                historical_intelligence_engine.analyze_recurring_hotspots(
                    events=events + sim_events,
                    incidents=incidents + sim_incidents,
                    road_defects=defects,
                    window=window,
                ))
            simulated = True
    if not result.get("route_delay_patterns", {}).get("patterns"):
        _, _, _, sim_eta = _historical_sim_topup(window, defects=defects)
        if sim_eta:
            result["route_delay_patterns"] = (
                historical_intelligence_engine.analyze_route_delay_patterns(
                    eta_snapshots=(eta_snapshots or []) + sim_eta,
                    window=window,
                ))
            simulated = True
    if not result.get("vehicle_health_trends", {}).get("bus_trends"):
        _, _, sim_risk, _ = _historical_sim_topup(window, defects=defects)
        if sim_risk:
            result["vehicle_health_trends"] = (
                historical_intelligence_engine.analyze_vehicle_health_trends(
                    risk_events=(risk_events or []) + sim_risk,
                    window="30d",
                ))
            simulated = True
    result["simulation"] = simulated or mode_state.is_simulation

    return jsonify(result)


# ---------------------------------------------------------------------------
# Phase F: AI Explainability for Events
# ---------------------------------------------------------------------------

@api.route("/api/v2/explain/event/<event_id>")
def v2_explain_event(event_id):
    """Get explainability output for a specific event."""
    from explainability_engine import explainability_engine

    events = store.get_events()
    event = next((e for e in events if e.get("event_id") == event_id), None)
    if not event:
        return jsonify({"error": f"Event {event_id} not found"}), 404

    bus_id = event.get("bus_id")
    bus = None
    if bus_id:
        buses = store.get_buses()
        bus = next((b for b in buses if b.get("bus_id") == bus_id), None)

    # Check for fusion data
    fusion_data = None
    try:
        from fusion_engine import fusion_engine
        fused_events = fusion_engine.get_fused_events(bus_id=bus_id, limit=10)
        for fe in fused_events:
            if any(e.get("event_id") == event_id for e in fe.get("sources", [])):
                fusion_data = fe
                break
    except Exception:
        pass

    result = explainability_engine.explain_event(event, bus=bus, fusion_data=fusion_data)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Phase C: Extended Incident Lifecycle Endpoints
# ---------------------------------------------------------------------------

@api.route("/api/incidents/<incident_id>/confirm", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def incident_confirm(incident_id):
    """Confirm an incident (DETECTED -> CONFIRMED). Operator from JSON body (X-Operator header fallback)."""
    from incident_intelligence import incident_store

    body = request.get_json(silent=True) or {}
    operator = body.get("operator") or request.headers.get("X-Operator", "system")
    incident = incident_store.confirm_incident(incident_id, operator)
    if not incident:
        return jsonify({"error": "incident not found or invalid status for confirm"}), 404
    return jsonify({"incident": incident.to_dict()})


@api.route("/api/incidents/<incident_id>/assign", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def incident_assign(incident_id):
    """Assign an incident to an operator (CONFIRMED/OPEN/DETECTED -> ASSIGNED). Operator from JSON body (X-Operator header fallback)."""
    from incident_intelligence import incident_store

    body = request.get_json(silent=True) or {}
    assignee = (body.get("assignee") or "").strip()
    if not assignee:
        return jsonify({"error": "assignee is required"}), 400

    operator = body.get("operator") or request.headers.get("X-Operator", "system")
    incident = incident_store.assign_incident(incident_id, operator, assignee)
    if not incident:
        return jsonify({"error": "incident not found or invalid status for assignment"}), 404
    return jsonify({"incident": incident.to_dict()})


@api.route("/api/incidents/<incident_id>/respond", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def incident_respond(incident_id):
    """Start responding to an incident (ASSIGNED/CONFIRMED/OPEN -> RESPONDING). Operator from JSON body (X-Operator header fallback)."""
    from incident_intelligence import incident_store

    body = request.get_json(silent=True) or {}
    operator = body.get("operator") or request.headers.get("X-Operator", "system")
    incident = incident_store.respond_incident(incident_id, operator)
    if not incident:
        return jsonify({"error": "incident not found or invalid status for response"}), 404
    return jsonify({"incident": incident.to_dict()})


@api.route("/api/incidents/<incident_id>/reject", methods=["POST"])
@_require_auth("operator", "supervisor", "admin")
def incident_reject(incident_id):
    """Decline assigned work (ASSIGNED -> CONFIRMED) and immediately re-route it to the next operator."""
    from incident_intelligence import incident_store, auto_assign_incident

    body = request.get_json(silent=True) or {}
    operator = body.get("operator") or request.headers.get("X-Operator", "system")
    incident = incident_store.reject_incident(incident_id, operator)
    if not incident:
        return jsonify({"error": "incident not found or not assigned"}), 404
    auto_assign_incident(incident, actor=operator)
    return jsonify({"incident": incident.to_dict()})


@api.route("/api/incidents/assigned")
def get_assigned_incidents():
    """Work waiting on an operator (ASSIGNED + RESPONDING) — drives the critical popup."""
    from incident_intelligence import incident_store
    incidents = incident_store.get_assigned_incidents()
    dicts = [i.to_dict() for i in incidents]
    dicts.sort(key=lambda d: (d.get("severity") != "CRITICAL", d.get("created_at") or ""))
    return jsonify({
        "incidents": dicts,
        "count": len(dicts),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    })


@api.route("/api/incidents/sla")
def incident_sla():
    """Get SLA compliance report for incidents."""
    from incident_intelligence import incident_store

    all_incidents = incident_store.get_incidents(limit=1000)

    sla_stats = {
        "total": len(all_incidents),
        "within_sla": 0,
        "exceeded_sla": 0,
        "avg_response_time": 0,
        "avg_resolution_time": 0,
        "by_category": {},
    }

    response_times = []
    resolution_times = []

    for inc in all_incidents:
        cat = inc.category
        if cat not in sla_stats["by_category"]:
            sla_stats["by_category"][cat] = {"total": 0, "within_sla": 0, "exceeded_sla": 0}
        sla_stats["by_category"][cat]["total"] += 1

        if inc.response_time_seconds is not None:
            response_times.append(inc.response_time_seconds)
            # SLA: CRITICAL < 5min, HIGH < 15min, others < 30min
            sla_limit = {"CRITICAL": 300, "HIGH": 900}.get(inc.severity, 1800)
            if inc.response_time_seconds <= sla_limit:
                sla_stats["within_sla"] += 1
                sla_stats["by_category"][cat]["within_sla"] += 1
            else:
                sla_stats["exceeded_sla"] += 1
                sla_stats["by_category"][cat]["exceeded_sla"] += 1

        if inc.resolution_time_seconds is not None:
            resolution_times.append(inc.resolution_time_seconds)

    if response_times:
        sla_stats["avg_response_time"] = round(sum(response_times) / len(response_times), 1)
    if resolution_times:
        sla_stats["avg_resolution_time"] = round(sum(resolution_times) / len(resolution_times), 1)

    return jsonify(sla_stats)
