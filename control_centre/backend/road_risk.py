"""
road_risk.py
Road Risk Intelligence — defect clustering → route risk index, risk zones on map,
feeds risk engine. Road defect threats on a bus's current leg surface on the bus
page.

Phase 12 enhancements:
- Haversine-based clustering (not just coordinate rounding)
- Explicit evidence/reasoning for risk zones
- Temporal risk analysis (recurring vs temporary)
- Bus exposure tracking (CLEAR/APPROACHING/EXPOSED/UNKNOWN)
- Route risk with affected segments
- Honest source labeling (LIVE/SIMULATION/HEURISTIC/MODEL/UNKNOWN)
- Persistence of risk zones and clusters to SQLite
- Vehicle health correlation (contextual, not causal)
"""

import json
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from data_store import store
from road_event_model import (
    RoadEventSource,
    RoadRiskZone,
    RouteRisk,
    BusExposure,
    utcnow_iso,
    _haversine_km,
)


# Enfield projector bounds (for display sanitization)
ENFIELD_BOUNDS = {"south": 12.85, "west": 80.10, "north": 13.30, "east": 80.40}

# Clustering threshold: defects within this distance (km) are grouped
CLUSTER_RADIUS_KM = 0.03  # ~30m

# Minimum detections to form a risk zone (avoids single-signal zones)
MIN_DEFECTS_FOR_ZONE = 1


def _level_for_score(score: float) -> str:
    # HIGH starts at 60 (aligned with the risk engine) so the high-risk tier
    # stays focused on the 60–70+ band worth operator attention.
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def _color_for_level(level: str) -> str:
    return {"CRITICAL": "#dc2626", "HIGH": "#d97706", "MEDIUM": "#d97706", "LOW": "#16a34a"}.get(level, "#6b7280")


def _dominant_source(sources: Set[RoadEventSource]) -> RoadEventSource:
    """Determine dominant source from a set (priority: LIVE > MODEL > HEURISTIC > SIMULATION > UNKNOWN)."""
    if RoadEventSource.LIVE in sources:
        return RoadEventSource.LIVE
    if RoadEventSource.MODEL in sources:
        return RoadEventSource.MODEL
    if RoadEventSource.HEURISTIC in sources:
        return RoadEventSource.HEURISTIC
    if RoadEventSource.SIMULATION in sources:
        return RoadEventSource.SIMULATION
    return RoadEventSource.UNKNOWN


def _build_evidence_string(
    defect_count: int,
    total_detections: int,
    routes_affected: List[str],
    affected_buses: List[str],
    top_defect_type: str,
    source: RoadEventSource,
    temporal: str = "UNKNOWN",
) -> str:
    """Build human-readable evidence string for a risk zone."""
    parts = []
    if defect_count > 0:
        parts.append(f"{defect_count} road-defect cluster(s)")
    if total_detections > 0:
        parts.append(f"{total_detections} total detections")
    if affected_buses:
        parts.append(f"across {len(affected_buses)} bus(es): {', '.join(sorted(affected_buses)[:5])}")
    if routes_affected:
        parts.append(f"on {len(routes_affected)} route(s): {', '.join(sorted(routes_affected))}")
    parts.append(f"primary type: {top_defect_type}")
    parts.append(f"evidence source: {source.value}")
    if temporal != "UNKNOWN":
        parts.append(f"temporal pattern: {temporal}")
    return "; ".join(parts)


def _classify_defect_source(defect: dict) -> RoadEventSource:
    """Determine the source of a single defect entry."""
    sensor = defect.get("sensor_source", "").lower()
    if "live" in sensor or defect.get("data_source") == "live":
        return RoadEventSource.LIVE
    if "heuristic" in sensor or "road_heuristic" in sensor:
        return RoadEventSource.HEURISTIC
    if "model" in sensor:
        return RoadEventSource.MODEL
    if defect.get("simulation") is True:
        return RoadEventSource.SIMULATION
    return RoadEventSource.UNKNOWN


