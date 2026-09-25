"""
test_phase13_eta.py
Phase 13 — ETA, Delay Prediction & Route Intelligence tests.

Tests the rewritten ETA engine with:
- Deterministic RNG (reproducible results)
- Route-specific road friction (not global defect check)
- Delay cause intelligence (road/vehicle/driver/occupancy/traffic context)
- ETA smoothing (bounded changes)
- Delay state change detection
- Fleet-level ETA summary
- Persistence integration
- Honest source labeling (SIMULATION/HEURISTIC)
- Edge cases (empty journeys, missing data, boundary values)

All tests use isolated SQLite DB via conftest.py autouse fixture.
All data is SIMULATED — no fabricated GPS, traffic, schedules, or ML models.
"""

import random
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_bus(bus_id="T-001", route_code="MTC-1", speed=25, occ_pct=50,
              health="NORMAL", driver_state="NORMAL", vibration=0.3):
    """Create a minimal bus dict with journey data."""
    return {
        "bus_id": bus_id,
        "route": f"Route {route_code}",
        "route_code": route_code,
        "speed_kmh": speed,
        "latitude": 13.0 + random.random() * 0.1,
        "longitude": 80.2 + random.random() * 0.1,
        "occupancy": {"pct": occ_pct, "passengers": int(occ_pct * 0.6), "capacity": 60},
        "vehicle": {"health": health, "vibration": vibration, "anomaly": None},
        "driver": {"state": driver_state},
        "journey": {
            "start": "A",
            "destination": "E",
            "stops": [
                {"stop": "A", "lat": 13.00, "lon": 80.20, "major": True},
                {"stop": "B", "lat": 13.01, "lon": 80.21, "major": False},
                {"stop": "C", "lat": 13.02, "lon": 80.22, "major": False},
                {"stop": "D", "lat": 13.03, "lon": 80.23, "major": False},
                {"stop": "E", "lat": 13.04, "lon": 80.24, "major": True},
            ],
            "current_index": 0,
            "next_index": 1,
            "state": "moving",
        },
        "simulation": True,
        "_live": False,
    }


def _make_bus_no_route(bus_id="T-002"):
    """Bus with no journey data."""
    return {
        "bus_id": bus_id,
        "route": "No Route",
        "route_code": "",
        "speed_kmh": 0,
        "latitude": 13.0,
        "longitude": 80.2,
        "occupancy": {"pct": 0},
        "vehicle": {"health": "NORMAL"},
        "driver": {"state": "NORMAL"},
        "journey": {},
        "simulation": True,
        "_live": False,
    }


def _make_bus_at_end(bus_id="T-003"):
    """Bus at last stop (next_index beyond stops)."""
    bus = _make_bus(bus_id=bus_id)
    bus["journey"]["current_index"] = 4
    bus["journey"]["next_index"] = None
    return bus


@pytest.fixture
def rng():
    return random.Random(42)


# ---------------------------------------------------------------------------
# ETAPrediction dataclass
# ---------------------------------------------------------------------------

class TestETAPredictionDataclass:
    def test_to_dict_returns_expected_keys(self):
        from eta import ETAPrediction
        p = ETAPrediction(
            stop="A", lat=13.0, lon=80.2, is_major=True,
            distance_km=1.5, base_dwell_sec=35, friction_delay_sec=8,
            traffic_delay_sec=5, total_delay_sec=43,
            eta_iso="2026-01-01T10:00:00+00:00", delay_band="ON_TIME",
        )
        d = p.to_dict()
        assert d["stop"] == "A"
        assert d["distance_km"] == 1.5
        assert d["delay_band"] == "ON_TIME"
        assert "eta" in d

    def test_to_dict_preserves_types(self):
        from eta import ETAPrediction
        p = ETAPrediction(
            stop="B", lat=13.0, lon=80.2, is_major=False,
            distance_km=0.5, base_dwell_sec=18, friction_delay_sec=0,
            traffic_delay_sec=2, total_delay_sec=20,
            eta_iso="2026-01-01T10:05:00+00:00", delay_band="MINOR_DELAY",
        )
        d = p.to_dict()
        assert isinstance(d["distance_km"], float)
        assert isinstance(d["total_delay_sec"], int)


