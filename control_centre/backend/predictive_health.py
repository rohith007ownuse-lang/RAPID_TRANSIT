"""
predictive_health.py
Predictive Vehicle Health — rolling degradation counters and RUL estimators.

Synthetic counters (tyre wear, vibration drift, harsh braking rate, energy degradation)
are accumulated each tick. Trend/RUL estimators warn early: "tyre #3 expected below
threshold in ~2h". All output is tagged SIMULATION.

Phase 11 enhancements:
- Component health model with proper states
- UNKNOWN handling (null instead of fabricated values)
- Data source honesty (LIVE/SIMULATION/HEURISTIC/MODEL/UNKNOWN)
- Maintenance recommendation engine
- Anomaly detection foundation
"""

import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from enum import Enum

from data_store import store


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HealthState(Enum):
    """Vehicle/component health states."""
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class DataSource(Enum):
    """Data source provenance labels."""
    LIVE = "LIVE"
    SIMULATION = "SIMULATION"
    HEURISTIC = "HEURISTIC"
    MODEL = "MODEL"
    UNKNOWN = "UNKNOWN"


# thresholds for health alerts
THRESHOLDS = {
    "tyre_wear_pct": 80,      # percent of expected life consumed
    "vibration_rms": 0.75,    # vibration threshold (0-1)
    "harsh_braking_rate": 0.15,  # per tick
    "energy_degradation_pct": 15,  # percent capacity loss
}

# Health state thresholds for components
HEALTH_THRESHOLDS = {
    "tyre": {
        "healthy_max": 40,
        "watch_max": 60,
        "warning_max": 80,
    },
    "vibration": {
        "healthy_max": 0.3,
        "watch_max": 0.5,
        "warning_max": 0.75,
    },
    "harsh_braking": {
        "healthy_max": 0.02,
        "watch_max": 0.05,
        "warning_max": 0.10,
    },
    "energy_degradation": {
        "healthy_max": 5,
        "watch_max": 10,
        "warning_max": 15,
    },
}


@dataclass
class ComponentHealth:
    """Rolling health state for a single component."""
    name: str
    component_type: str  # "tyre", "vibration", "harsh_braking", "energy_degradation"
    value: float = 0.0
    trend: float = 0.0  # per tick
    history: List[float] = field(default_factory=list)
    rul_ticks: Optional[int] = None  # remaining useful life in ticks
    data_source: DataSource = DataSource.SIMULATION
    last_update: str = field(default_factory=utcnow_iso)
    anomaly_count: int = 0

    def update(self, increment: float, max_history: int = 200, data_source: DataSource = DataSource.SIMULATION):
        self.value = min(100.0, max(0.0, self.value + increment))
        self.history.append(self.value)
        if len(self.history) > max_history:
            self.history = self.history[-max_history:]
        # simple linear trend
        if len(self.history) >= 10:
            recent = self.history[-10:]
            self.trend = (recent[-1] - recent[0]) / len(recent)
            if self.trend > 0:
                self.rul_ticks = int((100.0 - self.value) / self.trend)
            else:
                self.rul_ticks = None
        else:
            self.rul_ticks = None
        self.data_source = data_source
        self.last_update = utcnow_iso()

    def get_health_state(self) -> HealthState:
        """Determine health state from current value using component-specific thresholds."""
        thresholds = HEALTH_THRESHOLDS.get(self.component_type, {})
        if not thresholds:
            return HealthState.UNKNOWN

        if self.value <= thresholds.get("healthy_max", 40):
            return HealthState.HEALTHY
        elif self.value <= thresholds.get("watch_max", 60):
            return HealthState.WATCH
        elif self.value <= thresholds.get("warning_max", 80):
            return HealthState.WARNING
        else:
            return HealthState.CRITICAL

    def to_dict(self) -> dict:
        state = self.get_health_state()
        return {
            "name": self.name,
            "component_type": self.component_type,
            "value": round(self.value, 1),
            "health_state": state.value,
            "trend_per_tick": round(self.trend, 4),
            "rul_ticks": self.rul_ticks,
            "rul_minutes": round(self.rul_ticks * 1.0 / 60, 1) if self.rul_ticks else None,
            "history": [round(v, 1) for v in self.history[-20:]] if self.history else [],
            "data_source": self.data_source.value,
            "last_update": self.last_update,
            "anomaly_count": self.anomaly_count,
        }


