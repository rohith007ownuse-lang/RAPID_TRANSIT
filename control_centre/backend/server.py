"""
server.py
Control Centre backend. Flask REST API serving the (simulated) fleet,
events, road defects, and analytics to the React frontend.

Currently all data is SIMULATED (see simulator.py). In a later phase,
real bus_node data will stream into the same store over WebSocket.

Phase 20: Refactored to use centralized configuration, lifecycle management,
and route handlers extracted to routes.py. This file now focuses on
application setup and startup logic.
"""

import atexit
import argparse
import os
import sys
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS

import auth
import persistence
from data_store import store, mode_state
from config import get_config, get_db_path
from lifecycle import get_lifecycle
from simulator import FleetSimulator
from websocket_handler import start_websocket_server, stop_websocket_server

# Create Flask app
app = Flask(__name__)

# CORS: same-origin deployments (nginx serving the SPA and proxying the API)
# get no CORS headers at all. A split deployment is restricted to an explicit
# allowlist, which production requires — see SecurityConfig.startup_blockers.
_SECURITY = get_config().security
_CORS_OPTIONS = _SECURITY.cors_options()
if _SECURITY.same_origin:
    print("[control-centre] CORS: same-origin mode (no cross-origin access allowed)")
elif _CORS_OPTIONS is None:
    CORS(app)
else:
    CORS(app, resources={r"/api/*": _CORS_OPTIONS})
    print(f"[control-centre] CORS restricted to: {', '.join(_CORS_OPTIONS['origins'])}")
app.config["JSON_SORT_KEYS"] = False

# Endpoints that stay reachable without a token even when authenticated reads
# are enforced: the health probe (uptime/load balancers) and the login call
# that mints the first token.
_PUBLIC_API_PATHS = frozenset({"/api/health", "/api/auth/login"})


@app.before_request
def _enforce_api_auth():
    """Authenticated reads: require a bearer token for the whole API surface.

    Only active when FLEETIQ_REQUIRE_AUTH_READS is set, or by default when
    FLEETIQ_ENV=production. CORS preflights are skipped so cross-origin
    requests carrying an Authorization header still negotiate.
    """
    if request.method == "OPTIONS" or not request.path.startswith("/api/"):
        return None
    if request.path in _PUBLIC_API_PATHS:
        return None
    if not get_config().security.effective_require_auth_reads:
        return None
    if auth.require_auth(request) is None:
        return jsonify({"error": "authentication required"}), 401
    return None

# Global safety net: kill ALL audio loops on any Python exit path.
def _server_atexit_kill_audio():
    try:
        from bus_node.utils.alert_manager import _kill_all_stray_loops
        _kill_all_stray_loops()
    except Exception:
        pass

atexit.register(_server_atexit_kill_audio)

# Register the API routes blueprint
from routes import api
app.register_blueprint(api)

# Global simulator reference for mode switching
_simulator_ref = [None]


def _get_simulator():
    return _simulator_ref[0]


def _set_simulator(sim):
    _simulator_ref[0] = sim


def _register_shutdown_hooks():
    """Register the ordered graceful-shutdown hooks on the lifecycle singleton.

    Historical contract (Phase 2): stop new work -> DDS -> capture DDS session
    -> camera -> WebSocket. Each hook is error-tolerant; lifecycle runs them
    exactly once on SIGINT/SIGTERM or lifecycle.stop().
    """
    lifecycle = get_lifecycle()

    def _stop_simulator():
        sim = _get_simulator()
        if sim:
            sim.stop()
            print("[control-centre] Simulator stopped.")

    def _stop_dds():
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

    def _stop_camera():
        try:
            from ai.camera_manager import camera_manager
            camera_manager.stop()
            print("[control-centre] Camera resources released.")
        except Exception as e:
            print(f"[control-centre] Camera stop error: {e}")

    def _stop_websocket():
        try:
            stop_websocket_server()
            time.sleep(0.3)
        except Exception as e:
            print(f"[control-centre] WebSocket stop error: {e}")

    def _stop_audio():
        """Kill ALL audio loops (AlertManager + any stray processes)."""
        try:
            from bus_node.utils.alert_manager import _kill_all_stray_loops, _all_managers, _all_managers_lock
            with _all_managers_lock:
                managers = list(_all_managers)
            for mgr in managers:
                try:
                    mgr.stop()
                except Exception:
                    pass
            _kill_all_stray_loops()
            print("[control-centre] Audio alerts stopped.")
        except Exception as e:
            print(f"[control-centre] Audio stop error: {e}")

    lifecycle.add_cleanup_fn(_stop_simulator)
    lifecycle.add_cleanup_fn(_stop_dds)
    lifecycle.add_cleanup_fn(lifecycle.capture_dds_session)
    lifecycle.add_cleanup_fn(_stop_camera)
    lifecycle.add_cleanup_fn(_stop_websocket)
    lifecycle.add_cleanup_fn(_stop_audio)  # last — kill any remaining sound


