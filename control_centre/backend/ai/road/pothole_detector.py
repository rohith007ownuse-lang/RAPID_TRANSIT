"""
pothole_detector.py
Pothole Detection Module for FLEET-IQ Live Prototype.

Receives frames from the configured road camera and runs pothole detection.

IMPORTANT — Source Honesty:
- This detector uses either:
  a) Contour-based classical CV (HEURISTIC) — default, no trained model
  b) YOLOv8n (COCO pre-trained) — generic object detector, NOT a trained pothole model
- The source is ALWAYS labeled HEURISTIC in events.
- Never presents detections as "AI model" or "ML" with fabricated confidence.
- A genuine trained pothole model would be MODEL source (not currently available).
"""

import threading
import time
from datetime import datetime, timezone
from enum import Enum

# Lazy imports
cv2 = None
np = None
YOLO = None


class PotholeDetectorSource(Enum):
    """Honest source classification for this detector."""
    HEURISTIC = "HEURISTIC"  # contour-based classical CV
    MODEL = "MODEL"          # genuine trained pothole model (not currently available)


def _import_deps():
    global cv2, np, YOLO
    if cv2 is None:
        try:
            import cv2 as _cv2
            cv2 = _cv2
        except ImportError:
            return False
    if np is None:
        try:
            import numpy as _np
            np = _np
        except ImportError:
            return False
    if YOLO is None:
        try:
            from ultralytics import YOLO as _YOLO
            YOLO = _YOLO
        except ImportError:
            pass  # YOLO optional, fallback to contour detection
    return True


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Default configuration
POTHOLE_CONFIRMATION_FRAMES = 3
POTHOLE_MIN_CONFIDENCE = 0.4
POTHOLE_MODEL_PATH = "yolov8n.pt"  # Generic COCO model — NOT a pothole model


