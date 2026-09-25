"""
pedestrian_detector.py
Vulnerable Road User (pedestrian) detection for the FLEET-IQ road camera.

Detects pedestrians on/near the roadway using the YOLOv8 COCO 'person' class
(id 0). This is the module behind the "vulnerable road users (school
children, etc.)" sensing line of the urban intelligence requirements.

IMPORTANT — Source Honesty:
- Uses YOLOv8n COCO pre-trained model → MODEL source. 'person' is a COCO class
  name produced by a *generic* model, NOT a custom pedestrian dataset.
- Counts pedestrians per frame (raw), tracks unique pedestrians with ByteTrack
  when available (same tracker as the traffic detector), and reports a
  PH Pedestrian-Presence event when people are present on the roadway.
- Close-to-bus ("near your lane") flag is a simple bbox-geometry HEURISTIC
  (bottom-third of frame / high bbox height fraction) — always labelled as such.
- Never fabricates ages, groups, or "school children" conclusions. The
  vulnerable-road-user framing is reported factually as detected persons.
"""

import threading
import time
from datetime import datetime, timezone
from enum import Enum

# Lazy imports
cv2 = None
np = None
YOLO = None

PEDESTRIAN_CLASS_ID = 0  # COCO 'person'
PEDESTRIAN_MIN_CONFIDENCE = 0.35
MODEL_PATH = "yolov8n.pt"

# bbox-geometry heuristic for "near the bus" / on roadway
NEAR_FRAME_BOTTOM = 0.55   # bottom X% of the frame is "near the vehicle"
NEAR_BBOX_HEIGHT_FRAC = 0.18  # tall in frame ≈ close to camera


class PedestrianSource(Enum):
    MODEL = "MODEL"
    HEURISTIC = "HEURISTIC"


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
            return False
    return True


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _near_roadway(bbox, frame_h):
    """BBox-geometry heuristic: a person whose feet sit in the bottom X% of the
    frame AND whose box is tall ≈ close to the vehicle / near the roadway."""
    if frame_h <= 0 or len(bbox) < 4:
        return False
    x1, y1, x2, y2 = bbox
    bh = (y2 - y1)
    return y2 >= NEAR_FRAME_BOTTOM * frame_h and bh >= NEAR_BBOX_HEIGHT_FRAC * frame_h


