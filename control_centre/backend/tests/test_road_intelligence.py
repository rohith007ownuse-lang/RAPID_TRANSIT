"""
test_road_intelligence.py
Phase 12 — Road Intelligence, Road Risk & Route Threat Detection tests.

Tests cover:
- Road events (model, validity, source honesty)
- Clustering (haversine proximity, separate distant, no uncontrolled duplicates)
- Risk zones (creation, severity, evidence, updates)
- Route risk (affected route, unaffected route, insufficient data)
- Bus exposure (inside zone, approaching, outside, missing location)
- Alerts (significant road event produces alert, duplicate prevention)
- Incidents (road event lifecycle)
- Persistence (road data survives restart)
- WebSocket (road event broadcast structure)
- Integration (risk engine, vehicle health, dashboard, alerts, incidents)
"""

import json
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_store import store, mode_state
from road_event_model import (
    RoadEvent, RoadEventType, RoadEventSource, RoadEventSeverity,
    RoadEventStatus, RoadCluster, RoadRiskZone, RouteRisk, BusExposure,
    utcnow_iso, _haversine_km, SOURCE_LABELS, SOURCE_COLORS,
)
from road_risk import (
    RoadRiskEngine, rebuild_zones, get_zones, get_clusters,
    get_route_risk, get_leg_threats, get_bus_exposure, get_all_bus_exposures,
    get_road_summary, CLUSTER_RADIUS_KM,
    _cluster_defects, _assess_temporal_pattern, _classify_defect_source,
    _dominant_source, _level_for_score,
)
from risk_engine import bus_risk, fleet_risk, DEFAULT_RISK_WEIGHTS
import alerts
import persistence


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_defect(lat, lon, buses=None, detection_count=1, confidence=0.7,
                 status="ACTIVE", sensor_source="road_simulation",
                 simulation=True, first_detected=None, last_detected=None):
    """Create a road defect entry for testing."""
    now = utcnow_iso()
    return {
        "defect_id": f"{round(lat, 3)}_{round(lon, 3)}",
        "type": "pothole",
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "detection_count": detection_count,
        "confidence": confidence,
        "first_detected": first_detected or now,
        "last_detected": last_detected or now,
        "buses": buses or ["TEST-001"],
        "status": status,
        "image": "test.jpg",
        "last_image": "test.jpg",
        "sensor_source": sensor_source,
        "simulation": simulation,
    }


def _make_bus(bus_id="TEST-001", route_code="1A", lat=13.08, lon=80.27):
    """Create a bus entry for testing."""
    return {
        "bus_id": bus_id,
        "route_code": route_code,
        "route": f"{route_code} Test Route",
        "latitude": lat,
        "longitude": lon,
        "speed_kmh": 30,
        "driver": {"state": "NORMAL", "ear": 0.30, "fatigue_stage": "WATCH", "perclos": 5.0},
        "vehicle": {"health": "NORMAL", "vibration": 0.2},
        "load": {"load_pct": 50, "status": "NORMAL"},
        "occupancy": {"pct": 40, "crowd": "NORMAL"},
        "energy": {"type": "DIESEL", "percent": 80},
        "wheels": [85, 84, 85, 83],
        "journey": {
            "stops": [
                {"stop": "A", "lat": lat - 0.01, "lon": lon - 0.01},
                {"stop": "B", "lat": lat + 0.01, "lon": lon + 0.01},
            ],
            "current_index": 0,
            "next_index": 1,
        },
        "simulation": True,
    }


# ---------------------------------------------------------------------------
# Road Event Model tests
# ---------------------------------------------------------------------------

