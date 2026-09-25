"""
fusion_engine.py
Multi-Source Data Fusion Engine.

Combines GPS, camera detections, traffic hotspots, vehicle telemetry,
and road risk data into unified urban events with composite confidence
and evidence chains.

Instead of showing 4 separate alerts:
  "Pothole detected by Bus 127"
  "Traffic slowdown at Anna Salai"
  "Bus 127 speed reduced"
  "Road risk zone nearby"

The fusion engine produces ONE event:
  "Critical Traffic Event at Anna Salai"
  Confidence: 94%
  Sources: Camera (91%), GPS (confirmed), Traffic (3 buses slowed), Vehicle (speed reduced)

DATA CLASSIFICATION: RULE-BASED FUSION LAYER
Uses spatial/temporal correlation with source diversity scoring.
No ML model; this is an engineered heuristic fusion system.
"""

import threading
import math
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from constants import now_iso, now_utc, parse_timestamp


# ---------------------------------------------------------------------------
# Fusion configuration
# ---------------------------------------------------------------------------

# Spatial correlation radius (meters) — signals within this distance are fused
SPATIAL_CORRELATION_RADIUS_M = 100

# Temporal correlation window (seconds) — signals within this time window are fused
TEMPORAL_CORRELATION_WINDOW_S = 300  # 5 minutes

# Source diversity scoring — more independent sources = higher confidence
SOURCE_DIVERSITY_MULTIPLIER = {
    1: 1.0,    # single source: no boost
    2: 1.25,   # two sources: slight boost
    3: 1.5,    # three sources: moderate boost
    4: 1.7,    # four sources: strong boost
    5: 1.85,   # five sources: maximum boost
}

# Source confidence weights — how much we trust each source type
SOURCE_WEIGHTS = {
    "camera_pothole": 0.91,
    "camera_cabin": 0.85,
    "camera_driver": 0.88,
    "gps": 0.95,
    "traffic": 0.80,
    "vehicle_health": 0.75,
    "vehicle_load": 0.85,
    "road_risk": 0.70,
    "event": 0.82,
}

# Fused event type mappings
FUSED_EVENT_TYPES = {
    "camera+traffic+gps": "FUSED_TRAFFIC_EVENT",
    "camera+vehicle": "FUSED_SAFETY_EVENT",
    "camera+road_risk": "FUSED_ROAD_EVENT",
    "camera+gps+traffic+vehicle": "FUSED_EMERGENCY_EVENT",
    "default": "FUSED_URBAN_EVENT",
}

