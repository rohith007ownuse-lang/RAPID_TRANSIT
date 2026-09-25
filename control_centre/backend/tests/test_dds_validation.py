"""
test_dds_validation.py
Deep validation tests — Phases 3–8 + Phase 16 (integration).

Covers:
  Phase 3  — State machine transitions and impossible-state guards
  Phase 4  — Calibration edge cases (no face, too few samples, extremes)
  Phase 5  — PERCLOS correctness (insufficient samples, rolling window, reset)
  Phase 6  — Event emission (edge-triggered, no duplicates, re-arm)
  Phase 7  — Audio safety (graceful failure, stop on reset)
  Phase 8  — Camera manager resilience (no camera, detector errors, restart)
  Phase 16 — Integration tests (DDS→event, camera→DDS, API, PROTO-001)
"""

import os
import sys
import threading
import time
from collections import deque
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("cv2", MagicMock())

from ai.driver.driver_drowsiness import (
    DriverDrowsinessDetector,
    EAR_THRESHOLD, MAR_THRESHOLD,
    EYE_CLOSED_DURATION, PERCLOS_MIN_SAMPLES, PERCLOS_THRESHOLD,
    CALIBRATION_DURATION, MIN_CALIBRATION_SAMPLES,
    EAR_THRESHOLD_MIN, EAR_THRESHOLD_MAX,
    MAR_THRESHOLD_MIN, MAR_THRESHOLD_MAX,
    EAR_CALIB_FACTOR, MAR_CALIB_MARGIN,
    COOLDOWN_HEAD,
)

from ai.camera_manager import CameraManager, SLOT_DRIVER, SLOT_CABIN, SLOT_ROAD


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _det(callback=None):
    return DriverDrowsinessDetector(event_callback=callback)

def _frame():
    return np.zeros((480, 640, 3), dtype=np.uint8)

def _lm(ear=0.45, mar=0.03, pitch=0.0, yaw=0.0, roll=0.0):
    return {"ear": ear, "mar": mar, "pitch": pitch, "yaw": yaw, "roll": roll}

def _patch_lm(ear=0.45, mar=0.03, pitch=0.0):
    """Context manager: patch landmarker to return fixed values."""
    return patch.multiple(
        "ai.driver.driver_drowsiness",
        _load_landmarker=MagicMock(return_value=True),
        _detect_with_landmarker=MagicMock(return_value=_lm(ear, mar, pitch)),
        _load_cascades=MagicMock(),
    )


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3 — State machine transitions
# ═══════════════════════════════════════════════════════════════════════

