"""
bus_state.py - BusState manager: real-time aggregation of every bus-node
source (driver AI, cameras, sensors, events) into one snapshot that later
streams to the Control Centre.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bus_node.data.event_model import Event

MAX_RECENT_EVENTS = 200


class BusState:
    """Holds the authoritative latest view of one bus."""

    def __init__(self, bus_id: str = "BUS-001", route: str = "Route 42 - Central Chennai"):
        self.bus_id = bus_id
        self.route = route

        # GPS / position
        self.latitude = 0.0
        self.longitude = 0.0
        self.speed_kmh = 0.0
        self.heading_deg = 0.0
        self.odometer_km = 0.0

        # Driver monitoring (from fatigue engine frame results)
        self.driver_status = "NO_DATA"
        self.driver_alert = False
        self.ear = 0.0
        self.mar = 0.0
        self.pitch = 0.0
        self.drowsy_percent = 0.0
        self.closed_time = 0.0
        self.brake_recommended = False
        self.brake_recommend_reason: Optional[str] = None

        # Load
        self.gvw_kg = 0
        self.tare_kg = 0
        self.payload_kg = 0
        self.payload_limit_kg = 0
        self.load_pct = 0.0
        self.load_status = "NORMAL"

        # Vehicle health (from IMU)
        self.health_status = "NORMAL"
        self.health_anomaly: Optional[str] = None
        self.impact_count = 0
        self.hard_braking_count = 0
        self.vibration_level = 0.0

        # Siren (from microphone)
        self.siren_detected = False
        self.siren_confidence = 0.0
        self.sound_level_db = 0.0

        # Subsystem states
        self.camera_status: List[Dict[str, Any]] = []
        self.sensor_status: List[Dict[str, Any]] = []

        # Recent events (bounded)
        self.events: List[Dict[str, Any]] = []

        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # -- ingestion -----------------------------------------------------------

    def update_sensor(self, reading: Dict[str, Any]) -> None:
        """Fold one labeled sensor reading into the bus state."""
        source = reading.get("source")
        if source == "gps":
            self.latitude = reading["latitude"]
            self.longitude = reading["longitude"]
            self.speed_kmh = reading["speed_kmh"]
            self.heading_deg = reading["heading_deg"]
            self.odometer_km = reading["odometer_km"]
        elif source == "imu":
            self._update_health(reading)
        elif source == "load_cell":
            self.gvw_kg = reading["gvw_kg"]
            self.tare_kg = reading["tare_kg"]
            self.payload_kg = reading["payload_kg"]
            self.payload_limit_kg = reading["payload_limit_kg"]
            self.load_pct = reading["load_pct"]
            self.load_status = reading["status"]
        elif source == "microphone":
            self.siren_detected = reading["siren_detected"]
            self.siren_confidence = reading["siren_confidence"]
            self.sound_level_db = reading["sound_level_db"]
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _update_health(self, reading: Dict[str, Any]) -> None:
        if reading.get("impact"):
            self.impact_count += 1
            self.health_status = "INSPECTION REQUIRED"
            self.health_anomaly = "crash/impact detected"
        if reading.get("hard_braking"):
            self.hard_braking_count += 1
        if self.hard_braking_count >= 5 and self.health_status == "NORMAL":
            self.health_status = "WARNING"
            self.health_anomaly = "repeated harsh braking"
        self.vibration_level = abs(reading.get("accel_z_g", 1.0) - 1.0)

    def update_driver(self, frame_result: Dict[str, Any]) -> None:
        """Absorb one FatigueEngine frame result."""
        self.driver_status = frame_result.get("status", "NO_DATA")
        self.ear = frame_result.get("ear", 0.0)
        self.mar = frame_result.get("mar", 0.0)
        self.pitch = frame_result.get("pitch", 0.0)
        self.drowsy_percent = frame_result.get("drowsy_percent", 0.0)
        self.closed_time = frame_result.get("closed_time", 0.0)
        self.brake_recommended = bool(frame_result.get("brake_recommended", False))
        self.brake_recommend_reason = frame_result.get("brake_recommend_reason")
        self.driver_alert = (
            frame_result.get("severity") in ("WARNING", "CRITICAL")
            or self.brake_recommended
        )
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def update_cameras(self, status_matrix: List[Dict[str, Any]]) -> None:
        self.camera_status = status_matrix

    def update_sensor_statuses(self, status_list: List[Dict[str, Any]]) -> None:
        self.sensor_status = status_list

    # -- events --------------------------------------------------------------

    def record_event(self, event: Event) -> Dict[str, Any]:
        """Store an event as a dict; returns the serialized copy."""
        d = event.to_dict()
        self.events.append(d)
        if len(self.events) > MAX_RECENT_EVENTS:
            self.events = self.events[-MAX_RECENT_EVENTS:]
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return d

    # -- output --------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bus_id": self.bus_id,
            "route": self.route,
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "speed_kmh": round(self.speed_kmh, 1),
            "heading_deg": round(self.heading_deg, 1),
            "odometer_km": round(self.odometer_km, 3),
            "driver": {
                "status": self.driver_status,
                "alert": self.driver_alert,
                "ear": round(self.ear, 3),
                "mar": round(self.mar, 3),
                "pitch": round(self.pitch, 3),
                "drowsy_percent": round(self.drowsy_percent, 1),
                "closed_time": round(self.closed_time, 2),
                "brake_recommended": self.brake_recommended,
                "brake_recommend_reason": self.brake_recommend_reason,
            },
            "load": {
                "gvw_kg": self.gvw_kg,
                "tare_kg": self.tare_kg,
                "payload_kg": self.payload_kg,
                "payload_limit_kg": self.payload_limit_kg,
                "load_pct": round(self.load_pct, 1),
                "status": self.load_status,
            },
            "vehicle": {
                "health": self.health_status,
                "anomaly": self.health_anomaly,
                "impact_count": self.impact_count,
                "hard_braking_count": self.hard_braking_count,
                "vibration": round(self.vibration_level, 3),
            },
            "siren": {
                "detected": self.siren_detected,
                "confidence": round(self.siren_confidence, 3),
                "sound_level_db": round(self.sound_level_db, 1),
            },
            "cameras": self.camera_status,
            "sensors": self.sensor_status,
            "recent_events": self.events,
            "updated_at": self.updated_at,
            "simulation": True,
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.to_dict()