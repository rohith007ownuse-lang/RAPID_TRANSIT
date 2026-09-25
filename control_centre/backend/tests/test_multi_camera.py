"""
test_multi_camera.py
Phase 6: multi-camera architecture tests.

Covers the independent per-camera lifecycle:
  - driver + cabin run as fully independent sources
  - failure isolation (one camera unavailable never stops the other)
  - honest state reporting (CONNECTED / DISCONNECTED / DISABLED / ERROR)
  - per-camera streams, resolution/FPS metadata
  - config-driven disable (FLEETIQ_CABIN_CAMERA_DEVICE=none)
  - single-camera test mode retained for all slots
  - API surface: /api/camera/status (open) + /api/camera/multi-camera (auth-gated)

All tests are hardware-independent: cv2 is mocked, cameras are fake captures.
"""

import contextlib
import os
import sys
import time
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock cv2 at module level so importing the manager/AI modules is safe.
cv2_mock = MagicMock()
sys.modules.setdefault("cv2", cv2_mock)

import pytest  # noqa: E402

from ai.camera_manager import (  # noqa: E402
    CameraManager,
    SLOT_DRIVER,
    SLOT_CABIN,
    SLOT_ROAD,
)
import server  # noqa: E402


def _make_cap(ok=True, res=(640, 480), fps=30.0):
    """A fake capture device. Device props are exposed exactly like a real cap."""
    cap = MagicMock()
    cap.isOpened.return_value = ok
    if ok:
        cap.read.return_value = (True, np.zeros((res[1], res[0], 3), dtype=np.uint8))
        cap.get.side_effect = lambda prop: {3: res[0], 4: res[1], 5: fps}.get(prop, 0.0)
    else:
        cap.read.return_value = (False, None)
        cap.get.return_value = 0.0
    return cap


def _cv2_local(caps):
    """cv2 stand-in: VideoCapture hands out the fake caps in order."""
    c = MagicMock()
    c.CAP_PROP_FRAME_WIDTH = 3
    c.CAP_PROP_FRAME_HEIGHT = 4
    c.CAP_PROP_FPS = 5
    c.FONT_HERSHEY_SIMPLEX = 0
    c.IMWRITE_JPEG_QUALITY = 80
    c.VideoCapture.side_effect = list(caps)
    c.imencode.return_value = (True, np.array([0xFF, 0xD8, 0xFF, 0xE0], dtype=np.uint8))
    return c


def _set_detectors(mgr):
    driver = MagicMock()
    driver.process_frame.return_value = {
        "state": "NORMAL", "ear": 0.40, "mar": 0.05, "closed_sec": 0.0,
        "face_detected": True, "ear_threshold": 0.23, "mar_threshold": 0.40,
    }
    cabin = MagicMock()
    cabin.process_frame.return_value = []
    pothole = MagicMock()
    pothole.detect.return_value = []
    mgr._driver_detector = driver
    mgr._cabin_detector = cabin
    mgr._pothole_detector = pothole
    return mgr


@contextlib.contextmanager
def _multi_ctx(caps):
    """A fresh manager with patched cv2; always stopped cleanly afterwards."""
    with patch("ai.camera_manager.cv2", _cv2_local(caps)):
        mgr = _set_detectors(CameraManager())
        try:
            yield mgr
        finally:
            mgr.stop()