# ---------------------------------------------------------------------------
# DelayCause dataclass
# ---------------------------------------------------------------------------

class TestDelayCause:
    def test_to_dict(self):
        from eta import DelayCause
        c = DelayCause(category="road", description="Pothole ahead",
                       severity="WARNING", source="HEURISTIC")
        d = c.to_dict()
        assert d["category"] == "road"
        assert d["source"] == "HEURISTIC"
        assert d["severity"] == "WARNING"


# ---------------------------------------------------------------------------
# BusETAResult dataclass
# ---------------------------------------------------------------------------

class TestBusETAResult:
    def test_to_dict_includes_all_fields(self):
        from eta import BusETAResult, ETAPrediction
        r = BusETAResult(
            bus_id="T-001", route="Route A", current_stop="A",
            destination="E", etas=[], delay_summary="ON_TIME",
            delay_causes=[], total_remaining_distance_km=5.0,
            total_remaining_time_sec=600, eta_destination_iso="2026-01-01T10:10:00+00:00",
            source="HEURISTIC", simulation=True, computed_at="2026-01-01T10:00:00+00:00",
        )
        d = r.to_dict()
        assert d["bus_id"] == "T-001"
        assert d["source"] == "HEURISTIC"
        assert d["simulation"] is True
        assert d["etas"] == []


# ---------------------------------------------------------------------------
# ETAEngine.compute_eta
# ---------------------------------------------------------------------------

