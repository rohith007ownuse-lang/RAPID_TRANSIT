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

Design rules (Phase 9, revised for the operator-focused Live Alerts policy):
- The event IS the truth. An alert is a small projection of one event and
  always carries the original `event_id` so the UI can correlate it with the
  incident workflow. Nothing is duplicated into a second store.
- Severity vocabulary is REUSED, not reinvented: CRITICAL > HIGH > WARNING >
  INFO (same hierarchy the risk engine / fleet summary use).
- Alert fatigue: ordinary telemetry never alerts. INFO-level operational
  notes (passenger moments, recoveries, interventions) never alert.
- Live Alerts tiers: CRITICAL types (crash, driver drowsiness, cabin smoke,
  cabin fire) are pinned at the top and leave only when acknowledged.
  WARNING types (road hazards, overload, risk escalation) queue normally.
  VEHICLE_ANOMALY never alerts (retired — it flooded the feed).
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

# ---------------------------------------------------------------------------
# Live Alerts policy (operator-focused, anti-fatigue)
#
# CRITICAL — highest priority, pinned at the top of Live Alerts and only
# removed once the operator acknowledges them:
#   crash, driver drowsiness, smoke, fire.
# WARNING — second priority, normal queue:
#   road hazards, bus overload, risk escalation predictions.
# INFO  — never alerts.
# VEHICLE_ANOMALY — intentionally NOT alertable: it flooded the alert feed.
# ---------------------------------------------------------------------------
CRITICAL_ALERT_TYPES = {
    "CRASH",                # possible crash / impact
    "DRIVER_DROWSINESS",    # driver safety (sim + live DDS + bus nodes)
    "CABIN_SMOKE",          # smoke in the bus
    "CABIN_FIRE",           # fire in the bus
}

WARNING_ALERT_TYPES = {
    "POTHOLE",                 # road hazard
    "ROAD_DEFECT",             # road hazard
    "OVERLOAD",                # bus overload
    "RISK_ESCALATION",         # risk escalation prediction
    "CRITICAL_RISK",           # risk escalated to the top band
    "RISK_STATE_CHANGE",       # meaningful risk state transition
    "DRIVER_REFRESH_REQUIRED",  # long-term fatigue elevated
}

# Types that must NEVER surface in Live Alerts (noise sources).
NEVER_ALERT_TYPES = {
    "VEHICLE_ANOMALY",
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

    Type-first rule on the EXISTING event severity:
      CRITICAL types (crash / drowsiness / smoke / fire) -> always alert,
        at any severity, and are pinned until acknowledged.
      WARNING types (road hazards / overload / risk escalation) -> only when
        the event severity is WARNING or above.
      INFO / unknown -> never (avoids alert fatigue).
      VEHICLE_ANOMALY -> never (explicitly retired from Live Alerts).
    """
    if not isinstance(event, dict):
        return False
    event_type = (event.get("event_type") or "").upper()
    if event_type in NEVER_ALERT_TYPES:
        return False
    severity = (event.get("severity") or "").upper()
    if event_type in CRITICAL_ALERT_TYPES:
        return True
    if event_type in WARNING_ALERT_TYPES:
        return severity in ("CRITICAL", "HIGH", "WARNING")
    return False


def alert_tier(event: dict) -> str:
    """UI tier for an alert-worthy event: 'CRITICAL' or 'WARNING'.

    The tier decides placement in Live Alerts: CRITICAL items are pinned at
    the top and only leave after acknowledgement.
    """
    event_type = ((event or {}).get("event_type") or "").upper()
    if event_type in CRITICAL_ALERT_TYPES:
        return "CRITICAL"
    return "WARNING"


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
        "tier": alert_tier(event),
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
    store — never a parallel store.

    Ordering: CRITICAL-tier unacknowledged alerts first (pinned), then
    everything else newest-first. Acknowledged criticals drop out of the
    pinned block — they only leave Live Alerts once acknowledged."""
    items = [build_alert(e) for e in events if is_alertworthy(e)]
    # newest first, then a stable pass that hoists the unacknowledged criticals
    items.sort(key=lambda a: (a.get("timestamp") or "",), reverse=True)
    items.sort(key=lambda a: 0 if (a.get("tier") == "CRITICAL" and a.get("status") == "ACTIVE") else 1)
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
