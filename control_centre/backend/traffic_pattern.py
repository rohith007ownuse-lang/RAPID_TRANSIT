"""
traffic_pattern.py
Realistic time-of-day traffic patterns for Chennai.

Provides congestion multipliers based on:
- Time of day (morning rush, evening rush, night, etc.)
- Day of week (weekday vs weekend)
- Area type (CBD, residential, highway)

These patterns are used to make simulated traffic conditions realistic
without requiring external API data.

DATA CLASSIFICATION: SIMULATED (based on real Chennai traffic patterns)
"""

import threading
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
import random


# Chennai-specific traffic patterns based on real observations
# Source: General knowledge of Chennai traffic patterns

TIME_PERIODS = {
    "early_morning": {"hours": (5, 7), "congestion_base": 0.1, "speed_factor": 0.9},
    "morning_rush": {"hours": (7, 10), "congestion_base": 0.7, "speed_factor": 0.4},
    "mid_morning": {"hours": (10, 12), "congestion_base": 0.3, "speed_factor": 0.7},
    "lunch": {"hours": (12, 14), "congestion_base": 0.4, "speed_factor": 0.6},
    "afternoon": {"hours": (14, 17), "congestion_base": 0.3, "speed_factor": 0.7},
    "evening_rush": {"hours": (17, 20), "congestion_base": 0.8, "speed_factor": 0.35},
    "evening": {"hours": (20, 22), "congestion_base": 0.2, "speed_factor": 0.8},
    "night": {"hours": (22, 5), "congestion_base": 0.05, "speed_factor": 0.95},
}

# Area-based congestion multipliers for Chennai
AREA_MULTIPLIERS = {
    "cbd": 1.4,          # Central Business District (T Nagar, Anna Salai)
    "commercial": 1.2,   # Commercial areas (Broadway, Tondiarpet)
    "residential": 0.8,  # Residential areas (Adyar, Velachery)
    "highway": 0.6,      # Highways (ECR, OMR)
    "suburban": 0.7,     # Suburban areas (Tambaram, Chromepet)
}

# Weather impact on traffic
WEATHER_IMPACT = {
    "clear": 1.0,
    "cloudy": 1.0,
    "light_rain": 1.3,
    "heavy_rain": 1.8,
    "flooding": 2.5,
}


