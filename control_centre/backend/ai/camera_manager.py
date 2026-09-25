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

# Pipeline rates: video is delivered at the full camera rate (30 fps target)
# while heavy AI inference (MediaPipe/YOLO) runs asynchronously at ~10 Hz.
# Overlays (boxes/stats/face mesh) are redrawn onto every fresh frame from the
# latest inference, so motion stays at 30 fps and AI refreshes at 10 Hz.
VIDEO_FRAME_INTERVAL = 1.0 / 30.0
AI_INFERENCE_INTERVAL = 0.1
MESH_MAX_AGE_SEC = 0.5

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
        # Async AI worker (inference off the frame-delivery path)
        self.detect_thread = None
        self.detect_running = False
        # Driver face-mesh snapshot: (meshed_frame, bool_mask, timestamp).
        # Lets the 30 fps video thread composite the 10 Hz mesh with no flicker.
        self.mesh_lock = threading.Lock()
        self.mesh_frame = None
        self.mesh_mask = None
        self.mesh_time = 0.0
        self.frame = None
        self.annotated_frame = None
        self.frame_lock = threading.Lock()
        self.last_frame_time = None
        self.measured_fps = None
        self._frames_in_window = 0
        self._fps_window_start = time.monotonic()
        # Pre-encoded JPEG base64 cache — avoids re-encoding per REST request
        self._encoded_b64 = None
        self._encoded_lock = threading.Lock()
        # Monotonic frame counter — lets streamers skip re-sending the same
        # frame (smooth delivery without redundant bandwidth/CPU).
        self.frame_seq = 0
        # Shared-camera fallback (single-webcam machines): when this slot has
        # no physical device of its own, it mirrors another slot's frames
        # instead of reporting DISCONNECTED. No synthetic frames — the shared
        # flag is reported honestly in status so the UI can label it.
        self.shared_with = None
        self.shared = False

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
        self._traffic_detector = None
        self._pedestrian_detector = None
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

        if self._traffic_detector is None:
            try:
                from ai.road.traffic_detector import traffic_detector as _traffic
                self._traffic_detector = _traffic
                print("[camera_manager] Traffic detector linked (shared singleton)")
            except Exception as e:
                print(f"[camera_manager] Traffic detector failed: {e}")

        if self._pedestrian_detector is None:
            try:
                from ai.road.pedestrian_detector import pedestrian_detector as _ped
                self._pedestrian_detector = _ped
                print("[camera_manager] Pedestrian detector linked (shared singleton)")
            except Exception as e:
                print(f"[camera_manager] Pedestrian detector failed: {e}")

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
            if not ok and test_slot != SLOT_DRIVER:
                # Single webcam machines: cabin/road slots have their own
                # device index (e.g. cabin=1) which often doesn't exist.
                # Test mode means ONE shared camera feeding one AI module
                # at a time, so fall back to the driver device (usually 0)
                # or the already pre-opened shared cap instead of failing.
                fallback = _resolve_camera_device(SLOT_DRIVER)
                if fallback is None:
                    fallback = 0
                if src.device_index != fallback:
                    orig = src.device_index
                    src.device_index = fallback
                    src.error = None
                    # Reuse the pre-opened shared camera when available —
                    # avoids re-opening the same USB device twice in a row.
                    if self._cap is not None:
                        try:
                            if self._cap.isOpened():
                                src.cap = self._cap
                        except Exception:
                            pass
                    ok2, msg2 = self._start_source_locked(src)
                    if ok2:
                        print(f"[camera_manager] {test_slot} fell back "
                              f"to shared camera {fallback!r} (own device {orig!r} unavailable)")
                        ok, msg = ok2, msg2
                    else:
                        src.device_index = orig
                        msg = f"{msg}; shared-camera fallback ({fallback!r}) also failed: {msg2}"
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
                # A previously-shared fallback must be cleared before a fresh start
                # attempt, otherwise a stale shared flag could mask a real device.
                src.shared_with = None
                src.shared = False
                if not src.enabled:
                    unavailable.append(slot)
                    continue
                ok, _msg = self._start_source_locked(src)
                if ok:
                    started.append(slot)
                else:
                    unavailable.append(slot)

            # No shared-camera fallback: the driver feed is DDS + face-presence
            # ONLY and must never be counted as passengers. When the cabin
            # camera has no device of its own it reports DISCONNECTED honestly
            # (with null counts) instead of mirroring the driver feed.

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
        # Async inference worker: heavy AI runs at ~10 Hz on frame copies so
        # the capture loop sustains the full 30 fps video rate.
        src.detect_running = True
        src.detect_thread = threading.Thread(target=self._detection_loop, args=(src,), daemon=True)
        src.detect_thread.start()
        # Register the running source so non-test mode status/is_slot_active see it.
        self._cameras[src.slot] = src
        return True, "ok"

    def _capture_loop(self, src):
        """Background thread for a single camera: read frame, overlay, store.

        Video delivery only — runs at the full camera rate (30 fps target).
        Heavy AI inference runs in `_detection_loop` at ~10 Hz; this loop
        redraws the latest results (boxes/stats/face mesh) onto every fresh
        frame, so motion stays smooth while AI refreshes asynchronously.

        Errors are contained to this camera's source: a failed read or an
        exception in one loop never stops the other cameras' threads.
        """
        print(f"[camera_manager] Capture loop started for {src.slot} (30 fps video)")
        while src.running and src.cap is not None and src.cap.isOpened():
            try:
                loop_start = time.monotonic()
                ret, frame = src.cap.read()
                if not ret:
                    if src.error is None:
                        src.error = "capture read returned no frame"
                    time.sleep(0.01)
                    continue

                src.error = None
                # Phase 19: Reset state to CONNECTED on successful frame
                if src.state != "CONNECTED":
                    src.state = "CONNECTED"
                    # Phase 19: Record camera recovery for health tracking
                    try:
                        from system_health import record_subsystem_success
                        camera_name = f"{src.slot}_camera"
                        record_subsystem_success(camera_name)
                    except ImportError:
                        pass

                # Store raw frame for this camera (kept clean for consumers
                # like the cabin occupancy engine — overlays go on a copy).
                with src.frame_lock:
                    src.frame = frame
                src.last_frame_time = time.time()

                # Track this camera's real frame rate (measured, not assumed)
                src._track_fps()

                # Cheap overlay redraw from the latest async inference results.
                annotated = frame.copy()
                self._redraw_overlay(annotated, src)
                with src.frame_lock:
                    src.annotated_frame = annotated

                # Pre-encode the annotated frame to JPEG base64 in the capture
                # thread so the REST handler never re-encodes per request.
                self._pre_encode(src)

                # Keep the per-camera annotated copy clean (keyed by slot, so
                # another camera writing its own annotation cannot corrupt ours).
                with self._frame_lock:
                    self._annotated_frame = annotated
                    self._slot_annotated[src.slot] = annotated

                # Mirror FPS for legacy view.
                if src.slot == self._active_slot:
                    with self._lock:
                        self._measured_fps = src.measured_fps

                # Pace to the 30 fps video target (never busy-spin).
                elapsed = time.monotonic() - loop_start
                time.sleep(max(0.001, VIDEO_FRAME_INTERVAL - elapsed))

            except Exception as e:
                print(f"[camera_manager] {src.slot} capture loop error: {e}")
                src.error = str(e)
                # Phase 19: Update source state on error for honest status reporting
                if src.state == "CONNECTED":
                    src.state = "ERROR"
                # Phase 19: Record camera failure for health tracking
                try:
                    from system_health import record_subsystem_failure
                    camera_name = f"{src.slot}_camera"
                    record_subsystem_failure(camera_name, str(e), critical=False)
                except ImportError:
                    pass
                time.sleep(0.1)

        print(f"[camera_manager] Capture loop ended for {src.slot}")

    def _detection_loop(self, src):
        """Async AI worker: inference at ~10 Hz on frame copies.

        Runs the slot's detector (MediaPipe/YOLO) off the video path and
        publishes results + the driver face-mesh snapshot for the capture
        loop to composite onto every 30 fps frame.
        """
        print(f"[camera_manager] Detection loop started for {src.slot} (~10 Hz AI)")
        while src.detect_running:
            try:
                tick = time.monotonic()
                with src.frame_lock:
                    raw = src.frame
                if raw is not None and src.cap is not None:
                    try:
                        work = raw.copy()
                    except Exception:
                        work = None
                    if work is not None:
                        # Inference + result store; draws mesh on the throwaway
                        # copy (never touches the live raw frame).
                        self._run_detection(work, src.slot, publish=False)
                        if src.slot == SLOT_DRIVER:
                            self._store_mesh_snapshot(src, raw, work)
                elapsed = time.monotonic() - tick
                time.sleep(max(0.01, AI_INFERENCE_INTERVAL - elapsed))
            except Exception as e:
                print(f"[camera_manager] {src.slot} detection loop error: {e}")
                time.sleep(0.2)
        print(f"[camera_manager] Detection loop ended for {src.slot}")

    def _store_mesh_snapshot(self, src, base, meshed):
        """Cache which pixels the DDS mesh drew, for 30 fps compositing.

        The mesh belongs to a ~10 Hz inference tick; the video thread stamps
        these pixels onto each fresh frame (no flicker, mild ghosting only
        during fast motion). Strictly validated — never stores garbage.
        """
        try:
            import numpy as _np
            diff = cv2.absdiff(meshed, base)
            mask = diff.max(axis=2) > 12
            if not isinstance(mask, _np.ndarray) or mask.shape != base.shape[:2]:
                return
            if not isinstance(meshed, _np.ndarray) or meshed.shape != base.shape:
                return
            if not bool(mask.any()):
                # No mesh drawn (e.g. NO FACE) — clear any stale snapshot.
                with src.mesh_lock:
                    src.mesh_frame = None
                    src.mesh_mask = None
                    src.mesh_time = 0.0
                return
            with src.mesh_lock:
                src.mesh_frame = meshed
                src.mesh_mask = mask
                src.mesh_time = time.monotonic()
        except Exception:
            pass

    def _redraw_overlay(self, annotated, src):
        """Draw the latest async inference results onto a fresh frame.

        Cheap OpenCV primitives only (text/boxes + cached mesh pixels) —
        safe to run at the full 30 fps video rate.
        """
        slot = src.slot
        if slot == SLOT_DRIVER:
            mesh = None
            with src.mesh_lock:
                if (src.mesh_frame is not None and src.mesh_mask is not None
                        and (time.monotonic() - src.mesh_time) < MESH_MAX_AGE_SEC):
                    try:
                        if src.mesh_frame.shape == annotated.shape \
                                and src.mesh_mask.shape == annotated.shape[:2]:
                            mesh = (src.mesh_frame, src.mesh_mask)
                    except Exception:
                        mesh = None
            if mesh is not None:
                try:
                    mframe, mmask = mesh
                    annotated[mmask] = mframe[mmask]
                except Exception:
                    pass
            with self._detection_lock:
                result = self._detection_results.get(SLOT_DRIVER) or {}
            if isinstance(result, dict) and result:
                try:
                    self._draw_driver(annotated, result)
                except Exception:
                    pass
            # Driver slot is DDS + face-presence ONLY: never draw passenger/
            # person-count overlays here. People counting lives on the cabin
            # slot (occupancy engine + cabin detector overlay below).
        elif slot == SLOT_ROAD:
            with self._detection_lock:
                dets = self._detection_results.get(SLOT_ROAD) or []
            try:
                # Separate pothole / traffic / pedestrian detections
                pothole_dets = [d for d in dets if d.get("class_name") == "pothole"]
                traffic_dets = [d for d in dets if d.get("class_name") in ("car", "bus", "truck", "motorcycle")]
                ped_dets = [d for d in dets if d.get("class_name") == "pedestrian"]
                if pothole_dets:
                    self._draw_potholes(annotated, pothole_dets)
                if traffic_dets and self._traffic_detector:
                    self._traffic_detector.draw_overlay(annotated, traffic_dets)
                if ped_dets and self._pedestrian_detector:
                    self._pedestrian_detector.draw_overlay(annotated, ped_dets)
            except Exception:
                pass
        elif slot == SLOT_CABIN:
            with self._detection_lock:
                dets = self._detection_results.get(SLOT_CABIN) or []
            try:
                if self._cabin_detector is not None:
                    self._cabin_detector.draw_overlay(annotated, list(dets))
            except Exception:
                pass
            # YOLO person-count overlay: green boxes + passenger count so the
            # operator SEES detection working (previously only fire/smoke drew).
            try:
                self._draw_person_boxes(annotated)
            except Exception:
                pass

    def _draw_person_boxes(self, frame):
        """Overlay the latest YOLO person boxes + passenger count (cheap).

        Reads the cabin occupancy snapshot the occupancy engine publishes on
        the PROTO-001 bus — no extra inference here, just drawing. No boxes
        means nothing is drawn (never fabricates detections).
        """
        if cv2 is None:
            return
        boxes, count = None, None
        try:
            from data_store import store as _store
            bus = _store.get_bus(_bus_id())
            snap = (bus or {}).get("cabin_occupancy") or {}
            boxes = snap.get("person_boxes")
            count = snap.get("occupancy_count")
        except Exception:
            return
        if not boxes:
            if count is not None:
                try:
                    cv2.putText(frame, f"Passengers: {count}", (10, 58),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                except Exception:
                    pass
            return
        try:
            h, w = frame.shape[:2]
            for b in boxes:
                try:
                    x1, y1, x2, y2 = [int(v) for v in b[:4]]
                except Exception:
                    continue
                x1 = max(0, min(w - 1, x1)); x2 = max(0, min(w - 1, x2))
                y1 = max(0, min(h - 1, y1)); y2 = max(0, min(h - 1, y2))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"Passengers: {count}" if count is not None else f"Persons: {len(boxes)}"
            cv2.putText(frame, label, (10, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        except Exception:
            pass

    def _stop_source(self, src):
        """Stop a single camera: halt its threads, release only its own cap."""
        # A shared-fallback slot owns no device/threads — just clear the alias
        # so a later start re-probes the real device instead of going stale.
        if getattr(src, "shared_with", None):
            src.shared_with = None
            src.shared = False
            src.state = "STOPPED"
            src.error = None
            src.last_frame_time = None
            return
        src.running = False
        src.detect_running = False
        if src.thread is not None:
            src.thread.join(timeout=2.0)
            src.thread = None
        if src.detect_thread is not None:
            src.detect_thread.join(timeout=2.0)
            src.detect_thread = None
        with src.mesh_lock:
            src.mesh_frame = None
            src.mesh_mask = None
            src.mesh_time = 0.0
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
        with src._encoded_lock:
            src._encoded_b64 = None
        src.measured_fps = None
        src.last_frame_time = None
        src.frame_seq = 0
        src.shared_with = None
        src.shared = False
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

    def _run_detection(self, frame, slot, publish=True):
        """Run AI detection on a frame and store the results.

        With publish=True (default) the annotated frame is also published to
        the stream cache (legacy synchronous path). The async detection worker
        calls with publish=False — results are stored for the 30 fps video
        thread to redraw, and the passed frame is just a throwaway working
        copy carrying the freshly-drawn mesh for the snapshot.
        """
        if slot == SLOT_DRIVER and self._driver_detector:
            try:
                result = self._driver_detector.process_frame(frame)  # draws mesh on frame
                with self._detection_lock:
                    self._detection_results[SLOT_DRIVER] = result
                if publish:
                    annotated = frame.copy()
                    self._draw_driver(annotated, result)
                    with self._frame_lock:
                        self._annotated_frame = annotated
                        self._slot_annotated[SLOT_DRIVER] = annotated
                return result
            except Exception as e:
                print(f"[camera_manager] Driver detect error: {e}")

        elif slot == SLOT_ROAD and (self._pothole_detector or self._traffic_detector or self._pedestrian_detector):
            try:
                # Run pothole + traffic + pedestrian detection on the road cam.
                pothole_dets = self._pothole_detector.detect(frame) if self._pothole_detector else []
                traffic_dets = self._traffic_detector.detect(frame) if self._traffic_detector else []
                # Pedestrian detection on a reduced cadence: three concurrent
                # YOLO passes on every frame is wasteful, so the slow pedestrians
                # pass runs every PEDESTRIAN_SKIP frames while traffic/potholes
                # stay at full rate.
                self._pedestrian_counter = getattr(self, "_pedestrian_counter", 0) + 1
                ped_dets = []
                if self._pedestrian_detector and self._pedestrian_counter % 6 == 0:
                    ped_dets = self._pedestrian_detector.detect(frame) or []
                    self._last_pedestrian_dets = ped_dets
                else:
                    ped_dets = list(getattr(self, "_last_pedestrian_dets", []) or [])
                # Only store the real per-frame types in detection_results so the
                # redraw layer can split them cleanly (pothole / vehicle / person).
                combined = list(pothole_dets) + list(traffic_dets) + [dict(d) for d in ped_dets]
                with self._detection_lock:
                    self._detection_results[SLOT_ROAD] = combined

                if publish:
                    annotated = frame.copy()
                    # Draw all overlays
                    if pothole_dets:
                        self._draw_potholes(annotated, pothole_dets)
                    if traffic_dets and self._traffic_detector:
                        self._traffic_detector.draw_overlay(annotated, traffic_dets)
                    if ped_dets and self._pedestrian_detector:
                        self._pedestrian_detector.draw_overlay(annotated, ped_dets)
                    with self._frame_lock:
                        self._annotated_frame = annotated
                        self._slot_annotated[SLOT_ROAD] = annotated
            except Exception as e:
                print(f"[camera_manager] Road detect error: {e}")
                if publish:
                    with self._frame_lock:
                        self._annotated_frame = frame.copy()
                        self._slot_annotated[SLOT_ROAD] = frame.copy()

        elif slot == SLOT_CABIN and self._cabin_detector:
            try:
                detections = self._cabin_detector.process_frame(frame)
                with self._detection_lock:
                    self._detection_results[SLOT_CABIN] = detections
                if publish:
                    annotated = frame.copy()
                    self._cabin_detector.draw_overlay(annotated, detections)
                    with self._frame_lock:
                        self._annotated_frame = annotated
                        self._slot_annotated[SLOT_CABIN] = annotated
            except Exception as e:
                print(f"[camera_manager] Cabin detect error: {e}")
                if publish:
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
        _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 60])
        return base64.b64encode(buffer).decode('utf-8')

    def _pre_encode(self, src):
        """Pre-encode the annotated frame to JPEG base64 in the capture thread.

        Called once per frame after detection — the REST handler just reads
        the cached string, never re-encodes.
        """
        with src.frame_lock:
            frame = src.annotated_frame if src.annotated_frame is not None else src.frame
        if frame is None:
            return
        try:
            b64 = self._encode_frame(frame)
            with src._encoded_lock:
                src._encoded_b64 = b64
            src.frame_seq += 1
        except Exception:
            pass

    def get_frame_as_base64(self, slot=None):
        if not _import_cv2():
            return None

        if self._test_mode:
            target_slot = slot or self._active_slot
            if not target_slot or target_slot != self._active_slot:
                return None

            src = self._sources.get(target_slot)
            # Return pre-encoded cache if available (no lock on hot path)
            if src is not None:
                with src._encoded_lock:
                    cached = src._encoded_b64
                if cached is not None:
                    return cached

            # Fallback: encode on demand
            with self._frame_lock:
                annotated = self._annotated_frame if self._annotated_frame is not None else self._frame
            if annotated is None:
                return None
            return self._encode_frame(annotated)

        # Multi-camera / non-test mode: return that camera's own latest frame.
        # A shared-fallback cabin mirrors the driver camera's frame.
        target_slot = slot
        src = self._sources.get(target_slot)
        if src is None:
            return None
        if getattr(src, "shared_with", None):
            donor = self._sources.get(src.shared_with)
            if donor is None:
                return None
            with donor._encoded_lock:
                cached = donor._encoded_b64
            if cached is not None:
                return cached
            with donor.frame_lock:
                frame = donor.annotated_frame if donor.annotated_frame is not None else donor.frame
            if frame is None:
                return None
            return self._encode_frame(frame)
        # Return pre-encoded cache if available
        with src._encoded_lock:
            cached = src._encoded_b64
        if cached is not None:
            return cached
        # Fallback: encode on demand
        with src.frame_lock:
            frame = src.annotated_frame if src.annotated_frame is not None else src.frame
        if frame is None:
            return None
        return self._encode_frame(frame)

    def get_frame_seq(self, slot):
        """Monotonic frame counter for a slot (-1 when the slot is inactive).

        Streamers compare this against the last-sent value and skip
        re-sending an unchanged frame, which keeps motion smooth without
        burning bandwidth on duplicates.
        """
        if self._test_mode and slot != self._active_slot:
            return -1
        src = self._sources.get(slot)
        if src is None:
            return -1
        if not self._test_mode and slot not in self._cameras:
            return -1
        return src.frame_seq

    def get_latest_frame(self, slot):
        """Return the raw latest frame for a slot (no new capture thread).

        Used by the cabin occupancy engine: it consumes the frame this camera's
        own capture loop already produced, so perception never reopens devices.
        A cabin slot in shared-camera fallback mirrors the driver slot's frame.
        """
        src = self._sources.get(slot)
        if src is None:
            return None
        if getattr(src, "shared_with", None):
            donor = self._sources.get(src.shared_with)
            if donor is None:
                return None
            with donor.frame_lock:
                return donor.frame
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
            # A shared-fallback slot mirrors its donor's device/frames honestly.
            shared_with = getattr(src, "shared_with", None) if src is not None else None
            if shared_with:
                donor = self._sources.get(shared_with)
                if donor is not None and donor.cap is not None and donor.cap.isOpened():
                    connected = True
                    device_num = donor.device_num()
                    resolution, fps, fps_source = self._cap_metadata(donor.cap, donor.measured_fps)
                elif is_active and self._cap is not None and self._cap.isOpened():
                    connected = True
                    device_num = 0
                    resolution, fps, fps_source = self._read_cap_metadata()
            elif src is not None and src.cap is not None and src.cap.isOpened():
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
            elif shared_with:
                donor = self._sources.get(shared_with)
                if donor is not None and donor.last_frame_time:
                    last_frame = datetime.fromtimestamp(
                        donor.last_frame_time, timezone.utc
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
                "shared": bool(shared_with),
                "shared_with": shared_with,
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