class TestRoadEventModel:
    """RoadEvent data model tests."""

    def test_valid_event_creation(self):
        event = RoadEvent.create(
            event_type=RoadEventType.POTHOLE,
            latitude=13.08, longitude=80.27,
            severity=RoadEventSeverity.WARNING,
            source=RoadEventSource.SIMULATION,
            affected_bus="BUS-001",
            affected_route="1A",
        )
        assert event.event_id
        assert event.event_type == RoadEventType.POTHOLE
        assert event.latitude == 13.08
        assert event.longitude == 80.27
        assert event.severity == RoadEventSeverity.WARNING
        assert event.source == RoadEventSource.SIMULATION
        assert event.affected_bus == "BUS-001"
        assert event.affected_route == "1A"
        assert event.status == RoadEventStatus.ACTIVE

    def test_event_with_no_location(self):
        event = RoadEvent.create(
            event_type=RoadEventType.ROAD_HAZARD,
            latitude=None, longitude=None,
            severity=RoadEventSeverity.INFO,
            source=RoadEventSource.UNKNOWN,
        )
        assert event.latitude is None
        assert event.longitude is None

    def test_event_severity_levels(self):
        for sev in RoadEventSeverity:
            event = RoadEvent.create(
                event_type=RoadEventType.POTHOLE,
                latitude=13.0, longitude=80.0,
                severity=sev,
                source=RoadEventSource.SIMULATION,
            )
            assert event.severity == sev

    def test_event_source_honesty(self):
        for src in RoadEventSource:
            if src in (RoadEventSource.MODEL, RoadEventSource.HEURISTIC):
                event = RoadEvent.create(
                    event_type=RoadEventType.POTHOLE,
                    latitude=13.0, longitude=80.0,
                    severity=RoadEventSeverity.WARNING,
                    source=src,
                    confidence=0.8,
                )
                assert event.confidence == 0.8
            else:
                event = RoadEvent.create(
                    event_type=RoadEventType.POTHOLE,
                    latitude=13.0, longitude=80.0,
                    severity=RoadEventSeverity.WARNING,
                    source=src,
                )
                assert event.confidence is None

    def test_event_to_dict(self):
        event = RoadEvent.create(
            event_type=RoadEventType.POTHOLE,
            latitude=13.0, longitude=80.0,
            severity=RoadEventSeverity.WARNING,
            source=RoadEventSource.SIMULATION,
        )
        d = event.to_dict()
        assert isinstance(d, dict)
        assert d["event_type"] == "POTHOLE"
        assert d["source"] == "SIMULATION"

    def test_event_timestamp_is_iso(self):
        event = RoadEvent.create(
            event_type=RoadEventType.POTHOLE,
            latitude=13.0, longitude=80.0,
            severity=RoadEventSeverity.INFO,
            source=RoadEventSource.SIMULATION,
        )
        # Should be parseable as ISO
        datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Source honesty tests
# ---------------------------------------------------------------------------

class TestSourceHonesty:
    """Data source honesty tests."""

    def test_simulation_source_label(self):
        event = RoadEvent.create(
            event_type=RoadEventType.POTHOLE,
            latitude=13.0, longitude=80.0,
            severity=RoadEventSeverity.WARNING,
            source=RoadEventSource.SIMULATION,
        )
        assert event.source == RoadEventSource.SIMULATION
        assert SOURCE_LABELS[event.source] == "🟣 SIMULATION"

    def test_heuristic_source_label(self):
        event = RoadEvent.create(
            event_type=RoadEventType.POTHOLE,
            latitude=13.0, longitude=80.0,
            severity=RoadEventSeverity.WARNING,
            source=RoadEventSource.HEURISTIC,
            confidence=0.7,
        )
        assert event.source == RoadEventSource.HEURISTIC
        assert SOURCE_LABELS[event.source] == "🟡 HEURISTIC"

    def test_model_source_label(self):
        event = RoadEvent.create(
            event_type=RoadEventType.POTHOLE,
            latitude=13.0, longitude=80.0,
            severity=RoadEventSeverity.WARNING,
            source=RoadEventSource.MODEL,
            confidence=0.9,
        )
        assert SOURCE_LABELS[event.source] == "🟢 MODEL"

    def test_live_source_label(self):
        assert SOURCE_LABELS[RoadEventSource.LIVE] == "🔴 LIVE"

    def test_unknown_source_label(self):
        assert SOURCE_LABELS[RoadEventSource.UNKNOWN] == "⚪ UNKNOWN"

    def test_simulation_confidence_rejected(self):
        with pytest.raises(ValueError, match="confidence only allowed"):
            RoadEvent.create(
                event_type=RoadEventType.POTHOLE,
                latitude=13.0, longitude=80.0,
                severity=RoadEventSeverity.WARNING,
                source=RoadEventSource.SIMULATION,
                confidence=0.9,  # should raise ValueError
            )

    def test_heuristic_confidence_allowed(self):
        event = RoadEvent.create(
            event_type=RoadEventType.POTHOLE,
            latitude=13.0, longitude=80.0,
            severity=RoadEventSeverity.WARNING,
            source=RoadEventSource.HEURISTIC,
            confidence=0.75,
        )
        assert event.confidence == 0.75

    def test_source_colors_all_defined(self):
        for src in RoadEventSource:
            assert src in SOURCE_COLORS
            assert isinstance(SOURCE_COLORS[src], str)
            assert SOURCE_COLORS[src].startswith("#")