class TrafficPatternEngine:
    """
    Generates realistic traffic conditions based on time, location, and weather.

    Uses observed Chennai traffic patterns to create believable congestion
    data without requiring real-time API access.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._weather = "clear"
        self._special_events = []  # List of special events affecting traffic

    def set_weather(self, weather: str):
        """Set current weather condition."""
        with self._lock:
            self._weather = weather

    def add_special_event(self, event: Dict):
        """
        Add a special event affecting traffic.

        Args:
            event: {
                "name": "Protest",
                "area": "cbd",
                "congestion_multiplier": 2.0,
                "start_hour": 14,
                "end_hour": 18
            }
        """
        with self._lock:
            self._special_events.append(event)

    def clear_special_events(self):
        """Clear all special events."""
        with self._lock:
            self._special_events.clear()

    def get_traffic_conditions(
        self,
        hour: int = None,
        area_type: str = "residential",
        route_code: str = None,
    ) -> Dict:
        """
        Get realistic traffic conditions for a given time and area.

        Args:
            hour: Hour of day (0-23). If None, uses current time.
            area_type: One of 'cbd', 'commercial', 'residential', 'highway', 'suburban'
            route_code: Optional route code for route-specific adjustments

        Returns:
            Dict with:
                - congestion_level: 'free_flow', 'light', 'moderate', 'heavy', 'gridlock'
                - speed_factor: Multiplier for free-flow speed (0.0 to 1.0)
                - avg_speed_kmh: Estimated average speed
                - delay_minutes: Estimated delay per km
                - confidence: Confidence in the estimate (0.0 to 1.0)
        """
        if hour is None:
            hour = datetime.now(timezone.utc).hour

        # Get base congestion from time of day
        time_congestion, time_speed = self._get_time_congestion(hour)

        # Apply area multiplier
        area_mult = AREA_MULTIPLIERS.get(area_type, 1.0)

        # Apply weather impact
        weather_mult = WEATHER_IMPACT.get(self._weather, 1.0)

        # Apply special events
        event_mult = self._get_event_multiplier(hour, area_type)

        # Calculate final congestion
        final_congestion = min(1.0, time_congestion * area_mult * weather_mult * event_mult)
        final_speed_factor = max(0.1, time_speed / (area_mult * weather_mult * event_mult))

        # Convert to congestion level
        congestion_level = self._congestion_from_score(final_congestion)

        # Estimate speeds (Chennai average free-flow: 35-45 km/h)
        free_flow_speed = 40.0
        avg_speed = free_flow_speed * final_speed_factor
        delay_per_km = (1.0 / max(0.1, final_speed_factor) - 1.0) * (60.0 / free_flow_speed)

        return {
            "congestion_level": congestion_level,
            "congestion_score": round(final_congestion, 3),
            "speed_factor": round(final_speed_factor, 3),
            "avg_speed_kmh": round(avg_speed, 1),
            "delay_minutes_per_km": round(delay_per_km, 2),
            "weather": self._weather,
            "area_type": area_type,
            "time_period": self._get_time_period(hour),
            "confidence": 0.75,  # Simulated data confidence
        }

    def get_route_congestion(
        self, route_code: str, stops: list, hour: int = None
    ) -> Dict:
        """
        Get congestion summary for an entire route.

        Args:
            route_code: Route code
            stops: List of stops with lat/lon
            hour: Hour of day

        Returns:
            Dict with route-wide congestion summary
        """
        if hour is None:
            hour = datetime.now(timezone.utc).hour

        segment_conditions = []
        for i in range(len(stops) - 1):
            # Determine area type based on stop names/locations
            area_type = self._infer_area_type(stops[i].get("stop_name", ""))
            condition = self.get_traffic_conditions(hour, area_type, route_code)
            segment_conditions.append(condition)

        # Calculate route-wide statistics
        avg_congestion = sum(c["congestion_score"] for c in segment_conditions) / max(1, len(segment_conditions))
        avg_speed = sum(c["avg_speed_kmh"] for c in segment_conditions) / max(1, len(segment_conditions))

        # Find worst segment
        worst = max(segment_conditions, key=lambda c: c["congestion_score"])

        return {
            "route_code": route_code,
            "num_segments": len(segment_conditions),
            "avg_congestion_score": round(avg_congestion, 3),
            "avg_speed_kmh": round(avg_speed, 1),
            "worst_segment": worst,
            "segment_conditions": segment_conditions,
            "overall_level": self._congestion_from_score(avg_congestion),
        }

    def _get_time_congestion(self, hour: int) -> Tuple[float, float]:
        """Get base congestion and speed factor for time of day."""
        for period_name, period in TIME_PERIODS.items():
            start, end = period["hours"]
            if start <= hour < end:
                return period["congestion_base"], period["speed_factor"]

        # Default (should not reach here)
        return 0.3, 0.7

    def _get_time_period(self, hour: int) -> str:
        """Get human-readable time period name."""
        for period_name, period in TIME_PERIODS.items():
            start, end = period["hours"]
            if start <= hour < end:
                return period_name
        return "unknown"

    def _get_event_multiplier(self, hour: int, area_type: str) -> float:
        """Get congestion multiplier from special events."""
        multiplier = 1.0
        for event in self._special_events:
            if (event.get("area") == area_type and
                event.get("start_hour", 0) <= hour < event.get("end_hour", 24)):
                multiplier *= event.get("congestion_multiplier", 1.0)
        return multiplier

    def _infer_area_type(self, stop_name: str) -> str:
        """Infer area type from stop name."""
        stop_lower = stop_name.lower()

        # CBD areas
        if any(x in stop_lower for x in ["t.nagar", "anna salai", "pondy bazaar", "express estate"]):
            return "cbd"

        # Commercial areas
        if any(x in stop_lower for x in ["broadway", "tondiarpet", "market", "station", "terminal"]):
            return "commercial"

        # Highway areas
        if any(x in stop_lower for x in ["omr", "ecr", "highway", "expressway", "bypass"]):
            return "highway"

        # Suburban areas
        if any(x in stop_lower for x in ["tambaram", "chromepet", "pallavaram", "ambattur", "koyambedu"]):
            return "suburban"

        # Default to residential
        return "residential"

    @staticmethod
    def _congestion_from_score(score: float) -> str:
        """Convert congestion score (0-1) to level string."""
        if score < 0.2:
            return "free_flow"
        elif score < 0.4:
            return "light"
        elif score < 0.6:
            return "moderate"
        elif score < 0.8:
            return "heavy"
        else:
            return "gridlock"


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

traffic_pattern_engine = TrafficPatternEngine()
