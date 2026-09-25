"""
eta.py
ETA / Delay Prediction — dwell-time model + delay banding.

Phase 13 enhancements:
- Route-specific road-friction (integrates road_risk zones, not global defect check)
- Delay cause intelligence (road/vehicle/driver context)
- Deterministic RNG (seeded per-bus for reproducibility)
- ETA smoothing (bounded changes to prevent wild jumps)
- Delay state tracking (change detection for alerts)
- Documented thresholds
- Honest source labeling (SIMULATION/HEURISTIC)
- Per-stop ETA with remaining-distance calculation
- Vehicle health / driver state contextual signals

Methodology: HEURISTIC — distance/speed * traffic_lapse + dwell * occupancy + friction.
No ML models. No fabricated traffic. No fabricated schedules.
"""

import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from data_store import store


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Constants & thresholds (documented)
# ---------------------------------------------------------------------------

# Base dwell time per stop (seconds) by stop type
BASE_DWELL = {
    "major": 35,    # terminals / major junctions
    "normal": 18,   # regular stops
}

# Road friction: extra seconds per stop when conditions apply
ROAD_FRICTION = {
    "pothole_per_stop": 8,      # extra seconds per stop if potholes on segment
    "roadwork_per_stop": 15,    # extra seconds per stop if roadworks on route
    "risk_zone_per_stop": 5,    # extra seconds per stop in high-risk zone
}

# Traffic lapse bounds (heuristic — no real traffic data)
TRAFFIC_LAPSE_MIN = 0.85
TRAFFIC_LAPSE_MAX = 1.25

# Delay severity thresholds (ratio of total_delay / base_dwell)
# Documented: these are heuristic ratios for the prototype, not calibrated
# against real transit data.
DELAY_THRESHOLDS = {
    "ON_TIME_MAX": 1.2,        # <= 1.2x base dwell → ON_TIME
    "MINOR_DELAY_MAX": 1.5,    # <= 1.5x → MINOR_DELAY
    "SIGNIFICANT_DELAY_MAX": 2.0,  # <= 2.0x → SIGNIFICANT_DELAY
    # > 2.0x → SEVERE_DELAY
}

# ETA smoothing: max change per update (seconds) to prevent wild jumps
ETA_SMOOTHING_WINDOW = 120  # 2 minutes max jump

# Delay state change detection
DELAY_STATE_ORDER = ["ON_TIME", "EARLY", "MINOR_DELAY", "SIGNIFICANT_DELAY", "SEVERE_DELAY", "UNKNOWN"]

# Alert thresholds for delay events
SEVERE_DELAY_ALERT_THRESHOLD = 300  # 5 minutes of cumulative delay triggers alert


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ETAPrediction:
    """ETA prediction for a single stop."""
    stop: str
    lat: float
    lon: float
    is_major: bool
    distance_km: float
    base_dwell_sec: int
    friction_delay_sec: int
    traffic_delay_sec: int
    total_delay_sec: int
    eta_iso: str
    delay_band: str  # ON_TIME / EARLY / MINOR_DELAY / SIGNIFICANT_DELAY / SEVERE_DELAY

    def to_dict(self) -> dict:
        return {
            "stop": self.stop,
            "lat": self.lat,
            "lon": self.lon,
            "is_major": self.is_major,
            "distance_km": self.distance_km,
            "base_dwell_sec": self.base_dwell_sec,
            "friction_delay_sec": self.friction_delay_sec,
            "traffic_delay_sec": self.traffic_delay_sec,
            "total_delay_sec": self.total_delay_sec,
            "eta": self.eta_iso,
            "delay_band": self.delay_band,
        }


@dataclass
class DelayCause:
    """A single contributing factor to delay (evidence, not causation)."""
    category: str       # road / vehicle / driver / occupancy / traffic
    description: str
    severity: str       # INFO / WARNING / CRITICAL
    source: str         # SIMULATION / HEURISTIC / LIVE

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "description": self.description,
            "severity": self.severity,
            "source": self.source,
        }


