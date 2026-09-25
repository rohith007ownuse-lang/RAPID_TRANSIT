"""
tests/test_traffic_engine.py
Unit tests for the traffic heat-map engine: 5+ buses within 150 m for >60 s
creates an ACTIVE red-dot hotspot; dispersal silences it; long absence evicts
it; six or more dots within 200 m merge into ONE blink-only super-zone.
"""

from traffic_engine import TrafficMonitor, EVICT_AFTER_SEC


def _buses(n, lat=13.0827, lon=80.2747, lat_step=1e-5, lon_step=0.0):
    """n buses clustered within a few metres by default (1e-5 deg ~ 1 m)."""
    return [
        {"bus_id": f"BUS-{i}", "latitude": lat + i * lat_step, "longitude": lon + i * lon_step}
        for i in range(n)
    ]


def test_four_buses_never_create_hotspot():
    tm = TrafficMonitor()
    for now in (0.0, 30.0, 60.0, 120.0):
        tm.update(_buses(4), now=now)
    assert tm.get_hotspots(now=120.0) == []


def test_buses_far_apart_do_not_cluster():
    tm = TrafficMonitor()
    # one bus parked a full kilometre away (~0.02 deg lat) cannot join the bunch
    buses = [
        {"bus_id": "A", "latitude": 13.0827, "longitude": 80.2747},
        {"bus_id": "B", "latitude": 13.08271, "longitude": 80.2747},
        {"bus_id": "C", "latitude": 13.1027, "longitude": 80.2747},
    ]
    for now in (0.0, 30.0, 60.0, 120.0):
        tm.update(buses, now=now)
    assert tm.get_hotspots(now=120.0) == []


def test_five_buses_activate_after_window():
    tm = TrafficMonitor()
    tm.update(_buses(5), now=0.0)
    # inside the 60 s window -> not yet active
    tm.update(_buses(5), now=30.0)
    assert tm.get_hotspots(now=50.0) == []
    # window satisfied -> active
    tm.update(_buses(5), now=60.0)
    spots = tm.get_hotspots(now=60.0)
    assert len(spots) == 1
    assert spots[0]["bus_count"] >= 5
    assert spots[0]["duration_sec"] is not None


def test_hotspot_blinks_out_on_dispersal():
    tm = TrafficMonitor()
    tm.update(_buses(5), now=0.0)
    tm.update(_buses(5), now=60.0)
    assert len(tm.get_hotspots(now=60.0)) == 1
    # only a couple of buses remain near the spot -> no longer a traffic zone
    tm.update(_buses(2), now=61.0)
    assert tm.get_hotspots(now=61.0) == []


def test_long_absence_evicts_hotspot():
    tm = TrafficMonitor()
    tm.update(_buses(5), now=0.0)
    tm.update(_buses(5), now=30.0)
    # the old zone is evicted once unseen for EVICT_AFTER_SEC; only the new
    # single-bus zone (from the far-away bus) remains tracked
    tm.update(_buses(1, lat=13.2, lon=80.3), now=30.0 + EVICT_AFTER_SEC + 1.0)
    now = 30.0 + EVICT_AFTER_SEC + 1.0
    assert tm.get_hotspots(now=now) == []
    assert tm.analytics(now=now)["tracked_zones"] == 1  # old zone evicted, new lone one tracked


def test_analytics_reflects_active_zones():
    tm = TrafficMonitor()
    tm.update(_buses(5), now=0.0)
    tm.update(_buses(7), now=70.0)
    a = tm.analytics(now=70.0)
    assert a["active_count"] == 1
    assert a["max_buses_in_one_zone"] == 7


def _dots(lats, per_dot=5, lon=80.2747):
    """One fleet snapshot containing one 5-bus dot at every lat given."""
    buses = []
    for gi, lat in enumerate(lats):
        for j in range(per_dot):
            buses.append({"bus_id": f"D{gi}-{j}", "latitude": lat, "longitude": lon})
    return buses


def test_six_dots_within_200m_merge_into_one_blink_only_zone():
    tm = TrafficMonitor()
    # build 6 separate red dots in a chain: neighbours ~178 m apart (0.0016 deg
    # lat) so each dot is its own 150 m cluster yet within 200 m of the next
    # one for the super-merge
    lats = [13.0827 + i * 0.0016 for i in range(6)]
    for now in (0.0, 61.0):
        tm.update(_dots(lats), now=now)
    spots = tm.get_hotspots(now=61.0)
    assert len(spots) == 1
    super_zone = spots[0]
    assert super_zone["merged"] is True
    assert super_zone["blink_only"] is True
    assert super_zone["level"] == "CRITICAL"
    assert super_zone["radius_m"] == 200
    assert super_zone["member_count"] == 6


def test_dots_spread_beyond_200m_stay_separate():
    tm = TrafficMonitor()
    # 6 dots but neighbours ~0.004 deg (~445 m) apart -> beyond the 200 m merge
    lats = [13.0827 + i * 0.004 for i in range(6)]
    for now in (0.0, 61.0):
        tm.update(_dots(lats), now=now)
    spots = tm.get_hotspots(now=61.0)
    assert len(spots) == 6
    assert all(not s.get("merged") for s in spots)


def test_recovery_after_long_dip_restarts_window_at_now():
    tm = TrafficMonitor()
    base = 1_700_000_000.0  # realistic epoch-scale clock (regression: dip
    # timestamp must never be subtracted from now -> epoch-era active_since)
    tm.update(_buses(5), now=base)
    tm.update(_buses(5), now=base + 61.0)
    assert len(tm.get_hotspots(now=base + 61.0)) == 1
    # long dip: bunch disperses, hysteresis clears the activation
    tm.update(_buses(2), now=base + 62.0)
    tm.update(_buses(2), now=base + 80.0)
    assert tm.get_hotspots(now=base + 80.0) == []
    # bunch reforms -> fresh 60 s window starts NOW, not an absurd duration
    tm.update(_buses(6), now=base + 100.0)
    assert tm.get_hotspots(now=base + 100.0) == []  # window not yet satisfied
    tm.update(_buses(6), now=base + 161.0)
    spots = tm.get_hotspots(now=base + 161.0)
    assert len(spots) == 1
    assert spots[0]["duration_sec"] is not None
    assert spots[0]["duration_sec"] < 3600  # sane, not billions of seconds
