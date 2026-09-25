"""
cabin_detector.py
Cabin Camera Module for FLEET-IQ Live Prototype.

Placeholder abstraction structured so a real cabin vision model can be
inserted later. Does not fabricate detection accuracy.

Supports event categories:
- CABIN_FIRE
- CABIN_SMOKE
- CABIN_INCIDENT

Only generates events if an actual implemented detector produces them.
"""

import threading
import time
from datetime import datetime, timezone

# Lazy imports
cv2 = None
np = None


def _import_deps():
    global cv2, np
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
            pass
    return True


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CabinDetector:
    """
    Cabin camera placeholder module.

    Structure:
    - process_frame(frame) -> detections
    - Event generation only when real detector is implemented
    - Model status tracking
    """

    def __init__(self, event_callback=None):
        self._event_callback = event_callback
        self._lock = threading.Lock()
        self._model_loaded = False
        self._model_name = None
        self._running = False

        # Current state
        self._status = "MODEL NOT CONFIGURED"
        self._last_detection = None
        self._total_frames = 0
        self._detections = []

    @property
    def status(self):
        with self._lock:
            return self._status

    def load_model(self, model_path=None):
        """
        Load cabin detection model.
        Override this method with actual model loading logic.
        """
        with self._lock:
            self._status = "MODEL NOT CONFIGURED"
            self._model_loaded = False
            self._model_name = None

        print("[cabin_detector] CABIN AI: MODEL NOT CONFIGURED")
        print("[cabin_detector] To enable cabin detection, implement load_model()")
        return False

    def process_frame(self, frame):
        """
        Process a cabin camera frame.
        Override this method with actual detection logic.

        Returns list of detections: [{type, confidence, bbox}]
        """
        self._total_frames += 1

        if not self._model_loaded:
            return []

        # Placeholder: no detections when model is not loaded
        return []

    def draw_overlay(self, frame, detections=None):
        """Draw detection overlay on frame."""
        if not _import_cv2() or frame is None:
            return frame

        try:
            overlay = frame.copy()

            # Draw status
            if not self._model_loaded:
                cv2.putText(overlay, "CABIN AI: MODEL NOT CONFIGURED", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                cv2.putText(overlay, "No detections available", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            else:
                cv2.putText(overlay, f"Cabin AI: {self._model_name}", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(overlay, f"Frames: {self._total_frames}", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

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
                "total_frames": self._total_frames,
                "detection_count": len(self._detections),
            }


# Singleton instance
cabin_detector = CabinDetector()