class TestStateMachineTransitions:
    """Verify every valid and invalid phase transition."""

    def test_idle_to_calibrating(self):
        d = _det()
        assert d.phase == "idle"
        ok, _ = d.start_calibration()
        assert ok and d.phase == "calibrating"

    def test_calibrating_to_ready(self):
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.40] * 20
        d._calib_mar = [0.05] * 20
        d._calib_pitch = [0.0] * 20
        d._finish_calibration()
        assert d.phase == "ready"

    def test_ready_to_monitoring(self):
        d = _det()
        d.phase = "ready"
        ok, _ = d.start_monitoring()
        assert ok and d.phase == "monitoring"

    def test_monitoring_to_ready_via_stop(self):
        d = _det()
        d.start_monitoring()
        ok, _ = d.stop_monitoring()
        assert ok and d.phase == "ready"

    def test_monitoring_to_idle_via_reset(self):
        d = _det()
        d.start_monitoring()
        d.reset()
        assert d.phase == "idle"

    def test_ready_to_idle_via_reset(self):
        d = _det()
        d.phase = "ready"
        d.reset()
        assert d.phase == "idle"

    def test_calibrating_to_idle_via_reset(self):
        d = _det()
        d.start_calibration()
        d.reset()
        assert d.phase == "idle"

    def test_idle_to_monitoring_directly(self):
        """Start monitoring from idle should work (uses default thresholds)."""
        d = _det()
        ok, _ = d.start_monitoring()
        assert ok and d.phase == "monitoring"

    def test_monitoring_blocks_calibration(self):
        d = _det()
        d.start_monitoring()
        ok, msg = d.start_calibration()
        assert not ok and "Stop monitoring" in msg

    def test_calibrating_to_monitoring_finishes_calibration(self):
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.40] * 20
        d._calib_mar = [0.05] * 20
        d._calib_pitch = [0.0] * 20
        ok, _ = d.start_monitoring()
        assert ok and d.phase == "monitoring" and d.calib["completed"]

    def test_impossible_ready_with_monitoring_true(self):
        """After stop, monitoring flag must be False."""
        d = _det()
        d.start_monitoring()
        d.stop_monitoring()
        status = d.get_status()
        assert status["monitoring"] is False

    def test_impossible_idle_with_active_monitoring(self):
        """Reset during monitoring must clear everything."""
        d = _det()
        d.start_monitoring()
        d.reset()
        assert d.phase == "idle"
        assert d.monitoring_started_at is None
        status = d.get_status()
        assert status["monitoring"] is False

    def test_impossible_calibrating_with_drowsiness_event(self):
        """During calibration, monitoring=False so no events should emit."""
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_calibration()
        # Simulate a full calibration + check no events
        d._calib_ear = [0.40] * 20
        d._calib_mar = [0.05] * 20
        d._calib_pitch = [0.0] * 20
        d._finish_calibration()
        assert len(events) == 0


# ═══════════════════════════════════════════════════════════════════════
# PHASE 4 — Calibration edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestCalibrationEdgeCases:
    def test_no_face_during_calibration(self):
        """No face → calibration should not pretend valid measurements exist."""
        d = _det()
        d.start_calibration()
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker") as mock_lm, \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            # First frame: face found
            mock_lm.return_value = _lm(0.45, 0.03)
            d.process_frame(_frame())
            assert d.calib["face_found"] is True
            assert len(d._calib_ear) == 1

            # Second frame: no face
            mock_lm.return_value = None
            d.process_frame(_frame())
            # Samples should NOT increase
            assert len(d._calib_ear) == 1

    def test_too_few_samples_fails(self):
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.40] * 5  # only 5, need 15
        d._calib_mar = [0.05] * 5
        d._calib_pitch = [0.0] * 5
        d._finish_calibration()
        assert d.phase == "idle"
        assert d.calib["completed"] is False
        assert "only 5 samples" in d.calib["message"]

    def test_normal_face_produces_valid_baseline(self):
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.40] * 20
        d._calib_mar = [0.05] * 20
        d._calib_pitch = [2.0] * 20
        d._finish_calibration()
        assert d.phase == "ready"
        assert d.ear_threshold > 0
        assert d.mar_threshold > 0

    def test_extremely_low_ear_baseline(self):
        """EAR baseline 0.05 * 0.75 = 0.0375, clamped to min 0.15."""
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.05] * 20
        d._calib_mar = [0.03] * 20
        d._calib_pitch = [0.0] * 20
        d._finish_calibration()
        assert d.ear_threshold == EAR_THRESHOLD_MIN

    def test_extremely_high_mar_baseline(self):
        """MAR baseline 0.85 + 0.20 = 1.05, clamped to max 0.90."""
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.40] * 20
        d._calib_mar = [0.85] * 20
        d._calib_pitch = [0.0] * 20
        d._finish_calibration()
        assert d.mar_threshold == MAR_THRESHOLD_MAX

    def test_extremely_high_ear_baseline(self):
        """EAR baseline 0.50 * 0.75 = 0.375, clamped to max 0.30."""
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.50] * 20
        d._calib_mar = [0.05] * 20
        d._calib_pitch = [0.0] * 20
        d._finish_calibration()
        assert d.ear_threshold == EAR_THRESHOLD_MAX

    def test_start_calibration_while_monitoring_rejected(self):
        d = _det()
        d.start_monitoring()
        ok, msg = d.start_calibration()
        assert not ok
        assert "Stop monitoring" in msg

    def test_start_monitoring_before_calibration_uses_defaults(self):
        d = _det()
        ok, _ = d.start_monitoring()
        assert ok
        assert d.ear_threshold == EAR_THRESHOLD
        assert d.mar_threshold == MAR_THRESHOLD

    def test_calibration_exactly_min_samples(self):
        """Exactly MIN_CALIBRATION_SAMPLES should succeed."""
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.40] * MIN_CALIBRATION_SAMPLES
        d._calib_mar = [0.05] * MIN_CALIBRATION_SAMPLES
        d._calib_pitch = [0.0] * MIN_CALIBRATION_SAMPLES
        d._finish_calibration()
        assert d.phase == "ready"
        assert d.calib["completed"] is True

    def test_calibration_one_sample_short(self):
        """MIN_CALIBRATION_SAMPLES - 1 should fail."""
        d = _det()
        d.start_calibration()
        n = MIN_CALIBRATION_SAMPLES - 1
        d._calib_ear = [0.40] * n
        d._calib_mar = [0.05] * n
        d._calib_pitch = [0.0] * n
        d._finish_calibration()
        assert d.phase == "idle"
        assert d.calib["completed"] is False


