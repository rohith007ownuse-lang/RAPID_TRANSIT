"""
feature_toggles.py
Manages feature enable/disable states that affect running system behavior.

Unlike localStorage (which only affects the UI), this module actually controls
whether features like audio alerts, auto-braking, etc. are active.
"""

import json
import os
import threading
from typing import Dict, Optional

# Persistent storage file
TOGGLES_FILE = os.path.join(os.path.dirname(__file__), "feature_toggles.json")

# Default feature states
DEFAULT_TOGGLES = {
    # Camera & AI — all ON: driver = DDS+face only, cabin = people+fire/smoke,
    # road = pothole only (per-camera roles enforced in camera_manager/occupancy)
    "camera_driver": True,
    "camera_cabin": True,
    "camera_road": True,
    "ai_driver_dds": True,
    "ai_pothole": True,
    "ai_cabin": True,
    "camera_websocket": True,

    # Sensors & Hardware
    "sensor_gps": True,
    "sensor_imu": True,
    "sensor_load": True,
    "sensor_mic": True,
    "arduino_control": True,
    "serial_comm": True,

    # Safety Features
    "auto_braking": True,
    "audio_alerts": True,  # ON: DDS 2.3 s eye-closure / face-lost CRITICAL alarm sounds
    "crash_detection": True,
    "overload_alert": True,

    # Communication
    "ws_alerts": True,
    "intercom": True,
    "bus_node_ws": True,

    # Fleet Simulation
    "fleet_sim": True,
    "event_fusion": True,
    "risk_engine": True,
    "eta_prediction": True,

    # Emergency Services
    "emergency_data": True,
    "emergency_map": True,
    "emergency_response": True,

    # Analytics
    "analytics_dashboard": True,
    "predictive_health": True,
    "demand_forecast": True,

    # Privacy
    "privacy_mode": True,  # Default ON: camera frames processed and discarded
}


class FeatureToggleManager:
    """Thread-safe feature toggle manager with persistence."""

    def __init__(self):
        self._lock = threading.Lock()
        self._toggles: Dict[str, bool] = {}
        self._load()

    def _load(self):
        """Load toggles from file or use defaults."""
        try:
            if os.path.exists(TOGGLES_FILE):
                with open(TOGGLES_FILE, "r") as f:
                    saved = json.load(f)
                    # Merge with defaults to handle new features
                    self._toggles = {**DEFAULT_TOGGLES, **saved}
                print(f"[feature_toggles] Loaded {len(self._toggles)} toggles from file")
            else:
                self._toggles = dict(DEFAULT_TOGGLES)
                self._save()
                print(f"[feature_toggles] Created default toggles ({len(self._toggles)} features)")
        except Exception as e:
            print(f"[feature_toggles] Error loading toggles: {e}")
            self._toggles = dict(DEFAULT_TOGGLES)

    def _save(self):
        """Save toggles to file."""
        try:
            with open(TOGGLES_FILE, "w") as f:
                json.dump(self._toggles, f, indent=2)
        except Exception as e:
            print(f"[feature_toggles] Error saving toggles: {e}")

    def get_all(self) -> Dict[str, bool]:
        """Get all toggle states."""
        with self._lock:
            return dict(self._toggles)

    def get(self, key: str) -> bool:
        """Get a single toggle state."""
        with self._lock:
            return self._toggles.get(key, DEFAULT_TOGGLES.get(key, False))

    def set(self, key: str, enabled: bool) -> bool:
        """Set a single toggle state. Returns True if changed."""
        changed = False
        with self._lock:
            old = self._toggles.get(key)
            self._toggles[key] = enabled
            self._save()
            if old != enabled:
                changed = True
                print(f"[feature_toggles] {key}: {old} -> {enabled}")
        # Handlers run OUTSIDE the lock: _on_change paths (e.g. DDS start)
        # re-read toggles through feature_toggles.get(), which acquires the
        # same lock — calling them while holding it deadlocks.
        if changed:
            self._on_change(key, enabled)
        return changed

    def update(self, toggles: Dict[str, bool]) -> int:
        """Update multiple toggles. Returns count of changes."""
        changed_keys = []
        with self._lock:
            for key, enabled in toggles.items():
                old = self._toggles.get(key)
                self._toggles[key] = enabled
                if old != enabled:
                    changed_keys.append((key, enabled))
            self._save()
        if changed_keys:
            print(f"[feature_toggles] Updated {len(changed_keys)} toggles")
            for key, enabled in changed_keys:
                self._on_change(key, enabled)
        return len(changed_keys)

    def _on_change(self, key: str, enabled: bool):
        """Handle toggle changes that affect running systems."""
        # Audio alerts
        if key == "audio_alerts":
            try:
                import sys
                import os
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
                from bus_node.utils.alert_manager import AlertManager
                # Set the CLASS variable (affects ALL instances)
                AlertManager.muted = not enabled
                print(f"[feature_toggles] Audio alerts {'ENABLED' if enabled else 'DISABLED'} (AlertManager.muted={AlertManager.muted})")
                # Also update any existing DDS detector instance
                try:
                    from ai.driver.driver_drowsiness import driver_detector
                    if driver_detector._audio is not None:
                        driver_detector._audio.muted = AlertManager.muted
                        print(f"[feature_toggles] Updated DDS AlertManager instance muted={AlertManager.muted}")
                except Exception:
                    pass
                # Play a test sound if enabling
                if enabled:
                    try:
                        am = AlertManager()
                        am.update("WARNING")
                        import threading
                        def stop_test():
                            import time
                            time.sleep(2)
                            am.stop()
                        threading.Thread(target=stop_test, daemon=True).start()
                        print("[feature_toggles] Test sound playing...")
                    except Exception as e:
                        print(f"[feature_toggles] Test sound failed: {e}")
            except ImportError as e:
                print(f"[feature_toggles] Could not import AlertManager: {e}")

        # Driver DDS engine: the toggle genuinely starts/stops monitoring so
        # enabling it makes the drowsiness / face-lost 2.3 s alarm actually run
        if key == "ai_driver_dds":
            try:
                from ai.driver.driver_drowsiness import driver_detector
                if enabled:
                    ok, msg = driver_detector.start_monitoring()
                    print(f"[feature_toggles] DDS engine started: {msg}")
                else:
                    driver_detector.stop_monitoring()
                    print("[feature_toggles] DDS engine stopped")
            except Exception as e:
                print(f"[feature_toggles] DDS toggle error: {e}")

        # Camera driver
        if key == "camera_driver":
            try:
                from ai.camera_manager import camera_manager
                if enabled:
                    camera_manager.open_shared_camera()
                    # Also start capture in test mode
                    camera_manager.set_single_camera_test_mode("driver")
                    print("[feature_toggles] Driver camera ENABLED and started")
                else:
                    camera_manager.stop()
                    print("[feature_toggles] Driver camera DISABLED")
            except Exception as e:
                print(f"[feature_toggles] Camera toggle error: {e}")


# Singleton
feature_toggles = FeatureToggleManager()
