"""
route_intelligence.py
Route-Level Intelligence Engine.

Provides the vehicle -> route -> corridor -> hotspot -> city hierarchy
for operational intelligence. Computes per-route health, delay, risk,
demand pressure, and operational recommendations.

Produces:
- Per-route health score (0-100) with classification (GREEN/AMBER/RED/CRITICAL)
- Route delay index from ETA data
- Route risk index from road risk engine
- Route demand pressure from occupancy data
- Route incident count from incident store
- Operational recommendations per route
- City-level intelligence summary

DATA CLASSIFICATION: RULE-BASED INTELLIGENCE LAYER
"""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import defaultdict
from constants import SEVERITY_RANK, now_iso, parse_timestamp


# ---------------------------------------------------------------------------
# Route intelligence configuration
# ---------------------------------------------------------------------------

# Route health classification thresholds
ROUTE_HEALTH_THRESHOLDS = {
    "GREEN": (75, 100),
    "AMBER": (50, 74),
    "RED": (25, 49),
    "CRITICAL": (0, 24),
}

# Health score weights
HEALTH_WEIGHTS = {
    "vehicle_health": 0.25,
    "road_quality": 0.20,
    "incident_frequency": 0.20,
    "delay_index": 0.15,
    "demand_pressure": 0.10,
    "risk_exposure": 0.10,
}

# Severity to score impact
SEVERITY_IMPACT = {
    "CRITICAL": 30,
    "HIGH": 20,
    "WARNING": 10,
    "INFO": 2,
}


# ---------------------------------------------------------------------------
# Route Intelligence Engine
# ---------------------------------------------------------------------------

