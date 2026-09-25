"""
base_sensor.py - shared contract for all bus-node sensors.

Every sensor implements:
    init()          -> open/prepare the sensor (simulation: no-op init)
    read()          -> one reading dict (always labeled source + simulation flag)
    get_status()    -> status/summary dict for bus state & logs
    enable()/disable()   -> routing control

Simulation flag comes from config (`sensors.<name>.simulation`, or the global
`simulation_mode`). Even in simulation mode every reading is explicitly labeled
`"simulation": true` and `"source": <sensor>` so downstream consumers can never
mistake synthetic data for real hardware measurements.
"""

import time
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseSensor(ABC):
    """Base class for all sensor interfaces."""

    kind = "unknown"
    sensor_name = "base"

    def __init__(self, simulation: bool = True):
        self.simulation = bool(simulation)
        self.enabled = True
        self.status = "INIT"          # INIT | ACTIVE | ERROR | DISABLED
        self.last_error: str | None = None
        self.last_read_at: str | None = None
        self.last_reading: Dict[str, Any] | None = None

    # -- lifecycle -----------------------------------------------------------

    def init(self) -> bool:
        """Prepare the sensor. Simulation sensors never touch hardware."""
        if self.simulation:
            self.status = "ACTIVE"
            self.last_error = None
            return True
        # Real-hardware branch: hardware not mounted yet.
        self.status = "ERROR"
        self.last_error = "Real hardware not mounted (simulation only)"
        return False

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    # -- reading -------------------------------------------------------------

    @abstractmethod
    def _read_simulated(self, now: float) -> Dict[str, Any]:
        """Produce one synthetic reading. Must be labeled source+simulation."""

    def read(self) -> Dict[str, Any] | None:
        """Return one labeled reading, or None if disabled/errored."""
        if not self.enabled:
            return None
        if self.status == "ERROR":
            return None
        now = time.time()
        try:
            reading = self._read_simulated(now)
        except Exception as e:  # noqa: BLE001
            self.status = "ERROR"
            self.last_error = str(e)
            return None
        reading.setdefault("source", self.kind)
        reading["sensor"] = self.sensor_name
        reading["simulation"] = self.simulation
        self.last_reading = reading
        self.last_read_at = time.strftime("%H:%M:%S")
        return reading

    # -- status --------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "sensor": self.sensor_name,
            "kind": self.kind,
            "simulation": self.simulation,
            "enabled": self.enabled,
            "status": self.status,
            "last_error": self.last_error,
            "last_read_at": self.last_read_at,
        }