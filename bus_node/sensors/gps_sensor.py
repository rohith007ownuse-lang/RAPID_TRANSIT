"""
gps_sensor.py - GPS position interface (NEO-6M; simulation mode active).

SIMULATION: the bus follows a waypoint loop around central Chennai
(Route 42) with a small drive cycle - stopping at bus stops,
accelerating, cruising at 20-45 km/h, decelerating - plus tiny noise on each
fix. Output is labeled with source + simulation.

Real NEO-6M (serial NMEA) reads are not implemented: hardware not mounted.
"""

import math
import time
from typing import Dict, Any

from bus_node.sensors.base_sensor import BaseSensor

# Route 42 - Central Chennai loop (approx., demo only)
WAYPOINTS = [
    (13.0827, 80.2747),   # Chennai Central / Park
    (13.0788, 80.2604),   # Egmore
    (13.0710, 80.2490),   # KMC / Simpsons–Anna Nagar approaches
    (13.0540, 80.2420),   # Nungambakkam
    (13.0349, 80.2454),   # Teynampet / Anna Salai
    (13.0403, 80.2780),   # Ice House / Triplicane
    (13.0500, 80.2824),   # Marina Beach (Kamarajar Salai)
    (13.0699, 80.2690),   # High Court / Parry's Corner
]

M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(13.08))  # ~108 km


class GPSSensor(BaseSensor):
    kind = "gps"
    sensor_name = "gps"

    def __init__(self, simulation: bool = True, home: tuple = (13.0827, 80.2747)):
        super().__init__(simulation=simulation)
        self._wp_index = 0
        self.lat, self.lon = home
        self.speed_kmh = 0.0
        self.heading_deg = 0.0
        self.odometer_km = 0.0
        self.fix = 0
        self._phase = "STOPPED"       # STOPPED | ACCELERATE | CRUISE | DECELERATE
        self._dwell_left = 2.0
        self._cruise_speed = 30.0
        self._last_advance = None
        self._rng = None

    def _seed_sim(self):
        self._rng = self._rng or __import__("random").Random(7)

    def _target(self):
        return WAYPOINTS[self._wp_index % len(WAYPOINTS)]

    def _advance_distance(self, meters: float):
        tlat, tlon = self._target()
        dlat = tlat - self.lat
        dlon = tlon - self.lon
        dx = dlon * M_PER_DEG_LON
        dy = dlat * M_PER_DEG_LAT
        dist = math.hypot(dx, dy)
        if dist <= meters or dist < 5.0:
            self.lat, self.lon = tlat, tlon
            self._wp_index += 1
            self.heading_deg = math.degrees(math.atan2(dx, dy)) % 360
            return
        frac = meters / dist
        self.lat += dlat * frac
        self.lon += dlon * frac
        self.heading_deg = math.degrees(math.atan2(dx, dy)) % 360

    def _read_simulated(self, now: float) -> Dict[str, Any]:
        self._seed_sim()
        # wall-clock based advance so real-time demo looks continuous
        if self._last_advance is None:
            self._last_advance = now
        dt = min(now - self._last_advance, 5.0)
        self._last_advance = now

        # drive cycle state machine
        if self._phase == "STOPPED":
            self._dwell_left -= dt
            self.speed_kmh = 0.0
            if self._dwell_left <= 0:
                self._phase = "ACCELERATE"
                self._cruise_speed = self._rng.uniform(18, 45)
        elif self._phase == "ACCELERATE":
            self.speed_kmh = min(self.speed_kmh + 6.0 * dt, self._cruise_speed)
            if self.speed_kmh >= self._cruise_speed:
                self._phase = "CRUISE"
        elif self._phase == "CRUISE":
            self.speed_kmh = self._cruise_speed
            if self._rng.random() < dt * 0.08:          # chance to start slowing
                self._phase = "DECELERATE"
        elif self._phase == "DECELERATE":
            self.speed_kmh = max(self.speed_kmh - 8.0 * dt, 0.0)
            if self.speed_kmh <= 0.0:
                self._phase = "STOPPED"
                self._dwell_left = self._rng.uniform(4.0, 18.0)

        meters = self.speed_kmh * 1000.0 / 3600.0 * dt
        self._advance_distance(meters)
        self.odometer_km += meters / 1000.0
        self.fix += 1
        self.status = "ACTIVE"

        # tiny simulated fix noise
        lat = self.lat + self._rng.uniform(-0.00002, 0.00002)
        lon = self.lon + self._rng.uniform(-0.00002, 0.00002)

        return {
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "speed_kmh": round(self.speed_kmh, 1),
            "heading_deg": round(self.heading_deg, 1),
            "odometer_km": round(self.odometer_km, 3),
            "fix": self.fix,
            "mode": "1" if self.fix > 0 else "0",
        }


if __name__ == "__main__":
    g = GPSSensor()
    g.init()
    for _ in range(60):
        print(g.read())
        time.sleep(0.1)
    g.disable()