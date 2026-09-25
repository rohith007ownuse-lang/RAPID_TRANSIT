"""
historical_intelligence.py
Historical Intelligence Engine.

Analyzes persisted data to identify recurring patterns, hotspot history,
route delay patterns, peak problem periods, and vehicle health trends.

Answers "WHAT KEEPS HAPPENING?" not just "WHAT IS HAPPENING NOW?"

Produces:
- Recurring hotspot detection (same location, multiple days)
- Route delay patterns (hour-of-day analysis)
- Peak problem periods (time-of-day, day-of-week patterns)
- Vehicle health trends (improving/degrading/stable)
- Incident frequency analysis (per-route, per-area)

DATA CLASSIFICATION: HISTORICAL ANALYTICS LAYER
Uses persisted data from SQLite. No real-time data.
"""

import threading
import math
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from collections import defaultdict, Counter
from constants import parse_timestamp, now_iso, IST


# Deterministic seed so the simulated history is stable across reloads.
# Same thresholds / code paths as the persisted analysis — only the input
# rows are synthesized when no logs are stored yet.
SIMULATION_SEED = 2026

# Rush-hour weights for spreading synthesized timestamps across the service
# day (05:00–23:00): strong morning rush (7–9), evening rush (17–19).
SIM_HOUR_WEIGHTS = {
    5: 0.5, 6: 1.0, 7: 2.2, 8: 2.6, 9: 1.9, 10: 1.2, 11: 1.0,
    12: 0.9, 13: 0.8, 14: 0.55, 15: 0.7, 16: 1.1, 17: 1.9, 18: 2.3,
    19: 1.6, 20: 1.0, 21: 0.6, 22: 0.3, 23: 0.15,
}

SIM_EVENT_TYPES = [
    "POTHOLE", "OVERLOAD", "HARD_BRAKING", "OVERSPEED",
    "DRIVER_DROWSINESS", "VEHICLE_ANOMALY", "EMERGENCY_SIREN",
]

# Fixed hotspot anchors — well-known Chennai congestion / road-stress
# junctions. The simulation always plants repeat incidents here (spread
# across distinct days, jittered well inside one GRID_SIZE cell) so the
# recurring-hotspot leg has clear, explainable output even on a fresh DB.
# Jitter must stay < GRID_SIZE/2 (0.005 deg) to guarantee same-cell grouping.
SIM_HOTSPOT_ANCHORS = [
    {"name": "Koyambedu Junction", "lat": 13.0697, "lon": 80.1970,
     "event_type": "POTHOLE", "days": 5, "per_day": 2},
    {"name": "Tambaram - Beach Rd", "lat": 12.9249, "lon": 80.1000,
     "event_type": "OVERLOAD", "days": 4, "per_day": 2},
    {"name": "T.Nagar Bus Terminus", "lat": 13.0410, "lon": 80.2340,
     "event_type": "HARD_BRAKING", "days": 4, "per_day": 2},
    {"name": "Adyar - OMR Link", "lat": 12.9980, "lon": 80.2570,
     "event_type": "OVERSPEED", "days": 3, "per_day": 2},
    {"name": "Anna Nagar Roundabout", "lat": 13.0850, "lon": 80.2101,
     "event_type": "POTHOLE", "days": 3, "per_day": 2},
]

# Rush hours used for BOTH the simulated peaks and the route-delay legs so
# the story is consistent: morning 7-9, evening 17-19.
SIM_RUSH_HOURS = [7, 8, 17, 18]


def _stable_seed(window):
    """Deterministic seed per window (hash() is salted per process)."""
    return SIMULATION_SEED + sum(ord(c) for c in str(window)) % 1000


def _bus_needs_attention(bus):
    """True when a fleet-snapshot bus looks unhealthy.

    The simulator stores ``bus["_attention"]`` as a real bool (not a
    marker string), so check truthiness first; fall back to the legacy
    marker-string, vehicle-health and driver-state signals.
    """
    if bus.get("_attention") is True:
        return True
    if "_attention" in str(bus.get("_attention", "")):
        return True
    if "_prone" in str(bus.get("_prone", "")):
        return True
    vehicle = bus.get("vehicle") or {}
    driver = bus.get("driver") or {}
    if vehicle.get("health") in ("WARNING", "INSPECTION REQUIRED"):
        return True
    if driver.get("state") in ("ATTENTION", "DROWSY"):
        return True
    return False


