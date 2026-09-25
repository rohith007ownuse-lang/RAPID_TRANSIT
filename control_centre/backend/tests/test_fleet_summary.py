"""
test_fleet_summary.py
Phase 8: fleet intelligence dashboard aggregation tests.

Covers the pure build_fleet_summary() contract plus the /api/fleet/summary
endpoint:

  - fleet counts (total / active / normal / warning / critical / offline)
  - classification from existing subsystems (driver, load, occupancy,
    cabin occupancy, vehicle health, risk)
  - offline/stale live assets (with healthy sim buses never counted offline)
  - incident summary counts by severity/status without double counting
  - camera-based vs simulated occupancy separation
  - attention list correct reasons, severities and prioritisation
  - source honesty (simulation flag, live prototype flag)
  - endpoint wiring (open, read-only, uses the in-memory store)
"""

import sys, os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from fleet_summary import build_fleet_summary  # noqa: E402
from data_store import store, mode_state  # noqa: E402
import server  # noqa: E402
from risk_engine import fleet_risk  # noqa: E402


def _iso_ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _bus(bus_id, driver="NORMAL", vehicle="NORMAL", load_status="NORMAL",
         crowd="NORMAL", capacity=60, passengers=0, route_code="19D",
         live=False, live_flag=True, last_s=0, cabin=None, load_pct=50):
    return {
        "bus_id": bus_id,
        "reg_no": f"TN-{bus_id}",
        "route": f"{route_code} - Route {bus_id}",
        "route_code": route_code,
        "speed_kmh": 40.0,
        "last_update": _iso_ago(last_s),
        "data_source": "live" if live else None,
        "_live": live_flag if live else False,
        "simulation": not live,
        "driver": {"state": driver, "name": "D", "fatigue_stage": "WATCH"},
        "vehicle": {"health": vehicle},
        "load": {"status": load_status, "load_pct": load_pct},
        "occupancy": {"passengers": passengers, "pct": round(passengers / capacity * 100) if capacity else 0,
                      "crowd": crowd, "capacity": capacity},
        "cabin_occupancy": cabin,
    }


def _mode(sim=True, connected=None):
    return {"mode": "simulation" if sim else "live", "simulation": sim,
            "connected_nodes": connected or {}}


def _risk(buses, events=()):
    return fleet_risk(buses, list(events), risk_weights={
        "driver": 30, "vehicle": 20, "load": 15, "speed": 10, "occupancy": 10, "history": 15})


@pytest.fixture(autouse=True)
def _clean():
    store.buses.clear()
    store.events.clear()
    store.road_defects.clear()
    mode_state._mode = "simulation"
    mode_state._live_nodes = {}
    yield
    store.buses.clear()
    store.events.clear()
    store.road_defects.clear()


# ---------------------------------------------------------------- fleet counts
class TestFleetCounts:
    def test_all_normal_buses(self):
        buses = [_bus("B1"), _bus("B2"), _bus("B3")]
        s = build_fleet_summary(buses, [], _risk(buses), _mode())
        assert s["fleet_counts"]["total_buses"] == 3
        assert s["fleet_counts"]["active"] == 3
        assert s["fleet_counts"]["normal"] == 3
        assert s["fleet_counts"]["warning"] == 0
        assert s["fleet_counts"]["critical"] == 0
        assert s["fleet_counts"]["offline"] == 0
        assert s["attention"] == []

    def test_critical_warning_normal_bucketing(self):
        buses = [
            _bus("NORM", driver="NORMAL"),
            _bus("WARN", vehicle="WARNING"),
            _bus("CRIT", load_status="CRITICAL OVERLOAD"),
        ]
        s = build_fleet_summary(buses, [], _risk(buses), _mode())
        fc = s["fleet_counts"]
        assert fc["normal"] == 1
        assert fc["warning"] == 1
        assert fc["critical"] == 1
        assert set(s["fleet"]["critical"]) == {"CRIT"}
        assert set(s["fleet"]["warning"]) == {"WARN"}

    def test_offline_live_bus(self):
        stale = _bus("LIVE1", live=True, live_flag=False, last_s=90)
        fresh = _bus("LIVE2", live=True, live_flag=True, last_s=2)
        sim = _bus("SIM1")
        buses = [stale, fresh, sim]
        s = build_fleet_summary(buses, [], _risk(buses), _mode(sim=False))
        fc = s["fleet_counts"]
        assert fc["offline"] == 1
        assert fc["active"] == 2
        assert fc["total_buses"] == 3
        # fresh live bus is active and normal (no conditions)
        assert fc["normal"] == 2  # LIVE2 + SIM1
        entry = next(a for a in s["attention"] if a["bus_id"] == "LIVE1")
        assert entry["severity"] == "OFFLINE"
        assert entry["offline"] is True
        assert "Telemetry stale" in entry["reasons"][0]["text"]

    def test_stale_live_with_age(self):
        stale = _bus("LIVE9", live=True, live_flag=True, last_s=45)
        s = build_fleet_summary([stale], [], _risk([stale]), _mode(sim=False))
        assert s["fleet_counts"]["offline"] == 1
        assert s["attention"][0]["staleness_seconds"] == 45