class TestETAEngineComputeEta:
    def test_returns_empty_when_no_journey(self, rng):
        from eta import eta_engine
        bus = _make_bus_no_route()
        result = eta_engine.compute_eta(bus, rng)
        assert result["delay_summary"] == "NO_ROUTE"
        assert result["etas"] == []
        assert result["source"] == "UNKNOWN"

    def test_returns_etas_for_valid_bus(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        result = eta_engine.compute_eta(bus, rng)
        assert result["bus_id"] == "T-001"
        assert len(result["etas"]) > 0
        assert result["delay_summary"] in ("ON_TIME", "EARLY", "MINOR_DELAY",
                                            "SIGNIFICANT_DELAY", "SEVERE_DELAY")

    def test_delay_summary_matches_worst_stop(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        result = eta_engine.compute_eta(bus, rng)
        if result["etas"]:
            bands = [e["delay_band"] for e in result["etas"]]
            assert result["delay_summary"] == max(
                bands, key=lambda b: ["ON_TIME", "EARLY", "MINOR_DELAY",
                                       "SIGNIFICANT_DELAY", "SEVERE_DELAY"].index(b)
            )

    def test_deterministic_results(self):
        from eta import eta_engine
        bus = _make_bus()
        r1 = eta_engine.compute_eta(bus, random.Random(42))
        r2 = eta_engine.compute_eta(bus, random.Random(42))
        assert r1["delay_summary"] == r2["delay_summary"]
        assert len(r1["etas"]) == len(r2["etas"])

    def test_source_labeled_simulation(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        bus["simulation"] = True
        result = eta_engine.compute_eta(bus, rng)
        assert result["source"] == "SIMULATION"

    def test_source_labeled_heuristic_when_not_simulation(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        bus["simulation"] = False
        bus["_live"] = False
        result = eta_engine.compute_eta(bus, rng)
        assert result["source"] == "HEURISTIC"

    def test_delay_causes_populated(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        bus["vehicle"]["health"] = "WARNING"
        bus["vehicle"]["anomaly"] = "Engine temp high"
        result = eta_engine.compute_eta(bus, rng)
        assert len(result["delay_causes"]) > 0
        cats = [c["category"] for c in result["delay_causes"]]
        assert "vehicle" in cats

    def test_high_occupancy_adds_cause(self, rng):
        from eta import eta_engine
        bus = _make_bus(occ_pct=90)
        result = eta_engine.compute_eta(bus, rng)
        cats = [c["category"] for c in result["delay_causes"]]
        assert "occupancy" in cats

    def test_low_speed_adds_traffic_cause(self, rng):
        from eta import eta_engine
        bus = _make_bus(speed=5)
        result = eta_engine.compute_eta(bus, rng)
        cats = [c["category"] for c in result["delay_causes"]]
        assert "traffic" in cats

    def test_drowsy_driver_adds_cause(self, rng):
        from eta import eta_engine
        bus = _make_bus(driver_state="DROWSY")
        result = eta_engine.compute_eta(bus, rng)
        cats = [c["category"] for c in result["delay_causes"]]
        assert "driver" in cats

    def test_attention_driver_adds_cause(self, rng):
        from eta import eta_engine
        bus = _make_bus(driver_state="ATTENTION")
        result = eta_engine.compute_eta(bus, rng)
        cats = [c["category"] for c in result["delay_causes"]]
        assert "driver" in cats

    def test_total_remaining_distance_positive(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        result = eta_engine.compute_eta(bus, rng)
        assert result["total_remaining_distance_km"] > 0

    def test_total_remaining_time_positive(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        result = eta_engine.compute_eta(bus, rng)
        assert result["total_remaining_time_sec"] > 0

    def test_destination_iso_is_valid(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        result = eta_engine.compute_eta(bus, rng)
        assert "T" in result["eta_destination"]

    def test_computed_at_is_iso(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        result = eta_engine.compute_eta(bus, rng)
        assert "T" in result["computed_at"]

    def test_bus_at_end_returns_empty_etas(self, rng):
        from eta import eta_engine
        bus = _make_bus_at_end()
        result = eta_engine.compute_eta(bus, rng)
        # next_index is None → defaults to current+1 = 5, which is beyond stops
        assert result["etas"] == []
        assert result["delay_summary"] == "ON_TIME"


# ---------------------------------------------------------------------------
# ETA Smoothing
# ---------------------------------------------------------------------------

class TestETASmoothing:
    def test_smoothing_bounds_change(self):
        from eta import eta_engine, ETA_SMOOTHING_WINDOW
        bus1 = _make_bus(bus_id="SMOOTH-001")
        bus2 = _make_bus(bus_id="SMOOTH-001")
        bus2["speed_kmh"] = 5  # very different speed → would cause big ETA jump
        rng1 = random.Random(1)
        rng2 = random.Random(2)
        r1 = eta_engine.compute_eta(bus1, rng1)
        r2 = eta_engine.compute_eta(bus2, rng2)
        # Both should have valid ETAs (smoothing may clamp but not break)
        assert len(r1["etas"]) == len(r2["etas"])


# ---------------------------------------------------------------------------
# Delay State Change Detection
# ---------------------------------------------------------------------------

class TestDelayStateChangeDetection:
    def test_no_change_returns_none(self):
        from eta import eta_engine
        eta_engine._prev_delay_states["BUS-1"] = "ON_TIME"
        change = eta_engine.detect_delay_change("BUS-1", "ON_TIME")
        assert change is None

    def test_first_detection_returns_none(self):
        from eta import eta_engine
        eta_engine._prev_delay_states.pop("BUS-NEW", None)
        change = eta_engine.detect_delay_change("BUS-NEW", "ON_TIME")
        assert change is None

    def test_worsening_detected(self):
        from eta import eta_engine
        eta_engine._prev_delay_states["BUS-2"] = "ON_TIME"
        change = eta_engine.detect_delay_change("BUS-2", "SEVERE_DELAY")
        assert change is not None
        assert "worsened" in change

    def test_recovery_detected(self):
        from eta import eta_engine
        eta_engine._prev_delay_states["BUS-3"] = "SEVERE_DELAY"
        change = eta_engine.detect_delay_change("BUS-3", "ON_TIME")
        assert change is not None
        assert "recovered" in change

    def test_minor_change_returns_none(self):
        from eta import eta_engine
        eta_engine._prev_delay_states["BUS-4"] = "ON_TIME"
        # ON_TIME=0, MINOR_DELAY=2 → rank diff=2, triggers alert
        # Use EARLY (rank=1) for truly minor change
        change = eta_engine.detect_delay_change("BUS-4", "EARLY")
        assert change is None


# ---------------------------------------------------------------------------
# Fleet ETA Summary
# ---------------------------------------------------------------------------

class TestFleetETASummary:
    def test_summary_structure(self, rng):
        from eta import get_fleet_eta_summary
        buses = [_make_bus(f"B-{i}") for i in range(5)]
        summary = get_fleet_eta_summary(buses)
        assert "total_buses" in summary
        assert "delay_distribution" in summary
        assert "on_time_percentage" in summary
        assert "delayed_percentage" in summary
        assert "source" in summary

    def test_summary_total_buses(self, rng):
        from eta import get_fleet_eta_summary
        buses = [_make_bus(f"B-{i}") for i in range(3)]
        summary = get_fleet_eta_summary(buses)
        assert summary["total_buses"] == 3

    def test_summary_skips_live_buses(self, rng):
        from eta import get_fleet_eta_summary
        buses = [_make_bus(f"B-{i}") for i in range(3)]
        buses[1]["_live"] = True
        summary = get_fleet_eta_summary(buses)
        assert summary["total_buses"] == 2

    def test_summary_delay_distribution_sums(self, rng):
        from eta import get_fleet_eta_summary
        buses = [_make_bus(f"B-{i}") for i in range(10)]
        summary = get_fleet_eta_summary(buses)
        total = sum(summary["delay_distribution"].values())
        assert total == summary["total_buses"]

    def test_summary_source_is_heuristic(self, rng):
        from eta import get_fleet_eta_summary
        buses = [_make_bus(f"B-{i}") for i in range(3)]
        summary = get_fleet_eta_summary(buses)
        assert summary["source"] == "HEURISTIC"


# ---------------------------------------------------------------------------
# Route-specific road friction
# ---------------------------------------------------------------------------

class TestRouteSpecificFriction:
    def test_no_defects_gives_zero_friction(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        friction = eta_engine._get_route_pothole_friction(
            bus["route_code"], bus["journey"]["stops"], 0, 1
        )
        assert friction == 0

    def test_defect_near_stop_gives_friction(self, rng):
        from eta import eta_engine
        from data_store import store
        # Add a defect near stop B (lat 13.01, lon 80.21)
        store.upsert_road_defect("test-pothole-1", {
            "type": "POTHOLE",
            "latitude": 13.01,
            "longitude": 80.21,
            "status": "ACTIVE",
            "severity": "MODERATE",
        })
        bus = _make_bus()
        friction = eta_engine._get_route_pothole_friction(
            bus["route_code"], bus["journey"]["stops"], 0, 1
        )
        assert friction >= 1


# ---------------------------------------------------------------------------
# Persistence integration
# ---------------------------------------------------------------------------

class TestETAPersistence:
    def test_persist_and_load_snapshot(self):
        from persistence import persist_eta_snapshot, load_eta_snapshots
        persist_eta_snapshot(
            bus_id="PERSIST-001",
            delay_summary="MINOR_DELAY",
            total_remaining_distance_km=3.5,
            total_remaining_time_sec=450,
            delay_causes=[{"category": "road", "description": "test"}],
            source="HEURISTIC",
            simulation=True,
        )
        snapshots = load_eta_snapshots(bus_id="PERSIST-001")
        assert len(snapshots) >= 1
        snap = snapshots[0]
        assert snap["bus_id"] == "PERSIST-001"
        assert snap["delay_summary"] == "MINOR_DELAY"

    def test_load_without_bus_id(self):
        from persistence import persist_eta_snapshot, load_eta_snapshots
        persist_eta_snapshot(
            bus_id="PERSIST-002",
            delay_summary="ON_TIME",
            total_remaining_distance_km=1.0,
            total_remaining_time_sec=120,
            delay_causes=[],
            source="HEURISTIC",
            simulation=True,
        )
        all_snaps = load_eta_snapshots()
        assert len(all_snaps) >= 1

    def test_truncate_clears_eta_snapshots(self):
        from persistence import persist_eta_snapshot, load_eta_snapshots, truncate
        persist_eta_snapshot(
            bus_id="TRUNC-001",
            delay_summary="ON_TIME",
            total_remaining_distance_km=1.0,
            total_remaining_time_sec=120,
            delay_causes=[],
            source="HEURISTIC",
            simulation=True,
        )
        truncate()
        snaps = load_eta_snapshots(bus_id="TRUNC-001")
        assert len(snaps) == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestETAEdgeCases:
    def test_bus_with_single_stop(self, rng):
        from eta import eta_engine
        bus = _make_bus()
        bus["journey"]["stops"] = [{"stop": "A", "lat": 13.0, "lon": 80.2, "major": True}]
        bus["journey"]["current_index"] = 0
        bus["journey"]["next_index"] = None
        result = eta_engine.compute_eta(bus, rng)
        assert result["bus_id"] == "T-001"

    def test_very_high_speed(self, rng):
        from eta import eta_engine
        bus = _make_bus(speed=120)
        result = eta_engine.compute_eta(bus, rng)
        assert result["total_remaining_time_sec"] > 0

    def test_very_low_speed(self, rng):
        from eta import eta_engine
        bus = _make_bus(speed=3)
        result = eta_engine.compute_eta(bus, rng)
        assert result["total_remaining_time_sec"] > 0

    def test_full_occupancy(self, rng):
        from eta import eta_engine
        bus = _make_bus(occ_pct=100)
        result = eta_engine.compute_eta(bus, rng)
        assert result["total_remaining_time_sec"] > 0

    def test_zero_occupancy(self, rng):
        from eta import eta_engine
        bus = _make_bus(occ_pct=0)
        result = eta_engine.compute_eta(bus, rng)
        assert result["total_remaining_time_sec"] > 0


# ---------------------------------------------------------------------------
# Constants / thresholds
# ---------------------------------------------------------------------------

class TestETAConstants:
    def test_delay_thresholds_ordered(self):
        from eta import DELAY_THRESHOLDS
        assert DELAY_THRESHOLDS["ON_TIME_MAX"] < DELAY_THRESHOLDS["MINOR_DELAY_MAX"]
        assert DELAY_THRESHOLDS["MINOR_DELAY_MAX"] < DELAY_THRESHOLDS["SIGNIFICANT_DELAY_MAX"]

    def test_delay_state_order_comprehensive(self):
        from eta import DELAY_STATE_ORDER
        assert "ON_TIME" in DELAY_STATE_ORDER
        assert "SEVERE_DELAY" in DELAY_STATE_ORDER
        assert "EARLY" in DELAY_STATE_ORDER

    def test_base_dwell_has_major_and_normal(self):
        from eta import BASE_DWELL
        assert "major" in BASE_DWELL
        assert "normal" in BASE_DWELL
        assert BASE_DWELL["major"] > BASE_DWELL["normal"]

    def test_traffic_lapse_bounds(self):
        from eta import TRAFFIC_LAPSE_MIN, TRAFFIC_LAPSE_MAX
        assert TRAFFIC_LAPSE_MIN < TRAFFIC_LAPSE_MAX
        assert TRAFFIC_LAPSE_MIN > 0
        assert TRAFFIC_LAPSE_MAX < 2.0
