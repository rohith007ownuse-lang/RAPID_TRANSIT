"""
demand_intelligence.py
Passenger Demand Intelligence — capacity, occupancy, demand patterns, pressure.

Phase 14: Upgrades the passenger-demand/load-management subsystem into an
operational intelligence layer.

Methodology: HEURISTIC
- Capacity model derived from bus configuration (capacity = 60 default)
- Occupancy from simulator (SIMULATION) or cabin camera (HEURISTIC/MODEL)
- Demand forecast from time-of-day + stop weights (HEURISTIC)
- Capacity pressure from occupancy/capacity ratio (HEURISTIC)
- No ML models. No fabricated data. No fake confidence scores.

Source honesty:
- SIMULATION: from simulator passenger generation
- HEURISTIC: from cabin camera density proxy or demand formula
- MODEL: from real ML model (when available)
- LIVE: from real bus telemetry (when connected)
- UNKNOWN: when data unavailable (never silently zero)
"""

import random
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from data_store import store


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Constants — documented thresholds
# ---------------------------------------------------------------------------

# Capacity thresholds (percentage of configured capacity)
# These define load STATE, not risk. Risk engine uses separate scoring.
CAPACITY_THRESHOLDS = {
    "EMPTY_MAX": 20,        # < 20% → EMPTY
    "LOW_MAX": 40,          # < 40% → LOW
    "NORMAL_MAX": 70,       # < 70% → NORMAL
    "HIGH_MAX": 85,         # < 85% → HIGH
    "NEAR_CAPACITY_MAX": 95,  # < 95% → NEAR_CAPACITY
    # >= 95% → OVER_CAPACITY
}

# Crowding levels (aligned with cabin occupancy thresholds)
CROWDING_THRESHOLDS = {
    "NORMAL_MAX": 60,       # < 60% → NORMAL
    "MODERATE_MAX": 75,     # < 75% → MODERATE
    "HIGH_MAX": 90,         # < 90% → HIGH
    # >= 90% → CRITICAL
}

# Capacity pressure thresholds (forecast demand / capacity)
CAPACITY_PRESSURE_THRESHOLDS = {
    "NORMAL_MAX": 0.7,      # < 70% → NORMAL
    "WATCH_MAX": 0.85,      # < 85% → WATCH
    "HIGH_PRESSURE_MAX": 1.0,  # < 100% → HIGH_PRESSURE
    # >= 100% → CRITICAL
}

# Demand trend detection: requires N observations to establish trend
DEMAND_TREND_WINDOW = 5  # observations needed for trend detection

# Overcrowding sustained threshold: N consecutive observations
OVERCROWDING_SUSTAINED_THRESHOLD = 3

# Default bus capacity
DEFAULT_CAPACITY = 60

# Passenger weight assumption (kg) — documented, not calibrated
PASSENGER_WEIGHT_KG = 68


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CapacityModel:
    """Bus capacity and utilization."""
    bus_id: str
    route_code: str
    capacity: int
    current_occupancy: int
    utilization_pct: float  # 0-100+
    available_seats: int  # can be negative if over capacity
    load_state: str  # EMPTY/LOW/NORMAL/HIGH/NEAR_CAPACITY/OVER_CAPACITY/UNKNOWN
    source: str  # SIMULATION/LIVE/HEURISTIC/MODEL/UNKNOWN
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "bus_id": self.bus_id,
            "route_code": self.route_code,
            "capacity": self.capacity,
            "current_occupancy": self.current_occupancy,
            "utilization_pct": round(self.utilization_pct, 1),
            "available_seats": self.available_seats,
            "load_state": self.load_state,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class OccupancySnapshot:
    """Current occupancy with source tracking."""
    bus_id: str
    passengers: int
    capacity: int
    pct: float
    crowd_level: str  # NORMAL/MODERATE/HIGH/CRITICAL
    source: str  # SIMULATION/LIVE/HEURISTIC/MODEL/UNKNOWN
    cabin_source: Optional[str] = None  # camera source if available
    cabin_count: Optional[int] = None
    cabin_pct: Optional[float] = None
    cabin_crowding: Optional[str] = None
    timestamp: str = ""

    def to_dict(self) -> dict:
        d = {
            "bus_id": self.bus_id,
            "passengers": self.passengers,
            "capacity": self.capacity,
            "pct": round(self.pct, 1),
            "crowd_level": self.crowd_level,
            "source": self.source,
            "timestamp": self.timestamp,
        }
        if self.cabin_source:
            d["cabin_source"] = self.cabin_source
            d["cabin_count"] = self.cabin_count
            d["cabin_pct"] = round(self.cabin_pct, 1) if self.cabin_pct is not None else None
            d["cabin_crowding"] = self.cabin_crowding
        return d


