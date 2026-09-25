"""
occupancy.py
Cabin occupancy intelligence for FLEET-IQ (Phase 7).

Pipeline:

    Cabin Camera (CameraManager source, Phase 6)
        -> CabinOccupancyEngine consumes the LATEST captured frame (no extra
           capture thread) on a reduced cadence (camera FPS != inference FPS)
        -> estimator produces an OCCUPANCY SNAPSHOT
        -> snapshot exposed via GET /api/cabin/occupancy and bus["cabin_occupancy"]

Honesty rules (Phase 7 core principles):
  * Real passenger calculation runs FIRST: YOLO person detection (COCO
    class 0) via CabinMLPersonDetector, using FLEETIQ_CABIN_MODEL_PATH when
    set, else the in-repo bus_node/src/yolov8n.pt. Its count/confidence/boxes
    are genuine model output.
  * The DEVELOPMENT heuristic (estimator_type="development") is only a
    fallback and must never be presented as "AI detected passengers".
  * confidence is never fabricated: heuristic output carries confidence=None.
  * Cabin camera unavailable  -> occupancy_count / occupancy_percentage /
    crowding_level / confidence are ALL null. "0 passengers" is a real estimate;
    "unknown" is null. The two are never conflated.
  * Frames are consumed and discarded; only the small aggregate snapshot is
    retained. No raw images are persisted anywhere.

Performance:
  The capture loop delivers frames continuously (measured FPS). The cabin
  estimate runs at most once every FLEETIQ_CABIN_INFERENCE_INTERVAL_SEC
  (default 2.0 s) so inference rate stays far below camera rate.

Configuration (env, defaults in brackets):
  FLEETIQ_CABIN_INFERENCE_INTERVAL_SEC : "2.0"
  FLEETIQ_CABIN_DEFAULT_CAPACITY       : "40"   (fallback only; bus-specific
                                                 occupancy.capacity wins)
  FLEETIQ_CABIN_MODEL_PATH             : unset  (defaults to in-repo
                                                  bus_node/src/yolov8n.pt;
                                                  "off"/"none" disables the
                                                  real model -> heuristic only)
  FLEETIQ_CAMERA_BUS_ID                : "PROTO-001"
"""

import os
import threading
import time
from datetime import datetime, timezone

SLOT_CABIN = "cabin"
CABIN_CAMERA_ID = "CAM-CAB-001"
CABIN_SOURCE = "cabin_camera"
CABIN_SOURCE_HEURISTIC = "cabin_camera_heuristic"

CROWDING_NORMAL = "NORMAL"
CROWDING_MODERATE = "MODERATE"
CROWDING_HIGH = "HIGH"
CROWDING_CRITICAL = "CRITICAL"

# Person-counting model candidates (first existing file wins). The repo ships
# bus_node/src/yolov8n.pt (standard COCO YOLOv8n, class 0 = person), so real
# passenger calculation works out of the box with no env configuration.
# FLEETIQ_CABIN_MODEL_PATH overrides all of these when explicitly set.
_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE = <root>/control_centre/backend/ai/cabin -> repo root is 4 levels up.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
DEFAULT_PERSON_MODEL_CANDIDATES = [
    os.path.join(_HERE, "models", "yolov8n.pt"),
    os.path.join(_PROJECT_ROOT, "bus_node", "src", "yolov8n.pt"),
]

PERSON_CONF_THRESHOLD = 0.35


def resolve_person_model_path(explicit=None):
    """Resolve which person-counting weights to use (no loading here).

    Returns (path_or_None, reason). Explicit env/config wins; otherwise the
    first existing in-repo candidate is used. Never downloads anything.
    """
    if explicit is not None:
        raw = str(explicit).strip()
        if not raw or raw.lower() in ("off", "none", "disabled"):
            return None, "person model explicitly disabled"
        if os.path.isfile(raw):
            return raw, "explicit path"
        return None, "no configured cabin model file"
    env = os.environ.get("FLEETIQ_CABIN_MODEL_PATH")
    if env is not None:
        raw = str(env).strip()
        if not raw or raw.lower() in ("off", "none", "disabled"):
            return None, "person model explicitly disabled"
        if os.path.isfile(raw):
            return raw, "FLEETIQ_CABIN_MODEL_PATH"
        return None, "no configured cabin model file"
    for cand in DEFAULT_PERSON_MODEL_CANDIDATES:
        if cand and os.path.isfile(cand):
            return cand, "in-repo default"
    return None, "no configured cabin model file"


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bus_id():
    return os.environ.get("FLEETIQ_CAMERA_BUS_ID", "PROTO-001")


