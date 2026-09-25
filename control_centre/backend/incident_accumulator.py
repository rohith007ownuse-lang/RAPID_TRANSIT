"""
incident_accumulator.py
Tracks and accumulates confirmed incidents over time.

Provides:
- Historical incident storage
- Pattern detection
- Hotspot identification
- Incident clustering

DATA CLASSIFICATION: SIMULATED (events from simulator + live mode)
"""

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter
import math


class IncidentAccumulator:
    """
    Accumulates and analyzes incidents over time.

    Maintains a rolling window of incidents for pattern detection
    and hotspot identification.
    """

    def __init__(self, window_hours: int = 24):
        self._lock = threading.Lock()
        self._incidents: List[Dict] = []
        self._window_hours = window_hours

    def add_incident(self, incident: Dict):
        """Add an incident to the accumulator."""
        with self._lock:
            # Ensure timestamp
            if "timestamp" not in incident:
                incident["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

            self._incidents.append(incident)

            # Prune old incidents
            self._prune_old()

    def add_incidents_batch(self, incidents: List[Dict]):
        """Add multiple incidents at once."""
        for incident in incidents:
            self.add_incident(incident)

    def _prune_old(self):
        """Remove incidents older than the window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._window_hours)
        self._incidents = [
            i for i in self._incidents
            if self._parse_timestamp(i.get("timestamp", "")) > cutoff
        ]

    def get_recent_incidents(self, hours: int = None) -> List[Dict]:
        """Get incidents from the last N hours."""
        if hours is None:
            hours = self._window_hours

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self._lock:
            return [
                i for i in self._incidents
                if self._parse_timestamp(i.get("timestamp", "")) > cutoff
            ]

    def get_incident_summary(self) -> Dict:
        """Get summary statistics of accumulated incidents."""
        with self._lock:
            self._prune_old()

            if not self._incidents:
                return {
                    "total": 0,
                    "by_severity": {},
                    "by_type": {},
                    "by_area": {},
                    "hotspots": [],
                    "trend": "stable",
                }

            # Count by severity
            severity_counts = Counter(i.get("severity", "INFO") for i in self._incidents)

            # Count by type
            type_counts = Counter(i.get("event_type", "UNKNOWN") for i in self._incidents)

            # Count by area (inferred from location)
            area_counts = Counter(self._infer_area(i) for i in self._incidents)

            # Detect hotspots
            hotspots = self._detect_hotspots()

            # Calculate trend
            trend = self._calculate_trend()

            return {
                "total": len(self._incidents),
                "by_severity": dict(severity_counts),
                "by_type": dict(type_counts),
                "by_area": dict(area_counts),
                "hotspots": hotspots,
                "trend": trend,
                "window_hours": self._window_hours,
            }

    def get_hotspot_areas(self, min_incidents: int = 3) -> List[Dict]:
        """Get areas with high incident concentration."""
        with self._lock:
            self._prune_old()

            # Group by grid cell (approx 1km x 1km)
            grid = defaultdict(list)
            for incident in self._incidents:
                lat = incident.get("latitude", 0)
                lon = incident.get("longitude", 0)
                if lat and lon:
                    # Round to ~1km grid
                    grid_key = (round(lat, 2), round(lon, 2))
                    grid[grid_key].append(incident)

            # Find hotspots
            hotspots = []
            for (lat, lon), incidents in grid.items():
                if len(incidents) >= min_incidents:
                    severity_counts = Counter(i.get("severity", "INFO") for i in incidents)
                    type_counts = Counter(i.get("event_type", "UNKNOWN") for i in incidents)

                    hotspots.append({
                        "lat": lat,
                        "lon": lon,
                        "incident_count": len(incidents),
                        "severity_distribution": dict(severity_counts),
                        "top_types": dict(type_counts.most_common(3)),
                        "risk_level": self._calculate_hotspot_risk(incidents),
                    })

            # Sort by incident count
            hotspots.sort(key=lambda h: h["incident_count"], reverse=True)

            return hotspots

    def get_incident_clusters(self, radius_km: float = 2.0) -> List[Dict]:
        """
        Cluster nearby incidents using simple distance-based grouping.

        Args:
            radius_km: Clustering radius in kilometers

        Returns:
            List of incident clusters
        """
        with self._lock:
            self._prune_old()

            if not self._incidents:
                return []

            # Simple greedy clustering
            assigned = set()
            clusters = []

            for i, inc1 in enumerate(self._incidents):
                if i in assigned:
                    continue

                cluster = [inc1]
                assigned.add(i)

                lat1 = inc1.get("latitude", 0)
                lon1 = inc1.get("longitude", 0)

                if not lat1 or not lon1:
                    continue

                for j, inc2 in enumerate(self._incidents):
                    if j in assigned:
                        continue

                    lat2 = inc2.get("latitude", 0)
                    lon2 = inc2.get("longitude", 0)

                    if lat2 and lon2:
                        dist = self._haversine(lat1, lon1, lat2, lon2)
                        if dist <= radius_km:
                            cluster.append(inc2)
                            assigned.add(j)

                if len(cluster) >= 2:
                    # Calculate cluster center
                    avg_lat = sum(i.get("latitude", 0) for i in cluster) / len(cluster)
                    avg_lon = sum(i.get("longitude", 0) for i in cluster) / len(cluster)

                    clusters.append({
                        "center_lat": round(avg_lat, 6),
                        "center_lon": round(avg_lon, 6),
                        "incident_count": len(cluster),
                        "incidents": cluster,
                        "radius_km": radius_km,
                    })

            return clusters

    def _detect_hotspots(self) -> List[Dict]:
        """Detect incident hotspots from accumulated data."""
        return self.get_hotspot_areas(min_incidents=2)[:5]  # Top 5 hotspots

    def _calculate_trend(self) -> str:
        """Calculate incident trend (increasing/decreasing/stable)."""
        if len(self._incidents) < 10:
            return "insufficient_data"

        # Compare last 6 hours vs previous 6 hours
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(hours=6)
        older_cutoff = now - timedelta(hours=12)

        recent = sum(1 for i in self._incidents
                     if self._parse_timestamp(i.get("timestamp", "")) > recent_cutoff)
        older = sum(1 for i in self._incidents
                    if older_cutoff < self._parse_timestamp(i.get("timestamp", "")) <= recent_cutoff)

        if recent > older * 1.2:
            return "increasing"
        elif recent < older * 0.8:
            return "decreasing"
        else:
            return "stable"

    def _calculate_hotspot_risk(self, incidents: List[Dict]) -> str:
        """Calculate risk level for a hotspot."""
        severity_scores = {"CRITICAL": 4, "HIGH": 3, "WARNING": 2, "INFO": 1}
        avg_score = sum(severity_scores.get(i.get("severity", "INFO"), 1) for i in incidents) / len(incidents)

        if avg_score >= 3:
            return "high"
        elif avg_score >= 2:
            return "medium"
        else:
            return "low"

    def _infer_area(self, incident: Dict) -> str:
        """Infer area name from incident location."""
        # Simple grid-based area inference for Chennai
        lat = incident.get("latitude", 0)
        lon = incident.get("longitude", 0)

        if not lat or not lon:
            return "unknown"

        # Rough Chennai area mapping
        if lat > 13.15:
            return "north_chennai"
        elif lat < 12.95:
            return "south_chennai"
        elif lon < 80.22:
            return "west_chennai"
        elif lon > 80.28:
            return "east_chennai"
        else:
            return "central_chennai"

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine distance in kilometers."""
        R = 6371.0
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        return R * c

    @staticmethod
    def _parse_timestamp(ts: str) -> datetime:
        """Parse ISO timestamp to datetime."""
        try:
            # Handle both Z suffix and +00:00
            ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

incident_accumulator = IncidentAccumulator()
