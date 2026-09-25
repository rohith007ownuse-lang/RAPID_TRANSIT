"""
risk_engine.py
Unified bus risk engine for the Control Centre — Phase 15 Enhanced.

Produces a single risk score (0-100) per bus from six weighted segments
(driver / vehicle / load / speed / occupancy / history), a risk level
(LOW / MEDIUM / HIGH / CRITICAL), human-readable reasons, and initial
recommended actions. All inputs are the SIMULATED live bus states plus the
recent event log; the engine is pure (no Flask/threading dependencies) so it
can be unit-tested and reused by the recommendation layer later.

Weights are user-tunable through /api/settings -> sink.risk_weights (defaults
below are merged in, never overrides the whole config structure).

Phase 15 Enhancements:
- Risk state tracking with UNKNOWN for missing data
- Factor-level explainability with evidence, source, timestamp
- Risk trend calculation (INCREASING/STABLE/DECREASING/UNKNOWN)
- Risk state transitions with debounce/hysteresis
- Data quality/coverage indicators
- Cross-system evidence integration
"""

from datetime import datetime, timezone
from collections import OrderedDict
import threading
import time

DEFAULT_RISK_WEIGHTS = {
    "driver": 30,
    "vehicle": 20,
    "load": 15,
    "speed": 10,
    "occupancy": 10,
    "history": 15,
}

# severity -> contribution to the history segment score
HISTORY_SEVERITY = {"CRITICAL": 34, "WARNING": 16, "INFO": 5}

SEVERITY_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# Risk states including UNKNOWN for missing data
RISK_STATES = ("LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN")

# Trend states
RISK_TRENDS = ("INCREASING", "STABLE", "DECREASING", "UNKNOWN")

# State transition debounce settings (seconds)
_TRANSITION_DEBOUNCE_S = 30.0
_TRANSITION_HYSTERESIS = 5.0  # score change required to trigger transition

# Risk state thresholds — HIGH starts at 60 so the "high risk" tier stays
# focused on the buses actually worth operator attention (60–70+ band).
_RISK_THRESHOLDS = {
    "LOW": (0, 30),
    "MODERATE": (30, 60),
    "HIGH": (60, 80),
    "CRITICAL": (80, 100),
}


def level_for_score(score):
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MODERATE"
    return "LOW"


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(x)))


def _bounded(*values):
    """Weighted mean of bounded scores -> 0-100."""
    if not values:
        return 0.0
    return _clamp(sum(values) / len(values))


# ---------------------------------------------------------------------------
# Factor data quality tracking
# ---------------------------------------------------------------------------

