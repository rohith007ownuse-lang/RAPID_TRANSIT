"""
road_corridor_intelligence.py
V2 Dynamic Road Risk Corridor Intelligence.

Combines:
- Pothole detections
- Road defects
- Incidents
- Traffic patterns
- Bus braking/speed anomalies
- Historical risk patterns

Produces dynamic road risk corridors with:
- Real-time risk level per corridor segment
- LOW → MEDIUM → HIGH → CRITICAL visualization data
- Explanation of why each corridor has its risk level
- Recommended actions per corridor

DATA CLASSIFICATION: RULE-BASED (uses existing road risk + traffic + event data)
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import math


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# Corridor segment length in km
CORRIDOR_SEGMENT_KM = 1.0

# Risk level thresholds for corridors
CORRIDOR_THRESHOLDS = {
    "LOW": (0, 25),
    "MEDIUM": (25, 50),
    "HIGH": (50, 75),
    "CRITICAL": (75, 100),
}


class RoadCorridorIntelligence:
    """
    Dynamic road risk corridor intelligence engine.

    Segments the road network into corridors and computes real-time
    risk levels based on multiple data sources.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._corridor_cache: Dict[str, Dict] = {}

    def compute_corridors(
        self,
        road_defects: List[Dict] = None,
        events: List[Dict] = None,
        risk_zones: List[Dict] = None,
        buses: List[Dict] = None,
        route_index: Dict = None,
    ) -> Dict:
        """
        Compute dynamic road risk corridors from available data.

        Returns corridor segments with risk levels, explanations,
        and recommended actions.
        """
        road_defects = road_defects or []
        events = events or []
        risk_zones = risk_zones or []
        buses = buses or []
        route_index = route_index or {}

        # ── Build corridor grid from risk zones ──
        corridors = self._build_corridors_from_zones(risk_zones)

        # ── Enrich corridors with defect data ──
        corridors = self._enrich_with_defects(corridors, road_defects)

        # ── Enrich with event data ──
        corridors = self._enrich_with_events(corridors, events)

        # ── Enrich with bus telemetry anomalies ──
        corridors = self._enrich_with_bus_anomalies(corridors, buses)

        # ── Enrich with route risk index ──
        corridors = self._enrich_with_route_risk(corridors, route_index)

        # ── Compute final corridor risk scores ──
        corridors = self._compute_corridor_scores(corridors)

        # ── Generate explanations and actions ──
        corridors = self._generate_corridor_intelligence(corridors)

        # ── Build summary ──
        summary = self._build_summary(corridors)

        # ── Publish to the detail cache so get_corridor()/get_bus_corridors()
        # resolve (previously the cache was never written, so the detail
        # endpoint always 404'd even when corridors existed).
        with self._lock:
            self._corridor_cache = dict(corridors)

        return {
            "corridors": corridors,
            "summary": summary,
            "total_corridors": len(corridors),
            "data_source": "RULE-BASED (road risk + events + traffic)",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def get_corridor(self, corridor_id: str) -> Optional[Dict]:
        """Get details for a specific corridor."""
        return self._corridor_cache.get(corridor_id)

    def get_bus_corridors(self, bus_id: str, buses: List[Dict] = None) -> List[Dict]:
        """Get corridors that a bus is currently passing through."""
        buses = buses or []
        bus = next((b for b in buses if b.get("bus_id") == bus_id), None)
        if not bus:
            return []

        bus_lat = bus.get("latitude", 0)
        bus_lon = bus.get("longitude", 0)
        if not bus_lat or not bus_lon:
            return []

        # Find corridors near bus
        nearby = []
        for cid, corridor in self._corridor_cache.items():
            center_lat = corridor.get("center_lat", 0)
            center_lon = corridor.get("center_lon", 0)
            if center_lat and center_lon:
                dist = _haversine_km(bus_lat, bus_lon, center_lat, center_lon)
                if dist <= CORRIDOR_SEGMENT_KM * 1.5:
                    nearby.append({
                        **corridor,
                        "distance_km": round(dist, 2),
                    })

        nearby.sort(key=lambda c: c.get("distance_km", 999))
        return nearby

    # ── Internal methods ──

    def _build_corridors_from_zones(self, risk_zones: List[Dict]) -> Dict[str, Dict]:
        """Build corridor segments from existing risk zones.

        Accepts both the corridor-native shape (center_lat/center_lon,
        affected_routes, detection_count) and the RoadRiskZone.to_dict()
        shape (lat/lon, routes_affected, total_detections) that the
        /api/v2/roads/corridors handler actually feeds in.
        """
        corridors = {}

        for zone in risk_zones:
            zone_id = zone.get("zone_id", "")
            center_lat = zone.get("center_lat") or zone.get("lat") or 0
            center_lon = zone.get("center_lon") or zone.get("lon") or 0

            if not center_lat or not center_lon:
                continue

            # Create corridor ID from zone
            corridor_id = f"CORR-{zone_id}"

            corridors[corridor_id] = {
                "corridor_id": corridor_id,
                "center_lat": center_lat,
                "center_lon": center_lon,
                "radius_m": zone.get("radius_m", 300),
                "risk_level": zone.get("risk_level", "LOW"),
                "risk_score": zone.get("risk_score", 0),
                "detection_count": zone.get("detection_count",
                                            zone.get("total_detections", 0)),
                "affected_routes": zone.get("affected_routes",
                                            zone.get("routes_affected", [])),
                "temporal_type": zone.get("temporal_type", "UNKNOWN"),
                "defect_count": 0,
                "event_count": 0,
                "bus_anomaly_count": 0,
                "route_risk_contribution": 0,
                "signal_sources": [],
                "contributing_factors": [],
            }

        return corridors

    def _enrich_with_defects(self, corridors: Dict, defects: List[Dict]) -> Dict:
        """Enrich corridors with nearby road defects."""
        for defect in defects:
            d_lat = defect.get("latitude", 0)
            d_lon = defect.get("longitude", 0)
            if not d_lat or not d_lon:
                continue

            for corr_id, corridor in corridors.items():
                dist = _haversine_km(
                    d_lat, d_lon,
                    corridor["center_lat"], corridor["center_lon"]
                )
                if dist <= corridor["radius_m"] / 1000:
                    corridor["defect_count"] += 1
                    if "ROAD_DEFECTS" not in corridor["signal_sources"]:
                        corridor["signal_sources"].append("ROAD_DEFECTS")

        return corridors

    def _enrich_with_events(self, corridors: Dict, events: List[Dict]) -> Dict:
        """Enrich corridors with relevant events."""
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

        for event in events:
            e_lat = event.get("latitude", 0)
            e_lon = event.get("longitude", 0)
            if not e_lat or not e_lon:
                continue

            # Check timestamp
            e_ts = event.get("timestamp", "")
            try:
                e_dt = datetime.fromisoformat(e_ts.replace("Z", "+00:00"))
                if e_dt < recent_cutoff:
                    continue
            except (ValueError, TypeError):
                pass

            for corr_id, corridor in corridors.items():
                dist = _haversine_km(
                    e_lat, e_lon,
                    corridor["center_lat"], corridor["center_lon"]
                )
                if dist <= corridor["radius_m"] / 1000:
                    corridor["event_count"] += 1
                    severity = event.get("severity", "INFO")
                    if severity in ("HIGH", "CRITICAL"):
                        corridor["contributing_factors"].append(
                            f"{event.get('event_type', 'EVENT')} ({severity})"
                        )
                    if "EVENTS" not in corridor["signal_sources"]:
                        corridor["signal_sources"].append("EVENTS")

        return corridors

    def _enrich_with_bus_anomalies(self, corridors: Dict, buses: List[Dict]) -> Dict:
        """Enrich corridors with bus speed/braking anomalies."""
        for bus in buses:
            b_lat = bus.get("latitude", 0)
            b_lon = bus.get("longitude", 0)
            if not b_lat or not b_lon:
                continue

            speed = bus.get("speed_kmh", 0)
            vehicle = bus.get("vehicle") or {}
            vibration = vehicle.get("vibration", 0)

            # Check for anomalies
            has_anomaly = False
            if speed > 50:
                has_anomaly = True
            if vibration > 1.5:
                has_anomaly = True

            if has_anomaly:
                for corr_id, corridor in corridors.items():
                    dist = _haversine_km(
                        b_lat, b_lon,
                        corridor["center_lat"], corridor["center_lon"]
                    )
                    if dist <= corridor["radius_m"] / 1000:
                        corridor["bus_anomaly_count"] += 1
                        if "BUS_TELEMETRY" not in corridor["signal_sources"]:
                            corridor["signal_sources"].append("BUS_TELEMETRY")

        return corridors

    def _enrich_with_route_risk(self, corridors: Dict, route_index: Dict) -> Dict:
        """Enrich corridors with route risk index data."""
        for route_code, risk_info in route_index.items():
            risk_score = risk_info.get("risk_score", 0)
            affected_segments = risk_info.get("affected_segments", [])

            for segment in affected_segments:
                seg_lat = segment.get("lat", 0)
                seg_lon = segment.get("lon", 0)
                if not seg_lat or not seg_lon:
                    continue

                for corr_id, corridor in corridors.items():
                    dist = _haversine_km(
                        seg_lat, seg_lon,
                        corridor["center_lat"], corridor["center_lon"]
                    )
                    if dist <= corridor["radius_m"] / 1000:
                        corridor["route_risk_contribution"] = max(
                            corridor["route_risk_contribution"], risk_score
                        )
                        if "ROUTE_RISK" not in corridor["signal_sources"]:
                            corridor["signal_sources"].append("ROUTE_RISK")

        return corridors

    def _compute_corridor_scores(self, corridors: Dict) -> Dict:
        """Compute final risk scores for each corridor."""
        for corr_id, corridor in corridors.items():
            # Weighted combination of signal contributions
            base_score = corridor.get("risk_score", 0)
            defect_factor = min(30, corridor["defect_count"] * 10)
            event_factor = min(30, corridor["event_count"] * 15)
            anomaly_factor = min(20, corridor["bus_anomaly_count"] * 10)
            route_factor = min(20, corridor["route_risk_contribution"] * 0.3)

            final_score = min(100, base_score + defect_factor + event_factor + anomaly_factor + route_factor)

            # Determine level
            level = "LOW"
            for l, (lo, hi) in CORRIDOR_THRESHOLDS.items():
                if lo <= final_score < hi:
                    level = l
                    break
            if final_score >= 75:
                level = "CRITICAL"

            corridor["computed_score"] = round(final_score, 1)
            corridor["computed_level"] = level

        return corridors

    def _generate_corridor_intelligence(self, corridors: Dict) -> Dict:
        """Generate explanations and recommended actions for corridors."""
        for corr_id, corridor in corridors.items():
            level = corridor.get("computed_level", "LOW")
            factors = corridor.get("contributing_factors", [])
            sources = corridor.get("signal_sources", [])

            # Build explanation
            if level == "CRITICAL":
                explanation = (
                    f"CORRIDOR CRITICAL: Multiple risk signals detected. "
                    f"Defects: {corridor['defect_count']}, "
                    f"Events: {corridor['event_count']}, "
                    f"Bus anomalies: {corridor['bus_anomaly_count']}. "
                    f"Immediate speed reduction and route monitoring recommended."
                )
                actions = [
                    "Alert all buses in corridor to reduce speed",
                    "Consider temporary route diversion",
                    "Deploy traffic management if available",
                ]
            elif level == "HIGH":
                explanation = (
                    f"CORRIDOR HIGH RISK: Elevated risk signals. "
                    f"Sources: {', '.join(sources) if sources else 'multiple'}. "
                    f"Monitor closely and prepare response."
                )
                actions = [
                    "Monitor bus speeds in corridor",
                    "Prepare diversion routes",
                ]
            elif level == "MEDIUM":
                explanation = (
                    f"CORRIDOR MODERATE: Some risk signals present. "
                    f"Continue monitoring."
                )
                actions = ["Standard monitoring"]
            else:
                explanation = f"CORRIDOR LOW RISK: No significant risk signals."
                actions = ["Continue normal operations"]

            corridor["explanation"] = explanation
            corridor["recommended_actions"] = actions

        return corridors

    def _build_summary(self, corridors: Dict) -> Dict:
        """Build corridor intelligence summary."""
        total = len(corridors)
        critical = sum(1 for c in corridors.values() if c.get("computed_level") == "CRITICAL")
        high = sum(1 for c in corridors.values() if c.get("computed_level") == "HIGH")
        medium = sum(1 for c in corridors.values() if c.get("computed_level") == "MEDIUM")
        low = sum(1 for c in corridors.values() if c.get("computed_level") == "LOW")

        return {
            "total_corridors": total,
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
            "needs_attention": critical + high > 0,
            "overall_status": (
                "CRITICAL" if critical > 0
                else "HIGH" if high > 0
                else "MEDIUM" if medium > 0
                else "LOW"
            ),
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
road_corridor_intelligence = RoadCorridorIntelligence()