# ---------------------------------------------------------------------------
# Historical analysis configuration
# ---------------------------------------------------------------------------

# Time window presets (seconds)
HISTORY_WINDOWS = {
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
}

# Spatial grid size for hotspot detection (degrees, ~1km)
GRID_SIZE = 0.01

# Minimum incidents for a location to be "recurring"
RECURRING_THRESHOLD = 3

# Trend calculation minimum samples
MIN_SAMPLES = 3


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance in kilometers."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _grid_key(lat, lon):
    """Snap a coordinate to a grid cell key."""
    return (round(lat / GRID_SIZE) * GRID_SIZE, round(lon / GRID_SIZE) * GRID_SIZE)


def _parse_ts(ts):
    """Parse ISO timestamp to datetime (always UTC-aware).

    Live simulator rows occasionally carry timezone-naive stamps; those
    are assumed UTC. Without this, a single naive row makes
    `ts > cutoff` raise TypeError and kills the whole endpoint (500).
    """
    dt = parse_timestamp(ts)
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _calculate_trend(values, min_samples=MIN_SAMPLES):
    """Calculate trend from a list of values (increasing/stable/decreasing)."""
    if len(values) < min_samples:
        return "UNKNOWN", 0.0
    # Simple linear regression
    n = len(values)
    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(values) / n
    numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return "STABLE", 0.0
    slope = numerator / denominator
    if slope > 0.5:
        return "INCREASING", slope
    elif slope < -0.5:
        return "DECREASING", slope
    return "STABLE", slope


# ---------------------------------------------------------------------------
# Historical Intelligence Engine
# ---------------------------------------------------------------------------

