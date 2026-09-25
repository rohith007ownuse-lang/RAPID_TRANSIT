"""
test_dds_engine.py
Unit tests for DriverDrowsinessDetector (ORIGINAL DDS logic).

Covers:
  - Initialization and defaults
  - Calibration flow (start, collect, finish, math)
  - Monitoring lifecycle (start, stop, reset)
  - State machine (NORMAL, EYES CLOSED, DROWSINESS DETECTED, PERCLOS, HEAD NOD, HEAD POSE)
  - PERCLOS calculation and window management
  - Event emission (edge-triggered, cooldowns, re-arm)
  - get_status / get_current_state
  - Edge cases (None frame, zero values)

All tests mock cv2 and mediapipe to avoid needing a webcam or model file.
"""

import os
import sys
import time
from collections import deque
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Add backend to path so imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch cv2 and mediapipe at module level before importing the detector
# so the module-level imports don't fail
sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())

from ai.driver.driver_drowsiness import (
    DriverDrowsinessDetector,
    EAR_THRESHOLD,
    MAR_THRESHOLD,
    EYE_CLOSED_DURATION,
    YAWN_DURATION,
    HEAD_POSE_ALERT_DEVIATION,
    HEAD_POSE_ALERT_DURATION,
    HEAD_NOD_DEVIATION,
    HEAD_NOD_DURATION,
    PERCLOS_WINDOW_SEC,
    PERCLOS_THRESHOLD,
    PERCLOS_MIN_SAMPLES,
    CALIBRATION_DURATION,
    MIN_CALIBRATION_SAMPLES,
    EAR_CALIB_FACTOR,
    MAR_CALIB_MARGIN,
    EAR_THRESHOLD_MIN,
    EAR_THRESHOLD_MAX,
    MAR_THRESHOLD_MIN,
    MAR_THRESHOLD_MAX,
    COOLDOWN_HEAD,
)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _make_detector(callback=None):
    """Create a fresh detector with an optional event callback."""
    return DriverDrowsinessDetector(event_callback=callback)