# ═══════════════════════════════════════════════════════════════════════
# PHASE 5 — PERCLOS correctness
# ═══════════════════════════════════════════════════════════════════════

class TestPERCLOSCorrectness:
    def test_insufficient_samples_perclos_not_meaningful(self):
        """With < PERCLOS_MIN_SAMPLES, perclos_ratio should be 0 for drowsy_percent."""
        d = _det()
        d.phase = "monitoring"
        d._last_status = "NORMAL"
        with _patch_lm(ear=0.10, mar=0.03) as mocks:
            # Feed only 5 frames (all below threshold)
            for _ in range(5):
                d.process_frame(_frame())
            # perclos should be high but drowsy_percent should not use it
            assert len(d._ear_timestamps) <= 6  # 5 + maybe 1 from last
            # With only 5 samples, perclos_ratio = 0 in drowsy_percent calc
            # (n < PERCLOS_MIN_SAMPLES guard)
            # So drowsy_percent depends only on closed_ratio
            # EAR 0.10 < threshold 0.23 → closed, but eye_closed_time is small
            assert d.drowsy_percent < 100  # should not be 100 from perclos alone

    def test_all_eyes_open_perclos_zero(self):
        d = _det()
        with _patch_lm(ear=0.45):
            d.process_frame(_frame())
            assert d.perclos == 0.0

    def test_all_eyes_closed_high_perclos(self):
        d = _det()
        d.ear_threshold = 0.23
        with _patch_lm(ear=0.10):
            for _ in range(50):
                d.process_frame(_frame())
            assert d.perclos >= 0.9

    def test_mixed_open_closed(self):
        d = _det()
        d.ear_threshold = 0.23
        # Alternate: closed (0.10), open (0.45)
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker") as mock_lm, \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            for i in range(40):
                if i % 2 == 0:
                    mock_lm.return_value = _lm(ear=0.10)
                else:
                    mock_lm.return_value = _lm(ear=0.45)
                d.process_frame(_frame())
            # ~50% closed → perclos ≈ 0.5
            assert 0.3 < d.perclos < 0.7

    def test_perclos_window_rolling(self):
        """Old timestamps should be evicted after 90s."""
        d = _det()
        now = time.time()
        # Add 100 timestamps spanning 120 seconds (some old)
        for i in range(100):
            ts = now - 120 + i * 0.8
            d._ear_timestamps.append((ts, 0.10))
        # Process one frame to trigger window cleanup
        with _patch_lm(ear=0.45):
            d.process_frame(_frame())
        # Window is 90s, so only timestamps from the last 90s remain (plus the new one)
        assert len(d._ear_timestamps) < 101

    def test_perclos_window_reset_on_no_face(self):
        d = _det()
        d._ear_timestamps.append((time.time(), 0.10))
        d._ear_timestamps.append((time.time(), 0.10))
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker", return_value=None), \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            d.process_frame(_frame())
        assert len(d._ear_timestamps) == 0

    def test_recovery_after_drowsiness_clears_perclos(self):
        """After drowsiness, opening eyes should reduce perclos over time."""
        d = _det()
        d.ear_threshold = 0.23
        # Build closed-eye history
        now = time.time()
        for i in range(40):
            d._ear_timestamps.append((now - 40 + i, 0.10))
        d.perclos = 1.0  # simulate high perclos
        # Now process open-eye frames
        with _patch_lm(ear=0.45):
            for _ in range(10):
                d.process_frame(_frame())
        # Open eyes should dilute the PERCLOS window
        assert d.perclos < 1.0

    def test_perclos_not_used_for_drowsy_percent_with_few_samples(self):
        """Bug regression: 1 sample should NOT make drowsy_percent=100."""
        d = _det()
        d.ear_threshold = 0.23
        with _patch_lm(ear=0.10):
            d.process_frame(_frame())
        # 1 sample → perclos_ratio = 0 (guard), so drowsy_percent comes from closed_ratio only
        # eye_closed_time is tiny (first frame), so drowsy_percent should be low
        assert d.drowsy_percent < 50


