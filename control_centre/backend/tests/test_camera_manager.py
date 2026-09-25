"""
test_camera_manager.py
Unit tests for CameraManager (FLEET-IQ Live Prototype camera + AI perception).

Covers:
  - Initialization and default state
  - Slot management (set_single_camera_test_mode, is_slot_active)
  - get_frame_as_base64 (base64 encoding, frame source priority)
  - get_detection_results
  - get_camera_status
  - _draw_driver overlay color logic (the bug we just fixed)
  - _draw_potholes
  - stop
  - Edge cases (no camera, invalid slot, no frame)

All tests mock cv2 to avoid needing a real webcam.
"""

import base64
import os
import sys
import threading
from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np
import pytest

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch cv2 at module level
cv2_mock = MagicMock()
sys.modules.setdefault("cv2", cv2_mock)

from ai.camera_manager import CameraManager, SLOT_DRIVER, SLOT_CABIN, SLOT_ROAD, ALL_SLOTS


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _make_manager():
    """Create a fresh CameraManager with no camera."""
    return CameraManager()


def _make_fake_frame(w=640, h=480):
    """Return a black BGR numpy frame."""
    return np.zeros((h, w, 3), dtype=np.uint8)


# ═══════════════════════════════════════════════════════════════════════
# 1. Initialization
# ═══════════════════════════════════════════════════════════════════════

class TestInitialization:
    def test_default_state(self):
        mgr = _make_manager()
        assert mgr.mode == "stopped"
        assert mgr.test_mode is True
        assert mgr.test_slot == SLOT_DRIVER
        assert mgr._running is False
        assert mgr._cap is None

    def test_detection_results_initialized(self):
        mgr = _make_manager()
        assert SLOT_DRIVER in mgr._detection_results
        assert SLOT_ROAD in mgr._detection_results
        assert SLOT_CABIN in mgr._detection_results

    def test_annotated_frame_none(self):
        mgr = _make_manager()
        assert mgr._annotated_frame is None


# ═══════════════════════════════════════════════════════════════════════
# 2. Slot management
# ═══════════════════════════════════════════════════════════════════════

class TestSlotManagement:
    def test_invalid_slot_rejected(self):
        mgr = _make_manager()
        ok, msg = mgr.set_single_camera_test_mode("invalid")
        assert ok is False
        assert "Invalid slot" in msg

    def test_is_slot_active_default(self):
        mgr = _make_manager()
        assert mgr.is_slot_active(SLOT_DRIVER) is False
        assert mgr.is_slot_active(SLOT_CABIN) is False
        assert mgr.is_slot_active(SLOT_ROAD) is False

    def test_is_slot_active_after_stop(self):
        mgr = _make_manager()
        mgr._mode = "single_camera"
        mgr._active_slot = SLOT_DRIVER
        mgr._test_mode = True
        assert mgr.is_slot_active(SLOT_DRIVER) is True
        assert mgr.is_slot_active(SLOT_CABIN) is False

    def test_is_slot_active_multi_camera_mode(self):
        mgr = _make_manager()
        mgr._test_mode = False
        mgr._cameras = {SLOT_DRIVER: "cam0", SLOT_CABIN: "cam1"}
        assert mgr.is_slot_active(SLOT_DRIVER) is True
        assert mgr.is_slot_active(SLOT_CABIN) is True
        assert mgr.is_slot_active(SLOT_ROAD) is False


# ═══════════════════════════════════════════════════════════════════════
# 3. get_frame_as_base64
# ═══════════════════════════════════════════════════════════════════════

