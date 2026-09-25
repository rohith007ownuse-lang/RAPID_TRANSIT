"""
data_store.py
In-memory store for the Control Centre. Holds bus states, events, and
road defects. Supports two mutually exclusive modes: SIMULATION and LIVE.
"""

import uuid
import threading
import time
from datetime import datetime, timezone
from collections import OrderedDict

import persistence
import alerts


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ModeState:
    """Centralized system mode management. Only one mode active at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._mode = "simulation"  # "simulation" or "live"
        self._live_nodes = {}  # bus_id -> {last_seen, connected, gps_available, ...}

    @property
    def mode(self):
        with self._lock:
            return self._mode

    @property
    def is_simulation(self):
        return self.mode == "simulation"

    @property
    def is_live(self):
        return self.mode == "live"

    def switch_mode(self, new_mode):
        """Switch between simulation and live modes. Returns (success, message)."""
        if new_mode not in ("simulation", "live"):
            return False, "Invalid mode. Use 'simulation' or 'live'."
        with self._lock:
            if self._mode == new_mode:
                return True, f"Already in {new_mode} mode."
            old_mode = self._mode
            self._mode = new_mode
        return True, f"Switched from {old_mode} to {new_mode}."

    def register_live_node(self, bus_id, info=None):
        """Register a live prototype node."""
        with self._lock:
            self._live_nodes[bus_id] = {
                "bus_id": bus_id,
                "last_seen": time.time(),
                "connected": True,
                "gps_available": False,
                "sensors": {},
                **(info or {}),
            }

    def update_live_node(self, bus_id, info=None):
        """Update live node info (last_seen, sensors, etc.)."""
        with self._lock:
            if bus_id in self._live_nodes:
                self._live_nodes[bus_id]["last_seen"] = time.time()
                self._live_nodes[bus_id]["connected"] = True
                if info:
                    self._live_nodes[bus_id].update(info)

    def get_live_node(self, bus_id):
        """Get live node info."""
        with self._lock:
            return self._live_nodes.get(bus_id)

    def get_live_nodes(self):
        """Get all live nodes."""
        with self._lock:
            return dict(self._live_nodes)

    def get_connected_live_nodes(self):
        """Get only connected live nodes (last seen within 30 seconds)."""
        now = time.time()
        with self._lock:
            return {
                bid: node for bid, node in self._live_nodes.items()
                if now - node.get("last_seen", 0) < 30
            }

    def remove_live_node(self, bus_id):
        """Remove a live node."""
        with self._lock:
            self._live_nodes.pop(bus_id, None)

    def clear_live_nodes(self):
        """Remove all live node registrations (e.g. when leaving live mode)."""
        with self._lock:
            self._live_nodes.clear()


class EventStore:
    """Thread-safe containers for buses, events, and road defects."""

    def __init__(self):
        self._lock = threading.Lock()

        # bus_id -> bus state dict
        self.buses = OrderedDict()

        # event_id -> event dict (append-only log)
        self.events = OrderedDict()

        # road-defect key -> defect dict (grouped persistent defects)
        self.road_defects = OrderedDict()

    def upsert_bus(self, bus):
        with self._lock:
            self.buses[bus["bus_id"]] = bus

    def get_bus(self, bus_id):
        with self._lock:
            return self.buses.get(bus_id)

    def get_buses(self):
        with self._lock:
            return list(self.buses.values())

    def add_event(self, event):
        event_id = event.get("event_id") or str(uuid.uuid4())[:13]
        event = dict(event)
        event["event_id"] = event_id
        event.setdefault("timestamp", utcnow_iso())
        event.setdefault("status", "ACTIVE")
        with self._lock:
            self.events[event_id] = event
        # Persistence first (the event is the source of truth), then the
        # Phase-9 real-time alert decision. The alert step is failure-isolated:
        # no broadcast problem can ever break event creation.
        persistence.save_event(event)
        try:
            bus_snapshot = self.buses.get(event.get("bus_id"))
            alerts.process_event(event, bus=bus_snapshot)
        except Exception as exc:  # noqa: BLE001 — events must never break
            print(f"[data-store] alert processing error (event kept): {exc}")
        return event

    def get_events(self, limit=200):
        with self._lock:
            items = list(self.events.values())
        return items[-limit:][::-1]

    def acknowledge_event(self, event_id, operator=None):
        with self._lock:
            ev = self.events.get(event_id)
            if ev:
                ev["status"] = "ACKNOWLEDGED"
                if operator:
                    ev["acknowledged_by"] = operator
                persistence.save_event(ev)
                return ev
        return None

    def review_event(self, event_id, operator=None):
        with self._lock:
            ev = self.events.get(event_id)
            if ev:
                ev["status"] = "REVIEWING"
                if operator:
                    ev["reviewed_by"] = operator
                persistence.save_event(ev)
                return ev
        return None

    def resolve_event(self, event_id, operator=None):
        with self._lock:
            ev = self.events.get(event_id)
            if ev:
                ev["status"] = "RESOLVED"
                if operator:
                    ev["resolved_by"] = operator
                persistence.save_event(ev)
                return ev
        return None

    def set_event_status(self, event_id, status, operator=None):
        """Explicit status override from the incidents edit form."""
        with self._lock:
            ev = self.events.get(event_id)
            tag = {
                "ACTIVE": "unreviewed_by",
                "REVIEWING": "reviewed_by",
                "ACKNOWLEDGED": "acknowledged_by",
                "RESOLVED": "resolved_by",
            }
            if ev and status in tag:
                ev["status"] = status
                if operator:
                    ev[tag[status]] = operator
                    ev["updated_by"] = operator
                persistence.save_event(ev)
                return ev
        return None

    def set_event_status_many(self, status, operator=None, bus_id=None):
        """Apply one status to many events at once (single bus or whole fleet)."""
        tag = {
            "ACTIVE": "unreviewed_by",
            "REVIEWING": "reviewed_by",
            "ACKNOWLEDGED": "acknowledged_by",
            "RESOLVED": "resolved_by",
        }
        if status not in tag:
            return 0
        with self._lock:
            updated = 0
            for ev in self.events.values():
                if bus_id and ev.get("bus_id") != bus_id:
                    continue
                ev["status"] = status
                if operator:
                    ev[tag[status]] = operator
                    ev["updated_by"] = operator
                persistence.save_event(ev)
                updated += 1
            return updated

    # ---- Road defects ----
    def get_road_defect(self, key):
        with self._lock:
            return self.road_defects.get(key)

    def upsert_road_defect(self, key, defect):
        with self._lock:
            existing = self.road_defects.get(key)
            if existing:
                existing.update(defect)
                return existing
            self.road_defects[key] = defect
            return defect

    def get_road_defects(self):
        with self._lock:
            return list(self.road_defects.values())

    # ---- Settings / config (editable from the UI) ----
    def get_settings(self):
        with self._lock:
            return dict(self.settings)

    def update_settings(self, patch):
        with self._lock:
            for k, v in patch.items():
                self.settings[k] = v
        return dict(self.settings)

    settings = {
        "simulation": True,
        "city": {
            "name": "Chennai",
            "country": "India",
            "map_center": [13.0827, 80.2747],
            "bounds": {"south": 12.85, "west": 80.10, "north": 13.30, "east": 80.40},
            "note": "Simulated demo map/route bounds only.",
        },
        "bus": {
            "tare_weight_kg": 11000,
            "max_gvw_kg": 17000,
            "payload_limit_kg": 6000,
            "tyre_target_psi": 85,
        },
        "detection": {
            "ear_threshold": 0.23,
            "mar_threshold": 0.40,
            "eye_closed_duration": 1.3,
        },
        "simulator": {
            "scan_interval_s": 1.0,
            "sim_min_per_tick": 2.0,
        },
        "risk": {
            "driver": 30,
            "vehicle": 20,
            "load": 15,
            "speed": 10,
            "occupancy": 10,
            "history": 15,
        },
    }


store = EventStore()
mode_state = ModeState()