def _default_capacity():
    raw = os.environ.get("FLEETIQ_CABIN_DEFAULT_CAPACITY", "40")
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        return 40


def capacity_of(bus):
    """Bus-specific capacity when present, else the configured default.

    The default is a documented fallback for the live prototype; it is NOT
    claimed to be the vehicle's actual capacity.
    """
    cap = ((bus or {}).get("occupancy") or {}).get("capacity")
    try:
        cap = int(round(float(cap)))
        if cap > 0:
            return cap
    except (TypeError, ValueError, OverflowError):
        pass
    return _default_capacity()


def occupancy_percentage(count, capacity):
    """0..100 occupancy percentage with bound + invalid-capacity protection.

    Returns None (unknown) whenever a term is missing or capacity <= 0 — it
    never returns a fabricated number.
    """
    if count is None or not capacity:
        return None
    try:
        pct = 100.0 * float(count) / float(capacity)
    except (ZeroDivisionError, TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, pct)))


def crowding_level(pct):
    """Canonical cabin crowding interpretation for a percentage.

    Thresholds are aligned with the existing risk-engine occupancy scoring so
    cabin crowding and risk agree on the same percentage (>=75% high, >=90%
    critical). The legacy simulated bus `occupancy.crowd` field keeps its own
    labels; this mapping governs the cabin intelligence snapshot.
    """
    if pct is None:
        return None
    if pct >= 90:
        return CROWDING_CRITICAL
    if pct >= 75:
        return CROWDING_HIGH
    if pct >= 60:
        return CROWDING_MODERATE
    return CROWDING_NORMAL


def unavailable_snapshot(bus_id, status="DISCONNECTED", error=None, capacity=None):
    """Honest 'camera unavailable' snapshot.

    occupancy_count / occupancy_percentage / crowding_level / confidence are all
    None here — unknown is NEVER represented as 0 passengers.
    """
    return {
        "bus_id": bus_id,
        "camera_id": CABIN_CAMERA_ID,
        "timestamp": _now_iso(),
        "occupancy_count": None,
        "occupancy_percentage": None,
        "capacity": capacity,
        "crowding_level": None,
        "confidence": None,
        "source": CABIN_SOURCE,
        "estimator": None,
        "estimator_type": None,
        "method": None,
        "model": None,
        "person_boxes": None,
        "frame_source": "cabin",
        "status": status,
        "error": error,
        "simulation": False,
        "privacy": "aggregate-only; frames discarded after inference",
    }


def build_occupancy_snapshot(bus_id, count, capacity, confidence=None,
                             estimator=None, estimator_type=None, method=None,
                             model=None, person_boxes=None):
    """Build the canonical cabin occupancy snapshot from an estimate.

    `confidence` is passed through from the estimator. Heuristic estimates pass
    None — a confidence value is never invented.
    """
    cap = capacity if (isinstance(capacity, int) and capacity > 0) else None
    pct = occupancy_percentage(count, cap)
    source = CABIN_SOURCE_HEURISTIC if estimator == "heuristic" else CABIN_SOURCE
    return {
        "bus_id": bus_id,
        "camera_id": CABIN_CAMERA_ID,
        "timestamp": _now_iso(),
        "occupancy_count": count,
        "occupancy_percentage": pct,
        "capacity": cap,
        "crowding_level": crowding_level(pct),
        "confidence": confidence,
        "source": source,
        "estimator": estimator,
        "estimator_type": estimator_type,
        "method": method,
        "model": model,
        "person_boxes": person_boxes,
        "frame_source": "cabin",
        "status": "CONNECTED",
        "error": None,
        "simulation": False,
        "privacy": "aggregate-only; frames discarded after inference",
    }


