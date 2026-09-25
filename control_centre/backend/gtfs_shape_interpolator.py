"""
gtfs_shape_interpolator.py
Interpolates bus positions along GTFS shape paths for realistic movement.

Uses real Chennai GTFS shape data to move buses along actual road paths
instead of straight-line interpolation between stops.

Architecture:
    GTFS Shapes (real road paths)
         │
         ▼
    Shape Interpolator
         │
         ▼
    Realistic Bus Positions (lat, lon, heading, speed)
"""

import math
import threading
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


class ShapeInterpolator:
    """
    Interpolates positions along GTFS shape paths.

    Given a progress value (0.0 to 1.0) along a route, returns the
    interpolated latitude, longitude, heading, and distance along the path.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._shapes: Dict[str, List[Dict]] = {}
        self._shape_cache: Dict[str, Dict] = {}
        self._loaded = False

    def load_shapes(self, shapes: Dict[str, List[Dict]]):
        """
        Load GTFS shapes data.

        Args:
            shapes: Dict mapping shape_id to list of {lat, lon, sequence} points
        """
        with self._lock:
            self._shapes = shapes
            self._shape_cache.clear()
            self._precompute_shape_data()
            self._loaded = True
            print(f"[shape-interpolator] Loaded {len(shapes)} shapes")

    def _precompute_shape_data(self):
        """Precompute cumulative distances for each shape."""
        for shape_id, points in self._shapes.items():
            if not points:
                continue

            # Sort by sequence
            sorted_points = sorted(points, key=lambda p: p.get("sequence", 0))

            # Compute cumulative distances
            cumulative_dist = [0.0]
            for i in range(1, len(sorted_points)):
                dist = self._haversine(
                    sorted_points[i-1]["lat"], sorted_points[i-1]["lon"],
                    sorted_points[i]["lat"], sorted_points[i]["lon"]
                )
                cumulative_dist.append(cumulative_dist[-1] + dist)

            self._shape_cache[shape_id] = {
                "points": sorted_points,
                "cumulative_dist": cumulative_dist,
                "total_dist": cumulative_dist[-1] if cumulative_dist else 0.0,
            }

    def get_position_at_progress(
        self, shape_id: str, progress: float
    ) -> Optional[Dict]:
        """
        Get interpolated position at a given progress along the shape.

        Args:
            shape_id: GTFS shape ID
            progress: Float between 0.0 (start) and 1.0 (end)

        Returns:
            Dict with lat, lon, heading, distance_km, or None if shape not found
        """
        with self._lock:
            cache = self._shape_cache.get(shape_id)
            if not cache or not cache["points"]:
                return None

            points = cache["points"]
            cum_dist = cache["cumulative_dist"]
            total_dist = cache["total_dist"]

            if total_dist == 0:
                return None

            # Target distance along the shape
            target_dist = progress * total_dist

            # Find the segment containing the target distance
            segment_idx = 0
            for i in range(len(cum_dist) - 1):
                if cum_dist[i] <= target_dist <= cum_dist[i + 1]:
                    segment_idx = i
                    break
            else:
                segment_idx = len(points) - 2

            # Interpolate within the segment
            seg_start_dist = cum_dist[segment_idx]
            seg_end_dist = cum_dist[segment_idx + 1]
            seg_length = seg_end_dist - seg_start_dist

            if seg_length > 0:
                t = (target_dist - seg_start_dist) / seg_length
            else:
                t = 0.0

            # Interpolate position
            lat = points[segment_idx]["lat"] + t * (points[segment_idx + 1]["lat"] - points[segment_idx]["lat"])
            lon = points[segment_idx]["lon"] + t * (points[segment_idx + 1]["lon"] - points[segment_idx]["lon"])

            # Compute heading
            heading = self._compute_heading(
                points[segment_idx]["lat"], points[segment_idx]["lon"],
                points[segment_idx + 1]["lat"], points[segment_idx + 1]["lon"]
            )

            return {
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "heading": round(heading, 1),
                "distance_km": round(target_dist, 3),
                "total_distance_km": round(total_dist, 3),
                "progress": round(progress, 4),
            }

    def get_position_at_distance(
        self, shape_id: str, distance_km: float
    ) -> Optional[Dict]:
        """
        Get interpolated position at a given distance along the shape.

        Args:
            shape_id: GTFS shape ID
            distance_km: Distance in kilometers from start

        Returns:
            Dict with lat, lon, heading, progress, or None
        """
        with self._lock:
            cache = self._shape_cache.get(shape_id)
            if not cache or not cache["points"]:
                return None

            total_dist = cache["total_dist"]
            if total_dist == 0:
                return None

            progress = min(1.0, max(0.0, distance_km / total_dist))
            return self.get_position_at_progress(shape_id, progress)

    def get_distance_between_points(
        self, shape_id: str, progress1: float, progress2: float
    ) -> float:
        """
        Get the distance along the shape between two progress points.

        Args:
            shape_id: GTFS shape ID
            progress1: Start progress (0.0 to 1.0)
            progress2: End progress (0.0 to 1.0)

        Returns:
            Distance in kilometers
        """
        with self._lock:
            cache = self._shape_cache.get(shape_id)
            if not cache:
                return 0.0

            total_dist = cache["total_dist"]
            return abs(progress2 - progress1) * total_dist

    def get_shape_info(self, shape_id: str) -> Optional[Dict]:
        """Get metadata about a shape."""
        with self._lock:
            cache = self._shape_cache.get(shape_id)
            if not cache:
                return None

            return {
                "shape_id": shape_id,
                "num_points": len(cache["points"]),
                "total_distance_km": round(cache["total_dist"], 3),
            }

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine distance in kilometers between two points."""
        R = 6371.0  # Earth radius in km
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        return R * c

    @staticmethod
    def _compute_heading(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Compute bearing/heading from point 1 to point 2.

        Returns heading in degrees (0 = North, 90 = East, etc.)
        """
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlon_rad = math.radians(lon2 - lon1)

        x = math.sin(dlon_rad) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad)

        bearing = math.degrees(math.atan2(x, y))
        return (bearing + 360) % 360


class RouteShapeManager:
    """
    Manages shape data for all routes in the system.

    Connects GTFS route data with shape interpolation for realistic
    bus movement along actual road paths.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._interpolator = ShapeInterpolator()
        self._route_shapes: Dict[str, str] = {}  # route_code -> shape_id
        self._route_stops: Dict[str, List[Dict]] = {}  # route_code -> [{stop, lat, lon, sequence}]

    def initialize_from_gtfs(self, gtfs_loader):
        """
        Initialize route shapes from GTFS data.

        Args:
            gtfs_loader: Loaded GTFSLoader instance
        """
        with self._lock:
            # Load all shapes
            self._interpolator.load_shapes(gtfs_loader.shapes)

            # Map routes to their shapes via trips
            for route in gtfs_loader.routes:
                route_id = route.get("route_id", "")
                route_code = route.get("route_short_name", route_id)

                # Find a trip for this route to get its shape
                trips = gtfs_loader.get_trips_for_route(route_id)
                if trips:
                    # Use the first trip's shape
                    shape_id = trips[0].get("shape_id", "")
                    if shape_id:
                        self._route_shapes[route_code] = shape_id

                # Get stops for this route
                if trips:
                    trip_id = trips[0].get("trip_id", "")
                    stop_times = gtfs_loader.get_stop_times_for_trip(trip_id)
                    route_stops = []
                    for st in stop_times:
                        stop_id = st.get("stop_id", "")
                        stop = gtfs_loader.get_stop(stop_id)
                        if stop:
                            route_stops.append({
                                "stop_id": stop_id,
                                "stop_name": stop.get("stop_name", ""),
                                "lat": float(stop.get("stop_lat", 0)),
                                "lon": float(stop.get("stop_lon", 0)),
                                "sequence": int(st.get("stop_sequence", 0)),
                            })
                    self._route_stops[route_code] = sorted(route_stops, key=lambda s: s["sequence"])

            print(f"[shape-manager] Mapped {len(self._route_shapes)} routes to shapes")
            print(f"[shape-manager] Mapped {len(self._route_stops)} routes to stops")

    def get_bus_position(
        self, route_code: str, progress: float
    ) -> Optional[Dict]:
        """
        Get realistic bus position along a route.

        Args:
            route_code: Route code (e.g., "19D", "23C")
            progress: Float between 0.0 (start) and 1.0 (end)

        Returns:
            Dict with lat, lon, heading, speed, or None
        """
        shape_id = self._route_shapes.get(route_code)
        if not shape_id:
            return None

        return self._interpolator.get_position_at_progress(shape_id, progress)

    def get_nearest_stop(
        self, route_code: str, lat: float, lon: float
    ) -> Optional[Dict]:
        """
        Find the nearest stop to a given position on a route.

        Args:
            route_code: Route code
            lat: Current latitude
            lon: Current longitude

        Returns:
            Nearest stop info or None
        """
        stops = self._route_stops.get(route_code, [])
        if not stops:
            return None

        min_dist = float('inf')
        nearest = None

        for stop in stops:
            dist = self._interpolator._haversine(lat, lon, stop["lat"], stop["lon"])
            if dist < min_dist:
                min_dist = dist
                nearest = {**stop, "distance_km": round(dist, 3)}

        return nearest

    def get_stops_for_route(self, route_code: str) -> List[Dict]:
        """Get all stops for a route."""
        return self._route_stops.get(route_code, [])

    def get_route_distance(self, route_code: str) -> float:
        """Get total route distance in km."""
        shape_id = self._route_shapes.get(route_code)
        if not shape_id:
            return 0.0

        info = self._interpolator.get_shape_info(shape_id)
        return info["total_distance_km"] if info else 0.0

    def get_interpolator(self) -> ShapeInterpolator:
        """Get the underlying shape interpolator."""
        return self._interpolator


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

route_shape_manager = RouteShapeManager()
