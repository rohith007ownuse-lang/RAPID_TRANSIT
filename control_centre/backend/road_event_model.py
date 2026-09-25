"""
road_event_model.py
Road Event Model — consistent road-event representation with honest source labeling.

Source vocabulary (strict):
    LIVE        — real hardware sensor / live camera AI model
    SIMULATION  — simulator-generated demo data
    HEURISTIC   — rule-based estimator (contour, threshold, classical CV)
    MODEL       — genuine trained ML model (YOLO, custom CNN, etc.)
    UNKNOWN     — insufficient information to classify

Never present SIMULATION as real. Never call HEURISTIC an AI model.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
import uuid


class RoadEventType(str, Enum):
    """Supported road event types (aligned with existing simulator/alerts)."""
    POTHOLE = "POTHOLE"
    ROAD_DAMAGE = "ROAD_DAMAGE"
    ROAD_HAZARD = "ROAD_HAZARD"
    ROAD_OBSTRUCTION = "ROAD_OBSTRUCTION"
    ROAD_DEFECT = "ROAD_DEFECT"  # grouped persistent defect
    OTHER = "OTHER"


class RoadEventSource(str, Enum):
    """Strict source classification — MUST be one of these."""
    LIVE = "LIVE"
    SIMULATION = "SIMULATION"
    HEURISTIC = "HEURISTIC"
    MODEL = "MODEL"
    UNKNOWN = "UNKNOWN"


class RoadEventSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RoadEventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVIEWING = "REVIEWING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


@dataclass
class RoadEvent:
    """Structured road event with honest source labeling."""
    event_id: str
    event_type: RoadEventType
    timestamp: str
    latitude: Optional[float]
    longitude: Optional[float]
    severity: RoadEventSeverity
    source: RoadEventSource
    confidence: Optional[float] = None  # 0.0-1.0, only for MODEL/HEURISTIC
    affected_route: Optional[str] = None
    affected_bus: Optional[str] = None
    status: RoadEventStatus = RoadEventStatus.ACTIVE
    additional_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "severity": self.severity.value,
            "source": self.source.value,
            "confidence": self.confidence,
            "affected_route": self.affected_route,
            "affected_bus": self.affected_bus,
            "status": self.status.value,
            "additional_data": self.additional_data,
        }

    @classmethod
    def create(
        cls,
        event_type: RoadEventType,
        latitude: Optional[float],
        longitude: Optional[float],
        severity: RoadEventSeverity,
        source: RoadEventSource,
        affected_bus: Optional[str] = None,
        affected_route: Optional[str] = None,
        confidence: Optional[float] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> "RoadEvent":
        """Factory method with validation."""
        # Validate source
        if not isinstance(source, RoadEventSource):
            raise ValueError(f"source must be RoadEventSource, got {type(source)}")

        # Validate confidence only for MODEL/HEURISTIC
        if confidence is not None:
            if source not in (RoadEventSource.MODEL, RoadEventSource.HEURISTIC):
                raise ValueError(f"confidence only allowed for MODEL/HEURISTIC sources, got {source}")
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence must be 0.0-1.0")

        # For SIMULATION, confidence must be None
        if source == RoadEventSource.SIMULATION and confidence is not None:
            confidence = None

        # Location unknown handling
        if latitude is None or longitude is None:
            latitude = None
            longitude = None

        return cls(
            event_id=str(uuid.uuid4())[:13],
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            latitude=latitude,
            longitude=longitude,
            severity=severity,
            source=source,
            confidence=confidence,
            affected_bus=affected_bus,
            affected_route=affected_route,
            additional_data=additional_data or {},
        )


@dataclass
class RoadCluster:
    """Cluster of road events representing the same physical road problem."""
    cluster_id: str
    representative_lat: float
    representative_lon: float
    radius_m: int
    event_count: int
    event_types: List[RoadEventType]
    severity: RoadEventSeverity  # worst severity in cluster
    first_detected: str
    last_detected: str
    affected_buses: List[str]
    affected_routes: List[str]
    source: RoadEventSource  # source of the cluster (dominant source)
    status: RoadEventStatus = RoadEventStatus.ACTIVE
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "representative_lat": self.representative_lat,
            "representative_lon": self.representative_lon,
            "radius_m": self.radius_m,
            "event_count": self.event_count,
            "event_types": [t.value for t in self.event_types],
            "severity": self.severity.value,
            "first_detected": self.first_detected,
            "last_detected": self.last_detected,
            "affected_buses": self.affected_buses,
            "affected_routes": self.affected_routes,
            "source": self.source.value,
            "status": self.status.value,
            "evidence": self.evidence,
        }


@dataclass
class RoadRiskZone:
    """A road risk zone with explicit reasoning."""
    zone_id: str
    lat: float
    lon: float
    radius_m: int
    risk_score: float  # 0-100
    risk_level: str  # LOW / MEDIUM / HIGH / CRITICAL
    defect_count: int
    total_detections: int
    routes_affected: List[str]
    affected_buses: List[str]
    top_defect_type: str
    evidence: str  # human-readable reasoning
    source: RoadEventSource  # dominant source of evidence
    first_detected: str
    last_detected: str
    status: RoadEventStatus = RoadEventStatus.ACTIVE

    def to_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": self.radius_m,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "defect_count": self.defect_count,
            "total_detections": self.total_detections,
            "routes_affected": self.routes_affected,
            "affected_buses": self.affected_buses,
            "top_defect_type": self.top_defect_type,
            "evidence": self.evidence,
            "source": self.source.value,
            "first_detected": self.first_detected,
            "last_detected": self.last_detected,
            "status": self.status.value,
        }


@dataclass
class RouteRisk:
    """Route-level risk from road intelligence."""
    route_id: str
    route_name: str
    risk_level: str  # LOW / MEDIUM / HIGH / CRITICAL
    avg_score: float
    zones_count: int
    total_defects: int
    active_hazards: int
    affected_segments: List[dict]  # segment info with lat/lon
    evidence: str
    last_updated: str
    source: RoadEventSource

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "route_name": self.route_name,
            "risk_level": self.risk_level,
            "avg_score": self.avg_score,
            "zones_count": self.zones_count,
            "total_defects": self.total_defects,
            "active_hazards": self.active_hazards,
            "affected_segments": self.affected_segments,
            "evidence": self.evidence,
            "last_updated": self.last_updated,
            "source": self.source.value,
        }


@dataclass
class BusExposure:
    """Bus exposure to road risk."""
    bus_id: str
    route_code: str
    current_lat: Optional[float]
    current_lon: Optional[float]
    exposure_state: str  # CLEAR / APPROACHING / EXPOSED / UNKNOWN
    nearby_zone_id: Optional[str] = None
    zone_risk_level: Optional[str] = None
    zone_distance_km: Optional[float] = None
    hazard_severity: Optional[str] = None
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "bus_id": self.bus_id,
            "route_code": self.route_code,
            "current_lat": self.current_lat,
            "current_lon": self.current_lon,
            "exposure_state": self.exposure_state,
            "nearby_zone_id": self.nearby_zone_id,
            "zone_risk_level": self.zone_risk_level,
            "zone_distance_km": self.zone_distance_km,
            "hazard_severity": self.hazard_severity,
            "evidence": self.evidence,
        }


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, sin, cos, sqrt, asin
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))


# Source label helpers for UI
SOURCE_LABELS = {
    RoadEventSource.LIVE: "🔴 LIVE",
    RoadEventSource.SIMULATION: "🟣 SIMULATION",
    RoadEventSource.HEURISTIC: "🟡 HEURISTIC",
    RoadEventSource.MODEL: "🟢 MODEL",
    RoadEventSource.UNKNOWN: "⚪ UNKNOWN",
}

SOURCE_COLORS = {
    RoadEventSource.LIVE: "#dc2626",
    RoadEventSource.SIMULATION: "#8b5cf6",
    RoadEventSource.HEURISTIC: "#d97706",
    RoadEventSource.MODEL: "#16a34a",
    RoadEventSource.UNKNOWN: "#6b7280",
}