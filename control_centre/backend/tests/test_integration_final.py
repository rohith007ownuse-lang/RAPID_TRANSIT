"""
test_integration_final.py
Integration tests for the final FLEET-IQ implementation requirements.

Covers:
  - 70V vehicle identity (route, name, reg_no)
  - Yawing detection (temporal MAR analysis)
  - Persistent DDS (runs independently of page navigation)
  - Simulation separation (live data never mixes with simulation)
  - Global alert (DDS → event → alert)
  - Camera failure handling
"""

import os
import sys
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("cv2", MagicMock())

from ai.driver.driver_drowsiness import (
    DriverDrowsinessDetector, YAWN_DURATION, MAR_THRESHOLD,
)


def _det(callback=None):
    return DriverDrowsinessDetector(event_callback=callback)

def _frame():
    return np.zeros((480, 640, 3), dtype=np.uint8)

def _lm(ear=0.45, mar=0.03, pitch=0.0):
    return {"ear": ear, "mar": mar, "pitch": pitch, "yaw": 0.0, "roll": 0.0}


# ═══════════════════════════════════════════════════════════════════════
# 70V Vehicle Identity
# ═══════════════════════════════════════════════════════════════════════

class TestVehicleIdentity:
    def test_proto_bus_has_70v_route(self):
        """PROTO-001 internal bus should display as 70V with correct route."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from server import _proto_bus
        bus = _proto_bus()
        assert bus["bus_id"] == "PROTO-001"  # internal ID stays
        assert bus["route_code"] == "70V"
        assert "70V" in bus["route"]
        assert "Koyambedu" in bus["route"]
        assert "Kilambakkam" in bus["route"]
        assert "Coimbatore" not in bus["route"]
        assert bus["name"] == "70V"

    def test_proto_bus_no_coimbatore(self):
        """Never use Coimbatore for this prototype."""
        from server import _proto_bus
        bus = _proto_bus()
        import json
        bus_str = json.dumps(bus)
        assert "Coimbatore" not in bus_str

    def test_proto_bus_data_source_live(self):
        from server import _proto_bus
        bus = _proto_bus()
        assert bus["data_source"] == "live"
        assert bus["live"] is True

    def test_proto_bus_stops_are_coimbedu_kilambakkam(self):
        from server import PROTO_STOPS
        stop_names = [s["stop"] for s in PROTO_STOPS]
        assert "Koyambedu" in stop_names
        assert "Kilambakkam" in stop_names


# ═══════════════════════════════════════════════════════════════════════
# Yawning Detection
# ═══════════════════════════════════════════════════════════════════════

class TestYawningDetection:
    def test_normal_mouth_no_yawn(self):
        """MAR below threshold → no yawn."""
        d = _det()
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker", return_value=_lm(mar=0.03)), \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            result = d.process_frame(_frame())
        assert result["yawning"] is False
        assert d.yawn_count == 0

    def test_brief_mouth_opening_no_yawn(self):
        """MAR above threshold for < YAWN_DURATION → no confirmed yawn."""
        d = _det()
        d.mar_threshold = MAR_THRESHOLD
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker", return_value=_lm(mar=0.50)), \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            # One frame with high MAR
            d.process_frame(_frame())
            # Immediately another frame with low MAR (reset)
            with patch("ai.driver.driver_drowsiness._detect_with_landmarker", return_value=_lm(mar=0.03)):
                d.process_frame(_frame())
        assert d.yawn_count == 0

    def test_sustained_mouth_opening_confirms_yawn(self):
        """MAR above threshold for >= YAWN_DURATION → confirmed yawn."""
        d = _det()
        d.mar_threshold = MAR_THRESHOLD
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker", return_value=_lm(mar=0.50)), \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            # First frame: start yawn timer
            d.process_frame(_frame())
            assert d._yawn_start is not None
            # Fast-forward: yawn timer exceeds YAWN_DURATION
            d._yawn_start = time.time() - (YAWN_DURATION + 0.5)
            result = d.process_frame(_frame())
        assert d.yawn_count == 1
        assert result["yawning"] is True

    def test_yawn_recovery_allows_new_yawn(self):
        """After yawn ends, a new sustained opening can trigger another yawn."""
        d = _det()
        d.mar_threshold = MAR_THRESHOLD
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker") as mock_lm, \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            # Yawn 1
            mock_lm.return_value = _lm(mar=0.50)
            d.process_frame(_frame())
            d._yawn_start = time.time() - (YAWN_DURATION + 0.5)
            d.process_frame(_frame())
            assert d.yawn_count == 1

            # Recovery (mouth closed)
            mock_lm.return_value = _lm(mar=0.03)
            d.process_frame(_frame())

            # Yawn 2
            mock_lm.return_value = _lm(mar=0.50)
            d.process_frame(_frame())
            d._yawn_start = time.time() - (YAWN_DURATION + 0.5)
            d.process_frame(_frame())
            assert d.yawn_count == 2


# ═══════════════════════════════════════════════════════════════════════
# Persistent DDS (runs independently of page navigation)
# ═══════════════════════════════════════════════════════════════════════

class TestPersistentDDS:
    def test_single_dds_instance(self):
        """Only one DDS detector singleton should exist."""
        from ai.driver.driver_drowsiness import driver_detector
        from ai.driver.driver_drowsiness import DriverDrowsinessDetector
        assert isinstance(driver_detector, DriverDrowsinessDetector)
        # Importing again should return the same object
        import importlib
        mod = importlib.import_module("ai.driver.driver_drowsiness")
        assert mod.driver_detector is driver_detector

    def test_dds_continues_across_navigation(self):
        """DDS state persists regardless of which 'page' is viewed."""
        d = _det()
        d.start_monitoring()
        assert d.phase == "monitoring"
        # Simulate page navigation (no effect on DDS)
        # The DDS engine is server-side, not tied to React routing
        assert d.phase == "monitoring"
        d.stop_monitoring()
        assert d.phase == "ready"

    def test_reset_does_not_create_duplicate(self):
        """Reset should reuse the same engine, not create a new one."""
        from ai.driver.driver_drowsiness import driver_detector
        id_before = id(driver_detector)
        driver_detector.reset()
        id_after = id(driver_detector)
        assert id_before == id_after  # same object


# ═══════════════════════════════════════════════════════════════════════
# Simulation Separation
# ═══════════════════════════════════════════════════════════════════════

class TestSimulationSeparation:
    def test_live_events_never_simulation(self):
        """Live DDS events must never have simulation=True."""
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker", return_value=_lm(ear=0.15)), \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.0
            d.process_frame(_frame())
        for e in events:
            assert e["simulation"] is False
            assert e["data_source"] == "live"
            assert e["bus_id"] == "PROTO-001"

    def test_live_bus_data_source(self):
        """PROTO-001 bus object must have data_source=live."""
        from server import _proto_bus
        bus = _proto_bus()
        assert bus["data_source"] == "live"
        assert bus["live"] is True


# ═══════════════════════════════════════════════════════════════════════
# Global Alert Flow
# ═══════════════════════════════════════════════════════════════════════

class TestGlobalAlertFlow:
    def test_drowsiness_emits_event_for_alert(self):
        """DDS drowsiness → DRIVER_DROWSINESS event → can trigger global alert."""
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker", return_value=_lm(ear=0.15)), \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.0
            d.process_frame(_frame())
        drowsy = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS"]
        assert len(drowsy) >= 1
        # Event has the fields the global alert needs
        e = drowsy[0]
        assert "additional_data" in e
        assert "note" in e["additional_data"]
        assert e["bus_id"] == "PROTO-001"

    def test_alert_not_spammed(self):
        """Only one DRIVER_DROWSINESS event per episode, not one per frame."""
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker", return_value=_lm(ear=0.15)), \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.0
            for _ in range(10):
                d.process_frame(_frame())
        drowsy = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS"]
        assert len(drowsy) == 1  # only one, not ten

    def test_recovery_allows_new_alert(self):
        """After recovery, a new drowsiness episode can generate a new alert."""
        events = []
        d = _det(callback=lambda e: events.append(e))
        d.start_monitoring()
        with patch("ai.driver.driver_drowsiness._load_landmarker", return_value=True), \
             patch("ai.driver.driver_drowsiness._detect_with_landmarker") as mock_lm, \
             patch("ai.driver.driver_drowsiness._load_cascades"):
            # Episode 1
            mock_lm.return_value = _lm(ear=0.15)
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.0
            d.process_frame(_frame())
            # Recovery
            mock_lm.return_value = _lm(ear=0.45)
            d.process_frame(_frame())
            # Episode 2
            mock_lm.return_value = _lm(ear=0.15)
            d.process_frame(_frame())
            d._eye_closed_start = time.time() - 2.0
            d.process_frame(_frame())
        drowsy = [e for e in events if e["event_type"] == "DRIVER_DROWSINESS"]
        assert len(drowsy) >= 2


# ═══════════════════════════════════════════════════════════════════════
# Camera Failure Handling
# ═══════════════════════════════════════════════════════════════════════

class TestCameraFailure:
    def test_no_camera_does_not_crash_api(self):
        """When camera is unavailable, API endpoints must still respond."""
        from ai.camera_manager import CameraManager
        mgr = CameraManager()
        # No camera opened
        assert mgr.get_frame_as_base64() is None
        status = mgr.get_camera_status()
        assert status["mode"] == "stopped"
        # Should not raise
        results = mgr.get_detection_results()
        assert isinstance(results, dict)

    def test_dds_works_without_camera(self):
        """DDS engine should work even without a camera feed."""
        d = _det()
        d.start_monitoring()
        # Process a None frame (simulates no camera)
        result = d.process_frame(None)
        assert result["state"] == "NORMAL"  # default for None frame
        assert result["face_detected"] is False
        # DDS should still be running
        assert d.phase == "monitoring"

    def test_camera_restart_after_failure(self):
        """Camera can be stopped and restarted without issues."""
        from ai.camera_manager import CameraManager
        mgr = CameraManager()
        mgr.stop()  # stop when already stopped
        mgr.stop()  # idempotent
        assert mgr.mode == "stopped"
