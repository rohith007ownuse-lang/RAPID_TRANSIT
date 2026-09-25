"""
analytics_intelligence.py
Phase 17: Analytics, Historical Intelligence & Operational Performance.

Transforms raw operational records into historical intelligence:
events, incidents, risk, ETA, load, road, driver safety.

Core principle: Never fabricate historical data. Every metric is based on
actual available records. Clearly distinguish data sources.

Data availability after audit:
- Events: FULLY PERSISTED (events table, timestamp + event_type + severity + bus_id + route_code)
- Incidents: FULLY PERSISTED (incidents table, created_at + category + severity + status + bus_id + route)
- Risk: PARTIALLY PERSISTED (risk_events table for transitions; full history in-memory only)
- ETA: PERSISTED (eta_snapshots table, bus_id + delay_summary + created_at)
- Load/Occupancy: PERSISTED (load_snapshots table, bus_id + passengers + capacity + created_at)
- Road: PERSISTED (road_clusters + road_risk_zones tables; events table for POTHOLE/ROAD_DEFECT)
- Driver Safety: VIA EVENTS ONLY (DRIVER_DROWSINESS events in events table)
- Vehicle Health: NOT PERSISTED (in-memory only, lost on restart)
"""

import json
import time
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

import persistence

# ---------------------------------------------------------------------------
# Data source classification
# ---------------------------------------------------------------------------

DATA_SOURCES = ("LIVE", "SIMULATION", "HEURISTIC", "MODEL", "UNKNOWN", "INSUFFICIENT_DATA")

# Time range presets (seconds)
TIME_RANGES = {
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
    "all": None,
}

# Trend states
TREND_INCREASING = "INCREASING"
TREND_STABLE = "STABLE"
TREND_DECREASING = "DECREASING"
TREND_UNKNOWN = "UNKNOWN"

# Severity rank for comparison
SEVERITY_RANK = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


# ---------------------------------------------------------------------------
# Time range parsing
# ---------------------------------------------------------------------------

def _parse_time_range(time_range, custom_start=None, custom_end=None):
    """Parse time range into (start_timestamp, end_timestamp, label).

    Returns (start_epoch, end_epoch, label_str) or (None, None, "all") for unbounded.
    """
    now = time.time()

    if time_range == "custom" and custom_start and custom_end:
        try:
            start = datetime.fromisoformat(custom_start.replace("Z", "+00:00")).timestamp()
            end = datetime.fromisoformat(custom_end.replace("Z", "+00:00")).timestamp()
            return start, end, f"custom ({custom_start} to {custom_end})"
        except (ValueError, TypeError):
            return None, None, "all"

    if time_range in TIME_RANGES:
        duration = TIME_RANGES[time_range]
        if duration is None:
            return None, None, "all"
        return now - duration, now, time_range

    # Default to 24h
    return now - 86400, now, "24h"


def _is_in_range(timestamp_str, start, end):
    """Check if a timestamp string is within the given range."""
    if start is None and end is None:
        return True
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).timestamp()
        if start is not None and ts < start:
            return False
        if end is not None and ts > end:
            return False
        return True
    except (ValueError, TypeError):
        return False


