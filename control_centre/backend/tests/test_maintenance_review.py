"""
test_maintenance_review.py
Review-to-clear maintenance list + historical simulation fallback.

- A bus flagged for maintenance stays flagged until reviewed.
- Reviewing clears the flag and records the reviewer.
- Historical synthesize_inputs() is deterministic and feeds the
  unchanged analysis functions (same thresholds, same code paths).
"""

from historical_intelligence import historical_intelligence_engine


def _bus(bus_id="19D", **over):
    b = {
        "bus_id": bus_id,
        "route_code": "19D",
        "route": "19D - Tambaram to Beach",
        "reg_no": "TN-01-F-2400",
        "latitude": 13.02,
        "longitude": 80.22,
        "vehicle": {"health": "WARNING"},
        "driver": {"state": "NORMAL", "name": "Ravi"},
        "simulation": True,
    }
    b.update(over)
    return b


class TestMaintenanceReview:
    def test_review_lifecycle(self):
        from data_store import EventStore
        s = EventStore()
        assert not s.is_maintenance_reviewed("19D")
        s.flag_maintenance("19D", days=1.2, status="SEND_TO_MAINTENANCE")
        assert "19D" in s.get_maintenance_flagged()
        rec = s.review_maintenance("19D", operator="op-1", note="brakes done")
        assert rec["reviewed_by"] == "op-1"
        assert s.is_maintenance_reviewed("19D")
        s.clear_maintenance_flag("19D")
        assert "19D" not in s.get_maintenance_flagged()

    def test_flag_keeps_first_seen(self):
        from data_store import EventStore
        s = EventStore()
        first = s.flag_maintenance("19D", days=2.0, status="PLAN_MAINTENANCE")
        second = s.flag_maintenance("19D", days=1.0, status="SEND_TO_MAINTENANCE")
        assert first["first_flagged_at"] == second["first_flagged_at"]
        assert second["last_days"] == 1.0

    def test_review_endpoint(self, client=None):
        # Endpoint-level coverage lives in test_predictive_health style;
        # the store contract above is the load-bearing behavior.
        pass


class TestHistoricalSimulation:
    def test_synthesize_deterministic(self):
        buses = [_bus("19D"), _bus("23C .2", vehicle={"health": "NORMAL"},
                                   driver={"state": "NORMAL"})]
        a = historical_intelligence_engine.synthesize_inputs(
            buses=buses, events=[], road_defects=[], window="7d")
        b = historical_intelligence_engine.synthesize_inputs(
            buses=buses, events=[], road_defects=[], window="7d")
        assert a["simulated"] is True
        assert len(a["events"]) == len(b["events"])
        assert len(a["risk_events"]) == len(b["risk_events"])
        assert len(a["eta_snapshots"]) == len(b["eta_snapshots"])

    def test_synthesized_inputs_feed_analysis(self):
        buses = [_bus("19D"), _bus("1A"), _bus("70V")]
        synth = historical_intelligence_engine.synthesize_inputs(
            buses=buses, events=[], road_defects=[], window="7d")
        peaks = historical_intelligence_engine.analyze_peak_periods(
            events=synth["events"], incidents=synth["incidents"], window="7d")
        assert peaks["total_events"] > 0
        assert len(peaks["peak_hours"]) > 0
        delays = historical_intelligence_engine.analyze_route_delay_patterns(
            eta_snapshots=synth["eta_snapshots"], window="7d")
        assert len(delays["patterns"]) > 0
        health = historical_intelligence_engine.analyze_vehicle_health_trends(
            risk_events=synth["risk_events"], window="7d")
        assert health["total_buses"] > 0

    def test_live_events_preserved(self):
        live = [{"event_type": "CRASH", "severity": "CRITICAL",
                 "bus_id": "19D", "latitude": 13.0, "longitude": 80.2,
                 "timestamp": "2026-09-14T08:00:00+00:00"}]
        synth = historical_intelligence_engine.synthesize_inputs(
            buses=[_bus()], events=live, road_defects=[], window="7d")
        assert live[0] in synth["events"]


class TestMaintenanceReviewEndpoints:
    def _auth(self, client):
        resp = client.post("/api/auth/login",
                           json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.get_json()['token']}"}

    def test_review_requires_bus_id(self):
        import server
        client = server.app.test_client()
        headers = self._auth(client)
        resp = client.post("/api/health/maintenance/review",
                           json={}, headers=headers)
        assert resp.status_code == 400

    def test_review_clears_bus(self):
        import server
        from data_store import store
        client = server.app.test_client()
        headers = self._auth(client)
        store.flag_maintenance("TEST-BUS-1", days=1.0,
                               status="SEND_TO_MAINTENANCE")
        resp = client.post("/api/health/maintenance/review",
                           json={"bus_id": "TEST-BUS-1", "operator": "admin"},
                           headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["review"]["bus_id"] == "TEST-BUS-1"
        assert store.is_maintenance_reviewed("TEST-BUS-1")
        assert "TEST-BUS-1" not in store.get_maintenance_flagged()

    def test_review_requires_auth(self):
        import server
        client = server.app.test_client()
        resp = client.post("/api/health/maintenance/review",
                           json={"bus_id": "X"})
        assert resp.status_code == 401

    def test_predictive_carries_reviews(self):
        import server
        client = server.app.test_client()
        resp = client.get("/api/health/predictive")
        assert resp.status_code == 200
        assert "maintenance_reviews" in resp.get_json()

    def test_historical_comprehensive_has_simulation_flag(self):
        import server
        from data_store import store
        # Seed a minimal fleet snapshot (test env runs no simulator).
        snapshot = dict(store.buses)
        try:
            for i, code in enumerate(["19D", "1A", "70V"]):
                store.upsert_bus(_bus(code, latitude=13.0 + i * 0.01,
                                      longitude=80.2 + i * 0.01))
                store.upsert_bus(_bus(f"{code} .2", latitude=13.0 - i * 0.01,
                                      longitude=80.2 - i * 0.01))
            client = server.app.test_client()
            resp = client.get("/api/historical/comprehensive?window=7d")
            assert resp.status_code == 200
            body = resp.get_json()
            assert "simulation" in body
            assert body["simulation"] is True
            assert body["route_delay_patterns"]["patterns"]
            assert body["peak_periods"]["total_events"] > 0
        finally:
            store.buses.clear()
            store.buses.update(snapshot)
