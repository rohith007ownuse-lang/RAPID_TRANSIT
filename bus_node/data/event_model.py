"""
event_model.py - structured Event data model for the bus node.

Enums and string values align with the Control Centre event types so bus-node
events can stream directly into the dashboard in the WebSocket phase.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


class EventType(str, Enum):
    DRIVER_DROWSINESS = "DRIVER_DROWSINESS"
    CABIN_FIRE = "CABIN_FIRE"
    CABIN_SMOKE = "CABIN_SMOKE"
    CABIN_INCIDENT = "CABIN_INCIDENT"
    ROAD_DEFECT = "ROAD_DEFECT"
    POTHOLE = "POTHOLE"
    CRASH = "CRASH"
    EMERGENCY_SIREN = "EMERGENCY_SIREN"
    OVERLOAD = "OVERLOAD"
    VEHICLE_ANOMALY = "VEHICLE_ANOMALY"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class EventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Event:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    bus_id: str = "BUS-001"
    event_type: EventType = EventType.DRIVER_DROWSINESS
    timestamp: str = field(default_factory=utcnow_iso)
    latitude: float = 0.0
    longitude: float = 0.0
    severity: Severity = Severity.WARNING
    confidence: float = 0.0
    sensor_source: str = "driver_ai"     # driver_ai | gps | imu | load_cell | microphone
    status: EventStatus = EventStatus.ACTIVE
    additional_data: Dict[str, Any] = field(default_factory=dict)
    fusion_events: List[str] = field(default_factory=list)
    simulation: bool = True              # bus-node events are simulated at this stage

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "bus_id": self.bus_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "sensor_source": self.sensor_source,
            "status": self.status.value,
            "additional_data": self.additional_data,
            "fusion_events": self.fusion_events,
            "simulation": self.simulation,
        }


def new_event(bus_id: str, event_type: EventType, **kwargs) -> Event:
    """Factory: fill the fixed bus_id/type and let optional kwargs override."""
    defaults = dict(bus_id=bus_id, event_type=event_type)
    defaults.update(kwargs)
    return Event(**defaults)