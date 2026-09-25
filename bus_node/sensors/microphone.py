"""
microphone.py - audio / emergency-siren interface (USB mic; simulation mode).

SIMULATION: emits a baseline ambient dB level; occasionally generates a siren
detection when simulated confidence exceeds the configured threshold
(0.7 by default). Every event is labeled [SIMULATION].

Real audio capture + siren classification (e.g. waveform / CNN) is not
implemented: hardware not mounted.
"""

import time
from typing import Dict, Any

from bus_node.sensors.base_sensor import BaseSensor


class MicrophoneSensor(BaseSensor):
    kind = "microphone"
    sensor_name = "microphone"

    def __init__(self, simulation: bool = True,
                 siren_confidence_threshold: float = 0.7,
                 seed: int = 41):
        super().__init__(simulation=simulation)
        self.siren_confidence_threshold = siren_confidence_threshold
        self._rng = __import__("random").Random(seed)
        self._siren_active_until = 0.0

    def _read_simulated(self, now: float) -> Dict[str, Any]:
        if now < self._siren_active_until:
            confidence = self._rng.uniform(0.75, 0.99)
            siren_detected = confidence >= self.siren_confidence_threshold
            status = "SIREN_DETECTED" if siren_detected else "LISTENING"
            db = round(self._rng.uniform(78, 110), 1)
        else:
            if self._rng.random() < 0.012:
                confidence = self._rng.uniform(0.68, 0.99)
                siren_detected = confidence >= self.siren_confidence_threshold
                db = round(self._rng.uniform(75, 112), 1)
                self._siren_active_until = now + self._rng.uniform(1.0, 4.0)
            else:
                confidence = round(self._rng.uniform(0.01, 0.25), 3)
                siren_detected = False
                db = round(self._rng.uniform(55, 72), 1)
            status = "SIREN_DETECTED" if siren_detected else "LISTENING"

        self.status = status
        return {
            "siren_detected": siren_detected,
            "siren_confidence": round(confidence, 3),
            "siren_confidence_threshold": self.siren_confidence_threshold,
            "sound_level_db": db,
        }


if __name__ == "__main__":
    mic = MicrophoneSensor()
    mic.init()
    for _ in range(2000):
        r = mic.read()
        if r and r["siren_detected"]:
            print("SIREN", r)
        time.sleep(0.05)
    mic.disable()