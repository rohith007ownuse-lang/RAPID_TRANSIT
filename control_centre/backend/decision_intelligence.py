"""
decision_intelligence.py
V2 Decision Intelligence Framework.

Provides the EVENT → CONTEXT → RISK → PREDICTION → RECOMMENDATION → RESPONSE
decision chain for every significant event.

For each event, generates:
- EVENT: What happened?
- CONTEXT: What other factors are relevant?
- RISK: How serious is it?
- PREDICTION: What could happen next?
- RECOMMENDATION: What should the operator do?
- RESPONSE: Which transportation/emergency resource should be involved?

DATA CLASSIFICATION: RULE-BASED DECISION LAYER
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

# Chennai IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


class DecisionIntelligence:
    """
    Produces structured decision intelligence for every significant event.

    Combines event data, risk assessments, incident predictions, and
    contextual information to generate actionable operator guidance.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def analyze_event(
        self,
        event: Dict,
        bus: Dict = None,
        risk_data: Dict = None,
        incident_prediction: Dict = None,
        road_data: Dict = None,
        emergency_context: Dict = None,
    ) -> Dict:
        """
        Generate full decision intelligence for a single event.

        Returns a structured decision packet with all six components.
        """
        bus = bus or {}
        risk_data = risk_data or {}
        incident_prediction = incident_prediction or {}
        road_data = road_data or {}
        emergency_context = emergency_context or {}

        bus_id = event.get("bus_id", bus.get("bus_id", "UNKNOWN"))
        event_type = event.get("event_type", "UNKNOWN")
        severity = event.get("severity", "INFO")

        # ── 1. EVENT: What happened? ──
        event_summary = self._summarize_event(event, bus)

        # ── 2. CONTEXT: What other factors are relevant? ──
        context = self._build_context(bus, event, risk_data, road_data)

        # ── 3. RISK: How serious is it? ──
        risk_assessment = self._assess_risk(
            event, bus, risk_data, incident_prediction
        )

        # ── 4. PREDICTION: What could happen next? ──
        prediction = self._predict_next(
            event, bus, risk_data, incident_prediction
        )

        # ── 5. RECOMMENDATION: What should the operator do? ──
        recommendation = self._generate_recommendation(
            event, bus, risk_assessment, prediction, context
        )

        # ── 6. RESPONSE: Which resources should be involved? ──
        response = self._determine_response(
            event, bus, risk_assessment, emergency_context
        )

        return {
            "bus_id": bus_id,
            "event_id": event.get("event_id", ""),
            "event_type": event_type,
            "event_summary": event_summary,
            "context": context,
            "risk_assessment": risk_assessment,
            "prediction": prediction,
            "recommendation": recommendation,
            "response": response,
            "data_source": "RULE-BASED DECISION",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def analyze_bus(self, bus: Dict, events: List[Dict] = None, **kwargs) -> Dict:
        """Generate decision intelligence summary for a bus."""
        events = events or []
        bus_id = bus.get("bus_id", "UNKNOWN")

        # Get recent events for this bus
        bus_events = [e for e in events if e.get("bus_id") == bus_id]
        recent_events = bus_events[:5]  # Last 5 events

        # Analyze each significant event
        analyses = []
        for event in recent_events:
            if event.get("severity") in ("HIGH", "CRITICAL", "MEDIUM"):
                analysis = self.analyze_event(event, bus, **kwargs)
                analyses.append(analysis)

        # Overall bus decision summary
        risk = kwargs.get("risk_data", {})
        prediction = kwargs.get("incident_prediction", {})

        return {
            "bus_id": bus_id,
            "total_events": len(bus_events),
            "recent_analyses": analyses,
            "overall_risk_level": risk.get("risk_level", "UNKNOWN"),
            "incident_probability": prediction.get("incident_probability", 0),
            "needs_attention": any(
                a["risk_assessment"].get("level") in ("HIGH", "CRITICAL")
                for a in analyses
            ),
            "top_recommendation": (
                analyses[0]["recommendation"] if analyses else None
            ),
            "data_source": "RULE-BASED DECISION",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # ── Component builders ──

    def _summarize_event(self, event: Dict, bus: Dict) -> Dict:
        """Build EVENT summary."""
        event_type = event.get("event_type", "UNKNOWN")
        severity = event.get("severity", "INFO")
        additional = event.get("additional_data") or {}

        descriptions = {
            "DRIVER_DROWSINESS": "Driver drowsiness detected via face tracking",
            "DRIVER_SAFETY_INCIDENT": "Driver safety incident reported",
            "CRASH": "Vehicle crash detected",
            "CABIN_FIRE": "Fire detected in bus cabin",
            "CABIN_SMOKE": "Smoke detected in bus cabin",
            "POTHOLE": "Road defect (pothole) detected",
            "ROAD_DEFECT": "Road defect identified",
            "OVERLOAD": "Vehicle overload condition detected",
            "EMERGENCY_SIREN": "Emergency siren detected nearby",
            "ETA_SEVERE_DELAY": "Severe delay detected on route",
            "RISK_ESCALATION": "Risk level escalated for bus",
            "VEHICLE_ANOMALY": "Vehicle anomaly detected",
            "OTHER_CC": "Control centre event",
        }

        return {
            "type": event_type,
            "severity": severity,
            "description": descriptions.get(event_type, f"Event: {event_type}"),
            "location": {
                "lat": event.get("latitude", 0),
                "lon": event.get("longitude", 0),
            },
            "bus_id": bus.get("bus_id", event.get("bus_id", "")),
            "route": bus.get("route", ""),
            "timestamp": event.get("timestamp", ""),
            "additional_info": additional,
        }

    def _build_context(
        self, bus: Dict, event: Dict, risk_data: Dict, road_data: Dict
    ) -> Dict:
        """Build CONTEXT — what other factors are relevant."""
        driver = bus.get("driver") or {}
        vehicle = bus.get("vehicle") or {}
        load = bus.get("load") or {}
        occ = bus.get("occupancy") or {}
        energy = bus.get("energy") or {}

        # Current bus state
        bus_state = {
            "speed_kmh": bus.get("speed_kmh", 0),
            "driver_state": driver.get("state", "UNKNOWN"),
            "fatigue_stage": driver.get("fatigue_stage", "UNKNOWN"),
            "vehicle_health": vehicle.get("health", "UNKNOWN"),
            "load_status": load.get("status", "UNKNOWN"),
            "occupancy_pct": occ.get("pct", 0),
            "energy_percent": energy.get("percent", 100),
        }

        # Risk context
        risk_context = {
            "risk_score": risk_data.get("risk_score", 0),
            "risk_level": risk_data.get("risk_level", "UNKNOWN"),
            "top_contributors": risk_data.get("top_contributors", []),
        }

        # Road context
        road_context = {
            "exposure_status": "UNKNOWN",
            "nearby_defects": 0,
        }

        # Temporal context (IST - Chennai timezone)
        now_ist = datetime.now(IST)
        hour = now_ist.hour
        if 7 <= hour <= 10:
            time_period = "MORNING_RUSH"
        elif 17 <= hour <= 20:
            time_period = "EVENING_RUSH"
        elif 22 <= hour or hour <= 5:
            time_period = "NIGHT"
        else:
            time_period = "OFF_PEAK"

        return {
            "bus_state": bus_state,
            "risk_context": risk_context,
            "road_context": road_context,
            "temporal_context": time_period,
            "active_events_on_bus": sum(
                1 for e in (bus.get("recent_events") or [])
                if e.get("status") == "ACTIVE"
            ),
        }

    def _assess_risk(
        self,
        event: Dict,
        bus: Dict,
        risk_data: Dict,
        incident_prediction: Dict,
    ) -> Dict:
        """Assess how serious the situation is."""
        severity = event.get("severity", "INFO")
        risk_score = risk_data.get("risk_score", 0)
        incident_prob = incident_prediction.get("incident_probability", 0)

        # Combined risk assessment
        base_risk = {"INFO": 10, "LOW": 25, "MEDIUM": 50, "HIGH": 75, "CRITICAL": 90}
        event_risk = base_risk.get(severity, 25)

        # Weighted combination
        combined = (event_risk * 0.4) + (risk_score * 0.35) + (incident_prob * 0.25)

        # Determine level
        if combined >= 80:
            level = "CRITICAL"
        elif combined >= 55:
            level = "HIGH"
        elif combined >= 30:
            level = "MEDIUM"
        else:
            level = "LOW"

        # Contributing factors
        factors = []
        if event_risk >= 50:
            factors.append(f"Event severity: {severity}")
        if risk_score >= 50:
            factors.append(f"Bus risk score: {risk_score}")
        if incident_prob >= 50:
            factors.append(f"Incident probability: {incident_prob:.0f}%")

        return {
            "score": round(combined, 1),
            "level": level,
            "event_severity": severity,
            "bus_risk_score": risk_score,
            "incident_probability": incident_prob,
            "contributing_factors": factors,
            "escalation_required": level in ("HIGH", "CRITICAL"),
        }

    def _predict_next(
        self,
        event: Dict,
        bus: Dict,
        risk_data: Dict,
        incident_prediction: Dict,
    ) -> Dict:
        """Predict what could happen next."""
        event_type = event.get("event_type", "")
        severity = event.get("severity", "INFO")
        risk_level = risk_data.get("risk_level", "LOW")
        incident_prob = incident_prediction.get("incident_probability", 0)

        scenarios = []
        timeframe = "30 minutes"

        # Event-type-specific predictions
        if event_type == "DRIVER_DROWSINESS":
            if severity in ("HIGH", "CRITICAL"):
                scenarios.append({
                    "scenario": "Accident due to driver inattention",
                    "probability": "HIGH" if incident_prob > 70 else "MEDIUM",
                    "timeframe": "15-30 minutes",
                })
            scenarios.append({
                "scenario": "Further fatigue degradation",
                "probability": "HIGH",
                "timeframe": "10-20 minutes",
            })

        elif event_type in ("CRASH", "CABIN_FIRE"):
            scenarios.append({
                "scenario": "Passenger injuries requiring medical response",
                "probability": "HIGH",
                "timeframe": "IMMEDIATE",
            })
            scenarios.append({
                "scenario": "Secondary incidents from road obstruction",
                "probability": "MEDIUM",
                "timeframe": "5-15 minutes",
            })

        elif event_type == "POTHOLE":
            if risk_level in ("HIGH", "CRITICAL"):
                scenarios.append({
                    "scenario": "Vehicle damage from road defect",
                    "probability": "MEDIUM",
                    "timeframe": "5-10 minutes",
                })

        elif event_type == "OVERLOAD":
            scenarios.append({
                "scenario": "Structural stress or passenger safety risk",
                "probability": "MEDIUM",
                "timeframe": "15-30 minutes",
            })

        # General escalation prediction
        if incident_prob > 60:
            scenarios.append({
                "scenario": "Incident probability elevated — multiple signals degraded",
                "probability": "HIGH",
                "timeframe": "15-30 minutes",
            })

        if not scenarios:
            scenarios.append({
                "scenario": "Situation stable — monitor for changes",
                "probability": "LOW",
                "timeframe": "30+ minutes",
            })

        return {
            "scenarios": scenarios,
            "primary_scenario": scenarios[0] if scenarios else None,
            "timeframe": timeframe,
        }

    def _generate_recommendation(
        self,
        event: Dict,
        bus: Dict,
        risk_assessment: Dict,
        prediction: Dict,
        context: Dict,
    ) -> Dict:
        """Generate operator recommendation."""
        event_type = event.get("event_type", "")
        risk_level = risk_assessment.get("level", "LOW")
        bus_id = bus.get("bus_id", "")

        actions = []
        priority = "LOW"

        # Risk-based actions
        if risk_level == "CRITICAL":
            priority = "CRITICAL"
            actions.append(f"IMMEDIATE: Review bus {bus_id} situation")
            actions.append("Consider emergency intervention")
        elif risk_level == "HIGH":
            priority = "HIGH"
            actions.append(f"Review bus {bus_id} status")
            actions.append("Prepare contingency response")

        # Event-specific actions
        if event_type == "DRIVER_DROWSINESS":
            actions.append("Arrange driver relief at next stop")
            if risk_level in ("HIGH", "CRITICAL"):
                actions.append("Deploy backup bus if available")

        elif event_type in ("CRASH", "CABIN_FIRE"):
            actions.append("Notify emergency services")
            actions.append("Activate emergency response protocol")
            actions.append("Reroute nearby buses")

        elif event_type == "POTHOLE":
            actions.append("Log road defect for maintenance")
            actions.append("Alert buses on same route")

        elif event_type == "OVERLOAD":
            actions.append("Limit boarding at next stops")
            actions.append("Deploy relief bus")

        elif event_type == "ETA_SEVERE_DELAY":
            actions.append("Evaluate route deviation")
            actions.append("Notify affected passengers")

        # Check for alternative bus
        alternative = self._find_alternative_bus(bus, context)
        if alternative:
            actions.append(f"Alternative bus available: {alternative}")

        return {
            "priority": priority,
            "actions": actions,
            "primary_action": actions[0] if actions else "Monitor situation",
            "operator_guidance": self._build_operator_guidance(
                bus_id, event_type, risk_level, actions
            ),
        }

    def _determine_response(
        self,
        event: Dict,
        bus: Dict,
        risk_assessment: Dict,
        emergency_context: Dict,
    ) -> Dict:
        """Determine which resources should be involved."""
        event_type = event.get("event_type", "")
        risk_level = risk_assessment.get("level", "LOW")
        severity = event.get("severity", "INFO")

        resources = []

        # Emergency services
        if event_type in ("CRASH", "CABIN_FIRE", "CABIN_SMOKE", "EMERGENCY_SIREN"):
            if severity in ("HIGH", "CRITICAL"):
                resources.append({
                    "type": "HOSPITAL",
                    "reason": "Potential medical emergency",
                    "priority": "HIGH",
                })
                resources.append({
                    "type": "FIRE_STATION",
                    "reason": "Fire/rescue response",
                    "priority": "HIGH",
                })
            resources.append({
                "type": "POLICE",
                "reason": "Incident documentation",
                "priority": "MEDIUM",
            })

        elif event_type == "DRIVER_DROWSINESS":
            if risk_level in ("HIGH", "CRITICAL"):
                resources.append({
                    "type": "DISPATCH",
                    "reason": "Driver relief coordination",
                    "priority": "HIGH",
                })

        elif event_type == "OVERLOAD":
            resources.append({
                "type": "DISPATCH",
                "reason": "Relief bus deployment",
                "priority": "MEDIUM",
            })

        # Always include dispatch for high-risk
        if risk_level in ("HIGH", "CRITICAL"):
            has_dispatch = any(r["type"] == "DISPATCH" for r in resources)
            if not has_dispatch:
                resources.append({
                    "type": "DISPATCH",
                    "reason": "Operational coordination",
                    "priority": "MEDIUM",
                })

        return {
            "resources": resources,
            "emergency_services_required": any(
                r["type"] in ("HOSPITAL", "FIRE_STATION", "POLICE")
                for r in resources
            ),
            "nearest_facilities": emergency_context.get("nearest_facilities", []),
        }

    def _find_alternative_bus(self, bus: Dict, context: Dict) -> Optional[str]:
        """Find an alternative bus that could cover this bus's route."""
        from data_store import store

        route_code = bus.get("route_code", "")
        if not route_code:
            return None

        buses = store.get_buses()
        for b in buses:
            if b.get("bus_id") == bus.get("bus_id"):
                continue
            if b.get("route_code") == route_code:
                b_risk = b.get("risk", {}).get("score", 0)
                b_occ = (b.get("occupancy") or {}).get("pct", 0)
                if b_risk < 40 and b_occ < 70:
                    return b.get("bus_id")

        return None

    def _build_operator_guidance(
        self, bus_id: str, event_type: str, risk_level: str, actions: List[str]
    ) -> str:
        """Build human-readable operator guidance."""
        if risk_level == "CRITICAL":
            return (
                f"CRITICAL: Bus {bus_id} requires immediate attention. "
                f"Event: {event_type}. "
                f"{'; '.join(actions[:2])}. "
                f"Escalate to supervisor if not resolved within 5 minutes."
            )
        elif risk_level == "HIGH":
            return (
                f"HIGH PRIORITY: Bus {bus_id} needs operator review. "
                f"Event: {event_type}. "
                f"{'; '.join(actions[:2])}."
            )
        else:
            return (
                f"Bus {bus_id}: {event_type} detected. "
                f"{'; '.join(actions[:2]) if actions else 'Monitor situation.'}"
            )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
decision_intelligence = DecisionIntelligence()
