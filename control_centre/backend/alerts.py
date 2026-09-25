"""
alerts.py
Real-Time Alert Intelligence (Phase 9) — the alert DECISION layer.

The existing event/incident system stays the single source of truth:

    Detection
       ↓
    Event  (store.add_event -> persisted to SQLite)
       ↓
    Classification  (this module: is_alertworthy / build_alert)
       ↓
    Alert decision  (process_event: once per event_id, never duplicated)
       ↓
    Broadcast  (registered broadcasters — the existing WebSocket server)
       ↓
    Control Centre UI  (toast + alert centre; dismiss ≠ resolve incident)

Design rules (Phase 9):
- The event IS the truth. An alert is a small projection of one event and
  always carries the original `event_id` so the UI can correlate it with the
  incident workflow. Nothing is duplicated into a second store.
- Severity vocabulary is REUSED, not reinvented: CRITICAL > HIGH > WARNING >
  INFO (same hierarchy the risk engine / fleet summary use).
- Alert fatigue: ordinary telemetry never alerts. INFO-level operational
  notes (passenger moments, recoveries, interventions) never alert.
- Identity: one event_id ⇒ at most one alert, even if the event is re-sent
  over WebSocket or the broadcast happens twice.
- Broadcast is best-effort and failure-isolated: if no broadcaster is
  registered (e.g. --no-ws) or a broadcaster raises, the event is already
  persisted and normal backend operation continues. This module never raises
  into the event path.

This module is intentionally dependency-free (no data_store / server
imports) so data_store.py can call into it without circular imports.
"""

import threading
from collections import OrderedDict
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Severity / priority (existing vocabulary, preserved)
# ---------------------------------------------------------------------------

PRIORITY_ORDER = ["CRITICAL", "HIGH", "WARNING", "INFO"]
PRIORITY_RANK = {name: i for i, name in enumerate(PRIORITY_ORDER)}

# Event types that deserve a UI alert even at WARNING severity (meaningful
# operational conditions that actually exist in this backend). CRITICAL/HIGH
# events of any type alert; INFO events of any type never do.
WARNING_ALERT_TYPES = {
    "DRIVER_DROWSINESS",       # driver safety (sim + live DDS + bus nodes)
    "DRIVER_ALERT",            # cabin audio warning issued
    "DRIVER_REFRESH_REQUIRED",  # long-term fatigue elevated
    "CRASH",                   # possible crash / impact
    "CABIN_FIRE",
    "CABIN_SMOKE",
    "CABIN_INCIDENT",
    "EMERGENCY_SIREN",
    "OVERLOAD",                # passenger overload
    "VEHICLE_ANOMALY",
    "POTHOLE",                 # road hazard
    "ROAD_DEFECT",
    "BUS_OFFLINE",             # live node stopped sending telemetry (watchdog)
    "ETA_SEVERE_DELAY",        # Phase 13: significant operational delay
    "CAPACITY_PRESSURE",       # Phase 14: forecast demand exceeds capacity
    "OVERCROWDING",            # Phase 14: sustained overcrowding detected
    "RISK_STATE_CHANGE",       # Phase 15: meaningful risk state transition
    "RISK_ESCALATION",         # Phase 15: risk escalated to higher level
    "RISK_RECOVERY",           # Phase 15: risk decreased to lower level
    "CRITICAL_RISK",           # Phase 15: critical risk detected
}

_MAX_SEEN_IDS = 1000          # recent alert-identity window (dedup registry)

# human-readable titles for the operator (mirrors the frontend TYPE_LABEL map)
TYPE_TITLES = {
    "DRIVER_DROWSINESS": "Driver drowsiness detected",
    "DRIVER_ALERT": "Driver alert issued (cabin audio)",
    "DRIVER_RECOVERED": "Driver recovered",
    "DRIVER_REFRESH_REQUIRED": "Driver refresh required",
    "CRASH": "Possible crash / impact",
    "CABIN_FIRE": "Cabin fire",
    "CABIN_SMOKE": "Cabin smoke",
    "CABIN_INCIDENT": "Cabin incident",
    "EMERGENCY_SIREN": "Emergency siren detected",
    "OVERLOAD": "Vehicle overload",
    "VEHICLE_ANOMALY": "Vehicle health anomaly",
    "POTHOLE": "Pothole / road defect",
    "ROAD_DEFECT": "Road defect detected",
    "PASSENGER_MOMENT": "Passenger update",
    "BUS_OFFLINE": "Bus went offline",
    "ETA_SEVERE_DELAY": "Severe delay detected",
    "CAPACITY_PRESSURE": "Capacity pressure forecast",
    "OVERCROWDING": "Sustained overcrowding",
    "RISK_STATE_CHANGE": "Risk state changed",
    "RISK_ESCALATION": "Risk escalated",
    "RISK_RECOVERY": "Risk recovered",
    "CRITICAL_RISK": "Critical risk detected",
    "OTHER_CC": "Control-centre intervention",
}