# ---------------------------------------------------------------------------
# PROTO-001 stub (for live prototype)
# ---------------------------------------------------------------------------

PROTO_STOPS = [
    {"stop": "Koyambedu", "lat": 13.0697, "lon": 80.2070, "major": True},
    {"stop": "Vadapalani", "lat": 13.0650, "lon": 80.2150, "major": False},
    {"stop": "T.Nagar", "lat": 13.0410, "lon": 80.2340, "major": True},
    {"stop": "Kilambakkam", "lat": 13.0210, "lon": 80.2230, "major": True},
]


def _proto_bus():
    """Stub bus for the FLEET-IQ live prototype node (70V)."""
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


def _road_event_callback(event):
    """Confirmed live potholes land in the event system + road-defect map
    (feeds Road Intelligence zones, alerts, and websocket subscribers)."""
    if event.get("latitude") is None:
        try:
            bus = store.get_bus("PROTO-001") or {}
            event["latitude"] = bus.get("latitude", 13.07)
            event["longitude"] = bus.get("longitude", 80.27)
            event["gps_status"] = "FIX"
        except Exception:
            pass
    stored = store.add_event(event)
    try:
        from websocket_handler import link_road_defect
        link_road_defect(stored if isinstance(stored, dict) else event)
    except Exception as e:
        print(f"[control-centre] Road defect link failed: {e}")
    mode_state.update_live_node("PROTO-001", {
        "gps_available": True,
        "sensors": {"driver_ai": "active", "road_ai": "active", "camera": "road"},
    })


def _cabin_event_callback(event):
    """Confirmed cabin hazards (fire/smoke) land in the event system +
    keep the node alive; severity CRITICAL/HIGH drives operator alerts."""
    if event.get("latitude") is None:
        try:
            bus = store.get_bus("PROTO-001") or {}
            event["latitude"] = bus.get("latitude", 13.07)
            event["longitude"] = bus.get("longitude", 80.27)
            event["gps_status"] = "FIX"
        except Exception:
            pass
    store.add_event(event)
    mode_state.update_live_node("PROTO-001", {
        "gps_available": True,
        "sensors": {"driver_ai": "active", "cabin_ai": "active", "camera": "cabin"},
    })


def _traffic_event_callback(event):
    """Frame-level vehicle counts land in the event system + update bus telemetry."""
    store.add_event(event)
    # Update PROTO-001 bus with latest traffic counts
    try:
        bus = store.get_bus("PROTO-001")
        if bus:
            ad = event.get("additional_data") or {}
            bus["traffic"] = {
                "total_vehicles": ad.get("total_vehicles", 0),
                "unique_vehicles": ad.get("unique_vehicles", 0),
                "class_counts": ad.get("class_counts", {}),
                "total_unique_vehicles": ad.get("total_unique_vehicles", 0),
                "tracking_active": ad.get("tracking_active", False),
                "timestamp": event.get("timestamp"),
                "source": "road_model",
            }
            store.upsert_bus(bus)
    except Exception:
        pass
    mode_state.update_live_node("PROTO-001", {
        "gps_available": True,
        "sensors": {"driver_ai": "active", "road_ai": "active", "traffic_ai": "active", "camera": "road"},
    })


