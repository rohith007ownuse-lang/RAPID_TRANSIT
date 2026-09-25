"""
incident_intelligence.py
Phase 16: Incident Intelligence, Correlation & Operational Response.

Converts raw events into meaningful operational incidents through correlation,
deduplication, prioritization, and lifecycle management.

Key concepts:
- EVENT: Something happened (drowsiness, pothole, vehicle anomaly, etc.)
- ALERT: Event requires operator attention (Phase 9 alerts.py)
- INCIDENT: Operational problem requiring tracking and resolution (this module)

The incident system does NOT replace events or alerts — it correlates them
into actionable operational intelligence.
"""

import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

import persistence

# ---------------------------------------------------------------------------
# Incident severity and priority
# ---------------------------------------------------------------------------

INCIDENT_SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
INCIDENT_PRIORITIES = ("LOW", "MEDIUM", "HIGH", "URGENT")
INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "CLOSED")
INCIDENT_SOURCES = (
    "DRIVER_SAFETY", "DDS", "VEHICLE_HEALTH", "ROAD_INTELLIGENCE",
    "ETA", "PASSENGER_LOAD", "RISK_ENGINE", "SYSTEM", "OTHER"
)
INCIDENT_CATEGORIES = (
    "DRIVER_SAFETY", "VEHICLE_HEALTH", "ROAD_HAZARD",
    "PASSENGER_LOAD", "ETA_DELAY", "RISK_ESCALATION", "SYSTEM"
)

# Event types that can trigger incidents
INCIDENT_TRIGGER_TYPES = {
    "DRIVER_DROWSINESS", "DRIVER_ALERT", "DRIVER_REFRESH_REQUIRED",
    "CRASH", "CABIN_FIRE", "CABIN_SMOKE", "CABIN_INCIDENT",
    "EMERGENCY_SIREN", "OVERLOAD", "VEHICLE_ANOMALY",
    "POTHOLE", "ROAD_DEFECT", "BUS_OFFLINE",
    "ETA_SEVERE_DELAY", "CAPACITY_PRESSURE", "OVERCROWDING",
    "RISK_STATE_CHANGE", "RISK_ESCALATION", "CRITICAL_RISK",
}

# Severity mapping from event severity to incident severity
EVENT_TO_INCIDENT_SEVERITY = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "WARNING": "MEDIUM",
    "INFO": "LOW",
}

# Source mapping from event type to incident source
EVENT_TYPE_TO_SOURCE = {
    "DRIVER_DROWSINESS": "DRIVER_SAFETY",
    "DRIVER_ALERT": "DDS",
    "DRIVER_REFRESH_REQUIRED": "DRIVER_SAFETY",
    "DRIVER_RECOVERED": "DRIVER_SAFETY",
    "CRASH": "SYSTEM",
    "CABIN_FIRE": "SYSTEM",
    "CABIN_SMOKE": "SYSTEM",
    "CABIN_INCIDENT": "SYSTEM",
    "EMERGENCY_SIREN": "SYSTEM",
    "OVERLOAD": "PASSENGER_LOAD",
    "VEHICLE_ANOMALY": "VEHICLE_HEALTH",
    "POTHOLE": "ROAD_INTELLIGENCE",
    "ROAD_DEFECT": "ROAD_INTELLIGENCE",
    "BUS_OFFLINE": "SYSTEM",
    "ETA_SEVERE_DELAY": "ETA",
    "CAPACITY_PRESSURE": "PASSENGER_LOAD",
    "OVERCROWDING": "PASSENGER_LOAD",
    "RISK_STATE_CHANGE": "RISK_ENGINE",
    "RISK_ESCALATION": "RISK_ENGINE",
    "CRITICAL_RISK": "RISK_ENGINE",
}

# Category mapping from event type to incident category
EVENT_TYPE_TO_CATEGORY = {
    "DRIVER_DROWSINESS": "DRIVER_SAFETY",
    "DRIVER_ALERT": "DRIVER_SAFETY",
    "DRIVER_REFRESH_REQUIRED": "DRIVER_SAFETY",
    "DRIVER_RECOVERED": "DRIVER_SAFETY",
    "CRASH": "SYSTEM",
    "CABIN_FIRE": "SYSTEM",
    "CABIN_SMOKE": "SYSTEM",
    "CABIN_INCIDENT": "SYSTEM",
    "EMERGENCY_SIREN": "SYSTEM",
    "OVERLOAD": "PASSENGER_LOAD",
    "VEHICLE_ANOMALY": "VEHICLE_HEALTH",
    "POTHOLE": "ROAD_HAZARD",
    "ROAD_DEFECT": "ROAD_HAZARD",
    "BUS_OFFLINE": "SYSTEM",
    "ETA_SEVERE_DELAY": "ETA_DELAY",
    "CAPACITY_PRESSURE": "PASSENGER_LOAD",
    "OVERCROWDING": "PASSENGER_LOAD",
    "RISK_STATE_CHANGE": "RISK_ESCALATION",
    "RISK_ESCALATION": "RISK_ESCALATION",
    "CRITICAL_RISK": "RISK_ESCALATION",
}

