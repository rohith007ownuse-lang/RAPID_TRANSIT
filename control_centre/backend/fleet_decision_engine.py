"""
fleet_decision_engine.py
V2 Intelligent Fleet Management Decision Engine.

Provides fleet-level decision intelligence:
- Fleet rebalancing recommendations
- Additional bus deployment suggestions
- Route adjustment recommendations
- Bus holding / spacing optimization
- Congestion-aware routing
- High-demand response coordination
- High-risk route intervention

Uses existing simulation data + traffic patterns + demand forecasts.
Clearly labels all recommendations as RULE-BASED / HEURISTIC.

DATA CLASSIFICATION: RULE-BASED DECISION LAYER
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import math


class FleetDecisionEngine:
    """
    Fleet-level decision intelligence engine.

    Analyzes fleet state, demand patterns, and operational conditions
    to generate actionable fleet management recommendations.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def analyze_fleet(
        self,
        buses: List[Dict],
        events: List[Dict] = None,
        risk_data: Dict = None,
        demand_data: Dict = None,
        eta_data: Dict = None,
        road_data: Dict = None,
    ) -> Dict:
        """
        Comprehensive fleet analysis with decision recommendations.

        Returns fleet health assessment, rebalancing suggestions,
        deployment recommendations, and route adjustments.
        """
        events = events or []
        risk_data = risk_data or {}
        demand_data = demand_data or {}
        eta_data = eta_data or {}
        road_data = road_data or {}

        # ── Fleet status analysis ──
        fleet_status = self._analyze_fleet_status(buses, events)

        # ── Rebalancing recommendations ──
        rebalancing = self._analyze_rebalancing_needs(
            buses, demand_data, eta_data
        )

        # ── Deployment recommendations ──
        deployment = self._analyze_deployment_needs(
            buses, demand_data, road_data
        )

        # ── Route adjustments ──
        route_adjustments = self._analyze_route_adjustments(
            buses, events, risk_data, eta_data, road_data
        )

        # ── Bus holding / spacing ──
        spacing = self._analyze_bus_spacing(buses, eta_data)

        # ── Congestion response ──
        congestion_response = self._analyze_congestion_response(
            buses, road_data, demand_data
        )

        # ── High-risk route intervention ──
        risk_intervention = self._analyze_risk_intervention(
            buses, risk_data, road_data
        )

        # ── Priority actions ──
        priority_actions = self._compile_priority_actions(
            rebalancing, deployment, route_adjustments, spacing,
            congestion_response, risk_intervention
        )

        return {
            "fleet_status": fleet_status,
            "rebalancing": rebalancing,
            "deployment": deployment,
            "route_adjustments": route_adjustments,
            "bus_spacing": spacing,
            "congestion_response": congestion_response,
            "risk_intervention": risk_intervention,
            "priority_actions": priority_actions,
            "summary": self._build_summary(
                fleet_status, rebalancing, deployment, priority_actions
            ),
            "data_source": "RULE-BASED DECISION",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    @staticmethod
    def _bus_age_seconds(bus: Dict) -> Optional[float]:
        """Seconds since bus last_update; None if unknown/invalid.

        last_update may be an ISO timestamp string (simulator/WS) or an epoch
        float; tolerate both.
        """
        lu = bus.get("last_update")
        if not lu:
            return None
        try:
            ts = lu if isinstance(lu, (int, float)) else datetime.fromisoformat(str(lu)).timestamp()
            return datetime.now(timezone.utc).timestamp() - ts
        except (ValueError, TypeError):
            return None

    def _analyze_fleet_status(self, buses: List[Dict], events: List[Dict]) -> Dict:
        """Analyze overall fleet operational status."""
        total = len(buses)
        active = 0
        offline = 0
        high_risk = 0
        overloaded = 0
        low_fuel = 0
        fatigued = 0

        for bus in buses:
            # Active check (last_update may be an ISO timestamp string or epoch)
            age_s = self._bus_age_seconds(bus)
            if age_s is not None and age_s > 60:
                offline += 1
            else:
                active += 1

            # Risk
            risk_score = bus.get("risk", {}).get("score", 0)
            if risk_score >= 55:
                high_risk += 1

            # Load
            load = bus.get("load") or {}
            if load.get("load_pct", 0) > 95:
                overloaded += 1

            # Energy
            energy = bus.get("energy") or {}
            if energy.get("percent", 100) < 15:
                low_fuel += 1

            # Driver
            driver = bus.get("driver") or {}
            if driver.get("fatigue_stage") in ("CRITICAL", "FATIGUE"):
                fatigued += 1

        return {
            "total_buses": total,
            "active": active,
            "offline": offline,
            "high_risk_buses": high_risk,
            "overloaded_buses": overloaded,
            "low_fuel_buses": low_fuel,
            "fatigued_drivers": fatigued,
            "fleet_health_score": max(0, 100 - (high_risk * 5) - (overloaded * 4) - (fatigued * 6)),
        }

    def _analyze_rebalancing_needs(
        self,
        buses: List[Dict],
        demand_data: Dict,
        eta_data: Dict,
    ) -> Dict:
        """Analyze where fleet rebalancing is needed."""
        suggestions = []

        # Group buses by route
        route_buses = defaultdict(list)
        for bus in buses:
            route = bus.get("route_code", "unknown")
            route_buses[route].append(bus)

        # Check for routes with imbalanced supply
        for route_code, route_bus_list in route_buses.items():
            active_count = sum(
                1 for b in route_bus_list
                if (age := self._bus_age_seconds(b)) is not None and age < 60
            )
            avg_risk = sum(b.get("risk", {}).get("score", 0) for b in route_bus_list) / max(1, len(route_bus_list))
            avg_occ = sum((b.get("occupancy") or {}).get("pct", 0) for b in route_bus_list) / max(1, len(route_bus_list))

            # Overloaded route
            if avg_occ > 80 and active_count > 0:
                suggestions.append({
                    "type": "ADD_BUS",
                    "route": route_code,
                    "priority": "HIGH" if avg_occ > 90 else "MEDIUM",
                    "reason": f"Route {route_code}: Average occupancy {avg_occ:.0f}%",
                    "action": f"Deploy additional bus to route {route_code}",
                    "current_buses": active_count,
                    "avg_occupancy": round(avg_occ, 1),
                })

            # Underutilized route
            elif avg_occ < 20 and active_count > 2:
                suggestions.append({
                    "type": "REDUCE_BUSES",
                    "route": route_code,
                    "priority": "LOW",
                    "reason": f"Route {route_code}: Average occupancy {avg_occ:.0f}% with {active_count} buses",
                    "action": f"Consider reducing buses on route {route_code}",
                    "current_buses": active_count,
                    "avg_occupancy": round(avg_occ, 1),
                })

            # High-risk route
            if avg_risk > 55:
                suggestions.append({
                    "type": "RISK_INTERVENTION",
                    "route": route_code,
                    "priority": "HIGH",
                    "reason": f"Route {route_code}: Average risk {avg_risk:.0f}",
                    "action": f"Review and potentially reassign buses from route {route_code}",
                    "current_buses": active_count,
                    "avg_risk": round(avg_risk, 1),
                })

        return {
            "suggestions": suggestions,
            "total_suggestions": len(suggestions),
        }

    def _analyze_deployment_needs(
        self,
        buses: List[Dict],
        demand_data: Dict,
        road_data: Dict,
    ) -> Dict:
        """Analyze where additional bus deployment is needed."""
        recommendations = []

        # Check demand patterns
        route_demand = demand_data.get("route_demand", {})
        for route_code, demand_info in route_demand.items():
            predicted = demand_info.get("predicted_demand", 0)
            current = demand_info.get("current_capacity", 0)

            if predicted > current * 0.9:
                recommendations.append({
                    "route": route_code,
                    "type": "DEMAND_RESPONSE",
                    "priority": "HIGH",
                    "reason": f"Predicted demand ({predicted}) exceeds available capacity ({current})",
                    "action": f"Deploy additional bus to route {route_code}",
                    "demand_deficit": predicted - current,
                })

        return {
            "recommendations": recommendations,
            "total": len(recommendations),
        }

    def _analyze_route_adjustments(
        self,
        buses: List[Dict],
        events: List[Dict],
        risk_data: Dict,
        eta_data: Dict,
        road_data: Dict,
    ) -> Dict:
        """Analyze where route adjustments are needed."""
        adjustments = []

        # Check for routes with severe delays
        route_eta = eta_data.get("route_summary", {})
        for route_code, eta_info in route_eta.items():
            delay_pct = eta_info.get("delayed_percentage", 0)
            if delay_pct > 40:
                adjustments.append({
                    "route": route_code,
                    "type": "DELAY_MITIGATION",
                    "priority": "HIGH",
                    "reason": f"Route {route_code}: {delay_pct:.0f}% of buses delayed",
                    "action": f"Consider express service or route deviation for route {route_code}",
                    "delayed_percentage": delay_pct,
                })

        # Check for road closures/hazards affecting routes
        road_zones = road_data.get("zones", [])
        for zone in road_zones:
            if zone.get("risk_level") in ("HIGH", "CRITICAL"):
                affected_routes = zone.get("affected_routes", [])
                for route in affected_routes:
                    adjustments.append({
                        "route": route,
                        "type": "ROAD_HAZARD_AVOIDANCE",
                        "priority": "HIGH",
                        "reason": f"High-risk road zone affecting route {route}",
                        "action": f"Evaluate diversion for route {route}",
                        "zone_risk": zone.get("risk_level"),
                    })

        return {
            "adjustments": adjustments,
            "total": len(adjustments),
        }

    def _analyze_bus_spacing(self, buses: List[Dict], eta_data: Dict) -> Dict:
        """Analyze bus spacing on routes for bus bunching detection."""
        issues = []

        # Group by route
        route_buses = defaultdict(list)
        for bus in buses:
            route = bus.get("route_code", "unknown")
            eta = bus.get("eta", {})
            progress = eta.get("route_progress_pct", 50)
            route_buses[route].append({
                "bus_id": bus.get("bus_id", ""),
                "progress": progress,
                "speed": bus.get("speed_kmh", 0),
            })

        for route_code, route_bus_list in route_buses.items():
            if len(route_bus_list) < 2:
                continue

            # Sort by progress
            sorted_buses = sorted(route_bus_list, key=lambda b: b["progress"])

            # Check for bunching (buses too close)
            for i in range(len(sorted_buses) - 1):
                gap = sorted_buses[i + 1]["progress"] - sorted_buses[i]["progress"]
                if gap < 5 and gap >= 0:  # Less than 5% apart
                    issues.append({
                        "route": route_code,
                        "type": "BUS_BUNCHING",
                        "priority": "MEDIUM",
                        "buses": [sorted_buses[i]["bus_id"], sorted_buses[i + 1]["bus_id"]],
                        "gap_pct": round(gap, 1),
                        "action": f"Hold bus {sorted_buses[i]['bus_id']} to restore spacing",
                    })

        return {
            "issues": issues,
            "total": len(issues),
        }

    def _analyze_congestion_response(
        self,
        buses: List[Dict],
        road_data: Dict,
        demand_data: Dict,
    ) -> Dict:
        """Analyze congestion and recommend responses."""
        responses = []

        # Check for congestion hotspots
        zones = road_data.get("zones", [])
        for zone in zones:
            if zone.get("detection_count", 0) > 5:
                responses.append({
                    "zone_id": zone.get("zone_id", ""),
                    "type": "CONGESTION_MANAGEMENT",
                    "priority": "MEDIUM",
                    "reason": f"High activity in zone: {zone.get('detection_count', 0)} detections",
                    "action": "Monitor for bus bunching, consider signal priority",
                    "detection_count": zone.get("detection_count", 0),
                })

        return {
            "responses": responses,
            "total": len(responses),
        }

    def _analyze_risk_intervention(
        self,
        buses: List[Dict],
        risk_data: Dict,
        road_data: Dict,
    ) -> Dict:
        """Analyze high-risk routes and recommend interventions."""
        interventions = []

        # Find high-risk buses
        for bus in buses:
            risk = bus.get("risk", {})
            risk_score = risk.get("score", 0)
            risk_level = risk.get("level", "LOW")

            if risk_level in ("HIGH", "CRITICAL"):
                interventions.append({
                    "bus_id": bus.get("bus_id", ""),
                    "route": bus.get("route_code", ""),
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "type": "RISK_INTERVENTION",
                    "priority": "HIGH" if risk_level == "CRITICAL" else "MEDIUM",
                    "action": f"Review bus {bus.get('bus_id', '')} and consider operational changes",
                    "reason": f"Bus {bus.get('bus_id', '')}: Risk {risk_score}/100 ({risk_level})",
                })

        return {
            "interventions": interventions,
            "total": len(interventions),
        }

    def _compile_priority_actions(
        self,
        rebalancing: Dict,
        deployment: Dict,
        route_adjustments: Dict,
        spacing: Dict,
        congestion_response: Dict,
        risk_intervention: Dict,
    ) -> List[Dict]:
        """Compile and rank all priority actions."""
        all_actions = []

        for s in rebalancing.get("suggestions", []):
            all_actions.append(s)
        for r in deployment.get("recommendations", []):
            all_actions.append(r)
        for a in route_adjustments.get("adjustments", []):
            all_actions.append(a)
        for i in spacing.get("issues", []):
            all_actions.append(i)
        for c in congestion_response.get("responses", []):
            all_actions.append(c)
        for ri in risk_intervention.get("interventions", []):
            all_actions.append(ri)

        # Sort by priority
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        all_actions.sort(key=lambda x: priority_order.get(x.get("priority", "LOW"), 2))

        return all_actions[:20]  # Top 20 actions

    def _build_summary(
        self,
        fleet_status: Dict,
        rebalancing: Dict,
        deployment: Dict,
        priority_actions: List[Dict],
    ) -> Dict:
        """Build executive summary."""
        high_priority = sum(1 for a in priority_actions if a.get("priority") == "HIGH")

        return {
            "fleet_health_score": fleet_status.get("fleet_health_score", 0),
            "active_buses": fleet_status.get("active", 0),
            "total_actions": len(priority_actions),
            "high_priority_actions": high_priority,
            "rebalancing_needed": rebalancing.get("total_suggestions", 0) > 0,
            "deployment_needed": deployment.get("total", 0) > 0,
            "overall_status": (
                "CRITICAL" if high_priority > 3
                else "WARNING" if high_priority > 0
                else "NORMAL"
            ),
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
fleet_decision_engine = FleetDecisionEngine()