def _pedestrian_event_callback(event):
    """Pedestrian-presence events land in the event system + update bus telemetry."""
    store.add_event(event)
    try:
        bus = store.get_bus("PROTO-001")
        if bus:
            ad = event.get("additional_data") or {}
            bus["pedestrians"] = {
                "this_frame": ad.get("pedestrians_this_frame", 0),
                "near_roadway": ad.get("near_roadway", 0),
                "total_unique": ad.get("total_unique_pedestrians", 0),
                "tracking_active": ad.get("tracking_active", False),
                "timestamp": event.get("timestamp"),
                "source": "road_model",
            }
            store.upsert_bus(bus)
    except Exception:
        pass
    mode_state.update_live_node("PROTO-001", {
        "gps_available": True,
        "sensors": {"driver_ai": "active", "road_ai": "active", "pedestrian_ai": "active", "camera": "road"},
    })


def _passenger_event(bus, event_type, severity, confidence, note, pax, occ, extra=None):
    """Build a passenger-counter event for the LIVE demo bus."""
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


def _make_live_load(passengers):
    """Build a load dict from passenger count."""
    payload_kg = passengers * 68 + __import__('random').randint(100, 800)
    payload_kg = max(0.0, min(float(payload_kg), 6000.0))
    gvw = 11000 + payload_kg
    pct = round(100 * payload_kg / 6000)
    status = "CRITICAL OVERLOAD" if pct > 100 else "HIGH LOAD" if pct > 90 else "NORMAL"
    return {
        "gvw_kg": round(gvw), "tare_kg": 11000, "payload_kg": round(payload_kg),
        "payload_limit_kg": 6000, "load_pct": pct, "status": status,
    }


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

    # Trained pothole model + event flow: confirmed potholes become events and
    # road defects, so they reach Road Intelligence and alert subscribers.
    try:
        from ai.road.pothole_detector import pothole_detector
        pothole_detector.set_event_callback(_road_event_callback)
        pothole_detector.load_model()
    except Exception as e:
        print(f"[control-centre] Pothole engine setup failed: {e}")

    # Trained cabin fire/smoke model + event flow: confirmed hazards become
    # CRITICAL/HIGH events that reach the operator dashboards and alerts.
    try:
        from ai.cabin.cabin_detector import cabin_detector
        cabin_detector.set_event_callback(_cabin_event_callback)
        cabin_detector.load_model()
    except Exception as e:
        print(f"[control-centre] Cabin engine setup failed: {e}")

    # Traffic detector (vehicle counting) — frame-level counts via YOLOv8 COCO
    try:
        from ai.road.traffic_detector import traffic_detector
        traffic_detector.set_event_callback(_traffic_event_callback)
        traffic_detector.load_model()
    except Exception as e:
        print(f"[control-centre] Traffic engine setup failed: {e}")

    # Pedestrian detector (vulnerable road users) — COCO person class on road cam
    try:
        from ai.road.pedestrian_detector import pedestrian_detector
        pedestrian_detector.set_event_callback(_pedestrian_event_callback)
        pedestrian_detector.load_model()
    except Exception as e:
        print(f"[control-centre] Pedestrian engine setup failed: {e}")

    # Heartbeat: keep the prototype node marked connected
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

    # Passenger moments simulation
    def _passenger_moments():
        import random as rng
        from road_event_model import _haversine_km
        time.sleep(5)
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

                tick_count += 1
                j = bus.get("journey", {})
                stops = j.get("stops") or []
                if not stops:
                    time.sleep(3)
                    continue

                total = len(stops)
                j.setdefault("direction", 1)
                j.setdefault("layover_ticks", 0)
                state = j.get("state", "AT_STOP")
                current_idx = j.get("current_index", 0)
                next_idx = j.get("next_index", 1)
                progress = j.get("progress", 0.0)
                direction = j.get("direction", 1)

                def _live_leg_km(jj):
                    a = jj["stops"][jj["current_index"]]
                    b = jj["stops"][min(jj["next_index"], len(jj["stops"]) - 1)]
                    try:
                        return max(0.1, _haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]))
                    except Exception:
                        return 2.0

                if state == "AT_STOP":
                    bus["speed_kmh"] = 0.0
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
                        tkt = bus.get("ticketing") or {}
                        fare_per = 8 + rng.randint(0, 12)
                        tkt["tickets_today"] = tkt.get("tickets_today", 0) + actual
                        tkt["passengers_total"] = tkt.get("passengers_total", 0) + actual
                        tkt["fare_collected"] = round(tkt.get("fare_collected", 0) + actual * fare_per, 2)
                        bus["ticketing"] = tkt
                        bus["daily_boarding_total"] = bus.get("daily_boarding_total", 0) + actual
                        bus["load"] = _make_live_load(occ["passengers"])
                        bus["last_update"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                        store.upsert_bus(bus)

                    if rng.random() < 0.3:
                        at_terminal = current_idx in (0, total - 1)
                        if at_terminal:
                            j["layover_ticks"] = j.get("layover_ticks", 0) + 1
                        if not at_terminal or j["layover_ticks"] >= 6:
                            if at_terminal:
                                j["direction"] = -j["direction"]
                                first = stops[0]["stop"]
                                last = stops[-1]["stop"]
                                if j["direction"] == 1:
                                    j["origin"] = first
                                    j["destination"] = last
                                else:
                                    j["origin"] = last
                                    j["destination"] = first
                                j["start"] = j["origin"]
                                j["destination"] = first if j["direction"] == -1 else last
                                j["next_index"] = current_idx + j["direction"]
                                j["layover_ticks"] = 0
                            j["state"] = "MOVING"
                            j["progress"] = 0.0
                elif state == "MOVING":
                    leg_km = _live_leg_km(j)
                    progress += (10.0 / 60.0) * 3.0 / leg_km
                    bus["speed_kmh"] = round(rng.uniform(22, 42), 1)
                    if progress >= 0.5:
                        j["state"] = "ARRIVING"
                    j["progress"] = progress
                    if current_idx < len(stops) and next_idx < len(stops):
                        a, b = stops[current_idx], stops[next_idx]
                        t = min(1.0, progress)
                        bus["latitude"] = round(a["lat"] + (b["lat"] - a["lat"]) * t, 6)
                        bus["longitude"] = round(a["lon"] + (b["lon"] - a["lon"]) * t, 6)
                    store.upsert_bus(bus)
                elif state == "ARRIVING":
                    leg_km = _live_leg_km(j)
                    progress += (10.0 / 60.0) * 3.0 / leg_km
                    bus["speed_kmh"] = round(max(5.0, 35 - progress * 25), 1)
                    if progress >= 1.0:
                        j["state"] = "AT_STOP"
                        j["current_index"] = next_idx
                        j["next_index"] = next_idx + direction
                        if j["next_index"] < 0 or j["next_index"] >= total:
                            j["next_index"] = next_idx  # parked at terminal until reversal
                        j["progress"] = 0.0
                        j["layover_ticks"] = 0
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

                if tick_count % 8 == 0 and rng.random() < 0.4:
                    occ = bus["occupancy"]
                    pax = occ.get("passengers", 0)
                    pct = occ.get("pct", 0)
                    stop_name = stops[current_idx]["stop"] if current_idx < len(stops) else "en route"
                    current_time = datetime.now(timezone.utc).hour

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


def _auto_start_live_cameras():
    """Start the live prototype cameras (driver + cabin) in a background thread."""
    def _runner():
        time.sleep(0.5)
        try:
            from ai.camera_manager import camera_manager
            result = camera_manager.set_multi_camera_mode()
            print(f"[control-centre] Live cameras auto-start: {result}")
        except Exception as e:
            print(f"[control-centre] Camera auto-start failed: {e}")

    threading.Thread(target=_runner, daemon=True).start()


def _auto_start_dds():
    """Auto-start the DDS engine when the ai_driver_dds toggle is ON.

    Without this the detector booted into phase idle and the per-frame
    monitoring/audio block (drowsiness + 2.3 s face-lost alarm) never ran,
    which is why the audio alert "wasn't on" in the app."""
    def _runner():
        time.sleep(3.0)
        try:
            from feature_toggles import feature_toggles
            if not feature_toggles.get("ai_driver_dds"):
                print("[control-centre] DDS auto-start skipped (toggle OFF)")
                return
            from ai.driver.driver_drowsiness import driver_detector
            ok, msg = driver_detector.start_monitoring()
            print(f"[control-centre] DDS auto-start: {msg}")
        except Exception as e:
            print(f"[control-centre] DDS auto-start failed: {e}")

    threading.Thread(target=_runner, daemon=True).start()


def _start_traffic_monitor():
    """Feed live bus positions to the traffic heat-map engine on a fixed cadence.

    A hotspot appears when 5+ buses stay within a 150 m radius for over a minute
    (see traffic_engine). Runs in every mode; it only reacts to whatever bus
    telemetry the store actually holds."""
    def _runner():
        from traffic_engine import traffic_monitor
        from congestion_heatmap import congestion_heatmap
        from data_store import store
        while True:
            try:
                buses = store.get_buses()
                traffic_monitor.update(buses)
                congestion_heatmap.update(buses)
            except Exception as e:
                print(f"[traffic-engine] update failed: {e}")
            time.sleep(5.0)

    threading.Thread(target=_runner, daemon=True).start()


def _start_auto_assign_monitor():
    """Re-route critical incidents nobody responded to (default: 3 s).

    Every second the monitor asks incident_intelligence for ASSIGNED work
    past its response deadline and re-routes it to the next operator with an
    escalated alert — after 3 unanswered attempts it goes to a supervisor.
    Each re-route needs a fresh popup + sound, which the dashboard picks up
    by polling GET /api/incidents/assigned.
    """
    def _runner():
        time.sleep(5.0)  # let startup settle before first sweep
        while True:
            try:
                from incident_intelligence import process_assignment_timeouts
                process_assignment_timeouts()
            except Exception as e:
                print(f"[control-centre] Auto-assign monitor failed: {e}")
            time.sleep(1.0)

    threading.Thread(target=_runner, daemon=True, name="auto-assign-monitor").start()


def _start_demo_incident_rotation():
    """Demo-only: keep the incident workflow to ~5 incidents that rotate.

    TEMPORARY demo behaviour ("only for now"). Every FLEETIQ_DEMO_ROTATION_SEC
    (default 120 s = 2 minutes) the active incident set is capped at
    FLEETIQ_DEMO_MAX_ACTIVE_INCIDENTS (default 5): oldest surplus incidents
    are resolved so they drop out, and fresh random incidents are created so
    new ones come in. Acknowledged incidents are preserved and counted on the
    Incidents page. Only runs in simulation mode. Opt out with
    FLEETIQ_DEMO_INCIDENT_ROTATION=0.
    """
    def _runner():
        from incident_intelligence import _demo_rotation_enabled, _demo_rotation_sec, _demo_max_active_incidents
        if not _demo_rotation_enabled():
            print("[control-centre] Demo incident rotation DISABLED (FLEETIQ_DEMO_INCIDENT_ROTATION=0)")
            return
        time.sleep(8.0)  # let startup + persisted history settle
        while True:
            try:
                from data_store import mode_state
                if mode_state.is_simulation:
                    from incident_intelligence import rotate_demo_incidents
                    result = rotate_demo_incidents(_demo_max_active_incidents())
                    print(f"[control-centre] Demo incident rotation: {result}")
            except Exception as e:
                print(f"[control-centre] Demo incident rotation failed: {e}")
            time.sleep(_demo_rotation_sec())

    threading.Thread(target=_runner, daemon=True, name="demo-incident-rotation").start()


def _load_persisted_history():
    """Re-hydrate the in-memory event log from SQLite at startup."""
    # Honour FLEETIQ_DB when set (deployments point it at a writable, persistent
    # path outside the code tree); fall back to the bundled dev database.
    persistence.init_db(get_db_path())
    loaded = persistence.load_events()
    # Bulk-load into memory WITHOUT re-persisting: the rows are already the
    # source of truth and re-writing all of them through add_event() is an
    # O(n) reconnect+INSERT+commit operation that stalls startup on large DBs.
    store.load_events_bulk(loaded)
    from incident_intelligence import load_incidents_from_persistence
    load_incidents_from_persistence()
    print(f"[control-centre] Persistence: loaded {len(loaded)} events from history.")


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

    # Refuse to boot a publicly-reachable production instance with known-unsafe
    # configuration (default admin password, wildcard CORS). Opt out with
    # FLEETIQ_ALLOW_INSECURE_STARTUP=1 for a deliberate, monitored exposure.
    security = get_config().security
    blockers = security.startup_blockers()
    if blockers and not security.allow_insecure_startup:
        print("[control-centre] REFUSING TO START: unsafe production configuration")
        for problem in blockers:
            print(f"  - {problem}")
        print("  Fix the environment above, or set FLEETIQ_ALLOW_INSECURE_STARTUP=1 to override.")
        raise SystemExit(2)
    if security.is_production:
        print(f"[control-centre] Environment: production "
              f"(authenticated reads: {security.effective_require_auth_reads})")

    # Initialize lifecycle
    lifecycle = get_lifecycle()
    lifecycle.setup_signal_handlers()
    _register_shutdown_hooks()

    # Kill any orphaned audio loops from previous runs
    try:
        from bus_node.utils.alert_manager import _kill_all_stray_loops
        _kill_all_stray_loops()
    except Exception:
        pass

    # Phase 19: Initialize system health tracking
    try:
        from system_health import initialize_health_tracking
        initialize_health_tracking()
        print("[control-centre] System health tracking initialized.")
    except ImportError:
        print("[control-centre] system_health module not available.")

    # Initialize data source manager
    try:
        from data_source_manager import initialize_data_sources
        initialize_data_sources()
        print("[control-centre] Data source manager initialized.")
    except ImportError:
        print("[control-centre] data_source_manager module not available.")

    # Initialize GTFS shape interpolator
    try:
        from gtfs_shape_interpolator import route_shape_manager
        from gtfs_loader import GTFSLoader
        from pathlib import Path
        gtfs_path = str(Path(__file__).parent / "data" / "mtc-gtfs.zip")
        if Path(gtfs_path).exists():
            gtfs = GTFSLoader(gtfs_path)
            gtfs.load()
            route_shape_manager.initialize_from_gtfs(gtfs)
            print("[control-centre] GTFS shape interpolator initialized.")
    except Exception as e:
        print(f"[control-centre] GTFS shape interpolator init failed: {e}")

    # Initialize traffic pattern engine
    try:
        from traffic_pattern import traffic_pattern_engine
        print("[control-centre] Traffic pattern engine initialized.")
    except ImportError:
        print("[control-centre] traffic_pattern module not available.")

    # Load persisted history
    _load_persisted_history()
    
    # Bootstrap the development Admin
    auth.ensure_bootstrap_admin()
    
    # Set initial mode
    if args.start_mode == "live":
        mode_state.switch_mode("live")
        store.buses.clear()
        store.road_defects.clear()
        _setup_live_proto()
        _auto_start_live_cameras()
        print("[control-centre] Starting in LIVE PROTOTYPE mode.")
    else:
        sim = FleetSimulator()
        _set_simulator(sim)
        sim.start()
        # Also start camera in simulation mode for DDS testing
        _auto_start_live_cameras()
        print("[control-centre] Starting in SIMULATION mode (300 buses).")

    # Auto-start the DDS engine (drowsiness + face-lost audio alarm) when enabled
    _auto_start_dds()

    # Traffic heat-map monitoring (sustained bus-bunch detection)
    _start_traffic_monitor()

    # Critical-incident auto-assignment monitor (3 s response deadline)
    _start_auto_assign_monitor()

    # Demo-only incident rotation (~5 incidents, cycling every 2 minutes)
    _start_demo_incident_rotation()

    # Start WebSocket server
    if not args.no_ws:
        start_websocket_server(host=args.host, port=args.ws_port)
        # Start camera WebSocket server (30 FPS streaming)
        try:
            from camera_ws import start_camera_ws
            start_camera_ws(host=args.host, port=args.ws_port + 1)
            print(f"[control-centre] Camera WebSocket on ws://{args.host}:{args.ws_port + 1}")
        except Exception as e:
            print(f"[control-centre] Camera WebSocket start failed: {e}")
    else:
        print("[control-centre] WebSocket server disabled (--no-ws).")

    # Start cabin occupancy intelligence engine
    try:
        from ai.cabin.occupancy import get_cabin_engine
        get_cabin_engine().start()
    except Exception as e:
        print(f"[control-centre] Cabin intelligence engine start failed: {e}")

    # Pre-open camera in main process
    try:
        from ai.camera_manager import camera_manager
        camera_manager.open_shared_camera()
    except Exception as e:
        print(f"[control-centre] Camera preload failed: {e}")

    # Mark lifecycle as running
    lifecycle.start()

    print(f"[control-centre] API ready at http://{args.host}:{args.port}")
    print(f"[control-centre] Mode: {mode_state.mode}")

    app.run(host=args.host, port=args.port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
