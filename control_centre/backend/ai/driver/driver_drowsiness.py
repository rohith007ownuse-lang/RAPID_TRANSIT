"""
driver_drowsiness.py
Driver Drowsiness Detection engine (ORIGINAL DDS logic) for the FLEET-IQ
Live Prototype.

This is the real driver-monitoring engine that powers the driver camera
feed on the existing Live Prototype page. It preserves the original DDS
behaviour:

  - OpenCV camera processing + MediaPipe FaceLandmarker (EAR/MAR/solvePnP
    head pose) with Haar cascade fallback
  - 60 s time-based PERCLOS window
  - Eye-closure duration, yawn tracking, head nod / head-pose alerts
  - Calibration: personal EAR/MAR baselines (original DDS math:
    ear_thr = clamp(median_ear * 0.75, 0.15, 0.30),
    mar_thr = clamp(median_mar + 0.20, 0.40, 0.90))
  - Drowsiness decision + severity (matches fatigue_engine.py states)
  - Original DDS audio warning (bus_node.utils.alert_manager / audio_synth)
  - Edge-triggered DRIVER_DROWSINESS / DRIVER_ALERT events for PROTO-001
    (data_source live, camera_id driver) fed into the existing event system

Engine phases: idle -> calibrating -> ready -> monitoring.
"""

import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

import cv2
import numpy as np

# ─── Asset paths (relative to this file -> control_centre/backend) ───
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CASCADE_DIR = os.path.join(BACKEND_DIR, "cascades")
MODELS_DIR = os.path.join(BACKEND_DIR, "models")
PROJECT_ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ─── Thresholds (defaults from config/system_config.json) ───
EAR_THRESHOLD = 0.23
MAR_THRESHOLD = 0.40
EYE_CLOSED_DURATION = 1.3
YAWN_DURATION = 1.0
HEAD_POSE_ALERT_DEVIATION = 15.0
HEAD_POSE_ALERT_DURATION = 2.5
HEAD_NOD_DEVIATION = 15.0
HEAD_NOD_DURATION = 1.3
PERCLOS_WINDOW_SEC = 60.0
PERCLOS_THRESHOLD = 0.15
PERCLOS_MIN_SAMPLES = 30

# ─── Calibration (original DDS calibration.py constants) ───
CALIBRATION_DURATION = 5.0
MIN_CALIBRATION_SAMPLES = 15
EAR_CALIB_FACTOR = 0.75
MAR_CALIB_MARGIN = 0.20
EAR_THRESHOLD_MIN, EAR_THRESHOLD_MAX = 0.15, 0.30
MAR_THRESHOLD_MIN, MAR_THRESHOLD_MAX = 0.40, 0.90

# ─── Event cooldowns (seconds) to avoid spamming the event log ───
COOLDOWN_DROWSY = 20.0      # re-armed earlier when driver returns to NORMAL
COOLDOWN_HEAD = 15.0
COOLDOWN_ALERT = 20.0

BUS_ID = "PROTO-001"
REG_NO = "TN-01-PROTO-001"

_face_cascade = None
_eye_cascade = None
_landmarker = None


def _load_cascades():
    global _face_cascade, _eye_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(
            os.path.join(CASCADE_DIR, "haarcascade_frontalface_default.xml"))
        _eye_cascade = cv2.CascadeClassifier(
            os.path.join(CASCADE_DIR, "haarcascade_eye.xml"))
        print("[driver_dds] Haar cascades loaded")


def _load_landmarker():
    global _landmarker
    if _landmarker is not None:
        return True
    try:
        import mediapipe as mp  # noqa: F401  (binds `mp` for _detect_with_landmarker)
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        model_path = os.path.join(MODELS_DIR, "face_landmarker.task")
        if not os.path.exists(model_path):
            print(f"[driver_dds] FaceLandmarker model not found at {model_path}")
            return False

        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options, num_faces=1,
            min_face_detection_confidence=0.3,
            min_face_presence_confidence=0.3,
            min_tracking_confidence=0.3,
        )
        _landmarker = vision.FaceLandmarker.create_from_options(options)
        print("[driver_dds] FaceLandmarker loaded")
        return True
    except Exception as e:
        print(f"[driver_dds] FaceLandmarker unavailable: {e}")
        return False