class HistoricalIntelligenceEngine:
    """
    Analyzes historical data to identify recurring patterns and trends.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}
        self._cache_time = None
        self._cache_ttl = 120  # seconds

    def analyze_recurring_hotspots(self, events=None, incidents=None,
                                    road_defects=None, window="7d"):
        """
        Identify recurring hotspots — locations with repeated incidents
        across multiple days.

        Returns a list of recurring hotspot objects.
        """
        window_seconds = HISTORY_WINDOWS.get(window, 604800)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

        # Collect all location-tagged events
        location_events = []

        for evt in (events or []):
            ts = _parse_ts(evt.get("timestamp"))
            if ts and ts > cutoff:
                lat = evt.get("latitude")
                lon = evt.get("longitude")
                if lat and lon:
                    location_events.append({
                        "lat": lat, "lon": lon,
                        "type": evt.get("event_type"),
                        "severity": evt.get("severity"),
                        "timestamp": ts,
                        "bus_id": evt.get("bus_id"),
                    })

        for inc in (incidents or []):
            ts = _parse_ts(inc.get("created_at"))
            if ts and ts > cutoff:
                loc = inc.get("location")
                if loc:
                    # Try to parse location string "lat, lon"
                    try:
                        parts = str(loc).split(",")
                        lat, lon = float(parts[0].strip()), float(parts[1].strip())
                        location_events.append({
                            "lat": lat, "lon": lon,
                            "type": inc.get("category"),
                            "severity": inc.get("severity"),
                            "timestamp": ts,
                            "bus_id": inc.get("bus_id"),
                        })
                    except (ValueError, IndexError):
                        pass

        # Group by grid cell
        grid_cells = defaultdict(list)
        for evt in location_events:
            key = _grid_key(evt["lat"], evt["lon"])
            grid_cells[key].append(evt)

        # Find recurring cells.
        # 24h windows can never span 3 unique days, so they use a repeat
        # count instead (>=4 events in one cell = repeat offender today).
        recurring = []
        for key, cell_events in grid_cells.items():
            # Count unique days
            days = set()
            for evt in cell_events:
                days.add(evt["timestamp"].date())

            if window == "24h":
                is_recurring = len(cell_events) >= 4
                pattern = "RECURRING" if len(cell_events) >= 6 else "TEMPORARY"
            elif len(days) >= RECURRING_THRESHOLD:
                is_recurring = True
                pattern = "RECURRING" if len(days) >= 3 else "TEMPORARY"
            else:
                is_recurring = False
                pattern = "TEMPORARY"

            if is_recurring:
                # Compute centroid
                avg_lat = sum(e["lat"] for e in cell_events) / len(cell_events)
                avg_lon = sum(e["lon"] for e in cell_events) / len(cell_events)

                # Severity distribution
                sev_counts = Counter(e["severity"] for e in cell_events)
                event_types = Counter(e["type"] for e in cell_events)

                recurring.append({
                    "location": {"lat": round(avg_lat, 4), "lon": round(avg_lon, 4)},
                    "incident_count": len(cell_events),
                    "unique_days": len(days),
                    "first_seen": min(e["timestamp"] for e in cell_events).isoformat(),
                    "last_seen": max(e["timestamp"] for e in cell_events).isoformat(),
                    "severity_distribution": dict(sev_counts),
                    "event_types": dict(event_types),
                    "affected_buses": list(set(e["bus_id"] for e in cell_events if e["bus_id"])),
                    "pattern": pattern,
                })

        # Sort by incident count (most frequent first)
        recurring.sort(key=lambda x: x["incident_count"], reverse=True)

        return {
            "window": window,
            "total_locations": len(grid_cells),
            "recurring_count": len(recurring),
            "recurring_hotspots": recurring[:20],
        }

    def analyze_route_delay_patterns(self, eta_snapshots=None, window="7d"):
        """
        Analyze delay patterns per route per hour-of-day.

        Identifies systematic delays (e.g., "Route 19D always delayed at 8 AM").
        """
        if not eta_snapshots:
            return {"patterns": [], "peak_delays": []}

        window_seconds = HISTORY_WINDOWS.get(window, 604800)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

        # Group by route and hour
        route_hour_delays = defaultdict(lambda: defaultdict(list))

        for snap in eta_snapshots:
            ts = _parse_ts(snap.get("created_at"))
            if not ts or ts <= cutoff:
                continue

            bus_id = snap.get("bus_id")
            delay_summary = snap.get("delay_summary", "")

            # Convert to IST for hour analysis
            ist_hour = ts.astimezone(IST).hour

            # Estimate delay minutes from summary
            delay_minutes = 0
            if "severe" in str(delay_summary).lower():
                delay_minutes = 15
            elif "significant" in str(delay_summary).lower():
                delay_minutes = 10
            elif "minor" in str(delay_summary).lower():
                delay_minutes = 5

            if delay_minutes > 0 and bus_id:
                # Try to get route from bus_id ("19D .2" -> "19D").
                # Simulator ids carry a " .N" suffix with a stray space,
                # so strip it to keep route codes clean.
                route_code = bus_id.split(".")[0].strip() if "." in bus_id else bus_id.strip()
                route_hour_delays[route_code][ist_hour].append(delay_minutes)

        # Analyze patterns
        patterns = []
        for route_code, hour_data in route_hour_delays.items():
            hourly_avg = {}
            for hour, delays in hour_data.items():
                if delays:
                    hourly_avg[hour] = round(sum(delays) / len(delays), 1)

            if hourly_avg:
                # Find peak delay hours
                peak_hour = max(hourly_avg, key=hourly_avg.get)
                patterns.append({
                    "route_code": route_code,
                    "peak_delay_hour": peak_hour,
                    "peak_delay_minutes": hourly_avg[peak_hour],
                    "hourly_delays": hourly_avg,
                    "sample_count": sum(len(d) for d in hour_data.values()),
                })

        # Sort by peak delay (worst first)
        patterns.sort(key=lambda x: x["peak_delay_minutes"], reverse=True)

        return {
            "window": window,
            "patterns": patterns[:10],
            "peak_delays": [
                {"route": p["route_code"], "hour": p["peak_delay_hour"],
                 "delay_minutes": p["peak_delay_minutes"]}
                for p in patterns[:5]
            ],
        }

    def analyze_peak_periods(self, events=None, incidents=None, window="7d"):
        """
        Identify peak problem periods — time-of-day and day-of-week patterns.
        """
        window_seconds = HISTORY_WINDOWS.get(window, 604800)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

        # Collect timestamps
        hourly_counts = defaultdict(int)
        daily_counts = defaultdict(int)
        weekday_counts = defaultdict(int)

        all_timestamps = []

        for evt in (events or []):
            ts = _parse_ts(evt.get("timestamp"))
            if ts and ts > cutoff:
                all_timestamps.append(ts)

        for inc in (incidents or []):
            ts = _parse_ts(inc.get("created_at"))
            if ts and ts > cutoff:
                all_timestamps.append(ts)

        for ts in all_timestamps:
            ist_ts = ts.astimezone(IST)
            hourly_counts[ist_ts.hour] += 1
            daily_counts[ist_ts.strftime("%Y-%m-%d")] += 1
            weekday_counts[ist_ts.strftime("%A")] += 1

        # Find peak hours
        peak_hours = sorted(hourly_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Find peak days
        peak_days = sorted(daily_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Trend over time (daily counts)
        daily_values = [daily_counts[d] for d in sorted(daily_counts.keys())]
        trend, slope = _calculate_trend(daily_values)

        return {
            "window": window,
            "total_events": len(all_timestamps),
            "peak_hours": [{"hour": h, "count": c} for h, c in peak_hours],
            "peak_days": [{"date": d, "count": c} for d, c in peak_days],
            "weekday_distribution": dict(weekday_counts),
            "daily_trend": trend,
            "trend_slope": round(slope, 2),
        }

    def analyze_vehicle_health_trends(self, risk_events=None, window="30d"):
        """
        Analyze vehicle health trends over time.

        Identifies improving, degrading, or stable vehicle health.
        """
        window_seconds = HISTORY_WINDOWS.get(window, 2592000)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

        # Group risk events by bus
        bus_risk_history = defaultdict(list)

        for evt in (risk_events or []):
            ts = _parse_ts(evt.get("created_at"))
            if not ts or ts <= cutoff:
                continue

            bus_id = evt.get("bus_id")
            risk_score = evt.get("risk_score")
            if bus_id and risk_score is not None:
                bus_risk_history[bus_id].append({
                    "timestamp": ts,
                    "risk_score": risk_score,
                    "risk_level": evt.get("risk_level"),
                })

        # Analyze trends per bus
        trends = []
        for bus_id, history in bus_risk_history.items():
            # Sort by timestamp
            history.sort(key=lambda x: x["timestamp"])

            scores = [h["risk_score"] for h in history]
            trend, slope = _calculate_trend(scores)

            # Classify
            if slope > 1.0:
                health_trend = "DEGRADING"
            elif slope < -1.0:
                health_trend = "IMPROVING"
            else:
                health_trend = "STABLE"

            trends.append({
                "bus_id": bus_id,
                "health_trend": health_trend,
                "current_risk": scores[-1] if scores else 0,
                "average_risk": round(sum(scores) / len(scores), 1) if scores else 0,
                "risk_slope": round(slope, 2),
                "data_points": len(scores),
                "first_seen": history[0]["timestamp"].isoformat(),
                "last_seen": history[-1]["timestamp"].isoformat(),
            })

        # Sort by trend (degrading first)
        trend_order = {"DEGRADING": 0, "STABLE": 1, "IMPROVING": 2}
        trends.sort(key=lambda x: (trend_order.get(x["health_trend"], 1), -x["current_risk"]))

        return {
            "window": window,
            "total_buses": len(trends),
            "degrading": sum(1 for t in trends if t["health_trend"] == "DEGRADING"),
            "stable": sum(1 for t in trends if t["health_trend"] == "STABLE"),
            "improving": sum(1 for t in trends if t["health_trend"] == "IMPROVING"),
            "bus_trends": trends[:20],
        }

    def get_comprehensive_history(self, events=None, incidents=None,
                                    road_defects=None, risk_events=None,
                                    eta_snapshots=None, window="7d"):
        """
        Generate a comprehensive historical analysis combining all analyses.
        """
        hotspots = self.analyze_recurring_hotspots(events, incidents, road_defects, window)
        delays = self.analyze_route_delay_patterns(eta_snapshots, window)
        peaks = self.analyze_peak_periods(events, incidents, window)
        health = self.analyze_vehicle_health_trends(risk_events, window)

        return {
            "window": window,
            "recurring_hotspots": hotspots,
            "route_delay_patterns": delays,
            "peak_periods": peaks,
            "vehicle_health_trends": health,
            "generated_at": now_iso(),
        }

    # ------------------------------------------------------------------
    # Simulation fallback: when no logs are persisted yet, synthesize a
    # deterministic pseudo-history from the CURRENT live fleet state so
    # the Historical page still shows realistic patterns (route delay
    # patterns, peak problem hours, recurring hotspots, health trends).
    # Everything is labelled simulation=True by the caller.
    # ------------------------------------------------------------------

    def _sim_hour(self, rng):
        """Pick a service-day hour weighted by rush-hour demand."""
        hours = sorted(SIM_HOUR_WEIGHTS)
        weights = [SIM_HOUR_WEIGHTS[h] for h in hours]
        return rng.choices(hours, weights=weights, k=1)[0]

    def _sim_timestamp(self, rng, window, hour=None):
        """ISO timestamp within the window, at a plausible service hour."""
        window_seconds = HISTORY_WINDOWS.get(window, 604800)
        days = max(1, window_seconds // 86400)
        now = datetime.now(timezone.utc)
        day_offset = rng.randint(0, days - 1)
        h = hour if hour is not None else self._sim_hour(rng)
        minute = rng.randint(0, 59)
        ts = (now - timedelta(days=day_offset)).replace(
            hour=h, minute=minute, second=0, microsecond=0)
        # Convert IST service hour to UTC for storage
        ts = ts - timedelta(hours=5, minutes=30)
        if ts > now:
            ts = now - timedelta(hours=rng.randint(1, 6))
        return ts

    def synthesize_inputs(self, buses=None, events=None, road_defects=None,
                          window="7d"):
        """
        Build deterministic simulated (events, incidents, risk_events,
        eta_snapshots) from the current fleet snapshot.

        Only used when persisted inputs are empty. Guarantees a CLEAR,
        explainable story on every leg:

        - recurring hotspots: fixed Chennai anchors with repeat incidents
          across distinct days (same grid cell every time);
        - route delays: rush-hour (7-9, 17-19) delay bands per route;
        - peak periods: event timestamps weighted to rush hours;
        - vehicle health: every 5th bus DEGRADING, every 5th+2 IMPROVING,
          the rest STABLE, with slopes well outside the +/-1.0 band.
        """
        rng = random.Random(_stable_seed(window))
        buses = buses or []
        live_events = list(events or [])
        defects = road_defects or []

        sim_events, sim_risk, sim_eta = [], [], []
        sim_incidents = []

        window_seconds = HISTORY_WINDOWS.get(window, 604800)
        span_days = max(1, window_seconds // 86400)

        def _anchor_day(offset):
            """A timestamp `offset` days ago at a rush-ish service hour."""
            now = datetime.now(timezone.utc)
            h = rng.choice(SIM_RUSH_HOURS + [10, 12, 15, 20])
            ts = (now - timedelta(days=offset)).replace(
                hour=h, minute=rng.randint(0, 59), second=0, microsecond=0)
            ts = ts - timedelta(hours=5, minutes=30)  # IST service hour -> UTC
            if ts > now:
                ts = now - timedelta(hours=rng.randint(1, 6))
            return ts

        # -- Leg 1 (guaranteed): anchor hotspots, one grid cell each. --
        # Jitter +/-0.002 deg keeps every repeat inside the same 0.01 deg
        # cell; distinct day offsets satisfy the >=3-unique-days rule.
        # For the 24h window every repeat lands today (>=4 per cell).
        anchor_bus = (buses[0].get("bus_id", "19D") if buses else "19D")
        anchor_route = ""
        if buses:
            anchor_route = (buses[0].get("route_code")
                            or str(buses[0].get("bus_id", "")).split(".")[0].strip())
        for anchor in SIM_HOTSPOT_ANCHORS:
            day_offsets = ([0] * (anchor["days"] * anchor["per_day"])
                           if window == "24h"
                           else [d % span_days
                                 for d in range(anchor["days"]) for _ in range(anchor["per_day"])])
            for offset in day_offsets:
                ts = _anchor_day(offset)
                sim_events.append({
                    "event_type": anchor["event_type"],
                    "severity": rng.choices(
                        ["CRITICAL", "WARNING", "INFO"],
                        weights=[1, 4, 3], k=1)[0],
                    "bus_id": anchor_bus,
                    "route_code": anchor_route,
                    "latitude": round(anchor["lat"] + rng.uniform(-0.002, 0.002), 5),
                    "longitude": round(anchor["lon"] + rng.uniform(-0.002, 0.002), 5),
                    "timestamp": ts.isoformat(),
                    "simulation": True,
                })

        # Anchor hotspots on real defect locations so recurring-hotspot
        # analysis has genuine spatial structure.
        defect_anchors = []
        for d in defects[:30]:
            try:
                defect_anchors.append((float(d.get("lat")), float(d.get("lon"))))
            except (TypeError, ValueError):
                continue

        for idx, bus in enumerate(buses):
            bus_id = bus.get("bus_id", "UNKNOWN")
            route_code = (bus.get("route_code")
                          or str(bus_id).split(".")[0].strip())
            lat = bus.get("latitude", 13.0) or 13.0
            lon = bus.get("longitude", 80.2) or 80.2
            attention = _bus_needs_attention(bus)
            n_events = rng.randint(3, 8) if attention else rng.randint(0, 2)
            # Clear health story by fleet position: degrading / improving /
            # stable rotation with slopes well outside the +/-1.0 band.
            role = idx % 5
            if role == 0:
                base_risk, drift = rng.uniform(45, 60), rng.uniform(1.8, 2.6)
            elif role == 2:
                base_risk, drift = rng.uniform(55, 70), rng.uniform(-2.6, -1.8)
            elif attention:
                base_risk, drift = rng.uniform(55, 80), rng.uniform(1.2, 2.0)
            else:
                base_risk, drift = rng.uniform(10, 35), rng.uniform(-0.4, 0.4)

            # Risk-event history: degrading slope for attention vehicles.
            n_risk = rng.randint(4, 10)
            for i in range(n_risk):
                ts = self._sim_timestamp(rng, window)
                score = max(0, min(100, base_risk + drift * i + rng.uniform(-4, 4)))
                sim_risk.append({
                    "bus_id": bus_id,
                    "risk_score": round(score, 1),
                    "risk_level": "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW",
                    "created_at": ts.isoformat(),
                })

            # ETA snapshots: rush-hour delays on busy routes. Attention and
            # degrading-role buses skew hard to rush-hour delay bands so the
            # route-delay leg always has a clear 7-9 / 17-19 story.
            delay_prone = attention or role == 0
            n_eta = rng.randint(2, 6) if delay_prone else rng.randint(0, 2)
            for _ in range(n_eta):
                rush = rng.random() < (0.8 if delay_prone else 0.5)
                h = rng.choice(SIM_RUSH_HOURS) if rush else self._sim_hour(rng)
                ts = self._sim_timestamp(rng, window, hour=h)
                band = rng.choices(
                    ["ON_TIME", "MINOR_DELAY", "SIGNIFICANT_DELAY", "SEVERE_DELAY"],
                    weights=[1, 3, 4, 2] if rush and delay_prone else [6, 2, 1, 1],
                    k=1,
                )[0]
                sim_eta.append({
                    "bus_id": bus_id,
                    "delay_summary": band,
                    "created_at": ts.isoformat(),
                })

            # Location-tagged events clustered near defects / bus position.
            for _ in range(n_events):
                ts = self._sim_timestamp(rng, window)
                if defect_anchors and rng.random() < 0.5:
                    alat, alon = rng.choice(defect_anchors)
                    elat = alat + rng.uniform(-0.004, 0.004)
                    elon = alon + rng.uniform(-0.004, 0.004)
                    etype = "POTHOLE"
                else:
                    elat = lat + rng.uniform(-0.01, 0.01)
                    elon = lon + rng.uniform(-0.01, 0.01)
                    etype = rng.choice(SIM_EVENT_TYPES)
                sev = rng.choices(
                    ["CRITICAL", "WARNING", "INFO"], weights=[1, 4, 5], k=1)[0]
                sim_events.append({
                    "event_type": etype,
                    "severity": sev,
                    "bus_id": bus_id,
                    "route_code": route_code,
                    "latitude": round(elat, 5),
                    "longitude": round(elon, 5),
                    "timestamp": ts.isoformat(),
                    "simulation": True,
                })

        # A few synthesized incidents for the incident-frequency leg.
        for i in range(min(12, max(3, len(buses) // 25))):
            bus = rng.choice(buses) if buses else {}
            ts = self._sim_timestamp(rng, window)
            sim_incidents.append({
                "category": rng.choice(["crash", "breakdown", "medical", "road"]),
                "severity": rng.choice(["HIGH", "MEDIUM", "CRITICAL"]),
                "status": rng.choice(["OPEN", "ACKNOWLEDGED", "RESOLVED"]),
                "bus_id": (bus or {}).get("bus_id", "UNKNOWN"),
                "location": f"{(bus or {}).get('latitude', 13.0)}, {(bus or {}).get('longitude', 80.2)}",
                "created_at": ts.isoformat(),
            })

        return {
            "events": live_events + sim_events,
            "incidents": sim_incidents,
            "risk_events": sim_risk,
            "eta_snapshots": sim_eta,
            "simulated": True,
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

historical_intelligence_engine = HistoricalIntelligenceEngine()
