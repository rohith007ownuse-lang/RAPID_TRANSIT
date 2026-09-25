"""
imu_sensor.py - IMU interface (MPU6050; simulation mode active).

SIMULATION: produces realistic acceleration along vehicle axes (m/s^2 and g):
    ax driving/braking, ay cornering, az bumps/road defects.
Flags: hard_braking (ax < -0.5 g), impact (resultant > impact_g_threshold).

Real MPU6050 (I2C 0x68) reads are not implemented: hardware not mounted.
"""

import math
import time
from typing import Dict, Any

from bus_node.sensors.base_sensor import BaseSensor

G = 9.80665  # m/s^2 per g


class IMUSensor(BaseSensor):
    kind = "imu"
    sensor_name = "imu"

    def __init__(self, simulation: bool = True,
                 impact_g_threshold: float = 3.0,
                 hard_decel_g_threshold: float = 0.5,
                 seed: int = 11):
        super().__init__(simulation=simulation)
        self.impact_g_threshold = impact_g_threshold
        self.hard_decel_g_threshold = hard_decel_g_threshold
        self._rng = __import__("random").Random(seed)
        self._ax = 0.0
        self._ay = 0.0
        self._az = 1.0  # gravity baseline (g units)

    def _read_simulated(self, now: float) -> Dict[str, Any]:
        # occasional brake / accelerate / corner / bump events
        r = self._rng.random()
        if r < 0.02:               # hard braking
            self._ax = -self._rng.uniform(0.45, 0.7)
        elif r < 0.05:             # mild acceleration
            self._ax = self._rng.uniform(0.1, 0.35)
        else:
            self._ax += self._rng.uniform(-0.03, 0.03)
            self._ax = max(-0.1, min(self._ax, 0.12))

        bump = 0.0
        if self._rng.random() < 0.03:    # road defect / bump
            bump = self._rng.uniform(0.3, 0.9)
        self._ay = max(-0.35, min(self._ay + self._rng.uniform(-0.05, 0.05), 0.35))
        self._az = 1.0 + bump * self._rng.choice([-1, 1])

        ax_g, ay_g, az_g = self._ax, self._ay, self._az
        magnitude_g = math.sqrt(ax_g ** 2 + ay_g ** 2 + az_g ** 2)

        hard_braking = ax_g < -self.hard_decel_g_threshold
        impact = magnitude_g > self.impact_g_threshold

        if impact:
            self.status = "IMPACT"
        else:
            self.status = "ACTIVE"

        return {
            "accel_x_g": round(ax_g, 3),
            "accel_y_g": round(ay_g, 3),
            "accel_z_g": round(az_g, 3),
            "accel_x_ms2": round(ax_g * G, 2),
            "accel_y_ms2": round(ay_g * G, 2),
            "accel_z_ms2": round(az_g * G, 2),
            "magnitude_g": round(magnitude_g, 3),
            "hard_braking": hard_braking,
            "impact": impact,
            "impact_g_threshold": self.impact_g_threshold,
        }


if __name__ == "__main__":
    imu = IMUSensor()
    imu.init()
    for _ in range(200):
        print(imu.read())
        time.sleep(0.05)
    imu.disable()