def _detect_with_landmarker(frame):
    """MediaPipe FaceLandmarker: EAR + MAR + head pose (original DDS method)."""
    try:
        import mediapipe as mp

        LEFT_EYE = [33, 160, 158, 133, 153, 144]
        RIGHT_EYE = [362, 385, 387, 263, 373, 380]

        def ear_dist(lm, a, b):
            return ((lm[a].x - lm[b].x) ** 2 + (lm[a].y - lm[b].y) ** 2) ** 0.5

        def eye_ear(lm, eye):
            v1 = ear_dist(lm, eye[1], eye[5])
            v2 = ear_dist(lm, eye[2], eye[4])
            h = ear_dist(lm, eye[0], eye[3])
            return (v1 + v2) / (2 * h) if h > 0 else 0

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        det = _landmarker.detect(mp_image)

        if not det.face_landmarks:
            return None

        lm = det.face_landmarks[0]
        ear = (eye_ear(lm, LEFT_EYE) + eye_ear(lm, RIGHT_EYE)) / 2

        # MAR — mouth aspect ratio
        mar_vert = ear_dist(lm, 13, 14)
        mar_horiz = ear_dist(lm, 61, 291)
        mar = mar_vert / mar_horiz if mar_horiz > 0 else 0.0

        # Head pose via solvePnP
        h, w = frame.shape[:2]
        NOSE, CHIN, LEye, REye, LMouth, RMouth = 1, 152, 33, 263, 61, 291
        MODEL = np.array([
            (0.0, 0.0, 0.0),
            (0.0, -330.0, -65.0),
            (-225.0, 170.0, -135.0),
            (225.0, 170.0, -135.0),
            (-150.0, -150.0, -125.0),
            (150.0, -150.0, -125.0),
        ], dtype="double")
        pts = np.array([(lm[i].x * w, lm[i].y * h)
                        for i in [NOSE, CHIN, LEye, REye, LMouth, RMouth]], dtype="double")
        cam = np.array([[w, 0, w / 2], [0, w, h / 2], [0, 0, 1]], dtype="double")
        ok, rvec, tvec = cv2.solvePnP(MODEL, pts, cam, np.zeros((4, 1)), flags=cv2.SOLVEPNP_ITERATIVE)
        pitch = yaw = roll = 0.0
        if ok:
            rmat, _ = cv2.Rodrigues(rvec)
            _, _, _, _, _, _, euler = cv2.decomposeProjectionMatrix(cv2.hconcat((rmat, tvec)))
            pitch, yaw, roll = euler.flatten()
            if pitch > 90:
                pitch -= 180
            elif pitch < -90:
                pitch += 180

        # Draw face mesh + mouth landmarks on the frame (visible in the feed).
        # Thickness 2 so the mesh survives JPEG compression in the stream.
        for eye in [LEFT_EYE, RIGHT_EYE]:
            pts_eye = [(int(lm[i].x * w), int(lm[i].y * h)) for i in eye]
            for j in range(len(pts_eye)):
                cv2.line(frame, pts_eye[j], pts_eye[(j + 1) % len(pts_eye)], (0, 255, 0), 2)

        cv2.circle(frame, (int(lm[13].x * w), int(lm[13].y * h)), 3, (0, 0, 255), -1)
        cv2.circle(frame, (int(lm[14].x * w), int(lm[14].y * h)), 3, (0, 0, 255), -1)

        return {
            "ear": round(ear, 3), "mar": round(mar, 3),
            "pitch": round(pitch, 1), "yaw": round(yaw, 1), "roll": round(roll, 1),
        }
    except Exception as e:
        print(f"[driver_dds] Landmarker detect error: {e}")
        return None


