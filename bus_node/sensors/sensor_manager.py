"""
sensor_manager.py - orchestrates all simulated sensor interfaces.

Builds GPS / IMU / load-cell / microphone sensors from config, provides
init_all()/read_all()/status_matrix(), and a `--demo` headless smoke runner.
All readings are simulation-labeled (never presented as real telemetry).
"""

import time
from typing import Dict, List

from bus_node.sensors import (
    GPSSensor,
    IMUSensor,
    LoadCellSensor,
    MicrophoneSensor,
)
from bus_node.utils.config_manager import get_config

SENSOR_KEYS = ("gps", "imu", "load_cell", "microphone")


class SensorManager:
    """Owns every bus-node sensor and reads them uniformly."""

    def __init__(self, sensors_config: Dict | None = None):
        cfg = sensors_config
        if cfg is None:
            cfg = get_config().get("sensors", {}) or {}

        def _sim(key: str, default: bool = True) -> bool:
            return bool(cfg.get(key, {}).get("simulation", default))

        gps_cfg = cfg.get("gps", {})
        imu_cfg = cfg.get("imu", {})
        load_cfg = cfg.get("load_cell", {})
        mic_cfg = cfg.get("microphone", {})
        bus_cfg = get_config().get("bus", {})

        self.sensors = {
            "gps": GPSSensor(
                simulation=_sim("gps"),
                home=(gps_cfg.get("home_latitude", 13.0827),
                      gps_cfg.get("home_longitude", 80.2747)),
            ),
            "imu": IMUSensor(
                simulation=_sim("imu"),
                impact_g_threshold=float(imu_cfg.get("impact_g_threshold", 3.0)),
                hard_decel_g_threshold=float(imu_cfg.get("hard_decel_g_threshold", 0.5)),
            ),
            "load_cell": LoadCellSensor(
                simulation=_sim("load_cell"),
                tare_weight_kg=int(bus_cfg.get("tare_weight_kg", 11000)),
                payload_limit_kg=int(bus_cfg.get("payload_limit_kg", 6000)),
                warning_threshold_kg=int(bus_cfg.get("overload_warning_threshold_kg", 5400)),
            ),
            "microphone": MicrophoneSensor(
                simulation=_sim("microphone"),
                siren_confidence_threshold=float(
                    mic_cfg.get("siren_confidence_threshold", 0.7)),
            ),
        }

    def init_all(self) -> int:
        """Initialize every sensor; returns count successfully initialized."""
        return sum(1 for s in self.sensors.values() if s.init())

    def read_all(self) -> Dict[str, Dict]:
        return {key: self.sensors[key].read() for key in SENSOR_KEYS}

    def read(self, name: str) -> Dict | None:
        return self.sensors[name].read()

    def enable(self, name: str) -> None:
        self.sensors[name].enable()

    def disable(self, name: str) -> None:
        self.sensors[name].disable()

    def get_status_store(self) -> List[Dict]:
        return [self.sensors[key].get_status() for key in SENSOR_KEYS]

    def summary(self) -> str:
        parts = [
            f"{s['sensor']}={s['status']}" + (":SIM" if s["simulation"] else "")
            for s in self.get_status_store()
        ]
        return " | ".join(parts)


def demo(ticks: int = 60, dt: float = 0.1) -> None:
    """Headless smoke runner: print labeled readings for each sensor."""
    print("Starting sensor demo (all values are [SIMULATION]).")
    mgr = SensorManager()
    print("Init sensors:", mgr.init_all())
    print("Status:", mgr.summary())
    print("-" * 78)
    for i in range(ticks):
        readings = mgr.read_all()
        g = readings["gps"] and readings["gps"]["source"] + " " + \
            f"lat={readings['gps']['latitude']} lon={readings['gps']['longitude']} " \
            f"v={readings['gps']['speed_kmh']}km/h hdg={readings['gps']['heading_deg']}"
        imu = readings["imu"] and (
            f"a_x={readings['imu']['accel_x_g']}g a_y={readings['imu']['accel_y_g']}g "
            f"a_z={readings['imu']['accel_z_g']}g impact={readings['imu']['impact']}")
        load = readings["load_cell"] and (
            f"gvw={readings['load_cell']['gvw_kg']}kg "
            f"payload={readings['load_cell']['payload_kg']}kg "
            f"({readings['load_cell']['load_pct']}%) {readings['load_cell']['status']}")
        mic = readings["microphone"] and (
            f"siren={readings['microphone']['siren_detected']} "
            f"conf={readings['microphone']['siren_confidence']} "
            f"{readings['microphone']['sound_level_db']}dB")
        print(f"[SIM] {g}\n     {imu}\n     {load}\n     {mic}")
        time.sleep(dt)
    print("-" * 78)
    print("Final status:", mgr.summary())


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Simulated sensor demo")
    p.add_argument("--ticks", type=int, default=60)
    p.add_argument("--dt", type=float, default=0.1)
    args = p.parse_args()
    demo(ticks=args.ticks, dt=args.dt)