class PedestrianDetector:
    """Real-time pedestrian presence detection on the road camera.

    Phase 14: vulnerable road users.
    """

    def __init__(self, event_callback=None, gps_source=None):
        self._event_callback = event_callback
        self._gps_source = gps_source
        self._lock = threading.Lock()
        self._model = None
        self._model_loaded = False
        self._last_tracked = None
        self._tracker_frames_since_last = 0

        self._current_pedestrians = []      # honest per-frame list
        self._total_frames_processed = 0
        self._total_pedestrian_detections = 0
        self._total_unique_pedestrians = 0
        self._seen_track_ids = set()
        self._current_frame_count = 0
        self._current_unique = 0
        self._near_roadway_count = 0
        self._tracking_active = False
        self._detection_source = PedestrianSource.MODEL

    @property
    def detection_source(self) -> str:
        return self._detection_source.value

    def set_event_callback(self, fn):
        with self._lock:
            self._event_callback = fn

    def set_gps_source(self, fn):
        with self._lock:
            self._gps_source = fn

    def load_model(self, model_path=None):
        if not _import_deps():
            print("[pedestrian_detector] Dependencies not available")
            return False
        path = model_path or MODEL_PATH
        if YOLO is not None:
            try:
                self._model = YOLO(path)
                self._model_loaded = True
                self._detection_source = PedestrianSource.MODEL
                print(f"[pedestrian_detector] YOLOv8 COCO model loaded: {path} (source = MODEL, person class)")
                return True
            except Exception as e:
                print(f"[pedestrian_detector] Failed to load model: {e}")
        self._model_loaded = False
        print("[pedestrian_detector] No model available — pedestrian detection unavailable")
        return False

    def detect(self, frame, gps_data=None):
        """Detect pedestrians in a frame. Returns [{bbox, confidence, near_roadway}]."""
        if not _import_deps() or frame is None or not self._model_loaded:
            return []

        detections, tracking_ok = self._run_detection(frame)
        frame_h = frame.shape[0] if frame is not None else 0

        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            near = _near_roadway(det["bbox"], frame_h)
            det["near_roadway"] = near
            det["heuristic_note"] = "bbox-geometry near/on-roadway heuristic"
            det["source"] = self.detection_source

        # Bookkeeping
        self._total_frames_processed += 1
        self._total_pedestrian_detections += len(detections)
        self._current_pedestrians = detections
        self._current_frame_count = len(detections)
        self._near_roadway_count = sum(1 for d in detections if d["near_roadway"])

        if tracking_ok:
            self._tracking_active = True
            ids = set()
            for d in detections:
                tid = d.get("track_id")
                if tid is None:
                    continue
                ids.add(tid)
                if tid not in self._seen_track_ids:
                    self._seen_track_ids.add(tid)
                    self._total_unique_pedestrians += 1
            self._current_unique = len(ids)
        else:
            self._tracking_active = False
            self._current_unique = len(detections)

        # Presence event only when people actually detected (never on absence).
        if self._event_callback and detections:
            self._trigger_event(detections, gps_data)

        return detections

    def _run_detection(self, frame):
        self._tracker_frames_since_last += 1
        if self._tracker_frames_since_last >= 8:
            self._tracker_frames_since_last = 0
            try:
                tracked = self._detect_tracked(frame)
                if tracked is not None:
                    self._last_tracked = tracked
                    return tracked, True
            except Exception as e:
                print(f"[pedestrian_detector] Tracker error (falling back): {e}")
            return self._detect_plain(frame), False
        if self._last_tracked:
            return self._last_tracked, True
        return self._detect_plain(frame), False

    def _detect_tracked(self, frame):
        dets = []
        try:
            results = self._model.track(
                frame, verbose=False, persist=True, tracker="bytetrack.yaml",
                conf=PEDESTRIAN_MIN_CONFIDENCE,
                classes=[PEDESTRIAN_CLASS_ID],
            )
            for result in results:
                if result.boxes is None or len(result.boxes) == 0:
                    continue
                for box in result.boxes:
                    if box.id is None:
                        return None
                    if int(box.cls[0]) != PEDESTRIAN_CLASS_ID:
                        continue
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    dets.append({
                        "bbox": [x1, y1, x2, y2],
                        "confidence": round(conf, 3),
                        "class_name": "pedestrian",
                        "track_id": int(box.id[0]),
                    })
            return dets
        except Exception as e:
            print(f"[pedestrian_detector] Tracked YOLO error: {e}")
            return None

    def _detect_plain(self, frame):
        dets = []
        try:
            results = self._model(frame, verbose=False)
            for result in results:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    if int(box.cls[0]) != PEDESTRIAN_CLASS_ID:
                        continue
                    conf = float(box.conf[0])
                    if conf < PEDESTRIAN_MIN_CONFIDENCE:
                        continue
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    dets.append({
                        "bbox": [x1, y1, x2, y2],
                        "confidence": round(conf, 3),
                        "class_name": "pedestrian",
                    })
            return dets
        except Exception as e:
            print(f"[pedestrian_detector] YOLO error: {e}")
            return []

    def _trigger_event(self, detections, gps_data):
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

        near = [d for d in detections if d.get("near_roadway")]
        event = {
            "event_type": "PEDESTRIAN_PRESENCE",
            "bus_id": "PROTO-001",
            "camera_id": "road",
            "data_source": "live",
            "confidence": max((d["confidence"] for d in detections), default=0.0),
            "latitude": lat,
            "longitude": lon,
            "gps_status": "FIX" if lat is not None else "NO_FIX",
            "severity": "WARNING" if near else "INFO",
            "sensor_source": "road_model",
            "timestamp": utcnow_iso(),
            "additional_data": {
                "pedestrians_this_frame": len(detections),
                "near_roadway": len(near),
                "unique_pedestrians": self._current_unique,
                "total_unique_pedestrians": self._total_unique_pedestrians,
                "tracking_active": self._tracking_active,
                "detection_method": self.detection_source,
                "note": ("COCO 'person' class via generic YOLOv8 model (MODEL). "
                         "near/on-roadway is a bbox-geometry HEURISTIC. "
                         "No age/group/school inference is made."),
            },
        }
        try:
            self._event_callback(event)
        except Exception as e:
            print(f"[pedestrian_detector] Event callback error: {e}")

    def draw_overlay(self, frame, detections=None):
        if not _import_deps() or frame is None:
            return frame
        try:
            overlay = frame.copy()
            dets = detections if detections is not None else self._current_pedestrians
            for d in dets:
                x1, y1, x2, y2 = d["bbox"]
                near = d.get("near_roadway", False)
                color = (0, 0, 255) if near else (0, 255, 255)  # BGR: red-near, yellow
                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)
                cv2.putText(overlay, f"ped {d['confidence']:.2f}", (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            cv2.putText(overlay, f"Pedestrians: {self._current_frame_count} "
                                f"(near: {self._near_roadway_count})",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.putText(overlay, f"source MODEL (COCO person) + near-flag heuristic",
                        (10, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            return overlay
        except Exception:
            return frame

    def get_stats(self):
        with self._lock:
            return {
                "total_frames_processed": self._total_frames_processed,
                "total_pedestrian_detections": self._total_pedestrian_detections,
                "total_unique_pedestrians": self._total_unique_pedestrians,
                "current_detections": self._current_frame_count,
                "near_roadway_this_frame": self._near_roadway_count,
                "tracking_active": self._tracking_active,
                "model_loaded": self._model_loaded,
                "detection_source": self.detection_source,
                "note": ("COCO 'person' class, generic YOLOv8 (MODEL). "
                         "Near/on-roadway uses a bbox-geometry heuristic. "
                         "No custom pedestrian training."),
            }


# Singleton
pedestrian_detector = PedestrianDetector()