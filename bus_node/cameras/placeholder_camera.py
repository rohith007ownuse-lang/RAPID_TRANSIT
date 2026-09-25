"""
placeholder_camera.py - shared placeholder for not-yet-implemented camera slots.

CABIN and ROAD slots have no hardware/AI yet. Each placeholder presents a
consistent start()/read()/release() API (so CameraManager code paths stay
uniform) and returns a clearly-labeled frame that the future UI can render
instead of a dead tile.
"""

import cv2
import numpy as np


class PlaceholderCamera:
    """Marker frame generator for a planned camera slot."""

    slot = "PLACEHOLDER"
    kind = "planned"

    def __init__(self, active: bool = False, width: int = 640, height: int = 480):
        self.active = active
        self.width = width
        self.height = height
        self.status = "PLANNED"  # PLANNED | DISABLED
        if not active:
            self.status = "DISABLED"
        self.last_error = None

    def start(self) -> bool:
        """Placeholders never open hardware; the slot stays planned/disabled."""
        self.status = "PLANNED" if self.active else "DISABLED"
        return False

    def read(self) -> tuple[bool, object]:
        """Return (False, labeled_placeholder_frame)."""
        if not self.active:
            return False, self._placeholder_frame()
        return False, self._placeholder_frame()

    def release(self) -> None:
        self.status = "DISABLED" if not self.active else "PLANNED"

    def info(self) -> dict:
        return {
            "slot": self.slot,
            "kind": self.kind,
            "resolution": [self.width, self.height],
            "status": self.status,
            "last_error": self.last_error,
        }

    def _placeholder_frame(self) -> object:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (34, 42, 56)  # BGR dark slate
        cv2.putText(
            frame, "[NO CAMERA]", (170, 225),
            cv2.FONT_HERSHEY_SIMPLEX, 1.1, (130, 215, 255), 2,
        )
        cv2.putText(
            frame, f"{self.slot} slot - PLANNED", (175, 265),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1,
        )
        return frame