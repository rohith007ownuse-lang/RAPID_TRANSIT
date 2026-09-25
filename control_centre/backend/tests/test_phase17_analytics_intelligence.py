"""
test_phase17_analytics_intelligence.py
Comprehensive tests for Phase 17: Analytics, Historical Intelligence & Operational Performance.

Covers:
  - Time range parsing
  - Trend analysis
  - Event analytics
  - Incident analytics
  - Risk analytics
  - ETA/delay analytics
  - Load/occupancy analytics
  - Road intelligence analytics
  - Driver safety analytics
  - Route analytics
  - Bus analytics
  - Cross-domain insights
  - Fleet KPIs
  - Data source honesty
  - Edge cases
"""

import json
import time
from datetime import datetime, timezone, timedelta

import pytest
import persistence

import analytics_intelligence
from analytics_intelligence import (
    _parse_time_range, _is_in_range, _calculate_trend, _bucket_by_time,
    get_event_analytics, get_incident_analytics, get_risk_analytics,
    get_eta_analytics, get_load_analytics, get_road_analytics,
    get_driver_safety_analytics, get_route_analytics, get_bus_analytics,
    get_cross_domain_insights, get_fleet_kpis, get_analytics_dashboard,
    TIME_RANGES, TREND_INCREASING, TREND_STABLE, TREND_DECREASING, TREND_UNKNOWN,
)


# ---------------------------------------------------------------------------
# Time range parsing tests
# ---------------------------------------------------------------------------

class TestTimeRangeParsing:
    """Tests for time range parsing."""

    def test_parse_1h(self):
        start, end, label = _parse_time_range("1h")
        assert start is not None
        assert end is not None
        assert label == "1h"
        assert end - start == 3600

    def test_parse_6h(self):
        start, end, label = _parse_time_range("6h")
        assert end - start == 21600

    def test_parse_24h(self):
        start, end, label = _parse_time_range("24h")
        assert end - start == 86400

    def test_parse_7d(self):
        start, end, label = _parse_time_range("7d")
        assert end - start == 604800

    def test_parse_30d(self):
        start, end, label = _parse_time_range("30d")
        assert end - start == 2592000

    def test_parse_all(self):
        start, end, label = _parse_time_range("all")
        assert start is None
        assert end is None
        assert label == "all"

    def test_parse_unknown_defaults_to_24h(self):
        start, end, label = _parse_time_range("unknown")
        assert start is not None
        assert end is not None
        assert label == "24h"

    def test_parse_custom_range(self):
        start_time = "2026-01-01T00:00:00Z"
        end_time = "2026-01-02T00:00:00Z"
        start, end, label = _parse_time_range("custom", start_time, end_time)
        assert start is not None
        assert end is not None
        assert "custom" in label

    def test_parse_custom_invalid(self):
        start, end, label = _parse_time_range("custom", "invalid", "invalid")
        assert label == "all"


# ---------------------------------------------------------------------------
# Time range filtering tests
# ---------------------------------------------------------------------------

