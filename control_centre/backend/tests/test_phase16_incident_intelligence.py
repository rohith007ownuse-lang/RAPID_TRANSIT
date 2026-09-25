"""
test_phase16_incident_intelligence.py
Comprehensive tests for Phase 16: Incident Intelligence, Correlation & Operational Response.

Covers:
  - Incident data model (create, serialize, lifecycle methods)
  - Incident correlation engine (deduplication, correlation)
  - Incident priority/severity calculation
  - Incident persistence (save/load)
  - Incident API endpoints (Flask)
  - Edge cases and error handling
"""

import json
import time
from datetime import datetime, timezone

import pytest
import persistence

import incident_intelligence
from incident_intelligence import (
    Incident, IncidentStore, incident_store,
    process_event, process_events_batch,
    get_incident_summary, get_incident_for_event_id,
    INCIDENT_SEVERITIES, INCIDENT_PRIORITIES, INCIDENT_STATUSES,
    INCIDENT_TRIGGER_TYPES, CORRELATION_WINDOW_S, DEDUP_WINDOW_S,
    SEVERITY_RANK, PRIORITY_RANK,
)
from data_store import store


# ---------------------------------------------------------------------------
# Incident data model tests
# ---------------------------------------------------------------------------

class TestIncidentModel:
    """Tests for the Incident class."""

    def test_create_default_incident(self):
        inc = Incident()
        assert inc.incident_id.startswith("INC-")
        assert inc.status == "OPEN"
        assert inc.severity == "MEDIUM"
        assert inc.priority == "MEDIUM"
        assert inc.category == "SYSTEM"
        assert inc.related_event_ids == []
        assert inc.evidence == []
        assert inc.timeline == []

    def test_create_with_parameters(self):
        inc = Incident(
            incident_id="INC-TEST-001",
            title="Test Incident",
            category="DRIVER_SAFETY",
            severity="HIGH",
            priority="URGENT",
            bus_id="BUS-001",
            route="5A",
        )
        assert inc.incident_id == "INC-TEST-001"
        assert inc.title == "Test Incident"
        assert inc.category == "DRIVER_SAFETY"
        assert inc.severity == "HIGH"
        assert inc.priority == "URGENT"
        assert inc.bus_id == "BUS-001"
        assert inc.route == "5A"

    def test_to_dict(self):
        inc = Incident(incident_id="INC-001", title="Test")
        d = inc.to_dict()
        assert d["incident_id"] == "INC-001"
        assert d["title"] == "Test"
        assert d["status"] == "OPEN"
        assert d["event_count"] == 0

    def test_add_timeline_entry(self):
        inc = Incident()
        inc.add_timeline_entry("CREATED", operator="op1", details="test")
        assert len(inc.timeline) == 1
        assert inc.timeline[0]["action"] == "CREATED"
        assert inc.timeline[0]["operator"] == "op1"
        assert inc.updated_at is not None

    def test_add_evidence(self):
        inc = Incident()
        inc.add_evidence("triggering_event", value="CRASH", detail="Crash detected", event_id="EVT-001")
        assert len(inc.evidence) == 1
        assert inc.evidence[0]["type"] == "triggering_event"
        assert inc.evidence[0]["event_id"] == "EVT-001"

    def test_add_event(self):
        inc = Incident()
        inc.add_event("EVT-001")
        assert "EVT-001" in inc.related_event_ids
        assert inc.event_count == 1
        # Adding same event again should not duplicate
        inc.add_event("EVT-001")
        assert inc.event_count == 1
        # Adding different event
        inc.add_event("EVT-002")
        assert inc.event_count == 2

    def test_acknowledge_incident(self):
        inc = Incident(status="OPEN")
        assert inc.acknowledge("op1") is True
        assert inc.status == "ACKNOWLEDGED"
        assert inc.acknowledged_by == "op1"
        assert inc.acknowledged_at is not None
        assert len(inc.timeline) == 1

    def test_acknowledge_investigating(self):
        inc = Incident(status="INVESTIGATING")
        assert inc.acknowledge("op1") is True
        assert inc.status == "ACKNOWLEDGED"

    def test_acknowledge_resolved_fails(self):
        inc = Incident(status="RESOLVED")
        assert inc.acknowledge("op1") is False
        assert inc.status == "RESOLVED"

    def test_investigate_incident(self):
        inc = Incident(status="OPEN")
        assert inc.investigate("op1", notes="Looking into it") is True
        assert inc.status == "INVESTIGATING"
        assert len(inc.investigation_notes) == 1
        assert inc.investigation_notes[0]["notes"] == "Looking into it"

    def test_investigate_from_acknowledged(self):
        inc = Incident(status="ACKNOWLEDGED")
        assert inc.investigate("op1") is True
        assert inc.status == "INVESTIGATING"

    def test_investigate_closed_fails(self):
        inc = Incident(status="CLOSED")
        assert inc.investigate("op1") is False

    def test_resolve_incident(self):
        inc = Incident(status="OPEN")
        assert inc.resolve("sup1", notes="Fixed") is True
        assert inc.status == "RESOLVED"
        assert inc.resolved_by == "sup1"
        assert inc.resolved_at is not None

    def test_resolve_from_investigating(self):
        inc = Incident(status="INVESTIGATING")
        assert inc.resolve("sup1") is True
        assert inc.status == "RESOLVED"

    def test_resolve_closed_fails(self):
        inc = Incident(status="CLOSED")
        assert inc.resolve("sup1") is False

    def test_close_incident(self):
        inc = Incident(status="RESOLVED")
        assert inc.close("sup1") is True
        assert inc.status == "CLOSED"
        assert len(inc.timeline) == 1

    def test_close_from_open_fails(self):
        inc = Incident(status="OPEN")
        assert inc.close("sup1") is False