# Severity fusion rules
SEVERITY_RANK = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
SEVERITY_NAMES = {v: k for k, v in SEVERITY_RANK.items()}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    """Haversine distance in meters between two points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _classify_source(signal_type, event_type=None):
    """Classify a signal into a source category."""
    if signal_type == "camera_detection":
        if event_type == "POTHOLE":
            return "camera_pothole"
        elif event_type in ("CABIN_FIRE", "CABIN_SMOKE"):
            return "camera_cabin"
        elif event_type in ("DRIVER_DROWSINESS", "DRIVER_ALERT"):
            return "camera_driver"
        return "camera_pothole"
    elif signal_type == "gps_movement":
        return "gps"
    elif signal_type == "traffic_congestion":
        return "traffic"
    elif signal_type in ("vehicle_health", "vehicle_vibration"):
        return "vehicle_health"
    elif signal_type in ("vehicle_load", "overload"):
        return "vehicle_load"
    elif signal_type == "road_risk":
        return "road_risk"
    elif signal_type == "event":
        return "event"
    return "event"


def _determine_fused_event_type(source_categories):
    """Determine the fused event type from contributing source categories."""
    if len(source_categories) >= 4:
        return "FUSED_EMERGENCY_EVENT"
    key = "+".join(sorted(source_categories))
    return FUSED_EVENT_TYPES.get(key, FUSED_EVENT_TYPES["default"])


def _fuse_severity(severities, confidences):
    """Compute fused severity from multiple source severities."""
    if not severities:
        return "MEDIUM"
    # Weighted max: highest severity with confidence boost
    max_rank = 0
    for sev, conf in zip(severities, confidences):
        rank = SEVERITY_RANK.get(sev, 0)
        adjusted = rank * (0.8 + 0.2 * conf)
        max_rank = max(max_rank, adjusted)
    clamped = min(4, max(0, int(round(max_rank))))
    return SEVERITY_NAMES.get(clamped, "MEDIUM")


# ---------------------------------------------------------------------------
# Fused Event data model
# ---------------------------------------------------------------------------

class FusedEvent:
    """A unified event created by fusing multiple data sources."""

    def __init__(self, fusion_id=None, bus_id=None, latitude=None, longitude=None,
                 severity="MEDIUM", confidence=0.5, event_type="FUSED_URBAN_EVENT",
                 title="", description="", sources=None, evidence_chain=None):
        self.fusion_id = fusion_id or f"FUS-{str(uuid.uuid4())[:8]}"
        self.bus_id = bus_id
        self.latitude = latitude
        self.longitude = longitude
        self.severity = severity
        self.confidence = confidence
        self.event_type = event_type
        self.title = title
        self.description = description
        self.sources = sources or []
        self.evidence_chain = evidence_chain or []
        self.first_detected_at = now_iso()
        self.last_updated_at = self.first_detected_at
        self.status = "ACTIVE"
        self.source_count = len(self.sources)

    def to_dict(self):
        return {
            "fusion_id": self.fusion_id,
            "bus_id": self.bus_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "event_type": self.event_type,
            "title": self.title,
            "description": self.description,
            "sources": self.sources,
            "evidence_chain": self.evidence_chain,
            "source_count": self.source_count,
            "first_detected_at": self.first_detected_at,
            "last_updated_at": self.last_updated_at,
            "status": self.status,
        }

    def add_source(self, source_type, confidence, location=None, detail=None, event_id=None):
        self.sources.append({
            "type": source_type,
            "confidence": round(confidence, 3),
            "location": location,
            "detail": detail,
            "event_id": event_id,
            "timestamp": now_iso(),
        })
        self.source_count = len(self.sources)
        self.last_updated_at = now_iso()

    def add_evidence(self, step, source, detection, confidence=None, location=None, timestamp=None):
        self.evidence_chain.append({
            "step": step,
            "source": source,
            "detection": detection,
            "confidence": confidence,
            "location": location,
            "timestamp": timestamp or now_iso(),
        })

    def update_confidence(self):
        """Recompute fused confidence from all sources."""
        if not self.sources:
            self.confidence = 0.5
            return
        source_confs = [s["confidence"] for s in self.sources]
        base_confidence = max(source_confs)
        diversity = len(set(s["type"] for s in self.sources))
        multiplier = SOURCE_DIVERSITY_MULTIPLIER.get(min(diversity, 5), 1.0)
        self.confidence = min(0.99, base_confidence * multiplier)


# ---------------------------------------------------------------------------
# Multi-Source Fusion Engine
# ---------------------------------------------------------------------------

class MultiSourceFusionEngine:
    """
    Combines multiple data sources into unified urban events.

    Architecture:
    1. Ingest signals from GPS, camera, traffic, vehicle, road risk
    2. Spatial correlation (haversine clustering)
    3. Temporal correlation (time window)
    4. Source diversity scoring
    5. Fused event creation with evidence chain
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._recent_signals = []  # rolling window of recent signals
        self._fused_events = {}    # fusion_id -> FusedEvent
        self._stats = {
            "total_signals": 0,
            "total_fusions": 0,
            "fusions_by_type": {},
            "avg_sources_per_fusion": 0,
        }

    def ingest_signal(self, signal_type, bus_id, latitude, longitude,
                      severity="MEDIUM", confidence=0.8, event_type=None,
                      detail=None, event_id=None, timestamp=None):
        """
        Ingest a signal from any data source.

        Returns a list of FusedEvent objects if this signal triggered a fusion.
        """
        signal = {
            "type": signal_type,
            "bus_id": bus_id,
            "latitude": latitude,
            "longitude": longitude,
            "severity": severity,
            "confidence": confidence,
            "event_type": event_type,
            "detail": detail,
            "event_id": event_id,
            "timestamp": timestamp or now_iso(),
            "source_category": _classify_source(signal_type, event_type),
        }

        fused = []
        with self._lock:
            self._recent_signals.append(signal)
            self._stats["total_signals"] += 1

            # Prune old signals (> temporal window)
            self._prune_signals()

            # Try to fuse with recent signals
            fused = self._try_fuse(signal)

        return fused

    def _prune_signals(self):
        """Remove signals older than the temporal correlation window."""
        now = now_utc()
        cutoff = now - timedelta(seconds=TEMPORAL_CORRELATION_WINDOW_S)
        self._recent_signals = [
            s for s in self._recent_signals
            if parse_timestamp(s["timestamp"]) and parse_timestamp(s["timestamp"]) > cutoff
        ]

    def _try_fuse(self, new_signal):
        """Try to fuse the new signal with recent signals."""
        fused = []

        # Find spatially correlated signals
        spatial_matches = []
        for sig in self._recent_signals:
            if sig["bus_id"] == new_signal["bus_id"]:
                continue
            dist = _haversine_m(
                new_signal["latitude"], new_signal["longitude"],
                sig["latitude"], sig["longitude"]
            )
            if dist <= SPATIAL_CORRELATION_RADIUS_M:
                spatial_matches.append((sig, dist))

        # If we have spatial matches, create a fused event
        if spatial_matches:
            fused_event = self._create_fused_event(new_signal, spatial_matches)
            if fused_event:
                fused.append(fused_event)
        else:
            # Even without spatial matches, check if the signal itself
            # is significant enough to create a standalone fused event
            if new_signal["severity"] in ("CRITICAL", "HIGH"):
                fused_event = self._create_standalone_fused(new_signal)
                if fused_event:
                    fused.append(fused_event)

        return fused

    def _create_fused_event(self, new_signal, spatial_matches):
        """Create a fused event from correlated signals."""
        # Collect all source categories
        source_categories = {new_signal["source_category"]}
        severities = [new_signal["severity"]]
        confidences = [new_signal["confidence"]]
        all_sources = [new_signal]

        for sig, dist in spatial_matches:
            source_categories.add(sig["source_category"])
            severities.append(sig["severity"])
            confidences.append(sig["confidence"])
            all_sources.append(sig)

        # Determine fused event type
        event_type = _determine_fused_event_type(source_categories)

        # Fuse severity
        fused_severity = _fuse_severity(severities, confidences)

        # Compute confidence
        base_confidence = max(confidences)
        diversity = len(source_categories)
        multiplier = SOURCE_DIVERSITY_MULTIPLIER.get(min(diversity, 5), 1.0)
        fused_confidence = min(0.99, base_confidence * multiplier)

        # Compute location (weighted centroid)
        total_weight = sum(confidences)
        avg_lat = sum(s["latitude"] * c for s, c in zip(all_sources, confidences)) / total_weight
        avg_lon = sum(s["longitude"] * c for s, c in zip(all_sources, confidences)) / total_weight

        # Build title and description
        bus_ids = list(set(s["bus_id"] for s in all_sources))
        bus_label = f"Bus #{bus_ids[0]}" if len(bus_ids) == 1 else f"{len(bus_ids)} buses"
        title = f"Multi-Source {fused_severity} Event — {bus_label}"
        source_names = sorted(source_categories)
        description = (
            f"Fused event from {len(all_sources)} sources "
            f"({', '.join(source_names)}) with {fused_confidence:.0%} confidence"
        )

        fused_event = FusedEvent(
            bus_id=bus_ids[0] if len(bus_ids) == 1 else ",".join(bus_ids[:3]),
            latitude=avg_lat,
            longitude=avg_lon,
            severity=fused_severity,
            confidence=fused_confidence,
            event_type=event_type,
            title=title,
            description=description,
        )

        # Add sources and evidence
        step = 1
        for sig in all_sources:
            fused_event.add_source(
                source_type=sig["source_category"],
                confidence=sig["confidence"],
                location=(sig["latitude"], sig["longitude"]),
                detail=sig["detail"],
                event_id=sig.get("event_id"),
            )
            fused_event.add_evidence(
                step=step,
                source=sig["source_category"],
                detection=sig["event_type"] or sig["detail"] or sig["type"],
                confidence=sig["confidence"],
                location=(sig["latitude"], sig["longitude"]),
                timestamp=sig["timestamp"],
            )
            step += 1

        fused_event.update_confidence()

        # Store and update stats
        self._fused_events[fused_event.fusion_id] = fused_event
        self._stats["total_fusions"] += 1
        self._stats["fusions_by_type"][event_type] = (
            self._stats["fusions_by_type"].get(event_type, 0) + 1
        )

        return fused_event

    def _create_standalone_fused(self, signal):
        """Create a standalone fused event for a significant single-source signal."""
        event_type = signal["event_type"] or signal["type"]
        title = f"{signal['severity']} Event — Bus #{signal['bus_id']}"

        fused_event = FusedEvent(
            bus_id=signal["bus_id"],
            latitude=signal["latitude"],
            longitude=signal["longitude"],
            severity=signal["severity"],
            confidence=signal["confidence"],
            event_type=event_type,
            title=title,
            description=signal["detail"] or f"{signal['source_category']} detection",
        )

        fused_event.add_source(
            source_type=signal["source_category"],
            confidence=signal["confidence"],
            location=(signal["latitude"], signal["longitude"]),
            detail=signal["detail"],
            event_id=signal.get("event_id"),
        )
        fused_event.add_evidence(
            step=1,
            source=signal["source_category"],
            detection=event_type,
            confidence=signal["confidence"],
            location=(signal["latitude"], signal["longitude"]),
            timestamp=signal["timestamp"],
        )

        self._fused_events[fused_event.fusion_id] = fused_event
        self._stats["total_fusions"] += 1

        return fused_event

    def get_fused_events(self, limit=50, bus_id=None, severity=None):
        """Get recent fused events, optionally filtered."""
        with self._lock:
            events = list(self._fused_events.values())

        # Filter
        if bus_id:
            events = [e for e in events if e.bus_id == bus_id]
        if severity:
            events = [e for e in events if e.severity == severity]

        # Sort by detection time (newest first)
        events.sort(key=lambda e: e.first_detected_at or "", reverse=True)
        return [e.to_dict() for e in events[:limit]]

    def get_stats(self):
        """Get fusion engine statistics."""
        with self._lock:
            stats = dict(self._stats)
        stats["recent_signals"] = len(self._recent_signals)
        stats["active_fused_events"] = len(self._fused_events)
        if stats["total_fusions"] > 0:
            stats["avg_sources_per_fusion"] = round(
                stats["total_signals"] / max(1, stats["total_fusions"]), 1
            )
        return stats

    def evaluate_bus(self, bus, events=None, traffic_data=None, road_risk_data=None):
        """
        Evaluate a single bus and generate fused events from all available data.

        Returns a list of FusedEvent objects.
        """
        fused = []
        bus_id = bus.get("bus_id")
        lat = bus.get("latitude")
        lon = bus.get("longitude")

        if not lat or not lon:
            return fused

        # GPS signal (always present)
        speed = bus.get("speed_kmh", 0)
        self.ingest_signal(
            signal_type="gps_movement",
            bus_id=bus_id,
            latitude=lat,
            longitude=lon,
            severity="INFO" if speed < 50 else "WARNING",
            confidence=0.95,
            event_type="GPS_SPEED",
            detail=f"Speed: {speed:.0f} km/h",
        )

        # Vehicle health signal
        vehicle = bus.get("vehicle", {})
        if vehicle.get("health") in ("WARNING", "INSPECTION REQUIRED"):
            sev = "HIGH" if vehicle["health"] == "INSPECTION REQUIRED" else "WARNING"
            fused.extend(self.ingest_signal(
                signal_type="vehicle_health",
                bus_id=bus_id,
                latitude=lat,
                longitude=lon,
                severity=sev,
                confidence=0.75,
                event_type="VEHICLE_ANOMALY",
                detail=f"Health: {vehicle['health']}",
            ))

        # Load signal
        load = bus.get("load", {})
        if load.get("status") in ("HIGH LOAD", "CRITICAL OVERLOAD"):
            sev = "CRITICAL" if load["status"] == "CRITICAL OVERLOAD" else "WARNING"
            fused.extend(self.ingest_signal(
                signal_type="vehicle_load",
                bus_id=bus_id,
                latitude=lat,
                longitude=lon,
                severity=sev,
                confidence=0.85,
                event_type="OVERLOAD",
                detail=f"Load: {load['status']}",
            ))

        # Driver signal
        driver = bus.get("driver", {})
        if driver.get("state") in ("DROWSY", "ATTENTION"):
            sev = "CRITICAL" if driver["state"] == "DROWSY" else "WARNING"
            fused.extend(self.ingest_signal(
                signal_type="camera_driver",
                bus_id=bus_id,
                latitude=lat,
                longitude=lon,
                severity=sev,
                confidence=0.88,
                event_type="DRIVER_DROWSINESS",
                detail=f"Driver: {driver['state']}",
            ))

        # Events signal
        for evt in (events or []):
            if evt.get("bus_id") == bus_id and evt.get("severity") in ("CRITICAL", "HIGH"):
                fused.extend(self.ingest_signal(
                    signal_type="event",
                    bus_id=bus_id,
                    latitude=lat,
                    longitude=lon,
                    severity=evt["severity"],
                    confidence=evt.get("confidence", 0.8),
                    event_type=evt.get("event_type"),
                    detail=evt.get("details"),
                    event_id=evt.get("event_id"),
                ))

        # Traffic signal
        if traffic_data:
            hotspots = traffic_data if isinstance(traffic_data, list) else traffic_data.get("hotspots", [])
            for hs in hotspots:
                hs_lat = hs.get("latitude") or hs.get("lat")
                hs_lon = hs.get("longitude") or hs.get("lon")
                if hs_lat and hs_lon:
                    dist = _haversine_m(lat, lon, hs_lat, hs_lon)
                    if dist <= 500:  # within 500m of a hotspot
                        fused.extend(self.ingest_signal(
                            signal_type="traffic_congestion",
                            bus_id=bus_id,
                            latitude=lat,
                            longitude=lon,
                            severity="WARNING" if dist < 200 else "INFO",
                            confidence=0.8,
                            event_type="TRAFFIC_HOTSPOT",
                            detail=f"Hotspot {dist:.0f}m away",
                        ))

        return fused


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

fusion_engine = MultiSourceFusionEngine()
