"""
test_auto_assign.py
Auto-assignment of CRITICAL incidents to operators.

Covers:
  - CRITICAL incidents auto-assign on creation; lower severities do not
  - Roster from registered users (operators, then supervisors, then fallback)
  - Response deadline (default 3 s): unanswered work re-routes + escalates
  - After 3 unanswered attempts the work goes to a supervisor
  - Reject immediately re-routes to the next operator
  - Reject + assigned API endpoints
  - New fields survive a persistence round-trip
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import incident_intelligence
from incident_intelligence import (
    Incident, IncidentStore, incident_store,
    process_event, process_assignment_timeouts,
    auto_assign_incident, get_duty_roster,
    AUTO_ASSIGN_SEVERITIES,
)


def _clear(store=None):
    s = store or incident_store
    with s._lock:
        s._incidents.clear()
        s._bus_incidents.clear()
        s._event_incidents.clear()
        s._last_created.clear()


def _critical_event(bus="BUS-001", etype="CABIN_FIRE"):
    return {
        "event_id": f"EVT-{time.time_ns()}",
        "event_type": etype,
        "bus_id": bus,
        "severity": "CRITICAL",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "simulation": True,
    }


@pytest.fixture(autouse=True)
def clean_store():
    _clear()
    yield
    _clear()


@pytest.fixture
def roster():
    with patch.object(incident_intelligence, "get_duty_roster",
                      return_value=(["op1", "op2"], ["sup1"])):
        yield


class TestAutoAssignOnCreation:
    def test_critical_auto_assigned(self, roster):
        res = process_event(_critical_event())
        assert res["action"] == "created"
        inc = res["incident"]
        assert inc.status == "ASSIGNED"
        assert inc.assigned_to == "op1"
        assert inc.auto_assigned is True
        assert inc.assign_attempts == 1
        actions = [t["action"] for t in inc.timeline]
        assert "AUTO_ASSIGNED" in actions

    def test_non_critical_not_assigned(self, roster):
        evt = _critical_event()
        evt["severity"] = "HIGH"
        evt["event_type"] = "POTHOLE"
        res = process_event(evt)
        assert res["action"] == "created"
        assert res["incident"].status != "ASSIGNED"
        assert res["incident"].auto_assigned is False

    def test_single_user_fallback(self):
        with patch.object(incident_intelligence, "get_duty_roster",
                          return_value=([], ["admin"])):
            res = process_event(_critical_event())
        inc = res["incident"]
        assert inc.status == "ASSIGNED"
        assert inc.assigned_to == "admin"

    def test_no_users_fallback(self):
        with patch.object(incident_intelligence, "get_duty_roster",
                          return_value=([], [])):
            res = process_event(_critical_event())
        assert res["incident"].assigned_to == "duty-operator"


class TestTimeouts:
    def _assigned(self, store=None):
        s = store or incident_store
        inc = Incident(incident_id="INC-T1", status="OPEN", severity="CRITICAL")
        s._add_incident(inc)
        with patch.object(incident_intelligence, "get_duty_roster",
                          return_value=(["op1", "op2"], ["sup1"])):
            auto_assign_incident(inc)
        return inc

    def _age(self, inc, seconds=10):
        past = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")
        inc.last_assigned_at = past
        inc.assigned_at = past

    def test_no_reroute_before_deadline(self, roster):
        inc = self._assigned()
        touched = process_assignment_timeouts()
        assert touched == []
        assert incident_store.get_incident("INC-T1").assigned_to == "op1"

    def test_reroute_after_deadline(self, roster):
        inc = self._assigned()
        self._age(inc)
        touched = process_assignment_timeouts()
        assert touched == ["INC-T1"]
        updated = incident_store.get_incident("INC-T1")
        assert updated.assigned_to == "op2"
        assert updated.assign_attempts == 2
        assert updated.escalation_level == 1

    def test_three_strikes_goes_to_supervisor(self, roster):
        inc = self._assigned()
        for _ in range(3):
            self._age(inc)
            process_assignment_timeouts()
            inc = incident_store.get_incident("INC-T1")
        assert inc.assigned_to == "sup1"
        actions = [t["action"] for t in inc.timeline]
        assert "ESCALATED_TO_SUPERVISOR" in actions

    def test_responded_work_untouched(self, roster):
        inc = self._assigned()
        incident_store.respond_incident("INC-T1", "op1")
        self._age(incident_store.get_incident("INC-T1"))
        assert process_assignment_timeouts() == []


class TestReject:
    def test_reject_reroutes(self, roster):
        inc = Incident(incident_id="INC-R1", status="OPEN", severity="CRITICAL")
        incident_store._add_incident(inc)
        auto_assign_incident(inc)
        assert inc.assigned_to == "op1"
        rejected = incident_store.reject_incident("INC-R1", "op1")
        assert rejected.status == "CONFIRMED"
        assert "op1" in rejected.rejected_by
        auto_assign_incident(rejected, actor="op1")
        assert rejected.assigned_to == "op2"
        assert rejected.assign_attempts == 2


class TestAutoAssignAPI:
    @pytest.fixture
    def client(self):
        from server import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

    def _login(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        return resp.get_json()["token"]

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def test_reject_endpoint(self, client):
        token = self._login(client)
        with patch.object(incident_intelligence, "get_duty_roster",
                          return_value=(["op1", "op2"], ["sup1"])):
            inc = Incident(incident_id="INC-REJ-1", status="OPEN", severity="CRITICAL")
            incident_store._add_incident(inc)
            auto_assign_incident(inc)
            resp = client.post("/api/incidents/INC-REJ-1/reject",
                               json={"operator": "op1"}, headers=self._headers(token))
        assert resp.status_code == 200
        data = resp.get_json()["incident"]
        assert data["status"] == "ASSIGNED"
        assert data["assigned_to"] == "op2"
        assert "op1" in data["rejected_by"]

    def test_assigned_endpoint(self, client):
        inc = Incident(incident_id="INC-ASD-1", status="ASSIGNED", severity="CRITICAL",
                       bus_id="BUS-001", assigned_to="op1")
        incident_store._add_incident(inc)
        resp = client.get("/api/incidents/assigned")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] >= 1
        assert any(i["incident_id"] == "INC-ASD-1" for i in data["incidents"])

    def test_reject_requires_auth(self, client):
        resp = client.post("/api/incidents/INC-X/reject", json={"operator": "op1"})
        assert resp.status_code in (401, 503)


class TestAutoAssignPersistence:
    def test_new_fields_round_trip(self):
        import persistence
        inc = Incident(incident_id="INC-P1", status="ASSIGNED", severity="CRITICAL",
                       bus_id="BUS-001", auto_assigned=True, assign_attempts=2,
                       rejected_by=["op1"], escalation_level=1,
                       last_assigned_at="2026-09-18T10:00:00+00:00",
                       assigned_to="op2")
        persistence.save_incident(inc.to_dict())
        rows = persistence.load_incidents()
        match = next(r for r in rows if r["incident_id"] == "INC-P1")
        assert match["auto_assigned"] is True
        assert match["assign_attempts"] == 2
        assert match["rejected_by"] == ["op1"]
        assert match["escalation_level"] == 1
