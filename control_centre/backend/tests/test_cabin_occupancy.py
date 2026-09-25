"""
test_cabin_occupancy.py
Phase 7: cabin occupancy intelligence tests.

Covers:
  - occupancy data model (count / capacity / percentage / crowding / source)
  - percentage bounds and zero/invalid capacity handling
  - honest unavailable state (unknown = null, never 0)
  - cabin connected / disconnected / disabled / error camera states
  - driver camera is never touched by the cabin engine
  - failure isolation (estimator errors cannot stop the engine or backend)
  - simulation vs live labelling
  - API exposure (GET /api/cabin/occupancy)
  - WebSocket bus schema carries cabin_occupancy passthrough (no new transport)

All tests are hardware-independent: cameras and stores are fakes, frames are
synthetic numpy arrays.
"""

import os
import sys
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock cv2 early so importing server is safe (same pattern as Phase 6 tests).
from unittest.mock import MagicMock

sys.modules.setdefault("cv2", MagicMock())

import pytest  # noqa: E402

from ai.cabin.occupancy import (  # noqa: E402
    CABIN_CAMERA_ID,
    CabinHeuristicEstimator,
    CabinMLPersonDetector,
    CabinOccupancyEngine,
    build_occupancy_snapshot,
    capacity_of,
    crowding_level,
    occupancy_percentage,
    unavailable_snapshot,
)
import server  # noqa: E402
from websocket_handler import adapt_bus_state  # noqa: E402

BLACK = np.zeros((480, 640, 3), dtype=np.uint8)
WHITE = np.full((480, 640, 3), 255, dtype=np.uint8)

BUS = {"bus_id": "PROTO-001", "occupancy": {"passengers": 0, "pct": 0, "capacity": 40}}


@pytest.fixture(autouse=True)
def _cabin_env(monkeypatch):
    """Deterministic env for cabin occupancy regardless of host environment.

    The real person model is explicitly disabled here so the engine/heuristic
    tests stay hermetic and never pay the torch/YOLO load cost. Real-model
    behaviour is covered by dedicated tests with injected fakes.
    """
    monkeypatch.delenv("FLEETIQ_CAMERA_BUS_ID", raising=False)
    monkeypatch.setenv("FLEETIQ_CABIN_MODEL_PATH", "off")
    monkeypatch.delenv("FLEETIQ_CABIN_DEFAULT_CAPACITY", raising=False)
    monkeypatch.delenv("FLEETIQ_CABIN_INFERENCE_INTERVAL_SEC", raising=False)


# ---------------------------------------------------------------------- fakes
class FakeCameraManager:
    def __init__(self, cabin_status="CONNECTED", frame=None, error=None):
        self.cabin_status = cabin_status
        self.frame = frame if frame is not None else BLACK
        self.error = error

    def get_camera_status(self):
        sl = {"cabin": {"status": self.cabin_status, "error": self.error}}
        return {"slots": sl}

    def get_latest_frame(self, slot):
        return self.frame if slot == "cabin" else None


class TrackingCameraManager(FakeCameraManager):
    def __init__(self):
        super().__init__()
        self.calls = []

    def get_camera_status(self):
        self.calls.append("status")
        return super().get_camera_status()

    def get_latest_frame(self, slot):
        self.calls.append(slot)
        return super().get_latest_frame(slot)


class FakeStore:
    def __init__(self):
        self.buses = {}

    def get_bus(self, bus_id):
        return self.buses.get(bus_id)

    def upsert_bus(self, bus):
        self.buses[bus["bus_id"]] = bus


class FakeMode:
    def __init__(self, is_live=False):
        self.is_live = is_live


def _engine(cabin_status="CONNECTED", frame=BLACK, error=None, is_live=True, store=None, interval=0.05):
    cm = FakeCameraManager(cabin_status, frame=frame, error=error)
    st = store or FakeStore()
    st.upsert_bus(dict(BUS))
    return CabinOccupancyEngine(cm, st, FakeMode(is_live=is_live), estimator=CabinHeuristicEstimator(), interval=interval)