class PotholeDetector:
    """
    Real-time pothole detection using contour-based HEURISTIC or generic YOLO fallback.

    Source Honesty:
    - Default mode: contour-based classical CV → source = HEURISTIC
    - YOLO mode: generic COCO YOLOv8n (not pothole-trained) → source = HEURISTIC
    - A genuine trained pothole model would be source = MODEL (not implemented)

    Features:
    - Contour-based detection (HEURISTIC)
    - YOLO inference when available (still HEURISTIC — generic model)
    - Temporal confirmation (N consecutive frames)
    - Bounding box visualization
    - GPS integration
    """

    def __init__(self, event_callback=None, gps_source=None):
        self._event_callback = event_callback
        self._gps_source = gps_source  # callable returning (lat, lon) or None
        self._lock = threading.Lock()
        self._running = False
        self._model = None
        self._model_loaded = False
        self._detection_source = PotholeDetectorSource.HEURISTIC

        # Temporal confirmation
        self._confirmation_frames = POTHOLE_CONFIRMATION_FRAMES
        self._detection_buffer = []  # list of recent detections
        self._last_event_time = 0
        self._event_cooldown = 10.0  # seconds between events

        # Current state
        self._current_detections = []
        self._total_detections = 0
        self._confirmed_detections = 0

    @property
    def confirmation_frames(self):
        return self._confirmation_frames

    @confirmation_frames.setter
    def confirmation_frames(self, value):
        if value > 0:
            self._confirmation_frames = value

    @property
    def detection_source(self) -> str:
        """Honest source label for this detector."""
        return self._detection_source.value

    def load_model(self, model_path=None):
        """Load YOLO model for pothole detection.

        NOTE: Even with YOLO loaded, source remains HEURISTIC because
        yolov8n.pt is a generic COCO model, not a trained pothole detector.
        """
        if not _import_deps():
            print("[pothole_detector] Dependencies not available")
            return False

        path = model_path or POTHOLE_MODEL_PATH

        if YOLO is not None:
            try:
                self._model = YOLO(path)
                self._model_loaded = True
                print(f"[pothole_detector] YOLO model loaded: {path} (source remains HEURISTIC — generic COCO model)")
                return True
            except Exception as e:
                print(f"[pothole_detector] Failed to load YOLO model: {e}")

        print("[pothole_detector] Using contour-based detection (HEURISTIC)")
        self._model_loaded = False
        return False

    def detect(self, frame, gps_data=None):
        """
        Run pothole detection on a frame.
        Returns list of detections: [{bbox, confidence, class_name, source}]
        """
        if not _import_deps() or frame is None:
            return []

        detections = []

        if self._model_loaded and self._model is not None:
            detections = self._detect_yolo(frame)
        else:
            detections = self._detect_contour(frame)

        # Add honest source label to each detection
        for det in detections:
            det["source"] = self.detection_source

        # Temporal confirmation
        now = time.time()
        self._detection_buffer.append({
            "detections": detections,
            "timestamp": now,
        })

        # Keep only recent detections
        self._detection_buffer = [
            d for d in self._detection_buffer
            if now - d["timestamp"] < 5.0  # 5 second window
        ]

        # Check for confirmed detection
        if len(self._detection_buffer) >= self._confirmation_frames:
            recent = self._detection_buffer[-self._confirmation_frames:]
            all_have_detections = all(len(d["detections"]) > 0 for d in recent)

            if all_have_detections and (now - self._last_event_time) > self._event_cooldown:
                # Confirmed detection!
                self._confirmed_detections += 1
                self._last_event_time = now
                self._trigger_event(detections, gps_data)

        self._current_detections = detections
        self._total_detections += len(detections)

        return detections

    def _detect_yolo(self, frame):
        """Run YOLO inference for pothole detection."""
        detections = []
        try:
            results = self._model(frame, verbose=False)
            for result in results:
                if result.boxes:
                    for box in result.boxes:
                        conf = float(box.conf[0])
                        if conf >= POTHOLE_MIN_CONFIDENCE:
                            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                            cls = int(box.cls[0])
                            class_name = self._model.names.get(cls, "pothole")
                            detections.append({
                                "bbox": [x1, y1, x2, y2],
                                "confidence": round(conf, 3),
                                "class_name": class_name,
                            })
        except Exception as e:
            print(f"[pothole_detector] YOLO error: {e}")
        return detections

    def _detect_contour(self, frame):
        """Fallback contour-based pothole detection."""
        detections = []
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                area = cv2.contourArea(contour)
                if 500 < area < 50000:  # reasonable pothole size
                    x, y, w, h = cv2.boundingRect(contour)
                    # Approximate confidence based on area
                    conf = min(0.9, area / 50000)
                    detections.append({
                        "bbox": [x, y, x + w, y + h],
                        "confidence": round(conf, 3),
                        "class_name": "pothole",
                    })

        except Exception as e:
            print(f"[pothole_detector] Contour detection error: {e}")
        return detections

    def _trigger_event(self, detections, gps_data):
        """Trigger a POTHOLE event via the event callback with honest source."""
        if not self._event_callback:
            return

        # Get GPS if available
        lat, lon = None, None
        if gps_data:
            lat, lon = gps_data.get("latitude"), gps_data.get("longitude")
        elif self._gps_source:
            try:
                gps = self._gps_source()
                if gps:
                    lat, lon = gps
            except Exception:
                pass

        # Use highest confidence detection
        best = max(detections, key=lambda d: d["confidence"])

        # Honest source: this detector is HEURISTIC (contour or generic YOLO)
        source = self.detection_source

        event = {
            "event_type": "POTHOLE",
            "bus_id": "PROTO-001",
            "camera_id": "road",
            "data_source": "live",
            "confidence": best["confidence"] if source == "HEURISTIC" else None,
            "latitude": lat,
            "longitude": lon,
            "gps_status": "FIX" if lat is not None else "NO_FIX",
            "severity": "MEDIUM" if best["confidence"] > 0.7 else "LOW",
            "sensor_source": f"road_{source.lower()}",  # e.g., "road_heuristic"
            "timestamp": utcnow_iso(),
            "additional_data": {
                "detection_count": len(detections),
                "total_detections": self._total_detections,
                "confirmed_detections": self._confirmed_detections,
                "detection_method": source,  # Explicit method for transparency
                "note": f"Pothole detection via {source.lower()} method (contour-based or generic YOLO). Not a trained pothole model.",
            },
        }

        try:
            self._event_callback(event)
            print(f"[pothole_detector] Event triggered: confidence={best['confidence']:.3f}, source={source}")
        except Exception as e:
            print(f"[pothole_detector] Event callback error: {e}")

    def draw_overlay(self, frame, detections=None):
        """Draw detection bounding boxes on frame."""
        if not _import_cv2() or frame is None:
            return frame

        try:
            overlay = frame.copy()
            dets = detections or self._current_detections

            for det in dets:
                x1, y1, x2, y2 = det["bbox"]
                conf = det["confidence"]

                # Color based on confidence
                if conf > 0.7:
                    color = (0, 0, 255)  # Red
                elif conf > 0.5:
                    color = (0, 165, 255)  # Orange
                else:
                    color = (0, 255, 255)  # Yellow

                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)
                cv2.putText(overlay, f"Pothole {conf:.2f}", (x1, y1 - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            # Draw stats
            cv2.putText(overlay, f"Detections: {self._total_detections}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(overlay, f"Confirmed: {self._confirmed_detections}", (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            return overlay

        except Exception:
            return frame

    def get_stats(self):
        """Get detection statistics with honest source labeling."""
        with self._lock:
            return {
                "total_detections": self._total_detections,
                "confirmed_detections": self._confirmed_detections,
                "current_detections": len(self._current_detections),
                "model_loaded": self._model_loaded,
                "confirmation_frames": self._confirmation_frames,
                "detection_source": self.detection_source,  # HEURISTIC (always)
                "note": "Source is HEURISTIC — contour-based classical CV or generic COCO YOLO. Not a trained pothole model.",
            }


# Singleton instance
pothole_detector = PotholeDetector()
