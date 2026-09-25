"""
test_phase19_system_health.py
Phase 19: Tests for system health, failure detection, degraded modes & resilience.
"""

import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from system_health import (
    HealthState,
    DataFreshness,
    SubsystemHealth,
    SystemHealthManager,
    health_manager,
    initialize_health_tracking,
    record_subsystem_success,
    record_subsystem_failure,
    get_subsystem_health,
    get_system_health,
    get_overall_health,
    STALENESS_THRESHOLDS,
    RECOVERY_DEBOUNCE_S,
)


# ---------------------------------------------------------------------------
# SubsystemHealth tests
# ---------------------------------------------------------------------------

class TestSubsystemHealth:
    def test_initial_state(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        assert subsystem.state == HealthState.UNKNOWN
        assert subsystem.freshness == DataFreshness.UNKNOWN
        assert subsystem.last_success is None
        assert subsystem.last_error is None
        assert subsystem.error_count == 0

    def test_record_success(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success("Operation completed")
        assert subsystem.state == HealthState.HEALTHY
        assert subsystem.freshness == DataFreshness.FRESH
        assert subsystem.last_success is not None
        assert subsystem.error_count == 0

    def test_record_failure(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success()
        subsystem.record_failure("Connection timeout")
        assert subsystem.state == HealthState.DEGRADED
        assert subsystem.error_count == 1
        assert subsystem.last_error == "Connection timeout"

    def test_record_critical_failure(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success()
        subsystem.record_failure("Fatal error", critical=True)
        assert subsystem.state == HealthState.FAILED

    def test_consecutive_failures(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success()
        # 3 consecutive failures should mark as FAILED
        subsystem.record_failure("Error 1")
        assert subsystem.state == HealthState.DEGRADED
        subsystem.record_failure("Error 2")
        assert subsystem.state == HealthState.DEGRADED
        subsystem.record_failure("Error 3")
        assert subsystem.state == HealthState.FAILED

    def test_record_disconnect(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success()
        subsystem.record_disconnect("Connection closed")
        assert subsystem.state == HealthState.DISCONNECTED
        assert subsystem.freshness == DataFreshness.UNAVAILABLE

    def test_record_starting(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_starting()
        assert subsystem.state == HealthState.STARTING

    def test_record_stopping(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success()
        subsystem.record_stopping()
        assert subsystem.state == HealthState.STOPPING

    def test_recovery_from_failure(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success()
        subsystem.record_failure("Error")
        assert subsystem.state == HealthState.DEGRADED
        # Recovery should transition to RECOVERING
        subsystem.record_success()
        assert subsystem.state == HealthState.RECOVERING

    def test_update_freshness_stale(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=0.1)
        subsystem.record_success()
        assert subsystem.freshness == DataFreshness.FRESH
        time.sleep(0.15)
        subsystem.update_freshness()
        assert subsystem.freshness == DataFreshness.STALE

    def test_to_dict(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success()
        state = subsystem.to_dict()
        assert state["name"] == "test_subsystem"
        assert state["state"] == HealthState.HEALTHY.value
        assert state["freshness"] == DataFreshness.FRESH.value
        assert "last_success" in state
        assert "error_count" in state

    def test_listener_notification(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        notifications = []
        subsystem.add_listener(lambda name, old, new: notifications.append((name, old, new)))
        subsystem.record_starting()
        subsystem.record_success()
        assert len(notifications) == 2
        assert notifications[0][1] == HealthState.UNKNOWN
        assert notifications[0][2] == HealthState.STARTING
        assert notifications[1][1] == HealthState.STARTING
        assert notifications[1][2] == HealthState.HEALTHY

    def test_thread_safety(self):
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        def record_ops():
            for _ in range(10):
                subsystem.record_success()
                subsystem.record_failure("error")

        threads = [threading.Thread(target=record_ops) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Should not crash or deadlock
        assert subsystem.error_count == 50


# ---------------------------------------------------------------------------
# SystemHealthManager tests
# ---------------------------------------------------------------------------

class TestSystemHealthManager:
    def test_register_subsystem(self):
        manager = SystemHealthManager()
        subsystem = manager.register("test_subsystem", stale_threshold_s=60)
        assert subsystem is not None
        assert subsystem.name == "test_subsystem"

    def test_get_subsystem(self):
        manager = SystemHealthManager()
        manager.register("test_subsystem")
        subsystem = manager.get("test_subsystem")
        assert subsystem is not None
        assert subsystem.name == "test_subsystem"

    def test_get_nonexistent_subsystem(self):
        manager = SystemHealthManager()
        assert manager.get("nonexistent") is None

    def test_get_all(self):
        manager = SystemHealthManager()
        manager.register("subsystem1")
        manager.register("subsystem2")
        all_health = manager.get_all()
        assert "subsystem1" in all_health
        assert "subsystem2" in all_health

    def test_overall_health_healthy(self):
        manager = SystemHealthManager()
        sub1 = manager.register("sub1")
        sub2 = manager.register("sub2")
        sub1.record_success()
        sub2.record_success()
        assert manager.get_overall_health() == HealthState.HEALTHY

    def test_overall_health_degraded(self):
        manager = SystemHealthManager()
        sub1 = manager.register("sub1")
        sub2 = manager.register("sub2")
        sub1.record_success()
        sub2.record_failure("Error")
        assert manager.get_overall_health() == HealthState.DEGRADED

    def test_overall_health_unknown(self):
        manager = SystemHealthManager()
        assert manager.get_overall_health() == HealthState.UNKNOWN

    def test_update_all_freshness(self):
        manager = SystemHealthManager()
        sub = manager.register("sub", stale_threshold_s=0.1)
        sub.record_success()
        time.sleep(0.15)
        manager.update_all_freshness()
        assert sub.freshness == DataFreshness.STALE

    def test_to_dict(self):
        manager = SystemHealthManager()
        manager.register("sub1")
        state = manager.to_dict()
        assert "overall" in state
        assert "subsystems" in state
        assert "timestamp" in state


# ---------------------------------------------------------------------------
# Convenience function tests
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_record_subsystem_success(self):
        manager = SystemHealthManager()
        manager.register("test_subsystem")
        # Patch the global health_manager
        import system_health
        original_manager = system_health.health_manager
        system_health.health_manager = manager
        try:
            record_subsystem_success("test_subsystem")
            health = get_subsystem_health("test_subsystem")
            assert health["state"] == HealthState.HEALTHY.value
        finally:
            system_health.health_manager = original_manager

    def test_record_subsystem_failure(self):
        manager = SystemHealthManager()
        manager.register("test_subsystem")
        import system_health
        original_manager = system_health.health_manager
        system_health.health_manager = manager
        try:
            record_subsystem_failure("test_subsystem", "Test error")
            health = get_subsystem_health("test_subsystem")
            assert health["state"] == HealthState.DEGRADED.value
        finally:
            system_health.health_manager = original_manager

    def test_get_subsystem_health(self):
        manager = SystemHealthManager()
        manager.register("test_subsystem")
        import system_health
        original_manager = system_health.health_manager
        system_health.health_manager = manager
        try:
            health = get_subsystem_health("test_subsystem")
            assert health is not None
            assert health["name"] == "test_subsystem"
        finally:
            system_health.health_manager = original_manager

    def test_get_system_health(self):
        manager = SystemHealthManager()
        manager.register("test_subsystem")
        import system_health
        original_manager = system_health.health_manager
        system_health.health_manager = manager
        try:
            health = get_system_health()
            assert "overall" in health
            assert "subsystems" in health
        finally:
            system_health.health_manager = original_manager


# ---------------------------------------------------------------------------
# Initialize health tracking tests
# ---------------------------------------------------------------------------

class TestInitializeHealthTracking:
    def test_initialize(self):
        manager = initialize_health_tracking()
        assert manager is not None
        # Should have registered core subsystems
        assert manager.get("api") is not None
        assert manager.get("websocket") is not None
        assert manager.get("persistence") is not None
        assert manager.get("simulator") is not None
        assert manager.get("dds") is not None
        assert manager.get("risk_engine") is not None
        assert manager.get("driver_camera") is not None
        assert manager.get("cabin_camera") is not None
        assert manager.get("cabin_occupancy") is not None

    def test_staleness_thresholds(self):
        assert STALENESS_THRESHOLDS["telemetry"] == 30.0
        assert STALENESS_THRESHOLDS["camera"] == 5.0
        assert STALENESS_THRESHOLDS["risk"] == 60.0
        assert STALENESS_THRESHOLDS["persistence"] == 60.0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestPhase19Integration:
    def test_full_lifecycle(self):
        """Test a full subsystem lifecycle: starting -> healthy -> degraded -> failed -> recovery."""
        manager = SystemHealthManager()
        subsystem = manager.register("test_subsystem", stale_threshold_s=60)

        # Starting
        subsystem.record_starting()
        assert subsystem.state == HealthState.STARTING

        # Healthy
        subsystem.record_success()
        assert subsystem.state == HealthState.HEALTHY
        assert subsystem.freshness == DataFreshness.FRESH

        # Degraded
        subsystem.record_failure("Minor error")
        assert subsystem.state == HealthState.DEGRADED

        # Failed
        subsystem.record_failure("Major error", critical=True)
        assert subsystem.state == HealthState.FAILED

        # Recovery
        subsystem.record_success()
        assert subsystem.state == HealthState.RECOVERING

    def test_multiple_subsystems_independent(self):
        """Test that multiple subsystems are tracked independently."""
        manager = SystemHealthManager()
        sub1 = manager.register("sub1")
        sub2 = manager.register("sub2")

        sub1.record_success()
        sub2.record_failure("Error")

        assert sub1.state == HealthState.HEALTHY
        assert sub2.state == HealthState.DEGRADED
        assert manager.get_overall_health() == HealthState.DEGRADED

    def test_health_serialization(self):
        """Test that health state can be serialized to JSON."""
        import json
        manager = SystemHealthManager()
        manager.register("sub1").record_success()
        manager.register("sub2").record_failure("Error")

        health_dict = manager.to_dict()
        # Should be JSON serializable
        json_str = json.dumps(health_dict)
        assert json_str is not None

    def test_debounce_recovery_flapping(self):
        """Test that rapid DEGRADED -> HEALTHY -> DEGRADED flipping is debounced."""
        subsystem = SubsystemHealth("test_subsystem", stale_threshold_s=60)
        subsystem.record_success()  # UNKNOWN -> HEALTHY

        # First failure: HEALTHY -> DEGRADED
        subsystem.record_failure("Error 1")
        assert subsystem.state == HealthState.DEGRADED

        # Recovery attempt: DEGRADED -> RECOVERING (allowed)
        subsystem.record_success()
        assert subsystem.state == HealthState.RECOVERING

        # Another failure should be allowed (not debounced)
        subsystem.record_failure("Error 2")
        assert subsystem.state == HealthState.FAILED


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_health_states(self):
        assert HealthState.HEALTHY.value == "HEALTHY"
        assert HealthState.DEGRADED.value == "DEGRADED"
        assert HealthState.DISCONNECTED.value == "DISCONNECTED"
        assert HealthState.STARTING.value == "STARTING"
        assert HealthState.STOPPING.value == "STOPPING"
        assert HealthState.FAILED.value == "FAILED"
        assert HealthState.RECOVERING.value == "RECOVERING"
        assert HealthState.UNKNOWN.value == "UNKNOWN"

    def test_freshness_states(self):
        assert DataFreshness.FRESH.value == "FRESH"
        assert DataFreshness.STALE.value == "STALE"
        assert DataFreshness.UNAVAILABLE.value == "UNAVAILABLE"
        assert DataFreshness.UNKNOWN.value == "UNKNOWN"

    def test_recovery_debounce(self):
        assert RECOVERY_DEBOUNCE_S == 10.0