# ------------------------------------------------------------------ data model
class TestOccupancyDataModel:
    def test_snapshot_required_keys(self):
        snap = build_occupancy_snapshot("PROTO-001", 29, 40)
        for key in ("bus_id", "camera_id", "timestamp", "occupancy_count",
                    "occupancy_percentage", "capacity", "crowding_level",
                    "confidence", "source", "status"):
            assert key in snap
        assert snap["camera_id"] == CABIN_CAMERA_ID
        assert snap["bus_id"] == "PROTO-001"

    def test_percentage_calculation(self):
        snap = build_occupancy_snapshot("PROTO-001", 29, 40)
        assert snap["occupancy_count"] == 29
        assert snap["capacity"] == 40
        assert snap["occupancy_percentage"] == 72
        assert snap["crowding_level"] == "MODERATE"
        assert snap["status"] == "CONNECTED"

    def test_heuristic_snapshot_is_labelled_not_ai(self):
        snap = build_occupancy_snapshot(
            "PROTO-001", 29, 40, confidence=None,
            estimator="heuristic", estimator_type="development",
            method="foreground-density grid proxy",
        )
        assert snap["source"] == "cabin_camera_heuristic"
        assert snap["estimator"] == "heuristic"
        assert snap["estimator_type"] == "development"
        assert snap["confidence"] is None
        assert snap["model"] is None

    def test_percentage_bounds_count_over_capacity(self):
        snap = build_occupancy_snapshot("PROTO-001", 50, 40)
        assert snap["occupancy_percentage"] == 100
        assert snap["crowding_level"] == "CRITICAL"

    def test_zero_capacity_is_safe(self):
        snap = build_occupancy_snapshot("PROTO-001", 10, 0)
        assert snap["occupancy_percentage"] is None
        assert snap["crowding_level"] is None
        assert snap["capacity"] is None

    def test_percentage_helper_invalid_capacity(self):
        assert occupancy_percentage(None, 40) is None
        assert occupancy_percentage(10, 0) is None
        assert occupancy_percentage(10, None) is None
        assert occupancy_percentage(10, "nope") is None

    def test_crowding_thresholds(self):
        assert crowding_level(None) is None
        assert crowding_level(0) == "NORMAL"
        assert crowding_level(59) == "NORMAL"
        assert crowding_level(60) == "MODERATE"
        assert crowding_level(74) == "MODERATE"
        assert crowding_level(75) == "HIGH"
        assert crowding_level(89) == "HIGH"
        assert crowding_level(90) == "CRITICAL"
        assert crowding_level(100) == "CRITICAL"

    def test_capacity_inherited_from_bus_internal_field(self):
        bus = {"occupancy": {"passengers": 3, "pct": 5, "capacity": 60}}
        assert capacity_of(bus) == 60
        assert capacity_of(None) == 40  # documented fallback, not claimed real


# ----------------------------------------------------------- honesty (unknown)
class TestUnavailableHonesty:
    def test_disconnected_unknown_is_not_zero(self):
        snap = unavailable_snapshot("PROTO-001", status="DISCONNECTED", capacity=40)
        assert snap["occupancy_count"] is None
        assert snap["occupancy_percentage"] is None
        assert snap["crowding_level"] is None
        assert snap["confidence"] is None
        assert snap["status"] == "DISCONNECTED"
        assert snap["simulation"] is False

    def test_disabled_status_same_unknown(self):
        snap = unavailable_snapshot("PROTO-001", status="DISABLED")
        assert snap["status"] == "DISABLED"
        assert snap["occupancy_count"] is None

    def test_error_reason_carried(self):
        snap = unavailable_snapshot("PROTO-001", status="ERROR", error="Failed to open camera on device 1")
        assert snap["error"] == "Failed to open camera on device 1"
        assert snap["occupancy_count"] is None