# ------------------------------------------------------------ reason sources
class TestAttentionReasons:
    def test_driver_drowsy_high(self):
        b = _bus("D1", driver="DROWSY")
        b["driver"]["fatigue_stage"] = "ALERT"
        s = build_fleet_summary([b], [], _risk([b]), _mode())
        e = next(a for a in s["attention"] if a["bus_id"] == "D1")
        assert e["severity"] == "HIGH"
        assert any(r["source"] == "driver_safety" for r in e["reasons"])
        assert any("drowsiness" in r["text"].lower() for r in e["reasons"])

    def test_driver_drowsy_critical_stage(self):
        b = _bus("DC", driver="DROWSY")
        b["driver"]["fatigue_stage"] = "CRITICAL"
        s = build_fleet_summary([b], [], _risk([b]), _mode())
        e = next(a for a in s["attention"] if a["bus_id"] == "DC")
        assert e["severity"] == "CRITICAL"

    def test_driver_attention_warning(self):
        b = _bus("A1", driver="ATTENTION")
        s = build_fleet_summary([b], [], _risk([b]), _mode())
        e = next(a for a in s["attention"] if a["bus_id"] == "A1")
        assert e["severity"] == "WARNING"
        assert any(r["source"] == "driver_safety" for r in e["reasons"])

    def test_vehicle_inspection_high(self):
        b = _bus("V1", vehicle="INSPECTION REQUIRED")
        s = build_fleet_summary([b], [], _risk([b]), _mode())
        e = next(a for a in s["attention"] if a["bus_id"] == "V1")
        assert e["severity"] == "HIGH"
        assert any(r["source"] == "vehicle_health" for r in e["reasons"])

    def test_load_critical(self):
        b = _bus("L1", load_status="CRITICAL OVERLOAD", load_pct=115)
        s = build_fleet_summary([b], [], _risk([b]), _mode())
        e = next(a for a in s["attention"] if a["bus_id"] == "L1")
        assert e["severity"] == "CRITICAL"
        assert any(r["source"] == "load" for r in e["reasons"])

    def test_occupancy_critical_and_high(self):
        bc = _bus("OC1", crowd="CRITICAL CROWDING", passengers=57, capacity=60)
        bh = _bus("OH1", crowd="HIGH", passengers=50, capacity=60)
        s = build_fleet_summary([bc, bh], [], _risk([bc, bh]), _mode())
        ec = next(a for a in s["attention"] if a["bus_id"] == "OC1")
        eh = next(a for a in s["attention"] if a["bus_id"] == "OH1")
        assert ec["severity"] == "CRITICAL"
        assert eh["severity"] == "WARNING"
        assert any(r["source"] == "occupancy" for r in eh["reasons"])

    def test_cabin_camera_reason(self):
        bass = _bus("CAB1", cabin={"status": "CONNECTED", "crowding_level": "CRITICAL",
                                  "occupancy_percentage": 95})
        s = build_fleet_summary([bass], [], _risk([bass]), _mode())
        e = next(a for a in s["attention"] if a["bus_id"] == "CAB1")
        assert e["severity"] == "CRITICAL"
        assert any(r["source"] == "cabin_camera" for r in e["reasons"])