class RouteIntelligenceEngine:
    """
    Computes per-route intelligence from multiple data sources.

    Aggregates vehicle health, road quality, incidents, delays, demand,
    and risk into a unified route health score with recommendations.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._route_cache = {}
        self._cache_time = None
        self._cache_ttl = 60  # seconds

    def compute_route_intelligence(self, buses, events=None, incidents=None,
                                    eta_summary=None, road_defects=None,
                                    risk_zones=None, traffic_data=None,
                                    route_index=None):
        """
        Compute intelligence for all routes.

        Returns a dict of route_code -> route_intelligence.
        """
        now = datetime.now(timezone.utc)

        # Group buses by route
        route_buses = defaultdict(list)
        for bus in buses:
            route_code = bus.get("route_code")
            if route_code:
                route_buses[route_code].append(bus)

        # Group events by route
        route_events = defaultdict(list)
        for evt in (events or []):
            rc = evt.get("route_code")
            if rc:
                route_events[rc].append(evt)

        # Group incidents by route
        route_incidents = defaultdict(list)
        for inc in (incidents or []):
            rc = inc.get("route") or inc.get("route_code")
            if rc:
                route_incidents[rc].append(inc)

        # Build per-route intelligence
        result = {}
        for route_code, route_bus_list in route_buses.items():
            intel = self._compute_single_route(
                route_code=route_code,
                buses=route_bus_list,
                events=route_events.get(route_code, []),
                incidents=route_incidents.get(route_code, []),
                all_buses=buses,
                all_events=events or [],
                road_defects=road_defects,
                risk_zones=risk_zones,
                traffic_data=traffic_data,
                route_index=route_index,
                eta_summary=eta_summary,
            )
            result[route_code] = intel

        # Sort by health score (worst first)
        result = dict(sorted(result.items(), key=lambda x: x[1]["health_score"]))

        return result

    def _compute_single_route(self, route_code, buses, events, incidents,
                               all_buses, all_events, road_defects,
                               risk_zones, traffic_data, route_index,
                               eta_summary=None):
        """Compute intelligence for a single route."""

        # --- Vehicle health on route ---
        health_scores = []
        for bus in buses:
            vehicle = bus.get("vehicle", {})
            h = vehicle.get("health", "NORMAL")
            if h == "NORMAL":
                health_scores.append(90)
            elif h == "WARNING":
                health_scores.append(55)
            elif h == "INSPECTION REQUIRED":
                health_scores.append(25)
            else:
                health_scores.append(75)
        avg_vehicle_health = sum(health_scores) / len(health_scores) if health_scores else 75

        # --- Incident frequency on route ---
        incident_count = len(incidents)
        critical_incidents = sum(1 for i in incidents if i.get("severity") == "CRITICAL")
        high_incidents = sum(1 for i in incidents if i.get("severity") == "HIGH")
        incident_score = max(0, 100 - (incident_count * 15) - (critical_incidents * 25) - (high_incidents * 10))

        # --- Delay index from ETA data ---
        delay_index = 0
        if eta_summary:
            # Count buses with severe delays on this route
            severe_delays = 0
            for bus in buses:
                bid = bus.get("bus_id")
                # Check if bus has severe delay in summary
                if eta_summary.get("severe_delay_buses") and bid in eta_summary["severe_delay_buses"]:
                    severe_delays += 1
            if buses:
                delay_index = max(0, 100 - (severe_delays / len(buses) * 100))

        # --- Road quality on route ---
        road_score = 100
        if road_defects:
            route_defects = [d for d in road_defects
                           if route_code in (d.get("affected_routes") or [])
                           or route_code in str(d.get("route_code", ""))]
            road_score = max(0, 100 - len(route_defects) * 10)

        # --- Risk exposure from route index ---
        risk_score = 100
        if route_index and route_code in route_index:
            ri = route_index[route_code]
            level = ri.get("level", "LOW")
            if level == "CRITICAL":
                risk_score = 20
            elif level == "HIGH":
                risk_score = 40
            elif level == "MEDIUM":
                risk_score = 65
            else:
                risk_score = 90

        # --- Demand pressure from occupancy ---
        demand_pressure = 50  # default
        overloaded_buses = sum(1 for b in buses
                              if (b.get("load") or {}).get("status") in ("HIGH LOAD", "CRITICAL OVERLOAD"))
        if buses:
            demand_pressure = max(0, 100 - (overloaded_buses / len(buses) * 100))

        # --- Compute weighted health score ---
        health_score = (
            avg_vehicle_health * HEALTH_WEIGHTS["vehicle_health"] +
            road_score * HEALTH_WEIGHTS["road_quality"] +
            incident_score * HEALTH_WEIGHTS["incident_frequency"] +
            delay_index * HEALTH_WEIGHTS["delay_index"] +
            demand_pressure * HEALTH_WEIGHTS["demand_pressure"] +
            risk_score * HEALTH_WEIGHTS["risk_exposure"]
        )
        health_score = max(0, min(100, round(health_score)))

        # --- Classification ---
        classification = "GREEN"
        for cls, (low, high) in ROUTE_HEALTH_THRESHOLDS.items():
            if low <= health_score <= high:
                classification = cls
                break

        # --- Generate recommendations ---
        recommendations = self._generate_recommendations(
            route_code=route_code,
            buses=buses,
            health_score=health_score,
            classification=classification,
            incident_count=incident_count,
            critical_incidents=critical_incidents,
            overloaded_buses=overloaded_buses,
            road_score=road_score,
            risk_score=risk_score,
        )

        # --- Bus details for route ---
        bus_details = []
        for bus in buses:
            bus_details.append({
                "bus_id": bus.get("bus_id"),
                "health": (bus.get("vehicle") or {}).get("health", "UNKNOWN"),
                "speed_kmh": bus.get("speed_kmh", 0),
                "load_status": (bus.get("load") or {}).get("status", "NORMAL"),
                "occupancy_pct": (bus.get("occupancy") or {}).get("pct"),
                "driver_state": (bus.get("driver") or {}).get("state", "NORMAL"),
            })

        # --- Route name ---
        route_name = ""
        if buses:
            route_name = buses[0].get("route") or route_code

        return {
            "route_code": route_code,
            "route_name": route_name,
            "health_score": health_score,
            "classification": classification,
            "bus_count": len(buses),
            "metrics": {
                "vehicle_health": round(avg_vehicle_health, 1),
                "road_quality": round(road_score, 1),
                "incident_score": round(incident_score, 1),
                "delay_index": round(delay_index, 1),
                "demand_pressure": round(demand_pressure, 1),
                "risk_exposure": round(risk_score, 1),
            },
            "incidents": {
                "total": incident_count,
                "critical": critical_incidents,
                "high": high_incidents,
            },
            "overloaded_buses": overloaded_buses,
            "recommendations": recommendations,
            "buses": bus_details,
            "computed_at": now_iso(),
        }

    def _generate_recommendations(self, route_code, buses, health_score,
                                   classification, incident_count,
                                   critical_incidents, overloaded_buses,
                                   road_score, risk_score):
        """Generate operational recommendations for a route."""
        recs = []

        if classification == "CRITICAL":
            recs.append({
                "priority": "URGENT",
                "action": f"Immediate attention required for Route {route_code}",
                "detail": f"Health score {health_score}/100. Deploy relief buses and review road conditions.",
            })

        if critical_incidents > 0:
            recs.append({
                "priority": "HIGH",
                "action": f"{critical_incidents} critical incident(s) on this route",
                "detail": "Review and assign operators to resolve critical incidents.",
            })

        if overloaded_buses > 0:
            recs.append({
                "priority": "HIGH",
                "action": f"Deploy relief bus on Route {route_code}",
                "detail": f"{overloaded_buses} bus(es) overloaded. Increase frequency during peak demand.",
            })

        if road_score < 50:
            recs.append({
                "priority": "MEDIUM",
                "action": f"Reroute buses via alternative corridor — Route {route_code}",
                "detail": f"Road quality score {road_score}/100. Consider alternative routes.",
            })

        if risk_score < 50:
            recs.append({
                "priority": "MEDIUM",
                "action": f"Increase monitoring on Route {route_code}",
                "detail": f"Risk exposure {risk_score}/100. Assign additional oversight.",
            })

        if health_score >= 75 and not recs:
            recs.append({
                "priority": "LOW",
                "action": f"Route {route_code} operating normally",
                "detail": f"Health score {health_score}/100. No action required.",
            })

        return recs

    def get_city_overview(self, route_intelligence):
        """Generate city-level intelligence summary from all route data."""
        routes = list(route_intelligence.values())
        if not routes:
            return {
                "total_routes": 0,
                "classification_counts": {},
                "most_affected_routes": [],
                "total_buses": 0,
                "overall_health": 0,
            }

        # Classification counts
        class_counts = defaultdict(int)
        for r in routes:
            class_counts[r["classification"]] += 1

        # Most affected routes (lowest health)
        most_affected = [
            {"route_code": r["route_code"], "route_name": r["route_name"],
             "health_score": r["health_score"], "classification": r["classification"],
             "bus_count": r["bus_count"]}
            for r in routes[:5]
        ]

        # Overall fleet health
        total_buses = sum(r["bus_count"] for r in routes)
        overall_health = sum(r["health_score"] * r["bus_count"] for r in routes) / max(1, total_buses)

        # High-risk corridors
        high_risk = [r for r in routes if r["classification"] in ("RED", "CRITICAL")]

        return {
            "total_routes": len(routes),
            "classification_counts": dict(class_counts),
            "most_affected_routes": most_affected,
            "high_risk_corridors": [
                {"route_code": r["route_code"], "health_score": r["health_score"],
                 "recommendations": r["recommendations"][:2]}
                for r in high_risk[:3]
            ],
            "total_buses": total_buses,
            "overall_health": round(overall_health, 1),
            "computed_at": now_iso(),
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

route_intelligence_engine = RouteIntelligenceEngine()
