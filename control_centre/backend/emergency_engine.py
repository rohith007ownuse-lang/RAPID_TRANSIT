"""
emergency_engine.py
Emergency Response Intelligence Engine for Rapid Transit.

Computes nearby emergency facilities for incident locations, ranks them
by distance and relevance, and connects incidents to the MTC transport network.

Uses haversine distance (no road network assumption).
"""

import threading
from typing import Dict, List, Optional, Tuple
from math import radians, sin, cos, sqrt, asin

from emergency_data import emergency_store


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km between two lat/lon points."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


# Incident type -> which facility categories are relevant and their priority
INCIDENT_FACILITY_MAP = {
    "ACCIDENT": {
        "hospital": {"priority": 1, "reason": "Medical response for injuries"},
        "fire": {"priority": 2, "reason": "Rescue / extrication if severe"},
        "police": {"priority": 3, "reason": "Incident report / traffic control"},
        "traffic_police": {"priority": 4, "reason": "Traffic management on corridor"},
    },
    "CRASH": {
        "hospital": {"priority": 1, "reason": "Medical response for injuries"},
        "fire": {"priority": 2, "reason": "Rescue / extrication"},
        "police": {"priority": 3, "reason": "Incident report"},
        "traffic_police": {"priority": 4, "reason": "Traffic diversion"},
    },
    "FIRE": {
        "fire": {"priority": 1, "reason": "Fire suppression / rescue"},
        "hospital": {"priority": 2, "reason": "Burns / smoke inhalation treatment"},
        "police": {"priority": 3, "reason": "Perimeter / crowd control"},
        "traffic_police": {"priority": 4, "reason": "Road closure management"},
    },
    "MEDICAL_EMERGENCY": {
        "hospital": {"priority": 1, "reason": "Emergency medical treatment"},
    },
    "CABIN_FIRE": {
        "fire": {"priority": 1, "reason": "Fire response for bus cabin fire"},
        "hospital": {"priority": 2, "reason": "Smoke inhalation / burns treatment"},
        "police": {"priority": 3, "reason": "Incident investigation"},
    },
    "CABIN_SMOKE": {
        "fire": {"priority": 1, "reason": "Investigate smoke source"},
        "hospital": {"priority": 2, "reason": "Smoke inhalation if needed"},
    },
    "ROAD_OBSTRUCTION": {
        "police": {"priority": 1, "reason": "Road clearance / diversion"},
        "traffic_police": {"priority": 2, "reason": "Traffic rerouting"},
    },
    "VEHICLE_BREAKDOWN": {
        "traffic_police": {"priority": 1, "reason": "Lane management / tow coordination"},
    },
    "TRAFFIC_INCIDENT": {
        "traffic_police": {"priority": 1, "reason": "Traffic control and management"},
        "police": {"priority": 2, "reason": "Incident documentation"},
    },
    "DRIVER_DROWSINESS": {
        "police": {"priority": 1, "reason": "Driver safety incident"},
    },
    "DRIVER_SAFETY_INCIDENT": {
        "police": {"priority": 1, "reason": "Driver safety investigation"},
    },
    "OVERLOAD": {
        "traffic_police": {"priority": 1, "reason": "Overloading violation"},
    },
    "EMERGENCY_SIREN": {
        "police": {"priority": 1, "reason": "Investigate emergency situation"},
        "hospital": {"priority": 2, "reason": "Standby for potential medical need"},
    },
}