class CabinHeuristicEstimator:
    """Development/prototype occupancy estimator. NOT a trained model.

    Computes a coarse foreground-density proxy: the current frame is downscaled
    and compared (per grid cell) against a slowly-adapting background; the
    share of active cells maps linearly onto the configured capacity. Every
    output is labelled heuristic/development/estimated and carries confidence
    None. This exists so the cabin pipeline is functional end-to-end without
    pretending a real AI model is present.
    """

    kind = "heuristic"
    estimator_type = "development"
    GRID = (6, 8)
    ACTIVE_THRESHOLD = 7.0
    ALPHA = 0.05

    def __init__(self):
        self._background = None
        self._np = None
        self._available = False
        try:
            import numpy as _np
            self._np = _np
            self._available = True
        except ImportError:
            self._np = None

    @property
    def available(self):
        return self._available

    def reset(self):
        self._background = None

    def estimate(self, frame, capacity):
        """Return an occupancy-count estimate (int in [0, capacity]) or None."""
        np = self._np
        if np is None or frame is None:
            return None
        try:
            gray = frame[::4, ::4].mean(axis=2).astype(np.float32)
        except Exception:  # noqa: BLE001
            return None
        h, w = gray.shape
        rows, cols = self.GRID
        ph, pw = h // rows, w // cols
        if ph < 1 or pw < 1:
            return 0
        try:
            cells = gray[: rows * ph, : cols * pw].reshape(rows, ph, cols, pw).transpose(0, 2, 1, 3)
            cell_mean = cells.mean(axis=(2, 3))
        except Exception:  # noqa: BLE001
            return 0
        if self._background is None:
            self._background = cell_mean.copy()
            return 0
        active = float((np.abs(cell_mean - self._background) > self.ACTIVE_THRESHOLD).mean())
        self._background = self._background * (1.0 - self.ALPHA) + cell_mean * self.ALPHA
        cap = max(0, int(capacity))
        count = int(round(cap * active))
        return max(0, min(cap, count))


class CabinMLPersonDetector:
    """Real passenger calculation: counts persons with a YOLO model.

    Model resolution order: explicit path arg > FLEETIQ_CABIN_MODEL_PATH >
    in-repo default (bus_node/src/yolov8n.pt, standard COCO YOLOv8n).
    Set the env var to "off"/"none" to disable and use the heuristic only.
    Nothing is downloaded or invented — without a weights file on disk the
    detector reports unavailable and the engine falls back to the heuristic.

    The weights load lazily on first estimate() so backend startup and
    unit tests never pay the torch/YOLO import cost when the cabin camera
    is not in use.
    """

    kind = "ml-person-detector"
    estimator_type = "real-model"
    source_label = "cabin_camera"

    def __init__(self, model_path=None):
        self._explicit = model_path
        self._model_path, self._resolve_reason = resolve_person_model_path(model_path)
        self._model = None
        self._available = self._model_path is not None
        self._error = None if self._available else self._resolve_reason
        self._load_attempted = False
        self.last_boxes = None

    @property
    def available(self):
        return self._available

    @property
    def error(self):
        return self._error

    @property
    def model_path(self):
        return self._model_path

    def _ensure_loaded(self):
        """Load YOLO weights on first use (lazy — keeps startup/tests fast)."""
        if self._load_attempted or not self._available:
            return self._model is not None
        self._load_attempted = True
        try:
            from ultralytics import YOLO
            self._model = YOLO(self._model_path)
            self._error = None
            return True
        except Exception as e:  # noqa: BLE001
            self._model = None
            self._available = False
            self._error = f"model load failed: {e}"
            return False

    def estimate(self, frame, capacity):
        """Count persons in a cabin frame -> (count, confidence, model_name).

        Returns (None, None, None) when unavailable (caller falls back to the
        heuristic). `last_boxes` holds the person bboxes of the latest
        successful inference for the snapshot/overlay.
        """
        if frame is None:
            return None, None, None
        if not self._available:
            return None, None, None
        if not self._ensure_loaded():
            return None, None, None
        try:
            results = self._model.predict(frame, conf=PERSON_CONF_THRESHOLD, verbose=False)[0]
            boxes = results.boxes
            if boxes is None or boxes.data is None or len(boxes.data) == 0:
                self.last_boxes = []
                return 0, 0.0, "person-detector(yolo)"
            data = boxes.data.tolist()
            persons = [r for r in data if int(r[5]) == 0]  # COCO class 0 == person
            self.last_boxes = [[int(r[0]), int(r[1]), int(r[2]), int(r[3])] for r in persons]
            conf = round(float(max(r[4] for r in persons)), 3) if persons else 0.0
            count = min(len(persons), max(0, int(capacity)))
            return count, conf, "person-detector(yolo)"
        except Exception as e:  # noqa: BLE001
            self._error = f"inference error: {e}"
            self.last_boxes = None
            return None, None, None


