"""
predictive_incident_engine.py
V2 Predictive Incident Intelligence.

Correlates multi-signal conditions to predict elevated incident probability
before an actual incident occurs. Combines:

- Driver fatigue/drowsiness state
- Vehicle health degradation
- Speed anomalies
- Road risk exposure
- Passenger load/overcrowding
- Traffic congestion
- Historical incident patterns
- Route characteristics

Produces:
- Incident probability score per bus (0-100)
- Contributing factor chain (signal → condition → prediction)
- Early warning alerts with lead time estimates
- Recommended preventive actions

DATA CLASSIFICATION: RULE-BASED PREDICTIVE LAYER
Uses multi-signal correlation with weighted thresholds.
No ML model is trained; this is an engineered heuristic predictive system.
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import math


# ---------------------------------------------------------------------------
# Incident prediction configuration
# ---------------------------------------------------------------------------

# Signal weights for incident probability (sum to 1.0)
SIGNAL_WEIGHTS = {
    "driver_fatigue": 0.25,
    "vehicle_health": 0.15,
    "speed_anomaly": 0.15,
    "road_risk": 0.20,
    "passenger_load": 0.10,
    "traffic_congestion": 0.05,
    "historical_incidents": 0.10,
}

# Incident probability thresholds
INCIDENT_PROB_THRESHOLDS = {
    "LOW": (0, 25),
    "MODERATE": (25, 50),
    "ELEVATED": (50, 70),
    "HIGH": (70, 85),
    "CRITICAL": (85, 100),
}

# Signal degradation thresholds (score 0-100, higher = worse)
SIGNAL_THRESHOLDS = {
    "driver_fatigue": {
        "normal": 20,
        "watch": 40,
        "alert": 60,
        "critical": 80,
    },
    "vehicle_health": {
        "healthy": 15,
        "watch": 35,
        "warning": 60,
        "critical": 85,
    },
    "speed_anomaly": {
        "normal": 20,
        "elevated": 45,
        "high": 70,
        "extreme": 90,
    },
    "road_risk": {
        "clear": 15,
        "moderate": 40,
        "high": 65,
        "critical": 85,
    },
    "passenger_load": {
        "normal": 20,
        "moderate": 45,
        "high": 70,
        "overcrowded": 90,
    },
    "traffic_congestion": {
        "free_flow": 10,
        "moderate": 35,
        "congested": 60,
        "gridlock": 85,
    },
    "historical_incidents": {
        "none": 5,
        "rare": 25,
        "occasional": 50,
        "frequent": 80,
    },
}

# Correlation multipliers: when multiple signals degrade simultaneously,
# the combined risk is higher than the sum of parts
CORRELATION_MULTIPLIERS = {
    2: 1.15,  # 2 signals degraded
    3: 1.35,  # 3 signals degraded
    4: 1.60,  # 4+ signals degraded
}

# Lead time categories
LEAD_TIME = {
    "IMMEDIATE": "< 5 minutes",
    "SHORT": "5-15 minutes",
    "MEDIUM": "15-30 minutes",
    "LONG": "30+ minutes",
}


class PredictiveIncidentEngine:
    """
    Multi-signal predictive incident intelligence engine.

    Correlates driver, vehicle, road, load, traffic, and historical signals
    to estimate incident probability and generate early warnings.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._prediction_history: Dict[str, List[Dict]] = defaultdict(list)
        self._alert_cache: Dict[str, Dict] = {}

    def evaluate_bus(
        self,
        bus: Dict,
        events: List[Dict] = None,
        road_risk_data: Dict = None,
        traffic_data: Dict = None,
    ) -> Dict:
        """
        Evaluate incident probability for a single bus.

        Returns comprehensive prediction with factor chain, probability score,
        and recommended preventive actions.
        """
        bus_id = bus.get("bus_id", "")
        events = events or []
        road_risk_data = road_risk_data or {}
        traffic_data = traffic_data or {}

        # ── Extract signals ──
        driver_signal = self._extract_driver_signal(bus)
        vehicle_signal = self._extract_vehicle_signal(bus)
        speed_signal = self._extract_speed_signal(bus)
        road_signal = self._extract_road_signal(bus, road_risk_data)
        load_signal = self._extract_load_signal(bus)
        traffic_signal = self._extract_traffic_signal(bus, traffic_data)
        historical_signal = self._extract_historical_signal(bus_id, events)

        signals = {
            "driver_fatigue": driver_signal,
            "vehicle_health": vehicle_signal,
            "speed_anomaly": speed_signal,
            "road_risk": road_signal,
            "passenger_load": load_signal,
            "traffic_congestion": traffic_signal,
            "historical_incidents": historical_signal,
        }

        # ── Calculate weighted probability ──
        weighted_sum = 0.0
        total_weight = 0.0
        degraded_signals = []

        for signal_name, signal_data in signals.items():
            weight = SIGNAL_WEIGHTS.get(signal_name, 0)
            score = signal_data.get("score", 0)
            weighted_sum += score * weight
            total_weight += weight
            if score >= 50:
                degraded_signals.append(signal_name)

        base_probability = weighted_sum / total_weight if total_weight > 0 else 0

        # ── Apply correlation multiplier ──
        num_degraded = len(degraded_signals)
        correlation_multiplier = 1.0
        if num_degraded >= 2:
            correlation_multiplier = CORRELATION_MULTIPLIERS.get(
                min(num_degraded, 4), 1.60
            )

        final_probability = min(100.0, base_probability * correlation_multiplier)

        # ── Determine probability level ──
        prob_level = "LOW"
        for level, (lo, hi) in INCIDENT_PROB_THRESHOLDS.items():
            if lo <= final_probability < hi:
                prob_level = level
                break
        if final_probability >= 85:
            prob_level = "CRITICAL"

        # ── Build factor chain ──
        factor_chain = self._build_factor_chain(signals, degraded_signals)

        # ── Determine lead time ──
        lead_time = self._estimate_lead_time(final_probability, signals)

        # ── Generate early warnings ──
        warnings = self._generate_early_warnings(
            bus_id, final_probability, prob_level, signals, degraded_signals
        )

        # ── Generate preventive recommendations ──
        recommendations = self._generate_preventive_recommendations(
            bus_id, final_probability, signals, degraded_signals
        )

        # ── Record prediction ──
        prediction = {
            "bus_id": bus_id,
            "route_code": bus.get("route_code", ""),
            "incident_probability": round(final_probability, 1),
            "probability_level": prob_level,
            "correlation_multiplier": round(correlation_multiplier, 2),
            "degraded_signal_count": num_degraded,
            "degraded_signals": degraded_signals,
            "signals": signals,
            "factor_chain": factor_chain,
            "lead_time": lead_time,
            "warnings": warnings,
            "recommendations": recommendations,
            "explanation": self._build_explanation(
                bus_id, final_probability, prob_level, signals, degraded_signals
            ),
            "data_source": "RULE-BASED PREDICTIVE",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        # ── Cache ──
        with self._lock:
            self._prediction_history[bus_id].append({
                "timestamp": prediction["timestamp"],
                "probability": final_probability,
                "level": prob_level,
            })
            # Keep last 2 hours
            cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
            self._prediction_history[bus_id] = [
                p for p in self._prediction_history[bus_id]
                if self._parse_ts(p["timestamp"]) > cutoff
            ]
            self._alert_cache[bus_id] = prediction

        return prediction

    def evaluate_fleet(
        self,
        buses: List[Dict],
        events: List[Dict] = None,
        road_risk_data: Dict = None,
        traffic_data: Dict = None,
    ) -> Dict:
        """Evaluate incident probability for entire fleet."""
        predictions = []
        for bus in buses:
            pred = self.evaluate_bus(bus, events, road_risk_data, traffic_data)
            predictions.append(pred)

        valid = [p for p in predictions if p.get("incident_probability") is not None]

        # Fleet summary
        if valid:
            avg_prob = sum(p["incident_probability"] for p in valid) / len(valid)
            high_risk_count = sum(1 for p in valid if p["probability_level"] in ("HIGH", "CRITICAL"))
            elevated_count = sum(1 for p in valid if p["probability_level"] == "ELEVATED")
            total_warnings = sum(len(p.get("warnings", [])) for p in valid)
        else:
            avg_prob = 0
            high_risk_count = 0
            elevated_count = 0
            total_warnings = 0

        # Sort by probability descending
        predictions.sort(key=lambda p: p.get("incident_probability", 0), reverse=True)

        return {
            "predictions": predictions,
            "fleet_summary": {
                "total_buses": len(buses),
                "evaluated": len(valid),
                "avg_incident_probability": round(avg_prob, 1),
                "high_risk_count": high_risk_count,
                "elevated_count": elevated_count,
                "total_warnings": total_warnings,
            },
            "data_source": "RULE-BASED PREDICTIVE",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # ── Signal extraction methods ──

    def _extract_driver_signal(self, bus: Dict) -> Dict:
        """Extract driver fatigue/drowsiness signal."""
        driver = bus.get("driver") or {}
        state = driver.get("state", "UNKNOWN")
        fatigue_stage = driver.get("fatigue_stage", "NORMAL")
        perclos = driver.get("perclos", 0)
        fatigue_lt = driver.get("fatigue_lt", 0)
        fatigue_st = driver.get("fatigue_st", 0)

        score = 0.0
        evidence = []

        if state in ("DROWSY", "EYES_CLOSED"):
            score = 85
            evidence.append(f"Driver state: {state}")
        elif state == "ALERT":
            score = 55
            evidence.append(f"Driver state: {state}")
        elif fatigue_stage == "CRITICAL":
            score = 80
            evidence.append(f"Fatigue stage: CRITICAL")
        elif fatigue_stage == "FATIGUE":
            score = 60
            evidence.append(f"Fatigue stage: FATIGUE")
        elif fatigue_stage == "ALERT":
            score = 45
            evidence.append(f"Fatigue stage: ALERT")

        if perclos > 40:
            score = max(score, 75)
            evidence.append(f"PERCLOS {perclos:.0f}% (critical threshold)")
        elif perclos > 25:
            score = max(score, 55)
            evidence.append(f"PERCLOS {perclos:.0f}% (elevated)")

        if fatigue_st > 60:
            score = max(score, 65)
            evidence.append(f"Short-term fatigue {fatigue_st:.0f}")

        return {
            "score": min(100, score),
            "state": self._score_to_state(score, "driver_fatigue"),
            "evidence": evidence,
            "source": "DDS" if state != "UNKNOWN" else "UNKNOWN",
        }

    def _extract_vehicle_signal(self, bus: Dict) -> Dict:
        """Extract vehicle health signal."""
        vehicle = bus.get("vehicle") or {}
        health = vehicle.get("health", "UNKNOWN")
        vibration = vehicle.get("vibration", 0)
        wheels = bus.get("wheels") or []
        energy = bus.get("energy") or {}

        score = 0.0
        evidence = []

        if health == "CRITICAL":
            score = 85
            evidence.append(f"Vehicle health: CRITICAL")
        elif health == "WARNING":
            score = 55
            evidence.append(f"Vehicle health: WARNING")
        elif health == "INSPECTION REQUIRED":
            score = 65
            evidence.append(f"Vehicle health: INSPECTION REQUIRED")

        if vibration > 1.5:
            score = max(score, 70)
            evidence.append(f"High vibration: {vibration:.2f}")
        elif vibration > 1.0:
            score = max(score, 45)
            evidence.append(f"Elevated vibration: {vibration:.2f}")

        # Tyre pressure
        out_of_range = [w for w in wheels if w < 70 or w > 95]
        if len(out_of_range) >= 2:
            score = max(score, 60)
            evidence.append(f"{len(out_of_range)} tyres out of range")
        elif out_of_range:
            score = max(score, 40)
            evidence.append(f"1 tyre out of range")

        # Energy
        if energy.get("percent", 100) < 15:
            score = max(score, 30)
            evidence.append(f"Low energy: {energy.get('percent', 0):.0f}%")

        return {
            "score": min(100, score),
            "state": self._score_to_state(score, "vehicle_health"),
            "evidence": evidence,
            "source": "VEHICLE_TELEMETRY",
        }

    def _extract_speed_signal(self, bus: Dict) -> Dict:
        """Extract speed anomaly signal."""
        speed = float(bus.get("speed_kmh", 0))

        score = 0.0
        evidence = []

        if speed > 60:
            score = 90
            evidence.append(f"Extreme speed: {speed:.0f} km/h")
        elif speed > 50:
            score = 65
            evidence.append(f"High speed: {speed:.0f} km/h")
        elif speed > 40:
            score = 35
            evidence.append(f"Moderate speed: {speed:.0f} km/h")
        else:
            score = 10
            evidence.append(f"Normal speed: {speed:.0f} km/h")

        return {
            "score": min(100, score),
            "state": self._score_to_state(score, "speed_anomaly"),
            "evidence": evidence,
            "source": "GPS_TELEMETRY",
        }

    def _extract_road_signal(self, bus: Dict, road_risk_data: Dict) -> Dict:
        """Extract road risk exposure signal."""
        bus_id = bus.get("bus_id", "")
        score = 0.0
        evidence = []

        # Check bus exposure from road risk system
        exposures = road_risk_data.get("exposures", {})
        bus_exposure = exposures.get(bus_id, {})
        exposure_status = bus_exposure.get("status", "UNKNOWN")

        if exposure_status == "EXPOSED":
            score = 75
            evidence.append(f"Bus exposed to road risk zone")
        elif exposure_status == "APPROACHING":
            score = 45
            evidence.append(f"Bus approaching road risk zone")

        # Check road defects near bus
        route_code = bus.get("route_code", "")
        route_risk = road_risk_data.get("route_index", {})
        if route_code in route_risk:
            route_risk_score = route_risk[route_code].get("risk_score", 0)
            if route_risk_score > 60:
                score = max(score, 60)
                evidence.append(f"High route risk: {route_risk_score}/100")
            elif route_risk_score > 35:
                score = max(score, 40)
                evidence.append(f"Moderate route risk: {route_risk_score}/100")

        return {
            "score": min(100, score),
            "state": self._score_to_state(score, "road_risk"),
            "evidence": evidence,
            "source": "ROAD_RISK_ENGINE",
        }

    def _extract_load_signal(self, bus: Dict) -> Dict:
        """Extract passenger load/overcrowding signal."""
        occ = bus.get("occupancy") or {}
        load = bus.get("load") or {}
        pct = occ.get("pct", 0)
        load_pct = load.get("load_pct", 0)

        score = 0.0
        evidence = []

        effective_pct = max(pct, load_pct)

        if effective_pct >= 95:
            score = 90
            evidence.append(f"Overcrowded: {effective_pct:.0f}% capacity")
        elif effective_pct >= 85:
            score = 65
            evidence.append(f"High load: {effective_pct:.0f}% capacity")
        elif effective_pct >= 70:
            score = 40
            evidence.append(f"Moderate load: {effective_pct:.0f}% capacity")
        else:
            score = 15
            evidence.append(f"Normal load: {effective_pct:.0f}% capacity")

        return {
            "score": min(100, score),
            "state": self._score_to_state(score, "passenger_load"),
            "evidence": evidence,
            "source": "OCCUPANCY_SYSTEM",
        }

    def _extract_traffic_signal(self, bus: Dict, traffic_data: Dict) -> Dict:
        """Extract traffic congestion signal."""
        congestion = traffic_data.get("congestion_level", "moderate")

        score_map = {
            "free_flow": 10,
            "moderate": 35,
            "congested": 60,
            "gridlock": 85,
        }
        score = score_map.get(congestion, 35)
        evidence = [f"Traffic: {congestion}"]

        return {
            "score": score,
            "state": self._score_to_state(score, "traffic_congestion"),
            "evidence": evidence,
            "source": "TRAFFIC_PATTERN",
        }

    def _extract_historical_signal(self, bus_id: str, events: List[Dict]) -> Dict:
        """Extract historical incident pattern signal."""
        # Count recent incidents for this bus
        bus_events = [e for e in events if e.get("bus_id") == bus_id]
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        incident_count = 0
        for e in bus_events:
            et = e.get("timestamp", "")
            try:
                et_dt = datetime.fromisoformat(et.replace("Z", "+00:00"))
                if et_dt > recent_cutoff:
                    severity = e.get("severity", "INFO")
                    if severity in ("HIGH", "CRITICAL"):
                        incident_count += 2
                    elif severity == "MEDIUM":
                        incident_count += 1
            except (ValueError, TypeError):
                pass

        score = min(80, incident_count * 15)
        evidence = [f"{incident_count} recent high-severity events"] if incident_count > 0 else ["No recent incidents"]

        return {
            "score": score,
            "state": self._score_to_state(score, "historical_incidents"),
            "evidence": evidence,
            "source": "EVENT_LOG",
        }

    # ── Analysis methods ──

    def _score_to_state(self, score: float, signal_type: str) -> str:
        """Convert numeric score to state label."""
        thresholds = SIGNAL_THRESHOLDS.get(signal_type, {})
        if score >= thresholds.get("critical", 80):
            return "CRITICAL"
        elif score >= thresholds.get("high", thresholds.get("warning", 60)):
            return "HIGH"
        elif score >= thresholds.get("elevated", thresholds.get("watch", 40)):
            return "ELEVATED"
        else:
            return "NORMAL"

    def _build_factor_chain(
        self, signals: Dict, degraded_signals: List[str]
    ) -> List[Dict]:
        """Build the causal chain showing how signals contribute to prediction."""
        chain = []
        for signal_name in degraded_signals:
            signal_data = signals[signal_name]
            chain.append({
                "signal": signal_name,
                "score": signal_data["score"],
                "state": signal_data["state"],
                "evidence": signal_data.get("evidence", []),
                "weight": SIGNAL_WEIGHTS.get(signal_name, 0),
                "contribution": round(
                    signal_data["score"] * SIGNAL_WEIGHTS.get(signal_name, 0), 1
                ),
            })
        chain.sort(key=lambda x: x["contribution"], reverse=True)
        return chain

    def _estimate_lead_time(self, probability: float, signals: Dict) -> Dict:
        """Estimate how much lead time the operator has."""
        # Higher probability = shorter lead time
        if probability >= 85:
            category = "IMMEDIATE"
            minutes = "< 5"
        elif probability >= 70:
            category = "SHORT"
            minutes = "5-15"
        elif probability >= 50:
            category = "MEDIUM"
            minutes = "15-30"
        else:
            category = "LONG"
            minutes = "30+"

        return {
            "category": category,
            "estimated_minutes": minutes,
            "description": LEAD_TIME.get(category, "Unknown"),
        }

    def _generate_early_warnings(
        self,
        bus_id: str,
        probability: float,
        level: str,
        signals: Dict,
        degraded: List[str],
    ) -> List[Dict]:
        """Generate actionable early warnings."""
        warnings = []

        if level in ("CRITICAL", "HIGH"):
            warnings.append({
                "type": "INCIDENT_PROBABILITY_HIGH",
                "severity": level,
                "message": f"Bus {bus_id}: Incident probability {level} ({probability:.0f}%)",
                "action": "Immediate operator attention required",
            })

        if level == "ELEVATED":
            warnings.append({
                "type": "INCIDENT_PROBABILITY_ELEVATED",
                "severity": "WARNING",
                "message": f"Bus {bus_id}: Incident probability elevated ({probability:.0f}%)",
                "action": "Monitor closely, prepare preventive action",
            })

        # Specific signal warnings
        driver = signals.get("driver_fatigue", {})
        if driver.get("score", 0) >= 70:
            warnings.append({
                "type": "DRIVER_FATIGUE_RISK",
                "severity": "HIGH",
                "message": f"Bus {bus_id}: Driver fatigue contributing significantly to incident risk",
                "action": "Consider driver relief or rest stop",
            })

        road = signals.get("road_risk", {})
        if road.get("score", 0) >= 60:
            warnings.append({
                "type": "ROAD_RISK_EXPOSURE",
                "severity": "WARNING",
                "message": f"Bus {bus_id}: Operating in high-risk road segment",
                "action": "Reduce speed, increase following distance",
            })

        load = signals.get("passenger_load", {})
        if load.get("score", 0) >= 70:
            warnings.append({
                "type": "OVERCROWDING_RISK",
                "severity": "WARNING",
                "message": f"Bus {bus_id}: Passenger overcrowding increasing incident risk",
                "action": "Consider relief bus or skip stop boarding",
            })

        return warnings

    def _generate_preventive_recommendations(
        self,
        bus_id: str,
        probability: float,
        signals: Dict,
        degraded: List[str],
    ) -> List[Dict]:
        """Generate recommended preventive actions."""
        recs = []

        if probability >= 70:
            recs.append({
                "action": "OPERATOR_INTERVENTION",
                "priority": "HIGH",
                "description": f"Bus {bus_id} requires immediate operator review",
            })

        driver = signals.get("driver_fatigue", {})
        if driver.get("score", 0) >= 60:
            recs.append({
                "action": "DRIVER_RELIEF",
                "priority": "HIGH",
                "description": "Arrange driver relief at next major stop",
            })

        vehicle = signals.get("vehicle_health", {})
        if vehicle.get("score", 0) >= 55:
            recs.append({
                "action": "VEHICLE_INSPECTION",
                "priority": "MEDIUM",
                "description": "Schedule vehicle inspection at next depot",
            })

        road = signals.get("road_risk", {})
        if road.get("score", 0) >= 50:
            recs.append({
                "action": "SPEED_REDUCTION",
                "priority": "MEDIUM",
                "description": "Advise driver to reduce speed in current corridor",
            })

        load = signals.get("passenger_load", {})
        if load.get("score", 0) >= 65:
            recs.append({
                "action": "RELIEF_BUS",
                "priority": "MEDIUM",
                "description": "Deploy relief bus to reduce overcrowding",
            })

        if len(degraded) >= 3:
            recs.append({
                "action": "ROUTE_REASSIGNMENT",
                "priority": "HIGH",
                "description": "Consider reassigning bus to lower-risk route",
            })

        return recs

    def _build_explanation(
        self,
        bus_id: str,
        probability: float,
        level: str,
        signals: Dict,
        degraded: List[str],
    ) -> str:
        """Build human-readable explanation of the prediction."""
        if not degraded:
            return f"Bus {bus_id}: All signals normal. Incident probability LOW ({probability:.0f}%)."

        # Top contributing factors
        top_factors = sorted(
            [(name, signals[name]) for name in degraded],
            key=lambda x: x[1]["score"] * SIGNAL_WEIGHTS.get(x[0], 0),
            reverse=True,
        )[:3]

        factor_str = ", ".join(
            f"{name.replace('_', ' ')} ({data['score']:.0f})"
            for name, data in top_factors
        )

        return (
            f"Bus {bus_id}: Incident probability {level} ({probability:.0f}%). "
            f"Key factors: {factor_str}. "
            f"{len(degraded)} signal(s) degraded simultaneously. "
            f"{'Immediate action recommended.' if level in ('HIGH', 'CRITICAL') else 'Monitor and prepare response.'}"
        )

    @staticmethod
    def _parse_ts(ts: str) -> datetime:
        try:
            ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
predictive_incident_engine = PredictiveIncidentEngine()