# ---------------------------------------------------------------------------
# Incident store tests
# ---------------------------------------------------------------------------

class TestIncidentStore:
    """Tests for the IncidentStore class."""

    def setup_method(self):
        self.store = IncidentStore()

    def test_add_and_get_incident(self):
        inc = Incident(incident_id="INC-001", bus_id="BUS-001", category="SYSTEM")
        self.store._add_incident(inc)
        retrieved = self.store.get_incident("INC-001")
        assert retrieved is not None
        assert retrieved.incident_id == "INC-001"

    def test_get_incidents_with_filters(self):
        inc1 = Incident(incident_id="INC-001", severity="HIGH", status="OPEN")
        inc2 = Incident(incident_id="INC-002", severity="LOW", status="RESOLVED")
        self.store._add_incident(inc1)
        self.store._add_incident(inc2)

        # Filter by severity
        high = self.store.get_incidents(severity="HIGH")
        assert len(high) == 1
        assert high[0].incident_id == "INC-001"

        # Filter by status
        resolved = self.store.get_incidents(status="RESOLVED")
        assert len(resolved) == 1
        assert resolved[0].incident_id == "INC-002"

    def test_get_active_incidents(self):
        inc1 = Incident(incident_id="INC-001", status="OPEN")
        inc2 = Incident(incident_id="INC-002", status="RESOLVED")
        self.store._add_incident(inc1)
        self.store._add_incident(inc2)
        active = self.store.get_active_incidents()
        assert len(active) == 1
        assert active[0].incident_id == "INC-001"

    def test_get_incidents_for_bus(self):
        inc1 = Incident(incident_id="INC-001", bus_id="BUS-001")
        inc2 = Incident(incident_id="INC-002", bus_id="BUS-002")
        inc3 = Incident(incident_id="INC-003", bus_id="BUS-001")
        self.store._add_incident(inc1)
        self.store._add_incident(inc2)
        self.store._add_incident(inc3)
        bus_incidents = self.store.get_incidents_for_bus("BUS-001")
        assert len(bus_incidents) == 2

    def test_get_incident_for_event(self):
        inc = Incident(incident_id="INC-001", related_event_ids=["EVT-001", "EVT-002"])
        self.store._add_incident(inc)
        found = self.store.get_incident_for_event("EVT-001")
        assert found is not None
        assert found.incident_id == "INC-001"
        not_found = self.store.get_incident_for_event("EVT-999")
        assert not_found is None

    def test_acknowledge_incident(self):
        inc = Incident(incident_id="INC-001", status="OPEN")
        self.store._add_incident(inc)
        result = self.store.acknowledge_incident("INC-001", "op1")
        assert result is not None
        assert result.status == "ACKNOWLEDGED"

    def test_investigate_incident(self):
        inc = Incident(incident_id="INC-001", status="OPEN")
        self.store._add_incident(inc)
        result = self.store.investigate_incident("INC-001", "op1", notes="Checking")
        assert result is not None
        assert result.status == "INVESTIGATING"

    def test_resolve_incident(self):
        inc = Incident(incident_id="INC-001", status="OPEN")
        self.store._add_incident(inc)
        result = self.store.resolve_incident("INC-001", "sup1")
        assert result is not None
        assert result.status == "RESOLVED"

    def test_close_incident(self):
        inc = Incident(incident_id="INC-001", status="RESOLVED")
        self.store._add_incident(inc)
        result = self.store.close_incident("INC-001", "sup1")
        assert result is not None
        assert result.status == "CLOSED"