class EmergencyResponseEngine:
    """Computes emergency response recommendations for incidents."""

    def __init__(self):
        self._lock = threading.Lock()

    def nearby_facilities(
        self,
        lat: float,
        lon: float,
        facility_type: Optional[str] = None,
        max_results: int = 5,
        max_distance_km: float = 25.0,
    ) -> Dict:
        """Find nearest emergency facilities to a GPS coordinate.

        Args:
            lat, lon: Incident/location coordinates
            facility_type: Filter by "hospital", "fire", "police", "traffic_police", or None for all
            max_results: Max results per category
            max_distance_km: Maximum search radius

        Returns:
            Dict with facilities grouped by category, each sorted by distance
        """
        facilities = emergency_store.get_all(facility_type)
        result = {}

        if facility_type:
            result[facility_type] = self._rank_nearby(
                facilities, lat, lon, max_results, max_distance_km
            )
        else:
            # Group by category
            for cat in ["hospital", "fire", "police", "traffic_police"]:
                cat_facilities = [f for f in facilities if self._facility_category(f) == cat]
                ranked = self._rank_nearby(cat_facilities, lat, lon, max_results, max_distance_km)
                if ranked:
                    result[cat] = ranked

        return result

    def incident_response(
        self,
        incident_type: str,
        lat: float,
        lon: float,
        severity: str = "MEDIUM",
        affected_routes: Optional[List[str]] = None,
        affected_buses: Optional[List[str]] = None,
    ) -> Dict:
        """Generate emergency response recommendation for an incident.

        Returns comprehensive response plan with nearest facilities per category,
        emergency contacts, affected transport info, and operator recommendations.
        """
        incident_upper = incident_type.upper().replace(" ", "_")
        facility_map = INCIDENT_FACILITY_MAP.get(incident_upper, {
            "hospital": {"priority": 1, "reason": "Standby for medical needs"},
            "police": {"priority": 2, "reason": "Incident documentation"},
        })

        # Find nearest facilities for each relevant category
        response_facilities = {}
        for cat, info in sorted(facility_map.items(), key=lambda x: x[1]["priority"]):
            facilities = emergency_store.get_all(cat)
            ranked = self._rank_nearby(facilities, lat, lon, 3, 25.0)
            if ranked:
                nearest = ranked[0]
                response_facilities[cat] = {
                    "priority": info["priority"],
                    "reason": info["reason"],
                    "nearest": nearest,
                    "alternatives": ranked[1:] if len(ranked) > 1 else [],
                    "all_within_range": ranked,
                }

        # Emergency contacts
        contacts = emergency_store.get_contacts()

        # Build operator recommendations
        recommendations = self._build_recommendations(
            incident_upper, severity, response_facilities,
            affected_routes, affected_buses
        )

        return {
            "incident_type": incident_upper,
            "severity": severity,
            "location": {"lat": lat, "lon": lon},
            "facilities": response_facilities,
            "emergency_contacts": contacts,
            "affected_routes": affected_routes or [],
            "affected_buses": affected_buses or [],
            "recommendations": recommendations,
            "distance_note": "Distances are straight-line (haversine). Actual response time depends on road network and traffic.",
        }

    def find_affected_routes(
        self,
        lat: float,
        lon: float,
        buses: List[Dict],
        radius_km: float = 3.0,
    ) -> Dict:
        """Find MTC routes and buses affected by an incident at the given location.

        Returns routes and buses within radius_km of the incident.
        """
        affected_routes = set()
        affected_buses = []
        nearby_stops = []

        for bus in buses:
            bus_lat = bus.get("latitude")
            bus_lon = bus.get("longitude")
            if bus_lat is None or bus_lon is None:
                continue
            dist = _haversine_km(lat, lon, bus_lat, bus_lon)
            if dist <= radius_km:
                route_code = bus.get("route_code", "")
                if route_code:
                    affected_routes.add(route_code)
                affected_buses.append({
                    "bus_id": bus.get("bus_id", ""),
                    "route_code": route_code,
                    "route": bus.get("route", ""),
                    "distance_km": round(dist, 2),
                    "speed_kmh": bus.get("speed_kmh", 0),
                })

        # Sort buses by distance
        affected_buses.sort(key=lambda b: b["distance_km"])

        return {
            "affected_routes": sorted(affected_routes),
            "affected_buses": affected_buses,
            "bus_count": len(affected_buses),
            "route_count": len(affected_routes),
            "radius_km": radius_km,
        }

    def _rank_nearby(
        self,
        facilities: List[Dict],
        lat: float,
        lon: float,
        max_results: int,
        max_distance_km: float,
    ) -> List[Dict]:
        """Rank facilities by distance from a point."""
        ranked = []
        for f in facilities:
            f_lat = f.get("latitude")
            f_lon = f.get("longitude")
            if f_lat is None or f_lon is None:
                continue
            dist = _haversine_km(lat, lon, f_lat, f_lon)
            if dist <= max_distance_km:
                entry = dict(f)
                entry["distance_km"] = round(dist, 2)
                entry["distance_note"] = "straight-line"
                ranked.append(entry)

        ranked.sort(key=lambda x: x["distance_km"])
        return ranked[:max_results]

    def _facility_category(self, facility: Dict) -> str:
        """Determine the category of a facility."""
        ftype = facility.get("type", "").lower()
        if "hospital" in ftype or "medical" in ftype or "health" in ftype:
            return "hospital"
        elif "fire" in ftype:
            return "fire"
        elif "traffic" in ftype:
            return "traffic_police"
        elif "police" in ftype:
            return "police"
        return "other"

    def _build_recommendations(
        self,
        incident_type: str,
        severity: str,
        facilities: Dict,
        affected_routes: Optional[List[str]],
        affected_buses: Optional[List[str]],
    ) -> List[Dict]:
        """Build operator action recommendations."""
        recs = []

        # Type-specific recommendations
        if incident_type in ("ACCIDENT", "CRASH"):
            recs.append({"action": "Notify nearest hospital for potential casualties", "priority": "HIGH"})
            if severity in ("HIGH", "CRITICAL"):
                recs.append({"action": "Request fire/rescue for vehicle extrication", "priority": "HIGH"})
            recs.append({"action": "Notify police for incident report", "priority": "MEDIUM"})
            recs.append({"action": "Alert traffic police for corridor management", "priority": "MEDIUM"})

        elif incident_type in ("FIRE", "CABIN_FIRE"):
            recs.append({"action": "Notify fire station immediately", "priority": "HIGH"})
            recs.append({"action": "Evacuate passengers from affected bus", "priority": "HIGH"})
            recs.append({"action": "Notify nearby hospital for burn/smoke treatment", "priority": "HIGH"})
            recs.append({"action": "Alert police for perimeter control", "priority": "MEDIUM"})

        elif incident_type == "MEDICAL_EMERGENCY":
            recs.append({"action": "Dispatch ambulance / notify nearest hospital", "priority": "HIGH"})
            recs.append({"action": "Advise driver to proceed to nearest medical facility", "priority": "HIGH"})

        elif incident_type == "TRAFFIC_INCIDENT":
            recs.append({"action": "Alert traffic police for intersection management", "priority": "HIGH"})
            recs.append({"action": "Identify alternate routes for affected MTC services", "priority": "MEDIUM"})

        elif incident_type == "DRIVER_DROWSINESS":
            recs.append({"action": "Arrange driver relief at next stop", "priority": "HIGH"})
            recs.append({"action": "Deploy backup bus if available", "priority": "MEDIUM"})

        elif incident_type == "VEHICLE_BREAKDOWN":
            recs.append({"action": "Arrange tow vehicle", "priority": "HIGH"})
            recs.append({"action": "Deploy replacement bus for affected route", "priority": "MEDIUM"})
            recs.append({"action": "Notify traffic police for lane management", "priority": "LOW"})

        else:
            recs.append({"action": "Assess situation and determine response", "priority": "MEDIUM"})

        # Transport impact recommendations
        if affected_routes:
            recs.append({
                "action": f"Monitor affected MTC routes: {', '.join(affected_routes[:5])}",
                "priority": "MEDIUM",
            })
        if affected_buses and len(affected_buses) > 3:
            recs.append({
                "action": f"Alert {len(affected_buses)} buses in incident area to proceed with caution",
                "priority": "MEDIUM",
            })

        # Severity-based escalation
        if severity == "CRITICAL":
            recs.append({"action": "Escalate to control center supervisor immediately", "priority": "HIGH"})
            recs.append({"action": "Prepare public advisory for affected routes", "priority": "MEDIUM"})

        return recs

    def severity_response_plan(
        self,
        incident_type: str,
        severity: str,
        lat: float,
        lon: float,
    ) -> Dict:
        """Generate severity-based emergency response plan.

        Returns tiered response actions based on incident severity, with
        response time estimates and prioritized facility dispatch.

        DATA CLASSIFICATION: RULE-BASED (uses severity thresholds + distance estimates)
        """
        severity = severity.upper()
        incident_type = incident_type.upper().replace(" ", "_")

        # Severity-based response tiers
        severity_config = {
            "CRITICAL": {
                "response_time_target_min": 5,
                "dispatch_level": "IMMEDIATE",
                "facilities_to_dispatch": 3,
                "actions": [
                    "IMMEDIATE: Notify all emergency services",
                    "IMMEDIATE: Clear path for emergency vehicles",
                    "IMMEDIATE: Evacuate if fire/safety hazard",
                    "WITHIN 5 MIN: First responder arrival expected",
                    "WITHIN 10 MIN: Supervisor escalation if unresolved",
                ],
                "bus_dispatch": True,
                "public_advisory": True,
            },
            "HIGH": {
                "response_time_target_min": 10,
                "dispatch_level": "PRIORITY",
                "facilities_to_dispatch": 2,
                "actions": [
                    "PRIORITY: Notify primary emergency facility",
                    "PRIORITY: Alert nearby buses to avoid area",
                    "WITHIN 10 MIN: First responder arrival expected",
                    "WITHIN 15 MIN: Assess need for escalation",
                ],
                "bus_dispatch": True,
                "public_advisory": False,
            },
            "MEDIUM": {
                "response_time_target_min": 20,
                "dispatch_level": "STANDARD",
                "facilities_to_dispatch": 1,
                "actions": [
                    "STANDARD: Notify appropriate emergency facility",
                    "Monitor situation for escalation",
                    "WITHIN 20 MIN: Response expected",
                ],
                "bus_dispatch": False,
                "public_advisory": False,
            },
            "LOW": {
                "response_time_target_min": 30,
                "dispatch_level": "ROUTINE",
                "facilities_to_dispatch": 1,
                "actions": [
                    "ROUTINE: Log incident for follow-up",
                    "Monitor for any change in severity",
                ],
                "bus_dispatch": False,
                "public_advisory": False,
            },
        }

        config = severity_config.get(severity, severity_config["MEDIUM"])

        # Get facility map for this incident type
        facility_map = INCIDENT_FACILITY_MAP.get(incident_type, {
            "hospital": {"priority": 1, "reason": "Standby for medical needs"},
            "police": {"priority": 2, "reason": "Incident documentation"},
        })

        # Find nearest facilities with response time estimates
        dispatch_facilities = {}
        for cat, info in sorted(facility_map.items(), key=lambda x: x[1]["priority"]):
            facilities = emergency_store.get_all(cat)
            ranked = self._rank_nearby(facilities, lat, lon, config["facilities_to_dispatch"], 25.0)
            if ranked:
                nearest = ranked[0]
                dist_km = nearest.get("distance_km", 0)
                # Estimate response time: 2 min/km in city + 3 min base
                est_response_min = max(3, round(dist_km * 2 + 3))
                dispatch_facilities[cat] = {
                    "priority": info["priority"],
                    "reason": info["reason"],
                    "nearest": nearest,
                    "alternatives": ranked[1:],
                    "estimated_response_min": est_response_min,
                    "within_target": est_response_min <= config["response_time_target_min"],
                }

        # Generate MTC bus dispatch recommendations if applicable
        bus_dispatch = []
        if config["bus_dispatch"]:
            bus_dispatch = self._generate_bus_dispatch_recommendations(
                incident_type, severity, lat, lon
            )

        return {
            "incident_type": incident_type,
            "severity": severity,
            "response_level": config["dispatch_level"],
            "response_time_target_min": config["response_time_target_min"],
            "location": {"lat": lat, "lon": lon},
            "dispatch_facilities": dispatch_facilities,
            "recommended_actions": config["actions"],
            "bus_dispatch_recommendations": bus_dispatch,
            "public_advisory_required": config["public_advisory"],
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        }

    def _generate_bus_dispatch_recommendations(
        self,
        incident_type: str,
        severity: str,
        lat: float,
        lon: float,
    ) -> List[Dict]:
        """Generate MTC bus dispatch recommendations for emergency response."""
        from data_store import store

        buses = store.get_buses()
        recommendations = []

        # Find buses that could assist
        for bus in buses:
            bus_lat = bus.get("latitude")
            bus_lon = bus.get("longitude")
            if bus_lat is None or bus_lon is None:
                continue

            dist = _haversine_km(lat, lon, bus_lat, bus_lon)

            # Only consider buses within 5km for emergency dispatch
            if dist <= 5.0:
                bus_id = bus.get("bus_id", "")
                route_code = bus.get("route_code", "")
                risk_score = bus.get("risk", {}).get("score", 0)

                # Only dispatch buses with acceptable risk levels
                if risk_score < 50:
                    recommendations.append({
                        "bus_id": bus_id,
                        "route_code": route_code,
                        "distance_km": round(dist, 2),
                        "risk_score": risk_score,
                        "suitability": "HIGH" if dist < 2.0 and risk_score < 30 else "MEDIUM",
                        "action": f"Consider diverting {bus_id} to assist at incident location",
                    })

        # Sort by distance and limit to top 3
        recommendations.sort(key=lambda x: x["distance_km"])
        return recommendations[:3]


# Singleton
emergency_engine = EmergencyResponseEngine()
