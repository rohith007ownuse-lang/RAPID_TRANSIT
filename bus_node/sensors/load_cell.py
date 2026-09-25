"""
load_cell.py - load/weight interface (HX711; simulation mode active).

SIMULATION: payload changes in boarding/alighting groups at bus stops,
bounded by the configured payload limit. GVW = tare + payload. Emits a load
status matching the Control Centre statuses (NORMAL / HIGH LOAD / OVERLOAD /
CRITICAL OVERLOAD).

Real HX711 (GPIO) weight reads are not implemented: hardware not mounted.
The tare/payload values are project assumptions, not validated load data.
"""

import time
from typing import Dict, Any

from bus_node.sensors.base_sensor import BaseSensor


class LoadCellSensor(BaseSensor):
    kind = "load_cell"
    sensor_name = "load_cell"

    def __init__(self, simulation: bool = True, tare_weight_kg: int = 11000,
                 payload_limit_kg: int = 6000,
                 warning_threshold_kg: int = 5400, seed: int = 23):
        super().__init__(simulation=simulation)
        self.tare_kg = tare_weight_kg
        self.payload_limit_kg = payload_limit_kg
        self.warning_threshold_kg = warning_threshold_kg
        self.payload_kg = int(payload_limit_kg * 0.35)
        self._rng = __import__("random").Random(seed)
        self._next_boarding_in = 8.0
        self._boarding = False
        self._boarding_left = 0.0
        self._step_sign = 1
        self._px_delta_left = 0

    def _status_for(self, payload_kg: float) -> str:
        pct = payload_kg / self.payload_limit_kg * 100.0
        if payload_kg > self.payload_limit_kg * 1.15:
            return "CRITICAL_OVERLOAD"
        if payload_kg > self.payload_limit_kg:
            return "OVERLOAD"
        if payload_kg > self.warning_threshold_kg:
            return "HIGH_LOAD"
        return "NORMAL"

    def _read_simulated(self, now: float) -> Dict[str, Any]:
        dt = 0.1  # nominal tick; sensor state machine is time-order-based

        if self._boarding:
            step = min(self._px_delta_left, self._rng.uniform(20, 90))
            self.payload_kg += self._step_sign * step
            self._px_delta_left -= step
            if self._px_delta_left <= 0:
                self._px_delta_left = 0
                self._boarding = False
                self._boarding_left = 0.0
        else:
            self._next_boarding_in -= dt
            if self._next_boarding_in <= 0:
                self._boarding = True
                self._next_boarding_in = self._rng.uniform(6.0, 20.0)
                passengers = self._rng.randint(1, 9)
                self._step_sign = self._rng.choice([1, -1])
                self._px_delta_left = int(passengers * self._rng.uniform(55, 75))

        self.payload_kg = int(max(0, min(self.payload_kg, self.payload_limit_kg)))

        gvw_kg = self.tare_kg + self.payload_kg
        load_pct = round(self.payload_kg / self.payload_limit_kg * 100.0, 1)
        status = self._status_for(self.payload_kg)
        self.status = status

        return {
            "gvw_kg": gvw_kg,
            "tare_kg": self.tare_kg,
            "payload_kg": self.payload_kg,
            "payload_limit_kg": self.payload_limit_kg,
            "warning_threshold_kg": self.warning_threshold_kg,
            "load_pct": load_pct,
            "status": status,
        }


if __name__ == "__main__":
    load = LoadCellSensor()
    load.init()
    for _ in range(300):
        print(load.read())
        time.sleep(0.1)
    load.disable()