def _detect_with_haar(frame, enhanced):
    """Haar cascade face+eye detection with approximate EAR (DDS fallback)."""
    h, w = frame.shape[:2]
    faces = _face_cascade.detectMultiScale(enhanced, 1.05, 2, minSize=(40, 40))
    if len(faces) == 0:
        return None

    fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (0, 255, 0), 2)

    face_roi = enhanced[fy:fy + fh, fx:fx + fw]
    eyes = _eye_cascade.detectMultiScale(face_roi, 1.1, 3, minSize=(15, 15))

    ear = 0.0
    eyes_found = 0

    if len(eyes) >= 2:
        eyes_found = 2
        sorted_eyes = sorted(eyes[:2], key=lambda e: e[0])
        ear_vals = [(e[3] / max(e[2], 1)) for e in sorted_eyes]
        ear = sum(ear_vals) / len(ear_vals)
        for (ex, ey, ew, eh) in sorted_eyes:
            cv2.rectangle(frame, (fx + ex, fy + ey), (fx + ex + ew, fy + ey + eh), (0, 255, 255), 1)
    elif len(eyes) == 1:
        eyes_found = 1
        ex, ey, ew, eh = eyes[0]
        ear = eh / max(ew, 1)
        cv2.rectangle(frame, (fx + ex, fy + ey), (fx + ex + ew, fy + ey + eh), (0, 255, 255), 1)
    else:
        eyes_found = 0
        face_ratio = fh / max(fw, 1)
        ear = 0.15 if face_ratio > 1.15 else 0.35

    # Approximate MAR from face region (mouth area is lower 40% of face)
    mouth_top = fy + int(fh * 0.6)
    mouth_roi = enhanced[mouth_top:fy + fh, fx:fx + fw]
    mar = 0.0
    if mouth_roi.size > 0:
        _, thresh = cv2.threshold(mouth_roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            mouth_area = mouth_roi.shape[0] * mouth_roi.shape[1]
            mar = min(1.0, area / max(mouth_area, 1))

    return {
        "ear": round(ear, 3),
        "mar": round(mar, 3),
        "pitch": 0.0, "yaw": 0.0, "roll": 0.0,
        "face_box": (fx, fy, fw, fh),
        "eyes_found": eyes_found,
    }


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DriverDrowsinessDetector:
    """Real DDS driver-monitoring engine with calibration + monitoring phases."""

    def __init__(self, event_callback=None):
        self._event_callback = event_callback
        self._lock = threading.Lock()
        self.ear = 0.0
        self.mar = 0.0
        self.head_pitch = 0.0
        self.head_yaw = 0.0
        self.head_roll = 0.0
        self.eye_closed_time = 0.0
        self.state = "NORMAL"
        self.perclos = 0.0
        self.drowsy_percent = 0.0
        self.attention_percent = 0.0
        self.yawn_count = 0
        self.fatigue_alerts = 0

        # Active thresholds (set by calibration, else defaults)
        self.ear_threshold = EAR_THRESHOLD
        self.mar_threshold = MAR_THRESHOLD
        self.baseline_pitch = 0.0

        # ── Engine phase: idle | calibrating | ready | monitoring ──
        self.phase = "idle"
        self.monitoring_started_at = None

        # ── Calibration state (original DDS calibration flow) ──
        self.calib = {
            "started_at": None,
            "samples": 0,
            "target_samples": MIN_CALIBRATION_SAMPLES,
            "duration": CALIBRATION_DURATION,
            "face_found": False,
            "completed": False,
            "message": "",
        }
        self._calib_ear = []
        self._calib_mar = []
        self._calib_pitch = []

        # ── Event emission ──
        self.events_emitted = 0
        self.audio_triggered = 0
        self._last_status = "NORMAL"
        self._alert_issued_for_episode = False
        self._last_event_time = {}

        # ── Tracking ──
        self._eye_closed_start = None
        self._yawn_start = None
        self._ear_timestamps = deque()
        self._head_nod_start = None
        self._head_pose_alert_start = None

        # ── Audio (original DDS alert manager, lazy) ──
        self._audio = None
        self._audio_ok = False
        self._audio_level = None

    # ------------------------------------------------------------------ audio
    def _ensure_audio(self):
        """Load the ORIGINAL DDS alert manager (bus_node.utils.alert_manager)."""
        if self._audio is not None:
            return self._audio_ok
        try:
            from bus_node.utils.alert_manager import AlertManager
            self._audio = AlertManager()
            self._audio_ok = True
            print("[driver_dds] Original DDS AlertManager loaded (audio warning active)")
        except Exception as e:
            self._audio = None
            self._audio_ok = False
            print(f"[driver_dds] Audio warning unavailable: {e}")
        return self._audio_ok

    # ------------------------------------------------------------- callbacks
    def set_event_callback(self, fn):
        self._event_callback = fn

    def _emit(self, event):
        """Push a live event into the Control Centre event system."""
        if not self._event_callback:
            return
        try:
            self._event_callback(event)
            self.events_emitted += 1
        except Exception as e:
            print(f"[driver_dds] Event callback error: {e}")

    def _build_event(self, event_type, severity, confidence, note, extra=None):
        data = {
            "bus_id": BUS_ID,
            "reg_no": REG_NO,
            "event_type": event_type,
            "latitude": None,
            "longitude": None,
            "severity": severity,
            "confidence": round(confidence, 2),
            "sensor_source": "driver_ai",
            "camera_id": "driver",
            "data_source": "live",
            "status": "ACTIVE",
            "simulation": False,
            "additional_data": {
                "note": note,
                "ear": round(self.ear, 3),
                "mar": round(self.mar, 3),
                "closed_sec": round(self.eye_closed_time, 2),
                "perclos": round(self.perclos, 3),
                "head_pitch_deg": round(self.head_pitch, 1),
                "ear_threshold": round(self.ear_threshold, 3),
                "mar_threshold": round(self.mar_threshold, 3),
                "drowsy_percent": self.drowsy_percent,
                "attention_percent": self.attention_percent,
            },
        }
        if extra:
            data["additional_data"].update(extra)
        return data

    # ---------------------------------------------------------- calibration
    def start_calibration(self):
        """Begin the 5 s personal baseline calibration (original DDS flow)."""
        with self._lock:
            if self.phase == "monitoring":
                return False, "Stop monitoring before calibrating."
            self.phase = "calibrating"
            self.calib = {
                "started_at": time.time(),
                "samples": 0,
                "target_samples": MIN_CALIBRATION_SAMPLES,
                "duration": CALIBRATION_DURATION,
                "face_found": False,
                "completed": False,
                "message": "CALIBRATING... Collecting baseline...",
            }
            self._calib_ear = []
            self._calib_mar = []
            self._calib_pitch = []
            self._stop_audio()
            print("[driver_dds] Calibration started")
            return True, "Calibration started"

    def _finish_calibration(self):
        """Compute personal thresholds using the original DDS calibration math."""
        ear_samples = self._calib_ear
        mar_samples = self._calib_mar
        pitch_samples = self._calib_pitch

        if len(ear_samples) < MIN_CALIBRATION_SAMPLES:
            self.phase = "idle"
            self.calib["completed"] = False
            self.calib["message"] = f"Calibration failed: only {len(ear_samples)} samples (need {MIN_CALIBRATION_SAMPLES}). Face not visible?"
            print(f"[driver_dds] {self.calib['message']}")
            return

        baseline_ear = float(np.median(ear_samples))
        baseline_mar = float(np.median(mar_samples))
        baseline_pitch = float(np.median(pitch_samples)) if pitch_samples else 0.0

        self.ear_threshold = max(EAR_THRESHOLD_MIN, min(baseline_ear * EAR_CALIB_FACTOR, EAR_THRESHOLD_MAX))
        self.mar_threshold = max(MAR_THRESHOLD_MIN, min(baseline_mar + MAR_CALIB_MARGIN, MAR_THRESHOLD_MAX))
        self.baseline_pitch = baseline_pitch

        self.phase = "ready"
        self.calib["completed"] = True
        self.calib["message"] = "CALIBRATION COMPLETE"
        print(f"[driver_dds] Calibration complete: EAR thr={self.ear_threshold:.3f}, MAR thr={self.mar_threshold:.3f}")

    # ----------------------------------------------------------- monitoring
    def start_monitoring(self):
        """Start the real DDS monitoring loop (uses calibrated thresholds)."""
        with self._lock:
            if self.phase == "monitoring":
                return False, "Already monitoring."
            if self.phase not in ("ready", "idle", "calibrating"):
                return False, f"Cannot start from phase {self.phase}."
            if self.phase == "calibrating":
                # Calibration still running: use current partial/previous thresholds.
                if not self.calib["completed"]:
                    self._finish_calibration()
            if self.phase != "ready":
                # Not calibrated -> run with default thresholds (original config).
                self.ear_threshold = EAR_THRESHOLD
                self.mar_threshold = MAR_THRESHOLD
                self.phase = "ready"
            self.phase = "monitoring"
            self.monitoring_started_at = time.time()
            self._last_status = "NORMAL"
            self._alert_issued_for_episode = False
            self._last_event_time = {}
            self._ensure_audio()
            print("[driver_dds] Monitoring started "
                  f"(EAR thr={self.ear_threshold:.3f}, MAR thr={self.mar_threshold:.3f})")
            return True, "Monitoring started"

    def stop_monitoring(self):
        with self._lock:
            was = self.phase
            if self.phase == "monitoring":
                self.phase = "ready"
            self._stop_audio()
            print(f"[driver_dds] Monitoring stopped (was {was})")
            return True, "Monitoring stopped"

    def reset(self):
        """Full reset: idle, no calibration, no monitoring."""
        with self._lock:
            self.phase = "idle"
            self.ear_threshold = EAR_THRESHOLD
            self.mar_threshold = MAR_THRESHOLD
            self.baseline_pitch = 0.0
            self.calib = {
                "started_at": None, "samples": 0, "target_samples": MIN_CALIBRATION_SAMPLES,
                "duration": CALIBRATION_DURATION, "face_found": False,
                "completed": False, "message": "",
            }
            self._calib_ear = []
            self._calib_mar = []
            self._calib_pitch = []
            self.monitoring_started_at = None
            self._last_status = "NORMAL"
            self._alert_issued_for_episode = False
            self._last_event_time = {}
            self.events_emitted = 0
            self.audio_triggered = 0
            self._audio_level = None
            self._reset_trackers()
            self._stop_audio()
            print("[driver_dds] Reset to idle")
            return True, "DDS engine reset"

    def _stop_audio(self):
        if self._audio is not None:
            try:
                self._audio.stop()
            except Exception:
                pass

    def _set_audio_severity(self, severity):
        if self._audio is None:
            return
        try:
            target = severity if severity in ("CRITICAL", "WARNING") else None
            if target != self._audio_level:
                self._audio_level = target
                self._audio.update(target)  # None stops the loop; else starts/loops
                if target is not None:
                    self.audio_triggered += 1
        except Exception as e:
            print(f"[driver_dds] Audio error: {e}")

    # ---------------------------------------------------------------- frames
    def _reset_trackers(self):
        self._eye_closed_start = None
        self._yawn_start = None
        self._head_nod_start = None
        self._head_pose_alert_start = None
        self.eye_closed_time = 0.0
        self.perclos = 0.0
        self.drowsy_percent = 0.0
        self.attention_percent = 0.0
        # Face absent -> wipe the PERCLOS window so stale closure flags from
        # an untracked period can never trigger a false drowsiness state.
        self._ear_timestamps.clear()

    def process_frame(self, frame):
        """Run the real DDS detection on one camera frame (called by CameraManager)."""
        _load_cascades()

        results = {
            "ear": 0.0, "mar": 0.0,
            "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0,
            "closed_sec": 0.0, "drowsy": False,
            "state": "NORMAL", "severity": "NONE",
            "perclos": 0.0, "confidence": 0.0,
            "face_detected": False, "eyes_detected": 0,
            "yawn_count": 0, "yawning": False,
            "drowsy_percent": 0.0, "attention_percent": 0.0,
            "engine_phase": self.phase,
            "ear_threshold": round(self.ear_threshold, 3),
            "mar_threshold": round(self.mar_threshold, 3),
            "monitoring": self.phase == "monitoring",
        }

        if frame is None:
            return results

        now = time.time()

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)

            # MediaPipe FaceLandmarker is the PRIMARY detector (it produces the
            # real EAR/MAR/head-pose values and the visible face mesh). Haar is
            # ONLY a last-resort fallback when MediaPipe itself is unavailable
            # (import/model missing) — never for a per-frame "no face" miss,
            # because Haar hallucinates faces from the background and fabricates
            # EAR/MAR/drowsiness (the noise the user saw).
            lm_available = _load_landmarker()
            if lm_available:
                lm_result = _detect_with_landmarker(frame)
                if lm_result is None:
                    # Landmarker loaded but no face in this frame -> honest NO FACE
                    results["state"] = "NO FACE"
                    results["severity"] = "INFO"
                    self._reset_trackers()
                    return results

                results["face_detected"] = True
                results["ear"] = lm_result["ear"]
                results["mar"] = lm_result["mar"]
                results["head_pitch"] = lm_result["pitch"]
                results["head_yaw"] = lm_result["yaw"]
                results["head_roll"] = lm_result["roll"]
                self.ear = lm_result["ear"]
                self.mar = lm_result["mar"]
                self.head_pitch = lm_result["pitch"]
                self.head_yaw = lm_result["yaw"]
                self.head_roll = lm_result["roll"]
                results["eyes_detected"] = 2
            else:
                # MediaPipe truly unavailable (no model / bad install): Haar only.
                haar_result = _detect_with_haar(frame, enhanced)
                if haar_result is None:
                    results["state"] = "NO FACE"
                    results["severity"] = "INFO"
                    self._reset_trackers()
                    return results

                results["face_detected"] = True
                results["eyes_detected"] = haar_result["eyes_found"]
                results["ear"] = haar_result["ear"]
                results["mar"] = haar_result["mar"]
                self.ear = haar_result["ear"]
                self.mar = haar_result["mar"]

            ear = results["ear"]
            mar = results["mar"]
            pitch = results["head_pitch"]

            # ─── EAR history (time-based, 60 s window) ───
            self._ear_timestamps.append((now, ear))
            cutoff = now - PERCLOS_WINDOW_SEC
            while self._ear_timestamps and self._ear_timestamps[0][0] < cutoff:
                self._ear_timestamps.popleft()

            # ─── Eye closure tracking (calibrated threshold) ───
            is_closed = ear > 0 and ear < self.ear_threshold
            if is_closed:
                if self._eye_closed_start is None:
                    self._eye_closed_start = now
                closed = now - self._eye_closed_start
                results["closed_sec"] = round(closed, 2)
                self.eye_closed_time = closed
            else:
                self._eye_closed_start = None
                results["closed_sec"] = 0.0
                self.eye_closed_time = 0.0

            # ─── Yawn tracking (temporal MAR analysis) ───
            # A confirmed yawn requires sustained mouth opening (> YAWN_DURATION)
            # above the calibrated MAR threshold. Brief mouth movements (talking,
            # coughing) are too short to qualify.
            is_yawning = mar > self.mar_threshold
            results["yawning"] = False
            if is_yawning:
                if self._yawn_start is None:
                    self._yawn_start = now
                elif now - self._yawn_start >= YAWN_DURATION:
                    # Confirmed yawn: sustained MAR above threshold
                    self.yawn_count += 1
                    results["yawning"] = True
                    results["yawn_count"] = self.yawn_count
                    self._yawn_start = None  # reset for next yawn
            else:
                # Mouth closed / below threshold → reset the yawn timer
                self._yawn_start = None
            results["yawn_count"] = self.yawn_count

            # ─── PERCLOS (time-based, 60 s window) ───
            n = len(self._ear_timestamps)
            if n:
                closed_count = sum(1 for _, e in self._ear_timestamps if 0 < e < self.ear_threshold)
                perclos = closed_count / n if n > 0 else 0.0
                results["perclos"] = round(perclos, 3)
                self.perclos = perclos
            else:
                results["perclos"] = 0.0

            # ─── Head nod detection (down, 15 deg, 1.3 s) ───
            nod_detected = False
            if pitch > HEAD_NOD_DEVIATION:
                if self._head_nod_start is None:
                    self._head_nod_start = now
                elif now - self._head_nod_start >= HEAD_NOD_DURATION:
                    nod_detected = True
                    self._head_nod_start = None
            else:
                self._head_nod_start = None

            # ─── Head pose alert (both, 15 deg, 2.5 s) ───
            pose_alert = False
            deviation = abs(pitch) + abs(results["head_yaw"])
            if deviation > HEAD_POSE_ALERT_DEVIATION:
                if self._head_pose_alert_start is None:
                    self._head_pose_alert_start = now
                elif now - self._head_pose_alert_start >= HEAD_POSE_ALERT_DURATION:
                    pose_alert = True
                    self._head_pose_alert_start = None
            else:
                self._head_pose_alert_start = None

            # ─── State classification (original DDS fatigue_engine logic) ───
            if self.eye_closed_time >= EYE_CLOSED_DURATION:
                results["state"] = "DROWSINESS DETECTED"
                results["severity"] = "CRITICAL"
                results["drowsy"] = True
                results["confidence"] = min(0.95, 0.7 + self.eye_closed_time * 0.1)
            elif self.perclos >= PERCLOS_THRESHOLD and n >= PERCLOS_MIN_SAMPLES:
                results["state"] = "DROWSINESS DETECTED (PERCLOS)"
                results["severity"] = "CRITICAL"
                results["drowsy"] = True
                results["confidence"] = 0.85
            elif pose_alert:
                results["state"] = "HEAD POSE ALERT"
                results["severity"] = "WARNING"
                results["confidence"] = 0.7
            elif nod_detected:
                results["state"] = "HEAD NOD DETECTED"
                results["severity"] = "WARNING"
                results["confidence"] = 0.7
            elif is_closed:
                results["state"] = "EYES CLOSED"
                results["severity"] = "INFO"
                results["confidence"] = 0.5
            else:
                results["state"] = "NORMAL"
                results["severity"] = "NONE"
                results["confidence"] = 0.9

            # ─── Drowsy / attention percent ───
            closed_ratio = min(1.0, self.eye_closed_time / EYE_CLOSED_DURATION) if self.eye_closed_time > 0 else 0.0
            # Only use PERCLOS for the percent if enough samples (same guard as
            # the state machine) — with 1–2 samples the ratio is meaningless.
            perclos_ratio = min(1.0, self.perclos / PERCLOS_THRESHOLD) if self.perclos > 0 and n >= PERCLOS_MIN_SAMPLES else 0.0
            self.drowsy_percent = round(100 * max(closed_ratio, perclos_ratio))
            results["drowsy_percent"] = self.drowsy_percent

            distraction = max(closed_ratio * 100, perclos_ratio * 100)
            self.attention_percent = max(0, 100 - round(distraction))
            results["attention_percent"] = self.attention_percent

            self.state = results["state"]

            # ─── Calibration sampling (only while phase == calibrating) ───
            if self.phase == "calibrating":
                if results["face_detected"]:
                    self.calib["face_found"] = True
                    self._calib_ear.append(ear)
                    self._calib_mar.append(mar)
                    self._calib_pitch.append(pitch)
                    self.calib["samples"] = len(self._calib_ear)
                remaining = CALIBRATION_DURATION - (now - (self.calib["started_at"] or now))
                results["calibration"] = {
                    "phase": "calibrating",
                    "samples": self.calib["samples"],
                    "target_samples": MIN_CALIBRATION_SAMPLES,
                    "remaining": round(max(0.0, remaining), 1),
                    "face_found": self.calib["face_found"],
                    "message": self.calib["message"],
                }
                if now - (self.calib["started_at"] or now) >= CALIBRATION_DURATION:
                    self._finish_calibration()
                    results["engine_phase"] = self.phase
                    results["ear_threshold"] = round(self.ear_threshold, 3)
                    results["mar_threshold"] = round(self.mar_threshold, 3)
                    results["calibration"] = {
                        "phase": self.phase,
                        "completed": self.calib["completed"],
                        "samples": self.calib["samples"],
                        "ear_threshold": round(self.ear_threshold, 3),
                        "mar_threshold": round(self.mar_threshold, 3),
                        "message": self.calib["message"],
                    }
                return results

            # ─── Monitoring: event emission + audio (edge-triggered) ───
            if self.phase == "monitoring":
                status = results["state"]
                prev = self._last_status

                drowsy_now = status in ("DROWSINESS DETECTED", "DROWSINESS DETECTED (PERCLOS)")
                head_now = status in ("HEAD NOD DETECTED", "HEAD POSE ALERT")

                # Audio warning (original DDS mechanism) on severity transitions
                if drowsy_now:
                    self._set_audio_severity("CRITICAL")
                elif head_now:
                    self._set_audio_severity("WARNING")
                else:
                    self._set_audio_severity(None)

                # DRIVER_DROWSINESS on drowsy start (re-arms when back to NORMAL)
                if drowsy_now and prev not in ("DROWSINESS DETECTED", "DROWSINESS DETECTED (PERCLOS)"):
                    self._emit(self._build_event(
                        "DRIVER_DROWSINESS", "CRITICAL", results["confidence"],
                        "Drowsiness detected by live DDS engine (eye closure / PERCLOS).",
                    ))
                    # Cabin audio warning event (once per episode)
                    if not self._alert_issued_for_episode:
                        self._alert_issued_for_episode = True
                        self._emit(self._build_event(
                            "DRIVER_ALERT", "CRITICAL", results["confidence"],
                            "Drowsiness detected; cabin audio warning issued (original DDS alarm).",
                            extra={
                                "cabin_action": {
                                    "type": "AUDIO_WARNING", "channel": "speakers",
                                    "message": "DRIVER ALERT - wake up",
                                },
                                "audio": "ORIGINAL_DDS_WARNING",
                            },
                        ))
                elif not drowsy_now and prev in ("DROWSINESS DETECTED", "DROWSINESS DETECTED (PERCLOS)"):
                    # Episode over -> re-arm for next episode
                    self._alert_issued_for_episode = False

                # Head nod / pose alert (cooldown-capped)
                if head_now and prev not in ("HEAD NOD DETECTED", "HEAD POSE ALERT"):
                    now_t = time.time()
                    if now_t - self._last_event_time.get("head", 0) >= COOLDOWN_HEAD:
                        self._last_event_time["head"] = now_t
                        self._emit(self._build_event(
                            "DRIVER_DROWSINESS", "WARNING", results["confidence"],
                            f"{status} by live DDS engine (head pose analysis).",
                        ))

                self._last_status = status

            # Fatigue alert counter (kept from earlier behaviour)
            if results["severity"] == "CRITICAL":
                self.fatigue_alerts += 1

        except Exception as e:
            print(f"[driver_dds] Error: {e}")

        return results

    # ------------------------------------------------------------- status
    def get_current_state(self):
        return {
            "state": self.state, "ear": self.ear, "mar": self.mar,
            "head_pitch": self.head_pitch, "head_yaw": self.head_yaw,
            "head_roll": self.head_roll,
            "perclos": self.perclos, "eye_closed_time": self.eye_closed_time,
            "yawn_count": self.yawn_count,
            "drowsy_percent": self.drowsy_percent,
            "attention_percent": self.attention_percent,
            "fatigue_alerts": self.fatigue_alerts,
            "phase": self.phase,
            "ear_threshold": round(self.ear_threshold, 3),
            "mar_threshold": round(self.mar_threshold, 3),
            "timestamp": utcnow_iso(),
        }

    def get_status(self):
        """Full engine status for /api/dds/status."""
        calib = dict(self.calib)
        calib["ear_threshold"] = round(self.ear_threshold, 3)
        calib["mar_threshold"] = round(self.mar_threshold, 3)
        calib["baseline_pitch"] = round(self.baseline_pitch, 1)
        if self.phase == "calibrating" and calib.get("started_at"):
            calib["remaining"] = round(max(0.0, CALIBRATION_DURATION - (time.time() - calib["started_at"])), 1)
        else:
            calib["remaining"] = 0.0

        monitoring_seconds = 0.0
        if self.phase == "monitoring" and self.monitoring_started_at:
            monitoring_seconds = round(time.time() - self.monitoring_started_at, 1)

        return {
            "phase": self.phase,
            "monitoring": self.phase == "monitoring",
            "monitoring_seconds": monitoring_seconds,
            "calibration": calib,
            "thresholds": {
                "ear_threshold": round(self.ear_threshold, 3),
                "mar_threshold": round(self.mar_threshold, 3),
                "baseline_pitch": round(self.baseline_pitch, 1),
            },
            "last": {
                "state": self.state,
                "ear": round(self.ear, 3),
                "mar": round(self.mar, 3),
                "head_pitch": round(self.head_pitch, 1),
                "head_yaw": round(self.head_yaw, 1),
                "closed_sec": round(self.eye_closed_time, 2),
                "perclos": round(self.perclos, 3),
                "drowsy_percent": self.drowsy_percent,
                "attention_percent": self.attention_percent,
                "yawn_count": self.yawn_count,
            },
            "audio": {
                "enabled": self._audio_ok,
                "triggered": self.audio_triggered,
            },
            "events_emitted": self.events_emitted,
            "bus_id": BUS_ID,
            "data_source": "live",
            "simulation": False,
            "timestamp": utcnow_iso(),
        }


driver_detector = DriverDrowsinessDetector()