@dataclass
class VehicleHealth:
    """Complete vehicle health snapshot."""
    bus_id: str
    overall_state: HealthState = HealthState.UNKNOWN
    overall_score: float = 0.0
    components: Dict[str, ComponentHealth] = field(default_factory=dict)
    anomalies: List[dict] = field(default_factory=list)
    maintenance_recommendations: List[dict] = field(default_factory=list)
    data_source: DataSource = DataSource.SIMULATION
    last_update: str = field(default_factory=utcnow_iso)
    confidence: Optional[float] = None  # None = unknown/unavailable

    def to_dict(self) -> dict:
        return {
            "bus_id": self.bus_id,
            "overall_state": self.overall_state.value,
            "overall_score": round(self.overall_score, 1),
            "components": {name: comp.to_dict() for name, comp in self.components.items()},
            "anomalies": self.anomalies,
            "maintenance_recommendations": self.maintenance_recommendations,
            "data_source": self.data_source.value,
            "last_update": self.last_update,
            "confidence": self.confidence,
        }


class VehicleHealthTracker:
    """Tracks degradation counters per bus and produces maintenance predictions."""

    def __init__(self):
        self._lock = threading.Lock()
        self.bus_health: Dict[str, Dict[str, ComponentHealth]] = {}
        self._maintenance_history: Dict[str, List[dict]] = {}  # bus_id -> list of recommendations

    def get_or_create(self, bus_id: str, data_source: DataSource = DataSource.SIMULATION) -> Dict[str, ComponentHealth]:
        with self._lock:
            if bus_id not in self.bus_health:
                self.bus_health[bus_id] = {
                    "tyre_fl": ComponentHealth("tyre_fl", "tyre", data_source=data_source),
                    "tyre_fr": ComponentHealth("tyre_fr", "tyre", data_source=data_source),
                    "tyre_rl": ComponentHealth("tyre_rl", "tyre", data_source=data_source),
                    "tyre_rr": ComponentHealth("tyre_rr", "tyre", data_source=data_source),
                    "vibration": ComponentHealth("vibration", "vibration", data_source=data_source),
                    "harsh_braking": ComponentHealth("harsh_braking", "harsh_braking", data_source=data_source),
                    "energy_degradation": ComponentHealth("energy_degradation", "energy_degradation", data_source=data_source),
                }
                self._maintenance_history[bus_id] = []
            return self.bus_health[bus_id]

    def _calculate_component_increments(self, bus: dict, rng: random.Random, data_source: DataSource) -> Dict[str, float]:
        """Calculate degradation increments for each component based on bus telemetry."""
        increments = {}
        bid = bus["bus_id"]

        # Tyre wear: accumulates with distance & low pressure
        wheels = bus.get("wheels", [85, 85, 85, 85])
        tyre_names = ["tyre_fl", "tyre_fr", "tyre_rl", "tyre_rr"]
        for i, name in enumerate(tyre_names):
            psi = float(wheels[i] if i < len(wheels) else 85)
            # low pressure accelerates wear; base wear per tick
            pressure_factor = 1.0 + max(0.0, (85.0 - psi) / 85.0) * 0.5
            increment = rng.uniform(0.03, 0.08) * pressure_factor
            increments[name] = increment

        # Vibration: rises with anomalies, potholes, tyre wear
        v = bus.get("vehicle", {})
        vib_base = float(v.get("vibration", 0.2))
        avg_tyre = sum(float(w) for w in wheels) / len(wheels)
        tyre_imbalance = max(0.0, (85.0 - avg_tyre) / 85.0) * 0.3
        vib_increment = rng.uniform(0.005, 0.02) + tyre_imbalance * 0.01
        if v.get("anomaly") and v.get("anomaly") != "none":
            vib_increment += 0.02
            # Track anomaly
            health = self.get_or_create(bid, data_source)
            health["vibration"].anomaly_count += 1
        increments["vibration"] = vib_increment

        # Harsh braking: occasional hard stops
        if rng.random() < 0.02:
            increments["harsh_braking"] = 1.0
        else:
            # slow decay when no harsh braking
            increments["harsh_braking"] = -0.01

        # Energy degradation: EV battery degrades faster than diesel fuel system
        energy = bus.get("energy", {})
        if energy.get("type") == "EV":
            deg_increment = rng.uniform(0.008, 0.015)
        else:
            deg_increment = rng.uniform(0.002, 0.006)
        increments["energy_degradation"] = deg_increment

        return increments

    def _check_thresholds_and_generate_predictions(self, bus_id: str, health: Dict[str, ComponentHealth]) -> List[dict]:
        """Check component thresholds and generate maintenance predictions."""
        predictions = []
        bus = store.get_bus(bus_id) or {}
        energy = bus.get("energy", {})

        for name, comp in health.items():
            if name.startswith("tyre") and comp.value >= THRESHOLDS["tyre_wear_pct"]:
                if comp.rul_ticks and comp.rul_ticks <= 50:  # ~50 ticks ~ 50s demo
                    predictions.append({
                        "type": "TYRE_REPLACEMENT",
                        "component": name,
                        "current": round(comp.value, 1),
                        "threshold": THRESHOLDS["tyre_wear_pct"],
                        "rul_ticks": comp.rul_ticks,
                        "rul_minutes": round(comp.rul_ticks * 1.0 / 60, 1),
                        "severity": "WARNING" if comp.rul_ticks > 20 else "CRITICAL",
                        "data_source": comp.data_source.value,
                    })
            elif name == "vibration" and comp.value >= THRESHOLDS["vibration_rms"]:
                if comp.rul_ticks and comp.rul_ticks <= 100:
                    predictions.append({
                        "type": "VIBRATION_INSPECTION",
                        "component": "chassis_suspension",
                        "current": round(comp.value, 3),
                        "threshold": THRESHOLDS["vibration_rms"],
                        "rul_ticks": comp.rul_ticks,
                        "rul_minutes": round(comp.rul_ticks * 1.0 / 60, 1),
                        "severity": "WARNING",
                        "data_source": comp.data_source.value,
                    })
            elif name == "energy_degradation" and comp.value >= THRESHOLDS["energy_degradation_pct"]:
                predictions.append({
                    "type": "ENERGY_DEGRADATION",
                    "component": "battery" if energy.get("type") == "EV" else "fuel_system",
                    "current": round(comp.value, 1),
                    "threshold": THRESHOLDS["energy_degradation_pct"],
                    "rul_ticks": comp.rul_ticks,
                    "rul_minutes": round(comp.rul_ticks * 1.0 / 60, 1) if comp.rul_ticks else None,
                    "severity": "INFO",
                    "data_source": comp.data_source.value,
                })

        return predictions

    def _generate_maintenance_recommendations(self, bus_id: str, health: Dict[str, ComponentHealth], predictions: List[dict]) -> List[dict]:
        """Generate evidence-based maintenance recommendations."""
        recommendations = []
        bus = store.get_bus(bus_id) or {}

        # Check each component for recommendations
        for name, comp in health.items():
            state = comp.get_health_state()

            if name.startswith("tyre"):
                if state == HealthState.CRITICAL:
                    recommendations.append({
                        "vehicle": bus_id,
                        "component": name,
                        "action": "REPLACE_TYRE",
                        "reason": f"Tyre wear at {comp.value:.1f}% (threshold: {THRESHOLDS['tyre_wear_pct']}%)",
                        "severity": "CRITICAL",
                        "evidence": {
                            "wear_pct": round(comp.value, 1),
                            "threshold": THRESHOLDS["tyre_wear_pct"],
                            "rul_ticks": comp.rul_ticks,
                            "pressure_psi": float(bus.get("wheels", [85, 85, 85, 85])[["tyre_fl", "tyre_fr", "tyre_rl", "tyre_rr"].index(name)] if name in ["tyre_fl", "tyre_fr", "tyre_rl", "tyre_rr"] else 85),
                        },
                        "source": comp.data_source.value,
                        "timestamp": utcnow_iso(),
                    })
                elif state == HealthState.WARNING:
                    recommendations.append({
                        "vehicle": bus_id,
                        "component": name,
                        "action": "INSPECT_TYRE",
                        "reason": f"Tyre wear at {comp.value:.1f}% (approaching threshold: {THRESHOLDS['tyre_wear_pct']}%)",
                        "severity": "WARNING",
                        "evidence": {
                            "wear_pct": round(comp.value, 1),
                            "threshold": THRESHOLDS["tyre_wear_pct"],
                            "rul_ticks": comp.rul_ticks,
                        },
                        "source": comp.data_source.value,
                        "timestamp": utcnow_iso(),
                    })

            elif name == "vibration":
                if state in (HealthState.WARNING, HealthState.CRITICAL):
                    recommendations.append({
                        "vehicle": bus_id,
                        "component": "chassis_suspension",
                        "action": "INSPECT_VIBRATION",
                        "reason": f"Vibration RMS at {comp.value:.3f} (threshold: {THRESHOLDS['vibration_rms']})",
                        "severity": state.value,
                        "evidence": {
                            "vibration_rms": round(comp.value, 3),
                            "threshold": THRESHOLDS["vibration_rms"],
                            "anomaly_count": comp.anomaly_count,
                            "rul_ticks": comp.rul_ticks,
                        },
                        "source": comp.data_source.value,
                        "timestamp": utcnow_iso(),
                    })

            elif name == "energy_degradation":
                if state == HealthState.WARNING:
                    comp_type = "battery" if bus.get("energy", {}).get("type") == "EV" else "fuel_system"
                    recommendations.append({
                        "vehicle": bus_id,
                        "component": comp_type,
                        "action": "CHECK_ENERGY_SYSTEM",
                        "reason": f"Energy degradation at {comp.value:.1f}% (threshold: {THRESHOLDS['energy_degradation_pct']}%)",
                        "severity": "WARNING",
                        "evidence": {
                            "degradation_pct": round(comp.value, 1),
                            "threshold": THRESHOLDS["energy_degradation_pct"],
                            "energy_type": bus.get("energy", {}).get("type", "UNKNOWN"),
                            "rul_ticks": comp.rul_ticks,
                        },
                        "source": comp.data_source.value,
                        "timestamp": utcnow_iso(),
                    })

        # Add predictions as recommendations too
        for pred in predictions:
            if pred["type"] in ("TYRE_REPLACEMENT", "VIBRATION_INSPECTION", "ENERGY_DEGRADATION"):
                # Avoid duplicate recommendations
                comp_name = pred["component"]
                existing = any(r["component"] == comp_name and r["action"] in ("REPLACE_TYRE", "INSPECT_VIBRATION", "CHECK_ENERGY_SYSTEM") for r in recommendations)
                if not existing:
                    action_map = {
                        "TYRE_REPLACEMENT": "REPLACE_TYRE",
                        "VIBRATION_INSPECTION": "INSPECT_VIBRATION",
                        "ENERGY_DEGRADATION": "CHECK_ENERGY_SYSTEM",
                    }
                    recommendations.append({
                        "vehicle": bus_id,
                        "component": comp_name,
                        "action": action_map.get(pred["type"], "INSPECT"),
                        "reason": f"{pred['type']}: {pred['component']} at {pred['current']} (threshold: {pred['threshold']})",
                        "severity": pred["severity"],
                        "evidence": {
                            "current": pred["current"],
                            "threshold": pred["threshold"],
                            "rul_ticks": pred.get("rul_ticks"),
                            "rul_minutes": pred.get("rul_minutes"),
                        },
                        "source": pred.get("data_source", "SIMULATION"),
                        "timestamp": utcnow_iso(),
                    })

        # Store in history
        if recommendations:
            with self._lock:
                if bus_id not in self._maintenance_history:
                    self._maintenance_history[bus_id] = []
                self._maintenance_history[bus_id].extend(recommendations)
                # Keep last 50 recommendations per bus
                if len(self._maintenance_history[bus_id]) > 50:
                    self._maintenance_history[bus_id] = self._maintenance_history[bus_id][-50:]

        return recommendations

    def tick(self, bus: dict, rng: random.Random, data_source: DataSource = DataSource.SIMULATION) -> List[dict]:
        """Advance degradation counters for one bus, return any new predictions."""
        bid = bus["bus_id"]
        health = self.get_or_create(bid, data_source)
        predictions = []

        # Calculate increments based on telemetry
        increments = self._calculate_component_increments(bus, rng, data_source)

        # Update each component
        for name, increment in increments.items():
            if name in health:
                health[name].update(increment, data_source=data_source)

        # Check thresholds and generate predictions
        predictions = self._check_thresholds_and_generate_predictions(bid, health)

        return predictions

    def get_vehicle_health(self, bus_id: str, data_source: DataSource = DataSource.SIMULATION) -> VehicleHealth:
        """Get complete vehicle health snapshot."""
        health = self.get_or_create(bus_id, data_source)

        # Calculate overall health from components
        component_states = [comp.get_health_state() for comp in health.values()]
        state_priority = {
            HealthState.CRITICAL: 4,
            HealthState.WARNING: 3,
            HealthState.WATCH: 2,
            HealthState.HEALTHY: 1,
            HealthState.UNKNOWN: 0,
        }
        overall_state = max(component_states, key=lambda s: state_priority[s])

        # Overall score: weighted average of component values (inverted so lower=better)
        component_scores = []
        for name, comp in health.items():
            state = comp.get_health_state()
            # Map health state to score (0=healthy, 100=critical)
            if state == HealthState.HEALTHY:
                score = comp.value * 0.25
            elif state == HealthState.WATCH:
                score = 25 + (comp.value - 40) * 0.5
            elif state == HealthState.WARNING:
                score = 50 + (comp.value - 60) * 0.75
            else:  # CRITICAL
                score = 75 + (comp.value - 80) * 1.25
            component_scores.append(min(100, max(0, score)))

        overall_score = sum(component_scores) / len(component_scores) if component_scores else 0

        # Generate current recommendations
        predictions = self._check_thresholds_and_generate_predictions(bus_id, health)
        recommendations = self._generate_maintenance_recommendations(bus_id, health, predictions)

        # Collect active anomalies
        anomalies = []
        for name, comp in health.items():
            state = comp.get_health_state()
            if state in (HealthState.WARNING, HealthState.CRITICAL):
                anomalies.append({
                    "component": name,
                    "type": comp.component_type,
                    "value": round(comp.value, 1),
                    "health_state": state.value,
                    "data_source": comp.data_source.value,
                })

        return VehicleHealth(
            bus_id=bus_id,
            overall_state=overall_state,
            overall_score=overall_score,
            components=health,
            anomalies=anomalies,
            maintenance_recommendations=recommendations,
            data_source=data_source,
            last_update=utcnow_iso(),
            confidence=None,  # heuristic, no confidence
        )

    def get_maintenance_history(self, bus_id: str) -> List[dict]:
        """Get maintenance recommendation history for a bus."""
        with self._lock:
            return list(self._maintenance_history.get(bus_id, []))

    def reset_bus(self, bus_id: str):
        """Reset health tracking for a bus (e.g., after maintenance)."""
        with self._lock:
            if bus_id in self.bus_health:
                del self.bus_health[bus_id]
            if bus_id in self._maintenance_history:
                del self._maintenance_history[bus_id]


