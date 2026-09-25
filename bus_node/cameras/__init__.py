"""
cameras package - 3-slot camera architecture.

Slots:
  DRIVER  - real webcam (active by default)
  CABIN   - placeholder (planned: cabin safety AI)
  ROAD    - placeholder (planned: road-condition AI)
"""

from bus_node.cameras.camera_manager import CameraManager, SLOTS
from bus_node.cameras.driver_camera import DriverCamera
from bus_node.cameras.cabin_camera import CabinCamera
from bus_node.cameras.road_camera import RoadCamera

__all__ = ["CameraManager", "SLOTS", "DriverCamera", "CabinCamera", "RoadCamera"]