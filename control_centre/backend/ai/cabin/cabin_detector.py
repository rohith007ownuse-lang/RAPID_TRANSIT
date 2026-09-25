"""
cabin_detector.py
Cabin Camera Module for FLEET-IQ Live Prototype.

Real hazard detection for the cabin camera: fire and smoke, using a trained
YOLOv8n model fine-tuned on the D-Fire dataset (models/best.pt).

IMPORTANT — Source Honesty:
- Trained fire/smoke model (models/best.pt) → source = MODEL.
- Without the model, NO detections are produced (never fabricated).
- Scope: fire + smoke only. Person-related anomaly detection (violence,
  weapons, falls) would need additional models and is NOT claimed here.

Event categories generated (confirmed detections only):
- CABIN_FIRE   (severity CRITICAL)
- CABIN_SMOKE  (severity HIGH)
"""

import os
import threading
import time
from datetime import datetime, timezone
from enum import Enum

# Lazy imports
cv2 = None
np = None
YOLO = None


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
            pass  # YOLO optional — without it there is no cabin detection
    return True


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CabinDetectorSource(Enum):
    """Honest source classification for this detector."""
    MODEL = "MODEL"  # trained D-Fire YOLO model (fire/smoke)


# Default configuration
# Trained fire/smoke model (YOLOv8n, D-Fire dataset). Lives next to this file
# under models/ so it survives project relocations.
CABIN_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "best.pt")
CABIN_MIN_CONFIDENCE = 0.4

# Temporal confirmation: fire escalates fast, so confirm on 2 consecutive
# frames; smoke is slower-moving, 3 frames.
FIRE_CONFIRMATION_FRAMES = 2
SMOKE_CONFIRMATION_FRAMES = 3

# D-Fire class order (verified against model.names at load; bare numeric
# labels fall back to this mapping).
DFIRE_CLASS_NAMES = {0: "fire", 1: "smoke"}