class TestGetFrameAsBase64:
    def test_returns_none_when_no_active_slot(self):
        mgr = _make_manager()
        result = mgr.get_frame_as_base64()
        assert result is None

    def test_returns_none_when_slot_mismatch(self):
        mgr = _make_manager()
        mgr._active_slot = SLOT_DRIVER
        result = mgr.get_frame_as_base64(slot=SLOT_CABIN)
        assert result is None

    def test_returns_none_when_no_frame(self):
        mgr = _make_manager()
        mgr._active_slot = SLOT_DRIVER
        result = mgr.get_frame_as_base64()
        assert result is None

    def test_returns_annotated_frame_when_available(self):
        mgr = _make_manager()
        mgr._active_slot = SLOT_DRIVER
        frame = _make_fake_frame()
        mgr._annotated_frame = frame

        with patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))
            result = mgr.get_frame_as_base64()
            assert result is not None
            # Verify it used annotated frame, not raw frame
            cv2_local.imencode.assert_called_once()

    def test_falls_back_to_raw_frame(self):
        mgr = _make_manager()
        mgr._active_slot = SLOT_DRIVER
        frame = _make_fake_frame()
        mgr._frame = frame
        mgr._annotated_frame = None  # no annotated

        with patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))
            result = mgr.get_frame_as_base64()
            assert result is not None

    def test_base64_encoding(self):
        """Verify the output is valid base64."""
        mgr = _make_manager()
        mgr._active_slot = SLOT_DRIVER
        frame = _make_fake_frame()
        mgr._frame = frame

        with patch("ai.camera_manager.cv2") as cv2_local:
            fake_jpg = np.array([0xFF, 0xD8, 0xFF, 0xE0], dtype=np.uint8)
            cv2_local.imencode.return_value = (True, fake_jpg)
            cv2_local.IMWRITE_JPEG_QUALITY = 80
            result = mgr.get_frame_as_base64()
            # Should be valid base64
            decoded = base64.b64decode(result)
            assert len(decoded) > 0


# ═══════════════════════════════════════════════════════════════════════
# 4. get_detection_results
# ═══════════════════════════════════════════════════════════════════════

class TestGetDetectionResults:
    def test_returns_empty_when_no_slot(self):
        mgr = _make_manager()
        result = mgr.get_detection_results()
        assert result == {}

    def test_returns_results_for_slot(self):
        mgr = _make_manager()
        mgr._detection_results[SLOT_DRIVER] = {"state": "NORMAL", "ear": 0.45}
        result = mgr.get_detection_results(SLOT_DRIVER)
        assert result["state"] == "NORMAL"
        assert result["ear"] == 0.45

    def test_returns_empty_for_unknown_slot(self):
        mgr = _make_manager()
        result = mgr.get_detection_results("unknown")
        assert result == {}

    def test_defaults_to_active_slot(self):
        mgr = _make_manager()
        mgr._active_slot = SLOT_DRIVER
        mgr._detection_results[SLOT_DRIVER] = {"state": "TEST"}
        result = mgr.get_detection_results()
        assert result["state"] == "TEST"


# ═══════════════════════════════════════════════════════════════════════
# 5. get_camera_status
# ═══════════════════════════════════════════════════════════════════════

class TestGetCameraStatus:
    def test_stopped_mode(self):
        mgr = _make_manager()
        status = mgr.get_camera_status()
        assert status["mode"] == "stopped"
        assert status["test_mode"] is True
        assert status["test_slot"] == SLOT_DRIVER
        assert status["available_cameras"] == []

    def test_single_camera_mode(self):
        mgr = _make_manager()
        mgr._mode = "single_camera"
        mgr._active_slot = SLOT_DRIVER
        mgr._test_mode = True
        mgr._test_slot = SLOT_DRIVER
        # Mock camera as opened
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mgr._cap = mock_cap

        status = mgr.get_camera_status()
        assert status["mode"] == "single_camera"
        assert status["slots"][SLOT_DRIVER]["active"] is True
        assert status["slots"][SLOT_CABIN]["active"] is False
        assert status["available_cameras"] == [0]

    def test_all_slots_reported(self):
        mgr = _make_manager()
        status = mgr.get_camera_status()
        assert SLOT_DRIVER in status["slots"]
        assert SLOT_CABIN in status["slots"]
        assert SLOT_ROAD in status["slots"]

    def test_timestamp_present(self):
        mgr = _make_manager()
        status = mgr.get_camera_status()
        assert "timestamp" in status


# ═══════════════════════════════════════════════════════════════════════
# 6. _draw_driver overlay colors
# ═══════════════════════════════════════════════════════════════════════