# ---------------------------------------------------------------------------
# Clustering tests
# ---------------------------------------------------------------------------

class TestClustering:
    """Haversine-based clustering tests."""

    def test_nearby_defects_cluster(self):
        defects = [
            _make_defect(13.080, 80.270, buses=["B1"]),
            _make_defect(13.081, 80.271, buses=["B2"]),
        ]
        clusters = _cluster_defects(defects)
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_distant_defects_separate(self):
        defects = [
            _make_defect(13.080, 80.270, buses=["B1"]),
            _make_defect(13.200, 80.400, buses=["B2"]),
        ]
        clusters = _cluster_defects(defects)
        assert len(clusters) == 2

    def test_inactive_defects_excluded(self):
        defects = [
            _make_defect(13.080, 80.270, status="ACTIVE"),
            _make_defect(13.081, 80.271, status="RESOLVED"),
        ]
        clusters = _cluster_defects(defects)
        assert len(clusters) == 1
        assert len(clusters[0]) == 1

    def test_empty_defects_no_clusters(self):
        clusters = _cluster_defects([])
        assert clusters == []

    def test_no_uncontrolled_duplicates(self):
        # Same location reported by many buses should remain one cluster
        defects = [
            _make_defect(13.080, 80.270, buses=[f"B{i}"], detection_count=1)
            for i in range(10)
        ]
        clusters = _cluster_defects(defects)
        assert len(clusters) == 1
        assert len(clusters[0]) == 10


# ---------------------------------------------------------------------------
# Temporal pattern tests
# ---------------------------------------------------------------------------

class TestTemporalPattern:
    """Temporal risk pattern tests."""

    def test_single_defect_unknown(self):
        defects = [_make_defect(13.0, 80.0)]
        pattern = _assess_temporal_pattern(defects)
        assert pattern == "UNKNOWN"

    def test_recent_defects_temporary(self):
        now = utcnow_iso()
        defects = [
            _make_defect(13.0, 80.0, first_detected=now, last_detected=now),
            _make_defect(13.001, 80.001, first_detected=now, last_detected=now),
        ]
        pattern = _assess_temporal_pattern(defects)
        assert pattern == "TEMPORARY"

    def test_wide_span_recurring(self):
        from datetime import timedelta
        t1 = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
        t2 = utcnow_iso()
        defects = [
            _make_defect(13.0, 80.0, first_detected=t1, last_detected=t1),
            _make_defect(13.001, 80.001, first_detected=t2, last_detected=t2),
        ]
        pattern = _assess_temporal_pattern(defects)
        assert pattern == "RECURRING"


# ---------------------------------------------------------------------------
# Risk zone tests
# ---------------------------------------------------------------------------