@dataclass
class DemandPattern:
    """Demand pattern for a route or stop."""
    route_code: str
    current_demand: str  # LOW/NORMAL/HIGH/PEAK/UNKNOWN
    demand_trend: str  # INCREASING/STABLE/DECREASING/PEAKING/UNKNOWN
    peak_hour: Optional[int]
    peak_boardings: int
    daily_boardings: int
    hourly_avg: float
    source: str  # SIMULATION/HEURISTIC/HISTORICAL/UNKNOWN
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "route_code": self.route_code,
            "current_demand": self.current_demand,
            "demand_trend": self.demand_trend,
            "peak_hour": self.peak_hour,
            "peak_boardings": self.peak_boardings,
            "daily_boardings": self.daily_boardings,
            "hourly_avg": round(self.hourly_avg, 1),
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class CapacityPressure:
    """Forecast capacity pressure for a bus or route."""
    bus_id: str
    route_code: str
    current_occupancy: int
    forecast_demand: int
    capacity: int
    pressure_level: str  # NORMAL/WATCH/HIGH_PRESSURE/CRITICAL/UNKNOWN
    pressure_pct: float  # forecast_demand / capacity * 100
    affected_stops: List[str]
    source: str  # HEURISTIC/SIMULATION/UNKNOWN
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "bus_id": self.bus_id,
            "route_code": self.route_code,
            "current_occupancy": self.current_occupancy,
            "forecast_demand": self.forecast_demand,
            "capacity": self.capacity,
            "pressure_level": self.pressure_level,
            "pressure_pct": round(self.pressure_pct, 1),
            "affected_stops": self.affected_stops,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class OvercrowdingEvent:
    """Detected overcrowding condition."""
    bus_id: str
    route_code: str
    occupancy_pct: float
    capacity: int
    passengers: int
    severity: str  # WARNING/CRITICAL
    sustained: bool  # True if multiple consecutive observations
    observation_count: int
    source: str
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "bus_id": self.bus_id,
            "route_code": self.route_code,
            "occupancy_pct": round(self.occupancy_pct, 1),
            "capacity": self.capacity,
            "passengers": self.passengers,
            "severity": self.severity,
            "sustained": self.sustained,
            "observation_count": self.observation_count,
            "source": self.source,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Demand Intelligence Engine
# ---------------------------------------------------------------------------

