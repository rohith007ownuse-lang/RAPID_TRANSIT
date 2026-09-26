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

    # In-memory event cap. Reads only ever serve the newest 500–1000, and
    # persistence (SQLite) keeps the full history — so the live dict holds a
    # generous window, not an unbounded month of simulation. Without this, a
    # 24/7 deployment grows without limit.
    MAX_EVENTS = 5000

    def __init__(self):
        self._lock = threading.Lock()

        # bus_id -> bus state dict
        self.buses = OrderedDict()

        # event_id -> event dict (append-only log)
        self.events = OrderedDict()

        # road-defect key -> defect dict (grouped persistent defects)
        self.road_defects = OrderedDict()

        # bus_id -> maintenance review record. A vehicle that enters the
        # "needs maintenance" list STAYS there until an operator reviews it
        # (review-to-clear) — it must not vanish just because its counters
        # decayed back under threshold on a later tick.
        self.maintenance_reviews = OrderedDict()

        # bus_id -> first-flag snapshot. Remembers every vehicle that EVER
        # entered the needs-maintenance list, so a bus cannot drop off the
        # list by transient counter decay — only an operator review clears it.
        self.maintenance_flagged = OrderedDict()

    def upsert_bus(self, bus):
        with self._lock:
            self.buses[bus["bus_id"]] = bus

    def get_bus(self, bus_id):
        with self._lock:
            return self.buses.get(bus_id)

    def get_buses(self):
        with self._lock:
            return list(self.buses.values())

    def load_events_bulk(self, events):
        """Bulk-load already-persisted events straight into memory.

        Used at startup to re-hydrate the in-memory log from SQLite without
        re-writing every row (they are the source of truth and already
        persisted) and without re-running the alert pipeline. This avoids
        the O(n) reconnect+INSERT+commit cost of replaying each event
        through add_event().
        """
        with self._lock:
            for event in events:
                event_id = event.get("event_id") or str(uuid.uuid4())[:13]
                self.events[event_id] = dict(event)
            self._trim_locked()

    def add_event(self, event):
        """Add an event to the store.

        Phase 19: Enhanced with health tracking and failure isolation.
        Persistence failures are now caught and logged without breaking
        the event pipeline.
        """
        event_id = event.get("event_id") or str(uuid.uuid4())[:13]
        event = dict(event)
        event["event_id"] = event_id
        event.setdefault("timestamp", utcnow_iso())
        event.setdefault("status", "ACTIVE")
        with self._lock:
            self.events[event_id] = event
            self._trim_locked()
        # Phase 16: correlate the raw event into an operational INCIDENT so
        # the Incident Management workflow (Not finished / Resolved / Total)
        # reflects what actually happens — previously incidents were only
        # created when operators acknowledged, so the counters stayed 0/0/0.
        try:
            from incident_intelligence import process_event as incident_process_event
            incident_process_event(event, bus=self.buses.get(event.get("bus_id")))
        except Exception:
            pass  # incident correlation must never break the event pipeline
        # Persistence first (the event is the source of truth), then the
        # Phase-9 real-time alert decision. The alert step is failure-isolated:
        # no broadcast problem can ever break event creation.
        # Phase 19: Persistence failure is now caught and logged
        try:
            persistence.save_event(event)
        except Exception as exc:
            # Phase 19: Persistence failure is non-blocking but observable
            print(f"[data-store] persistence error (event kept in memory): {exc}")
            try:
                from system_health import record_subsystem_failure
                record_subsystem_failure("persistence", str(exc), critical=False)
            except ImportError:
                pass
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

    def _trim_locked(self):
        """Drop oldest events beyond MAX_EVENTS. Callers must hold the lock.

        OrderedDict preserves insertion order, so the head is always the
        oldest. Persistence keeps the full history — this only bounds RAM.
        """
        overflow = len(self.events) - self.MAX_EVENTS
        for _ in range(max(0, overflow)):
            self.events.popitem(last=False)

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

    # ---- Maintenance reviews (review-to-clear for Vehicle Health) ----
    def review_maintenance(self, bus_id, operator=None, note=None):
        """Mark a vehicle's maintenance entry reviewed (clears it from the list)."""
        with self._lock:
            record = {
                "bus_id": bus_id,
                "reviewed_by": operator or "operator",
                "reviewed_at": utcnow_iso(),
                "note": note or "",
            }
            self.maintenance_reviews[bus_id] = record
            return record

    def unreview_maintenance(self, bus_id):
        """Re-open a maintenance entry (e.g. fault re-appears)."""
        with self._lock:
            return self.maintenance_reviews.pop(bus_id, None)

    def get_maintenance_reviews(self):
        with self._lock:
            return dict(self.maintenance_reviews)

    def is_maintenance_reviewed(self, bus_id):
        with self._lock:
            return bus_id in self.maintenance_reviews

    def flag_maintenance(self, bus_id, days=None, status=None):
        """Remember that a bus entered the needs-maintenance list."""
        with self._lock:
            existing = self.maintenance_flagged.get(bus_id)
            if existing:
                existing["last_days"] = days
                existing["last_status"] = status
                existing["last_seen"] = utcnow_iso()
                return existing
            record = {
                "bus_id": bus_id,
                "first_flagged_at": utcnow_iso(),
                "last_seen": utcnow_iso(),
                "last_days": days,
                "last_status": status,
            }
            self.maintenance_flagged[bus_id] = record
            return record

    def get_maintenance_flagged(self):
        with self._lock:
            return dict(self.maintenance_flagged)

    def clear_maintenance_flag(self, bus_id):
        """Drop the sticky flag (called together with a review)."""
        with self._lock:
            return self.maintenance_flagged.pop(bus_id, None)

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