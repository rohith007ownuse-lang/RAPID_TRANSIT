"""
camera_manager.py
Camera + AI Perception engine for FLEET-IQ Live Prototype.

Captures webcam frames and routes them to the correct AI module:
  Driver Camera → Driver DDS (EAR/MAR/drowsiness)
  Cabin Camera  → Cabin Detector (placeholder — no fabrication)
  Road Camera   → Pothole Detector (YOLO/contour)

Phase 6 — multi-camera architecture:
  * Each camera slot ("driver", "cabin") is an independent CameraSource with its
    own capture thread, state, measured FPS and error channel. One camera failing
    to open or dying at runtime never affects another camera's loop.
  * Honest status: a missing/disabled cabin camera reports DISCONNECTED (or
    DISABLED from config). No synthetic frames, no fabricated resolution/FPS.
  * Single-camera test mode (one device feeding one module at a time) is retained
    and remains the harness that lets one shared camera exercise every slot.
  * The legacy manager-level fields (_cap/_frame/_annotated_frame/_active_slot/
    _mode/_running/_cameras/_measurements) are preserved as the compatibility view
    onto the primary capture, so existing tests and streaming code keep working.

Configuration (env, default in brackets):
  FLEETIQ_DRIVER_CAMERA_DEVICE : "0"            (int index or device path/URL)
  FLEETIQ_CABIN_CAMERA_DEVICE  : "1"            ("none"/"off" disables the slot)
  FLEETIQ_ROAD_CAMERA_DEVICE   : "0"
  FLEETIQ_CAMERA_BUS_ID        : "PROTO-001"    (bus these cameras belong to)
"""

import os
import threading
import time
from datetime import datetime, timezone

cv2 = None


def _import_cv2():
    global cv2
    if cv2 is None:
        try:
            import cv2 as _cv2
            cv2 = _cv2
        except ImportError:
            print("[camera_manager] WARNING: opencv-python not installed")
            return False
    return cv2 is not None


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SLOT_DRIVER = "driver"
SLOT_CABIN = "cabin"
SLOT_ROAD = "road"
ALL_SLOTS = [SLOT_DRIVER, SLOT_CABIN, SLOT_ROAD]

_SLOT_META = {
    SLOT_DRIVER: {
        "camera_id": "CAM-DRV-001", "camera_type": "driver",
        "env": "FLEETIQ_DRIVER_CAMERA_DEVICE", "default_device": "0",
    },
    SLOT_CABIN: {
        "camera_id": "CAM-CAB-001", "camera_type": "cabin",
        "env": "FLEETIQ_CABIN_CAMERA_DEVICE", "default_device": "1",
    },
    SLOT_ROAD: {
        "camera_id": "CAM-RD-001", "camera_type": "road",
        "env": "FLEETIQ_ROAD_CAMERA_DEVICE", "default_device": "0",
    },
}


def _resolve_camera_device(slot):
    """Return the env-configured device for a slot (int index, path or URL).

    Returns None for "none"/"off" — the slot is then configured as disabled and
    will honestly report DISABLED rather than pretending to be connected.
    """
    meta = _SLOT_META[slot]
    raw = (os.environ.get(meta["env"], meta["default_device"]) or "").strip()
    if not raw or raw.lower() in ("none", "off", "disabled"):
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def _bus_id():
    return os.environ.get("FLEETIQ_CAMERA_BUS_ID", "PROTO-001")


class CameraSource:
    """One physical camera with its own capture thread and state.

    Lifecycle is fully independent per source: opening, frame delivery, measured
    FPS and errors belong to this camera alone.
    """

    def __init__(self, slot, camera_id, camera_type, device_index, enabled):
        self.slot = slot
        self.camera_id = camera_id
        self.camera_type = camera_type
        self.bus_id = _bus_id()
        self.device_index = device_index  # int index, device path string, or None
        self.enabled = enabled
        self.state = "STOPPED"
        self.error = None
        self.cap = None
        self.thread = None
        self.running = False
        self.frame = None
        self.annotated_frame = None
        self.frame_lock = threading.Lock()
        self.last_frame_time = None
        self.measured_fps = None
        self._frames_in_window = 0
        self._fps_window_start = time.monotonic()

    def device_num(self):
        """Consumer-facing device label (int for an index, str for a path)."""
        if isinstance(self.device_index, int):
            return self.device_index
        return self.device_index or None

    def _track_fps(self):
        """Sample the real loop frame rate over a rolling window (2s)."""
        now = time.monotonic()
        self._frames_in_window += 1
        elapsed = now - self._fps_window_start
        if elapsed >= 2.0:
            self.measured_fps = round(self._frames_in_window / elapsed, 1)
            self._frames_in_window = 0
            self._fps_window_start = now