class FactorData:
    """Tracks data quality and source for each risk factor."""

    def __init__(self, factor_name, score=0.0, state="UNKNOWN", evidence=None,
                 source="UNKNOWN", data_quality="UNKNOWN", available=False,
                 timestamp=None, confidence=None):
        self.factor_name = factor_name
        self.score = score
        self.state = state
        self.evidence = evidence or []
        self.source = source
        self.data_quality = data_quality
        self.available = available
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.confidence = confidence

    def to_dict(self):
        return {
            "factor_name": self.factor_name,
            "score": self.score,
            "state": self.state,
            "evidence": self.evidence,
            "source": self.source,
            "data_quality": self.data_quality,
            "available": self.available,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Risk state tracker (per-bus history for trends and transitions)
# ---------------------------------------------------------------------------

class RiskStateTracker:
    """Tracks risk state history for trend calculation and transition detection."""

    def __init__(self, max_history=20):
        self._lock = threading.Lock()
        self._bus_history = OrderedDict()  # bus_id -> list of (timestamp, score, state)
        self._bus_states = {}  # bus_id -> current state
        self._bus_last_transition = {}  # bus_id -> timestamp of last transition
        self._max_history = max_history

    def update(self, bus_id, score, state):
        """Update risk state for a bus. Returns (state_changed, transition_info)."""
        now = time.time()
        with self._lock:
            if bus_id not in self._bus_history:
                self._bus_history[bus_id] = []
                self._bus_history.move_to_end(bus_id)

            history = self._bus_history[bus_id]
            history.append((now, score, state))

            # Trim history
            while len(history) > self._max_history:
                history.pop(0)

            prev_state = self._bus_states.get(bus_id)
            self._bus_states[bus_id] = state

            # Check for meaningful transition with debounce
            state_changed = False
            transition_info = None

            if prev_state and prev_state != state:
                last_transition = self._bus_last_transition.get(bus_id, 0)
                if now - last_transition >= _TRANSITION_DEBOUNCE_S:
                    # Check hysteresis (score must change significantly)
                    if len(history) >= 2:
                        prev_score = history[-2][1]
                        if abs(score - prev_score) >= _TRANSITION_HYSTERESIS:
                            state_changed = True
                            transition_info = {
                                "from_state": prev_state,
                                "to_state": state,
                                "from_score": prev_score,
                                "to_score": score,
                                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            }
                            self._bus_last_transition[bus_id] = now

            return state_changed, transition_info

    def get_trend(self, bus_id):
        """Calculate risk trend based on recent history."""
        with self._lock:
            history = self._bus_history.get(bus_id, [])
            if len(history) < 2:
                return "UNKNOWN"

            # Compare recent scores (last 5 entries)
            recent = [h[1] for h in history[-5:]]
            if len(recent) < 2:
                return "UNKNOWN"

            # Calculate simple linear trend
            avg_first = sum(recent[:len(recent)//2]) / max(len(recent)//2, 1)
            avg_second = sum(recent[len(recent)//2:]) / max(len(recent) - len(recent)//2, 1)

            diff = avg_second - avg_first
            if diff > 3:
                return "INCREASING"
            elif diff < -3:
                return "DECREASING"
            else:
                return "STABLE"

    def get_history(self, bus_id, limit=None):
        """Get risk history for a bus."""
        with self._lock:
            history = self._bus_history.get(bus_id, [])
            if limit:
                return history[-limit:]
            return list(history)

    def get_coverage(self, bus_id):
        """Get data coverage (number of history points)."""
        with self._lock:
            return len(self._bus_history.get(bus_id, []))


# Global risk state tracker
_risk_tracker = RiskStateTracker()


# ---------------------------------------------------------------------------
# Segment scoring functions (enhanced with data quality)
# ---------------------------------------------------------------------------

def _score_driver(d, detection):
    """Driver alertness: state + temporal fatigue (stage, PERCLOS) + EAR/closure/pitch."""
    reasons = []
    evidence = []
    source = "UNKNOWN"
    available = False

    state = (d.get("state") or "NORMAL").upper()

    # Check if driver data is actually available
    if d.get("state") is not None or d.get("ear") is not None or d.get("fatigue_stage") is not None:
        available = True
        source = "LIVE DDS" if d.get("data_source") == "live" else "SIMULATION"

    if not available:
        return FactorData(
            factor_name="driver",
            score=0.0,
            state="UNKNOWN",
            evidence=["Driver telemetry unavailable"],
            source="UNKNOWN",
            data_quality="NO_DATA",
            available=False,
        )

    if state == "NORMAL":
        base = 8.0
    elif state == "ATTENTION":
        base = 48.0
        reasons.append("Driver attention level flagged")
        evidence.append({"type": "driver_state", "value": state, "detail": "Attention flagged"})
    else:  # DROWSY
        base = 78.0
        reasons.append("Driver drowsy - immediate attention")
        evidence.append({"type": "driver_state", "value": state, "detail": "Drowsiness detected"})

    # temporal fatigue: cumulative + short-term + stage
    stage = (d.get("fatigue_stage") or "WATCH").upper()
    stage_contrib = {"WATCH": 8.0, "ALERT": 55.0, "CRITICAL": 85.0}.get(stage, 8.0) * 0.4
    if stage == "CRITICAL":
        reasons.append("Critical fatigue stage")
        evidence.append({"type": "fatigue_stage", "value": stage, "detail": "Critical fatigue"})
    elif stage == "ALERT":
        reasons.append("Raised fatigue alert stage")
        evidence.append({"type": "fatigue_stage", "value": stage, "detail": "Elevated fatigue"})

    perclos = float(d.get("perclos", 0.0))
    if perclos >= 40:
        perc_contrib = 50.0
        reasons.append(f"PERCLOS high ({perclos:.0f}% of window)")
        evidence.append({"type": "perclos", "value": perclos, "detail": "High PERCLOS"})
    elif perclos >= 25:
        perc_contrib = 28.0
        reasons.append(f"PERCLOS elevated ({perclos:.0f}%)")
        evidence.append({"type": "perclos", "value": perclos, "detail": "Elevated PERCLOS"})
    else:
        perc_contrib = 0.0

    lt = float(d.get("fatigue_lt", 0.0))
    lt_contrib = _clamp(100 * (lt - 40) / 60, 0, 100) * 0.5 if lt > 40 else 0.0
    st = float(d.get("fatigue_st", 0.0))
    st_contrib = _clamp(100 * (st - 50) / 50, 0, 100) * 0.4 if st > 50 else 0.0

    ear_threshold = float(detection.get("ear_threshold", 0.23))
    ear = float(d.get("ear", 0.30))
    if ear < ear_threshold:
        ear_contrib = _clamp(100 * (ear_threshold - ear) / ear_threshold, 0, 100) * 0.6
        reasons.append(f"EAR below threshold ({ear:.2f} < {ear_threshold})")
        evidence.append({"type": "ear", "value": ear, "threshold": ear_threshold, "detail": "Low EAR"})
    else:
        ear_contrib = 0.0

    closed_sec = float(d.get("closed_sec", 0.0))
    if closed_sec >= float(detection.get("eye_closed_duration", 1.3)):
        closed_contrib = _clamp(100 * closed_sec / float(detection.get("eye_closed_duration", 1.3)) / 4, 0, 100)
        reasons.append(f"Eye-closure duration {closed_sec:.1f}s exceeds threshold")
        evidence.append({"type": "eye_closure", "value": closed_sec, "detail": "Extended eye closure"})
    else:
        closed_contrib = 0.0

    pitch = abs(float(d.get("head_pitch_deg", 0.0)))
    pitch_contrib = _clamp(100 * pitch / 20.0, 0, 100) * 0.4
    if pitch_contrib >= 50:
        reasons.append(f"Abnormal head pitch ({pitch:.0f} deg)")
        evidence.append({"type": "head_pitch", "value": pitch, "detail": "Abnormal head position"})

    score = _bounded(base, ear_contrib, closed_contrib, pitch_contrib,
                     stage_contrib, perc_contrib, lt_contrib, st_contrib)
    if state in ("DROWSY", "ATTENTION"):
        score = max(score, base)

    # Determine state
    if score >= 80:
        factor_state = "CRITICAL"
    elif score >= 60:
        factor_state = "HIGH"
    elif score >= 30:
        factor_state = "MODERATE"
    else:
        factor_state = "LOW"

    return FactorData(
        factor_name="driver",
        score=round(score, 1),
        state=factor_state,
        evidence=evidence[:4],
        source=source,
        data_quality="LIVE" if source == "LIVE DDS" else "SIMULATED",
        available=True,
        confidence=0.85 if source == "LIVE DDS" else 0.7,
    )


def _score_vehicle(vehicle, energy, wheels, tyre_target):
    """Health, anomaly, vibration, tyre pressure, energy remaining."""
    reasons = []
    evidence = []
    source = "UNKNOWN"
    available = False

    # Check if vehicle data is available
    if vehicle.get("health") is not None or vehicle.get("vibration") is not None:
        available = True
        source = "SIMULATION"

    if not available:
        return FactorData(
            factor_name="vehicle",
            score=0.0,
            state="UNKNOWN",
            evidence=["Vehicle health telemetry unavailable"],
            source="UNKNOWN",
            data_quality="NO_DATA",
            available=False,
        )

    health = (vehicle.get("health") or "NORMAL").upper()
    if health == "NORMAL":
        base = 8.0
    elif health == "WARNING":
        base = 40.0
        reasons.append(f"Vehicle warning: {vehicle.get('anomaly') or 'anomaly'}")
        evidence.append({"type": "vehicle_health", "value": health, "detail": vehicle.get('anomaly', 'Unknown anomaly')})
    else:  # INSPECTION REQUIRED / fault
        base = 72.0
        reasons.append(f"Vehicle needs inspection ({health})")
        evidence.append({"type": "vehicle_health", "value": health, "detail": "Inspection required"})

    vibration = float(vehicle.get("vibration", 0.0))
    vib = _clamp(100 * (vibration - 0.5) / 0.5, 0, 100) * 0.5
    if vib >= 45:
        reasons.append(f"High vibration ({vibration:.2f})")
        evidence.append({"type": "vibration", "value": vibration, "detail": "Elevated vibration"})

    out_of_range = [(i + 1, float(w)) for i, w in enumerate(wheels) if float(w) < 70 or float(w) > 95]
    tyre = _clamp(35 * len(out_of_range), 0, 100)
    if out_of_range:
        reasons.append(f"Tyre pressure out of range: {', '.join(f'#{i}' for i, _ in out_of_range)}")
        evidence.append({"type": "tyre_pressure", "value": [w for _, w in out_of_range], "detail": "Out of range tyres"})

    energy = energy or {"type": "DIESEL", "percent": 100}
    pct = float(energy.get("percent", 100))
    if pct <= (15 if energy.get("type") == "DIESEL" else 20):
        en = _clamp(100 * (25 - pct) / 25, 0, 100)
        reasons.append(f"{energy.get('type')} reserve low ({pct:.0f}%)")
        evidence.append({"type": "energy", "value": pct, "detail": f"Low {energy.get('type')} level"})
    else:
        en = 0.0

    score = round(_bounded(base, vib, tyre, en), 1)

    # Determine state
    if score >= 80:
        factor_state = "CRITICAL"
    elif score >= 60:
        factor_state = "HIGH"
    elif score >= 30:
        factor_state = "MODERATE"
    else:
        factor_state = "LOW"

    return FactorData(
        factor_name="vehicle",
        score=score,
        state=factor_state,
        evidence=evidence[:3],
        source=source,
        data_quality="SIMULATED",
        available=True,
        confidence=0.7,
    )


def _score_load(load):
    reasons = []
    evidence = []
    source = "UNKNOWN"
    available = False

    # Check if load data is available
    if load.get("load_pct") is not None or load.get("status") is not None:
        available = True
        source = "SIMULATION"

    if not available:
        return FactorData(
            factor_name="load",
            score=0.0,
            state="UNKNOWN",
            evidence=["Load data unavailable"],
            source="UNKNOWN",
            data_quality="NO_DATA",
            available=False,
        )

    pct = float(load.get("load_pct", 0))
    status = (load.get("status") or "NORMAL").upper()
    if status in ("CRITICAL OVERLOAD", "HIGH LOAD") or pct > 90:
        score = _clamp(100 * (pct - 70) / 30, 20, 100)
        reasons.append(f"Load at {pct:.0f}% of payload limit")
        evidence.append({"type": "load", "value": pct, "status": status, "detail": "Near/over capacity"})
    elif pct > 75:
        score = 32.0
        reasons.append(f"Load approaching limit ({pct:.0f}%)")
        evidence.append({"type": "load", "value": pct, "detail": "Approaching limit"})
    else:
        score = 6.0

    # Determine state
    if score >= 80:
        factor_state = "CRITICAL"
    elif score >= 60:
        factor_state = "HIGH"
    elif score >= 30:
        factor_state = "MODERATE"
    else:
        factor_state = "LOW"

    return FactorData(
        factor_name="load",
        score=round(score, 1),
        state=factor_state,
        evidence=evidence[:2],
        source=source,
        data_quality="SIMULATED",
        available=True,
        confidence=0.6,
    )


def _score_speed(speed_kmh):
    reasons = []
    evidence = []
    source = "UNKNOWN"
    available = False

    # Check if speed data is available
    if speed_kmh is not None:
        available = True
        source = "GPS"

    if not available:
        return FactorData(
            factor_name="speed",
            score=0.0,
            state="UNKNOWN",
            evidence=["Speed data unavailable"],
            source="UNKNOWN",
            data_quality="NO_DATA",
            available=False,
        )

    v = float(speed_kmh or 0)
    # thresholds reflect cautious city-bus operation
    if v >= 55:
        score = 75.0
        reasons.append(f"High speed {v:.0f} km/h")
        evidence.append({"type": "speed", "value": v, "detail": "Excessive speed"})
    elif v >= 45:
        score = 42.0
        reasons.append(f"Speeding {v:.0f} km/h")
        evidence.append({"type": "speed", "value": v, "detail": "Above limit"})
    elif v >= 35:
        score = 18.0
    else:
        score = 4.0

    # Determine state
    if score >= 80:
        factor_state = "CRITICAL"
    elif score >= 60:
        factor_state = "HIGH"
    elif score >= 30:
        factor_state = "MODERATE"
    else:
        factor_state = "LOW"

    return FactorData(
        factor_name="speed",
        score=round(score, 1),
        state=factor_state,
        evidence=evidence[:2],
        source=source,
        data_quality="GPS",
        available=True,
        confidence=0.9,
    )


def _score_occupancy(occupancy):
    reasons = []
    evidence = []
    source = "UNKNOWN"
    available = False

    # Check if occupancy data is available
    if occupancy and occupancy.get("pct") is not None:
        available = True
        source = "CABIN_CAMERA" if occupancy.get("source") == "cabin" else "SIMULATION"

    if not available:
        return FactorData(
            factor_name="occupancy",
            score=0.0,
            state="UNKNOWN",
            evidence=["Occupancy data unavailable"],
            source="UNKNOWN",
            data_quality="NO_DATA",
            available=False,
        )

    pct = float(occupancy.get("pct", 0))
    if pct >= 90:
        score = _clamp(100 * (pct - 60) / 40, 30, 100)
        reasons.append("Crowded - near/over seating+standing capacity")
        evidence.append({"type": "occupancy", "value": pct, "detail": "Critical crowding"})
    elif pct >= 75:
        score = 34.0
        reasons.append(f"Occupancy high ({pct:.0f}%)")
        evidence.append({"type": "occupancy", "value": pct, "detail": "High occupancy"})
    else:
        score = 5.0

    # Determine state
    if score >= 80:
        factor_state = "CRITICAL"
    elif score >= 60:
        factor_state = "HIGH"
    elif score >= 30:
        factor_state = "MODERATE"
    else:
        factor_state = "LOW"

    return FactorData(
        factor_name="occupancy",
        score=round(score, 1),
        state=factor_state,
        evidence=evidence[:2],
        source=source,
        data_quality="HEURISTIC" if source == "CABIN_CAMERA" else "SIMULATED",
        available=True,
        confidence=0.5 if source == "HEURISTIC" else 0.6,
    )


def _score_history(active_events, road_exposure=None):
    reasons = []
    evidence = []
    source = "EVENT_LOG"
    available = False

    # Check if we have event data
    if active_events:
        available = True

    if not available and not road_exposure:
        return FactorData(
            factor_name="history",
            score=0.0,
            state="UNKNOWN",
            evidence=["No historical event data available"],
            source="UNKNOWN",
            data_quality="NO_DATA",
            available=False,
        )

    score = 5.0
    if active_events:
        for e in active_events:
            score += HISTORY_SEVERITY.get(e.get("severity", "INFO"), 5)
        score = _clamp(score, 0, 100)
        n_crit = sum(1 for e in active_events if e.get("severity") == "CRITICAL")
        if n_crit:
            reasons.append(f"{n_crit} active critical event(s)")
            evidence.append({"type": "critical_events", "count": n_crit, "detail": "Active critical events"})
        n_warn = sum(1 for e in active_events if e.get("severity") == "WARNING")
        if n_warn:
            reasons.append(f"{n_warn} active warning(s)")
            evidence.append({"type": "warning_events", "count": n_warn, "detail": "Active warnings"})

    # Road exposure context
    if road_exposure:
        exposure_state = road_exposure.get("exposure_state", "CLEAR")
        if exposure_state == "EXPOSED":
            score = _clamp(score + 15.0, 0, 100)
            reasons.append(f"Exposure to road-hazard zone ({road_exposure.get('zone_risk_level', 'UNKNOWN')})")
            evidence.append({"type": "road_exposure", "value": exposure_state, "detail": road_exposure.get('zone_risk_level', 'Unknown')})
        elif exposure_state == "APPROACHING":
            score = _clamp(score + 8.0, 0, 100)
            reasons.append("Approaching road-risk zone")
            evidence.append({"type": "road_exposure", "value": exposure_state, "detail": "Approaching hazard zone"})

    # Determine state
    if score >= 80:
        factor_state = "CRITICAL"
    elif score >= 60:
        factor_state = "HIGH"
    elif score >= 30:
        factor_state = "MODERATE"
    else:
        factor_state = "LOW"

    return FactorData(
        factor_name="history",
        score=round(score, 1),
        state=factor_state,
        evidence=evidence[:3],
        source=source,
        data_quality="EVENT_LOG",
        available=True,
        confidence=0.75,
    )


# ---------------------------------------------------------------------------
# Cross-system evidence integration
# ---------------------------------------------------------------------------

def _gather_cross_system_evidence(bus, events):
    """Gather evidence from existing subsystems (DDS, vehicle health, road, ETA)."""
    evidence = []

    # DDS/Driver Safety evidence
    d = bus.get("driver") or {}
    if d.get("state") in ("DROWSY", "ATTENTION"):
        evidence.append({
            "system": "driver_safety",
            "type": "dds_state",
            "value": d.get("state"),
            "detail": f"Driver {d.get('state').lower()}",
            "source": "LIVE DDS" if d.get("data_source") == "live" else "SIMULATION",
        })

    # Vehicle health evidence
    vh = bus.get("vehicle") or {}
    if vh.get("health") in ("WARNING", "INSPECTION REQUIRED"):
        evidence.append({
            "system": "vehicle_health",
            "type": "health_state",
            "value": vh.get("health"),
            "detail": vh.get("anomaly", "Vehicle anomaly"),
            "source": "SIMULATION",
        })

    # Road exposure evidence
    road = bus.get("road_exposure") or {}
    if road.get("exposure_state") in ("EXPOSED", "APPROACHING"):
        evidence.append({
            "system": "road_intelligence",
            "type": "road_exposure",
            "value": road.get("exposure_state"),
            "detail": road.get("zone_risk_level", "Unknown zone"),
            "source": "ROAD_RISK_ENGINE",
        })

    # ETA/Delay evidence
    eta = bus.get("eta") or {}
    if eta.get("delay_summary") in ("SIGNIFICANT_DELAY", "SEVERE_DELAY"):
        evidence.append({
            "system": "eta_intelligence",
            "type": "delay",
            "value": eta.get("delay_summary"),
            "detail": f"Delay: {eta.get('delay_summary').replace('_', ' ').lower()}",
            "source": "ETA_ENGINE",
        })

    # Load/Overcrowding evidence
    load = bus.get("load") or {}
    if load.get("status") in ("CRITICAL OVERLOAD", "HIGH LOAD"):
        evidence.append({
            "system": "load_management",
            "type": "overload",
            "value": load.get("status"),
            "detail": f"Load at {load.get('load_pct', 0):.0f}%",
            "source": "SIMULATION",
        })

    return evidence


# ---------------------------------------------------------------------------
# Explainability functions
# ---------------------------------------------------------------------------

def _calculate_contributions(segments, weights):
    """Calculate how much each factor contributes to the overall score."""
    contributions = {}
    total_weight = sum(weights.values()) or 1.0

    for factor, factor_data in segments.items():
        weight = weights.get(factor, 0)
        contribution = (factor_data.score * weight) / total_weight
        contributions[factor] = {
            "score": factor_data.score,
            "weight": weight,
            "contribution": round(contribution, 2),
            "contribution_pct": round((contribution / 100) * 100, 1),
        }

    return contributions


def _get_top_contributors(contributions, limit=3):
    """Get the top contributing factors to risk."""
    sorted_factors = sorted(
        contributions.items(),
        key=lambda x: x[1]["contribution"],
        reverse=True
    )
    return [
        {"factor": factor, **data}
        for factor, data in sorted_factors[:limit]
        if data["contribution"] > 0
    ]


def _generate_explanation(segments, contributions, cross_evidence):
    """Generate human-readable explanation of risk factors."""
    explanations = []

    # Top contributors
    top = _get_top_contributors(contributions, limit=3)
    if top:
        explanations.append("Main risk contributors:")
        for i, item in enumerate(top, 1):
            explanations.append(f"{i}. {item['factor'].title()} — {item['contribution_pct']:.1f}% of total risk")

    # Cross-system context
    if cross_evidence:
        explanations.append("\nRelated system alerts:")
        for ev in cross_evidence[:3]:
            explanations.append(f"- {ev['system']}: {ev['detail']}")

    return explanations


# -----------------------------------------------------------------------
# Recommended actions (enhanced)
# ---------------------------------------------------------------------------

def recommended_actions(bus, segments):
    actions = []
    d = bus.get("driver") or {}
    state = (d.get("state") or "NORMAL").upper()

    if state in ("DROWSY", "ATTENTION"):
        actions.append("Issue cabin audio wake-up warning immediately")
        actions.append("Alert driver; plan rest stop at next major stop")
    if float(d.get("closed_sec", 0)) >= 1.3:
        actions.append("Request driver confirmation of alertness over intercom")
    if (d.get("fatigue_stage") or "").upper() == "CRITICAL":
        actions.append("Escalate to dispatch; consider relief driver")

    vh = bus.get("vehicle") or {}
    if (vh.get("health") or "NORMAL").upper() != "NORMAL":
        actions.append("Dispatch maintenance crew; inspect at next depot")
    if any(float(w) < 70 or float(w) > 95 for w in bus.get("wheels", [])):
        actions.append("Inflate/rectify tyre pressure at next stop")

    load = bus.get("load") or {}
    if float(load.get("load_pct", 0)) > 90:
        actions.append("Advise conductor to limit boarding at next stop")
        actions.append("Flag overload for dispatch review")

    energy = bus.get("energy") or {"type": "DIESEL", "percent": 100}
    low_limit = 15 if energy.get("type") == "DIESEL" else 20
    if float(energy.get("percent", 100)) <= low_limit:
        actions.append(f"Plan {energy.get('type')} refill/charge")

    if float(bus.get("speed_kmh", 0)) >= 45:
        actions.append("Advise driver to reduce speed")

    if float((bus.get("occupancy") or {}).get("pct", 0)) >= 90:
        actions.append("Consider relief bus to ease crowding")

    if segments.get("history", {}).get("score", 0) >= 60:
        actions.append("Prioritise review of recent incidents for this bus")

    # Road-related recommendations (contextual, not causal)
    road_reasons = []
    for r in segments.get("history", {}).get("reasons", []):
        if isinstance(r, dict):
            detail = r.get("detail", "")
            if "road" in detail.lower() or "hazard" in detail.lower():
                road_reasons.append(r)
        elif isinstance(r, str):
            if "road" in r.lower() or "hazard" in r.lower():
                road_reasons.append(r)
    if road_reasons:
        actions.append("Alert driver to road-hazard zone ahead; reduce speed if needed")

    # de-dup, keep order, cap
    seen, out = set(), []
    for a in actions:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out[:5]


# ---------------------------------------------------------------------------
# Public API (Phase 15 Enhanced)
# ---------------------------------------------------------------------------

def bus_risk(bus, events=None, risk_weights=None, detection=None, road_exposure=None):
    """Compute the full risk record for one bus from its live state + events.

    Phase 15 Enhanced with:
    - Factor-level explainability
    - Data quality tracking
    - Risk trends
    - State transitions
    - Cross-system evidence

    road_exposure (optional): dict with road risk exposure info (from road_risk engine).
    Used as contextual signal — does NOT claim causation.
    """
    events = events or []
    active = [e for e in events if e.get("status") == "ACTIVE"]
    weights = dict(DEFAULT_RISK_WEIGHTS)
    if risk_weights:
        weights.update({k: max(0, float(v)) for k, v in risk_weights.items() if k in weights})
    detection = detection or {}

    # Score each factor with data quality tracking
    segs = {}
    segs["driver"] = _score_driver(bus.get("driver") or {}, detection)
    segs["vehicle"] = _score_vehicle(bus.get("vehicle") or {}, bus.get("energy"),
                                     bus.get("wheels") or [], detection.get("tyre_target_psi", 85))
    segs["load"] = _score_load(bus.get("load") or {})
    # Pass None explicitly if speed_kmh is not in the bus dict
    speed_val = bus.get("speed_kmh")
    segs["speed"] = _score_speed(speed_val)
    segs["occupancy"] = _score_occupancy(bus.get("occupancy") or {})
    segs["history"] = _score_history(active, road_exposure)

    # Calculate weighted total with normalized weights for available factors
    available_factors = [k for k, v in segs.items() if v.available]
    if available_factors:
        # Use normalized weights for available factors only
        available_weight_sum = sum(weights[k] for k in available_factors)
        if available_weight_sum > 0:
            score = sum(segs[k].score * weights[k] for k in available_factors) / available_weight_sum
        else:
            score = 0.0
    else:
        score = 0.0

    # Calculate data coverage
    total_factors = len(segs)
    available_count = len(available_factors)
    coverage = f"{available_count}/{total_factors}"

    # Calculate contributions
    contributions = _calculate_contributions(segs, weights)

    # Get top contributors
    top_contributors = _get_top_contributors(contributions, limit=3)

    # Gather cross-system evidence
    cross_evidence = _gather_cross_system_evidence(bus, events)

    # Generate explanation
    explanation = _generate_explanation(segs, contributions, cross_evidence)

    # Track state and get trend
    bus_id = bus.get("bus_id", "UNKNOWN")
    risk_level = level_for_score(score)
    state_changed, transition_info = _risk_tracker.update(bus_id, score, risk_level)
    trend = _risk_tracker.get_trend(bus_id)

    # Build segments dict for API response
    segments_dict = {}
    for k, factor_data in segs.items():
        segments_dict[k] = {
            "score": factor_data.score,
            "state": factor_data.state,
            "reasons": factor_data.evidence,  # Use evidence as reasons
            "weight": weights[k],
            "available": factor_data.available,
            "source": factor_data.source,
            "data_quality": factor_data.data_quality,
            "evidence": factor_data.evidence,
            "timestamp": factor_data.timestamp,
            "confidence": factor_data.confidence,
        }

    # Build reasons list from top contributors
    reasons = []
    for item in top_contributors:
        factor = item["factor"]
        factor_data = segs[factor]
        for ev in factor_data.evidence[:1]:
            reasons.append(f"{factor.title()}: {ev.get('detail', 'Elevated risk')}")

    # Determine overall data quality
    if available_count == total_factors:
        overall_quality = "COMPLETE"
    elif available_count >= total_factors - 1:
        overall_quality = "MOSTLY_COMPLETE"
    elif available_count >= total_factors // 2:
        overall_quality = "PARTIAL"
    else:
        overall_quality = "INSUFFICIENT"

    return {
        "bus_id": bus_id,
        "route": bus.get("route", ""),
        "reg_no": bus.get("reg_no", ""),
        "risk_score": round(_clamp(score), 1),
        "risk_level": risk_level,
        "risk_state": risk_level,  # Alias for clarity
        "segments": segments_dict,
        "reasons": reasons[:4],
        "recommended_actions": recommended_actions(bus, segments_dict),
        "weights": weights,
        "simulation": bus.get("simulation", True),
        "road_exposure": road_exposure.get("exposure_state") if road_exposure else None,
        "road_zone": road_exposure.get("nearby_zone_id") if road_exposure else None,
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Phase 15 additions
        "data_coverage": coverage,
        "data_quality": overall_quality,
        "available_factors": available_count,
        "total_factors": total_factors,
        "trend": trend,
        "contributions": contributions,
        "top_contributors": top_contributors,
        "cross_system_evidence": cross_evidence,
        "explanation": explanation,
        "state_transition": transition_info,
    }


def _segment_status(k, bus, score):
    if k == "driver":
        return (bus.get("driver") or {}).get("state", "NORMAL")
    if k == "vehicle":
        return (bus.get("vehicle") or {}).get("health", "NORMAL")
    if k == "load":
        return (bus.get("load") or {}).get("status", "NORMAL")
    if k == "occupancy":
        return (bus.get("occupancy") or {}).get("crowd", "NORMAL")
    if k == "speed":
        return "NORMAL" if score < 35 else "FAST"
    return "CLEAR" if score < 35 else "ACTIVE_EVENTS"


def _top_reasons(segments):
    out = []
    for k in ("driver", "history", "load", "vehicle", "speed", "occupancy"):
        for r in segments[k]["reasons"]:
            out.append(f"{k.title()}: {r}")
    return out[:4]


def fleet_risk(buses, events=None, risk_weights=None, detection=None):
    items = [bus_risk(b, events, risk_weights, detection) for b in buses]
    items.sort(key=lambda r: r["risk_score"], reverse=True)
    return items


def get_risk_history(bus_id, limit=None):
    """Get risk history for a bus."""
    return _risk_tracker.get_history(bus_id, limit)


def get_risk_trend(bus_id):
    """Get risk trend for a bus."""
    return _risk_tracker.get_trend(bus_id)


def get_risk_coverage(bus_id):
    """Get data coverage for a bus."""
    return _risk_tracker.get_coverage(bus_id)


if __name__ == "__main__":
    # quick self-check with a made-up bus
    import json
    sample = {
        "bus_id": "TEST-1", "route": "TEST", "reg_no": "TN-01-XX-0001",
        "speed_kmh": 52.0, "simulation": True,
        "driver": {"state": "DROWSY", "ear": 0.15, "closed_sec": 2.1, "head_pitch_deg": -8},
        "occupancy": {"pct": 86, "crowd": "HIGH"},
        "energy": {"type": "DIESEL", "percent": 12},
        "wheels": [82, 88, 66, 84],
        "load": {"load_pct": 82, "status": "NORMAL"},
        "vehicle": {"health": "WARNING", "anomaly": "coolant temp", "vibration": 0.6},
    }
    result = bus_risk(sample)
    print(json.dumps(result, indent=2))