def _cluster_defects(defects: List[dict]) -> List[List[dict]]:
    """Group defects by haversine proximity. Returns list of clusters."""
    active = [d for d in defects if d.get("status") == "ACTIVE"]
    if not active:
        return []

    clusters: List[List[dict]] = []
    assigned = set()

    for i, d1 in enumerate(active):
        if i in assigned:
            continue
        cluster = [d1]
        assigned.add(i)
        lat1, lon1 = d1.get("latitude", 0), d1.get("longitude", 0)
        if lat1 is None or lon1 is None:
            continue

        for j, d2 in enumerate(active):
            if j in assigned:
                continue
            lat2, lon2 = d2.get("latitude", 0), d2.get("longitude", 0)
            if lat2 is None or lon2 is None:
                continue
            dist = _haversine_km(lat1, lon1, lat2, lon2)
            if dist <= CLUSTER_RADIUS_KM:
                cluster.append(d2)
                assigned.add(j)

        clusters.append(cluster)

    return clusters


def _assess_temporal_pattern(cluster: List[dict]) -> str:
    """Assess whether a cluster represents a recurring or temporary issue.

    Returns: RECURRING, TEMPORARY, or UNKNOWN
    """
    if len(cluster) < 2:
        return "UNKNOWN"

    timestamps = []
    for d in cluster:
        ts = d.get("last_detected") or d.get("first_detected")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass

    if len(timestamps) < 2:
        return "UNKNOWN"

    timestamps.sort()
    # Check span: if detections span > 2 hours, it's likely recurring
    span = (timestamps[-1] - timestamps[0]).total_seconds()
    if span > 7200:  # > 2 hours
        return "RECURRING"
    if span > 1800:  # > 30 minutes
        return "RECURRING"
    return "TEMPORARY"


