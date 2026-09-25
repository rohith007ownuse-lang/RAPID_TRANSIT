"""Tests for traffic intelligence + OD + pedestrian detection (Phases 10-14)."""

import pytest

from ai.road.traffic_detector import TrafficDetectorSource, VEHICLE_CLASS_IDS
from congestion_heatmap import CongestionHeatmap, WEIGHT_CONGESTED, SAMPLE_THRESHOLD
from od_analytics import compute_od
from ai.road.pedestrian_detector import _near_roadway, PedestrianSource


def _bus(bus_id, lat, lon, speed_kmh, traffic=None, route="R1"):
    return {
        "bus_id": bus_id,
        "latitude": lat,
        "longitude": lon,
        "speed_kmh": speed_kmh,
        "route_code": route,
        "traffic": traffic
        or {"total_detections": 0, "class_totals": {}, "tracking_active": False},
    }


def test_traffic_detector_honest_source_labeled():
    assert TrafficDetectorSource.MODEL.value == "MODEL"
    assert "car" in VEHICLE_CLASS_IDS.values()


def test_congestion_heatmap_moving_bus_produces_cell():
    hm = CongestionHeatmap()
    hm.update([_bus("B1", 13.0827, 80.2747, 40.0)], now=1_700_000_000.0)
    heat = hm.get_heat(now=1_700_000_000.0)
    assert heat["cells"], "one moving bus should grid a faint cell"
    assert 0 < heat["cells"][0]["intensity"] <= 1.0


def test_congestion_heatmap_congested_cell_heavier():
    hm = CongestionHeatmap()
    t = 1_700_000_000.0
    buses = [
        _bus("B1", 13.0827, 80.2747, 12.0),
        _bus("B2", 13.0830, 80.2749, 8.0),
        _bus("B3", 13.0825, 80.2745, 6.0),
    ]
    hm.update(buses, now=t)
    cells = hm.get_heat(now=t)["cells"]
    assert cells
    heavy = max(c["weight"] for c in cells)
    assert heavy >= WEIGHT_CONGESTED * SAMPLE_THRESHOLD
    assert cells[0]["intensity"] == 1.0  # strongest cell peaks


def test_pedestrian_near_roadway_geometry():
    frame_h = 480
    near = [300, 380, 340, 470]  # feet deep in bottom 45% + tall box
    far = [300, 60, 340, 150]    # upper frame / short
    assert _near_roadway(near, frame_h) is True
    assert _near_roadway(far, frame_h) is False
    assert _near_roadway([0, 0, 0, 0], 0) is False


def test_pedestrian_source_honest():
    assert PedestrianSource.MODEL.value == "MODEL"


def test_od_analytics_source_honest():
    res = compute_od(limit=0)  # no buses -> honest empty result
    assert res["method"].startswith("gravity-style")
    assert res["total_riders_estimated"] == 0
    assert res["matrix_count"] == 0