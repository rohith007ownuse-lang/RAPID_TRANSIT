"""
test_phase2_hardening.py
Phase 2 — controlled correction tests.

Covers exactly the verified correctness/reliability issues fixed in Phase 2:
  - Simulation/live honesty: passenger events are marked simulation; genuine
    live events (drowsiness/DDS/WS) remain live.
  - Camera metadata: no fabricated fps/resolution; real device values reused;
    camera status stays valid.
  - DDS graceful shutdown: SIGINT/SIGTERM path stops DDS, captures the session,
    releases camera + WS, and refuses new work while shutting down.

Note: the Phase 2 scenario-flag tests lived here but were removed in Phase 3
because the Scenarios product feature itself was removed.

These tests do NOT depend on a webcam or a running DDS binary.
"""

import os
import sys
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# cv2 must be mocked before importing server/camera_manager modules.
cv2_mock = MagicMock()
sys.modules.setdefault("cv2", cv2_mock)

import server  # noqa: E402
import lifecycle  # noqa: E402
from lifecycle import get_lifecycle  # noqa: E402
from ai.camera_manager import CameraManager, SLOT_DRIVER, SLOT_CABIN, SLOT_ROAD  # noqa: E402
from ai.driver.driver_drowsiness import DriverDrowsinessDetector  # noqa: E402
from data_store import store  # noqa: E402
from websocket_handler import adapt_bus_state, stop_websocket_server  # noqa: E402


def _reset_lifecycle():
    """Replace the lifecycle singleton so shutdown state never leaks between
    tests (Phase 20: shutdown state lives in lifecycle, not on server)."""
    lifecycle._lifecycle = None


@pytest.fixture(autouse=True)
def _clean_state():
    store.events.clear()
    store.buses.clear()
    store.road_defects.clear()
    _reset_lifecycle()
    yield
    store.events.clear()
    _reset_lifecycle()


# ═══════════════════════════════════════════════════════════════════════
# 1. HONESTY — simulated must never be labelled live
# ═══════════════════════════════════════════════════════════════════════

class TestHonesty:
    def test_passenger_moment_event_marked_simulation(self):
        ev = server._passenger_event(
            {"latitude": 13.1, "longitude": 80.2}, "PASSENGER_MOMENT", "INFO",
            0.93, "boarding at stop", 12, {"crowd": "NORMAL", "passengers": 12},
        )
        assert ev["simulation"] is True
        assert ev["data_source"] == "simulation"
        assert ev["sensor_source"] == "passenger_counter"
        assert ev["bus_id"] == "PROTO-001"

    def test_overload_event_marked_simulation(self):
        ev = server._passenger_event(
            {"latitude": 13.1, "longitude": 80.2}, "OVERLOAD", "CRITICAL",
            0.95, "Overload: 60/60 (100%)", 60, {"crowd": "OVERCROWDED", "passengers": 60},
        )
        assert ev["simulation"] is True
        assert ev["data_source"] == "simulation"

    def test_simulated_passenger_event_stored_as_simulation(self):
        store.events.clear()
        ev = server._passenger_event(
            {"latitude": 13.1, "longitude": 80.2}, "PASSENGER_MOMENT", "INFO",
            0.9, "demo", 8, {"crowd": "NORMAL", "passengers": 8},
        )
        store.add_event(ev)
        stored = list(store.events.values())[-1]
        assert stored["simulation"] is True
        assert stored["data_source"] == "simulation"

    def test_live_drowsiness_events_remain_live(self):
        d = DriverDrowsinessDetector()
        ev = d._build_event("DRIVER_DROWSINESS", "CRITICAL", 0.9, "live demo")
        assert ev["data_source"] == "live"
        assert ev["simulation"] is False

    def test_websocket_adapter_preserves_live_flag(self):
        live = adapt_bus_state({"bus_id": "PROTO-001", "data_source": "live", "driver": {}})
        assert live["simulation"] is False
        assert live["data_source"] == "live"

    def test_websocket_adapter_preserves_simulation_flag(self):
        sim = adapt_bus_state({"bus_id": "BUS-1", "data_source": "simulation", "driver": {}})
        assert sim["simulation"] is True
        assert sim["data_source"] == "simulation"


# ═══════════════════════════════════════════════════════════════════════
# 2. CAMERA METADATA — honest, no fabricated fps/resolution
# ═══════════════════════════════════════════════════════════════════════