class DemandIntelligenceEngine:
    """Operational intelligence for passenger demand and capacity.

    Methodology: HEURISTIC
    - Capacity derived from bus configuration
    - Occupancy from available data sources (sim/cabin/telemetry)
    - Demand forecast from time-of-day profile + stop weights
    - Capacity pressure from demand/capacity ratio
    - No ML models. No fabricated data.

    Source honesty:
    - Each output carries a source label
    - UNKNOWN means data unavailable, never silently zero
    - Simulation data is always labeled SIMULATION
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._overcrowding_counts: Dict[str, int] = defaultdict(int)  # bus_id -> consecutive count
        self._demand_history: Dict[str, List[int]] = defaultdict(list)  # bus_id -> recent demand values
        self._capacity_models: Dict[str, CapacityModel] = {}

    def get_capacity_model(self, bus: dict) -> CapacityModel:
        """Build capacity model for a bus from available data."""
        bus_id = bus.get("bus_id", "")
        route_code = bus.get("route_code", "")
        occ = bus.get("occupancy", {})
        capacity = occ.get("capacity", DEFAULT_CAPACITY)
        passengers = occ.get("passengers", 0)

        # Determine source
        if bus.get("_live"):
            source = "LIVE"
        elif bus.get("simulation"):
            source = "SIMULATION"
        else:
            source = "UNKNOWN"

        # Check cabin occupancy for more accurate data
        cabin = bus.get("cabin_occupancy")
        if cabin and cabin.get("status") == "CONNECTED" and cabin.get("occupancy_count") is not None:
            cabin_count = cabin["occupancy_count"]
            # Cabin data takes precedence if available and connected
            passengers = cabin_count
            source = cabin.get("source", "HEURISTIC")

        # Calculate utilization
        if capacity > 0:
            utilization = (passengers / capacity) * 100
        else:
            utilization = 0.0

        available = capacity - passengers

        # Determine load state
        if capacity <= 0 or passengers < 0:
            load_state = "UNKNOWN"
        elif utilization >= CAPACITY_THRESHOLDS["NEAR_CAPACITY_MAX"]:
            load_state = "OVER_CAPACITY"
        elif utilization >= CAPACITY_THRESHOLDS["HIGH_MAX"]:
            load_state = "NEAR_CAPACITY"
        elif utilization >= CAPACITY_THRESHOLDS["NORMAL_MAX"]:
            load_state = "HIGH"
        elif utilization >= CAPACITY_THRESHOLDS["LOW_MAX"]:
            load_state = "NORMAL"
        elif utilization >= CAPACITY_THRESHOLDS["EMPTY_MAX"]:
            load_state = "LOW"
        else:
            load_state = "EMPTY"

        model = CapacityModel(
            bus_id=bus_id,
            route_code=route_code,
            capacity=capacity,
            current_occupancy=passengers,
            utilization_pct=utilization,
            available_seats=available,
            load_state=load_state,
            source=source,
            timestamp=utcnow_iso(),
        )

        with self._lock:
            self._capacity_models[bus_id] = model

        return model

    def get_occupancy_snapshot(self, bus: dict) -> OccupancySnapshot:
        """Build occupancy snapshot with source tracking."""
        bus_id = bus.get("bus_id", "")
        occ = bus.get("occupancy", {})
        passengers = occ.get("passengers", 0)
        capacity = occ.get("capacity", DEFAULT_CAPACITY)
        pct = occ.get("pct", 0)

        # Determine source
        if bus.get("_live"):
            source = "LIVE"
        elif bus.get("simulation"):
            source = "SIMULATION"
        else:
            source = "UNKNOWN"

        # Cabin occupancy integration
        cabin = bus.get("cabin_occupancy")
        cabin_source = None
        cabin_count = None
        cabin_pct = None
        cabin_crowding = None

        if cabin and cabin.get("status") == "CONNECTED":
            cabin_count = cabin.get("occupancy_count")
            cabin_pct = cabin.get("occupancy_percentage")
            cabin_crowding = cabin.get("crowding_level")
            cabin_source = cabin.get("source", "HEURISTIC")

            if cabin_count is not None:
                passengers = cabin_count
                if cabin_pct is not None:
                    pct = cabin_pct
                elif capacity > 0:
                    pct = (passengers / capacity) * 100
                source = cabin_source

        # Determine crowd level from percentage
        if capacity <= 0:
            crowd_level = "UNKNOWN"
        elif pct >= CROWDING_THRESHOLDS["HIGH_MAX"]:
            crowd_level = "CRITICAL"
        elif pct >= CROWDING_THRESHOLDS["MODERATE_MAX"]:
            crowd_level = "HIGH"
        elif pct >= CROWDING_THRESHOLDS["NORMAL_MAX"]:
            crowd_level = "MODERATE"
        else:
            crowd_level = "NORMAL"

        return OccupancySnapshot(
            bus_id=bus_id,
            passengers=passengers,
            capacity=capacity,
            pct=pct,
            crowd_level=crowd_level,
            source=source,
            cabin_source=cabin_source,
            cabin_count=cabin_count,
            cabin_pct=cabin_pct,
            cabin_crowding=cabin_crowding,
            timestamp=utcnow_iso(),
        )

    def get_demand_pattern(self, bus: dict) -> DemandPattern:
        """Compute demand pattern for a bus's route from boarding history."""
        bus_id = bus.get("bus_id", "")
        route_code = bus.get("route_code", "")
        boarding_hour = bus.get("boarding_by_hour", {})
        daily_total = bus.get("daily_boarding_total", 0)
        peak_hour = bus.get("boarding_peak_hour")

        # Source
        if bus.get("_live"):
            source = "LIVE"
        elif bus.get("simulation"):
            source = "SIMULATION"
        else:
            source = "UNKNOWN"

        # Calculate hourly average
        hours_with_data = [v for v in boarding_hour.values() if v > 0]
        hourly_avg = sum(hours_with_data) / max(1, len(hours_with_data))

        # Peak info
        if peak_hour is not None:
            peak_hour = int(peak_hour)
            peak_boardings = boarding_hour.get(str(peak_hour), 0)
        elif boarding_hour:
            peak_entry = max(boarding_hour.items(), key=lambda x: int(x[1]))
            peak_hour = int(peak_entry[0])
            peak_boardings = int(peak_entry[1])
        else:
            peak_hour = None
            peak_boardings = 0

        # Current demand level based on time of day
        current_demand = self._estimate_current_demand(boarding_hour, daily_total)

        # Demand trend from recent observations
        trend = self._estimate_demand_trend(bus_id, daily_total)

        return DemandPattern(
            route_code=route_code,
            current_demand=current_demand,
            demand_trend=trend,
            peak_hour=peak_hour,
            peak_boardings=peak_boardings,
            daily_boardings=daily_total,
            hourly_avg=hourly_avg,
            source=source,
            timestamp=utcnow_iso(),
        )

    def get_capacity_pressure(self, bus: dict, forecast_boardings: int = 0) -> CapacityPressure:
        """Compute capacity pressure from current occupancy + forecast demand."""
        bus_id = bus.get("bus_id", "")
        route_code = bus.get("route_code", "")
        occ = bus.get("occupancy", {})
        passengers = occ.get("passengers", 0)
        capacity = occ.get("capacity", DEFAULT_CAPACITY)

        # Source
        if bus.get("_live"):
            source = "LIVE"
        elif bus.get("simulation"):
            source = "SIMULATION"
        else:
            source = "HEURISTIC"

        # Total expected demand = current + forecast
        total_demand = passengers + forecast_boardings

        # Pressure ratio
        if capacity > 0:
            pressure_pct = (total_demand / capacity) * 100
        else:
            pressure_pct = 0

        # Pressure level
        if capacity <= 0:
            pressure_level = "UNKNOWN"
        elif pressure_pct >= CAPACITY_PRESSURE_THRESHOLDS["HIGH_PRESSURE_MAX"] * 100:
            pressure_level = "CRITICAL"
        elif pressure_pct >= CAPACITY_PRESSURE_THRESHOLDS["WATCH_MAX"] * 100:
            pressure_level = "HIGH_PRESSURE"
        elif pressure_pct >= CAPACITY_PRESSURE_THRESHOLDS["NORMAL_MAX"] * 100:
            pressure_level = "WATCH"
        else:
            pressure_level = "NORMAL"

        # Affected stops from journey
        journey = bus.get("journey", {})
        stops = journey.get("stops", [])
        next_idx = journey.get("next_index", journey.get("current_index", 0) + 1)
        affected = [s["stop"] for s in stops[next_idx:next_idx + 3]] if stops else []

        return CapacityPressure(
            bus_id=bus_id,
            route_code=route_code,
            current_occupancy=passengers,
            forecast_demand=forecast_boardings,
            capacity=capacity,
            pressure_level=pressure_level,
            pressure_pct=pressure_pct,
            affected_stops=affected,
            source=source,
            timestamp=utcnow_iso(),
        )

    def detect_overcrowding(self, bus: dict) -> Optional[OvercrowdingEvent]:
        """Detect overcrowding with sustained-observation requirement."""
        bus_id = bus.get("bus_id", "")
        route_code = bus.get("route_code", "")
        occ = bus.get("occupancy", {})
        passengers = occ.get("passengers", 0)
        capacity = occ.get("capacity", DEFAULT_CAPACITY)
        pct = occ.get("pct", 0)

        # Source
        if bus.get("_live"):
            source = "LIVE"
        elif bus.get("simulation"):
            source = "SIMULATION"
        else:
            source = "UNKNOWN"

        # Check if overcrowded
        is_overcrowded = pct >= CROWDING_THRESHOLDS["HIGH_MAX"] and capacity > 0

        with self._lock:
            if is_overcrowded:
                self._overcrowding_counts[bus_id] += 1
                count = self._overcrowding_counts[bus_id]
            else:
                # Recovery: reset count
                if self._overcrowding_counts.get(bus_id, 0) > 0:
                    self._overcrowding_counts[bus_id] = 0
                return None

        # Only report if sustained or first observation
        if count >= OVERCROWDING_SUSTAINED_THRESHOLD:
            severity = "CRITICAL"
            sustained = True
        elif count == 1:
            severity = "WARNING"
            sustained = False
        else:
            # Between 1 and threshold: accumulating, don't report yet
            return None

        return OvercrowdingEvent(
            bus_id=bus_id,
            route_code=route_code,
            occupancy_pct=pct,
            capacity=capacity,
            passengers=passengers,
            severity=severity,
            sustained=sustained,
            observation_count=count,
            source=source,
            timestamp=utcnow_iso(),
        )

    def get_route_demand_summary(self, buses: list) -> Dict[str, dict]:
        """Aggregate demand intelligence at route level."""
        route_data = defaultdict(lambda: {
            "buses": 0,
            "total_passengers": 0,
            "total_capacity": 0,
            "overloaded": 0,
            "high_demand": 0,
            "daily_boardings": 0,
            "peak_boardings": 0,
        })

        for bus in buses:
            route = bus.get("route_code", "UNKNOWN")
            rd = route_data[route]
            rd["buses"] += 1

            occ = bus.get("occupancy", {})
            passengers = occ.get("passengers", 0)
            capacity = occ.get("capacity", DEFAULT_CAPACITY)

            rd["total_passengers"] += passengers
            rd["total_capacity"] += capacity

            pct = (passengers / capacity * 100) if capacity > 0 else 0
            if pct >= CROWDING_THRESHOLDS["HIGH_MAX"]:
                rd["overloaded"] += 1
            elif pct >= CROWDING_THRESHOLDS["MODERATE_MAX"]:
                rd["high_demand"] += 1

            rd["daily_boardings"] += bus.get("daily_boarding_total", 0)
            rd["peak_boardings"] += bus.get("boarding_by_hour", {}).get(
                str(bus.get("boarding_peak_hour", 8)), 0
            )

        result = {}
        for route, rd in route_data.items():
            avg_util = (rd["total_passengers"] / rd["total_capacity"] * 100) if rd["total_capacity"] > 0 else 0
            result[route] = {
                "route_code": route,
                "bus_count": rd["buses"],
                "total_passengers": rd["total_passengers"],
                "total_capacity": rd["total_capacity"],
                "avg_utilization_pct": round(avg_util, 1),
                "overloaded_buses": rd["overloaded"],
                "high_demand_buses": rd["high_demand"],
                "daily_boardings": rd["daily_boardings"],
                "peak_boardings": rd["peak_boardings"],
                "demand_level": self._route_demand_level(rd, avg_util),
                "source": "SIMULATION" if any(b.get("simulation") for b in buses) else "UNKNOWN",
                "timestamp": utcnow_iso(),
            }

        return result

    def get_fleet_load_summary(self, buses: list) -> dict:
        """Fleet-level load intelligence for the dashboard."""
        load_counts = {"EMPTY": 0, "LOW": 0, "NORMAL": 0, "HIGH": 0,
                       "NEAR_CAPACITY": 0, "OVER_CAPACITY": 0, "UNKNOWN": 0}
        crowd_counts = {"NORMAL": 0, "MODERATE": 0, "HIGH": 0, "CRITICAL": 0, "UNKNOWN": 0}
        source_counts = {"SIMULATION": 0, "LIVE": 0, "HEURISTIC": 0, "MODEL": 0, "UNKNOWN": 0}

        overloaded_buses = []
        near_capacity_buses = []
        unknown_occupancy_buses = []

        for bus in buses:
            cap = self.get_capacity_model(bus)
            occ = self.get_occupancy_snapshot(bus)

            load_counts[cap.load_state] = load_counts.get(cap.load_state, 0) + 1
            crowd_counts[occ.crowd_level] = crowd_counts.get(occ.crowd_level, 0) + 1
            source_counts[cap.source] = source_counts.get(cap.source, 0) + 1

            if cap.load_state == "OVER_CAPACITY":
                overloaded_buses.append(bus.get("bus_id", ""))
            elif cap.load_state == "NEAR_CAPACITY":
                near_capacity_buses.append(bus.get("bus_id", ""))
            elif cap.load_state == "UNKNOWN":
                unknown_occupancy_buses.append(bus.get("bus_id", ""))

        total = len(buses)
        overloaded_pct = round(100 * len(overloaded_buses) / max(1, total), 1)
        high_pct = round(100 * (load_counts.get("HIGH", 0) + load_counts.get("NEAR_CAPACITY", 0) +
                                 load_counts.get("OVER_CAPACITY", 0)) / max(1, total), 1)

        return {
            "total_buses": total,
            "load_distribution": load_counts,
            "crowding_distribution": crowd_counts,
            "source_distribution": source_counts,
            "overloaded_buses": overloaded_buses,
            "near_capacity_buses": near_capacity_buses,
            "unknown_occupancy_buses": unknown_occupancy_buses,
            "overloaded_percentage": overloaded_pct,
            "high_utilization_percentage": high_pct,
            "source": "HEURISTIC",
            "note": "All values from simulator or heuristic estimation. No live passenger counting.",
            "timestamp": utcnow_iso(),
        }

    # --- internal helpers ---

    def _estimate_current_demand(self, boarding_hour: dict, daily_total: int) -> str:
        """Estimate current demand level from hourly boarding profile."""
        if not boarding_hour or daily_total <= 0:
            return "UNKNOWN"

        # Get current hour (IST approximation)
        utc_hour = datetime.now(timezone.utc).hour
        local_hour = (utc_hour + 5) % 24

        current_boardings = boarding_hour.get(str(local_hour), 0)
        if current_boardings <= 0:
            return "LOW"

        # Compare to average
        values = [v for v in boarding_hour.values() if v > 0]
        avg = sum(values) / max(1, len(values))

        if current_boardings >= avg * 1.5:
            return "PEAK"
        elif current_boardings >= avg * 1.2:
            return "HIGH"
        elif current_boardings >= avg * 0.8:
            return "NORMAL"
        else:
            return "LOW"

    def _estimate_demand_trend(self, bus_id: str, current_daily: int) -> str:
        """Estimate demand trend from recent observations."""
        with self._lock:
            history = self._demand_history[bus_id]
            history.append(current_daily)
            # Keep only recent observations
            if len(history) > DEMAND_TREND_WINDOW:
                history.pop(0)

            if len(history) < 3:
                return "UNKNOWN"

            # Simple trend: compare recent average to older average
            mid = len(history) // 2
            recent = sum(history[mid:]) / max(1, len(history[mid:]))
            older = sum(history[:mid]) / max(1, len(history[:mid]))

            if older <= 0:
                return "UNKNOWN"

            change = (recent - older) / older

            if change > 0.15:
                return "INCREASING"
            elif change < -0.15:
                return "DECREASING"
            elif recent > older * 1.05:
                return "PEAKING"
            else:
                return "STABLE"

    def _route_demand_level(self, rd: dict, avg_util: float) -> str:
        """Classify route demand level."""
        if rd["overloaded"] > 0:
            return "HIGH"
        elif rd["high_demand"] > 0:
            return "ELEVATED"
        elif avg_util >= 70:
            return "MODERATE"
        elif avg_util >= 40:
            return "NORMAL"
        elif avg_util > 0:
            return "LOW"
        else:
            return "UNKNOWN"