class TestMultiCameraMode:
    def test_starts_driver_and_cabin_independently(self):
        with _multi_ctx([_make_cap(), _make_cap()]) as mgr:
            ok, msg = mgr.set_multi_camera_mode()
            assert ok is True, msg
            assert mgr.mode == "multi_camera"
            assert mgr.test_mode is False
            assert mgr.test_slot is None
            assert mgr.is_slot_active(SLOT_DRIVER) is True
            assert mgr.is_slot_active(SLOT_CABIN) is True
            assert mgr.is_slot_active(SLOT_ROAD) is False

            status = mgr.get_camera_status()
            assert status["mode"] == "multi_camera"
            assert status["slots"][SLOT_DRIVER]["status"] == "CONNECTED"
            assert status["slots"][SLOT_CABIN]["status"] == "CONNECTED"
            assert status["slots"][SLOT_ROAD]["status"] == "DISCONNECTED"
            assert status["available_cameras"] == [0, 1]
            assert SLOT_DRIVER in status["cameras"]
            assert status["cameras"][SLOT_DRIVER]["camera_id"] != status["cameras"][SLOT_CABIN]["camera_id"]

    def test_cabin_failure_does_not_stop_driver(self):
        with _multi_ctx([_make_cap(ok=True), _make_cap(ok=False)]) as mgr:
            ok, msg = mgr.set_multi_camera_mode()
            assert ok is True, msg  # driver still runs
            assert mgr.is_slot_active(SLOT_DRIVER) is True
            # No shared fallback: the driver feed is DDS-only and must never
            # be counted as passengers, so a failed cabin reports
            # DISCONNECTED honestly instead of mirroring the driver feed.
            assert mgr.is_slot_active(SLOT_CABIN) is False
            status = mgr.get_camera_status()
            assert status["slots"][SLOT_DRIVER]["status"] == "CONNECTED"
            assert status["slots"][SLOT_CABIN]["status"] == "DISCONNECTED"
            assert status["slots"][SLOT_CABIN]["shared"] is False
            assert status["slots"][SLOT_CABIN]["shared_with"] is None
            assert status["available_cameras"] == [0]

    def test_driver_failure_does_not_stop_cabin(self):
        with _multi_ctx([_make_cap(ok=False), _make_cap(ok=True)]) as mgr:
            ok, msg = mgr.set_multi_camera_mode()
            assert ok is True, msg  # cabin still runs
            assert mgr.is_slot_active(SLOT_CABIN) is True
            assert mgr.is_slot_active(SLOT_DRIVER) is False
            status = mgr.get_camera_status()
            assert status["slots"][SLOT_DRIVER]["status"] == "DISCONNECTED"
            assert status["slots"][SLOT_CABIN]["status"] == "CONNECTED"
            assert status["available_cameras"] == [1]

    def test_road_not_started_in_multi(self):
        with _multi_ctx([_make_cap(), _make_cap()]) as mgr:
            mgr.set_multi_camera_mode()
            assert mgr.is_slot_active(SLOT_ROAD) is False
            assert mgr.get_camera_status()["slots"][SLOT_ROAD]["status"] == "DISCONNECTED"

    def test_cabin_disabled_via_config(self, monkeypatch):
        monkeypatch.setenv("FLEETIQ_DRIVER_CAMERA_DEVICE", "0")
        monkeypatch.setenv("FLEETIQ_CABIN_CAMERA_DEVICE", "none")
        with _multi_ctx([_make_cap()]) as mgr:
            ok, msg = mgr.set_multi_camera_mode()
            assert ok is True, msg
            status = mgr.get_camera_status()
            assert status["slots"][SLOT_DRIVER]["status"] == "CONNECTED"
            assert status["slots"][SLOT_CABIN]["status"] == "DISABLED"
            assert status["slots"][SLOT_CABIN]["enabled"] is False

    def test_both_unavailable_is_not_success(self):
        with _multi_ctx([_make_cap(ok=False), _make_cap(ok=False)]) as mgr:
            ok, msg = mgr.set_multi_camera_mode()
            assert ok is False
            assert "No cameras available" in msg
            assert mgr.mode == "stopped"
            status = mgr.get_camera_status()
            assert status["slots"][SLOT_DRIVER]["status"] == "DISCONNECTED"
            assert status["slots"][SLOT_CABIN]["status"] == "DISCONNECTED"

    def test_no_cv2_multi_graceful(self):
        mgr = CameraManager()
        with patch("ai.camera_manager._import_cv2", return_value=False):
            ok, _ = mgr.set_multi_camera_mode()
            assert not ok


