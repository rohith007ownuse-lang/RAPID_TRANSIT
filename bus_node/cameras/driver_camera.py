"""
driver_camera.py - real webcam capture for the DRIVER slot.

Wraps cv2.VideoCapture with a consistent start()/read()/release() contract so
the CameraManager can treat every slot uniformly. Produces BGR frames for the
downstream MediaPipe / Fatiguengine pipeline.
"""

import cv2


class DriverCamera:
    """Actual webcam capture used by the driver-monitoring pipeline."""

    slot = "DRIVER"
    kind = "webcam"

    def __init__(self, index: int = 0, width: int = 640, height: int = 480):
        self.index = index
        self.width = width
        self.height = height
        self.cap = None
        self.status = "OFF"  # OFF | ACTIVE | ERROR
        self.last_error = None
        self._failed_reads = 0

    def start(self) -> bool:
        """Open the webcam. Returns True if streaming is available."""
        try:
            cap = cv2.VideoCapture(self.index)
            if not cap.isOpened():
                cap.release()
                self.status = "ERROR"
                self.last_error = f"Cannot open camera index {self.index}"
                return False
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap = cap
            self.status = "ACTIVE"
            self.last_error = None
            self._failed_reads = 0
            return True
        except Exception as e:  # noqa: BLE001 - surface any open failure
            self.status = "ERROR"
            self.last_error = str(e)
            return False

    def read(self) -> tuple[bool, object]:
        """Grab one frame. Returns (ok, frame_bgr). frame is None on failure."""
        if self.cap is None:
            return False, None
        ok, frame = self.cap.read()
        if not ok:
            self._failed_reads += 1
            if self._failed_reads > 10:
                self.status = "ERROR"
                self.last_error = "repeated frame read failures"
            return False, None
        self._failed_reads = 0
        self.status = "ACTIVE"
        return True, frame

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.status = "OFF"

    def info(self) -> dict:
        return {
            "slot": self.slot,
            "kind": self.kind,
            "index": self.index,
            "resolution": [self.width, self.height],
            "status": self.status,
            "last_error": self.last_error,
        }