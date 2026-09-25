"""
event_fusion.py - correlates raw detections/sensor events into structured
incident events with severity escalation and deduplication.

Rules implemented (per plan):
  - IMU impact + speed over threshold        -> CRASH (escalated to CRITICAL)
  - Driver drowsy detected while moving      -> DRIVER_DROWSINESS HIGH ALERT
  - Overload + harsh braking at same tick    -> OVERLOAD compound risk
  - Siren confidence over threshold          -> EMERGENCY_SIREN
  - Repeated pothole detections near same    -> ONE persistent ROAD_DEFECT
    location within a time window              (dedup, count increments)

Edge-triggering prevents event spam: state transitions (not every frame) emit.
All emitted events carry simulation=True until real sources exist.
"""

import math
import time
from typing import Dict, List, Optional

from bus_node.data.bus_state import BusState
from bus_node.data.event_model import Event, EventType, Severity, new_event


class FusionEngine:
    def __init__(self, bus_id: str = "BUS-001",
                 crash_speed_threshold_kmh: float = 30.0,
                 pothole_merge_radius_m: float = 30.0,
                 pothole_merge_window_s: float = 20.0):
        self.bus_id = bus_id
        self.crash_speed_threshold_kmh = crash_speed_threshold_kmh
        self.pothole_merge_radius_m = pothole_merge_radius_m
        self.pothole_merge_window_s = pothole_merge_window_s

        # edge-trigger bookkeeping
        self._driver_alert_active = False
        self._siren_active = False
        self._overload_armed = False
        self._last_crash_event_id: Optional[str] = None
        self._pothole_anchors: List[Dict] = []   # fused potential potholes

    # -- public --------------------------------------------------------------

    def evaluate(
        self,
        bus: BusState,
        sensor_readings: Optional[Dict[str, Dict]] = None,
        road_detections: Optional[List[Dict]] = None,
    ) -> List[Event]:
        """Fold current state + readings into new/fused events."""
        events: List[Event] = []
        sensor_readings = sensor_readings or {}

        imu = sensor_readings.get("imu") or {}
        load = sensor_readings.get("load_cell") or {}
        mic = sensor_readings.get("microphone") or {}
        speed = bus.speed_kmh

        # -- crash / impact correlated with speed
        if imu.get("impact"):
            severity = Severity.CRITICAL if speed >= self.crash_speed_threshold_kmh else Severity.WARNING
            ev = new_event(
                self.bus_id, EventType.CRASH,
                severity=severity,
                confidence=min(0.99, abs(imu.get("magnitude_g", 1.0)) / 4.0),
                sensor_source="imu",
                latitude=bus.latitude, longitude=bus.longitude,
                additional_data={
                    "magnitude_g": imu.get("magnitude_g"),
                    "speed_kmh": speed,
                    "brake_recommended": bus.brake_recommended,
                },
            )
            if bus.brake_recommended:
                ev.fusion_events.append("DRIVER_BRAKE_RECOMMENDATION")
            events.append(ev)
            self._last_crash_event_id = ev.event_id

        # -- driver drowsiness while moving (high alert)
        if bus.driver_alert and not self._driver_alert_active:
            severity = Severity.CRITICAL if speed > 0 else Severity.WARNING
            events.append(new_event(
                self.bus_id, EventType.DRIVER_DROWSINESS,
                severity=severity,
                confidence=min(0.99, bus.drowsy_percent / 100.0),
                sensor_source="driver_ai",
                latitude=bus.latitude, longitude=bus.longitude,
                additional_data={
                    "drowsy_percent": bus.drowsy_percent,
                    "closed_time": bus.closed_time,
                    "ear": bus.ear,
                    "mar": bus.mar,
                    "speed_kmh": speed,
                    "brake_recommended": bus.brake_recommended,
                    "brake_recommend_reason": bus.brake_recommend_reason,
                },
            ))
        self._driver_alert_active = bus.driver_alert

        # -- overload + harsh braking = compound risk
        if load.get("status") in ("OVERLOAD", "CRITICAL_OVERLOAD"):
            self._overload_armed = True
            if imu.get("hard_braking") and self._overload_armed:
                events.append(new_event(
                    self.bus_id, EventType.OVERLOAD,
                    severity=Severity.CRITICAL,
                    confidence=min(0.99, (bus.load_pct or 0) / 100.0 + 0.1),
                    sensor_source="load_cell",
                    latitude=bus.latitude, longitude=bus.longitude,
                    additional_data={
                        "payload_kg": bus.payload_kg,
                        "gvw_kg": bus.gvw_kg,
                        "load_pct": bus.load_pct,
                        "harsh_braking": True,
                    },
                    fusion_events=["VEHICLE_ANOMALY_HARSH_BRAKING"],
                ))
                self._overload_armed = False
        else:
            self._overload_armed = False

        # -- emergency siren (edge-triggered)
        if mic.get("siren_detected") and not self._siren_active:
            events.append(new_event(
                self.bus_id, EventType.EMERGENCY_SIREN,
                severity=Severity.WARNING,
                confidence=float(mic.get("siren_confidence", 0.0)),
                sensor_source="microphone",
                latitude=bus.latitude, longitude=bus.longitude,
                additional_data={
                    "sound_level_db": mic.get("sound_level_db"),
                    "confidence": mic.get("siren_confidence"),
                },
            ))
        self._siren_active = bool(mic.get("siren_detected"))

        # -- pothole/road-defect dedup (future Road AI slot)
        for det in road_detections or []:
            events.append(self._deduped_road_defect(det))

        return events

    # -- road-defect dedup ---------------------------------------------------

    def _deduped_road_defect(self, det: Dict) -> Event:
        now = time.time()
        lat, lon = det["latitude"], det["longitude"]
        for anchor in self._pothole_anchors:
            if now - anchor["time"] > self.pothole_merge_window_s:
                continue
            dist = self._haversine(lat, lon, anchor["latitude"], anchor["longitude"])
            if dist <= self.pothole_merge_radius_m:
                anchor["count"] += 1
                anchor["time"] = now
                anchor["last_confidence"] = max(anchor["last_confidence"], float(det.get("confidence", 0.9)))
                return new_event(
                    self.bus_id, EventType.ROAD_DEFECT,
                    severity=Severity.INFO,
                    confidence=anchor["last_confidence"],
                    sensor_source="road_ai",
                    latitude=anchor["latitude"], longitude=anchor["longitude"],
                    additional_data={
                        "defect_type": det.get("type", "pothole"),
                        "detection_count": anchor["count"],
                        "fused": True,
                    },
                )
        self._pothole_anchors.append({
            "latitude": lat, "longitude": lon, "time": now,
            "count": 1, "last_confidence": float(det.get("confidence", 0.9)),
        })
        return new_event(
            self.bus_id, EventType.ROAD_DEFECT,
            severity=Severity.INFO,
            confidence=float(det.get("confidence", 0.9)),
            sensor_source="road_ai",
            latitude=lat, longitude=lon,
            additional_data={"defect_type": det.get("type", "pothole"), "detection_count": 1, "fused": False},
        )

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6_371_000.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    def reset(self) -> None:
        self._driver_alert_active = False
        self._siren_active = False
        self._overload_armed = False
        self._pothole_anchors = []