@dataclass
class BusETAResult:
    """Complete ETA result for one bus."""
    bus_id: str
    route: str
    current_stop: str
    destination: str
    etas: List[ETAPrediction]
    delay_summary: str
    delay_causes: List[DelayCause]
    total_remaining_distance_km: float
    total_remaining_time_sec: float
    eta_destination_iso: str
    source: str  # SIMULATION / HEURISTIC / LIVE / UNKNOWN
    simulation: bool
    computed_at: str

    def to_dict(self) -> dict:
        return {
            "bus_id": self.bus_id,
            "route": self.route,
            "current_stop": self.current_stop,
            "destination": self.destination,
            "etas": [e.to_dict() for e in self.etas],
            "delay_summary": self.delay_summary,
            "delay_causes": [c.to_dict() for c in self.delay_causes],
            "total_remaining_distance_km": round(self.total_remaining_distance_km, 3),
            "total_remaining_time_sec": round(self.total_remaining_time_sec, 1),
            "eta_destination": self.eta_destination_iso,
            "source": self.source,
            "simulation": self.simulation,
            "computed_at": self.computed_at,
        }


# ---------------------------------------------------------------------------
# ETA Engine
# ---------------------------------------------------------------------------

class ETAEngine:
    """Computes ETA and delay predictions for buses on their routes.

    Methodology: HEURISTIC
    - Travel time = distance / speed * traffic_lapse
    - Dwell = fixed_base * occupancy_factor
    - Friction = route-specific road-risk zones + pothole defects
    - Delay band = ratio of total_delay / base_dwell
    - Traffic lapse = bounded random variation (no real traffic data)

    No ML models. No fabricated traffic. No fabricated schedules.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._prev_etas: Dict[str, float] = {}  # bus_id -> previous destination ETA (epoch)
        self._prev_delay_states: Dict[str, str] = {}  # bus_id -> previous delay state

    def compute_eta(self, bus: dict, rng: random.Random) -> dict:
        """Compute ETA predictions for a bus's remaining stops.

        Returns a BusETAResult as dict (for backward compatibility).
        """
        journey = bus.get("journey", {})
        if not journey or "stops" not in journey:
            return self._empty_result(bus, "NO_ROUTE")

        stops = journey["stops"]
        if not stops:
            return self._empty_result(bus, "NO_ROUTE")

        current_idx = journey.get("current_index", 0)
        next_idx = journey.get("next_index", current_idx + 1)
        if next_idx is None:
            next_idx = current_idx + 1
        current_stop = stops[current_idx] if current_idx < len(stops) else stops[-1]
        destination = stops[-1] if stops else current_stop

        # Speed (min 5 km/h to avoid division by zero)
        speed = max(5.0, float(bus.get("speed_kmh", 25)))

        # Route-specific road friction
        route_code = bus.get("route_code", "")
        pothole_friction = self._get_route_pothole_friction(route_code, stops, current_idx, next_idx)
        risk_zone_friction = self._get_risk_zone_friction(route_code)

        # Occupancy dwell factor
        occ_pct = float((bus.get("occupancy") or {}).get("pct", 0))
        occupancy_factor = 1.0 + (occ_pct / 100.0) * 0.4  # up to +40% at full

        # Traffic lapse (deterministic per bus via seeded rng)
        traffic_lapse = rng.uniform(TRAFFIC_LAPSE_MIN, TRAFFIC_LAPSE_MAX)

        etas: List[ETAPrediction] = []
        delay_causes: List[DelayCause] = []
        cum_time_sec = 0.0
        cum_distance_km = 0.0

        for i in range(next_idx, len(stops)):
            stop = stops[i]
            prev_stop = stops[i - 1] if i > 0 else current_stop

            # Distance
            dist_km = self._haversine_km(prev_stop["lat"], prev_stop["lon"],
                                          stop["lat"], stop["lon"])
            cum_distance_km += dist_km

            # Travel time
            travel_time_sec = (dist_km / speed) * 3600 * traffic_lapse

            # Base dwell
            is_major = stop.get("major", False)
            base_dwell = BASE_DWELL["major" if is_major else "normal"]
            dwell_sec = int(base_dwell * occupancy_factor)

            # Friction delays
            friction_delay = 0
            if pothole_friction > 0:
                friction_delay += ROAD_FRICTION["pothole_per_stop"] * pothole_friction
            if risk_zone_friction > 0:
                friction_delay += ROAD_FRICTION["risk_zone_per_stop"] * risk_zone_friction

            total_delay = dwell_sec + friction_delay
            cum_time_sec += travel_time_sec + total_delay

            # ETA timestamp
            eta_time = datetime.now(timezone.utc).timestamp() + cum_time_sec

            # Apply smoothing (bounded change from previous ETA for this stop)
            stop_key = f"{bus.get('bus_id', '')}_{stop['stop']}"
            prev_eta = self._prev_etas.get(stop_key)
            if prev_eta is not None:
                change = eta_time - prev_eta
                if abs(change) > ETA_SMOOTHING_WINDOW:
                    # Clamp to smoothing window
                    eta_time = prev_eta + (ETA_SMOOTHING_WINDOW if change > 0 else -ETA_SMOOTHING_WINDOW)
            self._prev_etas[stop_key] = eta_time

            eta_iso = datetime.fromtimestamp(eta_time, timezone.utc).isoformat(timespec="seconds")

            # Delay band (ratio-based)
            delay_ratio = total_delay / max(1, base_dwell)
            if delay_ratio <= DELAY_THRESHOLDS["ON_TIME_MAX"]:
                delay_band = "ON_TIME"
            elif delay_ratio <= DELAY_THRESHOLDS["MINOR_DELAY_MAX"]:
                delay_band = "MINOR_DELAY"
            elif delay_ratio <= DELAY_THRESHOLDS["SIGNIFICANT_DELAY_MAX"]:
                delay_band = "SIGNIFICANT_DELAY"
            else:
                delay_band = "SEVERE_DELAY"

            etas.append(ETAPrediction(
                stop=stop["stop"],
                lat=stop["lat"],
                lon=stop["lon"],
                is_major=is_major,
                distance_km=round(dist_km, 3),
                base_dwell_sec=base_dwell,
                friction_delay_sec=friction_delay,
                traffic_delay_sec=int(travel_time_sec * (traffic_lapse - 1.0)),
                total_delay_sec=int(total_delay),
                eta_iso=eta_iso,
                delay_band=delay_band,
            ))

        # Collect delay causes from context
        delay_causes = self._collect_delay_causes(bus, pothole_friction, risk_zone_friction)

        # Overall delay summary
        if etas:
            band_rank = {b: i for i, b in enumerate(DELAY_STATE_ORDER)}
            max_band = max(etas, key=lambda e: band_rank.get(e.delay_band, 0))
            delay_summary = max_band.delay_band
        else:
            delay_summary = "ON_TIME"

        # Destination ETA (last stop)
        destination_eta = etas[-1].eta_iso if etas else utcnow_iso()

        # Source honesty
        source = "SIMULATION" if bus.get("simulation") or bus.get("data_source") == "simulation" else "HEURISTIC"
        if bus.get("_live"):
            source = "LIVE"

        result = BusETAResult(
            bus_id=bus.get("bus_id", ""),
            route=bus.get("route", ""),
            current_stop=current_stop.get("stop", "en route"),
            destination=destination.get("stop", "unknown"),
            etas=etas,
            delay_summary=delay_summary,
            delay_causes=delay_causes,
            total_remaining_distance_km=round(cum_distance_km, 3),
            total_remaining_time_sec=round(cum_time_sec, 1),
            eta_destination_iso=destination_eta,
            source=source,
            simulation=bus.get("simulation", True),
            computed_at=utcnow_iso(),
        )

        return result.to_dict()

    def _collect_delay_causes(self, bus: dict, pothole_friction: int,
                               risk_zone_friction: int) -> List[DelayCause]:
        """Collect contextual delay causes from existing subsystems.

        These are evidence-based observations, NOT causal claims.
        """
        causes = []

        # Road intelligence context
        if risk_zone_friction > 0:
            causes.append(DelayCause(
                category="road",
                description=f"Bus operating through high-risk road segment ({risk_zone_friction} zone(s) on route)",
                severity="WARNING",
                source="HEURISTIC",
            ))
        if pothole_friction > 0:
            causes.append(DelayCause(
                category="road",
                description=f"Active road defect(s) detected on route ({pothole_friction} segment(s))",
                severity="INFO",
                source="HEURISTIC",
            ))

        # Vehicle health context
        vehicle = bus.get("vehicle", {})
        health = (vehicle.get("health") or "NORMAL").upper()
        if health == "WARNING":
            causes.append(DelayCause(
                category="vehicle",
                description=f"Vehicle warning active: {vehicle.get('anomaly') or 'anomaly'}",
                severity="WARNING",
                source="SIMULATION" if bus.get("simulation") else "HEURISTIC",
            ))
        elif health not in ("NORMAL", ""):
            causes.append(DelayCause(
                category="vehicle",
                description=f"Vehicle health issue: {health}",
                severity="CRITICAL",
                source="SIMULATION" if bus.get("simulation") else "HEURISTIC",
            ))

        vibration = float(vehicle.get("vibration", 0))
        if vibration > 0.6:
            causes.append(DelayCause(
                category="vehicle",
                description=f"Elevated vibration ({vibration:.2f}) may affect travel",
                severity="INFO",
                source="SIMULATION" if bus.get("simulation") else "HEURISTIC",
            ))

        # Driver context
        driver = bus.get("driver", {})
        state = (driver.get("state") or "NORMAL").upper()
        if state in ("ATTENTION", "DROWSY"):
            causes.append(DelayCause(
                category="driver",
                description=f"Driver {state.lower()} — reduced speed may be warranted",
                severity="WARNING" if state == "ATTENTION" else "CRITICAL",
                source="SIMULATION" if bus.get("simulation") else "HEURISTIC",
            ))

        # Occupancy context
        occ_pct = float((bus.get("occupancy") or {}).get("pct", 0))
        if occ_pct >= 85:
            causes.append(DelayCause(
                category="occupancy",
                description=f"High occupancy ({occ_pct:.0f}%) increases dwell time",
                severity="INFO",
                source="SIMULATION" if bus.get("simulation") else "HEURISTIC",
            ))

        # Speed context
        speed = float(bus.get("speed_kmh", 25))
        if speed < 8:
            causes.append(DelayCause(
                category="traffic",
                description=f"Low speed ({speed:.0f} km/h) — possible congestion or stop",
                severity="INFO",
                source="HEURISTIC",
            ))

        return causes

    def _get_route_pothole_friction(self, route_code: str, stops: list,
                                     current_idx: int, next_idx: int) -> int:
        """Count active road defects along this bus's remaining route.

        Returns the number of segments with active defects (route-specific,
        NOT global like the previous implementation).
        """
        defects = store.get_road_defects()
        active_defects = [d for d in defects if d.get("status") == "ACTIVE"]
        if not active_defects:
            return 0

        # Check if any active defect is near the bus's remaining route
        count = 0
        for defect in active_defects:
            d_lat = defect.get("latitude", 0)
            d_lon = defect.get("longitude", 0)
            if d_lat is None or d_lon is None:
                continue
            # Check proximity to any remaining stop
            for i in range(next_idx, len(stops)):
                stop = stops[i]
                dist = self._haversine_km(d_lat, d_lon, stop["lat"], stop["lon"])
                if dist <= 0.5:  # within 500m of a remaining stop
                    count += 1
                    break
        return count

    def _get_risk_zone_friction(self, route_code: str) -> int:
        """Count risk zones that affect this bus's route.

        Uses the road_risk engine's route risk index for route-specific data.
        """
        try:
            from road_risk import road_risk_engine
            with road_risk_engine._lock:
                zones = list(road_risk_engine.zones.values())
            count = 0
            for z in zones:
                if route_code in z.routes_affected and z.risk_level in ("HIGH", "CRITICAL"):
                    count += 1
            return count
        except Exception:
            return 0

    def _haversine_km(self, lat1, lon1, lat2, lon2):
        from math import radians, sin, cos, sqrt, asin
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return 2 * R * asin(sqrt(a))

    def _empty_result(self, bus: dict, delay_summary: str) -> dict:
        """Return an empty ETA result for buses without route data."""
        return {
            "bus_id": bus.get("bus_id", ""),
            "route": bus.get("route", ""),
            "current_stop": "unknown",
            "destination": "unknown",
            "etas": [],
            "delay_summary": delay_summary,
            "delay_causes": [],
            "total_remaining_distance_km": 0,
            "total_remaining_time_sec": 0,
            "eta_destination": utcnow_iso(),
            "source": "UNKNOWN",
            "simulation": bus.get("simulation", True),
            "computed_at": utcnow_iso(),
        }

    def detect_delay_change(self, bus_id: str, new_state: str) -> Optional[str]:
        """Detect if delay state changed significantly. Returns the change
        description or None if no meaningful change."""
        prev = self._prev_delay_states.get(bus_id)
        self._prev_delay_states[bus_id] = new_state
        if prev is None or prev == new_state:
            return None
        # Significant changes: recovery or worsening
        prev_rank = DELAY_STATE_ORDER.index(prev) if prev in DELAY_STATE_ORDER else 0
        new_rank = DELAY_STATE_ORDER.index(new_state) if new_state in DELAY_STATE_ORDER else 0
        if abs(new_rank - prev_rank) >= 2:
            if new_rank > prev_rank:
                return f"Delay worsened: {prev} → {new_state}"
            else:
                return f"Delay recovered: {prev} → {new_state}"
        return None

    def get_fleet_eta_summary(self, buses: list) -> dict:
        """Compute fleet-level ETA KPI for the dashboard."""
        rng = random.Random(42)  # deterministic for fleet summary
        all_etas = compute_all_etas(buses, rng)

        total = len(all_etas)
        delay_counts = {"ON_TIME": 0, "EARLY": 0, "MINOR_DELAY": 0,
                        "SIGNIFICANT_DELAY": 0, "SEVERE_DELAY": 0, "NO_ROUTE": 0}
        severe_buses = []
        delayed_buses = []

        for bus_id, eta_result in all_etas.items():
            state = eta_result.get("delay_summary", "UNKNOWN")
            delay_counts[state] = delay_counts.get(state, 0) + 1

            if state == "SEVERE_DELAY":
                severe_buses.append(bus_id)
            elif state in ("SIGNIFICANT_DELAY", "SEVERE_DELAY"):
                delayed_buses.append(bus_id)

        on_time_pct = round(100 * delay_counts.get("ON_TIME", 0) / max(1, total), 1)
        delayed_pct = round(100 * (delay_counts.get("SIGNIFICANT_DELAY", 0) +
                                    delay_counts.get("SEVERE_DELAY", 0)) / max(1, total), 1)

        return {
            "total_buses": total,
            "delay_distribution": delay_counts,
            "on_time_percentage": on_time_pct,
            "delayed_percentage": delayed_pct,
            "severe_delay_buses": severe_buses,
            "delayed_buses": delayed_buses,
            "source": "HEURISTIC",
            "note": "ETA computed from dwell model + traffic heuristic. No ML models.",
        }


eta_engine = ETAEngine()


def compute_all_etas(buses: list, rng: random.Random) -> Dict[str, dict]:
    """Compute ETA for all buses (skips live buses)."""
    result = {}
    for bus in buses:
        if bus.get("_live"):
            continue
        result[bus["bus_id"]] = eta_engine.compute_eta(bus, rng)
    return result


def get_fleet_eta_summary(buses: list) -> dict:
    """Fleet-level ETA KPI for the dashboard."""
    return eta_engine.get_fleet_eta_summary(buses)


if __name__ == "__main__":
    import json
    buses = store.get_buses()
    rng = random.Random(42)
    for bus in buses[:3]:
        print(json.dumps(eta_engine.compute_eta(bus, rng), indent=2))
