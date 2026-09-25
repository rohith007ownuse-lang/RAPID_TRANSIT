"""
camera_manager.py - manages the 3-slot camera architecture.

DRIVER (active webcam), CABIN (planned), ROAD (planned). Slot availability is
driven by config/system_config.json -> cameras.*. The manager exposes a
uniform API so the rest of the bus node doesn't care which slots are live.
"""

from typing import Dict, List

from bus_node.cameras.driver_camera import DriverCamera
from bus_node.cameras.cabin_camera import CabinCamera
from bus_node.cameras.road_camera import RoadCamera
from bus_node.utils.config_manager import get_config

SLOTS = ("DRIVER", "CABIN", "ROAD")


class CameraManager:
    """Owns all camera slots and gives read access to any of them."""

    def __init__(self, cameras_config: Dict | None = None):
        cfg = cameras_config
        if cfg is None:
            cfg = get_config().get("cameras", {}) or {}

        def _res(cam_cfg):
            res = cam_cfg.get("resolution", [640, 480])
            return int(res[0]), int(res[1])

        driver_cfg = cfg.get("driver", {})
        cabin_cfg = cfg.get("cabin", {})
        road_cfg = cfg.get("road", {})

        w, h = _res(driver_cfg)
        self.cameras: Dict[str, object] = {
            "DRIVER": DriverCamera(
                index=int(driver_cfg.get("index", 0)), width=w, height=h
            ),
            "CABIN": CabinCamera(active=bool(cabin_cfg.get("active", False))),
            "ROAD": RoadCamera(active=bool(road_cfg.get("active", False))),
        }

    def slots(self) -> List[str]:
        return list(SLOTS)

    def start_slot(self, slot: str) -> bool:
        """Start one slot (webcam open for DRIVER; no-op placeholders)."""
        return self.cameras[slot].start()

    def start_active(self) -> int:
        """Start every slot; returns how many opened real captures."""
        return sum(1 for s in SLOTS if self.start_slot(s))

    def get_frame(self, slot: str) -> tuple[bool, object]:
        """Read one frame from a slot: (ok, frame). placeholders -> (False, label)."""
        return self.cameras[slot].read()

    def release_all(self) -> None:
        for cam in self.cameras.values():
            cam.release()

    def status_matrix(self) -> List[dict]:
        """Per-slot status for logging / bus-state / future Control Centre payload."""
        return [self.cameras[s].info() for s in SLOTS]

    def summary(self) -> str:
        parts = [f"{c['slot']}={c['status']}" for c in self.status_matrix()]
        return " | ".join(parts)