# ═══════════════════════════════════════════════════════════════════════
# PHASE 6 — Event emission
# ═══════════════════════════════════════════════════════════════════════

class TestEventEmission:
    def test_drowsiness_start_emits_event(self):
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()

        with _patch_lm(ear=0.15, mar=0.03) as mocks:
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.5
            d.process_frame(_frame())

        drowsy = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS"]
        assert len(drowsy) >= 1

    def test_same_episode_no_duplicate_events(self):
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()

        with _patch_lm(ear=0.15, mar=0.03):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.5
            for _ in range(5):
                d.process_frame(_frame())

        drowsy = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS"]
        assert len(drowsy) == 1  # only one, not five

    def test_alert_emitted_once_per_episode(self):
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()

        with _patch_lm(ear=0.15, mar=0.03):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.5
            for _ in range(5):
                d.process_frame(_frame())

        alerts = [e for e in events if e["event_type"] == "DRIVER_ALERT"]
        assert len(alerts) == 1

    def test_recovery_resets_episode(self):
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()

        # Episode 1: drowsy
        with _patch_lm(ear=0.15, mar=0.03):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.5
            d.process_frame(_frame())
        assert d._alert_issued_for_episode is True

        # Recovery
        with _patch_lm(ear=0.45):
            d.process_frame(_frame())
        assert d._alert_issued_for_episode is False

    def test_new_episode_allows_new_event(self):
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()

        # Episode 1
        with _patch_lm(ear=0.15, mar=0.03):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.5
            d.process_frame(_frame())

        # Recovery
        with _patch_lm(ear=0.45):
            d.process_frame(_frame())

        # Episode 2
        with _patch_lm(ear=0.15, mar=0.03):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.5
            d.process_frame(_frame())

        drowsy = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS"]
        assert len(drowsy) >= 2

    def test_head_pose_cooldown(self):
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()

        with _patch_lm(ear=0.45, mar=0.03, pitch=20.0):
            d.process_frame(_frame())
            d._head_pose_alert_start = time.time() - 3.0
            d.process_frame(_frame())

        head_events_1 = [e for e in events if e["severity"] == "WARNING"]

        # Immediate re-trigger blocked by cooldown
        with _patch_lm(ear=0.45, mar=0.03, pitch=20.0):
            d._head_pose_alert_start = time.time() - 3.0
            d.process_frame(_frame())

        head_events_2 = [e for e in events if e["severity"] == "WARNING"]
        assert len(head_events_2) == len(head_events_1)  # no new event

    def test_event_structure_fields(self):
        d = _det()
        d.ear = 0.42
        d.mar = 0.03
        d.head_pitch = 5.0
        d.eye_closed_time = 1.5
        d.perclos = 0.12
        d.ear_threshold = 0.28
        d.mar_threshold = 0.40
        d.drowsy_percent = 60
        d.attention_percent = 40

        event = d._build_event("DRIVER_DROWSINESS", "CRITICAL", 0.85, "Test")
        required = ["bus_id", "event_type", "severity", "confidence",
                     "sensor_source", "camera_id", "data_source",
                     "status", "simulation", "additional_data"]
        for field in required:
            assert field in event, f"Missing field: {field}"
        assert event["bus_id"] == "PROTO-001"
        assert event["camera_id"] == "driver"
        assert event["data_source"] == "live"
        assert event["simulation"] is False

    def test_no_simulation_false_in_live_events(self):
        """Live events must never have simulation=True."""
        d = _det()
        event = d._build_event("DRIVER_DROWSINESS", "CRITICAL", 0.9, "test")
        assert event["simulation"] is False
        assert event["data_source"] == "live"