def _format_timestamp(ts):
    """Format epoch timestamp for display."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def _calculate_trend(values, min_samples=3):
    """Calculate trend direction from a list of numerical values.

    Uses simple linear regression slope to determine direction.
    Requires at least min_samples data points.
    """
    if not values or len(values) < min_samples:
        return TREND_UNKNOWN, 0.0

    n = len(values)
    x_vals = list(range(n))
    y_vals = list(values)

    # Simple linear regression: slope = (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x^2) - sum(x)^2)
    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
    sum_x2 = sum(x * x for x in x_vals)

    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        return TREND_UNKNOWN, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denominator

    # Normalize slope by mean value to get relative change
    mean_y = sum_y / n if n > 0 else 0
    if mean_y == 0:
        return TREND_UNKNOWN, 0.0

    relative_slope = slope / mean_y

    # Thresholds for trend classification
    if relative_slope > 0.05:
        return TREND_INCREASING, relative_slope
    elif relative_slope < -0.05:
        return TREND_DECREASING, relative_slope
    else:
        return TREND_STABLE, relative_slope


def _bucket_by_time(records, timestamp_key, bucket_size_hours=1, start=None, end=None):
    """Bucket records into time intervals for trend visualization.

    Returns list of {time_bucket, count, ...}.
    """
    if start is None:
        start = time.time() - 86400  # Default: last 24h
    if end is None:
        end = time.time()

    bucket_size_s = bucket_size_hours * 3600
    num_buckets = max(1, int((end - start) / bucket_size_s))
    buckets = []

    for i in range(num_buckets):
        bucket_start = start + i * bucket_size_s
        bucket_end = bucket_start + bucket_size_s
        buckets.append({
            "time_bucket": _format_timestamp(bucket_start),
            "time_end": _format_timestamp(bucket_end),
            "count": 0,
            "records": [],
        })

    for record in records:
        ts_str = record.get(timestamp_key)
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue

        if ts < start or ts > end:
            continue

        bucket_idx = int((ts - start) / bucket_size_s)
        if 0 <= bucket_idx < num_buckets:
            buckets[bucket_idx]["count"] += 1
            buckets[bucket_idx]["records"].append(record)

    return buckets


# ---------------------------------------------------------------------------
# Event analytics (from events table)
# ---------------------------------------------------------------------------

def get_event_analytics(time_range="24h", custom_start=None, custom_end=None,
                        bus_id=None, route_code=None):
    """Analyze persisted events within a time range.

    Returns event counts, types, severity distribution, trends.
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    # Load events from persistence
    all_events = persistence.load_events()

    # Filter by time range
    if start is not None or end is not None:
        events = [e for e in all_events if _is_in_range(e.get("timestamp", ""), start, end)]
    else:
        events = all_events

    # Apply bus/route filters
    if bus_id:
        events = [e for e in events if e.get("bus_id") == bus_id]
    if route_code:
        events = [e for e in events if e.get("route_code") == route_code]

    if not events:
        return {
            "total": 0,
            "by_type": {},
            "by_severity": {},
            "by_bus": {},
            "by_route": {},
            "by_hour": {},
            "trend": TREND_UNKNOWN,
            "time_range": label,
            "data_source": "INSUFFICIENT_DATA",
            "record_count": 0,
        }

    # Aggregate
    by_type = Counter(e.get("event_type", "UNKNOWN") for e in events)
    by_severity = Counter(e.get("severity", "UNKNOWN") for e in events)
    by_bus = Counter(e.get("bus_id", "UNKNOWN") for e in events)
    by_route = Counter(e.get("route_code", "UNKNOWN") for e in events)

    # Hourly distribution
    by_hour = defaultdict(int)
    for e in events:
        ts = e.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            by_hour[dt.hour] += 1
        except (ValueError, TypeError):
            pass

    # Trend: bucket events by day
    buckets = _bucket_by_time(events, "timestamp", bucket_size_hours=24, start=start, end=end)
    counts = [b["count"] for b in buckets]
    trend, slope = _calculate_trend(counts)

    # Determine data source
    sim_count = sum(1 for e in events if e.get("simulation"))
    live_count = len(events) - sim_count
    if live_count > 0 and sim_count > 0:
        data_source = "MIXED"
    elif sim_count > 0:
        data_source = "SIMULATION"
    elif live_count > 0:
        data_source = "LIVE"
    else:
        data_source = "UNKNOWN"

    return {
        "total": len(events),
        "by_type": dict(by_type.most_common()),
        "by_severity": dict(by_severity.most_common()),
        "by_bus": dict(by_bus.most_common(20)),
        "by_route": dict(by_route.most_common()),
        "by_hour": {str(h): c for h, c in sorted(by_hour.items())},
        "trend": trend,
        "trend_slope": round(slope, 4),
        "time_range": label,
        "data_source": data_source,
        "record_count": len(events),
        "timeline": [{"time": b["time_bucket"], "count": b["count"]} for b in buckets],
    }


# ---------------------------------------------------------------------------
# Incident analytics (from incidents table)
# ---------------------------------------------------------------------------