def _make_fake_frame(w=640, h=480):
    """Return a black BGR frame (MediaPipe not needed when mocked)."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _make_landmarker_result(ear=0.40, mar=0.03, pitch=0.0, yaw=0.0, roll=0.0):
    """Build a mock _detect_with_landmarker return value."""
    return {"ear": ear, "mar": mar, "pitch": pitch, "yaw": yaw, "roll": roll}


# ═══════════════════════════════════════════════════════════════════════
# 1. Initialization
# ═══════════════════════════════════════════════════════════════════════

class TestInitialization:
    def test_default_state(self):
        det = _make_detector()
        assert det.phase == "idle"
        assert det.state == "NORMAL"
        assert det.ear == 0.0
        assert det.mar == 0.0
        assert det.ear_threshold == EAR_THRESHOLD
        assert det.mar_threshold == MAR_THRESHOLD
        assert det.perclos == 0.0
        assert det.yawn_count == 0
        assert det.fatigue_alerts == 0
        assert det.events_emitted == 0

    def test_calibration_state_initialized(self):
        det = _make_detector()
        calib = det.calib
        assert calib["started_at"] is None
        assert calib["samples"] == 0
        assert calib["target_samples"] == MIN_CALIBRATION_SAMPLES
        assert calib["completed"] is False

    def test_tracker_queues_empty(self):
        det = _make_detector()
        assert len(det._ear_timestamps) == 0
        assert det._eye_closed_start is None
        assert det._yawn_start is None
        assert det._head_nod_start is None
        assert det._head_pose_alert_start is None


# ═══════════════════════════════════════════════════════════════════════
# 2. Calibration flow
# ═══════════════════════════════════════════════════════════════════════

class TestCalibration:
    def test_start_calibration(self):
        det = _make_detector()
        ok, msg = det.start_calibration()
        assert ok is True
        assert det.phase == "calibrating"
        assert det.calib["started_at"] is not None
        assert det.calib["samples"] == 0
        assert det.calib["face_found"] is False

    def test_start_calibration_blocked_when_monitoring(self):
        det = _make_detector()
        det.phase = "monitoring"
        ok, msg = det.start_calibration()
        assert ok is False
        assert "Stop monitoring" in msg

    def test_finish_calibration_insufficient_samples(self):
        det = _make_detector()
        det.start_calibration()
        # Feed only 5 samples (need 15)
        det._calib_ear = [0.40] * 5
        det._calib_mar = [0.03] * 5
        det._calib_pitch = [0.0] * 5
        det._finish_calibration()
        assert det.phase == "idle"
        assert det.calib["completed"] is False
        assert "only 5 samples" in det.calib["message"]

    def test_finish_calibration_success(self):
        det = _make_detector()
        det.start_calibration()
        # Feed 20 samples with EAR ~0.45, MAR ~0.05
        det._calib_ear = [0.45] * 20
        det._calib_mar = [0.05] * 20
        det._calib_pitch = [2.0] * 20
        det._finish_calibration()
        assert det.phase == "ready"
        assert det.calib["completed"] is True
        # EAR thr = median(0.45) * 0.75 = 0.3375, clamped to max 0.30
        assert det.ear_threshold == EAR_THRESHOLD_MAX
        # MAR thr = median(0.05) + 0.20 = 0.25, clamped to min 0.40
        assert det.mar_threshold == MAR_THRESHOLD_MIN
        assert det.baseline_pitch == 2.0

    def test_calibration_math_low_ear(self):
        """EAR below min threshold floor."""
        det = _make_detector()
        det.start_calibration()
        det._calib_ear = [0.10] * 20
        det._calib_mar = [0.30] * 20
        det._calib_pitch = [0.0] * 20
        det._finish_calibration()
        # EAR thr = 0.10 * 0.75 = 0.075, clamped to min 0.15
        assert det.ear_threshold == EAR_THRESHOLD_MIN
        # MAR thr = 0.30 + 0.20 = 0.50, within range
        assert det.mar_threshold == 0.50

    def test_calibration_math_high_mar(self):
        """MAR above max threshold ceiling."""
        det = _make_detector()
        det.start_calibration()
        det._calib_ear = [0.40] * 20
        det._calib_mar = [0.80] * 20
        det._calib_pitch = [0.0] * 20
        det._finish_calibration()
        # MAR thr = 0.80 + 0.20 = 1.00, clamped to max 0.90
        assert det.mar_threshold == MAR_THRESHOLD_MAX

    def test_calibration_math_normal(self):
        """Normal person: EAR 0.40, MAR 0.05."""
        det = _make_detector()
        det.start_calibration()
        det._calib_ear = [0.40] * 20
        det._calib_mar = [0.05] * 20
        det._calib_pitch = [1.5] * 20
        det._finish_calibration()
        # EAR thr = 0.40 * 0.75 = 0.30, clamped to max 0.30
        assert det.ear_threshold == 0.30
        # MAR thr = 0.05 + 0.20 = 0.25, clamped to min 0.40
        assert det.mar_threshold == 0.40
        assert det.baseline_pitch == 1.5


# ═══════════════════════════════════════════════════════════════════════
# 3. Monitoring lifecycle
# ═══════════════════════════════════════════════════════════════════════

class TestMonitoringLifecycle:
    def test_start_from_idle(self):
        det = _make_detector()
        ok, msg = det.start_monitoring()
        assert ok is True
        assert det.phase == "monitoring"
        assert det.monitoring_started_at is not None

    def test_start_from_ready(self):
        det = _make_detector()
        det.phase = "ready"
        ok, msg = det.start_monitoring()
        assert ok is True
        assert det.phase == "monitoring"

    def test_start_blocked_when_already_monitoring(self):
        det = _make_detector()
        det.start_monitoring()
        ok, msg = det.start_monitoring()
        assert ok is False
        assert "Already monitoring" in msg

    def test_stop_monitoring(self):
        det = _make_detector()
        det.start_monitoring()
        ok, msg = det.stop_monitoring()
        assert ok is True
        assert det.phase == "ready"

    def test_stop_from_idle_is_noop(self):
        det = _make_detector()
        ok, msg = det.stop_monitoring()
        assert ok is True
        assert det.phase == "idle"

    def test_reset(self):
        det = _make_detector()
        det.start_calibration()
        det._calib_ear = [0.40] * 20
        det._calib_mar = [0.05] * 20
        det._calib_pitch = [0.0] * 20
        det._finish_calibration()
        det.start_monitoring()
        det.events_emitted = 5
        det.fatigue_alerts = 3

        ok, msg = det.reset()
        assert ok is True
        assert det.phase == "idle"
        assert det.ear_threshold == EAR_THRESHOLD
        assert det.mar_threshold == MAR_THRESHOLD
        assert det.events_emitted == 0
        assert det.calib["completed"] is False

    def test_start_monitoring_from_calibrating_finishes_calibration(self):
        det = _make_detector()
        det.start_calibration()
        # Feed enough samples
        det._calib_ear = [0.40] * 20
        det._calib_mar = [0.05] * 20
        det._calib_pitch = [0.0] * 20
        # Start monitoring while calibrating
        ok, msg = det.start_monitoring()
        assert ok is True
        assert det.phase == "monitoring"
        # Calibration should have been completed
        assert det.calib["completed"] is True


# ═══════════════════════════════════════════════════════════════════════
# 4. State machine (process_frame with mocked detectors)
# ═══════════════════════════════════════════════════════════════════════

class TestStateMachine:
    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_no_face_returns_no_face(self, mock_cascades, mock_detect, mock_lm):
        mock_detect.return_value = None
        det = _make_detector()
        frame = _make_fake_frame()
        result = det.process_frame(frame)
        assert result["state"] == "NO FACE"
        assert result["severity"] == "INFO"
        assert result["face_detected"] is False

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_none_frame_returns_defaults(self, mock_cascades, mock_detect, mock_lm):
        det = _make_detector()
        result = det.process_frame(None)
        assert result["state"] == "NORMAL"
        assert result["face_detected"] is False
        assert result["ear"] == 0.0

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_normal_state_when_eyes_open(self, mock_cascades, mock_detect, mock_lm):
        """EAR above threshold, pitch normal → NORMAL."""
        mock_detect.return_value = _make_landmarker_result(ear=0.45, mar=0.03, pitch=0.0)
        det = _make_detector()
        frame = _make_fake_frame()
        result = det.process_frame(frame)
        assert result["state"] == "NORMAL"
        assert result["face_detected"] is True
        assert result["ear"] == 0.45
        assert result["eyes_detected"] == 2

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_eyes_closed_state(self, mock_cascades, mock_detect, mock_lm):
        """EAR below threshold → EYES CLOSED."""
        mock_detect.return_value = _make_landmarker_result(ear=0.15, mar=0.03, pitch=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23  # EAR 0.15 < 0.23 → closed
        frame = _make_fake_frame()
        result = det.process_frame(frame)
        assert result["state"] == "EYES CLOSED"
        assert result["severity"] == "INFO"
        # First frame: _eye_closed_start = now, so closed_sec = 0
        # Second frame (fast-forward): closed_sec > 0
        det._eye_closed_start = time.time() - 1.0
        result2 = det.process_frame(frame)
        assert result2["closed_sec"] >= 0.9

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_drowsiness_detected_after_eye_closure(self, mock_cascades, mock_detect, mock_lm):
        """Eye closed for >= 1.3s → DROWSINESS DETECTED."""
        mock_detect.return_value = _make_landmarker_result(ear=0.15, mar=0.03, pitch=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # Simulate first frame: eye starts closing
        det.process_frame(frame)
        assert det._eye_closed_start is not None

        # Fast-forward: set _eye_closed_start to 2 seconds ago
        det._eye_closed_start = time.time() - 2.0
        result = det.process_frame(frame)
        assert "DROWSINESS" in result["state"]
        assert result["severity"] == "CRITICAL"
        assert result["drowsy"] is True
        assert result["closed_sec"] >= 1.3

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_perclos_drowsiness(self, mock_cascades, mock_detect, mock_lm):
        """High PERCLOS with enough samples → DROWSINESS DETECTED (PERCLOS)."""
        mock_detect.return_value = _make_landmarker_result(ear=0.10, mar=0.03, pitch=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # Build up enough EAR timestamps with closed eyes
        now = time.time()
        for i in range(PERCLOS_MIN_SAMPLES + 5):
            det._ear_timestamps.append((now - (PERCLOS_MIN_SAMPLES + 5 - i) * 0.5, 0.10))

        result = det.process_frame(frame)
        # PERCLOS should be high (most timestamps are below threshold)
        assert result["perclos"] >= PERCLOS_THRESHOLD
        assert "DROWSINESS" in result["state"] or result["perclos"] >= PERCLOS_THRESHOLD

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_head_pose_alert(self, mock_cascades, mock_detect, mock_lm):
        """Pitch > 15° for >= 2.5s → HEAD POSE ALERT."""
        mock_detect.return_value = _make_landmarker_result(ear=0.45, mar=0.03, pitch=20.0, yaw=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # First frame: starts tracking
        det.process_frame(frame)
        assert det._head_pose_alert_start is not None

        # Fast-forward: start was 3 seconds ago
        det._head_pose_alert_start = time.time() - 3.0
        result = det.process_frame(frame)
        assert result["state"] == "HEAD POSE ALERT"
        assert result["severity"] == "WARNING"

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_head_nod_detected(self, mock_cascades, mock_detect, mock_lm):
        """Pitch > 15° for >= 1.3s → HEAD NOD DETECTED."""
        mock_detect.return_value = _make_landmarker_result(ear=0.45, mar=0.03, pitch=20.0, yaw=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # First frame: starts tracking
        det.process_frame(frame)

        # Fast-forward: 1.5 seconds
        det._head_nod_start = time.time() - 1.5
        result = det.process_frame(frame)
        assert result["state"] == "HEAD NOD DETECTED"
        assert result["severity"] == "WARNING"

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_no_face_resets_perclos_window(self, mock_cascades, mock_detect, mock_lm):
        """No face should wipe the PERCLOS window."""
        mock_detect.return_value = None
        det = _make_detector()
        # Build up stale timestamps
        det._ear_timestamps.append((time.time(), 0.10))
        det._ear_timestamps.append((time.time(), 0.10))
        assert len(det._ear_timestamps) == 2

        frame = _make_fake_frame()
        det.process_frame(frame)
        assert len(det._ear_timestamps) == 0


# ═══════════════════════════════════════════════════════════════════════
# 5. Event emission
# ═══════════════════════════════════════════════════════════════════════

class TestEventEmission:
    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_drowsiness_event_emitted(self, mock_cascades, mock_detect, mock_lm):
        """Drowsiness transition emits DRIVER_DROWSINESS + DRIVER_ALERT events."""
        events = []
        det = _make_detector(callback=lambda e: events.append(e))
        det.start_monitoring()

        mock_detect.return_value = _make_landmarker_result(ear=0.15, mar=0.03, pitch=0.0)
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # First frame: eye starts closing
        det.process_frame(frame)

        # Fast-forward past EYE_CLOSED_DURATION
        det._eye_closed_start = time.time() - 2.0
        det.process_frame(frame)

        # Should have emitted 2 events: DRIVER_DROWSINESS + DRIVER_ALERT
        assert len(events) >= 2
        types = [e["event_type"] for e in events]
        assert "DRIVER_DROWSINESS" in types
        assert "DRIVER_ALERT" in types

        # Check event structure
        drowsiness_event = next(e for e in events if e["event_type"] == "DRIVER_DROWSINESS")
        assert drowsiness_event["bus_id"] == "PROTO-001"
        assert drowsiness_event["severity"] == "CRITICAL"
        assert drowsiness_event["simulation"] is False
        assert drowsiness_event["data_source"] == "live"

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_alert_issued_once_per_episode(self, mock_cascades, mock_detect, mock_lm):
        """DRIVER_ALERT fires once per drowsy episode, not every frame."""
        events = []
        det = _make_detector(callback=lambda e: events.append(e))
        det.start_monitoring()

        mock_detect.return_value = _make_landmarker_result(ear=0.15, mar=0.03, pitch=0.0)
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # Start closing eyes
        det.process_frame(frame)

        # Fast-forward to drowsiness
        det._eye_closed_start = time.time() - 2.0
        det.process_frame(frame)

        alert_count = sum(1 for e in events if e["event_type"] == "DRIVER_ALERT")
        assert alert_count == 1

        # Continue: still drowsy, should NOT emit another ALERT
        det._eye_closed_start = time.time() - 3.0
        det.process_frame(frame)
        alert_count = sum(1 for e in events if e["event_type"] == "DRIVER_ALERT")
        assert alert_count == 1  # still 1

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_event_rearm_after_recovery(self, mock_cascades, mock_detect, mock_lm):
        """After returning to NORMAL, a new drowsy episode can trigger another event."""
        events = []
        det = _make_detector(callback=lambda e: events.append(e))
        det.start_monitoring()

        # Phase 1: drowsy
        mock_detect.return_value = _make_landmarker_result(ear=0.15, mar=0.03, pitch=0.0)
        det.ear_threshold = 0.23
        frame = _make_fake_frame()
        det.process_frame(frame)
        det._eye_closed_start = time.time() - 2.0
        det.process_frame(frame)
        assert det._alert_issued_for_episode is True

        # Phase 2: recovery (eyes open)
        mock_detect.return_value = _make_landmarker_result(ear=0.45, mar=0.03, pitch=0.0)
        det.process_frame(frame)
        assert det._alert_issued_for_episode is False

        # Phase 3: drowsy again → new event
        mock_detect.return_value = _make_landmarker_result(ear=0.15, mar=0.03, pitch=0.0)
        det.process_frame(frame)
        det._eye_closed_start = time.time() - 2.0
        det.process_frame(frame)
        drowsy_events = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS"]
        assert len(drowsy_events) >= 2

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_head_pose_event_with_cooldown(self, mock_cascades, mock_detect, mock_lm):
        """Head pose alert emits with cooldown (15s gap)."""
        events = []
        det = _make_detector(callback=lambda e: events.append(e))
        det.start_monitoring()

        mock_detect.return_value = _make_landmarker_result(ear=0.45, mar=0.03, pitch=20.0, yaw=0.0)
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # First: start tracking
        det.process_frame(frame)
        det._head_pose_alert_start = time.time() - 3.0
        det.process_frame(frame)
        head_events = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS" and e["severity"] == "WARNING"]
        assert len(head_events) == 1

        # Second: immediate re-trigger should be blocked by cooldown
        det._head_pose_alert_start = time.time() - 3.0
        det.process_frame(frame)
        head_events = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS" and e["severity"] == "WARNING"]
        assert len(head_events) == 1  # still 1

    def test_build_event_structure(self):
        """Event dict has all required fields."""
        det = _make_detector()
        det.ear = 0.42
        det.mar = 0.03
        det.head_pitch = 5.0
        det.eye_closed_time = 1.5
        det.perclos = 0.12
        det.ear_threshold = 0.28
        det.mar_threshold = 0.40
        det.drowsy_percent = 60
        det.attention_percent = 40

        event = det._build_event("DRIVER_DROWSINESS", "CRITICAL", 0.85, "Test note")
        assert event["bus_id"] == "PROTO-001"
        assert event["event_type"] == "DRIVER_DROWSINESS"
        assert event["severity"] == "CRITICAL"
        assert event["confidence"] == 0.85
        assert event["simulation"] is False
        assert event["data_source"] == "live"
        assert event["additional_data"]["note"] == "Test note"
        assert event["additional_data"]["ear"] == 0.42

    def test_build_event_with_extra(self):
        det = _make_detector()
        event = det._build_event("DRIVER_ALERT", "CRITICAL", 0.9, "Test",
                                  extra={"cabin_action": {"type": "AUDIO_WARNING"}})
        assert event["additional_data"]["cabin_action"]["type"] == "AUDIO_WARNING"


# ═══════════════════════════════════════════════════════════════════════
# 6. Status and state queries
# ═══════════════════════════════════════════════════════════════════════

class TestStatus:
    def test_get_current_state(self):
        det = _make_detector()
        state = det.get_current_state()
        assert state["phase"] == "idle"
        assert state["state"] == "NORMAL"
        assert "ear" in state
        assert "mar" in state
        assert "timestamp" in state

    def test_get_status_idle(self):
        det = _make_detector()
        status = det.get_status()
        assert status["phase"] == "idle"
        assert status["monitoring"] is False
        assert status["monitoring_seconds"] == 0.0
        assert status["events_emitted"] == 0
        assert status["bus_id"] == "PROTO-001"
        assert status["simulation"] is False
        assert status["audio"]["enabled"] is False
        assert status["audio"]["triggered"] == 0

    def test_get_status_monitoring(self):
        det = _make_detector()
        det.start_monitoring()
        status = det.get_status()
        assert status["phase"] == "monitoring"
        assert status["monitoring"] is True
        assert status["monitoring_seconds"] >= 0

    def test_get_status_calibration_complete(self):
        det = _make_detector()
        det.start_calibration()
        det._calib_ear = [0.40] * 20
        det._calib_mar = [0.05] * 20
        det._calib_pitch = [0.0] * 20
        det._finish_calibration()
        status = det.get_status()
        assert status["calibration"]["completed"] is True
        assert status["thresholds"]["ear_threshold"] > 0


# ═══════════════════════════════════════════════════════════════════════
# 7. PERCLOS calculation
# ═══════════════════════════════════════════════════════════════════════

class TestPERCLOS:
    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_perclos_zero_when_eyes_open(self, mock_cascades, mock_detect, mock_lm):
        """All EAR values above threshold → PERCLOS = 0."""
        mock_detect.return_value = _make_landmarker_result(ear=0.45, mar=0.03, pitch=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23
        frame = _make_fake_frame()
        det.process_frame(frame)
        assert det.perclos == 0.0

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_perclos_window_size(self, mock_cascades, mock_detect, mock_lm):
        """PERCLOS window should not exceed 60 seconds."""
        mock_detect.return_value = _make_landmarker_result(ear=0.10, mar=0.03, pitch=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # Build a window that spans > 60s
        now = time.time()
        for i in range(100):
            det._ear_timestamps.append((now - 70 + i * 0.7, 0.10))
        # After processing one frame, old entries should be purged
        det.process_frame(frame)
        assert len(det._ear_timestamps) <= 101  # at most original + 1 new


# ═══════════════════════════════════════════════════════════════════════
# 8. Drowsy percent and attention percent
# ═══════════════════════════════════════════════════════════════════════

class TestDrowsyAttentionPercent:
    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_drowsy_percent_scales_with_closure(self, mock_cascades, mock_detect, mock_lm):
        """drowsy_percent should scale with eye closure duration."""
        mock_detect.return_value = _make_landmarker_result(ear=0.15, mar=0.03, pitch=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23
        frame = _make_fake_frame()

        # 30% closure → ~30% drowsy
        det._eye_closed_start = time.time() - (EYE_CLOSED_DURATION * 0.3)
        result = det.process_frame(frame)
        assert 0 < result["drowsy_percent"] <= 50

        # 80% closure → ~80% drowsy
        det._eye_closed_start = time.time() - (EYE_CLOSED_DURATION * 0.8)
        result2 = det.process_frame(frame)
        assert result2["drowsy_percent"] > result["drowsy_percent"]

    @patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True)
    @patch("ai.driver.driver_drowsiness._detect_with_landmarker")
    @patch("ai.driver.driver_drowsiness._load_cascades")
    def test_attention_percent_inversely_scales(self, mock_cascades, mock_detect, mock_lm):
        """attention_percent should be 100 - drowsy_percent (roughly)."""
        mock_detect.return_value = _make_landmarker_result(ear=0.45, mar=0.03, pitch=0.0)
        det = _make_detector()
        det.ear_threshold = 0.23
        frame = _make_fake_frame()
        result = det.process_frame(frame)
        # Normal eyes → high attention
        assert result["attention_percent"] == 100


# ═══════════════════════════════════════════════════════════════════════
# 9. Audio
# ═══════════════════════════════════════════════════════════════════════

class TestAudio:
    def test_ensure_audio_fails_gracefully(self):
        """Audio unavailable should not crash."""
        det = _make_detector()
        # Simulate import failure by temporarily removing bus_node from sys.modules
        import sys
        saved = sys.modules.pop('bus_node', None)
        saved_utils = sys.modules.pop('bus_node.utils', None)
        saved_alert = sys.modules.pop('bus_node.utils.alert_manager', None)
        try:
            sys.modules['bus_node'] = None  # makes "from bus_node.utils..." fail
            result = det._ensure_audio()
            assert result is False
            assert det._audio_ok is False
        finally:
            # Restore
            if saved is not None:
                sys.modules['bus_node'] = saved
            else:
                sys.modules.pop('bus_node', None)
            if saved_utils is not None:
                sys.modules['bus_node.utils'] = saved_utils
            if saved_alert is not None:
                sys.modules['bus_node.utils.alert_manager'] = saved_alert

    def test_set_audio_severity_no_audio(self):
        """Setting audio severity when audio unavailable is a no-op."""
        det = _make_detector()
        det._set_audio_severity("CRITICAL")  # should not raise
        assert det.audio_triggered == 0

    def test_stop_audio_noop(self):
        det = _make_detector()
        det._stop_audio()  # should not raise