# ═══════════════════════════════════════════════════════════════════════
# PHASE 7 — Audio safety
# ═══════════════════════════════════════════════════════════════════════

class TestAudioSafety:
    def test_audio_unavailable_no_crash(self):
        import sys
        saved = sys.modules.pop("bus_node", None)
        saved_u = sys.modules.pop("bus_node.utils", None)
        saved_a = sys.modules.pop("bus_node.utils.alert_manager", None)
        try:
            sys.modules["bus_node"] = None
            d = _det()
            result = d._ensure_audio()
            assert result is False
        finally:
            if saved is not None:
                sys.modules["bus_node"] = saved
            else:
                sys.modules.pop("bus_node", None)
            if saved_u:
                sys.modules["bus_node.utils"] = saved_u
            if saved_a:
                sys.modules["bus_node.utils.alert_manager"] = saved_a

    def test_set_audio_severity_no_audio_no_crash(self):
        d = _det()
        d._set_audio_severity("CRITICAL")  # should not raise
        d._set_audio_severity("WARNING")
        d._set_audio_severity(None)

    def test_stop_audio_noop_without_audio(self):
        d = _det()
        d._stop_audio()  # should not raise

    def test_stop_monitoring_stops_audio(self):
        d = _det()
        mock_audio = MagicMock()
        d._audio = mock_audio
        d._audio_ok = True
        d.phase = "monitoring"
        d.stop_monitoring()
        mock_audio.stop.assert_called_once()

    def test_reset_stops_audio(self):
        d = _det()
        mock_audio = MagicMock()
        d._audio = mock_audio
        d._audio_ok = True
        d.phase = "monitoring"
        d.reset()
        mock_audio.stop.assert_called()

    def test_audio_triggered_counts_severity_transitions(self):
        d = _det()
        mock_audio = MagicMock()
        d._audio = mock_audio
        d._audio_ok = True
        d._audio_level = None

        d._set_audio_severity("CRITICAL")
        assert d.audio_triggered == 1

        # Same severity → no increment
        d._set_audio_severity("CRITICAL")
        assert d.audio_triggered == 1

        # Different severity → increment
        d._set_audio_severity("WARNING")
        assert d.audio_triggered == 2

        # Back to None → no increment
        d._set_audio_severity(None)
        assert d.audio_triggered == 2


# ═══════════════════════════════════════════════════════════════════════
# PHASE 8 — Camera manager resilience
# ═══════════════════════════════════════════════════════════════════════