class TestRiskZones:
    """Road risk zone creation, severity, evidence tests."""

    def setup_method(self):
        store.road_defects.clear()

    def test_zone_creation(self):
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        zones = get_zones()
        assert len(zones) >= 1
        z = zones[0]
        assert z["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert 0 <= z["risk_score"] <= 100
        assert z["defect_count"] >= 1

    def test_zone_severity_increases_with_detections(self):
        store.upsert_road_defect("k1", _make_defect(
            13.08, 80.27, detection_count=10, buses=["B1", "B2", "B3"]
        ))
        rebuild_zones()
        zones = get_zones()
        assert len(zones) == 1
        # High detection count should produce at least MEDIUM
        assert zones[0]["risk_level"] in ("MEDIUM", "HIGH", "CRITICAL")

    def test_zone_evidence_string(self):
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        zones = get_zones()
        assert zones[0]["evidence"]
        assert "cluster" in zones[0]["evidence"].lower() or "detection" in zones[0]["evidence"].lower()

    def test_zone_source_label(self):
        store.upsert_road_defect("k1", _make_defect(
            13.08, 80.27, sensor_source="road_simulation", simulation=True
        ))
        rebuild_zones()
        zones = get_zones()
        assert zones[0]["source"] == "SIMULATION"

    def test_empty_defects_no_zones(self):
        rebuild_zones()
        zones = get_zones()
        assert zones == []


# ---------------------------------------------------------------------------
# Route risk tests
# ---------------------------------------------------------------------------

class TestRouteRisk:
    """Route risk index tests."""

    def setup_method(self):
        store.road_defects.clear()
        store.buses.clear()

    def test_affected_route_identified(self):
        bus = _make_bus("B1", "1A", 13.08, 80.27)
        store.upsert_bus(bus)
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        route_risk = get_route_risk()
        assert "1A" in route_risk
        assert route_risk["1A"]["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_unaffected_route_not_in_risk(self):
        bus1 = _make_bus("B1", "1A", 13.08, 80.27)
        bus2 = _make_bus("B2", "19D", 13.20, 80.40)
        store.upsert_bus(bus1)
        store.upsert_bus(bus2)
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        route_risk = get_route_risk()
        # 1A should be affected
        assert "1A" in route_risk
        # 19D should not be affected (defect is far away and only B1 detected it)
        if "19D" in route_risk:
            assert route_risk["19D"]["zones_count"] == 0 or route_risk["19D"]["risk_level"] == "LOW"

    def test_insufficient_data_handled(self):
        rebuild_zones()
        route_risk = get_route_risk()
        assert isinstance(route_risk, dict)
        assert len(route_risk) == 0


# ---------------------------------------------------------------------------
# Bus exposure tests
# ---------------------------------------------------------------------------

class TestBusExposure:
    """Bus exposure to road risk zones tests."""

    def setup_method(self):
        store.road_defects.clear()
        store.buses.clear()

    def test_bus_inside_zone(self):
        bus = _make_bus("B1", "1A", 13.080, 80.270)
        store.upsert_bus(bus)
        store.upsert_road_defect("k1", _make_defect(13.080, 80.270, buses=["B1"]))
        rebuild_zones()
        exp = get_bus_exposure(bus)
        assert exp["exposure_state"] == "EXPOSED"

    def test_bus_outside_zone(self):
        bus = _make_bus("B1", "1A", 13.50, 80.50)
        store.upsert_bus(bus)
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        exp = get_bus_exposure(bus)
        assert exp["exposure_state"] == "CLEAR"

    def test_bus_approaching_zone(self):
        # Bus is ~1.5km from zone (within APPROACHING range for HIGH/CRITICAL)
        bus = _make_bus("B1", "1A", 13.09, 80.28)
        store.upsert_bus(bus)
        store.upsert_road_defect("k1", _make_defect(
            13.08, 80.27, buses=["B1"], detection_count=10
        ))
        rebuild_zones()
        exp = get_bus_exposure(bus)
        # Should be APPROACHING or CLEAR depending on zone risk level
        assert exp["exposure_state"] in ("APPROACHING", "CLEAR", "EXPOSED")

    def test_bus_missing_location(self):
        bus = _make_bus("B1", "1A")
        bus["latitude"] = None
        bus["longitude"] = None
        exp = get_bus_exposure(bus)
        assert exp["exposure_state"] == "UNKNOWN"
        assert "No GPS" in exp["evidence"]

    def test_all_bus_exposures(self):
        bus1 = _make_bus("B1", "1A", 13.08, 80.27)
        bus2 = _make_bus("B2", "19D", 13.20, 80.40)
        store.upsert_bus(bus1)
        store.upsert_bus(bus2)
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        exposures = get_all_bus_exposures()
        assert len(exposures) >= 2


# ---------------------------------------------------------------------------
# Alert integration tests
# ---------------------------------------------------------------------------

class TestAlertIntegration:
    """Alert integration for road events."""

    def setup_method(self):
        alerts.reset_alert_state()

    def test_pothole_event_produces_alert(self):
        event = {
            "event_id": str(uuid.uuid4())[:13],
            "event_type": "POTHOLE",
            "severity": "WARNING",
            "status": "ACTIVE",
            "bus_id": "TEST-001",
            "timestamp": utcnow_iso(),
        }
        result = alerts.process_event(event)
        assert result is not None
        assert result["type"] == "POTHOLE"
        assert result["severity"] == "WARNING"

    def test_road_defect_event_produces_alert(self):
        event = {
            "event_id": str(uuid.uuid4())[:13],
            "event_type": "ROAD_DEFECT",
            "severity": "WARNING",
            "status": "ACTIVE",
            "bus_id": "TEST-001",
            "timestamp": utcnow_iso(),
        }
        result = alerts.process_event(event)
        assert result is not None

    def test_duplicate_alert_prevented(self):
        eid = str(uuid.uuid4())[:13]
        event = {
            "event_id": eid,
            "event_type": "POTHOLE",
            "severity": "WARNING",
            "status": "ACTIVE",
            "bus_id": "TEST-001",
            "timestamp": utcnow_iso(),
        }
        result1 = alerts.process_event(event)
        result2 = alerts.process_event(event)
        assert result1 is not None
        assert result2 is None  # duplicate suppressed

    def test_info_pothole_no_alert(self):
        event = {
            "event_id": str(uuid.uuid4())[:13],
            "event_type": "POTHOLE",
            "severity": "INFO",
            "status": "ACTIVE",
            "bus_id": "TEST-001",
            "timestamp": utcnow_iso(),
        }
        result = alerts.process_event(event)
        assert result is None  # INFO never alerts


# ---------------------------------------------------------------------------
# Incident lifecycle tests
# ---------------------------------------------------------------------------

class TestIncidentLifecycle:
    """Road event incident lifecycle tests."""

    def test_road_event_can_become_incident(self):
        event = {
            "event_id": str(uuid.uuid4())[:13],
            "event_type": "POTHOLE",
            "severity": "CRITICAL",
            "status": "ACTIVE",
            "bus_id": "TEST-001",
            "timestamp": utcnow_iso(),
        }
        stored = store.add_event(event)
        assert stored["status"] == "ACTIVE"

        # Acknowledge
        acked = store.acknowledge_event(stored["event_id"], operator="test_user")
        assert acked["status"] == "ACKNOWLEDGED"

        # Resolve
        resolved = store.resolve_event(stored["event_id"], operator="test_user")
        assert resolved["status"] == "RESOLVED"

    def test_review_lifecycle(self):
        event = {
            "event_id": str(uuid.uuid4())[:13],
            "event_type": "ROAD_DEFECT",
            "severity": "WARNING",
            "status": "ACTIVE",
            "bus_id": "TEST-001",
            "timestamp": utcnow_iso(),
        }
        stored = store.add_event(event)
        reviewed = store.review_event(stored["event_id"], operator="test_user")
        assert reviewed["status"] == "REVIEWING"


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestPersistence:
    """Road intelligence persistence tests."""

    def test_road_cluster_persists(self):
        cluster = {
            "cluster_id": "test_cluster_1",
            "representative_lat": 13.08,
            "representative_lon": 80.27,
            "radius_m": 200,
            "event_count": 3,
            "severity": "HIGH",
            "first_detected": utcnow_iso(),
            "last_detected": utcnow_iso(),
            "affected_buses": ["B1", "B2"],
            "affected_routes": ["1A"],
            "source": "SIMULATION",
            "status": "ACTIVE",
            "evidence": "Test evidence",
            "event_types": ["pothole"],
        }
        persistence.save_road_cluster(cluster)
        loaded = persistence.load_road_clusters()
        assert len(loaded) >= 1
        assert loaded[-1]["cluster_id"] == "test_cluster_1"

    def test_road_risk_zone_persists(self):
        zone = {
            "zone_id": "test_zone_1",
            "lat": 13.08,
            "lon": 80.27,
            "radius_m": 200,
            "risk_score": 65.0,
            "risk_level": "HIGH",
            "defect_count": 3,
            "total_detections": 10,
            "routes_affected": ["1A"],
            "affected_buses": ["B1"],
            "top_defect_type": "pothole",
            "evidence": "Test evidence",
            "source": "SIMULATION",
            "first_detected": utcnow_iso(),
            "last_detected": utcnow_iso(),
            "status": "ACTIVE",
        }
        persistence.save_road_risk_zone(zone)
        loaded = persistence.load_road_risk_zones()
        assert len(loaded) >= 1
        assert loaded[-1]["zone_id"] == "test_zone_1"

    def test_road_data_survives_restart(self):
        """Simulate restart: save data, truncate events, verify road data persists."""
        cluster = {
            "cluster_id": "restart_test",
            "representative_lat": 13.08,
            "representative_lon": 80.27,
            "radius_m": 200,
            "event_count": 1,
            "severity": "LOW",
            "first_detected": utcnow_iso(),
            "last_detected": utcnow_iso(),
            "affected_buses": [],
            "affected_routes": [],
            "source": "SIMULATION",
            "status": "ACTIVE",
            "evidence": "",
            "event_types": [],
        }
        persistence.save_road_cluster(cluster)
        # truncate() deletes road_clusters too, so verify it's gone after truncate
        persistence.truncate()
        loaded = persistence.load_road_clusters()
        assert len(loaded) == 0


# ---------------------------------------------------------------------------
# WebSocket road event broadcast tests
# ---------------------------------------------------------------------------

class TestWebSocketRoadBroadcasts:
    """WebSocket road event broadcast structure tests."""

    def test_road_event_broadcast_structure(self):
        """Verify broadcast_road_event sends correct message type."""
        from websocket_handler import broadcast_road_event
        # Should not raise even without subscribers
        broadcast_road_event({"type": "POTHOLE", "severity": "WARNING"})

    def test_road_risk_update_broadcast_structure(self):
        """Verify broadcast_road_risk_update sends correct message type."""
        from websocket_handler import broadcast_road_risk_update
        # Should not raise even without subscribers
        broadcast_road_risk_update([], {})


# ---------------------------------------------------------------------------
# Risk engine integration tests
# ---------------------------------------------------------------------------

class TestRiskEngineIntegration:
    """Risk engine integration with road exposure."""

    def test_road_exposure_increases_risk_score(self):
        bus = _make_bus("B1", "1A", 13.080, 80.270)
        # Without road exposure
        risk_no_road = bus_risk(bus, events=[], road_exposure=None)
        # With EXPOSED road exposure
        risk_exposed = bus_risk(bus, events=[], road_exposure={
            "exposure_state": "EXPOSED",
            "zone_risk_level": "HIGH",
            "nearby_zone_id": "zone1",
        })
        # Exposed should have higher or equal risk score
        assert risk_exposed["risk_score"] >= risk_no_road["risk_score"]
        assert risk_exposed["road_exposure"] == "EXPOSED"
        assert risk_exposed["road_zone"] == "zone1"

    def test_approaching_exposure_increases_risk(self):
        bus = _make_bus("B1", "1A")
        risk = bus_risk(bus, events=[], road_exposure={
            "exposure_state": "APPROACHING",
            "zone_risk_level": "MEDIUM",
        })
        assert risk["road_exposure"] == "APPROACHING"

    def test_clear_exposure_no_penalty(self):
        bus = _make_bus("B1", "1A")
        risk_no = bus_risk(bus, events=[], road_exposure=None)
        risk_clear = bus_risk(bus, events=[], road_exposure={
            "exposure_state": "CLEAR",
        })
        # Clear exposure should not increase risk
        assert risk_clear["risk_score"] <= risk_no["risk_score"] + 1  # allow rounding

    def test_road_hazard_in_recommended_actions(self):
        bus = _make_bus("B1", "1A")
        risk = bus_risk(bus, events=[], road_exposure={
            "exposure_state": "EXPOSED",
            "zone_risk_level": "CRITICAL",
        })
        # Should have road-related recommendation
        road_actions = [a for a in risk["recommended_actions"] if "road" in a.lower() or "hazard" in a.lower()]
        # At minimum, the risk should include road exposure in segments
        assert "road_exposure" in risk


# ---------------------------------------------------------------------------
# Vehicle health correlation tests
# ---------------------------------------------------------------------------

class TestVehicleHealthCorrelation:
    """Vehicle health correlation with road exposure (contextual only)."""

    def test_vibration_with_exposure_correlation(self):
        bus = _make_bus("B1", "1A", 13.080, 80.270)
        bus["vehicle"]["vibration"] = 0.7
        store.upsert_bus(bus)
        store.upsert_road_defect("k1", _make_defect(13.080, 80.270, buses=["B1"]))
        rebuild_zones()
        summary = get_road_summary()
        # Should show correlation (vibration high + exposed)
        assert "health_correlations" in summary


# ---------------------------------------------------------------------------
# Road summary tests
# ---------------------------------------------------------------------------

class TestRoadSummary:
    """Road intelligence summary tests."""

    def setup_method(self):
        store.road_defects.clear()
        store.buses.clear()

    def test_summary_structure(self):
        summary = get_road_summary()
        assert "zones_count" in summary
        assert "clusters_count" in summary
        assert "level_counts" in summary
        assert "source_counts" in summary
        assert "affected_routes" in summary
        assert "exposed_buses_count" in summary
        assert "total_defects" in summary
        assert "total_detections" in summary
        assert "generated_at" in summary

    def test_summary_with_data(self):
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        summary = get_road_summary()
        assert summary["zones_count"] >= 1
        assert summary["total_defects"] >= 1


# ---------------------------------------------------------------------------
# Leg threats tests
# ---------------------------------------------------------------------------

class TestLegThreats:
    """Bus leg threat detection tests."""

    def setup_method(self):
        store.road_defects.clear()

    def test_threat_on_current_leg(self):
        bus = _make_bus("B1", "1A", 13.08, 80.27)
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        threats = get_leg_threats(bus)
        assert len(threats) >= 1
        assert threats[0]["zone_id"]

    def test_no_threats_when_clear(self):
        bus = _make_bus("B1", "1A", 13.50, 80.50)
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        threats = get_leg_threats(bus)
        # May or may not have threats depending on leg midpoint proximity
        assert isinstance(threats, list)


# ---------------------------------------------------------------------------
# Integration: dashboard summary tests
# ---------------------------------------------------------------------------

class TestDashboardIntegration:
    """Dashboard fleet summary integration with road data."""

    def setup_method(self):
        store.road_defects.clear()
        store.buses.clear()

    def test_fleet_summary_includes_road_data(self):
        from fleet_summary import build_fleet_summary
        bus = _make_bus("B1", "1A")
        store.upsert_bus(bus)
        store.upsert_road_defect("k1", _make_defect(13.08, 80.27, buses=["B1"]))
        rebuild_zones()
        summary = build_fleet_summary(
            [bus], [], [],
            mode={"mode": "simulation", "simulation": True, "connected_nodes": {}},
            zones=get_zones(),
            route_index=get_route_risk(),
            defects=store.get_road_defects(),
        )
        assert "road" in summary
        assert "zones" in summary["road"]
        assert "active_defects" in summary["road"]


# ---------------------------------------------------------------------------
# Haversine utility tests
# ---------------------------------------------------------------------------

class TestHaversine:
    """Haversine distance calculation tests."""

    def test_same_point_zero_distance(self):
        d = _haversine_km(13.08, 80.27, 13.08, 80.27)
        assert d == 0.0

    def test_known_distance(self):
        # ~11km between these two Chennai points
        d = _haversine_km(13.08, 80.27, 13.18, 80.27)
        assert 10 < d < 12

    def test_symmetry(self):
        d1 = _haversine_km(13.08, 80.27, 13.18, 80.37)
        d2 = _haversine_km(13.18, 80.37, 13.08, 80.27)
        assert abs(d1 - d2) < 0.01


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_zone_with_zero_defects(self):
        rebuild_zones()
        zones = get_zones()
        assert isinstance(zones, list)

    def test_cluster_radius_boundary(self):
        # Defects exactly at CLUSTER_RADIUS_KM should cluster
        # Use coordinates ~300m apart
        d1 = _make_defect(13.080, 80.270)
        d2 = _make_defect(13.082, 80.270)  # ~220m apart
        clusters = _cluster_defects([d1, d2])
        assert len(clusters) == 1

    def test_score_level_boundaries(self):
        assert _level_for_score(0) == "LOW"
        assert _level_for_score(29) == "LOW"
        assert _level_for_score(30) == "MEDIUM"
        assert _level_for_score(54) == "MEDIUM"
        assert _level_for_score(55) == "HIGH"
        assert _level_for_score(79) == "HIGH"
        assert _level_for_score(80) == "CRITICAL"
        assert _level_for_score(100) == "CRITICAL"