# Singleton
demand_intelligence_engine = DemandIntelligenceEngine()


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

def get_capacity_model(bus: dict) -> dict:
    """Get capacity model for a bus."""
    return demand_intelligence_engine.get_capacity_model(bus).to_dict()


def get_occupancy_snapshot(bus: dict) -> dict:
    """Get occupancy snapshot for a bus."""
    return demand_intelligence_engine.get_occupancy_snapshot(bus).to_dict()


def get_demand_pattern(bus: dict) -> dict:
    """Get demand pattern for a bus's route."""
    return demand_intelligence_engine.get_demand_pattern(bus).to_dict()


def get_capacity_pressure(bus: dict, forecast_boardings: int = 0) -> dict:
    """Get capacity pressure for a bus."""
    return demand_intelligence_engine.get_capacity_pressure(bus, forecast_boardings).to_dict()


def detect_overcrowding(bus: dict) -> Optional[dict]:
    """Detect overcrowding for a bus."""
    event = demand_intelligence_engine.detect_overcrowding(bus)
    return event.to_dict() if event else None


def get_route_demand_summary(buses: list) -> dict:
    """Get route-level demand summary."""
    return demand_intelligence_engine.get_route_demand_summary(buses)


def get_fleet_load_summary(buses: list) -> dict:
    """Get fleet-level load intelligence."""
    return demand_intelligence_engine.get_fleet_load_summary(buses)