# Correlation window (seconds) — events within this window on same bus/category
# are candidates for correlation into one incident
CORRELATION_WINDOW_S = 600  # 10 minutes

# Deduplication window (seconds) — same event type on same bus within this
# window updates existing incident instead of creating new one
DEDUP_WINDOW_S = 300  # 5 minutes

# Priority thresholds
PRIORITY_THRESHOLDS = {
    "URGENT": {"min_severity": "CRITICAL", "min_events": 2},
    "HIGH": {"min_severity": "HIGH", "min_events": 2},
    "MEDIUM": {"min_severity": "MEDIUM", "min_events": 1},
    "LOW": {"min_severity": "LOW", "min_events": 1},
}

# Severity rank for comparison
SEVERITY_RANK = {s: i for i, s in enumerate(INCIDENT_SEVERITIES)}
PRIORITY_RANK = {p: i for i, p in enumerate(INCIDENT_PRIORITIES)}


# ---------------------------------------------------------------------------
# Incident data model
# ---------------------------------------------------------------------------

class Incident:
    """Represents a meaningful operational incident."""

    def __init__(self, incident_id=None, title="", category="SYSTEM",
                 severity="MEDIUM", priority="MEDIUM", status="OPEN",
                 bus_id=None, route=None, location=None,
                 source="SYSTEM", data_source="SIMULATION",
                 description="", evidence=None, related_event_ids=None,
                 related_alert_ids=None, risk_info=None,
                 created_at=None, updated_at=None,
                 acknowledged_by=None, acknowledged_at=None,
                 resolved_by=None, resolved_at=None,
                 investigation_notes=None, timeline=None):
        self.incident_id = incident_id or f"INC-{str(uuid.uuid4())[:8]}"
        self.title = title
        self.category = category
        self.severity = severity
        self.priority = priority
        self.status = status
        self.bus_id = bus_id
        self.route = route
        self.location = location
        self.source = source
        self.data_source = data_source
        self.description = description
        self.evidence = evidence or []
        self.related_event_ids = related_event_ids or []
        self.related_alert_ids = related_alert_ids or []
        self.risk_info = risk_info or {}
        self.created_at = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.updated_at = updated_at or self.created_at
        self.acknowledged_by = acknowledged_by
        self.acknowledged_at = acknowledged_at
        self.resolved_by = resolved_by
        self.resolved_at = resolved_at
        self.investigation_notes = investigation_notes or []
        self.timeline = timeline or []
        self.event_count = len(self.related_event_ids)

    def to_dict(self):
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "priority": self.priority,
            "status": self.status,
            "bus_id": self.bus_id,
            "route": self.route,
            "location": self.location,
            "source": self.source,
            "data_source": self.data_source,
            "description": self.description,
            "evidence": self.evidence,
            "related_event_ids": self.related_event_ids,
            "related_alert_ids": self.related_alert_ids,
            "risk_info": self.risk_info,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "investigation_notes": self.investigation_notes,
            "timeline": self.timeline,
            "event_count": self.event_count,
        }

    def add_timeline_entry(self, action, operator=None, details=None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action,
            "operator": operator,
            "details": details,
        }
        self.timeline.append(entry)
        self.updated_at = entry["timestamp"]

    def add_evidence(self, evidence_type, value=None, detail=None, source=None, event_id=None):
        self.evidence.append({
            "type": evidence_type,
            "value": value,
            "detail": detail,
            "source": source,
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    def add_event(self, event_id):
        if event_id and event_id not in self.related_event_ids:
            self.related_event_ids.append(event_id)
            self.event_count = len(self.related_event_ids)

    def acknowledge(self, operator):
        if self.status in ("OPEN", "INVESTIGATING"):
            self.status = "ACKNOWLEDGED"
            self.acknowledged_by = operator
            self.acknowledged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.add_timeline_entry("ACKNOWLEDGED", operator)
            return True
        return False

    def investigate(self, operator, notes=None):
        if self.status in ("OPEN", "ACKNOWLEDGED"):
            self.status = "INVESTIGATING"
            if notes:
                self.investigation_notes.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "operator": operator,
                    "notes": notes,
                })
            self.add_timeline_entry("INVESTIGATING", operator, notes)
            return True
        return False

    def resolve(self, operator, notes=None):
        if self.status in ("OPEN", "ACKNOWLEDGED", "INVESTIGATING"):
            self.status = "RESOLVED"
            self.resolved_by = operator
            self.resolved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if notes:
                self.investigation_notes.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "operator": operator,
                    "notes": notes,
                    "action": "RESOLVE",
                })
            self.add_timeline_entry("RESOLVED", operator, notes)
            return True
        return False

    def close(self, operator):
        if self.status == "RESOLVED":
            self.status = "CLOSED"
            self.add_timeline_entry("CLOSED", operator)
            return True
        return False