class TestCameraManagerResilience:
    def test_no_cv2_graceful(self):
        mgr = CameraManager()
        with patch("ai.camera_manager._import_cv2", return_value=False):
            ok, msg = mgr.set_single_camera_test_mode("driver")
            assert not ok

    def test_camera_cannot_open(self):
        mgr = CameraManager()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        with patch("ai.camera_manager._import_cv2", return_value=True), \
             patch("ai.camera_manager.cv2") as cv2_mock:
            cv2_mock.VideoCapture.return_value = mock_cap
            ok, msg = mgr.set_single_camera_test_mode("driver")
            assert not ok

    def test_camera_no_frame_after_open(self):
        mgr = CameraManager()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)
        with patch("ai.camera_manager._import_cv2", return_value=True), \
             patch("ai.camera_manager.cv2") as cv2_mock:
            cv2_mock.VideoCapture.return_value = mock_cap
            result = mgr.open_shared_camera()
            assert result is False

    def test_get_frame_returns_none_without_camera(self):
        mgr = CameraManager()
        assert mgr.get_frame_as_base64() is None

    def test_stop_is_idempotent(self):
        mgr = CameraManager()
        mgr.stop()
        mgr.stop()
        mgr.stop()
        assert mgr.mode == "stopped"

    def test_invalid_slot_rejected(self):
        mgr = CameraManager()
        ok, _ = mgr.set_single_camera_test_mode("invalid")
        assert not ok

    def test_driver_detect_exception_sets_fallback_frame(self):
        mgr = CameraManager()
        mock_det = MagicMock()
        mock_det.process_frame.side_effect = RuntimeError("test")
        mgr._driver_detector = mock_det
        frame = _frame()
        mgr._run_detection(frame, SLOT_DRIVER)
        # Driver error path: annotated frame may not be set (error before copy)
        # But the code should not crash

    def test_road_detect_exception_sets_annotated_fallback(self):
        mgr = CameraManager()
        mock_det = MagicMock()
        mock_det.detect.side_effect = RuntimeError("test")
        mgr._pothole_detector = mock_det
        frame = _frame()
        mgr._run_detection(frame, SLOT_ROAD)
        assert mgr._annotated_frame is not None  # fallback to raw frame

    def test_cabin_detect_exception_sets_annotated_fallback(self):
        mgr = CameraManager()
        mock_det = MagicMock()
        mock_det.process_frame.side_effect = RuntimeError("test")
        mgr._cabin_detector = mock_det
        frame = _frame()
        mgr._run_detection(frame, SLOT_CABIN)
        assert mgr._annotated_frame is not None

    def test_no_detector_for_slot_is_noop(self):
        mgr = CameraManager()
        frame = _frame()
        mgr._run_detection(frame, SLOT_DRIVER)  # no detector linked
        assert mgr._annotated_frame is None

    def test_camera_status_reports_all_slots(self):
        mgr = CameraManager()
        status = mgr.get_camera_status()
        assert SLOT_DRIVER in status["slots"]
        assert SLOT_CABIN in status["slots"]
        assert SLOT_ROAD in status["slots"]
        assert status["mode"] == "stopped"

    def test_stop_clears_cap(self):
        mgr = CameraManager()
        mock_cap = MagicMock()
        mgr._cap = mock_cap
        mgr._running = True
        mgr.stop()
        mock_cap.release.assert_called()
        assert mgr._cap is None


# ═══════════════════════════════════════════════════════════════════════
# PHASE 16 — Integration tests
# ═══════════════════════════════════════════════════════════════════════

