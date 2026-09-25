"""
test_phase14_demand_intelligence.py
Phase 14 — Passenger Demand Intelligence, Load Forecasting & Capacity Awareness tests.

Tests the new demand_intelligence.py module and updated demand.py with:
- Capacity model (bus capacity, utilization, load state)
- Occupancy snapshot (source-aware, cabin integration)
- Demand patterns and trends
- Capacity pressure detection
- Overcrowding detection (sustained)
- Route-level demand summary
- Fleet load summary
- Source honesty (SIMULATION/LIVE/HEURISTIC/UNKNOWN)
- Persistence integration
- Edge cases (zero capacity, missing data, over-capacity)

All tests use isolated SQLite DB via conftest.py autouse fixture.
All data is SIMULATED — no fabricated GPS, traffic, schedules, or ML models.
"""

import random
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bus(bus_id="T-001", route_code="MTC-1", passengers=30, capacity=60,
              health="NORMAL", driver_state="NORMAL", simulation=True):
    """Create a minimal bus dict with load/occupancy data."""
    pct = (passengers / capacity * 100) if capacity > 0 else 0
    crowd = "NORMAL"
    if pct >= 90:
        crowd = "CRITICAL CROWDING"
    elif pct >= 75:
        crowd = "HIGH"
    elif pct >= 60:
        crowd = "MODERATE"

    load_pct = (passengers * 68) / 6000 * 100  # payload percentage
    load_status = "NORMAL"
    if load_pct > 100:
        load_status = "CRITICAL OVERLOAD"
    elif load_pct > 90:
        load_status = "HIGH LOAD"

    return {
        "bus_id": bus_id,
        "route": f"Route {route_code}",
        "route_code": route_code,
        "speed_kmh": 25,
        "latitude": 13.0,
        "longitude": 80.2,
        "occupancy": {"passengers": passengers, "pct": round(pct, 1), "crowd": crowd, "capacity": capacity},
        "load": {
            "gvw_kg": 11000 + passengers * 68,
            "tare_kg": 11000,
            "payload_kg": passengers * 68,
            "payload_limit_kg": 6000,
            "load_pct": round(load_pct, 1),
            "status": load_status,
        },
        "vehicle": {"health": health, "vibration": 0.3},
        "driver": {"state": driver_state},
        "journey": {
            "start": "A",
            "destination": "E",
            "stops": [
                {"stop": "A", "lat": 13.00, "lon": 80.20, "major": True},
                {"stop": "B", "lat": 13.01, "lon": 80.21, "major": False},
                {"stop": "C", "lat": 13.02, "lon": 80.22, "major": False},
            ],
            "current_index": 0,
            "next_index": 1,
        },
        "daily_boarding_total": 600,
        "boarding_by_hour": {"7": 50, "8": 80, "9": 60, "17": 70, "18": 90},
        "boarding_peak_hour": 8,
        "simulation": simulation,
        "_live": False,
    }


def _make_bus_over_capacity(bus_id="T-OVER"):
    """Bus that exceeds capacity."""
    return _make_bus(bus_id=bus_id, passengers=70, capacity=60)


def _make_bus_unknown_occ(bus_id="T-UNK"):
    """Bus with unknown occupancy."""
    bus = _make_bus(bus_id=bus_id)
    bus["occupancy"] = {"passengers": 0, "pct": 0, "crowd": "NORMAL", "capacity": 60}
    return bus


@pytest.fixture
def rng():
    return random.Random(42)


# ---------------------------------------------------------------------------
# CapacityModel
# ---------------------------------------------------------------------------