health_tracker = VehicleHealthTracker()


def tick_all(buses: list, rng: random.Random, data_source: DataSource = DataSource.SIMULATION) -> Dict[str, list]:
    """Run health tick for all buses, return predictions by bus_id."""
    all_preds = {}
    for bus in buses:
        preds = health_tracker.tick(bus, rng, data_source)
        if preds:
            all_preds[bus["bus_id"]] = preds
    return all_preds


def get_health_summary(bus_id: str, data_source: DataSource = DataSource.SIMULATION) -> dict:
    """Get current health summary for a bus."""
    vehicle_health = health_tracker.get_vehicle_health(bus_id, data_source)
    return vehicle_health.to_dict()


def get_fleet_health_summary(data_source: DataSource = DataSource.SIMULATION) -> dict:
    """Get fleet-wide health summary for dashboard."""
    buses = store.get_buses()
    summary = {
        "healthy": 0,
        "watch": 0,
        "warning": 0,
        "critical": 0,
        "unknown": 0,
        "buses": {},
    }
    for bus in buses:
        vh = health_tracker.get_vehicle_health(bus["bus_id"], data_source)
        state = vh.overall_state.value.lower()
        if state in summary:
            summary[state] += 1
        else:
            summary["unknown"] += 1
        summary["buses"][bus["bus_id"]] = {
            "overall_state": vh.overall_state.value,
            "overall_score": round(vh.overall_score, 1),
            "anomaly_count": len(vh.anomalies),
            "recommendation_count": len(vh.maintenance_recommendations),
        }
    return summary


