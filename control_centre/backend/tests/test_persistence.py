"""
test_persistence.py — Phase 4: SQLite persistence.

Verifies that events/incidents written to the in-memory store land in SQLite
and that the history survives a simulated backend restart (fresh in-memory
store re-hydrated from the database), including status transitions
(ack / review / resolve / status override) and per-event simulation/live labels.

Each test runs against an isolated SQLite database provided by conftest.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import persistence  # noqa: E402
from data_store import store  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_store():
    store.events.clear()
    store.buses.clear()
    store.road_defects.clear()
    persistence.truncate()
    yield
    store.events.clear()
    persistence.truncate()


def _mk_event(**overrides):
    base = {
        "event_type": "DRIVER_DROWSINESS",
        "bus_id": "B-1A",
        "route_code": "1A",
        "severity": "CRITICAL",
        "details": "drowsy driver on route 1A",
        "sensor_source": "driver_ai",
        "confidence": 0.91,
        "latitude": 13.08,
        "longitude": 80.27,
    }
    base.update(overrides)
    return base


def _restart():
    """Simulate a backend restart: wipe the in-memory log, then re-hydrate
    from the persistent database (same path as the app startup path)."""
    store.events.clear()
    for ev in persistence.load_events():
        store.add_event(ev)


def test_event_is_persisted():
    ev = store.add_event(_mk_event(timestamp="2026-01-01T10:00:00+00:00"))
    assert persistence.count_events() == 1
    persisted = persistence.load_events()[0]
    assert persisted["event_id"] == ev["event_id"]
    assert persisted["event_type"] == "DRIVER_DROWSINESS"
    assert persisted["bus_id"] == "B-1A"
    assert persisted["timestamp"] == "2026-01-01T10:00:00+00:00"


def test_restart_loads_event_back_into_store():
    ev = store.add_event(_mk_event())
    _restart()
    got = store.get_events(100)
    assert len(got) == 1
    assert got[0]["event_id"] == ev["event_id"]


def test_simulation_event_label_survives_restart():
    store.add_event(_mk_event(simulation=True, data_source="simulation"))
    _restart()
    got = store.get_events(100)[0]
    assert got["simulation"] is True
    assert got["data_source"] == "simulation"


def test_live_event_label_survives_restart():
    store.add_event(_mk_event(
        bus_id="PROTO-001", event_type="DDS_SESSION_END",
        simulation=False, data_source="live",
    ))
    _restart()
    got = store.get_events(100)[0]
    assert got["simulation"] is False
    assert got["data_source"] == "live"
    assert got["bus_id"] == "PROTO-001"


def test_mixed_history_keeps_correct_labels():
    store.add_event(_mk_event(simulation=True, data_source="simulation"))
    store.add_event(_mk_event(
        bus_id="PROTO-001", event_type="DRIVER_DROWSINESS",
        simulation=False, data_source="live",
    ))
    _restart()
    by_source = {e["data_source"]: e for e in store.get_events(100)}
    assert by_source["simulation"]["simulation"] is True
    assert by_source["live"]["simulation"] is False


def test_acknowledged_incident_survives_restart():
    ev = store.add_event(_mk_event())
    store.acknowledge_event(ev["event_id"], operator="op-1")
    _restart()
    got = store.get_events(100)[0]
    assert got["status"] == "ACKNOWLEDGED"
    assert got["acknowledged_by"] == "op-1"


def test_resolved_incident_survives_restart():
    ev = store.add_event(_mk_event())
    store.resolve_event(ev["event_id"], operator="sup-1")
    _restart()
    got = store.get_events(100)[0]
    assert got["status"] == "RESOLVED"
    assert got["resolved_by"] == "sup-1"


def test_status_override_survives_restart():
    ev = store.add_event(_mk_event())
    store.set_event_status(ev["event_id"], "REVIEWING", operator="op-2")
    _restart()
    got = store.get_events(100)[0]
    assert got["status"] == "REVIEWING"
    assert got["reviewed_by"] == "op-2"


def test_bulk_status_persisted():
    e1 = store.add_event(_mk_event(bus_id="B-1"))
    e2 = store.add_event(_mk_event(bus_id="B-1"))
    store.set_event_status_many("ACKNOWLEDGED", operator="op-3", bus_id="B-1")
    count = persistence.load_events()
    assert all(e["status"] == "ACKNOWLEDGED" for e in count)
    _restart()
    assert len(store.get_events(100)) == 2


def test_reload_is_idempotent():
    ev = store.add_event(_mk_event())
    _restart()
    _restart()
    assert len(store.get_events(100)) == 1
    assert persistence.count_events() == 1


def test_incident_fields_persisted():
    store.add_event(_mk_event(
        event_type="POTHOLE",
        severity="WARNING",
        sensor_source="road_ai",
        latitude=13.0827,
        longitude=80.2747,
        data_source="simulation",
        simulation=True,
    ))
    ev = persistence.load_events()[0]
    assert ev["severity"] == "WARNING"
    assert ev["sensor_source"] == "road_ai"
    assert ev["latitude"] == 13.0827
    assert ev["longitude"] == 80.2747


def test_dds_session_event_persisted():
    store.add_event(_mk_event(
        event_type="DDS_SESSION_END",
        data_source="live",
        simulation=False,
        details="session complete | drowsy=3 alert=1",
    ))
    _restart()
    got = store.get_events(100)[0]
    assert got["event_type"] == "DDS_SESSION_END"
    assert "drowsy=3" in got["details"]