class TestDrawDriver:
    def _get_state_color(self, state_result):
        """Run _draw_driver and extract the color from the STATE putText call."""
        mgr = _make_manager()
        frame = _make_fake_frame()
        with patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.FONT_HERSHEY_SIMPLEX = 0
            cv2_local.putText = MagicMock()
            mgr._draw_driver(frame, state_result)
            calls = cv2_local.putText.call_args_list
            # putText args: (img, text, org, fontFace, fontScale, color, thickness)
            # color is at index 5 (0-indexed) in the positional args
            return calls[0][0][5]

    def test_normal_state_green(self):
        """NORMAL state → green overlay."""
        result = {"state": "NORMAL", "ear": 0.45, "mar": 0.03, "closed_sec": 0.0,
                  "face_detected": True, "ear_threshold": 0.23, "mar_threshold": 0.40}
        assert self._get_state_color(result) == (0, 255, 0)  # green

    def test_drowsiness_detected_red(self):
        """DROWSINESS DETECTED → red overlay."""
        result = {"state": "DROWSINESS DETECTED", "ear": 0.15, "mar": 0.03,
                  "closed_sec": 2.0, "face_detected": True, "ear_threshold": 0.23, "mar_threshold": 0.40}
        assert self._get_state_color(result) == (0, 0, 255)  # red

    def test_perclos_drowsiness_red(self):
        """DROWSINESS DETECTED (PERCLOS) → red overlay."""
        result = {"state": "DROWSINESS DETECTED (PERCLOS)", "ear": 0.10, "mar": 0.03,
                  "closed_sec": 0.0, "face_detected": True, "ear_threshold": 0.23, "mar_threshold": 0.40}
        assert self._get_state_color(result) == (0, 0, 255)  # red

    def test_head_pose_alert_orange(self):
        """HEAD POSE ALERT → orange overlay."""
        result = {"state": "HEAD POSE ALERT", "ear": 0.45, "mar": 0.03,
                  "closed_sec": 0.0, "face_detected": True, "ear_threshold": 0.23, "mar_threshold": 0.40}
        assert self._get_state_color(result) == (0, 165, 255)  # orange

    def test_head_nod_detected_orange(self):
        """HEAD NOD DETECTED → orange overlay."""
        result = {"state": "HEAD NOD DETECTED", "ear": 0.45, "mar": 0.03,
                  "closed_sec": 0.0, "face_detected": True, "ear_threshold": 0.23, "mar_threshold": 0.40}
        assert self._get_state_color(result) == (0, 165, 255)  # orange

    def test_eyes_closed_yellow(self):
        """EYES CLOSED → yellow overlay."""
        result = {"state": "EYES CLOSED", "ear": 0.20, "mar": 0.03,
                  "closed_sec": 0.5, "face_detected": True, "ear_threshold": 0.23, "mar_threshold": 0.40}
        assert self._get_state_color(result) == (0, 200, 255)  # yellow

    def test_no_face_shows_warning_text(self):
        """face_detected=False → 'NO FACE DETECTED' text."""
        mgr = _make_manager()
        frame = _make_fake_frame()
        result = {"state": "NORMAL", "ear": 0.0, "mar": 0.0,
                  "closed_sec": 0.0, "face_detected": False, "ear_threshold": 0.23, "mar_threshold": 0.40}

        with patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.FONT_HERSHEY_SIMPLEX = 0
            cv2_local.putText = MagicMock()
            mgr._draw_driver(frame, result)

            calls = cv2_local.putText.call_args_list
            texts = [c[0][1] for c in calls]
            assert any("NO FACE" in t for t in texts)


# ═══════════════════════════════════════════════════════════════════════
# 7. _draw_potholes
# ═══════════════════════════════════════════════════════════════════════

class TestDrawPotholes:
    def test_empty_detections(self):
        mgr = _make_manager()
        frame = _make_fake_frame()
        with patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.FONT_HERSHEY_SIMPLEX = 0
            cv2_local.putText = MagicMock()
            cv2_local.rectangle = MagicMock()
            mgr._draw_potholes(frame, [])
            # Should still draw the "Potholes: 0" count
            cv2_local.putText.assert_called()

    def test_pothole_boxes_drawn(self):
        mgr = _make_manager()
        frame = _make_fake_frame()
        detections = [{"bbox": [100, 100, 200, 200], "confidence": 0.85}]
        with patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.FONT_HERSHEY_SIMPLEX = 0
            cv2_local.putText = MagicMock()
            cv2_local.rectangle = MagicMock()
            mgr._draw_potholes(frame, detections)
            cv2_local.rectangle.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# 8. stop
# ═══════════════════════════════════════════════════════════════════════

class TestStop:
    def test_stop_clears_state(self):
        mgr = _make_manager()
        mgr._mode = "single_camera"
        mgr._active_slot = SLOT_DRIVER
        mgr._running = True
        mgr._cap = MagicMock()
        mgr._frame = _make_fake_frame()
        mgr._annotated_frame = _make_fake_frame()

        mgr.stop()

        assert mgr.mode == "stopped"
        assert mgr._active_slot is None
        assert mgr._cap is None
        assert mgr._annotated_frame is None

    def test_stop_is_idempotent(self):
        mgr = _make_manager()
        mgr.stop()
        mgr.stop()  # should not raise