class TestCameraMetadata:
    def _fake_cv2(self):
        return SimpleNamespace(
            CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4, CAP_PROP_FPS=5,
        )

    def test_no_metadata_not_fabricated(self):
        """When the device reports nothing, status must say unknown, not 640x480/30."""
        mgr = CameraManager()
        mgr._mode = "single_camera"
        mgr._active_slot = SLOT_DRIVER
        mgr._test_mode = True
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mgr._cap = mock_cap
        with patch("ai.camera_manager.cv2", MagicMock()):
            status = mgr.get_camera_status()
        s = status["slots"][SLOT_DRIVER]
        assert s["resolution"] is None
        assert s["fps"] is None
        assert not status["slots"][SLOT_DRIVER]["connected"] or s.get("resolution") is None

    def test_device_resolution_and_fps_used(self):
        mgr = CameraManager()
        mgr._mode = "single_camera"
        mgr._active_slot = SLOT_DRIVER
        mgr._test_mode = True
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {3: 1920.0, 4: 1080.0, 5: 24.0}.get(prop, 0.0)
        mgr._cap = mock_cap
        with patch("ai.camera_manager.cv2", self._fake_cv2()):
            status = mgr.get_camera_status()
        s = status["slots"][SLOT_DRIVER]
        assert s["resolution"] == "1920x1080"
        assert s["fps"] == 24.0
        assert s["fps_source"] == "device"

    def test_measured_fps_preferred_when_available(self):
        mgr = CameraManager()
        mgr._mode = "single_camera"
        mgr._active_slot = SLOT_DRIVER
        mgr._test_mode = True
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {3: 640.0, 4: 480.0, 5: 30.0}.get(prop, 0.0)
        mgr._cap = mock_cap
        mgr._measured_fps = 18.5
        with patch("ai.camera_manager.cv2", self._fake_cv2()):
            status = mgr.get_camera_status()
        s = status["slots"][SLOT_DRIVER]
        assert s["fps"] == 18.5
        assert s["fps_source"] == "measured"

    def test_camera_status_structure_valid(self):
        mgr = CameraManager()
        status = mgr.get_camera_status()
        assert status["mode"] == "stopped"
        for slot in (SLOT_DRIVER, SLOT_CABIN, SLOT_ROAD):
            assert slot in status["slots"]
            assert "resolution" in status["slots"][slot]
            assert "fps" in status["slots"][slot]
            assert "fps_source" in status["slots"][slot]


# ═══════════════════════════════════════════════════════════════════════
# 3. DDS GRACEFUL SHUTDOWN
# ═══════════════════════════════════════════════════════════════════════

class TestShutdown:
    def _patch_components(self, running=False):
        mgr = MagicMock()
        mgr.is_running = running
        mgr.stop = MagicMock(return_value=(True, "DDS stopped"))
        cm_mock = MagicMock()
        ws_stop = MagicMock()
        patchers = (
            patch("ai.dds.dds_process.get_dds_manager", return_value=mgr),
            patch("ai.camera_manager.camera_manager", cm_mock),
            patch("server.stop_websocket_server", ws_stop),
            patch("lifecycle.ApplicationLifecycle.capture_dds_session"),
        )
        return patchers, mgr, cm_mock, ws_stop

    def _graceful_shutdown(self, patchers):
        """Production path: register the ordered hooks, then signal shutdown."""
        with ExitStack() as stack:
            entered = [stack.enter_context(p) for p in patchers]
            server._register_shutdown_hooks()
            get_lifecycle().stop()
        return entered

    def test_shutdown_with_already_stopped_dds(self):
        patchers, mgr, cm, ws_stop = self._patch_components(running=False)
        entered = self._graceful_shutdown(patchers)
        capture_mock = entered[3]
        assert get_lifecycle().is_shutting_down
        mgr.stop.assert_not_called()  # already stopped -> no spurious stop
        capture_mock.assert_called_once()
        cm.stop.assert_called_once()
        ws_stop.assert_called_once()

    def test_shutdown_with_active_dds(self):
        patchers, mgr, cm, ws_stop = self._patch_components(running=True)
        entered = self._graceful_shutdown(patchers)
        capture_mock = entered[3]
        mgr.stop.assert_called_once()
        capture_mock.assert_called_once()
        cm.stop.assert_called_once()
        ws_stop.assert_called_once()

    def test_new_work_refused_while_shutting_down(self):
        get_lifecycle().request_shutdown()
        client = server.app.test_client()
        resp = client.post("/api/dds/subprocess/start")
        assert resp.status_code == 503
        resp = client.post("/api/camera/start", json={"slot": "driver"})
        assert resp.status_code == 503
        assert resp.json.get("error") == "server is shutting down"

    def test_capture_dds_session_dedupes(self):
        ev_a = {"event_type": "DRIVER_DROWSINESS", "bus_id": "PROTO-001",
                "timestamp": "2026-01-01T00:00:00+00:00", "details": "drowsy",
                "data_source": "live"}
        ev_b = {"event_type": "DDS_SESSION_END", "bus_id": "PROTO-001",
                "timestamp": "2026-01-01T00:01:00+00:00", "details": "session done"}
        store.events.clear()
        store.add_event(dict(ev_a))  # already ingested via live callback
        with patch("ai.dds.dds_log_reader.get_dds_log_files", return_value=["f.csv"]), \
             patch("ai.dds.dds_log_reader.read_dds_events", return_value=[ev_a, ev_b]):
            before = len(store.events)
            get_lifecycle().capture_dds_session()
            after = len(store.events)
        new_events = [e for e in store.events.values() if e.get("details") == "session done"]
        assert new_events, "session-only event should have been captured"
        assert after == before + 1  # only the not-already-ingested event

    def test_websocket_stop_no_server_no_crash(self):
        stop_websocket_server()  # no server running -> must not raise

    def test_websocket_stop_requests_event_set(self):
        loop, event = MagicMock(), MagicMock()
        with patch("websocket_handler._ws_loop", loop), \
             patch("websocket_handler._ws_stop_event", event):
            stop_websocket_server()
            loop.call_soon_threadsafe.assert_called_once_with(event.set)