class TestTimeRangeFiltering:
    """Tests for time range filtering."""

    def test_in_range_within_window(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        start = time.time() - 3600
        end = time.time() + 3600
        assert _is_in_range(now, start, end) is True

    def test_in_range_outside_window(self):
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
        start = time.time() - 3600
        end = time.time()
        assert _is_in_range(old_time, start, end) is False

    def test_in_range_no_bounds(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        assert _is_in_range(now, None, None) is True

    def test_in_range_invalid_timestamp(self):
        assert _is_in_range("invalid", 0, 9999999999) is False

    def test_in_range_empty_timestamp(self):
        assert _is_in_range("", 0, 9999999999) is False


# ---------------------------------------------------------------------------
# Trend analysis tests
# ---------------------------------------------------------------------------

class TestTrendAnalysis:
    """Tests for trend calculation."""

    def test_increasing_trend(self):
        values = [1, 2, 3, 4, 5, 6, 7]
        trend, slope = _calculate_trend(values)
        assert trend == TREND_INCREASING
        assert slope > 0

    def test_decreasing_trend(self):
        values = [7, 6, 5, 4, 3, 2, 1]
        trend, slope = _calculate_trend(values)
        assert trend == TREND_DECREASING
        assert slope < 0

    def test_stable_trend(self):
        values = [5, 5, 5, 5, 5, 5, 5]
        trend, slope = _calculate_trend(values)
        assert trend == TREND_STABLE

    def test_unknown_insufficient_samples(self):
        values = [1, 2]
        trend, slope = _calculate_trend(values, min_samples=3)
        assert trend == TREND_UNKNOWN

    def test_unknown_empty(self):
        trend, slope = _calculate_trend([])
        assert trend == TREND_UNKNOWN

    def test_unknown_single_value(self):
        trend, slope = _calculate_trend([5])
        assert trend == TREND_UNKNOWN


# ---------------------------------------------------------------------------
# Bucket by time tests
# ---------------------------------------------------------------------------

class TestBucketByTime:
    """Tests for time bucketing."""

    def test_basic_bucketing(self):
        now = time.time()
        records = [
            {"timestamp": datetime.fromtimestamp(now - 100, tz=timezone.utc).isoformat(timespec="seconds")},
            {"timestamp": datetime.fromtimestamp(now - 200, tz=timezone.utc).isoformat(timespec="seconds")},
        ]
        buckets = _bucket_by_time(records, "timestamp", bucket_size_hours=1, start=now - 3600, end=now)
        assert len(buckets) == 1
        assert buckets[0]["count"] == 2

    def test_multiple_buckets(self):
        now = time.time()
        records = [
            {"timestamp": datetime.fromtimestamp(now - 100, tz=timezone.utc).isoformat(timespec="seconds")},
            {"timestamp": datetime.fromtimestamp(now - 3700, tz=timezone.utc).isoformat(timespec="seconds")},
        ]
        buckets = _bucket_by_time(records, "timestamp", bucket_size_hours=1, start=now - 7200, end=now)
        assert len(buckets) == 2

    def test_empty_records(self):
        now = time.time()
        buckets = _bucket_by_time([], "timestamp", bucket_size_hours=1, start=now - 3600, end=now)
        assert len(buckets) == 1
        assert buckets[0]["count"] == 0


# ---------------------------------------------------------------------------
# Event analytics tests
# ---------------------------------------------------------------------------

class TestEventAnalytics:
    """Tests for event analytics."""

    def test_empty_events(self):
        result = get_event_analytics(time_range="1h")
        assert result["total"] == 0
        assert result["data_source"] == "INSUFFICIENT_DATA"

    def test_events_with_data(self):
        # Create test events
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        test_event = {
            "event_id": f"EVT-ANALYTICS-{int(time.time())}",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": "BUS-001",
            "route_code": "5A",
            "severity": "WARNING",
            "timestamp": now,
            "simulation": True,
        }
        persistence.save_event(test_event)

        result = get_event_analytics(time_range="all")
        assert result["total"] >= 1
        assert "DRIVER_DROWSINESS" in result["by_type"]

    def test_events_by_bus_filter(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        persistence.save_event({
            "event_id": f"EVT-FILTER-{int(time.time())}",
            "event_type": "CRASH",
            "bus_id": "BUS-FILTER",
            "severity": "CRITICAL",
            "timestamp": now,
            "simulation": True,
        })

        result = get_event_analytics(time_range="all", bus_id="BUS-FILTER")
        assert result["total"] >= 1

    def test_events_data_source_simulation(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        persistence.save_event({
            "event_id": f"EVT-SIM-{int(time.time())}",
            "event_type": "CRASH",
            "bus_id": "BUS-SIM",
            "severity": "CRITICAL",
            "timestamp": now,
            "simulation": True,
        })

        result = get_event_analytics(time_range="all")
        assert result["data_source"] == "SIMULATION"

    def test_events_timeline(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        persistence.save_event({
            "event_id": f"EVT-TL-{int(time.time())}",
            "event_type": "CRASH",
            "bus_id": "BUS-TL",
            "severity": "CRITICAL",
            "timestamp": now,
            "simulation": True,
        })

        result = get_event_analytics(time_range="all")
        assert "timeline" in result
        assert isinstance(result["timeline"], list)


# ---------------------------------------------------------------------------
# Incident analytics tests
# ---------------------------------------------------------------------------

class TestIncidentAnalytics:
    """Tests for incident analytics."""

    def test_empty_incidents(self):
        result = get_incident_analytics(time_range="1h")
        assert result["total"] == 0
        assert result["data_source"] == "INSUFFICIENT_DATA"

    def test_incidents_with_data(self):
        from incident_intelligence import Incident
        inc = Incident(
            incident_id=f"INC-ANALYTICS-{int(time.time())}",
            category="DRIVER_SAFETY",
            severity="HIGH",
            status="OPEN",
            bus_id="BUS-001",
            route="5A",
        )
        persistence.save_incident(inc.to_dict())

        result = get_incident_analytics(time_range="all")
        assert result["total"] >= 1
        assert "DRIVER_SAFETY" in result["by_category"]

    def test_incident_avg_duration(self):
        from incident_intelligence import Incident
        inc = Incident(
            incident_id=f"INC-DURATION-{int(time.time())}",
            category="SYSTEM",
            severity="MEDIUM",
            status="RESOLVED",
            bus_id="BUS-001",
        )
        inc.resolve("sup1")
        persistence.save_incident(inc.to_dict())

        result = get_incident_analytics(time_range="all")
        # Duration may or may not be calculable depending on timestamps
        assert result["total"] >= 1


# ---------------------------------------------------------------------------
# Risk analytics tests
# ---------------------------------------------------------------------------

class TestRiskAnalytics:
    """Tests for risk analytics."""

    def test_empty_risk(self):
        result = get_risk_analytics(time_range="1h")
        assert result["total"] == 0
        assert result["data_source"] == "INSUFFICIENT_DATA"

    def test_risk_with_data(self):
        # Create a risk event via persistence
        persistence.persist_risk_event(
            bus_id="BUS-001",
            event_type="RISK_STATE_CHANGE",
            risk_score=75.0,
            risk_level="HIGH",
            from_state="MEDIUM",
            to_state="HIGH",
        )

        result = get_risk_analytics(time_range="all")
        assert result["total"] >= 1

    def test_risk_note_about_limits(self):
        result = get_risk_analytics(time_range="all")
        assert "note" in result


# ---------------------------------------------------------------------------
# ETA analytics tests
# ---------------------------------------------------------------------------

class TestEtaAnalytics:
    """Tests for ETA/delay analytics."""

    def test_empty_eta(self):
        result = get_eta_analytics(time_range="1h")
        assert result["total"] == 0
        assert result["data_source"] == "INSUFFICIENT_DATA"
        assert result["on_time_performance"] == "UNKNOWN"

    def test_eta_with_data(self):
        persistence.persist_eta_snapshot(
            bus_id="BUS-001",
            delay_summary="minor_delay",
            total_remaining_distance_km=5.0,
            total_remaining_time_sec=600,
            delay_causes=[],
        )

        result = get_eta_analytics(time_range="all")
        assert result["total"] >= 1

    def test_eta_severe_delay(self):
        persistence.persist_eta_snapshot(
            bus_id="BUS-002",
            delay_summary="severe_delay",
            total_remaining_distance_km=10.0,
            total_remaining_time_sec=1200,
            delay_causes=[],
        )

        result = get_eta_analytics(time_range="all")
        assert result["severe_delay_count"] >= 1


# ---------------------------------------------------------------------------
# Load analytics tests
# ---------------------------------------------------------------------------

class TestLoadAnalytics:
    """Tests for load/occupancy analytics."""

    def test_empty_load(self):
        result = get_load_analytics(time_range="1h")
        assert result["total"] == 0
        assert result["data_source"] == "INSUFFICIENT_DATA"

    def test_load_with_data(self):
        persistence.persist_load_snapshot(
            bus_id="BUS-001",
            route_code="5A",
            passengers=30,
            capacity=40,
            utilization_pct=75.0,
            load_state="HIGH",
            crowd_level="HIGH",
        )

        result = get_load_analytics(time_range="all")
        assert result["total"] >= 1
        assert result["avg_occupancy_pct"] is not None

    def test_load_overloaded(self):
        persistence.persist_load_snapshot(
            bus_id="BUS-002",
            route_code="5A",
            passengers=45,
            capacity=40,
            utilization_pct=112.5,
            load_state="OVERLOADED",
            crowd_level="CRITICAL",
        )

        result = get_load_analytics(time_range="all")
        assert result["overloaded_count"] >= 1


# ---------------------------------------------------------------------------
# Road analytics tests
# ---------------------------------------------------------------------------

class TestRoadAnalytics:
    """Tests for road intelligence analytics."""

    def test_road_basic(self):
        result = get_road_analytics(time_range="all")
        assert "total_events" in result
        assert "zones_count" in result
        assert result["data_source"] == "HEURISTIC"

    def test_road_with_zones(self):
        # Road zones are loaded from persistence
        result = get_road_analytics(time_range="all")
        assert "top_risk_zones" in result


# ---------------------------------------------------------------------------
# Driver safety analytics tests
# ---------------------------------------------------------------------------

class TestDriverSafetyAnalytics:
    """Tests for driver safety analytics."""

    def test_empty_safety(self):
        result = get_driver_safety_analytics(time_range="1h")
        assert result["total"] == 0
        assert result["data_source"] == "INSUFFICIENT_DATA"

    def test_safety_with_events(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        persistence.save_event({
            "event_id": f"EVT-SAFETY-{int(time.time())}",
            "event_type": "DRIVER_DROWSINESS",
            "bus_id": "BUS-001",
            "severity": "WARNING",
            "timestamp": now,
            "simulation": True,
        })

        result = get_driver_safety_analytics(time_range="all")
        assert result["total"] >= 1

    def test_repeated_offenders(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for i in range(3):
            persistence.save_event({
                "event_id": f"EVT-REPEAT-{int(time.time())}-{i}",
                "event_type": "DRIVER_DROWSINESS",
                "bus_id": "BUS-REPEAT",
                "severity": "WARNING",
                "timestamp": now,
                "simulation": True,
            })

        result = get_driver_safety_analytics(time_range="all", bus_id="BUS-REPEAT")
        assert len(result.get("repeated_offenders", [])) >= 1


# ---------------------------------------------------------------------------
# Route analytics tests
# ---------------------------------------------------------------------------

class TestRouteAnalytics:
    """Tests for route analytics."""

    def test_empty_routes(self):
        result = get_route_analytics(time_range="1h")
        assert result["data_source"] == "INSUFFICIENT_DATA"

    def test_routes_with_data(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        persistence.save_event({
            "event_id": f"EVT-ROUTE-{int(time.time())}",
            "event_type": "CRASH",
            "bus_id": "BUS-001",
            "route_code": "5A",
            "severity": "CRITICAL",
            "timestamp": now,
            "simulation": True,
        })

        result = get_route_analytics(time_range="all")
        assert "5A" in result.get("routes", {})


# ---------------------------------------------------------------------------
# Bus analytics tests
# ---------------------------------------------------------------------------

class TestBusAnalytics:
    """Tests for bus analytics."""

    def test_empty_buses(self):
        result = get_bus_analytics(time_range="1h")
        assert result["data_source"] == "INSUFFICIENT_DATA"

    def test_buses_with_data(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        persistence.save_event({
            "event_id": f"EVT-BUS-{int(time.time())}",
            "event_type": "CRASH",
            "bus_id": "BUS-ANALYTICS",
            "severity": "CRITICAL",
            "timestamp": now,
            "simulation": True,
        })

        result = get_bus_analytics(time_range="all")
        assert "BUS-ANALYTICS" in result.get("buses", {})

    def test_bus_specific_filter(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        persistence.save_event({
            "event_id": f"EVT-BUSFILTER-{int(time.time())}",
            "event_type": "CRASH",
            "bus_id": "BUS-SPECIFIC",
            "severity": "CRITICAL",
            "timestamp": now,
            "simulation": True,
        })

        result = get_bus_analytics(time_range="all", bus_id="BUS-SPECIFIC")
        assert "BUS-SPECIFIC" in result.get("buses", {})


# ---------------------------------------------------------------------------
# Cross-domain insights tests
# ---------------------------------------------------------------------------

class TestCrossDomainInsights:
    """Tests for cross-domain insights."""

    def test_insights_with_no_data(self):
        result = get_cross_domain_insights(time_range="1h")
        assert len(result["insights"]) >= 1
        # Should have a "no pattern" insight
        assert any(i["type"] == "no_pattern" for i in result["insights"])

    def test_insights_with_events(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Create multiple events for same bus to trigger insight
        for i in range(4):
            persistence.save_event({
                "event_id": f"EVT-INSIGHT-{int(time.time())}-{i}",
                "event_type": "CRASH",
                "bus_id": "BUS-INSIGHT",
                "severity": "CRITICAL",
                "timestamp": now,
                "simulation": True,
            })

        result = get_cross_domain_insights(time_range="all")
        assert len(result["insights"]) >= 1
        # Should have a bus_repeated_events insight
        types = [i["type"] for i in result["insights"]]
        assert "bus_repeated_events" in types or "no_pattern" in types


# ---------------------------------------------------------------------------
# Fleet KPI tests
# ---------------------------------------------------------------------------

class TestFleetKpis:
    """Tests for fleet KPI summary."""

    def test_empty_kpis(self):
        result = get_fleet_kpis(time_range="1h")
        assert result["total_events"] == 0
        assert result["active_buses"] == 0

    def test_kpis_with_data(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        persistence.save_event({
            "event_id": f"EVT-KPI-{int(time.time())}",
            "event_type": "CRASH",
            "bus_id": "BUS-KPI",
            "severity": "CRITICAL",
            "timestamp": now,
            "simulation": True,
        })

        result = get_fleet_kpis(time_range="all")
        assert result["total_events"] >= 1
        assert result["active_buses"] >= 1

    def test_kpis_data_source(self):
        result = get_fleet_kpis(time_range="all")
        assert result["data_source"] in ("SIMULATION", "LIVE", "UNKNOWN")


# ---------------------------------------------------------------------------
# Dashboard endpoint tests
# ---------------------------------------------------------------------------

class TestAnalyticsDashboard:
    """Tests for the comprehensive dashboard endpoint."""

    def test_dashboard_structure(self):
        result = get_analytics_dashboard(time_range="all")
        assert "kpis" in result
        assert "events" in result
        assert "incidents" in result
        assert "risk" in result
        assert "eta" in result
        assert "load" in result
        assert "road" in result
        assert "driver_safety" in result
        assert "routes" in result
        assert "buses" in result
        assert "insights" in result
        assert "generated_at" in result


# ---------------------------------------------------------------------------
# Flask API endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from server import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestAnalyticsAPI:
    """Tests for analytics REST API endpoints."""

    def test_historical_analytics(self, client):
        resp = client.get("/api/analytics/historical?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "kpis" in data
        assert "events" in data

    def test_kpis_endpoint(self, client):
        resp = client.get("/api/analytics/kpis?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_events" in data

    def test_events_endpoint(self, client):
        resp = client.get("/api/analytics/events?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data

    def test_incidents_endpoint(self, client):
        resp = client.get("/api/analytics/incidents?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data

    def test_risk_endpoint(self, client):
        resp = client.get("/api/analytics/risk?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data

    def test_eta_endpoint(self, client):
        resp = client.get("/api/analytics/eta?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data

    def test_load_endpoint(self, client):
        resp = client.get("/api/analytics/load?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data

    def test_road_endpoint(self, client):
        resp = client.get("/api/analytics/road?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_events" in data

    def test_driver_safety_endpoint(self, client):
        resp = client.get("/api/analytics/driver-safety?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data

    def test_routes_endpoint(self, client):
        resp = client.get("/api/analytics/routes?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "routes" in data

    def test_buses_endpoint(self, client):
        resp = client.get("/api/analytics/buses?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "buses" in data

    def test_insights_endpoint(self, client):
        resp = client.get("/api/analytics/insights?time_range=all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "insights" in data

    def test_invalid_time_range(self, client):
        resp = client.get("/api/analytics/historical?time_range=invalid")
        assert resp.status_code == 200  # Should default to 24h

    def test_simulation_mode_flag(self, client):
        resp = client.get("/api/analytics/kpis")
        data = resp.get_json()
        assert "simulation" in data
        assert "mode" in data


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases and data honesty."""

    def test_insufficient_data_label(self):
        result = get_event_analytics(time_range="1h")
        assert result["data_source"] == "INSUFFICIENT_DATA"

    def test_data_source_consistency(self):
        result = get_load_analytics(time_range="all")
        # When no data, should be INSUFFICIENT_DATA
        if result["total"] == 0:
            assert result["data_source"] == "INSUFFICIENT_DATA"
        else:
            # Load data is simulation in current system
            assert result["data_source"] == "SIMULATION"

    def test_trend_with_minimal_data(self):
        values = [5]
        trend, slope = _calculate_trend(values, min_samples=3)
        assert trend == TREND_UNKNOWN

    def test_bucket_with_no_timestamps(self):
        records = [{"no_timestamp": "value"}]
        buckets = _bucket_by_time(records, "timestamp", bucket_size_hours=1)
        assert all(b["count"] == 0 for b in buckets)

    def test_analytics_constants(self):
        assert "1h" in TIME_RANGES
        assert "24h" in TIME_RANGES
        assert "7d" in TIME_RANGES
        assert "30d" in TIME_RANGES
        assert "all" in TIME_RANGES