class CabinOccupancyEngine:
    """Consumes cabin frames at a reduced cadence and publishes a snapshot.

    Dependencies are injected so tests can use fake cameras / stores; the module
    singleton wires the live camera manager and data store.
    """

    def __init__(self, camera_manager, store, mode_state, estimator=None, interval=None,
                 real_model=None):
        self._cm = camera_manager
        self._store = store
        self._mode = mode_state
        try:
            self._interval = float(interval if interval is not None
                                   else os.environ.get("FLEETIQ_CABIN_INFERENCE_INTERVAL_SEC", 2.0))
        except (TypeError, ValueError):
            self._interval = 2.0
        self._interval = max(0.05, self._interval)
        self._estimator = estimator or CabinHeuristicEstimator()
        # Real passenger calculation (YOLO person count). Pass an explicit
        # detector (or fake) in tests; otherwise auto-resolve the in-repo
        # weights. Construction is cheap — weights load lazily on first use.
        self._real_model = real_model if real_model is not None else CabinMLPersonDetector()
        self._last_estimator_kind = None  # "real" | "heuristic" | None (honest label)
        self._lock = threading.Lock()
        self._snapshot = None
        self._last_error = None
        self._inference_count = 0
        self._inference_fps = None
        self._inference_times = []
        self._stop = threading.Event()
        self._thread = None

    # ---- lifecycle ----
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="cabin-occupancy")
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ---- loop ----
    def _loop(self):
        # Wall-clock ring buffer of successful inference timestamps. Only
        # successful inferences count (camera disconnected / no estimate do
        # not inflate the rate), so inference_fps reflects real throughput.
        while not self._stop.is_set():
            if not self._mode.is_live:
                time.sleep(max(0.05, self._interval))
                continue
            started = time.monotonic()
            try:
                estimated = self._tick(started=started)
            except Exception as e:  # never bring FLEET-IQ down
                print(f"[cabin] occupancy tick error: {e}")
                self._last_error = str(e)
                estimated = False
            elapsed = time.monotonic() - started
            time.sleep(max(0.05, self._interval - elapsed))

    def _cabin_status_and_error(self):
        try:
            s = self._cm.get_camera_status()["slots"].get(SLOT_CABIN, {})
            return s.get("status", "DISCONNECTED"), s.get("error")
        except Exception:  # noqa: BLE001
            return "DISCONNECTED", None

    def _resolve_frame(self, cabin_status):
        """Return (frame, frame_source_label, status_to_report, error).

        Cabin frames ONLY: passenger counting never runs on the driver feed.
        When the cabin slot is not CONNECTED (or has no frame) the caller
        reports an honest unavailable snapshot (null counts) instead of
        counting the driver camera.
        """
        if cabin_status == "CONNECTED":
            frame = self._cm.get_latest_frame(SLOT_CABIN)
            if frame is not None:
                return frame, "cabin", "CONNECTED", None
        return None, "cabin", cabin_status, None

    def _record_inference(self, started):
        with self._lock:
            self._inference_times.append(started)
            if len(self._inference_times) > 50:
                self._inference_times = self._inference_times[-25:]
            if len(self._inference_times) >= 2:
                span = self._inference_times[-1] - self._inference_times[0]
                n = len(self._inference_times) - 1
                avg = span / n if n else 0.0
                self._inference_fps = round(1.0 / avg, 2) if avg > 0 else None
            else:
                self._inference_fps = None

    def _tick(self, started=None):
        """Process one tick of cabin occupancy estimation.

        Phase 19: Added health tracking for cabin occupancy subsystem.
        """
        # Returns True when a real estimate was produced this tick (so the
        # loop can gate inference_fps on actual successful inferences only).
        if not self._mode.is_live:
            self._snapshot = None
            self._drop_bus_field()
            return False

        bus = self._store.get_bus(_bus_id()) if hasattr(self._store, "get_bus") else None
        capacity = capacity_of(bus)
        status, error = self._cabin_status_and_error()

        frame, frame_source, status, _fb_err = self._resolve_frame(status)

        if status != "CONNECTED" or frame is None:
            snap = unavailable_snapshot(_bus_id(), status=status, error=error, capacity=capacity)
            estimated = False
            # Phase 19: Record cabin occupancy failure
            try:
                from system_health import record_subsystem_failure
                record_subsystem_failure("cabin_occupancy", error or f"Camera status: {status}", critical=False)
            except ImportError:
                pass
        else:
            count = None
            conf = None
            model_name = None
            boxes = None
            used = None
            # 1) Real passenger calculation first (YOLO person count).
            if self._real_model is not None and self._real_model.available:
                try:
                    count, conf, model_name = self._real_model.estimate(frame, capacity)
                    if count is not None:
                        boxes = list(getattr(self._real_model, "last_boxes", None) or [])
                        used = "real"
                except Exception as e:  # noqa: BLE001
                    self._last_error = f"person-model error: {e}"
                    error = str(e)
            # 2) Heuristic fallback (development proxy, confidence None).
            if count is None:
                try:
                    count = self._estimator.estimate(frame, capacity)
                    if count is not None:
                        used = "heuristic"
                        conf = None
                        model_name = None
                        boxes = None
                except Exception as e:  # noqa: BLE001
                    self._last_error = f"estimator error: {e}"
                    error = str(e)
                    # Phase 19: Record estimator failure
                    try:
                        from system_health import record_subsystem_failure
                        record_subsystem_failure("cabin_occupancy", str(e), critical=False)
                    except ImportError:
                        pass
            if count is None:
                snap = unavailable_snapshot(_bus_id(), status="CONNECTED",
                                            error=error or "no usable cabin frame / estimator unavailable",
                                            capacity=capacity)
                estimated = False
            else:
                if used == "real":
                    snap = build_occupancy_snapshot(
                        _bus_id(), count, capacity,
                        confidence=conf,
                        estimator=self._real_model.kind,
                        estimator_type=self._real_model.estimator_type,
                        method="yolo person detection (COCO class 0)",
                        model=model_name,
                        person_boxes=boxes,
                    )
                else:
                    snap = build_occupancy_snapshot(
                        _bus_id(), count, capacity,
                        confidence=None,
                        estimator=self._estimator.kind,
                        estimator_type=self._estimator.estimator_type,
                        method="foreground-density grid proxy",
                    )
                # Honest frame provenance: "cabin" for a dedicated cabin
                # camera, "driver-shared" when counting on the shared driver
                # feed on single-camera machines.
                snap["frame_source"] = frame_source
                self._last_estimator_kind = used
                self._inference_count += 1
                started = started if started is not None else time.monotonic()
                self._record_inference(started)
                estimated = True
                # Phase 19: Record cabin occupancy success
                try:
                    from system_health import record_subsystem_success
                    record_subsystem_success("cabin_occupancy")
                except ImportError:
                    pass

        with self._lock:
            self._snapshot = snap
        if bus is not None:
            bus["cabin_occupancy"] = snap
            self._store.upsert_bus(bus)
        return estimated

    def _drop_bus_field(self):
        bus = self._store.get_bus(_bus_id()) if hasattr(self._store, "get_bus") else None
        if bus is not None:
            bus.pop("cabin_occupancy", None)

    # ---- state for the API/frontend ----
    def public_state(self, system_mode="simulation"):
        with self._lock:
            snap = dict(self._snapshot) if self._snapshot is not None else None
            count, fps = self._inference_count, self._inference_fps
            last_error = self._last_error
        real = bool(self._real_model is not None and self._real_model.available)
        # Honest label: which estimator produced the LAST snapshot (not just
        # which one is available). Falls back to availability before any tick.
        if self._last_estimator_kind == "real":
            estimator_in_use = "real-model (ml-person-detector)"
        elif self._last_estimator_kind == "heuristic":
            estimator_in_use = "heuristic (development)"
        else:
            estimator_in_use = "real-model (ml-person-detector)" if real else "heuristic (development)"
        base = dict(snap) if snap else unavailable_snapshot(_bus_id(), status="UNAVAILABLE")
        return {
            "bus_id": base["bus_id"],
            "camera_id": base["camera_id"],
            "timestamp": base["timestamp"],
            "status": base["status"],
            "error": base["error"],
            "occupancy_count": base["occupancy_count"],
            "occupancy_percentage": base["occupancy_percentage"],
            "capacity": base["capacity"],
            "crowding_level": base["crowding_level"],
            "confidence": base["confidence"],
            "source": base["source"],
            "estimator": base["estimator"],
            "estimator_type": base["estimator_type"],
            "method": base["method"],
            "model": base["model"],
            "person_boxes": base.get("person_boxes"),
            "frame_source": base.get("frame_source", "cabin"),
            "privacy": base["privacy"],
            "simulation": False,
            "occupancy": snap,
            "camera_status": base["status"],
            "real_model_available": real,
            "estimator_in_use": estimator_in_use,
            "inference_count": count,
            "inference_fps": fps,
            "last_error": last_error,
            "system_mode": system_mode,
        }


_engine = None


def get_cabin_engine():
    """Module singleton wired to the live camera manager + data store."""
    global _engine
    if _engine is None:
        from data_store import store, mode_state
        from ai.camera_manager import camera_manager
        _engine = CabinOccupancyEngine(camera_manager, store, mode_state)
    return _engine