# ---------------------------------------------------------------------------
# Incident store (in-memory + persistence)
# ---------------------------------------------------------------------------

class IncidentStore:
    """Thread-safe incident storage with correlation and deduplication."""

    def __init__(self):
        self._lock = threading.Lock()
        self._incidents = OrderedDict()  # incident_id -> Incident
        self._bus_incidents = {}  # bus_id -> set of incident_ids
        self._event_incidents = {}  # event_id -> incident_id
        self._last_created = {}  # (bus_id, category) -> timestamp

    def get_incident(self, incident_id):
        with self._lock:
            return self._incidents.get(incident_id)

    def get_incidents(self, status=None, severity=None, priority=None,
                      bus_id=None, category=None, source=None, limit=100):
        with self._lock:
            items = list(self._incidents.values())
        # Apply filters
        if status:
            items = [i for i in items if i.status == status]
        if severity:
            items = [i for i in items if i.severity == severity]
        if priority:
            items = [i for i in items if i.priority == priority]
        if bus_id:
            items = [i for i in items if i.bus_id == bus_id]
        if category:
            items = [i for i in items if i.category == category]
        if source:
            items = [i for i in items if i.source == source]
        # Sort by created_at descending (newest first)
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items[:limit]

    def get_active_incidents(self):
        return self.get_incidents(status="OPEN")

    def get_incidents_for_bus(self, bus_id):
        with self._lock:
            incident_ids = self._bus_incidents.get(bus_id, set())
        return [self._incidents[iid] for iid in incident_ids if iid in self._incidents]

    def get_incident_for_event(self, event_id):
        with self._lock:
            incident_id = self._event_incidents.get(event_id)
        if incident_id:
            return self._incidents.get(incident_id)
        return None

    def _add_incident(self, incident):
        with self._lock:
            self._incidents[incident.incident_id] = incident
            # Index by bus
            if incident.bus_id:
                if incident.bus_id not in self._bus_incidents:
                    self._bus_incidents[incident.bus_id] = set()
                self._bus_incidents[incident.bus_id].add(incident.incident_id)
            # Index events
            for eid in incident.related_event_ids:
                self._event_incidents[eid] = incident.incident_id
            # Track last created for dedup
            key = (incident.bus_id, incident.category)
            self._last_created[key] = time.time()
        # Persist
        persistence.save_incident(incident.to_dict())
        return incident

    def _update_incident(self, incident):
        persistence.save_incident(incident.to_dict())

    def acknowledge_incident(self, incident_id, operator):
        incident = self.get_incident(incident_id)
        if incident and incident.acknowledge(operator):
            self._update_incident(incident)
            return incident
        return None

    def investigate_incident(self, incident_id, operator, notes=None):
        incident = self.get_incident(incident_id)
        if incident and incident.investigate(operator, notes):
            self._update_incident(incident)
            return incident
        return None

    def resolve_incident(self, incident_id, operator, notes=None):
        incident = self.get_incident(incident_id)
        if incident and incident.resolve(operator, notes):
            self._update_incident(incident)
            return incident
        return None

    def close_incident(self, incident_id, operator):
        incident = self.get_incident(incident_id)
        if incident and incident.close(operator):
            self._update_incident(incident)
            return incident
        return None

    def _check_dedup(self, bus_id, category):
        """Check if we should deduplicate (update existing incident)."""
        now = time.time()
        key = (bus_id, category)
        with self._lock:
            last = self._last_created.get(key, 0)
        if now - last < DEDUP_WINDOW_S:
            # Find the most recent incident for this bus/category
            incidents = self.get_incidents(bus_id=bus_id, category=category, status="OPEN", limit=1)
            if incidents:
                return incidents[0]
        return None

    def _check_correlation(self, bus_id, category, event_timestamp):
        """Check if we should correlate with an existing incident."""
        now = time.time()
        try:
            event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            event_time = now

        # Find open incidents for this bus/category within correlation window
        incidents = self.get_incidents(bus_id=bus_id, category=category, status="OPEN", limit=5)
        for inc in incidents:
            try:
                inc_time = datetime.fromisoformat(inc.created_at.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                continue
            if event_time - inc_time < CORRELATION_WINDOW_S:
                return inc
        return None


# Global incident store
incident_store = IncidentStore()


# ---------------------------------------------------------------------------
# Incident creation helpers
# ---------------------------------------------------------------------------

def _determine_severity(event):
    """Determine incident severity from event."""
    event_severity = (event.get("severity") or "INFO").upper()
    return EVENT_TO_INCIDENT_SEVERITY.get(event_severity, "MEDIUM")


def _determine_source(event):
    """Determine incident source from event type."""
    event_type = (event.get("event_type") or "").upper()
    return EVENT_TYPE_TO_SOURCE.get(event_type, "SYSTEM")


def _determine_category(event):
    """Determine incident category from event type."""
    event_type = (event.get("event_type") or "").upper()
    return EVENT_TYPE_TO_CATEGORY.get(event_type, "SYSTEM")


def _determine_priority(severity, event_count, risk_level=None):
    """Determine incident priority from severity and context."""
    severity_rank = SEVERITY_RANK.get(severity, 0)

    # Critical severity with multiple events = URGENT
    if severity == "CRITICAL" and event_count >= 2:
        return "URGENT"
    # High severity with multiple events = HIGH
    if severity == "HIGH" and event_count >= 2:
        return "HIGH"
    # CRITICAL risk escalation = HIGH priority
    if risk_level == "CRITICAL":
        return "HIGH"
    # High severity = MEDIUM priority
    if severity_rank >= SEVERITY_RANK.get("HIGH", 0):
        return "MEDIUM"
    # Default
    return "LOW"


def _build_incident_title(event, category, bus_id):
    """Build a human-readable incident title."""
    event_type = (event.get("event_type") or "Unknown").replace("_", " ").title()
    return f"{event_type} — Bus {bus_id}"


def _build_incident_description(event, category, evidence):
    """Build a human-readable incident description."""
    event_type = (event.get("event_type") or "Unknown").replace("_", " ").lower()
    severity = (event.get("severity") or "INFO").upper()
    description = f"{severity} severity {event_type} detected"
    if evidence:
        description += f" with {len(evidence)} evidence item(s)"
    return description


def _gather_event_evidence(event, bus=None, risk_info=None):
    """Gather evidence from an event."""
    evidence = []

    # Event evidence
    evidence.append({
        "type": "triggering_event",
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "severity": event.get("severity"),
        "timestamp": event.get("timestamp"),
        "detail": f"Event {event.get('event_type')} at {event.get('timestamp')}",
    })

    # Additional event data
    extra = event.get("additional_data") or {}
    if extra:
        evidence.append({
            "type": "event_details",
            "value": extra,
            "detail": str(extra)[:200],
        })

    # Bus context
    if bus:
        driver = bus.get("driver") or {}
        if driver.get("state") in ("DROWSY", "ATTENTION"):
            evidence.append({
                "type": "driver_state",
                "value": driver.get("state"),
                "detail": f"Driver {driver.get('state').lower()}",
            })

        vehicle = bus.get("vehicle") or {}
        if vehicle.get("health") in ("WARNING", "INSPECTION REQUIRED"):
            evidence.append({
                "type": "vehicle_health",
                "value": vehicle.get("health"),
                "detail": vehicle.get("anomaly", "Vehicle anomaly"),
            })

    # Risk context
    if risk_info:
        risk_level = risk_info.get("risk_level")
        if risk_level in ("HIGH", "CRITICAL"):
            evidence.append({
                "type": "risk_context",
                "value": risk_level,
                "risk_score": risk_info.get("risk_score"),
                "detail": f"Risk level {risk_level} (score {risk_info.get('risk_score', 0)})",
            })

    return evidence


def _classify_data_source(event, bus=None):
    """Classify the data source (LIVE/SIMULATION/HEURISTIC/MODEL/UNKNOWN)."""
    # Check event data source
    ds = event.get("data_source")
    if ds:
        return ds.upper()

    # Check simulation flag
    if event.get("simulation") is False:
        return "LIVE"
    if event.get("simulation") is True:
        return "SIMULATION"

    # Check bus data source
    if bus:
        if bus.get("_live") or bus.get("data_source") == "live":
            return "LIVE"
        if bus.get("simulation"):
            return "SIMULATION"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Public API: process event into incident
# ---------------------------------------------------------------------------

def process_event(event, bus=None, risk_info=None):
    """Process an event and potentially create/update an incident.

    Returns:
        dict with:
        - action: "created" | "updated" | "deduplicated" | "ignored"
        - incident: Incident object (or None if ignored)
        - reason: explanation string
    """
    if not isinstance(event, dict):
        return {"action": "ignored", "incident": None, "reason": "Invalid event"}

    event_type = (event.get("event_type") or "").upper()
    if event_type not in INCIDENT_TRIGGER_TYPES:
        return {"action": "ignored", "incident": None, "reason": f"Event type {event_type} not an incident trigger"}

    event_id = event.get("event_id")
    bus_id = event.get("bus_id")
    if not bus_id:
        return {"action": "ignored", "incident": None, "reason": "No bus_id"}

    category = _determine_category(event)
    severity = _determine_severity(event)
    source = _determine_source(event)
    data_source = _classify_data_source(event, bus)
    timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Check deduplication — same bus/category within dedup window
    existing = incident_store._check_dedup(bus_id, category)
    if existing:
        # Update existing incident with new evidence
        existing.add_event(event_id)
        existing.add_evidence(
            "subsequent_event",
            value=event_type,
            detail=f"Additional {event_type.lower().replace('_', ' ')} event",
            source=source,
            event_id=event_id,
        )
        existing.severity = max(existing.severity, severity, key=lambda s: SEVERITY_RANK.get(s, 0))
        existing.priority = _determine_priority(existing.severity, existing.event_count,
                                                 risk_info.get("risk_level") if risk_info else None)
        existing.add_timeline_entry("EVENT_ADDED", details=f"Event {event_id} added")
        incident_store._update_incident(existing)
        return {"action": "deduplicated", "incident": existing,
                "reason": f"Event {event_id} added to existing incident {existing.incident_id}"}

    # Check correlation — related events within correlation window
    correlated = incident_store._check_correlation(bus_id, category, timestamp)
    if correlated:
        correlated.add_event(event_id)
        correlated.add_evidence(
            "correlated_event",
            value=event_type,
            detail=f"Correlated {event_type.lower().replace('_', ' ')} event",
            source=source,
            event_id=event_id,
        )
        correlated.severity = max(correlated.severity, severity, key=lambda s: SEVERITY_RANK.get(s, 0))
        correlated.priority = _determine_priority(correlated.severity, correlated.event_count,
                                                   risk_info.get("risk_level") if risk_info else None)
        correlated.add_timeline_entry("EVENT_CORRELATED", details=f"Event {event_id} correlated")
        incident_store._update_incident(correlated)
        return {"action": "updated", "incident": correlated,
                "reason": f"Event {event_id} correlated with incident {correlated.incident_id}"}

    # Create new incident
    evidence = _gather_event_evidence(event, bus, risk_info)
    title = _build_incident_title(event, category, bus_id)
    description = _build_incident_description(event, category, evidence)
    priority = _determine_priority(severity, 1, risk_info.get("risk_level") if risk_info else None)

    # Get route from bus
    route = None
    if bus:
        route = bus.get("route") or bus.get("route_code")

    incident = Incident(
        title=title,
        category=category,
        severity=severity,
        priority=priority,
        bus_id=bus_id,
        route=route,
        source=source,
        data_source=data_source,
        description=description,
        evidence=evidence,
        related_event_ids=[event_id],
        risk_info=risk_info or {},
    )
    incident.add_timeline_entry("CREATED", details=f"Incident created from event {event_id}")

    incident_store._add_incident(incident)
    return {"action": "created", "incident": incident,
            "reason": f"New incident {incident.incident_id} created from event {event_id}"}


def process_events_batch(events, buses=None, risk_info_map=None):
    """Process a batch of events into incidents.

    Args:
        events: list of event dicts
        buses: dict of bus_id -> bus state (optional)
        risk_info_map: dict of bus_id -> risk info (optional)

    Returns:
        dict with stats: created, updated, deduplicated, ignored
    """
    buses = buses or {}
    risk_info_map = risk_info_map or {}
    stats = {"created": 0, "updated": 0, "deduplicated": 0, "ignored": 0}

    for event in events:
        bus_id = event.get("bus_id")
        bus = buses.get(bus_id)
        risk_info = risk_info_map.get(bus_id)
        result = process_event(event, bus=bus, risk_info=risk_info)
        stats[result["action"]] = stats.get(result["action"], 0) + 1

    return stats


# ---------------------------------------------------------------------------
# Incident summary / analytics
# ---------------------------------------------------------------------------

def get_incident_summary():
    """Get a summary of all incidents."""
    all_incidents = incident_store.get_incidents(limit=10000)

    summary = {
        "total": len(all_incidents),
        "by_status": {},
        "by_severity": {},
        "by_priority": {},
        "by_category": {},
        "by_source": {},
        "active_count": 0,
        "critical_count": 0,
        "high_priority_count": 0,
    }

    for inc in all_incidents:
        # By status
        summary["by_status"][inc.status] = summary["by_status"].get(inc.status, 0) + 1
        # By severity
        summary["by_severity"][inc.severity] = summary["by_severity"].get(inc.severity, 0) + 1
        # By priority
        summary["by_priority"][inc.priority] = summary["by_priority"].get(inc.priority, 0) + 1
        # By category
        summary["by_category"][inc.category] = summary["by_category"].get(inc.category, 0) + 1
        # By source
        summary["by_source"][inc.source] = summary["by_source"].get(inc.source, 0) + 1
        # Active
        if inc.status in ("OPEN", "INVESTIGATING"):
            summary["active_count"] += 1
        # Critical
        if inc.severity == "CRITICAL":
            summary["critical_count"] += 1
        # High priority
        if inc.priority in ("HIGH", "URGENT"):
            summary["high_priority_count"] += 1

    return summary


def get_incident_for_event_id(event_id):
    """Get the incident associated with an event."""
    return incident_store.get_incident_for_event(event_id)


def get_bus_incidents(bus_id, limit=20):
    """Get incidents for a specific bus."""
    return incident_store.get_incidents_for_bus(bus_id)[:limit]


# ---------------------------------------------------------------------------
# Loading from persistence on startup
# ---------------------------------------------------------------------------

def load_incidents_from_persistence():
    """Load persisted incidents into memory on startup."""
    incidents = persistence.load_incidents()
    loaded = 0
    for inc_data in incidents:
        try:
            inc = Incident(
                incident_id=inc_data.get("incident_id"),
                title=inc_data.get("title", ""),
                category=inc_data.get("category", "SYSTEM"),
                severity=inc_data.get("severity", "MEDIUM"),
                priority=inc_data.get("priority", "MEDIUM"),
                status=inc_data.get("status", "OPEN"),
                bus_id=inc_data.get("bus_id"),
                route=inc_data.get("route"),
                location=inc_data.get("location"),
                source=inc_data.get("source", "SYSTEM"),
                data_source=inc_data.get("data_source", "SIMULATION"),
                description=inc_data.get("description", ""),
                evidence=inc_data.get("evidence", []),
                related_event_ids=inc_data.get("related_event_ids", []),
                related_alert_ids=inc_data.get("related_alert_ids", []),
                risk_info=inc_data.get("risk_info", {}),
                created_at=inc_data.get("created_at"),
                updated_at=inc_data.get("updated_at"),
                acknowledged_by=inc_data.get("acknowledged_by"),
                acknowledged_at=inc_data.get("acknowledged_at"),
                resolved_by=inc_data.get("resolved_by"),
                resolved_at=inc_data.get("resolved_at"),
                investigation_notes=inc_data.get("investigation_notes", []),
                timeline=inc_data.get("timeline", []),
            )
            incident_store._add_incident.__func__(incident_store, inc)
            loaded += 1
        except Exception as e:
            print(f"[incident-intelligence] Failed to load incident: {e}")
    print(f"[incident-intelligence] Loaded {loaded} incidents from persistence")
    return loaded


if __name__ == "__main__":
    # Quick self-test
    test_event = {
        "event_id": "EVT-TEST-001",
        "event_type": "DRIVER_DROWSINESS",
        "bus_id": "BUS-001",
        "severity": "WARNING",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "simulation": True,
    }
    result = process_event(test_event, bus={"bus_id": "BUS-001", "driver": {"state": "DROWSY"}})
    print(f"Action: {result['action']}")
    print(f"Incident: {result['incident'].incident_id if result['incident'] else None}")
    print(f"Reason: {result['reason']}")