# ---------------------------------------------------------------- priority
class TestPrioritisation:
    def test_ordering_critical_high_warning_offline(self):
        buses = [
            _bus("W1", driver="ATTENTION"),
            _bus("O1", live=True, live_flag=False, last_s=60),
            _bus("C1", load_status="CRITICAL OVERLOAD"),
            _bus("H1", vehicle="INSPECTION REQUIRED"),
        ]
        s = build_fleet_summary(buses, [], _risk(buses), _mode(sim=False))
        order = [a["severity"] for a in s["attention"]]
        # critical first, then high, then warning, then offline (rank desc)
        assert order == ["CRITICAL", "HIGH", "WARNING", "OFFLINE"]

    def test_reason_dedupe_presence(self):
        # a bus flaggedDROWSY + high risk may carry both driver_safety and risk
        b = _bus("R1", driver="DROWSY")
        b["driver"]["fatigue_stage"] = "CRITICAL"
        s = build_fleet_summary([b], [], _risk([b]), _mode())
        e = next(a for a in s["attention"] if a["bus_id"] == "R1")
        assert e["severity"] == "CRITICAL"
        # reasons list is bounded and never empty
        assert 1 <= len(e["reasons"]) <= 4


# ---------------------------------------------------------------- incidents
class TestIncidentSummary:
    def _event(self, eid, sev, status):
        return {"event_id": eid, "severity": sev, "status": status,
                "event_type": "TYPE", "timestamp": _iso_ago(10)}

    def test_counts_by_status_and_severity(self):
        events = [
            self._event("E1", "CRITICAL", "ACTIVE"),
            self._event("E2", "CRITICAL", "ACKNOWLEDGED"),
            self._event("E3", "WARNING", "ACTIVE"),
            self._event("E4", "INFO", "RESOLVED"),
            self._event("E5", "WARNING", "REVIEWING"),
        ]
        s = build_fleet_summary([], events, [], _mode())
        inc = s["incidents"]
        assert inc["total"] == 5
        assert inc["open"] == 3  # ACTIVE(2) + REVIEWING(1)
        assert inc["acknowledged"] == 1
        assert inc["resolved"] == 1
        assert inc["severity"]["CRITICAL"] == 2
        assert inc["severity"]["WARNING"] == 2
        assert inc["severity"]["INFO"] == 1
        # no double counting: sum(status) == total
        assert sum(inc["status"].values()) == inc["total"]


# ---------------------------------------------------------------- occupancy
class TestOccupancySummary:
    def test_camera_vs_simulated_separation(self):
        cam = _bus("CAM1", cabin={"status": "CONNECTED", "crowding_level": "MODERATE",
                                 "occupancy_percentage": 65})
        sim = _bus("SIM1", crowd="HIGH", passengers=50, capacity=60)
        s = build_fleet_summary([cam, sim], [], _risk([cam, sim]), _mode())
        occ = s["occupancy"]
        assert occ["camera_based"] == 1
        assert occ["simulated"] == 1
        assert occ["moderate"] == 1  # camera bucket
        assert occ["high"] == 1      # simulated bucket
        # the camera bus never contributes to the simulated occupancy count
        assert occ["normal"] == 0

    def test_cabin_unavailable_not_fabricated(self):
        cam = _bus("CAM2", cabin={"status": "DISCONNECTED", "crowding_level": None})
        o = (cam.get("occupancy") or {})
        # camera disconnected => no camera-based occupancy claim; falls back to telemetry bucket
        s = build_fleet_summary([cam], [], _risk([cam]), _mode())
        assert s["occupancy"]["camera_based"] == 0
        assert s["occupancy"]["simulated"] == 1

    def test_offline_occupancy_unavailable(self):
        off = _bus("OFF1", live=True, live_flag=False, last_s=90)
        s = build_fleet_summary([off], [], _risk([off]), _mode(sim=False))
        assert s["occupancy"]["unavailable"] == 1
        assert s["occupancy"]["simulated"] == 0