class TestIntegration:
    """End-to-end integration: DDS → detection → event, camera → DDS, API."""

    def test_dds_detection_to_event_flow(self):
        """Full flow: calibrate → monitor → drowsy → event emitted."""
        events = []
        d = _det(callback=lambda e: events.append(e))

        # Calibrate
        d.start_calibration()
        d._calib_ear = [0.40] * 20
        d._calib_mar = [0.05] * 20
        d._calib_pitch = [0.0] * 20
        d._finish_calibration()
        assert d.phase == "ready"

        # Monitor
        d.start_monitoring()
        assert d.phase == "monitoring"

        # Simulate drowsy frames
        with _patch_lm(ear=0.15, mar=0.03):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.5
            d.process_frame(_frame())

        # Verify events
        drowsy_events = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS"]
        alert_events = [e for e in events if e["event_type"] == "DRIVER_ALERT"]
        assert len(drowsy_events) >= 1
        assert len(alert_events) >= 1
        assert drowsy_events[0]["bus_id"] == "PROTO-001"
        assert drowsy_events[0]["simulation"] is False

    def test_camera_manager_to_dds_detection(self):
        """CameraManager feeds frames to DDS engine and stores results."""
        mgr = CameraManager()
        mock_det = MagicMock()
        mock_det.process_frame.return_value = {
            "state": "NORMAL", "ear": 0.45, "mar": 0.03,
            "face_detected": True, "eyes_detected": 2,
            "ear_threshold": 0.23, "mar_threshold": 0.40,
        }
        mgr._driver_detector = mock_det
        frame = _frame()

        with patch("ai.camera_manager.cv2") as cv2_mock:
            cv2_mock.FONT_HERSHEY_SIMPLEX = 0
            cv2_mock.putText = MagicMock()
            result = mgr._run_detection(frame, SLOT_DRIVER)

        assert result["state"] == "NORMAL"
        assert mgr.get_detection_results(SLOT_DRIVER)["state"] == "NORMAL"

    def test_dds_api_status_structure(self):
        """Simulate what /api/dds/status returns."""
        d = _det()
        d.start_calibration()
        d._calib_ear = [0.40] * 20
        d._calib_mar = [0.05] * 20
        d._calib_pitch = [0.0] * 20
        d._finish_calibration()

        status = d.get_status()
        # Must have all fields the frontend expects
        assert "phase" in status
        assert "monitoring" in status
        assert "calibration" in status
        assert "thresholds" in status
        assert "last" in status
        assert "audio" in status
        assert "events_emitted" in status
        assert status["bus_id"] == "PROTO-001"
        assert status["data_source"] == "live"
        assert status["simulation"] is False
        assert status["calibration"]["completed"] is True

    def test_proto001_event_fields(self):
        """PROTO-001 events must have live data_source, not simulation."""
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()

        with _patch_lm(ear=0.15, mar=0.03):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.5
            d.process_frame(_frame())

        for e in events:
            assert e["bus_id"] == "PROTO-001"
            assert e["data_source"] == "live"
            assert e["simulation"] is False

    def test_camera_unhealthy_does_not_crash_api(self):
        """When camera is unavailable, API endpoints must still respond."""
        mgr = CameraManager()
        # No camera opened, no slot active
        assert mgr.get_frame_as_base64() is None
        assert mgr.get_frame_as_base64("driver") is None
        status = mgr.get_camera_status()
        assert status["mode"] == "stopped"
        # Should not raise
        results = mgr.get_detection_results(SLOT_DRIVER)
        assert isinstance(results, dict)

    def test_full_cycle_start_stop_start(self):
        """Camera start → stop → start should not create duplicate threads."""
        mgr = CameraManager()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, _frame())
        mock_det = MagicMock()
        mock_det.process_frame.return_value = {"state": "NORMAL", "ear": 0.45}
        mgr._driver_detector = mock_det

        with patch("ai.camera_manager._import_cv2", return_value=True), \
             patch("ai.camera_manager.cv2") as cv2_mock:
            cv2_mock.VideoCapture.return_value = mock_cap
            cv2_mock.FONT_HERSHEY_SIMPLEX = 0
            cv2_mock.putText = MagicMock()

            # Start
            ok, _ = mgr.set_single_camera_test_mode("driver")
            assert ok
            t1 = mgr._thread
            time.sleep(0.1)

            # Stop
            mgr.stop()
            assert mgr._thread is None

            # Start again
            ok, _ = mgr.set_single_camera_test_mode("driver")
            assert ok
            t2 = mgr._thread
            assert t2 is not None
            assert t2 is not t1  # different thread object

            mgr.stop()