class TestCapacityModel:
    def test_valid_bus(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus(passengers=30, capacity=60)
        model = get_capacity_model(bus)
        assert model["bus_id"] == "T-001"
        assert model["capacity"] == 60
        assert model["current_occupancy"] == 30
        assert model["utilization_pct"] == 50.0
        assert model["available_seats"] == 30
        assert model["load_state"] == "NORMAL"
        assert model["source"] == "SIMULATION"

    def test_over_capacity(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus_over_capacity()
        model = get_capacity_model(bus)
        assert model["load_state"] == "OVER_CAPACITY"
        assert model["utilization_pct"] > 100
        assert model["available_seats"] < 0

    def test_near_capacity(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus(passengers=55, capacity=60)
        model = get_capacity_model(bus)
        assert model["load_state"] == "NEAR_CAPACITY"

    def test_high_load(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus(passengers=50, capacity=60)
        model = get_capacity_model(bus)
        assert model["load_state"] == "HIGH"

    def test_empty_bus(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus(passengers=5, capacity=60)
        model = get_capacity_model(bus)
        assert model["load_state"] == "EMPTY"

    def test_zero_capacity(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus(passengers=10, capacity=0)
        model = get_capacity_model(bus)
        assert model["load_state"] == "UNKNOWN"

    def test_live_bus_source(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus()
        bus["_live"] = True
        bus["simulation"] = False
        model = get_capacity_model(bus)
        assert model["source"] == "LIVE"

    def test_source_simulation(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus()
        bus["simulation"] = True
        model = get_capacity_model(bus)
        assert model["source"] == "SIMULATION"

    def test_cabin_occupancy_integration(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus(passengers=30)
        bus["cabin_occupancy"] = {
            "status": "CONNECTED",
            "occupancy_count": 45,
            "occupancy_percentage": 75.0,
            "crowding_level": "HIGH",
            "source": "HEURISTIC",
        }
        model = get_capacity_model(bus)
        assert model["current_occupancy"] == 45
        assert model["source"] == "HEURISTIC"


# ---------------------------------------------------------------------------
# OccupancySnapshot
# ---------------------------------------------------------------------------

class TestOccupancySnapshot:
    def test_valid_bus(self):
        from demand_intelligence import get_occupancy_snapshot
        bus = _make_bus(passengers=40, capacity=60)
        snap = get_occupancy_snapshot(bus)
        assert snap["bus_id"] == "T-001"
        assert snap["passengers"] == 40
        assert snap["capacity"] == 60
        assert snap["pct"] > 60
        assert snap["crowd_level"] in ("MODERATE", "HIGH", "CRITICAL")
        assert snap["source"] == "SIMULATION"

    def test_critical_crowding(self):
        from demand_intelligence import get_occupancy_snapshot
        bus = _make_bus(passengers=55, capacity=60)
        snap = get_occupancy_snapshot(bus)
        assert snap["crowd_level"] == "CRITICAL"

    def test_normal_crowding(self):
        from demand_intelligence import get_occupancy_snapshot
        bus = _make_bus(passengers=20, capacity=60)
        snap = get_occupancy_snapshot(bus)
        assert snap["crowd_level"] == "NORMAL"

    def test_cabin_data_used(self):
        from demand_intelligence import get_occupancy_snapshot
        bus = _make_bus(passengers=20)
        bus["cabin_occupancy"] = {
            "status": "CONNECTED",
            "occupancy_count": 50,
            "occupancy_percentage": 83.3,
            "crowding_level": "HIGH",
            "source": "HEURISTIC",
        }
        snap = get_occupancy_snapshot(bus)
        assert snap["passengers"] == 50
        assert snap["cabin_source"] == "HEURISTIC"
        assert snap["cabin_count"] == 50

    def test_cabin_disconnected_ignored(self):
        from demand_intelligence import get_occupancy_snapshot
        bus = _make_bus(passengers=20)
        bus["cabin_occupancy"] = {
            "status": "DISCONNECTED",
            "occupancy_count": None,
        }
        snap = get_occupancy_snapshot(bus)
        assert snap["passengers"] == 20  # Falls back to sim
        # cabin_source is not included when cabin is disconnected
        assert "cabin_source" not in snap


# ---------------------------------------------------------------------------
# DemandPattern
# ---------------------------------------------------------------------------

class TestDemandPattern:
    def test_valid_bus(self):
        from demand_intelligence import get_demand_pattern
        bus = _make_bus()
        pattern = get_demand_pattern(bus)
        assert pattern["route_code"] == "MTC-1"
        assert pattern["daily_boardings"] == 600
        assert pattern["peak_boardings"] > 0
        assert pattern["source"] == "SIMULATION"

    def test_peak_hour_detected(self):
        from demand_intelligence import get_demand_pattern
        bus = _make_bus()
        bus["boarding_peak_hour"] = 8
        bus["boarding_by_hour"]["8"] = 80
        pattern = get_demand_pattern(bus)
        assert pattern["peak_hour"] == 8
        assert pattern["peak_boardings"] == 80

    def test_live_bus_source(self):
        from demand_intelligence import get_demand_pattern
        bus = _make_bus()
        bus["_live"] = True
        bus["simulation"] = False
        pattern = get_demand_pattern(bus)
        assert pattern["source"] == "LIVE"

    def test_unknown_when_no_data(self):
        from demand_intelligence import get_demand_pattern
        bus = _make_bus()
        bus["boarding_by_hour"] = {}
        bus["daily_boarding_total"] = 0
        pattern = get_demand_pattern(bus)
        assert pattern["current_demand"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# CapacityPressure
# ---------------------------------------------------------------------------

class TestCapacityPressure:
    def test_normal_pressure(self):
        from demand_intelligence import get_capacity_pressure
        bus = _make_bus(passengers=20, capacity=60)
        pressure = get_capacity_pressure(bus, forecast_boardings=5)
        assert pressure["pressure_level"] == "NORMAL"
        assert pressure["pressure_pct"] < 70

    def test_watch_pressure(self):
        from demand_intelligence import get_capacity_pressure
        bus = _make_bus(passengers=40, capacity=60)
        pressure = get_capacity_pressure(bus, forecast_boardings=10)
        assert pressure["pressure_level"] in ("WATCH", "HIGH_PRESSURE", "CRITICAL")

    def test_critical_pressure(self):
        from demand_intelligence import get_capacity_pressure
        bus = _make_bus(passengers=55, capacity=60)
        pressure = get_capacity_pressure(bus, forecast_boardings=10)
        assert pressure["pressure_level"] == "CRITICAL"

    def test_no_forecast(self):
        from demand_intelligence import get_capacity_pressure
        bus = _make_bus(passengers=30, capacity=60)
        pressure = get_capacity_pressure(bus, forecast_boardings=0)
        assert pressure["forecast_demand"] == 0


# ---------------------------------------------------------------------------
# Overcrowding Detection
# ---------------------------------------------------------------------------

class TestOvercrowdingDetection:
    def test_no_overcrowding_normal_bus(self):
        from demand_intelligence import detect_overcrowding
        bus = _make_bus(passengers=30, capacity=60)
        event = detect_overcrowding(bus)
        assert event is None

    def test_first_overcrowding_observation(self):
        from demand_intelligence import detect_overcrowding
        bus = _make_bus(passengers=55, capacity=60)
        event = detect_overcrowding(bus)
        assert event is not None
        assert event["severity"] == "WARNING"
        assert event["sustained"] is False
        assert event["observation_count"] == 1

    def test_sustained_overcrowding(self):
        from demand_intelligence import detect_overcrowding, demand_intelligence_engine
        bus = _make_bus(passengers=55, capacity=60)
        # Reset state
        demand_intelligence_engine._overcrowding_counts.clear()
        # First observation
        detect_overcrowding(bus)
        # Second observation
        detect_overcrowding(bus)
        # Third observation (sustained)
        event = detect_overcrowding(bus)
        assert event is not None
        assert event["severity"] == "CRITICAL"
        assert event["sustained"] is True
        assert event["observation_count"] == 3

    def test_recovery_resets_count(self):
        from demand_intelligence import detect_overcrowding, demand_intelligence_engine
        bus_over = _make_bus(passengers=55, capacity=60)
        bus_normal = _make_bus(passengers=30, capacity=60)
        demand_intelligence_engine._overcrowding_counts.clear()
        # Build up count
        detect_overcrowding(bus_over)
        detect_overcrowding(bus_over)
        # Recovery
        event = detect_overcrowding(bus_normal)
        assert event is None
        assert demand_intelligence_engine._overcrowding_counts.get("T-001", 0) == 0


# ---------------------------------------------------------------------------
# Route Demand Summary
# ---------------------------------------------------------------------------

class TestRouteDemandSummary:
    def test_summary_structure(self):
        from demand_intelligence import get_route_demand_summary
        buses = [_make_bus(f"B-{i}", route_code="MTC-1") for i in range(5)]
        routes = get_route_demand_summary(buses)
        assert "MTC-1" in routes
        route = routes["MTC-1"]
        assert route["bus_count"] == 5
        assert route["total_passengers"] > 0
        assert route["total_capacity"] == 300

    def test_multiple_routes(self):
        from demand_intelligence import get_route_demand_summary
        buses = [
            _make_bus("B-1", route_code="MTC-1"),
            _make_bus("B-2", route_code="MTC-2"),
        ]
        routes = get_route_demand_summary(buses)
        assert "MTC-1" in routes
        assert "MTC-2" in routes


# ---------------------------------------------------------------------------
# Fleet Load Summary
# ---------------------------------------------------------------------------

class TestFleetLoadSummary:
    def test_summary_structure(self):
        from demand_intelligence import get_fleet_load_summary
        buses = [_make_bus(f"B-{i}") for i in range(5)]
        summary = get_fleet_load_summary(buses)
        assert summary["total_buses"] == 5
        assert "load_distribution" in summary
        assert "crowding_distribution" in summary
        assert "source_distribution" in summary

    def test_overloaded_buses_identified(self):
        from demand_intelligence import get_fleet_load_summary
        buses = [_make_bus(f"B-{i}") for i in range(3)]
        buses.append(_make_bus_over_capacity("OVER-1"))
        summary = get_fleet_load_summary(buses)
        assert "OVER-1" in summary["overloaded_buses"]

    def test_source_honesty(self):
        from demand_intelligence import get_fleet_load_summary
        buses = [_make_bus(f"B-{i}") for i in range(3)]
        summary = get_fleet_load_summary(buses)
        assert summary["source"] == "HEURISTIC"
        assert "note" in summary


# ---------------------------------------------------------------------------
# Source Honesty
# ---------------------------------------------------------------------------

class TestSourceHonesty:
    def test_simulation_bus_labeled(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus()
        bus["simulation"] = True
        model = get_capacity_model(bus)
        assert model["source"] == "SIMULATION"

    def test_live_bus_labeled(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus()
        bus["_live"] = True
        bus["simulation"] = False
        model = get_capacity_model(bus)
        assert model["source"] == "LIVE"

    def test_unknown_when_no_flag(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus()
        bus["simulation"] = False
        bus["_live"] = False
        model = get_capacity_model(bus)
        assert model["source"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestLoadPersistence:
    def test_persist_and_load_snapshot(self):
        from persistence import persist_load_snapshot, load_load_snapshots
        persist_load_snapshot(
            bus_id="PERSIST-001",
            route_code="MTC-1",
            passengers=45,
            capacity=60,
            utilization_pct=75.0,
            load_state="HIGH",
            crowd_level="HIGH",
            source="SIMULATION",
            simulation=True,
        )
        snapshots = load_load_snapshots(bus_id="PERSIST-001")
        assert len(snapshots) >= 1
        snap = snapshots[0]
        assert snap["bus_id"] == "PERSIST-001"
        assert snap["passengers"] == 45
        assert snap["load_state"] == "HIGH"

    def test_truncate_clears_load_snapshots(self):
        from persistence import persist_load_snapshot, load_load_snapshots, truncate
        persist_load_snapshot(
            bus_id="TRUNC-001",
            route_code="MTC-1",
            passengers=30,
            capacity=60,
            utilization_pct=50.0,
            load_state="NORMAL",
            crowd_level="NORMAL",
            source="SIMULATION",
            simulation=True,
        )
        truncate()
        snaps = load_load_snapshots(bus_id="TRUNC-001")
        assert len(snaps) == 0

    def test_route_demand_history(self):
        from persistence import persist_load_snapshot, load_route_demand_history
        persist_load_snapshot(
            bus_id="ROUTE-001",
            route_code="MTC-5",
            passengers=40,
            capacity=60,
            utilization_pct=66.7,
            load_state="NORMAL",
            crowd_level="MODERATE",
            source="SIMULATION",
            simulation=True,
        )
        history = load_route_demand_history("MTC-5")
        assert len(history) >= 1
        assert history[0]["route_code"] == "MTC-5"


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_capacity_bus(self):
        from demand_intelligence import get_capacity_model, get_occupancy_snapshot
        bus = _make_bus(passengers=0, capacity=0)
        model = get_capacity_model(bus)
        snap = get_occupancy_snapshot(bus)
        assert model["load_state"] == "UNKNOWN"
        assert snap["crowd_level"] == "UNKNOWN"

    def test_negative_passengers(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus(passengers=-5, capacity=60)
        model = get_capacity_model(bus)
        # Should handle gracefully
        assert model["current_occupancy"] == -5

    def test_very_high_occupancy(self):
        from demand_intelligence import get_capacity_model
        bus = _make_bus(passengers=100, capacity=60)
        model = get_capacity_model(bus)
        assert model["load_state"] == "OVER_CAPACITY"
        assert model["utilization_pct"] > 100

    def test_bus_without_journey(self):
        from demand_intelligence import get_demand_pattern
        bus = _make_bus()
        bus["journey"] = {}
        pattern = get_demand_pattern(bus)
        # Should handle gracefully
        assert pattern["route_code"] == "MTC-1"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_capacity_thresholds_ordered(self):
        from demand_intelligence import CAPACITY_THRESHOLDS
        assert CAPACITY_THRESHOLDS["EMPTY_MAX"] < CAPACITY_THRESHOLDS["LOW_MAX"]
        assert CAPACITY_THRESHOLDS["LOW_MAX"] < CAPACITY_THRESHOLDS["NORMAL_MAX"]
        assert CAPACITY_THRESHOLDS["NORMAL_MAX"] < CAPACITY_THRESHOLDS["HIGH_MAX"]
        assert CAPACITY_THRESHOLDS["HIGH_MAX"] < CAPACITY_THRESHOLDS["NEAR_CAPACITY_MAX"]

    def test_crowding_thresholds_ordered(self):
        from demand_intelligence import CROWDING_THRESHOLDS
        assert CROWDING_THRESHOLDS["NORMAL_MAX"] < CROWDING_THRESHOLDS["MODERATE_MAX"]
        assert CROWDING_THRESHOLDS["MODERATE_MAX"] < CROWDING_THRESHOLDS["HIGH_MAX"]

    def test_pressure_thresholds_ordered(self):
        from demand_intelligence import CAPACITY_PRESSURE_THRESHOLDS
        assert CAPACITY_PRESSURE_THRESHOLDS["NORMAL_MAX"] < CAPACITY_PRESSURE_THRESHOLDS["WATCH_MAX"]
        assert CAPACITY_PRESSURE_THRESHOLDS["WATCH_MAX"] < CAPACITY_PRESSURE_THRESHOLDS["HIGH_PRESSURE_MAX"]


# ---------------------------------------------------------------------------
# Demand module (updated)
# ---------------------------------------------------------------------------

class TestDemandModule:
    def test_demand_has_source_label(self, rng):
        from demand import demand_engine
        bus = _make_bus()
        fc = demand_engine.forecast_bus(bus, rng, 3)
        assert len(fc) > 0
        for f in fc:
            assert f.source == "SIMULATION"

    def test_demand_confidence_is_none(self, rng):
        from demand import demand_engine
        bus = _make_bus()
        fc = demand_engine.forecast_bus(bus, rng, 3)
        for f in fc:
            assert f.confidence is None  # No synthetic random confidence

    def test_demand_with_friction(self, rng):
        from demand import demand_engine
        bus = _make_bus()
        fc = demand_engine.forecast_bus(bus, rng, 3)
        # Friction factor should be 1.0 when no road risk zones exist
        for f in fc:
            assert f.friction_factor == 1.0

    def test_empty_bus_no_forecast(self, rng):
        from demand import demand_engine
        bus = _make_bus()
        bus["daily_boarding_total"] = 0
        fc = demand_engine.forecast_bus(bus, rng, 3)
        assert len(fc) == 0
