"""
explainability_engine.py
V2 Explainable AI Layer for the Control Centre.

Every important AI-generated event answers:
- WHAT? What was detected?
- WHY? Which signals caused the classification?
- CONFIDENCE / SCORE: Risk score (not fake AI confidence)
- WHAT NEXT? What action is recommended?

Produces structured explainability output for:
- Risk assessments
- Incident predictions
- Fleet decisions
- Emergency responses
- Demand forecasts

DATA CLASSIFICATION: RULE-BASED EXPLAINABILITY
"""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional


class ExplainabilityEngine:
    """
    Produces structured explainability output for all AI-generated events.

    Follows the WHAT / WHY / CONFIDENCE / WHAT NEXT framework.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def explain_risk(self, bus_id: str, risk_data: Dict) -> Dict:
        """Generate explainable risk assessment."""
        risk_score = risk_data.get("risk_score", 0)
        risk_level = risk_data.get("risk_level", "UNKNOWN")
        segments = risk_data.get("segments", {})
        top_contributors = risk_data.get("top_contributors", [])
        reasons = risk_data.get("reasons", [])
        trend = risk_data.get("trend", "UNKNOWN")

        # WHAT
        what = {
            "subject": f"Bus {bus_id}",
            "assessment": "Risk Assessment",
            "result": f"Risk Level: {risk_level} (Score: {risk_score}/100)",
            "trend": f"Trend: {trend}",
        }

        # WHY
        why_signals = []
        for contributor in top_contributors[:3]:
            factor = contributor.get("factor", "")
            pct = contributor.get("contribution_pct", 0)
            why_signals.append(f"{factor} contributes {pct}% of total risk")

        # Add segment breakdown
        segment_details = []
        for seg_name, seg_data in segments.items():
            if seg_data.get("available"):
                segment_details.append(
                    f"{seg_name}: {seg_data.get('score', 0)}/100 "
                    f"(weight: {seg_data.get('weight', 0)}%)"
                )

        why = {
            "primary_factors": why_signals,
            "segment_breakdown": segment_details,
            "reasons": reasons,
        }

        # CONFIDENCE / SCORE
        confidence = {
            "type": "RULE-BASED RISK SCORE",
            "score": risk_score,
            "level": risk_level,
            "note": "Score computed from weighted multi-segment analysis. "
                    "Not an ML model confidence value.",
            "data_quality": risk_data.get("data_coverage", "UNKNOWN"),
        }

        # WHAT NEXT
        actions = risk_data.get("recommended_actions", [])
        what_next = {
            "recommended_actions": actions,
            "primary_action": actions[0] if actions else "Continue monitoring",
            "escalation_required": risk_level in ("HIGH", "CRITICAL"),
        }

        return {
            "bus_id": bus_id,
            "what": what,
            "why": why,
            "confidence": confidence,
            "what_next": what_next,
            "explanation": self._build_plain_text(what, why, confidence, what_next),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def explain_incident_prediction(
        self, bus_id: str, prediction: Dict
    ) -> Dict:
        """Generate explainable incident prediction."""
        probability = prediction.get("incident_probability", 0)
        level = prediction.get("probability_level", "UNKNOWN")
        signals = prediction.get("signals", {})
        degraded = prediction.get("degraded_signals", [])
        factor_chain = prediction.get("factor_chain", [])
        lead_time = prediction.get("lead_time", {})

        # WHAT
        what = {
            "subject": f"Bus {bus_id}",
            "assessment": "Incident Probability Prediction",
            "result": f"Probability: {level} ({probability:.0f}%)",
            "lead_time": f"Estimated lead time: {lead_time.get('estimated_minutes', 'Unknown')} minutes",
        }

        # WHY
        why_signals = []
        for factor in factor_chain[:3]:
            why_signals.append(
                f"{factor['signal'].replace('_', ' ')}: "
                f"score {factor['score']:.0f}, "
                f"contribution {factor['contribution']:.1f}"
            )

        why = {
            "degraded_signals": [s.replace('_', ' ') for s in degraded],
            "primary_drivers": why_signals,
            "correlation_note": (
                f"{len(degraded)} signals degraded simultaneously "
                f"(correlation multiplier applied)"
                if len(degraded) >= 2 else "Single signal degradation"
            ),
        }

        # CONFIDENCE / SCORE
        confidence = {
            "type": "RULE-BASED PREDICTIVE SCORE",
            "score": probability,
            "level": level,
            "note": "Probability estimated from multi-signal correlation. "
                    "Not an ML model prediction. Heuristic rule-based layer.",
            "data_source": prediction.get("data_source", "RULE-BASED PREDICTIVE"),
        }

        # WHAT NEXT
        recs = prediction.get("recommendations", [])
        what_next = {
            "recommended_actions": [r.get("description", "") for r in recs],
            "primary_action": recs[0].get("description", "Monitor") if recs else "Continue monitoring",
            "lead_time_action": (
                "Immediate action required" if lead_time.get("category") == "IMMEDIATE"
                else f"Action within {lead_time.get('estimated_minutes', '?')} minutes"
            ),
        }

        return {
            "bus_id": bus_id,
            "what": what,
            "why": why,
            "confidence": confidence,
            "what_next": what_next,
            "explanation": self._build_plain_text(what, why, confidence, what_next),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def explain_decision(self, bus_id: str, decision: Dict) -> Dict:
        """Generate explainable decision intelligence."""
        event_summary = decision.get("event_summary", {})
        risk_assessment = decision.get("risk_assessment", {})
        prediction = decision.get("prediction", {})
        recommendation = decision.get("recommendation", {})

        # WHAT
        what = {
            "subject": f"Bus {bus_id}",
            "event": event_summary.get("type", "UNKNOWN"),
            "severity": event_summary.get("severity", "INFO"),
            "description": event_summary.get("description", ""),
        }

        # WHY
        context = decision.get("context", {})
        why = {
            "risk_factors": risk_assessment.get("contributing_factors", []),
            "context": {
                "driver": context.get("bus_state", {}).get("driver_state", "UNKNOWN"),
                "vehicle": context.get("bus_state", {}).get("vehicle_health", "UNKNOWN"),
                "risk_score": risk_assessment.get("bus_risk_score", 0),
                "incident_probability": risk_assessment.get("incident_probability", 0),
            },
        }

        # CONFIDENCE
        confidence = {
            "type": "RULE-BASED DECISION",
            "risk_score": risk_assessment.get("score", 0),
            "risk_level": risk_assessment.get("level", "UNKNOWN"),
            "note": "Decision generated from rule-based analysis of event, "
                    "risk, and contextual signals.",
        }

        # WHAT NEXT
        what_next = {
            "priority": recommendation.get("priority", "LOW"),
            "actions": recommendation.get("actions", []),
            "operator_guidance": recommendation.get("operator_guidance", ""),
            "resources": decision.get("response", {}).get("resources", []),
        }

        return {
            "bus_id": bus_id,
            "what": what,
            "why": why,
            "confidence": confidence,
            "what_next": what_next,
            "explanation": self._build_decision_text(what, why, confidence, what_next),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def explain_fleet_decision(self, fleet_analysis: Dict) -> Dict:
        """Generate explainable fleet-level decision summary."""
        summary = fleet_analysis.get("summary", {})
        priority_actions = fleet_analysis.get("priority_actions", [])

        # WHAT
        what = {
            "subject": "Fleet Operations",
            "assessment": "Fleet Decision Intelligence",
            "fleet_health": summary.get("fleet_health_score", 0),
            "status": summary.get("overall_status", "UNKNOWN"),
            "active_buses": summary.get("active_buses", 0),
        }

        # WHY
        why = {
            "total_actions": summary.get("total_actions", 0),
            "high_priority": summary.get("high_priority_actions", 0),
            "rebalancing_needed": summary.get("rebalancing_needed", False),
            "deployment_needed": summary.get("deployment_needed", False),
        }

        # CONFIDENCE
        confidence = {
            "type": "RULE-BASED FLEET ANALYSIS",
            "note": "Fleet decisions derived from aggregation of per-bus "
                    "risk, demand, and operational signals.",
        }

        # WHAT NEXT
        top_actions = priority_actions[:5]
        what_next = {
            "top_actions": [
                {
                    "action": a.get("action", a.get("reason", "")),
                    "priority": a.get("priority", "LOW"),
                    "type": a.get("type", "UNKNOWN"),
                }
                for a in top_actions
            ],
            "primary_recommendation": (
                top_actions[0].get("action", "Continue monitoring")
                if top_actions else "Fleet operating normally"
            ),
        }

        return {
            "what": what,
            "why": why,
            "confidence": confidence,
            "what_next": what_next,
            "explanation": self._build_fleet_text(what, why, confidence, what_next),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # ── Text builders ──

    def explain_event(self, event: Dict, bus: Dict = None,
                      fusion_data: Dict = None) -> Dict:
        """
        Generate explainable output for an individual event.

        Every AI-generated event answers:
        - WHAT happened?
        - WHY was it detected?
        - CONFIDENCE: How confident is the system?
        - WHAT NEXT: What should the operator do?

        This is the method used for individual event explainability
        shown on incident cards and alert feeds.
        """
        event_type = event.get("event_type", "UNKNOWN")
        severity = event.get("severity", "MEDIUM")
        confidence = event.get("confidence", 0.5)
        bus_id = event.get("bus_id", "UNKNOWN")
        lat = event.get("latitude")
        lon = event.get("longitude")
        sensor_source = event.get("sensor_source", "UNKNOWN")
        timestamp = event.get("timestamp", "")

        # WHAT — describe the detection
        event_descriptions = {
            "DRIVER_DROWSINESS": "Driver drowsiness detected",
            "DRIVER_ALERT": "Driver alert triggered",
            "POTHOLE": "Pothole detected on road",
            "CABIN_FIRE": "Fire detected in cabin",
            "CABIN_SMOKE": "Smoke detected in cabin",
            "OVERLOAD": "Vehicle overload detected",
            "VEHICLE_ANOMALY": "Vehicle anomaly detected",
            "CRASH": "Crash detected",
            "ROAD_DEFECT": "Road defect detected",
            "EMERGENCY_SIREN": "Emergency siren detected",
            "FUSED_TRAFFIC_EVENT": "Multi-source traffic event",
            "FUSED_SAFETY_EVENT": "Multi-source safety event",
            "FUSED_ROAD_EVENT": "Multi-source road event",
            "FUSED_EMERGENCY_EVENT": "Multi-source emergency event",
        }
        what_subject = event_descriptions.get(event_type, f"{event_type} event detected")
        what_result = f"{severity} severity {event_type} event"

        what = {
            "subject": what_subject,
            "assessment": f"Detected by {sensor_source}",
            "result": what_result,
            "bus_id": bus_id,
            "location": {"lat": lat, "lon": lon} if lat and lon else None,
            "timestamp": timestamp,
        }

        # WHY — evidence chain
        primary_factors = []
        evidence_chain = []

        # Source attribution
        if sensor_source:
            primary_factors.append(f"Detection source: {sensor_source}")
            evidence_chain.append({
                "step": 1,
                "source": sensor_source,
                "detection": event_type,
                "confidence": confidence,
            })

        # Bus context
        if bus:
            driver = bus.get("driver", {})
            vehicle = bus.get("vehicle", {})
            load = bus.get("load", {})

            if driver.get("state") in ("DROWSY", "ATTENTION"):
                primary_factors.append(f"Driver state: {driver['state']}")
                evidence_chain.append({
                    "step": len(evidence_chain) + 1,
                    "source": "driver_monitor",
                    "detection": f"Driver {driver['state']}",
                    "confidence": 0.88,
                })

            if vehicle.get("health") in ("WARNING", "INSPECTION REQUIRED"):
                primary_factors.append(f"Vehicle health: {vehicle['health']}")
                evidence_chain.append({
                    "step": len(evidence_chain) + 1,
                    "source": "vehicle_health",
                    "detection": vehicle['health'],
                    "confidence": 0.75,
                })

            if load.get("status") in ("HIGH LOAD", "CRITICAL OVERLOAD"):
                primary_factors.append(f"Load status: {load['status']}")
                evidence_chain.append({
                    "step": len(evidence_chain) + 1,
                    "source": "load_monitor",
                    "detection": load['status'],
                    "confidence": 0.85,
                })

        # Fusion data
        if fusion_data:
            source_count = fusion_data.get("source_count", 0)
            primary_factors.append(f"Corroborated by {source_count} independent sources")
            for src in fusion_data.get("sources", []):
                evidence_chain.append({
                    "step": len(evidence_chain) + 1,
                    "source": src.get("type"),
                    "detection": f"Source contribution (conf: {src.get('confidence', 0):.0%})",
                    "confidence": src.get("confidence", 0),
                })

        why = {
            "primary_factors": primary_factors,
            "evidence_chain": evidence_chain,
            "reasons": [f"Severity: {severity}", f"Source: {sensor_source}"],
        }

        # CONFIDENCE
        # Determine confidence type based on source
        if fusion_data and fusion_data.get("source_count", 0) > 1:
            conf_type = "MULTI-SOURCE FUSION"
            conf_note = f"High confidence: {fusion_data['source_count']} independent sources corroborate"
        elif "MODEL" in str(sensor_source).upper() or "YOLO" in str(sensor_source).upper():
            conf_type = "MODEL-BASED"
            conf_note = "Detection via trained ML model"
        elif "HEURISTIC" in str(sensor_source).upper():
            conf_type = "RULE-BASED"
            conf_note = "Detection via classical computer vision heuristic"
        else:
            conf_type = "RULE-BASED"
            conf_note = "Detection via engineered rules"

        # Confidence level
        if confidence >= 0.85:
            conf_level = "HIGH"
        elif confidence >= 0.65:
            conf_level = "MEDIUM"
        else:
            conf_level = "LOW"

        confidence_output = {
            "type": conf_type,
            "score": round(confidence, 3),
            "level": conf_level,
            "note": conf_note,
            "sources_used": len(evidence_chain),
        }

        # WHAT NEXT — recommended actions
        actions = []
        if severity == "CRITICAL":
            actions.append("Immediate operator attention required")
            actions.append("Consider dispatching emergency response")
        elif severity == "HIGH":
            actions.append("Review and acknowledge incident")
            actions.append("Assign operator for response")
        elif severity == "WARNING":
            actions.append("Monitor situation")
            actions.append("Acknowledge when ready")

        # Event-specific recommendations
        if event_type in ("CABIN_FIRE", "CABIN_SMOKE"):
            actions.append("Alert emergency services")
            actions.append("Initiate evacuation protocol")
        elif event_type == "DRIVER_DROWSINESS":
            actions.append("Dispatch driver relief")
            actions.append("Play audio warning to driver")
        elif event_type == "POTHOLE":
            actions.append("Schedule road maintenance")
            actions.append("Alert nearby buses")
        elif event_type in ("FUSED_TRAFFIC_EVENT", "FUSED_EMERGENCY_EVENT"):
            actions.append("Review all contributing sources")
            actions.append("Coordinate multi-asset response")

        what_next = {
            "actions": actions[:4],
            "primary_action": actions[0] if actions else "Monitor",
            "escalation_required": severity in ("CRITICAL", "HIGH"),
        }

        # Build plain text explanation
        explanation_parts = [
            f"{what_subject} at [{lat:.4f}, {lon:.4f}]" if lat and lon else what_subject,
            f"(confidence: {confidence:.0%})",
        ]
        if evidence_chain:
            sources = [e["source"] for e in evidence_chain[:3]]
            explanation_parts.append(f"Sources: {', '.join(sources)}")
        if actions:
            explanation_parts.append(f"Recommended: {actions[0]}")
        explanation = " ".join(explanation_parts)

        return {
            "event_id": event.get("event_id"),
            "what": what,
            "why": why,
            "confidence": confidence_output,
            "what_next": what_next,
            "explanation": explanation,
            "timestamp": timestamp,
        }

    # ── Text builders ──

    def _build_plain_text(self, what, why, confidence, what_next) -> str:
        """Build plain text explanation."""
        parts = []
        parts.append(f"WHAT: {what.get('subject', '')} — {what.get('result', '')}")

        if why.get("primary_factors"):
            parts.append(f"WHY: {'; '.join(why['primary_factors'][:3])}")

        parts.append(
            f"SCORE: {confidence.get('score', 0)}/100 "
            f"({confidence.get('type', 'RULE-BASED')})"
        )

        if what_next.get("recommended_actions"):
            parts.append(f"ACTION: {what_next['primary_action']}")

        return " | ".join(parts)

    def _build_decision_text(self, what, why, confidence, what_next) -> str:
        """Build plain text for decision explanation."""
        parts = []
        parts.append(
            f"EVENT: {what.get('event', '')} "
            f"(severity: {what.get('severity', '')})"
        )

        ctx = why.get("context", {})
        parts.append(
            f"CONTEXT: Driver={ctx.get('driver', '?')}, "
            f"Vehicle={ctx.get('vehicle', '?')}, "
            f"Risk={ctx.get('risk_score', 0)}"
        )

        parts.append(
            f"RISK: {confidence.get('risk_level', '?')} "
            f"(score {confidence.get('risk_score', 0)})"
        )

        if what_next.get("actions"):
            parts.append(f"RECOMMEND: {what_next['actions'][0]}")

        return " | ".join(parts)

    def _build_fleet_text(self, what, why, confidence, what_next) -> str:
        """Build plain text for fleet decision."""
        parts = []
        parts.append(
            f"FLEET STATUS: Health={what.get('fleet_health', 0)}/100, "
            f"Active={what.get('active_buses', 0)}"
        )
        parts.append(
            f"ACTIONS: {why.get('total_actions', 0)} total, "
            f"{why.get('high_priority', 0)} high priority"
        )
        parts.append(f"RECOMMEND: {what_next.get('primary_recommendation', '')}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
explainability_engine = ExplainabilityEngine()