class RoadRiskEngine:
    """Aggregates road defects into risk zones, route risk indices, and bus exposure."""

    def __init__(self):
        self._lock = threading.Lock()
        self.zones: Dict[str, RoadRiskZone] = {}
        self.clusters: List[dict] = []
        self._exposure_cache: Dict[str, BusExposure] = {}
        self._last_rebuild = 0

    def rebuild_zones(self):
        """Recompute risk zones from current road defects with haversine clustering."""
        defects = store.get_road_defects()
        if not defects:
            with self._lock:
                self.zones = {}
                self.clusters = []
            return

        # Step 1: Cluster defects by proximity
        raw_clusters = _cluster_defects(defects)

        new_zones = {}
        persisted_clusters = []

        for cluster_defects in raw_clusters:
            if not cluster_defects:
                continue

            # Representative location (centroid of cluster)
            lat = sum(d.get("latitude", 0) for d in cluster_defects) / len(cluster_defects)
            lon = sum(d.get("longitude", 0) for d in cluster_defects) / len(cluster_defects)

            # Generate cluster ID from representative coordinates
            cluster_key = f"{round(lat, 3)}_{round(lon, 3)}"

            total_detections = sum(d.get("detection_count", 1) for d in cluster_defects)

            # Collect affected buses and routes
            all_buses: Set[str] = set()
            routes: Set[str] = set()
            sources: Set[RoadEventSource] = set()
            first_detected_list = []
            last_detected_list = []
            event_types = set()

            for d in cluster_defects:
                all_buses.update(d.get("buses", []))
                sources.add(_classify_defect_source(d))
                etype = d.get("type", "pothole")
                event_types.add(etype)

                if d.get("first_detected"):
                    first_detected_list.append(d["first_detected"])
                if d.get("last_detected"):
                    last_detected_list.append(d["last_detected"])

            for b in all_buses:
                bus = store.get_bus(b)
                if bus:
                    routes.add(bus.get("route_code", ""))

            dominant = _dominant_source(sources)
            temporal = _assess_temporal_pattern(cluster_defects)

            # Risk score: detection density + route coverage + bus coverage
            avg_confidence = sum(d.get("confidence", 0.5) for d in cluster_defects) / len(cluster_defects)
            # Recurring issues get higher scores
            temporal_mult = 1.3 if temporal == "RECURRING" else 1.0
            score = min(100,
                (total_detections * 8 +
                 len(routes) * 12 +
                 len(all_buses) * 3 +
                 avg_confidence * 10) * temporal_mult
            )
            level = _level_for_score(score)

            # Defect types
            top_type = max(event_types, key=lambda t: sum(1 for d in cluster_defects if d.get("type", "pothole") == t))

            evidence = _build_evidence_string(
                defect_count=len(cluster_defects),
                total_detections=total_detections,
                routes_affected=sorted(routes),
                affected_buses=sorted(all_buses),
                top_defect_type=top_type,
                source=dominant,
                temporal=temporal,
            )

            zone = RoadRiskZone(
                zone_id=cluster_key,
                lat=round(lat, 4),
                lon=round(lon, 4),
                radius_m=200,
                risk_score=round(score, 1),
                risk_level=level,
                defect_count=len(cluster_defects),
                total_detections=total_detections,
                routes_affected=sorted(routes),
                affected_buses=sorted(all_buses),
                top_defect_type=top_type,
                evidence=evidence,
                source=dominant,
                first_detected=min(first_detected_list) if first_detected_list else utcnow_iso(),
                last_detected=max(last_detected_list) if last_detected_list else utcnow_iso(),
            )

            new_zones[cluster_key] = zone

            # Build cluster record for persistence
            cluster_record = {
                "cluster_id": cluster_key,
                "representative_lat": round(lat, 4),
                "representative_lon": round(lon, 4),
                "radius_m": 200,
                "event_count": len(cluster_defects),
                "severity": level,
                "first_detected": zone.first_detected,
                "last_detected": zone.last_detected,
                "affected_buses": sorted(all_buses),
                "affected_routes": sorted(routes),
                "source": dominant.value,
                "status": "ACTIVE",
                "evidence": evidence,
                "event_types": sorted(event_types),
                "temporal_pattern": temporal,
            }
            persisted_clusters.append(cluster_record)

        with self._lock:
            self.zones = new_zones
            self.clusters = persisted_clusters

        # Persist risk zones and clusters
        self._persist_state(new_zones, persisted_clusters)
        self._last_rebuild = datetime.now(timezone.utc).timestamp()

    def _persist_state(self, zones: Dict[str, RoadRiskZone], clusters: List[dict]) -> None:
        """Persist risk zones and clusters to SQLite (best-effort, non-blocking)."""
        try:
            import persistence
            for z in zones.values():
                persistence.save_road_risk_zone(z.to_dict())
            for c in clusters:
                persistence.save_road_cluster(c)
        except Exception as e:
            print(f"[road-risk] persistence error (non-fatal): {e}")

    def get_zones(self) -> List[dict]:
        with self._lock:
            return [z.to_dict() for z in self.zones.values()]

    def get_clusters(self) -> List[dict]:
        with self._lock:
            return list(self.clusters)

    def get_route_risk_index(self) -> Dict[str, dict]:
        """Per-route risk index: aggregate zone scores on that route with segments."""
        with self._lock:
            zones = list(self.zones.values())

        route_accum = defaultdict(lambda: {
            "score": 0.0, "zones": 0, "defects": 0, "level": "LOW",
            "buses": set(), "zone_ids": [], "segments": []
        })

        for z in zones:
            for r in z.routes_affected:
                route_accum[r]["score"] += z.risk_score
                route_accum[r]["zones"] += 1
                route_accum[r]["defects"] += z.defect_count
                route_accum[r]["buses"].update(z.affected_buses)
                route_accum[r]["zone_ids"].append(z.zone_id)
                route_accum[r]["segments"].append({
                    "zone_id": z.zone_id,
                    "lat": z.lat,
                    "lon": z.lon,
                    "risk_score": z.risk_score,
                    "risk_level": z.risk_level,
                    "defect_count": z.defect_count,
                })

        # Build RouteRisk objects with evidence
        result = {}
        levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        for r, v in route_accum.items():
            avg_score = round(v["score"] / max(1, v["zones"]), 1)
            # Max level across all zones on this route
            max_level_idx = 0
            for z in zones:
                if r in z.routes_affected:
                    idx = levels.index(z.risk_level) if z.risk_level in levels else 0
                    max_level_idx = max(max_level_idx, idx)
            level = levels[max_level_idx]

            # Determine dominant source for this route
            route_sources = set()
            for z in zones:
                if r in z.routes_affected:
                    route_sources.add(z.source)
            dom_source = _dominant_source(route_sources)

            evidence = (
                f"Route {r}: {v['zones']} risk zone(s), {v['defects']} defect(s), "
                f"{len(v['buses'])} affected bus(es). "
                f"Avg zone score: {avg_score}. Source: {dom_source.value}."
            )

            route_risk = RouteRisk(
                route_id=r,
                route_name=r,
                risk_level=level,
                avg_score=avg_score,
                zones_count=v["zones"],
                total_defects=v["defects"],
                active_hazards=sum(1 for z in zones if r in z.routes_affected and z.risk_level in ("HIGH", "CRITICAL")),
                affected_segments=v["segments"],
                evidence=evidence,
                last_updated=utcnow_iso(),
                source=dom_source,
            )
            result[r] = route_risk.to_dict()

        return result

    def get_leg_threats(self, bus: dict) -> List[dict]:
        """Road threats on the bus's current leg (current -> next stop)."""
        journey = bus.get("journey", {})
        if not journey or "stops" not in journey:
            return []
        current_idx = journey.get("current_index", 0)
        next_idx = journey.get("next_index", current_idx + 1)
        if next_idx is None:
            next_idx = current_idx + 1
        stops = journey.get("stops", [])
        if not stops or next_idx >= len(stops):
            return []

        a = stops[current_idx]
        b = stops[next_idx]

        threats = []
        with self._lock:
            for z in self.zones.values():
                # Proximity: zone within 1km of segment midpoint
                mid_lat = (a["lat"] + b["lat"]) / 2
                mid_lon = (a["lon"] + b["lon"]) / 2
                dist = _haversine_km(mid_lat, mid_lon, z.lat, z.lon)
                if dist <= 1.0:
                    threats.append({
                        "zone_id": z.zone_id,
                        "lat": z.lat,
                        "lon": z.lon,
                        "risk_score": z.risk_score,
                        "risk_level": z.risk_level,
                        "defect_count": z.defect_count,
                        "top_defect_type": z.top_defect_type,
                        "distance_km": round(dist, 2),
                        "evidence": z.evidence,
                        "source": z.source.value,
                    })
        return threats

    def compute_bus_exposure(self, bus: dict) -> BusExposure:
        """Compute a bus's exposure to road risk zones.

        Considers both proximity and route overlap for more accurate exposure.
        """
        bus_id = bus.get("bus_id", "")
        route_code = bus.get("route_code", "")
        lat = bus.get("latitude")
        lon = bus.get("longitude")

        if lat is None or lon is None:
            return BusExposure(
                bus_id=bus_id,
                route_code=route_code,
                current_lat=None,
                current_lon=None,
                exposure_state="UNKNOWN",
                evidence="No GPS location available",
            )

        with self._lock:
            zones = list(self.zones.values())

        if not zones:
            return BusExposure(
                bus_id=bus_id,
                route_code=route_code,
                current_lat=lat,
                current_lon=lon,
                exposure_state="CLEAR",
                evidence="No active risk zones",
            )

        # Find zones this bus's route intersects
        route_zones = [z for z in zones if route_code in z.routes_affected]
        # Find nearest zone overall
        closest_zone = None
        min_dist = float("inf")
        for z in zones:
            dist = _haversine_km(lat, lon, z.lat, z.lon)
            if dist < min_dist:
                min_dist = dist
                closest_zone = z

        # Route-aware exposure: if bus route has a risk zone, increase exposure awareness
        route_has_risk = len(route_zones) > 0
        nearest_route_zone = None
        min_route_dist = float("inf")
        for z in route_zones:
            dist = _haversine_km(lat, lon, z.lat, z.lon)
            if dist < min_route_dist:
                min_route_dist = dist
                nearest_route_zone = z

        # Determine exposure state
        if min_dist <= 0.5:
            state = "EXPOSED"
        elif min_dist <= 2.0 and closest_zone.risk_level in ("HIGH", "CRITICAL"):
            state = "APPROACHING"
        elif min_dist <= 1.0:
            state = "APPROACHING"
        elif route_has_risk and min_route_dist <= 3.0:
            state = "APPROACHING"  # route intersects risk zone
        else:
            state = "CLEAR"

        # Use route zone for evidence if closer
        evidence_zone = nearest_route_zone if nearest_route_zone and min_route_dist < min_dist else closest_zone
        evidence_dist = min_route_dist if evidence_zone == nearest_route_zone else min_dist

        evidence = (
            f"Bus {bus_id} at {lat:.4f},{lon:.4f}. "
            f"Nearest risk zone: {evidence_zone.zone_id} ({evidence_zone.risk_level}, "
            f"score {evidence_zone.risk_score}) at {evidence_dist:.2f} km. "
            f"Zone evidence: {evidence_zone.evidence}"
        )

        return BusExposure(
            bus_id=bus_id,
            route_code=route_code,
            current_lat=lat,
            current_lon=lon,
            exposure_state=state,
            nearby_zone_id=evidence_zone.zone_id,
            zone_risk_level=evidence_zone.risk_level,
            zone_distance_km=round(evidence_dist, 2),
            hazard_severity=evidence_zone.risk_level,
            evidence=evidence,
        )

    def get_all_bus_exposures(self) -> List[dict]:
        """Get exposure for all active buses."""
        buses = store.get_buses()
        exposures = []
        for bus in buses:
            if bus.get("_live") or bus.get("simulation"):
                exp = self.compute_bus_exposure(bus)
                exposures.append(exp.to_dict())
        return exposures

    def get_road_summary(self) -> dict:
        """Build a comprehensive road intelligence summary for the dashboard."""
        with self._lock:
            zones = list(self.zones.values())
            clusters = list(self.clusters)

        # Count by level
        level_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        for z in zones:
            level_counts[z.risk_level] = level_counts.get(z.risk_level, 0) + 1

        # Count by source
        source_counts = {}
        for z in zones:
            src = z.source.value
            source_counts[src] = source_counts.get(src, 0) + 1

        # Route impact
        route_risk = self.get_route_risk_index()
        affected_routes = [r for r, v in route_risk.items() if v.get("risk_level") in ("MEDIUM", "HIGH", "CRITICAL")]

        # Bus exposure summary
        exposures = self.get_all_bus_exposures()
        exposed_buses = [e for e in exposures if e.get("exposure_state") == "EXPOSED"]
        approaching_buses = [e for e in exposures if e.get("exposure_state") == "APPROACHING"]

        # Vehicle health correlation (contextual only)
        health_correlations = []
        for bus in store.get_buses():
            vh = bus.get("vehicle", {})
            vib = vh.get("vibration", 0)
            if vib > 0.5:
                # Check if bus is near a risk zone
                exp = self.compute_bus_exposure(bus)
                if exp.exposure_state in ("EXPOSED", "APPROACHING"):
                    health_correlations.append({
                        "bus_id": bus["bus_id"],
                        "vibration": vib,
                        "exposure": exp.exposure_state,
                        "zone": exp.nearby_zone_id,
                        "correlation": "Contextual: increased vibration coincided with road-hazard exposure",
                    })

        return {
            "zones_count": len(zones),
            "clusters_count": len(clusters),
            "level_counts": level_counts,
            "source_counts": source_counts,
            "affected_routes": affected_routes,
            "exposed_buses_count": len(exposed_buses),
            "approaching_buses_count": len(approaching_buses),
            "health_correlations": health_correlations[:5],  # limit to 5
            "total_defects": sum(z.defect_count for z in zones),
            "total_detections": sum(z.total_detections for z in zones),
            "generated_at": utcnow_iso(),
        }