# ---------------------------------------------------------------- estimator
class TestHeuristicEstimator:
    def test_none_frame_returns_none(self):
        est = CabinHeuristicEstimator()
        assert est.estimate(None, 40) is None

    def test_blank_frames_yield_zero_estimate(self):
        est = CabinHeuristicEstimator()
        assert est.estimate(BLACK, 40) == 0
        assert est.estimate(BLACK, 40) == 0

    def test_black_to_white_yields_full_estimate(self):
        est = CabinHeuristicEstimator()
        est.estimate(BLACK, 40)
        assert est.estimate(WHITE, 40) == 40

    def test_estimate_bounded_to_capacity(self):
        est = CabinHeuristicEstimator()
        assert 0 <= est.estimate(BLACK, 40) <= 40
        assert est.estimate(WHITE, 0) == 0

    def test_kind_is_heuristic_development(self):
        est = CabinHeuristicEstimator()
        assert est.kind == "heuristic"
        assert est.estimator_type == "development"


class TestRealModelSlot:
    def test_real_model_resolves_in_repo_weights_by_default(self, monkeypatch):
        # No explicit env -> falls back to the in-repo yolov8n.pt (COCO person).
        monkeypatch.delenv("FLEETIQ_CABIN_MODEL_PATH", raising=False)
        m = CabinMLPersonDetector()
        assert m.available is True
        assert m.model_path is not None and m.model_path.endswith(".pt")
        assert m.error is None
        # Lazy: constructing must NOT load torch/YOLO yet.
        assert m._model is None

    def test_real_model_explicitly_disabled(self, monkeypatch):
        monkeypatch.setenv("FLEETIQ_CABIN_MODEL_PATH", "off")
        m = CabinMLPersonDetector()
        assert m.available is False
        assert m.estimate(BLACK, 40) == (None, None, None)

    def test_real_model_path_missing_is_not_available(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FLEETIQ_CABIN_MODEL_PATH", str(tmp_path / "does-not-exist.pt"))
        m = CabinMLPersonDetector()
        assert m.available is False
        assert "no configured cabin model file" in (m.error or "")


# -------------------------------------------------------------------- engine
class TestCabinOccupancyEngine:
    def test_connected_produces_snapshot_and_bus_field(self):
        eng = _engine()
        eng._tick()
        st = eng.public_state()
        assert st["status"] == "CONNECTED"
        # first tick only initialises the background -> 0-estimate (a real one)
        assert st["occupancy_count"] == 0
        assert st["occupancy_percentage"] == 0
        assert st["crowding_level"] == "NORMAL"
        assert st["confidence"] is None
        bus = eng._store.buses["PROTO-001"]
        assert bus["cabin_occupancy"]["occupancy_count"] == 0

        eng._cm.frame = WHITE
        eng._tick()
        st = eng.public_state()
        assert st["occupancy_count"] == 40
        assert st["occupancy_percentage"] == 100
        assert st["crowding_level"] == "CRITICAL"
        assert st["estimator"] == "heuristic"
        assert st["estimator_in_use"] == "heuristic (development)"

    def test_disconnected_is_unknown_not_zero(self):
        eng = _engine(cabin_status="DISCONNECTED", error="Failed to open camera on device 1")
        eng._tick()
        st = eng.public_state()
        assert st["status"] == "DISCONNECTED"
        assert st["occupancy_count"] is None
        assert st["occupancy_percentage"] is None
        assert st["crowding_level"] is None
        assert st["confidence"] is None
        assert "Failed to open camera" in (st["error"] or "")

    def test_disabled_the_same(self):
        eng = _engine(cabin_status="DISABLED")
        eng._tick()
        st = eng.public_state()
        assert st["status"] == "DISABLED"
        assert st["occupancy_count"] is None

    def test_error_state_is_unknown(self):
        eng = _engine(cabin_status="ERROR", error="camera error")
        eng._tick()
        st = eng.public_state()
        assert st["status"] == "ERROR"
        assert st["occupancy_count"] is None

    def test_simulation_mode_no_snapshot_and_field_dropped(self):
        store = FakeStore()
        bus = dict(BUS)
        bus["cabin_occupancy"] = {"occupancy_count": 40}
        store.upsert_bus(bus)
        cm = FakeCameraManager("CONNECTED", frame=WHITE)
        eng = CabinOccupancyEngine(cm, store, FakeMode(is_live=False), estimator=CabinHeuristicEstimator(), interval=0.05)
        eng._tick()
        assert eng.public_state()["occupancy"] is None
        assert "cabin_occupancy" not in store.buses["PROTO-001"]

    def test_driver_camera_never_touched(self):
        cm = TrackingCameraManager()
        store = FakeStore()
        store.upsert_bus(dict(BUS))
        eng = CabinOccupancyEngine(cm, store, FakeMode(is_live=True), estimator=CabinHeuristicEstimator(), interval=0.05)
        eng._tick()
        assert "driver" not in cm.calls
        assert "status" in cm.calls
        assert "cabin" in cm.calls

    def test_estimator_failure_is_isolated(self):
        class _Boom(CabinHeuristicEstimator):
            def estimate(self, frame, capacity):
                raise RuntimeError("boom")

        cm = FakeCameraManager("CONNECTED", frame=BLACK)
        store = FakeStore()
        store.upsert_bus(dict(BUS))
        eng = CabinOccupancyEngine(cm, store, FakeMode(is_live=True), estimator=_Boom(), interval=0.05)
        eng._tick()  # must not raise
        st = eng.public_state()
        assert st["status"] == "CONNECTED"
        assert st["occupancy_count"] is None
        assert "boom" in (st["error"] or "")
        assert "boom" in (st["last_error"] or "")
        # engine remains usable
        eng._estimator = CabinHeuristicEstimator()
        eng._tick()
        assert eng.public_state()["occupancy_count"] == 0

    def test_real_model_flag(self, monkeypatch):
        # Fixture disables the person model -> flag honestly reports False.
        eng = _engine()
        assert eng.public_state()["real_model_available"] is False
        # With no explicit setting, the in-repo weights resolve -> True.
        monkeypatch.delenv("FLEETIQ_CABIN_MODEL_PATH", raising=False)
        eng2 = _engine()
        assert eng2.public_state()["real_model_available"] is True

    def test_inference_fps_none_when_no_successful_inference(self):
        # Disconnected camera: no estimates => inference_fps stays None (never
        # an inflated tick-rate artifact), and inference_count stays 0.
        eng = _engine(cabin_status="DISCONNECTED", error="Failed to open camera on device 1")
        eng._tick()
        eng._tick()
        st = eng.public_state()
        assert st["status"] == "DISCONNECTED"
        assert st["inference_count"] == 0
        assert st["inference_fps"] is None

    def test_inference_fps_set_after_successful_inferences(self):
        eng = _engine(cabin_status="CONNECTED", frame=WHITE)
        # first tick initialises the background (no estimate yet); subsequent
        # ticks estimate count=0 and must record wall-clock inference rate.
        eng._tick(started=0.0)
        eng._tick(started=0.1)
        eng._tick(started=0.2)
        eng._tick(started=0.3)
        st = eng.public_state()
        assert st["inference_count"] >= 1
        assert st["inference_fps"] is not None
        assert 0 < st["inference_fps"] <= 1000

    def test_loop_rate_bounded_by_interval(self):
        # The engine sleeps at least (interval - tick_time) so inference rate is
        # capped far below camera rate; just verify a short start/stop cycle is
        # well-behaved and bounded.
        eng = _engine(interval=0.05)
        eng.start()
        import time
        time.sleep(0.25)
        eng.stop()
        assert eng._inference_count <= 10


class FakePersonModel:
    """Injectable stand-in for CabinMLPersonDetector (no torch needed)."""
    kind = "ml-person-detector"
    estimator_type = "real-model"
    available = True

    def __init__(self, result=(3, 0.9, "person-detector(yolo)"), boxes=None, raise_=False):
        self._result = result
        self.last_boxes = boxes if boxes is not None else [[10, 10, 50, 90]]
        self._raise = raise_

    def estimate(self, frame, capacity):
        if self._raise:
            raise RuntimeError("yolo boom")
        return self._result


def _engine_with_real(real):
    cm = FakeCameraManager("CONNECTED", frame=BLACK)
    st = FakeStore()
    st.upsert_bus(dict(BUS))
    return CabinOccupancyEngine(cm, st, FakeMode(is_live=True),
                                estimator=CabinHeuristicEstimator(),
                                real_model=real, interval=0.05)


class TestRealPersonCount:
    def test_real_count_preferred_over_heuristic(self):
        eng = _engine_with_real(FakePersonModel(result=(3, 0.87, "person-detector(yolo)")))
        eng._tick()
        st = eng.public_state()
        assert st["occupancy_count"] == 3
        assert st["occupancy_percentage"] == 8  # 3 of 40 seats
        assert st["estimator"] == "ml-person-detector"
        assert st["estimator_type"] == "real-model"
        assert st["confidence"] == 0.87
        assert st["source"] == "cabin_camera"
        assert st["model"] == "person-detector(yolo)"
        assert st["person_boxes"] == [[10, 10, 50, 90]]
        assert st["estimator_in_use"] == "real-model (ml-person-detector)"
        assert st["real_model_available"] is True
        assert eng._store.buses["PROTO-001"]["cabin_occupancy"]["occupancy_count"] == 3

    def test_real_none_falls_back_to_heuristic(self):
        eng = _engine_with_real(FakePersonModel(result=(None, None, None)))
        eng._tick()
        st = eng.public_state()
        assert st["occupancy_count"] == 0  # heuristic BLACK first tick
        assert st["estimator"] == "heuristic"
        assert st["confidence"] is None
        assert st["estimator_in_use"] == "heuristic (development)"

    def test_real_error_is_isolated_to_heuristic(self):
        eng = _engine_with_real(FakePersonModel(raise_=True))
        eng._tick()  # must not raise
        st = eng.public_state()
        assert st["occupancy_count"] == 0
        assert st["estimator"] == "heuristic"


# ------------------------------------------------------------------------ API
class TestCabinOccupancyApi:
    @pytest.fixture
    def client(self):
        return server.app.test_client()

    def _fake_engine(self, **overrides):
        base = {
            "status": "DISCONNECTED",
            "bus_id": "PROTO-001",
            "camera_id": CABIN_CAMERA_ID,
            "timestamp": None,
            "occupancy_count": None,
            "occupancy_percentage": None,
            "capacity": 40,
            "crowding_level": None,
            "confidence": None,
            "source": "cabin_camera",
            "estimator": None,
            "estimator_type": None,
            "method": None,
            "camera_status": "DISCONNECTED",
            "real_model_available": False,
            "estimator_in_use": "heuristic (development)",
            "inference_count": 0,
            "system_mode": "live",
        }
        base.update(overrides)
        return base

    def test_occupancy_endpoint_open(self, client):
        with patch("ai.cabin.occupancy.get_cabin_engine") as get_engine:
            get_engine.return_value.public_state.return_value = self._fake_engine(
                status="CONNECTED", occupancy_count=29, occupancy_percentage=72,
                crowding_level="MODERATE", estimator="heuristic",
            )
            resp = client.get("/api/cabin/occupancy")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "CONNECTED"
            assert data["occupancy_count"] == 29
            assert data["occupancy_percentage"] == 72
            assert data["crowding_level"] == "MODERATE"
            assert data["estimator"] == "heuristic"
            assert data["real_model_available"] is False

    def test_occupancy_endpoint_honest_when_camera_down(self, client):
        with patch("ai.cabin.occupancy.get_cabin_engine") as get_engine:
            get_engine.return_value.public_state.return_value = self._fake_engine()
            resp = client.get("/api/cabin/occupancy")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "DISCONNECTED"
            assert data["occupancy_count"] is None
            assert data["occupancy_percentage"] is None
            assert data["crowding_level"] is None
            assert data["confidence"] is None


# ------------------------------------------------------------------ WebSocket
class TestWebSocketCabinPassthrough:
    def test_bus_state_accepts_cabin_occupancy(self):
        node = {
            "bus_id": "PROTO-001",
            "data_source": "live",
            "occupancy": {"passengers": 5, "pct": 8, "crowd": "NORMAL", "capacity": 60},
            "cabin_occupancy": {
                "bus_id": "PROTO-001", "occupancy_count": 29, "occupancy_percentage": 72,
                "crowding_level": "MODERATE", "confidence": None, "source": "cabin_camera",
            },
        }
        bus = adapt_bus_state(node)
        assert bus["cabin_occupancy"]["occupancy_count"] == 29
        assert bus["cabin_occupancy"]["crowding_level"] == "MODERATE"