class CabinDetector:
    """
    Cabin camera hazard detection: fire + smoke via a trained YOLO model.

    Structure:
    - process_frame(frame) -> detections [{type, confidence, bbox}]
    - Temporal confirmation before any event fires
    - Event generation only from real model output (never fabricated)
    - Model status tracking (get_stats)
    """

    def __init__(self, event_callback=None):
        self._event_callback = event_callback
        self._lock = threading.Lock()
        self._model = None
        self._model_loaded = False
        self._model_name = None
        self._running = False

        # Current state
        self._status = "MODEL NOT CONFIGURED"
        self._last_detection = None
        self._total_frames = 0
        self._detections = []

        # Temporal confirmation buffers (per class)
        self._fire_buffer = []   # list of (timestamp, had_fire)
        self._smoke_buffer = []  # list of (timestamp, had_smoke)
        self._last_event_time = {}  # per event_type
        self._event_cooldown = 10.0  # seconds between events of the same type
        self._total_detections = 0
        self._confirmed_detections = 0

    @property
    def status(self):
        with self._lock:
            return self._status

    @property
    def detection_source(self) -> str:
        """Honest source label for this detector."""
        return CabinDetectorSource.MODEL.value

    def set_event_callback(self, fn):
        """Attach a callback invoked when a confirmed cabin hazard is detected."""
        with self._lock:
            self._event_callback = fn

    def load_model(self, model_path=None):
        """Load the trained fire/smoke YOLO model."""
        if not _import_deps():
            with self._lock:
                self._status = "DEPENDENCIES MISSING (opencv/ultralytics)"
            print("[cabin_detector] Dependencies not available")
            return False

        path = model_path or CABIN_MODEL_PATH

        if YOLO is None:
            with self._lock:
                self._status = "ULTRALYTICS NOT INSTALLED"
            print("[cabin_detector] ultralytics not installed — cabin hazard detection disabled")
            return False

        try:
            self._model = YOLO(path)
            self._model_loaded = True
            self._model_name = "D-Fire YOLOv8n (fire/smoke)"
            self._status = "ARMED (fire/smoke model)"
            print(f"[cabin_detector] Trained fire/smoke model loaded: {path} (source = MODEL)")
            return True
        except Exception as e:
            with self._lock:
                self._model_loaded = False
                self._status = f"MODEL LOAD FAILED: {e}"
            print(f"[cabin_detector] Failed to load YOLO model: {e}")
            return False

    def _class_label(self, cls_id):
        """Map a model class index to a readable label (D-Fire: fire/smoke)."""
        raw = None
        try:
            raw = self._model.names.get(cls_id)
        except Exception:
            pass
        if raw and not str(raw).isdigit():
            return str(raw).lower()
        return DFIRE_CLASS_NAMES.get(cls_id, "fire")

    def _prune(self, buffer, window=6.0):
        now = time.time()
        return [entry for entry in buffer if now - entry[0] < window]

    def _confirmed_and_ready(self, buffer, needed, event_type):
        """True when the last N frames all had the hazard and cooldown passed."""
        if len(buffer) < needed:
            return False
        recent = buffer[-needed:]
        if not all(flag for _, flag in recent):
            return False
        last = self._last_event_time.get(event_type, 0)
        return (time.time() - last) > self._event_cooldown

    def _trigger_event(self, event_type, detections, frame_ts):
        """Trigger a CABIN_FIRE / CABIN_SMOKE event via the callback."""
        if not self._event_callback:
            return

        best = max(detections, key=lambda d: d["confidence"])
        source = self.detection_source
        self._last_event_time[event_type] = frame_ts

        event = {
            "event_type": event_type,
            "bus_id": "PROTO-001",
            "camera_id": "cabin",
            "data_source": "live",
            "confidence": best.get("confidence"),
            "latitude": None,   # server callback fills bus GPS
            "longitude": None,
            "gps_status": "NO_FIX",
            "severity": "CRITICAL" if event_type == "CABIN_FIRE" else "HIGH",
            "sensor_source": f"cabin_{source.lower()}",
            "timestamp": utcnow_iso(),
            "additional_data": {
                "detection_count": len(detections),
                "total_detections": self._total_detections,
                "confirmed_detections": self._confirmed_detections,
                "detection_method": source,
                "hazard_class": best.get("type"),
                "note": "Cabin hazard detection via trained D-Fire YOLOv8n model (fire/smoke).",
            },
        }

        try:
            self._event_callback(event)
            print(f"[cabin_detector] Event triggered: {event_type} conf={best['confidence']:.3f}")
        except Exception as e:
            print(f"[cabin_detector] Event callback error: {e}")

    def process_frame(self, frame):
        """
        Process a cabin camera frame.

        Returns list of detections: [{type, confidence, bbox}]
        Fires CABIN_FIRE / CABIN_SMOKE events on temporal confirmation.
        """
        self._total_frames += 1

        if not self._model_loaded or self._model is None or frame is None:
            return []

        detections = []
        try:
            results = self._model(frame, verbose=False)
            for result in results:
                if result.boxes:
                    for box in result.boxes:
                        conf = float(box.conf[0])
                        if conf < CABIN_MIN_CONFIDENCE:
                            continue
                        cls = int(box.cls[0])
                        label = self._class_label(cls)
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        detections.append({
                            "type": label,          # "fire" | "smoke"
                            "confidence": round(conf, 3),
                            "bbox": [x1, y1, x2, y2],
                        })
        except Exception as e:
            print(f"[cabin_detector] Inference error: {e}")
            return []

        now = time.time()
        had_fire = any(d["type"] == "fire" for d in detections)
        had_smoke = any(d["type"] == "smoke" for d in detections)

        with self._lock:
            self._detections = detections
            self._total_detections += len(detections)
            if detections:
                self._last_detection = detections[0]

            self._fire_buffer = self._prune(self._fire_buffer + [(now, had_fire)])
            self._smoke_buffer = self._prune(self._smoke_buffer + [(now, had_smoke)])

        # Fire first — it is the more urgent hazard.
        if self._confirmed_and_ready(self._fire_buffer, FIRE_CONFIRMATION_FRAMES, "CABIN_FIRE"):
            fire_dets = [d for d in detections if d["type"] == "fire"] or detections
            self._confirmed_detections += 1
            self._trigger_event("CABIN_FIRE", fire_dets, now)
        elif self._confirmed_and_ready(self._smoke_buffer, SMOKE_CONFIRMATION_FRAMES, "CABIN_SMOKE"):
            smoke_dets = [d for d in detections if d["type"] == "smoke"] or detections
            self._confirmed_detections += 1
            self._trigger_event("CABIN_SMOKE", smoke_dets, now)

        return detections

    def draw_overlay(self, frame, detections=None):
        """Draw detection overlay on frame (red = fire, slate = smoke)."""
        if not _import_deps() or frame is None:
            return frame

        try:
            overlay = frame.copy()
            dets = detections if detections is not None else self._detections

            for d in dets or []:
                x1, y1, x2, y2 = d.get("bbox", [0, 0, 0, 0])
                is_fire = d.get("type") == "fire"
                color = (40, 40, 230) if is_fire else (160, 160, 160)
                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)
                label = f"{d.get('type', '?').upper()} {d.get('confidence', 0):.2f}"
                cv2.putText(overlay, label, (x1, max(20, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            status_color = (40, 40, 230) if any(d.get("type") == "fire" for d in dets or []) else (0, 200, 0)
            cv2.putText(overlay, f"Cabin AI: {self._model_name or 'not loaded'}", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)
            return overlay
        except Exception:
            return frame

    def get_stats(self):
        """Get detection statistics."""
        with self._lock:
            return {
                "model_loaded": self._model_loaded,
                "model_name": self._model_name,
                "status": self._status,
                "detection_source": self.detection_source,
                "total_frames": self._total_frames,
                "total_detections": self._total_detections,
                "confirmed_detections": self._confirmed_detections,
                "detection_count": len(self._detections),
                "current_detections": list(self._detections),
            }


# Singleton instance
cabin_detector = CabinDetector()