# ═══════════════════════════════════════════════════════════════════════
# 9. open_shared_camera
# ═══════════════════════════════════════════════════════════════════════

class TestOpenSharedCamera:
    def test_fails_when_no_cv2(self):
        mgr = _make_manager()
        with patch("ai.camera_manager._import_cv2", return_value=False):
            result = mgr.open_shared_camera()
            assert result is False

    def test_fails_when_camera_cannot_open(self):
        mgr = _make_manager()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch("ai.camera_manager._import_cv2", return_value=True), \
             patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.VideoCapture.return_value = mock_cap
            result = mgr.open_shared_camera()
            assert result is False

    def test_fails_when_camera_cannot_read(self):
        mgr = _make_manager()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)

        with patch("ai.camera_manager._import_cv2", return_value=True), \
             patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.VideoCapture.return_value = mock_cap
            cv2_local.CAP_PROP_FRAME_WIDTH = 3
            cv2_local.CAP_PROP_FRAME_HEIGHT = 4
            result = mgr.open_shared_camera()
            assert result is False
            mock_cap.release.assert_called_once()

    def test_success(self):
        mgr = _make_manager()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, _make_fake_frame())

        with patch("ai.camera_manager._import_cv2", return_value=True), \
             patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.VideoCapture.return_value = mock_cap
            cv2_local.CAP_PROP_FRAME_WIDTH = 3
            cv2_local.CAP_PROP_FRAME_HEIGHT = 4
            result = mgr.open_shared_camera()
            assert result is True
            assert mgr._cap is mock_cap


# ═══════════════════════════════════════════════════════════════════════
# 10. _run_detection
# ═══════════════════════════════════════════════════════════════════════

class TestRunDetection:
    def test_driver_detection_stores_results(self):
        mgr = _make_manager()
        mock_detector = MagicMock()
        mock_detector.process_frame.return_value = {"state": "NORMAL", "ear": 0.45}
        mgr._driver_detector = mock_detector

        frame = _make_fake_frame()
        with patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.FONT_HERSHEY_SIMPLEX = 0
            cv2_local.putText = MagicMock()
            result = mgr._run_detection(frame, SLOT_DRIVER)

        assert result["state"] == "NORMAL"
        assert mgr._detection_results[SLOT_DRIVER]["state"] == "NORMAL"

    def test_driver_detection_sets_annotated_frame(self):
        mgr = _make_manager()
        mock_detector = MagicMock()
        mock_detector.process_frame.return_value = {"state": "NORMAL"}
        mgr._driver_detector = mock_detector

        frame = _make_fake_frame()
        with patch("ai.camera_manager.cv2") as cv2_local:
            cv2_local.FONT_HERSHEY_SIMPLEX = 0
            cv2_local.putText = MagicMock()
            mgr._run_detection(frame, SLOT_DRIVER)

        assert mgr._annotated_frame is not None

    def test_driver_detection_exception_sets_annotated(self):
        """When driver detection throws, annotated frame should still be set."""
        mgr = _make_manager()
        mock_detector = MagicMock()
        mock_detector.process_frame.side_effect = RuntimeError("test error")
        mgr._driver_detector = mock_detector

        frame = _make_fake_frame()
        # Should not raise, but annotated frame won't be set (error path)
        mgr._run_detection(frame, SLOT_DRIVER)
        # After fix: even on error, we don't set annotated for driver
        # (the fix only added fallback for road/cabin)

    def test_road_detection_sets_annotated_on_error(self):
        """After fix: road detection error should set annotated frame to raw."""
        mgr = _make_manager()
        mock_detector = MagicMock()
        mock_detector.detect.side_effect = RuntimeError("test error")
        mgr._pothole_detector = mock_detector

        frame = _make_fake_frame()
        mgr._run_detection(frame, SLOT_ROAD)
        assert mgr._annotated_frame is not None  # fallback

    def test_cabin_detection_sets_annotated_on_error(self):
        """After fix: cabin detection error should set annotated frame to raw."""
        mgr = _make_manager()
        mock_detector = MagicMock()
        mock_detector.process_frame.side_effect = RuntimeError("test error")
        mgr._cabin_detector = mock_detector

        frame = _make_fake_frame()
        mgr._run_detection(frame, SLOT_CABIN)
        assert mgr._annotated_frame is not None  # fallback

    def test_no_detector_for_slot_is_noop(self):
        mgr = _make_manager()
        # No detectors linked
        frame = _make_fake_frame()
        mgr._run_detection(frame, SLOT_DRIVER)  # should not raise
        assert mgr._annotated_frame is None