def demo() -> None:
    """Headless verification of the fusion rules with synthetic inputs."""
    from bus_node.data.bus_state import BusState

    engine = FusionEngine("BUS-001")
    bus = BusState("BUS-001")
    hits = []

    # 1) driver drowsy while moving -> CRASH? no: DRIVER_DROWSINESS CRITICAL
    bus.update_driver({"status": "DROWSINESS", "drowsy_percent": 80, "severity": "CRITICAL",
                       "brake_recommended": True, "brake_recommend_reason": "eye_closure"})
    bus.update_sensor({"source": "gps", "latitude": 13.0827, "longitude": 80.2747,
                       "speed_kmh": 42, "heading_deg": 90.0, "odometer_km": 1.0})
    evs = engine.evaluate(bus, {"gps": {}})
    hits += [(e.event_type.value, e.severity.value) for e in evs]

    # 2) IMU impact at speed -> CRASH CRITICAL
    bus.update_driver({"status": "NORMAL", "drowsy_percent": 5, "severity": None})
    evs = engine.evaluate(bus, {"imu": {"impact": True, "magnitude_g": 3.9, "hard_braking": False},
                               "gps": {"speed_kmh": 42}})
    hits += [(e.event_type.value, e.severity.value) for e in evs]

    # 3) overload + harsh braking -> OVERLOAD compound
    bus.load_status = "OVERLOAD"
    bus.payload_kg = 6300
    bus.load_pct = 105
    bus.gvw_kg = 17300
    evs = engine.evaluate(bus, {"load_cell": {"status": "OVERLOAD"},
                               "imu": {"hard_braking": True, "impact": False}})
    hits += [(e.event_type.value, e.severity.value) for e in evs]

    # 4) siren -> EMERGENCY_SIREN
    evs = engine.evaluate(bus, {"microphone": {"siren_detected": True, "siren_confidence": 0.85, "sound_level_db": 96}})
    hits += [(e.event_type.value, e.severity.value) for e in evs]

    # 5) pothole dedup: two near detections -> two events, second fused w/ count 2
    det = {"latitude": 13.0830, "longitude": 80.2750, "type": "pothole", "confidence": 0.88}
    e1 = engine.evaluate(bus, None, road_detections=[det])[0]
    e2 = engine.evaluate(bus, None, road_detections=[det])[0]
    fused = e2.additional_data["detection_count"] == 2 and e2.additional_data["fused"] is True

    print("fusion demo results:")
    for h in hits:
        print("   ", h)
    print("   ", ("ROAD_DEFECT", "INFO", "count=2", fused))
    expected = [
        ("DRIVER_DROWSINESS", "CRITICAL"),
        ("CRASH", "CRITICAL"),
        ("OVERLOAD", "CRITICAL"),
        ("EMERGENCY_SIREN", "WARNING"),
    ]
    assert hits == expected, f"mismatch: {hits}"
    assert fused, "pothole dedup failed"
    print("ALL FUSION CHECKS PASSED")


if __name__ == "__main__":
    demo()