road_risk_engine = RoadRiskEngine()


def rebuild_zones():
    road_risk_engine.rebuild_zones()


def get_zones():
    return road_risk_engine.get_zones()


def get_clusters():
    return road_risk_engine.get_clusters()


def get_route_risk():
    return road_risk_engine.get_route_risk_index()


def get_leg_threats(bus: dict):
    return road_risk_engine.get_leg_threats(bus)


def get_bus_exposure(bus: dict) -> dict:
    return road_risk_engine.compute_bus_exposure(bus).to_dict()


def get_all_bus_exposures() -> List[dict]:
    return road_risk_engine.get_all_bus_exposures()


def get_road_summary() -> dict:
    return road_risk_engine.get_road_summary()


if __name__ == "__main__":
    import json
    rebuild_zones()
    print("=== ZONES ===")
    print(json.dumps(get_zones()[:3], indent=2))
    print("\n=== CLUSTERS ===")
    print(json.dumps(get_clusters()[:3], indent=2))
    print("\n=== ROUTE RISK ===")
    print(json.dumps(get_route_risk(), indent=2))
    print("\n=== BUS EXPOSURES ===")
    print(json.dumps(get_all_bus_exposures()[:3], indent=2))
    print("\n=== ROAD SUMMARY ===")
    print(json.dumps(get_road_summary(), indent=2))