class CameraManager:
    def __init__(self):
        self._lock = threading.Lock()
        # Legacy single-camera surface (kept for compatibility)
        self._cameras = {}
        self._active_slot = None
        self._mode = "stopped"
        self._test_mode = True
        self._test_slot = SLOT_DRIVER
        self._running = False
        self._thread = None
        self._cap = None
        self._frame = None
        self._frame_lock = threading.Lock()

        # Phase 6: per-camera sources (lazily created when a slot is used)
        self._sources = {}
        self._slot_annotated = {}

        # AI modules (lazy loaded)
        self._driver_detector = None
        self._pothole_detector = None
        self._cabin_detector = None

        # Detection results per slot
        self._detection_results = {
            SLOT_DRIVER: {},
            SLOT_ROAD: [],
            SLOT_CABIN: [],
        }
        self._detection_lock = threading.Lock()

        # Annotated frame (with bounding boxes drawn)
        self._annotated_frame = None

        # Real capture-rate tracking (measured FPS, honest — never assumed)
        self._measured_fps = None
        self._frames_in_window = 0
        self._fps_window_start = time.monotonic()

    @property
    def mode(self):
        with self._lock:
            return self._mode

    @property
    def test_mode(self):
        with self._lock:
            return self._test_mode

    @property
    def test_slot(self):
        with self._lock:
            return self._test_slot

    def _get_source(self, slot):
        """Return (creating on first use) the CameraSource for a slot."""
        src = self._sources.get(slot)
        if src is None:
            meta = _SLOT_META[slot]
            device = _resolve_camera_device(slot)
            src = CameraSource(slot, meta["camera_id"], meta["camera_type"],
                               device, device is not None)
            self._sources[slot] = src
        return src

    def _ensure_ai_modules(self):
        """Link the SHARED AI module singletons (same instances the API controls).

        Using the module-level singletons matters: the REST endpoints
        (e.g. /api/dds/calibrate, /api/ai/status) configure and read the
        singletons, so the capture loop must run detection on the very same
        objects or phase/state changes never reach the frames.
        """
        if self._driver_detector is None:
            try:
                from ai.driver.driver_drowsiness import driver_detector as _driver
                self._driver_detector = _driver
                print("[camera_manager] Driver DDS engine linked (shared singleton)")
            except Exception as e:
                print(f"[camera_manager] Driver DDS failed: {e}")

        if self._pothole_detector is None:
            try:
                from ai.road.pothole_detector import pothole_detector as _pothole
                self._pothole_detector = _pothole
                print("[camera_manager] Pothole detector linked (shared singleton)")
            except Exception as e:
                print(f"[camera_manager] Pothole detector failed: {e}")

        if self._cabin_detector is None:
            try:
                from ai.cabin.cabin_detector import cabin_detector as _cabin
                self._cabin_detector = _cabin
                print("[camera_manager] Cabin detector linked (shared singleton)")
            except Exception as e:
                print(f"[camera_manager] Cabin detector failed: {e}")

    def open_shared_camera(self):
        """Pre-open driver camera in main process (call at server startup, NOT in a thread)."""
        if not _import_cv2():
            print("[camera_manager] OpenCV not available for shared camera")
            return False
        try:
            self._cap = cv2.VideoCapture(_resolve_camera_device(SLOT_DRIVER) or 0)
            if not self._cap.isOpened():
                self._cap = None
                print("[camera_manager] Failed to open shared camera")
                return False
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            # Read one frame to confirm it works
            ret, _ = self._cap.read()
            if not ret:
                self._cap.release()
                self._cap = None
                print("[camera_manager] Camera opened but cannot read frames")
                return False
            print("[camera_manager] Shared camera opened successfully")
            return True
        except Exception as e:
            print(f"[camera_manager] Shared camera error: {e}")
            return False

    def set_single_camera_test_mode(self, test_slot):
        if test_slot not in ALL_SLOTS:
            return False, f"Invalid slot: {test_slot}. Use: {ALL_SLOTS}"

        with self._lock:
            self._test_mode = True
            self._test_slot = test_slot

            # Stop existing capture
            self._stop_all_capture_locked()

            # Load AI modules
            self._ensure_ai_modules()

            src = self._get_source(test_slot)
            if not src.enabled:
                return False, f"Camera for slot '{test_slot}' is disabled via configuration"

            ok, msg = self._start_source_locked(src)
            if not ok:
                return False, msg

            self._active_slot = test_slot
            self._mode = "single_camera"
            self._running = True
            self._thread = src.thread

            print(f"[camera_manager] Camera started for {test_slot}")
            return True, f"Test mode: camera feeding {test_slot}"

    def set_multi_camera_mode(self):
        """Start the driver + cabin cameras as independent sources (Phase 6).

        A camera that cannot open (or is disabled via config) is reported
        honestly and does not prevent the other camera from running.
        """
        with self._lock:
            self._stop_all_capture_locked()
            self._test_mode = False
            self._test_slot = None
            self._ensure_ai_modules()

            started = []
            unavailable = []
            for slot in (SLOT_DRIVER, SLOT_CABIN):
                src = self._get_source(slot)
                if not src.enabled:
                    unavailable.append(slot)
                    continue
                ok, _msg = self._start_source_locked(src)
                if ok:
                    started.append(slot)
                else:
                    unavailable.append(slot)

            if not started:
                self._mode = "stopped"
                self._running = False
                self._active_slot = None
                self._cameras.clear()
                print("[camera_manager] Multi-camera: no cameras available")
                return False, "No cameras available"

            self._mode = "multi_camera"
            self._running = True
            self._active_slot = SLOT_DRIVER
            self._thread = self._get_source(SLOT_DRIVER).thread

            detail = f"Multi-camera active: {', '.join(started)}"
            if unavailable:
                detail += f"; unavailable: {', '.join(unavailable)}"
            print(f"[camera_manager] {detail}")
            return True, detail

    def _start_source_locked(self, src):
        """Open the source camera (if needed) and launch its capture thread."""
        if not _import_cv2():
            src.state = "ERROR"
            src.error = "OpenCV not available"
            return False, "OpenCV not available"
        if src.cap is None or not src.cap.isOpened():
            try:
                cap = cv2.VideoCapture(src.device_index or 0)
                if not cap.isOpened():
                    src.error = (f"Failed to open camera on device "
                                 f"{src.device_index!r}")
                    src.state = "DISCONNECTED"
                    return False, "Failed to open camera"
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                src.cap = cap
            except Exception as e:
                src.state = "ERROR"
                src.error = str(e)
                return False, str(e)

        if src.slot == SLOT_DRIVER:
            self._cap = src.cap

        src.running = True
        src.error = None
        src.state = "CONNECTED"
        src.thread = threading.Thread(target=self._capture_loop, args=(src,), daemon=True)
        src.thread.start()
        # Register the running source so non-test mode status/is_slot_active see it.
        self._cameras[src.slot] = src
        return True, "ok"

    def _capture_loop(self, src):
        """Background thread for a single camera: read frame, detect, store.

        Errors are contained to this camera's source: a failed read or an
        exception in one loop never stops the other cameras' threads.
        """
        print(f"[camera_manager] Capture loop started for {src.slot}")
        while src.running and src.cap is not None and src.cap.isOpened():
            try:
                ret, frame = src.cap.read()
                if not ret:
                    if src.error is None:
                        src.error = "capture read returned no frame"
                    time.sleep(0.01)
                    continue

                src.error = None

                # Store raw frame for this camera
                with src.frame_lock:
                    src.frame = frame.copy()
                src.last_frame_time = time.time()

                # Track this camera's real frame rate (measured, not assumed)
                src._track_fps()

                # Run detection for this slot
                self._run_detection(frame, src.slot)

                # Keep the per-camera annotated copy clean (keyed by slot, so
                # another camera writing its own annotation cannot corrupt ours).
                with self._frame_lock:
                    per_slot = self._slot_annotated.get(src.slot)
                    if per_slot is not None:
                        src.annotated_frame = per_slot

                # Mirror the primary capture into the legacy view.
                if src.slot == self._active_slot:
                    with self._frame_lock:
                        self._frame = frame.copy()
                    with self._lock:
                        self._measured_fps = src.measured_fps

                # Rate cap: never busy-spin. Detection itself takes most of the
                # frame budget; max ~30 fps.
                time.sleep(0.03)

            except Exception as e:
                print(f"[camera_manager] {src.slot} capture loop error: {e}")
                src.error = str(e)
                time.sleep(0.1)

        print(f"[camera_manager] Capture loop ended for {src.slot}")

    def _stop_source(self, src):
        """Stop a single camera: halt its thread, release only its own cap."""
        src.running = False
        if src.thread is not None:
            src.thread.join(timeout=2.0)
            src.thread = None
        if src.cap is not None:
            if src.cap is not self._cap:
                # The primary cap is released exactly once by _stop_capture.
                try:
                    src.cap.release()
                except Exception:
                    pass
            src.cap = None
        with src.frame_lock:
            src.frame = None
            src.annotated_frame = None
        src.measured_fps = None
        src.last_frame_time = None
        if src.state in ("CONNECTED", "STARTING"):
            src.state = "STOPPED"

    def _stop_sources(self):
        for src in list(self._sources.values()):
            self._stop_source(src)
        self._cameras.clear()

    def _stop_capture(self):
        """Legacy single-camera stop (releases the manager-level primary cap)."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        with self._frame_lock:
            self._frame = None
            self._annotated_frame = None
            self._slot_annotated.clear()
        self._measured_fps = None
        self._frames_in_window = 0
        self._fps_window_start = time.monotonic()

    def _stop_all_capture_locked(self):
        self._stop_sources()
        self._stop_capture()

    def _record_frame(self):
        """Legacy measured-FPS sampler (kept for API compatibility)."""
        now = time.monotonic()
        self._frames_in_window += 1
        elapsed = now - self._fps_window_start
        if elapsed >= 2.0:
            self._measured_fps = round(self._frames_in_window / elapsed, 1)
            self._frames_in_window = 0
            self._fps_window_start = now

    @staticmethod
    def _cap_metadata(cap, measured_fps):
        """Read real resolution / stream FPS from a capture device.

        Returns (resolution, fps, fps_source). Never fabricates a measurement:
        if the device does not expose a value, the field is None so the caller
        reports it honestly as unknown rather than a fabricated number.
        """
        resolution = None
        fps = None
        fps_source = None
        if cv2 is None or cap is None:
            return resolution, fps, fps_source
        try:
            w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            if isinstance(w, (int, float)) and isinstance(h, (int, float)) and w > 0 and h > 0:
                resolution = f"{int(w)}x{int(h)}"
            f = cap.get(cv2.CAP_PROP_FPS)
            if isinstance(f, (int, float)) and f > 0:
                fps = round(float(f), 1)
                fps_source = "device"
        except Exception:
            pass
        # Prefer the measured loop rate (true end-to-end delivery) when known.
        if isinstance(measured_fps, (int, float)) and measured_fps > 0:
            fps = measured_fps
            fps_source = "measured"
        return resolution, fps, fps_source

    def _read_cap_metadata(self):
        """Legacy metadata reader for the manager-level primary cap."""
        return self._cap_metadata(self._cap, self._measured_fps)

    def stop(self):
        with self._lock:
            self._stop_all_capture_locked()
            self._cameras.clear()
            self._active_slot = None
            self._mode = "stopped"
        print("[camera_manager] Stopped")

    def _run_detection(self, frame, slot):
        """Run AI detection on a frame (called from the capture loop).

        The annotated frame is copied AFTER detection so overlays the detectors
        draw onto the raw frame (e.g. the DDS face mesh, mouth points) appear
        in the streamed image — copying first used to drop them.
        """
        if slot == SLOT_DRIVER and self._driver_detector:
            try:
                result = self._driver_detector.process_frame(frame)  # draws mesh on frame
                with self._detection_lock:
                    self._detection_results[SLOT_DRIVER] = result
                annotated = frame.copy()
                self._draw_driver(annotated, result)
                with self._frame_lock:
                    self._annotated_frame = annotated
                    self._slot_annotated[SLOT_DRIVER] = annotated
                return result
            except Exception as e:
                print(f"[camera_manager] Driver detect error: {e}")

        elif slot == SLOT_ROAD and self._pothole_detector:
            try:
                detections = self._pothole_detector.detect(frame)
                with self._detection_lock:
                    self._detection_results[SLOT_ROAD] = detections
                annotated = frame.copy()
                self._draw_potholes(annotated, detections)
                with self._frame_lock:
                    self._annotated_frame = annotated
                    self._slot_annotated[SLOT_ROAD] = annotated
            except Exception as e:
                print(f"[camera_manager] Pothole detect error: {e}")
                with self._frame_lock:
                    self._annotated_frame = frame.copy()
                    self._slot_annotated[SLOT_ROAD] = frame.copy()

        elif slot == SLOT_CABIN and self._cabin_detector:
            try:
                detections = self._cabin_detector.process_frame(frame)
                with self._detection_lock:
                    self._detection_results[SLOT_CABIN] = detections
                with self._frame_lock:
                    self._annotated_frame = frame.copy()
                    self._slot_annotated[SLOT_CABIN] = frame.copy()
            except Exception as e:
                print(f"[camera_manager] Cabin detect error: {e}")
                with self._frame_lock:
                    self._annotated_frame = frame.copy()
                    self._slot_annotated[SLOT_CABIN] = frame.copy()

    def _draw_driver(self, frame, result):
        """Draw drowsiness overlay on frame."""
        h, w = frame.shape[:2]
        state = result.get("state", "NORMAL")
        ear = result.get("ear", 0)
        mar = result.get("mar", 0)
        closed = result.get("closed_sec", 0)
        face = result.get("face_detected", False)

        # State color — match actual DDS engine state strings
        if "DROWSINESS" in state:
            color = (0, 0, 255)  # red
        elif state in ("HEAD POSE ALERT", "HEAD NOD DETECTED"):
            color = (0, 165, 255)  # orange
        elif state in ("EYES CLOSED",):
            color = (0, 200, 255)  # yellow
        else:
            color = (0, 255, 0)  # green

        # State text
        cv2.putText(frame, f"STATE: {state}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        # Metrics
        cv2.putText(frame, f"EAR: {ear:.2f}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"MAR: {mar:.2f}", (10, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"Closed: {closed:.1f}s", (10, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        if not face:
            cv2.putText(frame, "NO FACE DETECTED", (10, 140),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 1)

        # Threshold line indicator (real calibrated values from the DDS engine)
        ear_thr = result.get("ear_threshold", 0.23)
        mar_thr = result.get("mar_threshold", 0.40)
        cv2.putText(frame, f"EAR thr: {ear_thr:.2f} | MAR thr: {mar_thr:.2f}", (10, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

    def _draw_potholes(self, frame, detections):
        """Draw pothole bounding boxes on frame."""
        for det in detections:
            x1, y1, x2, y2 = det.get("bbox", [0, 0, 0, 0])
            conf = det.get("confidence", 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(frame, f"Pothole {conf:.0%}", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        count = len(detections)
        cv2.putText(frame, f"Potholes: {count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

    @staticmethod
    def _encode_frame(annotated):
        import base64
        _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buffer).decode('utf-8')

    def get_frame_as_base64(self, slot=None):
        if not _import_cv2():
            return None

        if self._test_mode:
            target_slot = slot or self._active_slot
            if not target_slot or target_slot != self._active_slot:
                return None

            # Use annotated frame from background detection thread
            with self._frame_lock:
                annotated = self._annotated_frame if self._annotated_frame is not None else self._frame

            if annotated is None:
                return None
            return self._encode_frame(annotated)

        # Multi-camera / non-test mode: return that camera's own latest frame.
        target_slot = slot
        src = self._sources.get(target_slot)
        if src is None:
            return None
        with src.frame_lock:
            frame = src.annotated_frame if src.annotated_frame is not None else src.frame
        if frame is None:
            return None
        return self._encode_frame(frame)

    def get_latest_frame(self, slot):
        """Return the raw latest frame for a slot (no new capture thread).

        Used by the cabin occupancy engine: it consumes the frame this camera's
        own capture loop already produced, so perception never reopens devices.
        """
        src = self._sources.get(slot)
        if src is None:
            return None
        with src.frame_lock:
            return src.frame

    def get_detection_results(self, slot=None):
        """Get current AI detection results for a slot."""
        target = slot or self._active_slot
        if not target:
            return {}
        with self._detection_lock:
            return self._detection_results.get(target, {})

    @staticmethod
    def _slot_state(src, is_active, connected):
        """Honest per-camera connection state."""
        if src is None:
            return "CONNECTED" if (is_active and connected) else "DISCONNECTED"
        if not src.enabled:
            return "DISABLED"
        if is_active and connected:
            return "CONNECTED"
        if not connected:
            if src.state == "ERROR":
                return "ERROR"
            if src.state == "STARTING":
                return "STARTING"
            return "DISCONNECTED"
        return src.state

    def get_camera_status(self):
        status = {}
        available = set()
        seen = set()
        for slot in ALL_SLOTS:
            src = self._sources.get(slot)
            is_active = (self._test_mode and self._active_slot == slot) or (
                not self._test_mode and slot in self._cameras
            )

            connected = False
            resolution = None
            fps = None
            fps_source = None
            device_num = None

            # Prefer the camera's own source; fall back to the legacy cap view.
            if src is not None and src.cap is not None and src.cap.isOpened():
                connected = True
                device_num = src.device_num()
                resolution, fps, fps_source = self._cap_metadata(src.cap, src.measured_fps)
            elif is_active and self._cap is not None and self._cap.isOpened():
                connected = True
                device_num = 0
                resolution, fps, fps_source = self._read_cap_metadata()

            last_frame = None
            if src is not None and src.last_frame_time:
                last_frame = datetime.fromtimestamp(
                    src.last_frame_time, timezone.utc
                ).isoformat(timespec="seconds")

            camera_index = device_num if device_num is not None else (0 if is_active else None)

            status[slot] = {
                "connected": connected,
                "status": self._slot_state(src, is_active, connected),
                "camera_id": (_SLOT_META[slot]["camera_id"]),
                "camera_type": (_SLOT_META[slot]["camera_type"]),
                "bus_id": _bus_id(),
                "enabled": (src.enabled if src is not None else True),
                "camera_index": camera_index,
                "device_index": camera_index,
                "resolution": resolution if is_active else None,
                "resolution_source": "device" if (is_active and resolution) else None,
                "fps": fps if is_active else None,
                "fps_source": fps_source if is_active else None,
                "active": is_active,
                "last_frame_time": last_frame,
                "error": (src.error if src is not None else None),
            }

            if connected and device_num is not None:
                key = str(device_num)
                if key not in seen:
                    seen.add(key)
                    available.add(device_num)

        # Legacy view: a pre-opened shared camera is always discoverable.
        if self._cap is not None and self._cap.isOpened() and 0 not in available:
            available.add(0)

        return {
            "mode": self._mode,
            "test_mode": self._test_mode,
            "test_slot": self._test_slot if self._test_mode else None,
            "available_cameras": sorted(available, key=lambda x: str(x)),
            "slots": status,
            "cameras": {slot: status[slot] for slot in ALL_SLOTS},
            "timestamp": utcnow_iso(),
        }

    def is_slot_active(self, slot):
        if self._test_mode:
            return slot == self._active_slot
        return slot in self._cameras


camera_manager = CameraManager()