class TestSingleCameraTestModeRetained:
    def test_single_test_mode_still_works_for_any_slot(self):
        with _multi_ctx([_make_cap(), _make_cap()]) as mgr:
            ok, msg = mgr.set_single_camera_test_mode(SLOT_CABIN)
            assert ok is True, msg
            assert mgr.test_mode is True
            assert mgr.test_slot == SLOT_CABIN
            status = mgr.get_camera_status()
            assert status["slots"][SLOT_CABIN]["status"] == "CONNECTED"
            assert status["slots"][SLOT_DRIVER]["status"] == "DISCONNECTED"
            assert status["slots"][SLOT_ROAD]["status"] == "DISCONNECTED"

    def test_disabled_slot_rejected_in_single_mode(self, monkeypatch):
        monkeypatch.setenv("FLEETIQ_CABIN_CAMERA_DEVICE", "off")
        with _multi_ctx([_make_cap()]) as mgr:
            ok, msg = mgr.set_single_camera_test_mode(SLOT_CABIN)
            assert ok is False
            assert "disabled" in msg


class TestPerCameraStreamAndMetadata:
    def test_per_slot_stream_returns_frames(self):
        with _multi_ctx([_make_cap(), _make_cap()]) as mgr:
            mgr.set_multi_camera_mode()
            time.sleep(0.2)  # let both loops deliver a frame
            assert mgr.get_frame_as_base64(SLOT_DRIVER) is not None
            assert mgr.get_frame_as_base64(SLOT_CABIN) is not None
            assert mgr.get_frame_as_base64(SLOT_ROAD) is None

    def test_per_slot_honest_metadata(self):
        caps = [
            _make_cap(ok=True, res=(1920, 1080), fps=24.0),
            _make_cap(ok=True, res=(640, 480), fps=30.0),
        ]
        with _multi_ctx(caps) as mgr:
            mgr.set_multi_camera_mode()
            status = mgr.get_camera_status()
            d = status["slots"][SLOT_DRIVER]
            c = status["slots"][SLOT_CABIN]
            assert d["resolution"] == "1920x1080" and d["fps"] == 24.0
            assert d["resolution_source"] == "device" and d["fps_source"] == "device"
            assert c["resolution"] == "640x480" and c["fps"] == 30.0
            assert c["resolution_source"] == "device" and c["fps_source"] == "device"

    def test_detections_are_per_slot(self):
        with _multi_ctx([_make_cap(), _make_cap()]) as mgr:
            mgr.set_multi_camera_mode()
            time.sleep(0.2)  # let detection run at least once per camera
            assert mgr.get_detection_results(SLOT_DRIVER).get("state") == "NORMAL"
            assert mgr.get_detection_results(SLOT_CABIN) == []
            assert mgr.get_detection_results(SLOT_ROAD) == []


class TestStopInMultiMode:
    def test_stop_stops_every_camera(self):
        with _multi_ctx([_make_cap(), _make_cap()]) as mgr:
            mgr.set_multi_camera_mode()
            caps = [mgr._sources[SLOT_DRIVER].cap, mgr._sources[SLOT_CABIN].cap]
            mgr.stop()
            assert mgr.mode == "stopped"
            assert mgr.is_slot_active(SLOT_DRIVER) is False
            assert mgr.is_slot_active(SLOT_CABIN) is False
            for c in caps:
                c.release.assert_called()
            assert mgr.get_frame_as_base64(SLOT_DRIVER) is None
            status = mgr.get_camera_status()
            assert status["slots"][SLOT_DRIVER]["status"] == "DISCONNECTED"
            assert status["slots"][SLOT_CABIN]["status"] == "DISCONNECTED"


class TestMultiCameraApi:
    @pytest.fixture
    def client(self):
        return server.app.test_client()

    def test_status_endpoint_open(self, client):
        resp = client.get("/api/camera/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "cameras" in data and SLOT_DRIVER in data["cameras"]

    def test_multi_camera_endpoint_requires_auth(self, client):
        resp = client.post("/api/camera/multi-camera", json={})
        assert resp.status_code in (401, 503)

    def test_multi_camera_endpoint_with_auth(self, client):
        login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert login.status_code == 200
        token = login.get_json()["token"]
        with patch(
            "ai.camera_manager.camera_manager.set_multi_camera_mode",
            return_value=(True, "Multi-camera active: driver"),
        ):
            resp = client.post("/api/camera/multi-camera", json={},
                               headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert isinstance(data["mode"], str)