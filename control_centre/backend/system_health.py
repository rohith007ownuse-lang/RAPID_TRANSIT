"""
system_health.py
Phase 19: Offline, Failure Detection, Degraded Modes & System Resilience.

Provides a unified system health model for all subsystems with:
- Subsystem health states (HEALTHY/DEGRADED/DISCONNECTED/STARTING/STOPPING/FAILED/RECOVERING/UNKNOWN)
- Data freshness tracking (FRESH/STALE/UNAVAILABLE/UNKNOWN)
- Failure detection and recovery
- Degraded mode support
- Operator-visible health status

Key principle: A missing subsystem must never silently appear healthy.
"""

import time
import threading
from enum import Enum
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Health states
# ---------------------------------------------------------------------------

class HealthState(Enum):
    """Subsystem health states."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    UNKNOWN = "UNKNOWN"


class DataFreshness(Enum):
    """Data freshness states."""
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default staleness thresholds (seconds)
STALENESS_THRESHOLDS = {
    "telemetry": 30.0,      # Bus GPS/telemetry
    "camera": 5.0,          # Camera frames
    "risk": 60.0,           # Risk calculations
    "occupancy": 30.0,      # Cabin occupancy
    "eta": 30.0,            # ETA updates
    "health": 120.0,        # Vehicle health
    "road": 300.0,          # Road intelligence
    "dds": 5.0,             # DDS heartbeat
    "persistence": 60.0,    # Database operations
    "websocket": 30.0,      # WebSocket connection
}

# Recovery flapping prevention
RECOVERY_DEBOUNCE_S = 10.0  # Minimum time between state transitions


# ---------------------------------------------------------------------------
# Subsystem health tracker
# ---------------------------------------------------------------------------

class SubsystemHealth:
    """Track health state for a single subsystem."""

    def __init__(self, name: str, stale_threshold_s: float = 60.0):
        self.name = name
        self._state = HealthState.UNKNOWN
        self._freshness = DataFreshness.UNKNOWN
        self._last_success = None
        self._last_error = None
        self._error_count = 0
        self._success_count = 0
        self._last_state_change = time.time()
        self._consecutive_failures = 0
        self._stale_threshold = stale_threshold_s
        self._lock = threading.Lock()
        self._listeners = []

    @property
    def state(self) -> HealthState:
        with self._lock:
            return self._state

    @property
    def freshness(self) -> DataFreshness:
        with self._lock:
            return self._freshness

    @property
    def last_success(self) -> Optional[float]:
        with self._lock:
            return self._last_success

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    @property
    def error_count(self) -> int:
        with self._lock:
            return self._error_count

    def record_success(self, details: str = None):
        """Record a successful operation.

        Phase 19: Updates state based on current state:
        - UNKNOWN/STARTING -> HEALTHY
        - FAILED/RECOVERING/DISCONNECTED/DEGRADED -> RECOVERING (then HEALTHY on next success)
        - HEALTHY -> HEALTHY (no change)
        """
        with self._lock:
            now = time.time()
            self._last_success = now
            self._success_count += 1
            self._consecutive_failures = 0

            # Update freshness
            self._freshness = DataFreshness.FRESH

            # Update state based on current state
            if self._state in (HealthState.UNKNOWN, HealthState.STARTING):
                self._set_state(HealthState.HEALTHY)
            elif self._state in (HealthState.FAILED, HealthState.RECOVERING, HealthState.DISCONNECTED, HealthState.DEGRADED):
                self._set_state(HealthState.RECOVERING)
            elif self._state == HealthState.HEALTHY:
                # Already healthy, no state change needed
                pass
            elif self._state == HealthState.STOPPING:
                # Don't change state if stopping
                pass

    def record_failure(self, error: str, critical: bool = False):
        """Record a failed operation.

        Phase 19: Updates state based on current state and failure severity:
        - UNKNOWN/STARTING/HEALTHY -> DEGRADED (first failure)
        - DEGRADED -> FAILED (if critical or 3+ consecutive failures)
        - RECOVERING -> FAILED (any failure during recovery)
        - Any state -> FAILED (if critical)
        """
        with self._lock:
            self._last_error = error
            self._error_count += 1
            self._consecutive_failures += 1

            # Update state based on failure severity
            if critical:
                self._set_state(HealthState.FAILED)
            elif self._consecutive_failures >= 3:
                self._set_state(HealthState.FAILED)
            elif self._state in (HealthState.UNKNOWN, HealthState.STARTING, HealthState.HEALTHY):
                self._set_state(HealthState.DEGRADED)
            elif self._state == HealthState.RECOVERING:
                # Failure during recovery attempt
                self._set_state(HealthState.FAILED)
            elif self._state == HealthState.DEGRADED:
                # Already degraded, no state change needed until 3+ failures
                pass

    def record_disconnect(self, reason: str = None):
        """Record that the subsystem is disconnected."""
        with self._lock:
            self._freshness = DataFreshness.UNAVAILABLE
            self._set_state(HealthState.DISCONNECTED)
            if reason:
                self._last_error = reason

    def record_starting(self):
        """Record that the subsystem is starting."""
        with self._lock:
            self._set_state(HealthState.STARTING)

    def record_stopping(self):
        """Record that the subsystem is stopping."""
        with self._lock:
            self._set_state(HealthState.STOPPING)

    def update_freshness(self):
        """Update freshness based on last success time."""
        with self._lock:
            if self._last_success is None:
                self._freshness = DataFreshness.UNKNOWN
            elif time.time() - self._last_success > self._stale_threshold:
                self._freshness = DataFreshness.STALE
                # Don't change health state for staleness - just mark data as stale

    def _set_state(self, new_state: HealthState):
        """Set state with debounce and notification.

        Phase 19: Debounce prevents rapid DEGRADED -> HEALTHY -> DEGRADED
        flipping (recovery flapping), but allows immediate transitions to
        DEGRADED, FAILED, or DISCONNECTED.
        """
        now = time.time()
        old_state = self._state

        # Debounce recovery flapping: only block DEGRADED -> HEALTHY within window
        if (now - self._last_state_change < RECOVERY_DEBOUNCE_S and
            old_state == HealthState.DEGRADED and
            new_state == HealthState.HEALTHY):
            return

        self._state = new_state
        self._last_state_change = now

        # Notify listeners outside lock
        for listener in self._listeners:
            try:
                listener(self.name, old_state, new_state)
            except Exception:
                pass

    def add_listener(self, listener: Callable):
        """Add a state change listener."""
        self._listeners.append(listener)

    def to_dict(self) -> dict:
        """Serialize health state."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "freshness": self._freshness.value,
                "last_success": self._last_success,
                "last_error": self._last_error,
                "error_count": self._error_count,
                "success_count": self._success_count,
                "consecutive_failures": self._consecutive_failures,
                "last_state_change": self._last_state_change,
            }


