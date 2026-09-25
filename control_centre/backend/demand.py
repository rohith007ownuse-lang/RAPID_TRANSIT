"""
demand.py
Demand / Boarding Forecasting — upcoming-stop demand from time-of-day +
weekday profile and known road friction.

Forecasts per-stop boardings for the next N stops so dispatch can pre-position
buses. Supplements (not replaces) the existing boarding-by-hour analytics.

Phase 14 enhancements:
- Source labels (SIMULATION/HEURISTIC/UNKNOWN)
- Road friction integration (from road_risk zones)
- Honest confidence reporting (no synthetic random)
- Documented thresholds and limitations

Methodology: HEURISTIC — time-of-day profile * stop weight * friction.
No ML models. No fabricated schedules. No fake confidence scores.
"""

import random
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from data_store import store


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Constants (shared with simulator, documented)
# ---------------------------------------------------------------------------

# Hourly demand profile (IST approximation, same as simulator HOURLY_DEMAND)
# Service day runs 5 AM → 11 PM per the MTC operating spec.
HOURLY_DEMAND = {
    5: 0.5, 6: 1.0, 7: 2.2, 8: 2.6, 9: 1.9, 10: 1.2, 11: 1.0,
    12: 0.9, 13: 0.8, 14: 0.55, 15: 0.7, 16: 1.1, 17: 1.9, 18: 2.3,
    19: 1.6, 20: 1.0, 21: 0.6, 22: 0.3, 23: 0.15,
}

# Stop weight by type (major terminals attract more boardings)
STOP_WEIGHT = {"major": 7, "normal": 1}

# Maximum boardings per stop (documented constraint)
MAX_BOARDINGS_PER_STOP = 20


@dataclass
class StopDemandForecast:
    """Forecast for a single stop."""
    stop: str
    lat: float
    lon: float
    is_major: bool
    forecast_boardings: int
    base_boardings: int
    friction_factor: float
    time_factor: float
    confidence: Optional[float]  # None = insufficient data, not synthetic random
    source: str  # SIMULATION/HEURISTIC/UNKNOWN

    def to_dict(self) -> dict:
        return {
            "stop": self.stop,
            "lat": self.lat,
            "lon": self.lon,
            "is_major": self.is_major,
            "forecast_boardings": self.forecast_boardings,
            "base_boardings": self.base_boardings,
            "friction_factor": self.friction_factor,
            "time_factor": self.time_factor,
            "confidence": self.confidence,
            "source": self.source,
        }


class DemandEngine:
    """Computes boarding demand forecasts for buses on their routes.

    Methodology: HEURISTIC
    - Hourly demand factor from IST time-of-day profile
    - Stop weight by type (major vs normal)
    - Road friction from active defects on route
    - Confidence: None (insufficient data to compute genuine confidence)

    No ML models. No fabricated confidence. No fake accuracy claims.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def _get_hour_factor(self) -> float:
        """Current hour demand factor (0-1 normalized to peak)."""
        hour = datetime.now(timezone.utc).hour
        # Approximate IST (UTC+5:30) — documented rough approximation
        local_hour = (hour + 5) % 24
        return HOURLY_DEMAND.get(local_hour, 0.5)

    def _get_friction_factor(self, bus: dict, stops: list, next_idx: int) -> float:
        """Combined demand friction from road conditions.

        Integrates road risk intelligence:
        - Active defects (potholes, roadworks) near remaining stops reduce demand
        - Returns multiplier: 1.0 = no friction, < 1.0 = reduced demand

        Source: HEURISTIC (road defect proximity check)
        """
        try:
            from road_risk import road_risk_engine
            with road_risk_engine._lock:
                zones = list(road_risk_engine.zones.values())
        except Exception:
            return 1.0

        # Check remaining stops for road risk zones
        friction = 1.0
        remaining = stops[next_idx:next_idx + 5]
        for zone in zones:
            if zone.risk_level in ("HIGH", "CRITICAL"):
                # Check if any remaining stop is in this zone
                for stop in remaining:
                    dist = self._haversine_km(
                        zone.center_lat, zone.center_lon,
                        stop["lat"], stop["lon"]
                    )
                    if dist <= zone.radius_km:
                        # Reduce demand factor for affected stops
                        if zone.risk_level == "CRITICAL":
                            friction = min(friction, 0.7)
                        else:
                            friction = min(friction, 0.85)
                        break

        return friction

    def _haversine_km(self, lat1, lon1, lat2, lon2):
        from math import radians, sin, cos, sqrt, asin
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return 2 * R * asin(sqrt(a))

    def forecast_bus(self, bus: dict, rng: random.Random, num_stops: int = 5) -> List[StopDemandForecast]:
        """Forecast demand for the next N stops on this bus's route."""
        journey = bus.get("journey", {})
        if not journey or "stops" not in journey:
            return []

        stops = journey["stops"]
        if not stops:
            return []
        current_idx = journey.get("current_index", 0)
        next_idx = journey.get("next_index", current_idx + 1)
        if next_idx is None:
            next_idx = current_idx + 1

        # Source
        if bus.get("_live"):
            source = "LIVE"
        elif bus.get("simulation"):
            source = "SIMULATION"
        else:
            source = "UNKNOWN"

        hour_factor = self._get_hour_factor()
        friction = self._get_friction_factor(bus, stops, next_idx)

        # Bus-specific daily total (from simulator boarding profile)
        daily_total = bus.get("daily_boarding_total", 600)
        if daily_total <= 0:
            return []

        # Distribute across remaining stops proportional to stop weight
        remaining = stops[next_idx:next_idx + num_stops]
        if not remaining:
            return []

        weights = [STOP_WEIGHT["major"] if s.get("major") else STOP_WEIGHT["normal"] for s in remaining]
        total_weight = sum(weights)

        forecasts = []
        for i, stop in enumerate(remaining):
            # Base proportion of daily total for this stop
            base = daily_total * (weights[i] / total_weight) * hour_factor
            # Apply friction
            forecast = round(base * friction)
            forecast = max(0, min(MAX_BOARDINGS_PER_STOP, forecast))

            forecasts.append(StopDemandForecast(
                stop=stop["stop"],
                lat=stop["lat"],
                lon=stop["lon"],
                is_major=stop.get("major", False),
                forecast_boardings=forecast,
                base_boardings=round(base),
                friction_factor=round(friction, 2),
                time_factor=round(hour_factor, 2),
                confidence=None,  # No genuine confidence calculation available
                source=source,
            ))
        return forecasts


demand_engine = DemandEngine()


def forecast_all(buses: list, rng: random.Random, num_stops: int = 5) -> Dict[str, List[dict]]:
    """Forecast demand for all buses."""
    result = {}
    for bus in buses:
        if bus.get("_live"):
            continue
        fc = demand_engine.forecast_bus(bus, rng, num_stops)
        result[bus["bus_id"]] = [f.to_dict() for f in fc]
    return result


def forecast_bus(bus_id: str, rng: random.Random, num_stops: int = 5) -> List[dict]:
    """Forecast demand for a single bus."""
    bus = store.get_bus(bus_id)
    if not bus:
        return []
    fc = demand_engine.forecast_bus(bus, rng, num_stops)
    return [f.to_dict() for f in fc]


if __name__ == "__main__":
    import json
    buses = store.get_buses()
    rng = random.Random(42)
    for bus in buses[:3]:
        fc = demand_engine.forecast_bus(bus, rng, 5)
        print(bus["bus_id"], json.dumps([f.to_dict() for f in fc], indent=2))