def generate_health_events(data_source: DataSource = DataSource.SIMULATION) -> List[dict]:
    """Generate vehicle health events from current health state.

    Creates VEHICLE_ANOMALY events for components in WARNING or CRITICAL state.
    Events are added to the store (which triggers alerts via data_store.add_event).
    """
    from data_store import store
    buses = store.get_buses()
    events = []

    for bus in buses:
        bid = bus["bus_id"]
        vh = health_tracker.get_vehicle_health(bid, data_source)

        for anomaly in vh.anomalies:
            # Only generate event for WARNING and CRITICAL (not WATCH)
            if anomaly["health_state"] in ("WARNING", "CRITICAL"):
                event = {
                    "bus_id": bid,
                    "reg_no": bus.get("reg_no", ""),
                    "event_type": "VEHICLE_ANOMALY",
                    "latitude": bus.get("latitude"),
                    "longitude": bus.get("longitude"),
                    "severity": anomaly["health_state"],
                    "confidence": 0.8 if anomaly["health_state"] == "WARNING" else 0.9,
                    "sensor_source": "vehicle_health",
                    "status": "ACTIVE",
                    "simulation": data_source == DataSource.SIMULATION,
                    "data_source": data_source.value.lower(),
                    "additional_data": {
                        "note": f"Vehicle health anomaly: {anomaly['component']} ({anomaly['type']}) at {anomaly['value']}",
                        "component": anomaly["component"],
                        "component_type": anomaly["type"],
                        "value": anomaly["value"],
                        "health_state": anomaly["health_state"],
                        "data_source": anomaly["data_source"],
                    },
                }
                events.append(event)
                store.add_event(event)

    return events