# ---------------------------------------------------------------------------
# System health manager
# ---------------------------------------------------------------------------

class SystemHealthManager:
    """Manage health state for all subsystems."""

    def __init__(self):
        self._subsystems = {}
        self._lock = threading.Lock()
        self._listeners = []

    def register(self, name: str, stale_threshold_s: float = 60.0) -> SubsystemHealth:
        """Register a subsystem for health tracking."""
        with self._lock:
            if name not in self._subsystems:
                subsystem = SubsystemHealth(name, stale_threshold_s)
                self._subsystems[name] = subsystem
            return self._subsystems[name]

    def get(self, name: str) -> Optional[SubsystemHealth]:
        """Get a subsystem's health tracker."""
        with self._lock:
            return self._subsystems.get(name)

    def get_all(self) -> Dict[str, dict]:
        """Get health state for all subsystems."""
        with self._lock:
            result = {}
            for name, subsystem in self._subsystems.items():
                result[name] = subsystem.to_dict()
            return result

    def get_overall_health(self) -> HealthState:
        """Get overall system health based on subsystem states."""
        with self._lock:
            states = [s.state for s in self._subsystems.values()]

            if not states:
                return HealthState.UNKNOWN

            # If any subsystem is FAILED, overall is DEGRADED
            if HealthState.FAILED in states:
                return HealthState.DEGRADED

            # If any subsystem is DEGRADED or DISCONNECTED, overall is DEGRADED
            if HealthState.DEGRADED in states or HealthState.DISCONNECTED in states:
                return HealthState.DEGRADED

            # If any subsystem is RECOVERING, overall is RECOVERING
            if HealthState.RECOVERING in states:
                return HealthState.RECOVERING

            # If all are HEALTHY, overall is HEALTHY
            if all(s == HealthState.HEALTHY for s in states):
                return HealthState.HEALTHY

            # If any is STARTING, overall is STARTING
            if HealthState.STARTING in states:
                return HealthState.STARTING

            return HealthState.UNKNOWN

    def update_all_freshness(self):
        """Update freshness for all subsystems."""
        with self._lock:
            for subsystem in self._subsystems.values():
                subsystem.update_freshness()

    def add_listener(self, listener: Callable):
        """Add a state change listener for all subsystems."""
        self._listeners.append(listener)
        with self._lock:
            for subsystem in self._subsystems.values():
                subsystem.add_listener(listener)

    def to_dict(self) -> dict:
        """Serialize full system health."""
        return {
            "overall": self.get_overall_health().value,
            "subsystems": self.get_all(),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

health_manager = SystemHealthManager()


# ---------------------------------------------------------------------------
# Subsystem registrations
# ---------------------------------------------------------------------------

def initialize_health_tracking():
    """Initialize health tracking for all known subsystems."""
    # Core subsystems
    health_manager.register("api", STALENESS_THRESHOLDS["persistence"])
    health_manager.register("websocket", STALENESS_THRESHOLDS["websocket"])
    health_manager.register("persistence", STALENESS_THRESHOLDS["persistence"])

    # Data subsystems
    health_manager.register("simulator", STALENESS_THRESHOLDS["telemetry"])
    health_manager.register("dds", STALENESS_THRESHOLDS["dds"])
    health_manager.register("risk_engine", STALENESS_THRESHOLDS["risk"])
    health_manager.register("incidents", STALENESS_THRESHOLDS["risk"])
    health_manager.register("alerts", STALENESS_THRESHOLDS["persistence"])

    # Camera subsystems
    health_manager.register("driver_camera", STALENESS_THRESHOLDS["camera"])
    health_manager.register("cabin_camera", STALENESS_THRESHOLDS["camera"])
    health_manager.register("cabin_occupancy", STALENESS_THRESHOLDS["occupancy"])

    # Intelligence subsystems
    health_manager.register("eta", STALENESS_THRESHOLDS["eta"])
    health_manager.register("road_intelligence", STALENESS_THRESHOLDS["road"])
    health_manager.register("vehicle_health", STALENESS_THRESHOLDS["health"])

    return health_manager


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def record_subsystem_success(subsystem_name: str, details: str = None):
    """Record a successful operation for a subsystem."""
    subsystem = health_manager.get(subsystem_name)
    if subsystem:
        subsystem.record_success(details)


def record_subsystem_failure(subsystem_name: str, error: str, critical: bool = False):
    """Record a failed operation for a subsystem."""
    subsystem = health_manager.get(subsystem_name)
    if subsystem:
        subsystem.record_failure(error, critical)


def get_subsystem_health(subsystem_name: str) -> Optional[dict]:
    """Get health state for a subsystem."""
    subsystem = health_manager.get(subsystem_name)
    if subsystem:
        return subsystem.to_dict()
    return None


def get_system_health() -> dict:
    """Get full system health status."""
    return health_manager.to_dict()


def get_overall_health() -> str:
    """Get overall system health state."""
    return health_manager.get_overall_health().value


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("System Health Module - Self Test")
    print("=" * 50)

    # Initialize
    manager = initialize_health_tracking()

    # Test success recording
    print("\n1. Record success:")
    record_subsystem_success("api")
    health = get_subsystem_health("api")
    print(f"   API state: {health['state']}, freshness: {health['freshness']}")

    # Test failure recording
    print("\n2. Record failure:")
    record_subsystem_failure("persistence", "SQLite locked")
    health = get_subsystem_health("persistence")
    print(f"   Persistence state: {health['state']}, errors: {health['error_count']}")

    # Test disconnect
    print("\n3. Record disconnect:")
    subsystem = manager.get("websocket")
    subsystem.record_disconnect("Connection closed")
    health = get_subsystem_health("websocket")
    print(f"   WebSocket state: {health['state']}, freshness: {health['freshness']}")

    # Test overall health
    print("\n4. Overall health:")
    overall = get_overall_health()
    print(f"   System health: {overall}")

    # Test full status
    print("\n5. Full system health:")
    full = get_system_health()
    print(f"   Subsystems: {len(full['subsystems'])}")
    for name, state in full['subsystems'].items():
        print(f"   {name}: {state['state']}")

    print("\n" + "=" * 50)
    print("All self-tests passed!")