# ---------------------------------------------------------------- distributions
class TestDistributions:
    def test_driver_safety_distribution(self):
        buses = [_bus("A", driver="DROWSY"), _bus("B", driver="ATTENTION"),
                 _bus("C", driver="NORMAL")]
        s = build_fleet_summary(buses, [], _risk(buses), _mode())
        d = s["driver_safety"]
        assert d == {"normal": 1, "attention": 1, "drowsy": 1, "unavailable": 0}

    def test_vehicle_health_distribution(self):
        buses = [_bus("A", vehicle="NORMAL"), _bus("B", vehicle="WARNING"),
                 _bus("C", vehicle="INSPECTION REQUIRED")]
        s = build_fleet_summary(buses, [], _risk(buses), _mode())
        v = s["vehicle_health"]
        assert v["NORMAL"] == 1 and v["WARNING"] == 1 and v["INSPECTION REQUIRED"] == 1

    def test_load_distribution(self):
        buses = [_bus("A", load_status="NORMAL"), _bus("B", load_status="HIGH LOAD"),
                 _bus("C", load_status="CRITICAL OVERLOAD")]
        s = build_fleet_summary(buses, [], _risk(buses), _mode())
        l = s["load"]
        assert l == {"normal": 1, "high": 1, "critical": 1}

    def test_risk_aggregate(self):
        buses = [_bus("A"), _bus("B")]
        risk = [
            {"bus_id": "A", "risk_score": 90, "risk_level": "CRITICAL"},
            {"bus_id": "B", "risk_score": 10, "risk_level": "LOW"},
        ]
        s = build_fleet_summary(buses, [], risk, _mode())
        assert s["risk"]["by_level"]["CRITICAL"] == 1
        assert s["risk"]["avg_score"] == 50.0

    def test_road_summary_uses_engine_output(self):
        buses = [_bus("A", route_code="19D"), _bus("B", route_code="70V")]
        route_index = {"19D": {"level": "HIGH", "avg_score": 72, "defects": 6, "zones": 2},
                       "70V": {"level": "LOW", "avg_score": 12, "defects": 0, "zones": 0}}
        defects = [{"status": "ACTIVE"}, {"status": "ACTIVE"}, {"status": "RESOLVED"}]
        s = build_fleet_summary(buses, [], _risk(buses), _mode(),
                                zones=[{"z"}] * 3, route_index=route_index, defects=defects)
        r = s["road"]
        assert r["high_risk_routes"] == 1
        assert r["risky_routes"] == ["19D"]
        assert r["active_defects"] == 2
        assert r["affected_buses"] == 1  # only 19D bus
        assert r["zones"] == 3


# ---------------------------------------------------------------- honesty
class TestHonesty:
    def test_simulation_flag_and_connected(self):
        s = build_fleet_summary([], [], [], _mode(sim=True))
        assert s["simulation"] is True
        assert s["mode"] == "simulation"
        assert s["live_prototype_connected"] is False

    def test_live_flag(self):
        s = build_fleet_summary([], [], [], _mode(sim=False, connected={"PROTO-001": {"last_seen": 1}}))
        assert s["simulation"] is False
        assert s["live_prototype_connected"] is True
        assert s["connected_nodes"] == 1


# ---------------------------------------------------------------- endpoint
class TestFleetSummaryEndpoint:
    @pytest.fixture
    def client(self):
        return server.app.test_client()

    def test_endpoint_returns_schema(self, client):
        store.upsert_bus(_bus("PROTO-001"))
        resp = client.get("/api/fleet/summary")
        assert resp.status_code == 200
        d = resp.get_json()
        for key in ("fleet", "fleet_counts", "risk", "incidents", "driver_safety",
                    "vehicle_health", "occupancy", "load", "road", "attention",
                    "simulation", "mode", "generated_at"):
            assert key in d
        assert d["fleet_counts"]["total_buses"] == 1

    def test_endpoint_open_without_auth(self, client):
        resp = client.get("/api/fleet/summary")
        assert resp.status_code == 200
        assert "error" not in resp.get_json()

    def test_endpoint_reflects_store(self, client):
        store.upsert_bus(_bus("D1", driver="DROWSY"))
        store.upsert_bus(_bus("N1"))
        resp = client.get("/api/fleet/summary")
        d = resp.get_json()
        ids = [a["bus_id"] for a in d["attention"]]
        assert "D1" in ids
        assert d["driver_safety"]["drowsy"] == 1
        assert d["fleet_counts"]["normal"] == 1