def get_incident_analytics(time_range="24h", custom_start=None, custom_end=None,
                           bus_id=None, category=None):
    """Analyze persisted incidents within a time range.

    Returns incident counts, categories, severity/status/priority distributions,
    trends, average duration.
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    all_incidents = persistence.load_incidents()

    # Filter by time range
    if start is not None or end is not None:
        incidents = [i for i in all_incidents if _is_in_range(i.get("created_at", ""), start, end)]
    else:
        incidents = all_incidents

    if bus_id:
        incidents = [i for i in incidents if i.get("bus_id") == bus_id]
    if category:
        incidents = [i for i in incidents if i.get("category") == category]

    if not incidents:
        return {
            "total": 0,
            "by_category": {},
            "by_severity": {},
            "by_status": {},
            "by_priority": {},
            "by_route": {},
            "by_bus": {},
            "trend": TREND_UNKNOWN,
            "avg_duration_hours": None,
            "time_range": label,
            "data_source": "INSUFFICIENT_DATA",
            "record_count": 0,
        }

    by_category = Counter(i.get("category", "UNKNOWN") for i in incidents)
    by_severity = Counter(i.get("severity", "UNKNOWN") for i in incidents)
    by_status = Counter(i.get("status", "UNKNOWN") for i in incidents)
    by_priority = Counter(i.get("priority", "UNKNOWN") for i in incidents)
    by_route = Counter(i.get("route", "UNKNOWN") for i in incidents if i.get("route"))
    by_bus = Counter(i.get("bus_id", "UNKNOWN") for i in incidents)

    # Calculate average duration for resolved/closed incidents
    durations = []
    for inc in incidents:
        created = inc.get("created_at")
        resolved = inc.get("resolved_at") or inc.get("acknowledged_at")
        if created and resolved:
            try:
                t_created = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                t_resolved = datetime.fromisoformat(resolved.replace("Z", "+00:00")).timestamp()
                durations.append(t_resolved - t_created)
            except (ValueError, TypeError):
                pass

    avg_duration_hours = None
    if durations:
        avg_duration_hours = round(sum(durations) / len(durations) / 3600, 2)

    # Trend
    buckets = _bucket_by_time(incidents, "created_at", bucket_size_hours=24, start=start, end=end)
    counts = [b["count"] for b in buckets]
    trend, slope = _calculate_trend(counts)

    # Data source
    data_source = "SIMULATION"  # All current incidents are simulation-derived

    return {
        "total": len(incidents),
        "by_category": dict(by_category.most_common()),
        "by_severity": dict(by_severity.most_common()),
        "by_status": dict(by_status.most_common()),
        "by_priority": dict(by_priority.most_common()),
        "by_route": dict(by_route.most_common(10)),
        "by_bus": dict(by_bus.most_common(20)),
        "trend": trend,
        "trend_slope": round(slope, 4),
        "avg_duration_hours": avg_duration_hours,
        "time_range": label,
        "data_source": data_source,
        "record_count": len(incidents),
        "timeline": [{"time": b["time_bucket"], "count": b["count"]} for b in buckets],
    }


# ---------------------------------------------------------------------------
# Risk analytics (from risk_events table)
# ---------------------------------------------------------------------------

def get_risk_analytics(time_range="24h", custom_start=None, custom_end=None,
                       bus_id=None):
    """Analyze persisted risk events within a time range.

    Returns risk distribution, transitions, high-risk occurrences.
    Note: Full risk history is in-memory only (max 20 per bus).
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    all_risk_events = persistence.load_risk_events(limit=10000)

    # Filter by time range
    if start is not None or end is not None:
        risk_events = [r for r in all_risk_events if _is_in_range(r.get("created_at", ""), start, end)]
    else:
        risk_events = all_risk_events

    if bus_id:
        risk_events = [r for r in risk_events if r.get("bus_id") == bus_id]

    if not risk_events:
        return {
            "total": 0,
            "by_level": {},
            "by_bus": {},
            "transitions": [],
            "high_risk_count": 0,
            "critical_risk_count": 0,
            "trend": TREND_UNKNOWN,
            "avg_score": None,
            "time_range": label,
            "data_source": "INSUFFICIENT_DATA",
            "record_count": 0,
            "note": "Full risk history is in-memory only (max 20 per bus). This data represents risk state transitions, not continuous risk scores.",
        }

    by_level = Counter(r.get("risk_level", "UNKNOWN") for r in risk_events)
    by_bus = Counter(r.get("bus_id", "UNKNOWN") for r in risk_events)

    # Transitions (from_state -> to_state)
    transitions = []
    for r in risk_events:
        from_s = r.get("from_state")
        to_s = r.get("to_state")
        if from_s and to_s:
            transitions.append({"from": from_s, "to": to_s, "bus_id": r.get("bus_id")})

    # Aggregate transitions
    transition_counts = Counter(f"{t['from']}→{t['to']}" for t in transitions)

    # High/critical counts
    high_risk = sum(1 for r in risk_events if r.get("risk_level") in ("HIGH", "CRITICAL"))
    critical_risk = sum(1 for r in risk_events if r.get("risk_level") == "CRITICAL")

    # Average score
    scores = [r.get("risk_score", 0) for r in risk_events if r.get("risk_score") is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    # Trend
    buckets = _bucket_by_time(risk_events, "created_at", bucket_size_hours=24, start=start, end=end)
    counts = [b["count"] for b in buckets]
    trend, slope = _calculate_trend(counts)

    return {
        "total": len(risk_events),
        "by_level": dict(by_level.most_common()),
        "by_bus": dict(by_bus.most_common(20)),
        "transitions": dict(transition_counts.most_common()),
        "high_risk_count": high_risk,
        "critical_risk_count": critical_risk,
        "trend": trend,
        "trend_slope": round(slope, 4),
        "avg_score": avg_score,
        "time_range": label,
        "data_source": "SIMULATION",
        "record_count": len(risk_events),
        "timeline": [{"time": b["time_bucket"], "count": b["count"]} for b in buckets],
        "note": "Risk events represent state transitions. Full continuous risk history is in-memory only (max 20 per bus).",
    }


# ---------------------------------------------------------------------------
# ETA / Delay analytics (from eta_snapshots table)
# ---------------------------------------------------------------------------

def get_eta_analytics(time_range="24h", custom_start=None, custom_end=None,
                      bus_id=None):
    """Analyze persisted ETA/delay snapshots.

    Returns delay distribution, severe delays, on-time performance.
    Note: Schedule-based on-time performance is UNKNOWN (no schedule data).
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    if bus_id:
        all_snapshots = persistence.load_eta_snapshots(bus_id=bus_id, limit=10000)
    else:
        all_snapshots = persistence.load_eta_snapshots(limit=10000)

    # Filter by time range
    if start is not None or end is not None:
        snapshots = [s for s in all_snapshots if _is_in_range(s.get("created_at", ""), start, end)]
    else:
        snapshots = all_snapshots

    if not snapshots:
        return {
            "total": 0,
            "avg_delay_minutes": None,
            "severe_delay_count": 0,
            "delay_distribution": {},
            "by_bus": {},
            "trend": TREND_UNKNOWN,
            "time_range": label,
            "data_source": "INSUFFICIENT_DATA",
            "record_count": 0,
            "on_time_performance": "UNKNOWN",
            "note": "No schedule data available. On-time performance cannot be calculated.",
        }

    # Parse delay summaries
    delay_minutes = []
    severe_delays = 0
    by_bus = defaultdict(int)

    for s in snapshots:
        delay_str = s.get("delay_summary", "")
        bus = s.get("bus_id", "UNKNOWN")
        by_bus[bus] += 1

        # Try to parse delay from summary
        # Common patterns: "on_time", "minor_delay", "moderate_delay", "severe_delay"
        if "severe" in delay_str.lower():
            severe_delays += 1
            delay_minutes.append(15)  # Estimate 15+ min for severe
        elif "moderate" in delay_str.lower():
            delay_minutes.append(8)
        elif "minor" in delay_str.lower():
            delay_minutes.append(3)
        elif "on_time" in delay_str.lower():
            delay_minutes.append(0)

    avg_delay = round(sum(delay_minutes) / len(delay_minutes), 2) if delay_minutes else None

    # Delay distribution
    delay_dist = Counter()
    for d in delay_minutes:
        if d == 0:
            delay_dist["on_time"] += 1
        elif d <= 5:
            delay_dist["minor"] += 1
        elif d <= 10:
            delay_dist["moderate"] += 1
        else:
            delay_dist["severe"] += 1

    # Trend
    buckets = _bucket_by_time(snapshots, "created_at", bucket_size_hours=24, start=start, end=end)
    counts = [b["count"] for b in buckets]
    trend, slope = _calculate_trend(counts)

    return {
        "total": len(snapshots),
        "avg_delay_minutes": avg_delay,
        "severe_delay_count": severe_delays,
        "delay_distribution": dict(delay_dist),
        "by_bus": dict(by_bus),
        "trend": trend,
        "trend_slope": round(slope, 4),
        "time_range": label,
        "data_source": "HEURISTIC",
        "record_count": len(snapshots),
        "on_time_performance": "UNKNOWN",
        "timeline": [{"time": b["time_bucket"], "count": b["count"]} for b in buckets],
        "note": "Delay estimates are heuristic (from delay_summary strings). Schedule-based on-time performance unavailable.",
    }


# ---------------------------------------------------------------------------
# Load / Occupancy analytics (from load_snapshots table)
# ---------------------------------------------------------------------------

def get_load_analytics(time_range="24h", custom_start=None, custom_end=None,
                       bus_id=None, route_code=None):
    """Analyze persisted load/occupancy snapshots.

    Returns occupancy distribution, overloaded buses, capacity pressure.
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    if bus_id:
        all_snapshots = persistence.load_load_snapshots(bus_id=bus_id, limit=10000)
    elif route_code:
        all_snapshots = persistence.load_route_demand_history(route_code, limit=10000)
    else:
        all_snapshots = persistence.load_load_snapshots(limit=10000)

    # Filter by time range
    if start is not None or end is not None:
        snapshots = [s for s in all_snapshots if _is_in_range(s.get("created_at", ""), start, end)]
    else:
        snapshots = all_snapshots

    if not snapshots:
        return {
            "total": 0,
            "avg_occupancy_pct": None,
            "overloaded_count": 0,
            "high_occupancy_count": 0,
            "by_bus": {},
            "by_route": {},
            "load_distribution": {},
            "trend": TREND_UNKNOWN,
            "time_range": label,
            "data_source": "INSUFFICIENT_DATA",
            "record_count": 0,
        }

    # Aggregate
    utilizations = []
    overloaded = 0
    high_occ = 0
    by_bus = defaultdict(lambda: {"count": 0, "total_util": 0})
    by_route = defaultdict(lambda: {"count": 0, "total_util": 0})
    load_dist = Counter()

    for s in snapshots:
        util = s.get("utilization_pct", 0)
        if util is not None:
            utilizations.append(util)
            bus = s.get("bus_id", "UNKNOWN")
            route = s.get("route_code", "UNKNOWN")

            by_bus[bus]["count"] += 1
            by_bus[bus]["total_util"] += util
            by_route[route]["count"] += 1
            by_route[route]["total_util"] += util

            if util >= 100:
                overloaded += 1
                load_dist["OVERLOADED"] += 1
            elif util >= 75:
                high_occ += 1
                load_dist["HIGH"] += 1
            elif util >= 50:
                load_dist["MODERATE"] += 1
            else:
                load_dist["NORMAL"] += 1

    avg_util = round(sum(utilizations) / len(utilizations), 2) if utilizations else None

    # Per-bus averages
    bus_avgs = {}
    for bus, data in by_bus.items():
        bus_avgs[bus] = {"sample_count": data["count"], "avg_utilization": round(data["total_util"] / data["count"], 2)}

    # Per-route averages
    route_avgs = {}
    for route, data in by_route.items():
        route_avgs[route] = {"sample_count": data["count"], "avg_utilization": round(data["total_util"] / data["count"], 2)}

    # Trend
    buckets = _bucket_by_time(snapshots, "created_at", bucket_size_hours=24, start=start, end=end)
    counts = [b["count"] for b in buckets]
    trend, slope = _calculate_trend(counts)

    return {
        "total": len(snapshots),
        "avg_occupancy_pct": avg_util,
        "overloaded_count": overloaded,
        "high_occupancy_count": high_occ,
        "by_bus": bus_avgs,
        "by_route": route_avgs,
        "load_distribution": dict(load_dist),
        "trend": trend,
        "trend_slope": round(slope, 4),
        "time_range": label,
        "data_source": "SIMULATION",
        "record_count": len(snapshots),
        "timeline": [{"time": b["time_bucket"], "count": b["count"]} for b in buckets],
    }


# ---------------------------------------------------------------------------
# Road intelligence analytics (from road tables + events)
# ---------------------------------------------------------------------------

def get_road_analytics(time_range="24h", custom_start=None, custom_end=None):
    """Analyze road intelligence data.

    Returns road events, risk zones, affected routes, high-risk areas.
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    # Road risk zones (from persistence)
    zones = persistence.load_road_risk_zones()
    clusters = persistence.load_road_clusters()

    # Road events from events table
    all_events = persistence.load_events()
    road_events = [e for e in all_events if e.get("event_type") in ("POTHOLE", "ROAD_DEFECT")]

    if start is not None or end is not None:
        road_events = [e for e in road_events if _is_in_range(e.get("timestamp", ""), start, end)]

    # Zone statistics
    zone_risk_levels = Counter(z.get("risk_level", "UNKNOWN") for z in zones)
    affected_routes = set()
    for z in zones:
        routes = z.get("routes_affected", [])
        if isinstance(routes, str):
            try:
                routes = json.loads(routes)
            except (json.JSONDecodeError, TypeError):
                routes = []
        affected_routes.update(routes)

    # Event type distribution
    event_types = Counter(e.get("event_type", "UNKNOWN") for e in road_events)

    # Event trend
    buckets = _bucket_by_time(road_events, "timestamp", bucket_size_hours=24, start=start, end=end)
    counts = [b["count"] for b in buckets]
    trend, slope = _calculate_trend(counts)

    # Top risk zones
    top_zones = sorted(zones, key=lambda z: z.get("risk_score", 0), reverse=True)[:10]

    return {
        "total_events": len(road_events),
        "event_types": dict(event_types),
        "zones_count": len(zones),
        "clusters_count": len(clusters),
        "zone_risk_levels": dict(zone_risk_levels),
        "affected_routes": list(affected_routes),
        "top_risk_zones": [
            {
                "zone_id": z.get("zone_id"),
                "risk_score": z.get("risk_score"),
                "risk_level": z.get("risk_level"),
                "defect_count": z.get("defect_count"),
                "routes": z.get("routes_affected", [])[:5] if isinstance(z.get("routes_affected"), list) else [],
            }
            for z in top_zones
        ],
        "trend": trend,
        "trend_slope": round(slope, 4),
        "time_range": label,
        "data_source": "HEURISTIC",
        "record_count": len(road_events),
        "timeline": [{"time": b["time_bucket"], "count": b["count"]} for b in buckets],
        "note": "Road events are detected by heuristic camera analysis. Not validated ground truth.",
    }


# ---------------------------------------------------------------------------
# Driver safety analytics (from events table)
# ---------------------------------------------------------------------------

def get_driver_safety_analytics(time_range="24h", custom_start=None, custom_end=None,
                                bus_id=None):
    """Analyze driver safety events (drowsiness, alerts, etc.).

    Returns event counts, by bus, trends.
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    all_events = persistence.load_events()
    safety_events = [e for e in all_events if e.get("event_type") in (
        "DRIVER_DROWSINESS", "DRIVER_ALERT", "DRIVER_REFRESH_REQUIRED",
        "DRIVER_RECOVERED"
    )]

    if start is not None or end is not None:
        safety_events = [e for e in safety_events if _is_in_range(e.get("timestamp", ""), start, end)]

    if bus_id:
        safety_events = [e for e in safety_events if e.get("bus_id") == bus_id]

    if not safety_events:
        return {
            "total": 0,
            "by_type": {},
            "by_bus": {},
            "by_severity": {},
            "trend": TREND_UNKNOWN,
            "repeated_offenders": [],
            "time_range": label,
            "data_source": "INSUFFICIENT_DATA",
            "record_count": 0,
        }

    by_type = Counter(e.get("event_type", "UNKNOWN") for e in safety_events)
    by_bus = Counter(e.get("bus_id", "UNKNOWN") for e in safety_events)
    by_severity = Counter(e.get("severity", "UNKNOWN") for e in safety_events)

    # Repeated offenders (buses with >1 event)
    repeated = [(bus, count) for bus, count in by_bus.items() if count > 1]
    repeated.sort(key=lambda x: x[1], reverse=True)

    # Trend
    buckets = _bucket_by_time(safety_events, "timestamp", bucket_size_hours=24, start=start, end=end)
    counts = [b["count"] for b in buckets]
    trend, slope = _calculate_trend(counts)

    return {
        "total": len(safety_events),
        "by_type": dict(by_type.most_common()),
        "by_bus": dict(by_bus.most_common(20)),
        "by_severity": dict(by_severity.most_common()),
        "trend": trend,
        "trend_slope": round(slope, 4),
        "repeated_offenders": [{"bus_id": b, "event_count": c} for b, c in repeated[:10]],
        "time_range": label,
        "data_source": "SIMULATION",
        "record_count": len(safety_events),
        "timeline": [{"time": b["time_bucket"], "count": b["count"]} for b in buckets],
        "note": "Driver safety events are detected by heuristic DDS. Not a driver performance score.",
    }


# ---------------------------------------------------------------------------
# Route analytics (cross-domain)
# ---------------------------------------------------------------------------

def get_route_analytics(time_range="24h", custom_start=None, custom_end=None):
    """Cross-domain route analytics.

    For each route: events, incidents, risk events, load, road events.
    Helps identify which routes need most attention.
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    all_events = persistence.load_events()
    all_incidents = persistence.load_incidents()
    all_risk = persistence.load_risk_events(limit=10000)
    all_load = persistence.load_load_snapshots(limit=10000)

    # Filter by time
    if start is not None or end is not None:
        events = [e for e in all_events if _is_in_range(e.get("timestamp", ""), start, end)]
        incidents = [i for i in all_incidents if _is_in_range(i.get("created_at", ""), start, end)]
        risk = [r for r in all_risk if _is_in_range(r.get("created_at", ""), start, end)]
        load = [l for l in all_load if _is_in_range(l.get("created_at", ""), start, end)]
    else:
        events = all_events
        incidents = all_incidents
        risk = all_risk
        load = all_load

    # Collect all routes
    route_set = set()
    for e in events:
        if e.get("route_code"):
            route_set.add(e["route_code"])
    for i in incidents:
        if i.get("route"):
            route_set.add(i["route"])
    for l in load:
        if l.get("route_code"):
            route_set.add(l["route_code"])

    if not route_set:
        return {
            "routes": {},
            "time_range": label,
            "data_source": "INSUFFICIENT_DATA",
            "record_count": 0,
            "note": "No route data available in the selected time range.",
        }

    route_data = {}
    for route in route_set:
        route_events = [e for e in events if e.get("route_code") == route]
        route_incidents = [i for i in incidents if i.get("route") == route]
        route_risk = [r for r in risk if r.get("bus_id") in
                     {e.get("bus_id") for e in route_events}]
        route_load = [l for l in load if l.get("route_code") == route]

        event_types = Counter(e.get("event_type", "UNKNOWN") for e in route_events)
        incident_cats = Counter(i.get("category", "UNKNOWN") for i in route_incidents)

        # Average load utilization
        utils = [l.get("utilization_pct", 0) for l in route_load if l.get("utilization_pct") is not None]
        avg_util = round(sum(utils) / len(utils), 2) if utils else None

        route_data[route] = {
            "event_count": len(route_events),
            "incident_count": len(route_incidents),
            "risk_event_count": len(route_risk),
            "top_event_types": dict(event_types.most_common(5)),
            "top_incident_categories": dict(incident_cats.most_common(5)),
            "avg_utilization": avg_util,
            "load_samples": len(route_load),
        }

    # Rank routes by total events + incidents
    for route in route_data:
        route_data[route]["attention_score"] = (
            route_data[route]["event_count"] +
            route_data[route]["incident_count"] * 2 +
            route_data[route]["risk_event_count"]
        )

    # Sort by attention score
    sorted_routes = sorted(route_data.keys(), key=lambda r: route_data[r]["attention_score"], reverse=True)

    return {
        "routes": route_data,
        "ranked_routes": sorted_routes,
        "time_range": label,
        "data_source": "MIXED",
        "record_count": len(events) + len(incidents),
    }


# ---------------------------------------------------------------------------
# Bus analytics (cross-domain)
# ---------------------------------------------------------------------------

def get_bus_analytics(time_range="24h", custom_start=None, custom_end=None,
                      bus_id=None):
    """Cross-domain bus analytics.

    For each bus: events, incidents, risk, load, health indicators.
    Helps identify which buses repeatedly require attention.
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    all_events = persistence.load_events()
    all_incidents = persistence.load_incidents()
    all_risk = persistence.load_risk_events(limit=10000)
    all_load = persistence.load_load_snapshots(limit=10000)
    all_eta = persistence.load_eta_snapshots(limit=10000)

    # Filter by time
    if start is not None or end is not None:
        events = [e for e in all_events if _is_in_range(e.get("timestamp", ""), start, end)]
        incidents = [i for i in all_incidents if _is_in_range(i.get("created_at", ""), start, end)]
        risk = [r for r in all_risk if _is_in_range(r.get("created_at", ""), start, end)]
        load = [l for l in all_load if _is_in_range(l.get("created_at", ""), start, end)]
        eta = [e for e in all_eta if _is_in_range(e.get("created_at", ""), start, end)]
    else:
        events = all_events
        incidents = all_incidents
        risk = all_risk
        load = all_load
        eta = all_eta

    # Collect all bus IDs
    bus_set = set()
    for e in events:
        if e.get("bus_id"):
            bus_set.add(e["bus_id"])
    for i in incidents:
        if i.get("bus_id"):
            bus_set.add(i["bus_id"])

    if bus_id:
        bus_set = {bus_id}

    if not bus_set:
        return {
            "buses": {},
            "time_range": label,
            "data_source": "INSUFFICIENT_DATA",
            "record_count": 0,
            "note": "No bus data available in the selected time range.",
        }

    bus_data = {}
    for bus in bus_set:
        bus_events = [e for e in events if e.get("bus_id") == bus]
        bus_incidents = [i for i in incidents if i.get("bus_id") == bus]
        bus_risk = [r for r in risk if r.get("bus_id") == bus]
        bus_load = [l for l in load if l.get("bus_id") == bus]
        bus_eta = [e for e in eta if e.get("bus_id") == bus]

        event_types = Counter(e.get("event_type", "UNKNOWN") for e in bus_events)
        incident_cats = Counter(i.get("category", "UNKNOWN") for i in bus_incidents)
        risk_levels = Counter(r.get("risk_level", "UNKNOWN") for r in bus_risk)

        # Average load utilization
        utils = [l.get("utilization_pct", 0) for l in bus_load if l.get("utilization_pct") is not None]
        avg_util = round(sum(utils) / len(utils), 2) if utils else None

        # Severe delays
        severe_delays = sum(1 for e in bus_eta if "severe" in (e.get("delay_summary", "") or "").lower())

        bus_data[bus] = {
            "event_count": len(bus_events),
            "incident_count": len(bus_incidents),
            "risk_event_count": len(bus_risk),
            "high_risk_count": sum(1 for r in bus_risk if r.get("risk_level") in ("HIGH", "CRITICAL")),
            "severe_delay_count": severe_delays,
            "top_event_types": dict(event_types.most_common(5)),
            "top_incident_categories": dict(incident_cats.most_common(5)),
            "risk_levels": dict(risk_levels),
            "avg_utilization": avg_util,
            "load_samples": len(bus_load),
        }

    # Attention score
    for bus in bus_data:
        bus_data[bus]["attention_score"] = (
            bus_data[bus]["event_count"] +
            bus_data[bus]["incident_count"] * 3 +
            bus_data[bus]["high_risk_count"] * 2 +
            bus_data[bus]["severe_delay_count"]
        )

    # Top buses requiring attention
    ranked = sorted(bus_data.keys(), key=lambda b: bus_data[b]["attention_score"], reverse=True)

    return {
        "buses": bus_data,
        "ranked_buses": ranked[:20],
        "time_range": label,
        "data_source": "MIXED",
        "record_count": len(events) + len(incidents),
    }


# ---------------------------------------------------------------------------
# Cross-domain insights
# ---------------------------------------------------------------------------

def get_cross_domain_insights(time_range="24h", custom_start=None, custom_end=None):
    """Generate cross-domain insights from available data.

    Returns contextual relationships (NOT causal claims).
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    insights = []

    # Load data from all domains
    all_events = persistence.load_events()
    all_incidents = persistence.load_incidents()
    all_risk = persistence.load_risk_events(limit=10000)
    all_load = persistence.load_load_snapshots(limit=10000)
    all_road = persistence.load_road_risk_zones()
    all_eta = persistence.load_eta_snapshots(limit=10000)

    # Filter by time
    if start is not None or end is not None:
        events = [e for e in all_events if _is_in_range(e.get("timestamp", ""), start, end)]
        incidents = [i for i in all_incidents if _is_in_range(i.get("created_at", ""), start, end)]
        risk = [r for r in all_risk if _is_in_range(r.get("created_at", ""), start, end)]
        load = [l for l in all_load if _is_in_range(l.get("created_at", ""), start, end)]
        eta = [e for e in all_eta if _is_in_range(e.get("created_at", ""), start, end)]
    else:
        events = all_events
        incidents = all_incidents
        risk = all_risk
        load = all_load
        eta = all_eta

    # Insight 1: Routes with most incidents
    route_incidents = Counter(i.get("route", "UNKNOWN") for i in incidents if i.get("route"))
    if route_incidents:
        top_route, count = route_incidents.most_common(1)[0]
        if count >= 2:
            insights.append({
                "type": "route_incidents",
                "severity": "MEDIUM",
                "title": f"Route {top_route} has the most incidents",
                "detail": f"Route {top_route} recorded {count} incidents in the selected period.",
                "recommendation": f"Investigate operational conditions on route {top_route}.",
                "data_source": "SIMULATION",
            })

    # Insight 2: Buses with repeated events
    bus_events = Counter(e.get("bus_id", "UNKNOWN") for e in events)
    repeated = [(bus, count) for bus, count in bus_events.items() if count >= 3]
    if repeated:
        top_bus, count = repeated[0]
        insights.append({
            "type": "bus_repeated_events",
            "severity": "MEDIUM",
            "title": f"Bus {top_bus} has repeated events",
            "detail": f"Bus {top_bus} generated {count} events in the selected period.",
            "recommendation": f"Review bus {top_bus} operational history for patterns.",
            "data_source": "SIMULATION",
        })

    # Insight 3: High-risk buses
    high_risk_buses = Counter(r.get("bus_id") for r in risk if r.get("risk_level") in ("HIGH", "CRITICAL"))
    if high_risk_buses:
        top_risk_bus, count = high_risk_buses.most_common(1)[0]
        if count >= 2:
            insights.append({
                "type": "bus_high_risk",
                "severity": "HIGH",
                "title": f"Bus {top_risk_bus} has multiple high-risk events",
                "detail": f"Bus {top_risk_bus} had {count} high/critical risk events.",
                "recommendation": f"Review risk factors for bus {top_risk_bus}.",
                "data_source": "SIMULATION",
            })

    # Insight 4: Overloaded buses
    overloaded = [l for l in load if l.get("utilization_pct", 0) >= 100]
    if overloaded:
        ol_buses = Counter(l.get("bus_id") for l in overloaded)
        top_ol_bus, count = ol_buses.most_common(1)[0]
        insights.append({
            "type": "bus_overloaded",
            "severity": "HIGH",
            "title": f"Bus {top_ol_bus} experienced capacity overflow",
            "detail": f"Bus {top_ol_bus} was overloaded {count} times.",
            "recommendation": f"Review capacity allocation for bus {top_ol_bus}.",
            "data_source": "SIMULATION",
        })

    # Insight 5: Road risk zones affecting multiple routes
    for zone in all_road:
        routes = zone.get("routes_affected", [])
        if isinstance(routes, str):
            try:
                routes = json.loads(routes)
            except (json.JSONDecodeError, TypeError):
                routes = []
        if len(routes) >= 3:
            insights.append({
                "type": "road_multi_route",
                "severity": "MEDIUM",
                "title": f"Road risk zone affects {len(routes)} routes",
                "detail": f"Zone {zone.get('zone_id')} (risk: {zone.get('risk_score')}) affects routes: {', '.join(routes[:5])}",
                "recommendation": "Investigate road conditions at this location.",
                "data_source": "HEURISTIC",
            })
            break  # Only show one

    # Insight 6: Severe delays
    severe_eta = [e for e in eta if "severe" in (e.get("delay_summary", "") or "").lower()]
    if severe_eta:
        delay_buses = Counter(e.get("bus_id") for e in severe_eta)
        top_delay_bus, count = delay_buses.most_common(1)[0]
        insights.append({
            "type": "bus_severe_delays",
            "severity": "MEDIUM",
            "title": f"Bus {top_delay_bus} has severe delays",
            "detail": f"Bus {top_delay_bus} experienced {count} severe delays.",
            "recommendation": f"Review route conditions for bus {top_delay_bus}.",
            "data_source": "HEURISTIC",
        })

    # Insight 7: No significant pattern
    if not insights:
        insights.append({
            "type": "no_pattern",
            "severity": "INFO",
            "title": "No significant pattern detected",
            "detail": "Insufficient data or no strong patterns found in the selected period.",
            "recommendation": "Expand the time range or check data availability.",
            "data_source": "UNKNOWN",
        })

    return {
        "insights": insights[:10],
        "time_range": label,
        "data_source": "MIXED",
        "record_count": len(events) + len(incidents),
    }


# ---------------------------------------------------------------------------
# Fleet KPI summary
# ---------------------------------------------------------------------------

def get_fleet_kpis(time_range="24h", custom_start=None, custom_end=None):
    """Get high-level fleet KPIs from persisted data.

    Returns operational metrics from actual records.
    """
    start, end, label = _parse_time_range(time_range, custom_start, custom_end)

    all_events = persistence.load_events()
    all_incidents = persistence.load_incidents()
    all_risk = persistence.load_risk_events(limit=10000)
    all_load = persistence.load_load_snapshots(limit=10000)
    all_eta = persistence.load_eta_snapshots(limit=10000)

    # Filter by time
    if start is not None or end is not None:
        events = [e for e in all_events if _is_in_range(e.get("timestamp", ""), start, end)]
        incidents = [i for i in all_incidents if _is_in_range(i.get("created_at", ""), start, end)]
        risk = [r for r in all_risk if _is_in_range(r.get("created_at", ""), start, end)]
        load = [l for l in all_load if _is_in_range(l.get("created_at", ""), start, end)]
        eta = [e for e in all_eta if _is_in_range(e.get("created_at", ""), start, end)]
    else:
        events = all_events
        incidents = all_incidents
        risk = all_risk
        load = all_load
        eta = all_eta

    # Unique buses with events
    active_buses = set(e.get("bus_id") for e in events if e.get("bus_id"))

    # Active incidents
    active_incidents = sum(1 for i in incidents if i.get("status") in ("OPEN", "INVESTIGATING"))
    critical_incidents = sum(1 for i in incidents if i.get("severity") == "CRITICAL" and i.get("status") != "CLOSED")

    # High-risk events
    high_risk_events = sum(1 for r in risk if r.get("risk_level") in ("HIGH", "CRITICAL"))

    # Overloaded buses
    overloaded = sum(1 for l in load if l.get("utilization_pct", 0) >= 100)

    # Severe delays
    severe_delays = sum(1 for e in eta if "severe" in (e.get("delay_summary", "") or "").lower())

    # Event type breakdown
    event_types = Counter(e.get("event_type", "UNKNOWN") for e in events)

    # Determine data source
    sim_events = sum(1 for e in events if e.get("simulation"))
    data_source = "SIMULATION" if sim_events > 0 else "LIVE"

    return {
        "time_range": label,
        "data_source": data_source,
        "total_events": len(events),
        "active_buses": len(active_buses),
        "total_incidents": len(incidents),
        "active_incidents": active_incidents,
        "critical_incidents": critical_incidents,
        "high_risk_events": high_risk_events,
        "overloaded_buses": overloaded,
        "severe_delays": severe_delays,
        "top_event_types": dict(event_types.most_common(10)),
        "record_count": len(events) + len(incidents) + len(risk) + len(load) + len(eta),
    }


# ---------------------------------------------------------------------------
# Comprehensive analytics endpoint
# ---------------------------------------------------------------------------

def get_analytics_dashboard(time_range="24h", custom_start=None, custom_end=None):
    """Get comprehensive analytics for the analytics dashboard.

    Combines all domain analytics into a single response.
    """
    return {
        "kpis": get_fleet_kpis(time_range, custom_start, custom_end),
        "events": get_event_analytics(time_range, custom_start, custom_end),
        "incidents": get_incident_analytics(time_range, custom_start, custom_end),
        "risk": get_risk_analytics(time_range, custom_start, custom_end),
        "eta": get_eta_analytics(time_range, custom_start, custom_end),
        "load": get_load_analytics(time_range, custom_start, custom_end),
        "road": get_road_analytics(time_range, custom_start, custom_end),
        "driver_safety": get_driver_safety_analytics(time_range, custom_start, custom_end),
        "routes": get_route_analytics(time_range, custom_start, custom_end),
        "buses": get_bus_analytics(time_range, custom_start, custom_end),
        "insights": get_cross_domain_insights(time_range, custom_start, custom_end),
        "time_range": time_range,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