_lock = threading.Lock()
_seen_alert_ids = OrderedDict()      # event_id -> True (insertion-ordered cap)
_broadcasters = []                   # callables: fn(alert_dict) -> None


# ---------------------------------------------------------------------------
# Classification (pure functions)
# ---------------------------------------------------------------------------

def is_alertworthy(event: dict) -> bool:
    """Should this event become a real-time UI alert?

    Severity-first rule on the EXISTING event severity:
      CRITICAL / HIGH -> always
      WARNING         -> only for operationally meaningful types
      INFO / unknown  -> never (avoids alert fatigue)
    """
    if not isinstance(event, dict):
        return False
    severity = (event.get("severity") or "").upper()
    if severity in ("CRITICAL", "HIGH"):
        return True
    if severity == "WARNING":
        return (event.get("event_type") or "").upper() in WARNING_ALERT_TYPES
    return False


def build_alert(event: dict, bus: dict | None = None) -> dict:
    """Project one persisted event into the small real-time alert schema.

    The event payload is NOT copied wholesale — `event_id` is the correlation
    handle back to the incident workflow.
    """
    event_id = event.get("event_id") or ""
    severity = (event.get("severity") or "INFO").upper()
    data_source = event.get("data_source") or ("live" if event.get("simulation") is False else "simulation")
    note = ""
    extra = event.get("additional_data")
    if isinstance(extra, dict):
        note = str(extra.get("note") or "")
    route = event.get("route_code")
    if not route and isinstance(bus, dict):
        route = bus.get("route_code") or bus.get("route")
    return {
        "alert_id": f"ALR-{event_id}",
        "event_id": event_id,
        "timestamp": event.get("timestamp")
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "type": event.get("event_type") or "UNKNOWN",
        "severity": severity,
        "priority": PRIORITY_RANK.get(severity, len(PRIORITY_ORDER)),
        "bus_id": event.get("bus_id") or "",
        "route": route,
        "title": TYPE_TITLES.get((event.get("event_type") or "").upper(),
                                 event.get("event_type") or "Event"),
        "message": note,
        "source": event.get("sensor_source") or "control_centre",
        "simulation": bool(event.get("simulation")),
        "data_source": data_source,
        "status": event.get("status") or "ACTIVE",
    }


def project_alerts(events: list) -> list:
    """Project a newest-first event list into alert payloads (for
    GET /api/alerts and reconnect reconciliation). Reads the EXISTING event
    store — never a parallel store."""
    items = [build_alert(e) for e in events if is_alertworthy(e)]
    items.sort(key=lambda a: (a.get("timestamp") or "",), reverse=True)
    return items


# ---------------------------------------------------------------------------
# Dedup + fan-out
# ---------------------------------------------------------------------------

def register_broadcaster(fn) -> None:
    """Register a broadcast callable (e.g. the WebSocket push). Idempotent."""
    with _lock:
        if fn not in _broadcasters:
            _broadcasters.append(fn)


def unregister_broadcaster(fn) -> None:
    with _lock:
        if fn in _broadcasters:
            _broadcasters.remove(fn)


def process_event(event: dict, bus: dict | None = None):
    """Alert decision for one persisted event. Called by the event store
    AFTER the event is safely persisted.

    Returns the alert dict when it was newly broadcast, or None when the
    event is not alert-worthy OR its event_id already produced an alert
    (duplicate suppression — one event_id can never spam the operator).

    Never raises: a broadcaster failure is logged and swallowed so event
    processing cannot be broken by a disconnected UI client.
    """
    if not isinstance(event, dict):
        return None
    event_id = event.get("event_id")
    if not event_id:
        return None

    with _lock:
        if event_id in _seen_alert_ids:
            return None
        # mark identity first: broadcast happens outside the lock, and a
        # duplicate arriving mid-broadcast must still not double-alert
        _seen_alert_ids[event_id] = True
        while len(_seen_alert_ids) > _MAX_SEEN_IDS:
            _seen_alert_ids.popitem(last=False)

    if not is_alertworthy(event):
        return None

    alert = build_alert(event, bus=bus)
    with _lock:
        broadcasters = list(_broadcasters)
    for fn in broadcasters:
        try:
            fn(alert)
        except Exception as exc:  # noqa: BLE001 — broadcast must never break events
            print(f"[alerts] broadcast failed (ignored): {exc}")
    return alert


def reset_alert_state() -> None:
    """Test helper: clear the dedup registry (broadcasters are untouched)."""
    with _lock:
        _seen_alert_ids.clear()
