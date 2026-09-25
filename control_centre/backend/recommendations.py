"""
recommendations.py
AI Intervention / Recommendation layer for the Control Centre.

A rule-based supervisor that converts risk engine outputs into concrete,
dismissible operator actions. Actions are logged, can be acknowledged,
and may auto-escalate for critical drowsiness/overload scenarios.
All output is tagged SIMULATION.
"""

from datetime import datetime, timezone
import threading
import uuid

from data_store import store
from risk_engine import bus_risk, fleet_risk, DEFAULT_RISK_WEIGHTS


class ActionStore:
    """Thread-safe store for recommended actions."""

    def __init__(self):
        self._lock = threading.Lock()
        self.actions = {}  # action_id -> action dict

    def add_action(self, action):
        with self._lock:
            self.actions[action["action_id"]] = action
        return action

    def get_action(self, action_id):
        with self._lock:
            return self.actions.get(action_id)

    def get_actions(self, bus_id=None, unacked_only=False):
        with self._lock:
            items = list(self.actions.values())
        if bus_id:
            items = [a for a in items if a.get("bus_id") == bus_id]
        if unacked_only:
            items = [a for a in items if not a.get("acknowledged")]
        return items

    def ack_action(self, action_id, operator=None):
        with self._lock:
            a = self.actions.get(action_id)
            if a:
                a["acknowledged"] = True
                a["acknowledged_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if operator:
                    a["acknowledged_by"] = operator
                return a
        return None

    def resolve_action(self, action_id, operator=None):
        with self._lock:
            a = self.actions.get(action_id)
            if a:
                a["resolved"] = True
                a["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if operator:
                    a["resolved_by"] = operator
                return a
        return None

    def clear_acknowledged(self):
        with self._lock:
            for a in self.actions.values():
                if a.get("acknowledged"):
                    a["archived"] = True


action_store = ActionStore()


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _emit_intervention_event(bus, action_type, note):
    """Write an OTHER_CC event for operator intervention."""
    store.add_event({
        "bus_id": bus["bus_id"],
        "reg_no": bus.get("reg_no"),
        "event_type": "OTHER_CC",
        "latitude": round(bus.get("latitude", 0.0), 6),
        "longitude": round(bus.get("longitude", 0.0), 6),
        "severity": "INFO",
        "confidence": 0.9,
        "sensor_source": "recommendation_ai",
        "status": "ACTIVE",
        "simulation": True,
        "additional_data": {
            "note": note,
            "intervention_type": action_type,
            "auto_generated": True,
        },
    })


def evaluate_fleet(buses, events, risk_weights=None, detection=None):
    """Generate recommended actions for the entire fleet based on risk."""
    actions_created = []
    for bus in buses:
        risk = bus_risk(bus, events, risk_weights, detection)
        new_actions = generate_actions(bus, risk)
        for act in new_actions:
            action_store.add_action(act)
            actions_created.append(act)
    # check for auto-escalation of unacknowledged critical actions
    auto_escalate_critical()
    return actions_created


def generate_actions(bus, risk):
    """Produce action dicts for a single bus from its risk assessment."""
    actions = []
    bid = bus["bus_id"]
    now = utcnow_iso()

    def make_action(action_type, title, detail, severity="INFO", auto_escalate=False):
        return {
            "action_id": str(uuid.uuid4())[:12],
            "bus_id": bid,
            "route": bus.get("route", ""),
            "reg_no": bus.get("reg_no", ""),
            "type": action_type,
            "title": title,
            "detail": detail,
            "severity": severity,
            "auto_escalate": auto_escalate,
            "acknowledged": False,
            "resolved": False,
            "created_at": now,
            "simulation": True,
        }

    # --- CRITICAL / HIGH risk auto-interventions ---
    if risk["risk_level"] in ("CRITICAL", "HIGH"):
        actions.append(make_action(
            "REVIEW_REQUIRED",
            "Operator review required",
            f"Bus {bid} risk level: {risk['risk_level']} (score {risk['risk_score']}).",
            severity=risk["risk_level"],
            auto_escalate=risk["risk_level"] == "CRITICAL",
        ))

    # --- Driver fatigue specific actions ---
    driver = bus.get("driver") or {}
    if driver.get("fatigue_stage") == "CRITICAL":
        actions.append(make_action(
            "RELIEF_DRIVER",
            "Consider relief driver",
            f"Driver {driver.get('name','')} in CRITICAL fatigue stage; "
            f"PERCLOS {driver.get('perclos',0)}%, long-term {driver.get('fatigue_lt',0):.0f}. "
            "Schedule relief at next major stop or depot.",
            severity="CRITICAL",
            auto_escalate=True,
        ))
    elif driver.get("fatigue_stage") == "ALERT":
        actions.append(make_action(
            "FATIGUE_MONITOR",
            "Heightened fatigue monitoring",
            f"Driver in ALERT fatigue stage; PERCLOS {driver.get('perclos',0)}%. "
            "Monitor for escalation; ready cabin alert.",
            severity="WARNING",
        ))

    # --- Overload ---
    load = bus.get("load") or {}
    if load.get("load_pct", 0) > 95:
        actions.append(make_action(
            "OVERLOAD_DISPATCH",
            "Overload — limit boarding",
            f"GVW {load.get('gvw_kg',0):,} kg ({load.get('load_pct',0)}% payload). "
            "Advise conductor to limit boarding; flag for dispatch review.",
            severity="WARNING",
        ))

    # --- Vehicle health ---
    vehicle = bus.get("vehicle") or {}
    if vehicle.get("health") != "NORMAL":
        is_critical = vehicle.get("health") != "WARNING"
        actions.append(make_action(
            "MAINTENANCE_DISPATCH",
            "Maintenance required",
            f"Vehicle health: {vehicle.get('health')} — {vehicle.get('anomaly','anomaly')}. "
            f"Vibration {vehicle.get('vibration',0):.2f}. "
            "Dispatch maintenance crew at next depot.",
            severity="WARNING" if not is_critical else "CRITICAL",
            auto_escalate=is_critical,
        ))

    # --- Tyre pressure ---
    wheels = bus.get("wheels") or []
    out_of_range = [(i+1, w) for i, w in enumerate(wheels) if w < 70 or w > 95]
    if out_of_range:
        actions.append(make_action(
            "TYRE_CHECK",
            "Tyre pressure check",
            f"Wheels out of range: {', '.join(f'#{i} ({w:.0f} PSI)' for i, w in out_of_range)}. "
            "Inflate/rectify at next stop.",
            severity="WARNING",
        ))

    # --- Energy low ---
    energy = bus.get("energy") or {}
    low_limit = 15 if energy.get("type") == "DIESEL" else 20
    if energy.get("percent", 100) <= low_limit:
        actions.append(make_action(
            "REFUEL_CHARGE",
            f"{energy.get('type','')} low",
            f"{energy.get('type','')} reserve at {energy.get('percent',0):.0f}% — "
            f"plan refuel/charge before next rotation.",
            severity="INFO",
        ))

    # --- Speed ---
    speed = float(bus.get("speed_kmh", 0))
    if speed >= 50:
        actions.append(make_action(
            "SPEED_ADVISORY",
            "Speed advisory",
            f"Running at {speed:.0f} km/h — advise driver to reduce speed.",
            severity="WARNING" if speed >= 55 else "INFO",
        ))

    # --- Occupancy ---
    occ = bus.get("occupancy") or {}
    if occ.get("pct", 0) >= 95:
        actions.append(make_action(
            "RELIEF_BUS",
            "High occupancy — consider relief bus",
            f"Passenger load {occ.get('pct',0)}% of capacity. "
            "Consider dispatching a relief bus to ease crowding.",
            severity="CRITICAL",
            auto_escalate=True,
        ))
    elif occ.get("pct", 0) >= 90:
        actions.append(make_action(
            "RELIEF_BUS",
            "High occupancy — consider relief bus",
            f"Passenger load {occ.get('pct',0)}% of capacity. "
            "Consider dispatching a relief bus to ease crowding.",
            severity="WARNING",
        ))

    return actions


def auto_escalate_critical():
    """Auto-escalate unacknowledged CRITICAL actions: notify dispatch, emit events."""
    unacked = action_store.get_actions(unacked_only=True)
    for a in unacked:
        if a.get("severity") == "CRITICAL" and a.get("auto_escalate") and not a.get("escalated"):
            a["escalated"] = True
            a["escalated_at"] = utcnow_iso()
            # emit escalation event
            bus = store.get_bus(a["bus_id"])
            if bus:
                _emit_intervention_event(bus, "AUTO_ESCALATE", f"Auto-escalated: {a['title']}")


if __name__ == "__main__":
    import json
    # quick self-test
    buses = store.get_buses()
    events = store.get_events(1000)
    acts = evaluate_fleet(buses, events)
    print(json.dumps(acts[:3], indent=2))