# ---------------------------------------------------------------------------
# Event processing tests
# ---------------------------------------------------------------------------

class TestEventProcessing:
    """Tests for processing events into incidents."""

    def setup_method(self):
        # Clear global incident store between tests
        with incident_store._lock:
            incident_store._incidents.clear()
            incident_store._bus_incidents.clear()
            incident_store._event_incidents.clear()
            incident_store._last_created.clear()

    def test_process_triggering_event_creates_incident(self):
        event = {
            "event_id": "EVT-001",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": "BUS-001",
            "severity": "WARNING",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        result = process_event(event, bus={"bus_id": "BUS-001", "driver": {"state": "DROWSY"}})
        assert result["action"] == "created"
        assert result["incident"] is not None
        assert result["incident"].category == "DRIVER_SAFETY"
        assert result["incident"].bus_id == "BUS-001"

    def test_process_non_triggering_event_ignored(self):
        event = {
            "event_id": "EVT-001",
            "event_type": "HEARTBEAT",
            "bus_id": "BUS-001",
            "severity": "INFO",
        }
        result = process_event(event)
        assert result["action"] == "ignored"

    def test_process_event_without_bus_id_ignored(self):
        event = {
            "event_id": "EVT-001",
            "event_type": "DRIVER_DROWSINESS",
            "severity": "WARNING",
        }
        result = process_event(event)
        assert result["action"] == "ignored"

    def test_process_event_no_bus_id(self):
        event = {
            "event_id": "EVT-001",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": None,
            "severity": "WARNING",
        }
        result = process_event(event)
        assert result["action"] == "ignored"

    def test_deduplication(self):
        event1 = {
            "event_id": "EVT-001",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": "BUS-001",
            "severity": "WARNING",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        event2 = {
            "event_id": "EVT-002",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": "BUS-001",
            "severity": "WARNING",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        result1 = process_event(event1)
        result2 = process_event(event2)
        assert result1["action"] == "created"
        assert result2["action"] == "deduplicated"
        assert result2["incident"].incident_id == result1["incident"].incident_id

    def test_correlation(self):
        # Create first event
        event1 = {
            "event_id": "EVT-001",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": "BUS-001",
            "severity": "WARNING",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        result1 = process_event(event1)

        # Wait a bit and create different type event (should correlate)
        time.sleep(0.1)
        event2 = {
            "event_id": "EVT-002",
            "event_type": "VEHICLE_ANOMALY",
            "bus_id": "BUS-001",
            "severity": "INFO",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        result2 = process_event(event2)
        # Different category won't correlate (different category)
        assert result2["action"] == "created"

    def test_severity_escalation_on_dedup(self):
        event1 = {
            "event_id": "EVT-001",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": "BUS-001",
            "severity": "INFO",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        event2 = {
            "event_id": "EVT-002",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": "BUS-001",
            "severity": "CRITICAL",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        result1 = process_event(event1)
        result2 = process_event(event2)
        # After dedup, the incident should have escalated to CRITICAL
        assert result2["action"] == "deduplicated"
        assert result2["incident"].severity == "CRITICAL"
        # Both results reference the same incident object
        assert result1["incident"].incident_id == result2["incident"].incident_id

    def test_priority_calculation_urgent(self):
        event1 = {
            "event_id": "EVT-001",
            "event_type": "CRASH",
            "bus_id": "BUS-001",
            "severity": "CRITICAL",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        event2 = {
            "event_id": "EVT-002",
            "event_type": "CRASH",
            "bus_id": "BUS-001",
            "severity": "CRITICAL",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        result1 = process_event(event1)
        result2 = process_event(event2)
        assert result2["incident"].priority == "URGENT"

    def test_process_events_batch(self):
        events = [
            {"event_id": "EVT-001", "event_type": "CRASH", "bus_id": "BUS-001", "severity": "CRITICAL"},
            {"event_id": "EVT-002", "event_type": "HEARTBEAT", "bus_id": "BUS-001", "severity": "INFO"},
            {"event_id": "EVT-003", "event_type": "DRIVER_DROWSINESS", "bus_id": "BUS-002", "severity": "WARNING"},
        ]
        stats = process_events_batch(events)
        assert stats["created"] >= 2  # CRASH and DROWSINESS
        assert stats["ignored"] >= 1  # HEARTBEAT

    def test_data_source_classification_live(self):
        event = {
            "event_id": "EVT-001",
            "event_type": "CRASH",
            "bus_id": "BUS-001",
            "severity": "CRITICAL",
            "simulation": False,
        }
        result = process_event(event, bus={"bus_id": "BUS-001", "_live": True})
        assert result["incident"].data_source == "LIVE"

    def test_data_source_classification_simulation(self):
        event = {
            "event_id": "EVT-001",
            "event_type": "CRASH",
            "bus_id": "BUS-001",
            "severity": "CRITICAL",
            "simulation": True,
        }
        result = process_event(event)
        assert result["incident"].data_source == "SIMULATION"


# ---------------------------------------------------------------------------
# Incident summary tests
# ---------------------------------------------------------------------------

class TestIncidentSummary:
    """Tests for incident summary/analytics."""

    def setup_method(self):
        # Clear global incident store between tests
        with incident_store._lock:
            incident_store._incidents.clear()
            incident_store._bus_incidents.clear()
            incident_store._event_incidents.clear()
            incident_store._last_created.clear()

    def test_empty_summary(self):
        summary = get_incident_summary()
        assert summary["total"] == 0
        assert summary["active_count"] == 0
        assert summary["critical_count"] == 0

    def test_summary_with_incidents(self):
        inc1 = Incident(severity="CRITICAL", status="OPEN", priority="URGENT", category="SYSTEM")
        inc2 = Incident(severity="LOW", status="RESOLVED", priority="LOW", category="DRIVER_SAFETY")
        incident_store._add_incident(inc1)
        incident_store._add_incident(inc2)

        summary = get_incident_summary()
        assert summary["total"] == 2
        assert summary["active_count"] == 1
        assert summary["critical_count"] == 1
        assert summary["by_severity"]["CRITICAL"] == 1
        assert summary["by_severity"]["LOW"] == 1
        assert summary["by_status"]["OPEN"] == 1
        assert summary["by_status"]["RESOLVED"] == 1


# ---------------------------------------------------------------------------
# Incident persistence tests
# ---------------------------------------------------------------------------

class TestIncidentPersistence:
    """Tests for incident persistence (save/load)."""

    def test_save_and_load_incident(self):
        inc = Incident(
            incident_id="INC-PERSIST-001",
            title="Persist Test",
            category="DRIVER_SAFETY",
            severity="HIGH",
            bus_id="BUS-001",
            related_event_ids=["EVT-001"],
        )
        persistence.save_incident(inc.to_dict())
        loaded = persistence.load_incident("INC-PERSIST-001")
        assert loaded is not None
        assert loaded["incident_id"] == "INC-PERSIST-001"
        assert loaded["title"] == "Persist Test"
        assert loaded["severity"] == "HIGH"

    def test_load_all_incidents(self):
        inc1 = Incident(incident_id="INC-001", title="First")
        inc2 = Incident(incident_id="INC-002", title="Second")
        persistence.save_incident(inc1.to_dict())
        persistence.save_incident(inc2.to_dict())
        loaded = persistence.load_incidents()
        assert len(loaded) == 2

    def test_load_incidents_for_bus(self):
        inc1 = Incident(incident_id="INC-001", bus_id="BUS-001")
        inc2 = Incident(incident_id="INC-002", bus_id="BUS-002")
        inc3 = Incident(incident_id="INC-003", bus_id="BUS-001")
        persistence.save_incident(inc1.to_dict())
        persistence.save_incident(inc2.to_dict())
        persistence.save_incident(inc3.to_dict())
        loaded = persistence.load_incidents_for_bus("BUS-001")
        assert len(loaded) == 2

    def test_incident_survives_truncate(self):
        inc = Incident(incident_id="INC-001", title="Survive")
        persistence.save_incident(inc.to_dict())
        persistence.truncate()
        # Re-init and check
        persistence.init_db(force=True)
        loaded = persistence.load_incident("INC-001")
        assert loaded is None  # Truncated

    def test_incident_fields_persisted(self):
        inc = Incident(
            incident_id="INC-FIELDS-001",
            title="Full Fields",
            category="VEHICLE_HEALTH",
            severity="MEDIUM",
            priority="HIGH",
            status="INVESTIGATING",
            bus_id="BUS-001",
            route="5A",
            source="VEHICLE_HEALTH",
            data_source="LIVE",
            description="Test description",
            evidence=[{"type": "test", "value": "data"}],
            related_event_ids=["EVT-001", "EVT-002"],
            risk_info={"risk_score": 0.75, "risk_level": "HIGH"},
            acknowledged_by="op1",
            resolved_by="sup1",
        )
        persistence.save_incident(inc.to_dict())
        loaded = persistence.load_incident("INC-FIELDS-001")
        assert loaded["title"] == "Full Fields"
        assert loaded["category"] == "VEHICLE_HEALTH"
        assert loaded["priority"] == "HIGH"
        assert loaded["bus_id"] == "BUS-001"
        assert loaded["route"] == "5A"
        assert loaded["acknowledged_by"] == "op1"
        assert loaded["resolved_by"] == "sup1"


# ---------------------------------------------------------------------------
# Flask API endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from server import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    return resp.get_json()["token"]


class TestIncidentAPI:
    """Tests for incident REST API endpoints."""

    def setup_method(self):
        # Clear global incident store between tests
        with incident_store._lock:
            incident_store._incidents.clear()
            incident_store._bus_incidents.clear()
            incident_store._event_incidents.clear()
            incident_store._last_created.clear()

    def test_list_incidents_empty(self, client):
        resp = client.get("/api/incidents")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["incidents"] == []
        assert data["count"] == 0

    def test_list_incidents_with_data(self, client):
        inc = Incident(incident_id="INC-API-001", title="API Test", bus_id="BUS-001")
        incident_store._add_incident(inc)
        resp = client.get("/api/incidents")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 1
        assert data["incidents"][0]["incident_id"] == "INC-API-001"

    def test_list_incidents_with_filters(self, client):
        inc1 = Incident(incident_id="INC-001", severity="HIGH", status="OPEN")
        inc2 = Incident(incident_id="INC-002", severity="LOW", status="RESOLVED")
        incident_store._add_incident(inc1)
        incident_store._add_incident(inc2)

        resp = client.get("/api/incidents?severity=HIGH")
        data = resp.get_json()
        assert data["count"] == 1

        resp = client.get("/api/incidents?status=RESOLVED")
        data = resp.get_json()
        assert data["count"] == 1

    def test_get_active_incidents(self, client):
        inc1 = Incident(incident_id="INC-001", status="OPEN")
        inc2 = Incident(incident_id="INC-002", status="RESOLVED")
        incident_store._add_incident(inc1)
        incident_store._add_incident(inc2)
        resp = client.get("/api/incidents/active")
        data = resp.get_json()
        assert data["count"] == 1

    def test_get_incident_summary(self, client):
        inc = Incident(incident_id="INC-001", severity="CRITICAL", status="OPEN")
        incident_store._add_incident(inc)
        resp = client.get("/api/incidents/summary")
        data = resp.get_json()
        assert data["summary"]["total"] == 1
        assert data["summary"]["critical_count"] == 1

    def test_get_single_incident(self, client):
        inc = Incident(incident_id="INC-SINGLE-001", title="Single Test")
        incident_store._add_incident(inc)
        resp = client.get("/api/incidents/INC-SINGLE-001")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["incident"]["incident_id"] == "INC-SINGLE-001"

    def test_get_single_incident_not_found(self, client):
        resp = client.get("/api/incidents/INC-NONEXISTENT")
        assert resp.status_code == 404

    def test_acknowledge_incident(self, client):
        token = _login(client)
        inc = Incident(incident_id="INC-ACK-001", status="OPEN")
        incident_store._add_incident(inc)
        resp = client.post("/api/incidents/INC-ACK-001/acknowledge",
                          json={"operator": "admin"},
                          headers=_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["incident"]["status"] == "ACKNOWLEDGED"

    def test_incident_by_bus(self, client):
        inc1 = Incident(incident_id="INC-001", bus_id="BUS-001")
        inc2 = Incident(incident_id="INC-002", bus_id="BUS-002")
        incident_store._add_incident(inc1)
        incident_store._add_incident(inc2)
        resp = client.get("/api/incidents/by-bus/BUS-001")
        data = resp.get_json()
        assert data["count"] == 1

    def test_incident_by_event(self, client):
        inc = Incident(incident_id="INC-EVT-001", related_event_ids=["EVT-001"])
        incident_store._add_incident(inc)
        resp = client.get("/api/incidents/by-event/EVT-001")
        data = resp.get_json()
        assert data["found"] is True
        assert data["incident"]["incident_id"] == "INC-EVT-001"

    def test_incident_by_event_not_found(self, client):
        resp = client.get("/api/incidents/by-event/EVT-NONEXISTENT")
        data = resp.get_json()
        assert data["found"] is False


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_invalid_event_type(self):
        event = {"event_id": "EVT-001", "event_type": "INVALID_TYPE", "bus_id": "BUS-001"}
        result = process_event(event)
        assert result["action"] == "ignored"

    def test_none_event(self):
        result = process_event(None)
        assert result["action"] == "ignored"

    def test_empty_event(self):
        result = process_event({})
        assert result["action"] == "ignored"

    def test_incident_id_uniqueness(self):
        inc1 = Incident()
        inc2 = Incident()
        assert inc1.incident_id != inc2.incident_id

    def test_severity_comparison(self):
        assert SEVERITY_RANK["CRITICAL"] > SEVERITY_RANK["HIGH"]
        assert SEVERITY_RANK["HIGH"] > SEVERITY_RANK["MEDIUM"]
        assert SEVERITY_RANK["MEDIUM"] > SEVERITY_RANK["LOW"]
        assert SEVERITY_RANK["LOW"] > SEVERITY_RANK["INFO"]

    def test_priority_comparison(self):
        assert PRIORITY_RANK["URGENT"] > PRIORITY_RANK["HIGH"]
        assert PRIORITY_RANK["HIGH"] > PRIORITY_RANK["MEDIUM"]
        assert PRIORITY_RANK["MEDIUM"] > PRIORITY_RANK["LOW"]

    def test_incident_constants(self):
        assert "CRITICAL" in INCIDENT_SEVERITIES
        assert "URGENT" in INCIDENT_PRIORITIES
        assert "OPEN" in INCIDENT_STATUSES
        assert "DRIVER_DROWSINESS" in INCIDENT_TRIGGER_TYPES
        assert "CRASH" in INCIDENT_TRIGGER_TYPES
