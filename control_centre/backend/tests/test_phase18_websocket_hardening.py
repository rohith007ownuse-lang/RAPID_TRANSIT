"""
test_phase18_websocket_hardening.py
Phase 18: Tests for WebSocket reliability, reconnection & hardening.
"""

import json
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from websocket_hardening import (
    ConnectionState,
    MessagePriority,
    MessageType,
    MessageDeduplicator,
    EventCoalescer,
    ConnectionStateManager,
    MessagePriorityQueue,
    ServerConnectionTracker,
    ReconnectionManager,
    StateResynchronizer,
    WebSocketMetrics,
    validate_message,
    classify_message_priority,
    calculate_backoff,
    preserve_data_source,
    create_ws_message,
    NON_COALESCED_TYPES,
    COALESCED_TYPES,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    CLOSE_AUTH_FAILED,
    CLOSE_RATE_LIMITED,
    CLOSE_STALE,
)


# ---------------------------------------------------------------------------
# MessageDeduplicator tests
# ---------------------------------------------------------------------------

class TestMessageDeduplicator:
    def test_first_event_not_duplicate(self):
        dedup = MessageDeduplicator(window_s=60)
        assert dedup.is_duplicate("EVT-001") is False

    def test_same_event_is_duplicate(self):
        dedup = MessageDeduplicator(window_s=60)
        dedup.is_duplicate("EVT-001")
        assert dedup.is_duplicate("EVT-001") is True

    def test_different_events_not_duplicate(self):
        dedup = MessageDeduplicator(window_s=60)
        dedup.is_duplicate("EVT-001")
        assert dedup.is_duplicate("EVT-002") is False

    def test_empty_event_id_not_duplicate(self):
        dedup = MessageDeduplicator(window_s=60)
        assert dedup.is_duplicate("") is False
        assert dedup.is_duplicate(None) is False

    def test_window_expiry(self):
        dedup = MessageDeduplicator(window_s=0.1)
        dedup.is_duplicate("EVT-001")
        time.sleep(0.15)
        assert dedup.is_duplicate("EVT-001") is False

    def test_clear(self):
        dedup = MessageDeduplicator(window_s=60)
        dedup.is_duplicate("EVT-001")
        dedup.clear()
        assert dedup.is_duplicate("EVT-001") is False

    def test_size(self):
        dedup = MessageDeduplicator(window_s=60)
        assert dedup.size() == 0
        dedup.is_duplicate("EVT-001")
        assert dedup.size() == 1
        dedup.is_duplicate("EVT-002")
        assert dedup.size() == 2

    def test_thread_safety(self):
        dedup = MessageDeduplicator(window_s=60)
        results = []

        def check_duplicate(event_id):
            results.append(dedup.is_duplicate(event_id))

        threads = [threading.Thread(target=check_duplicate, args=(f"EVT-{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        # First 10 unique events should all be non-duplicate
        assert all(r is False for r in results)


# ---------------------------------------------------------------------------
# EventCoalescer tests
# ---------------------------------------------------------------------------

class TestEventCoalescer:
    def test_non_coalesced_passes_through(self):
        coalescer = EventCoalescer(window_s=1.0)
        received = []
        event = {"type": "incident_created", "bus_id": "BUS-001", "severity": "CRITICAL"}
        coalescer.process(event, lambda e: received.append(e))
        assert len(received) == 1
        assert received[0]["type"] == "incident_created"

    def test_coalesced_event_queued(self):
        coalescer = EventCoalescer(window_s=0.05)
        received = []
        event = {"type": "health_update", "bus_id": "BUS-001", "score": 85}
        coalescer.process(event, lambda e: received.append(e))
        # Should not be immediately available
        assert len(received) == 0
        # Wait for flush
        time.sleep(0.1)
        assert len(received) == 1

    def test_multiple_coalesced_events(self):
        coalescer = EventCoalescer(window_s=0.05)
        received = []
        for i in range(5):
            event = {"type": "eta_update", "bus_id": "BUS-001", "eta": 10 + i}
            coalescer.process(event, lambda e: received.append(e))
        time.sleep(0.1)
        # Should coalesce to 1 (latest)
        assert len(received) == 1
        assert received[0]["eta"] == 14  # Latest value

    def test_clear(self):
        coalescer = EventCoalescer(window_s=0.05)
        received = []
        event = {"type": "load_update", "bus_id": "BUS-001", "load": 50}
        coalescer.process(event, lambda e: received.append(e))
        coalescer.clear()
        time.sleep(0.1)
        assert len(received) == 0

    def test_different_bus_ids_not_coalesced(self):
        coalescer = EventCoalescer(window_s=0.05)
        received = []
        event1 = {"type": "health_update", "bus_id": "BUS-001", "score": 85}
        event2 = {"type": "health_update", "bus_id": "BUS-002", "score": 90}
        coalescer.process(event1, lambda e: received.append(e))
        coalescer.process(event2, lambda e: received.append(e))
        time.sleep(0.1)
        # Different bus IDs should not coalesce
        assert len(received) == 2


# ---------------------------------------------------------------------------
# ConnectionStateManager tests
# ---------------------------------------------------------------------------

class TestConnectionStateManager:
    def test_initial_state(self):
        csm = ConnectionStateManager()
        assert csm.state == ConnectionState.DISCONNECTED
        assert csm.is_ready is False

    def test_set_state(self):
        csm = ConnectionStateManager()
        csm.set_state(ConnectionState.CONNECTING)
        assert csm.state == ConnectionState.CONNECTING

    def test_listener_notification(self):
        csm = ConnectionStateManager()
        notifications = []
        csm.add_listener(lambda old, new: notifications.append((old, new)))
        csm.set_state(ConnectionState.CONNECTED)
        assert len(notifications) == 1
        assert notifications[0] == (ConnectionState.DISCONNECTED, ConnectionState.CONNECTED)

    def test_remove_listener(self):
        csm = ConnectionStateManager()
        notifications = []
        listener = lambda old, new: notifications.append((old, new))
        csm.add_listener(listener)
        csm.remove_listener(listener)
        csm.set_state(ConnectionState.CONNECTED)
        assert len(notifications) == 0

    def test_is_ready(self):
        csm = ConnectionStateManager()
        csm.set_state(ConnectionState.READY)
        assert csm.is_ready is True

    def test_record_message(self):
        csm = ConnectionStateManager()
        assert csm.last_message is None
        csm.record_message()
        assert csm.last_message is not None

    def test_is_stale(self):
        csm = ConnectionStateManager()
        assert csm.is_stale(timeout=0.1) is True
        csm.record_message()
        assert csm.is_stale(timeout=0.1) is False
        time.sleep(0.15)
        assert csm.is_stale(timeout=0.1) is True

    def test_reconnect_attempts(self):
        csm = ConnectionStateManager()
        assert csm.reconnect_attempts == 0
        csm.set_state(ConnectionState.RECONNECTING)
        assert csm.reconnect_attempts == 1
        csm.set_state(ConnectionState.RECONNECTING)
        assert csm.reconnect_attempts == 2

    def test_to_dict(self):
        csm = ConnectionStateManager()
        state = csm.to_dict()
        assert "state" in state
        assert "reconnect_attempts" in state
        assert "is_stale" in state


# ---------------------------------------------------------------------------
# MessagePriorityQueue tests
# ---------------------------------------------------------------------------

class TestMessagePriorityQueue:
    def test_put_and_get(self):
        pq = MessagePriorityQueue(max_size=10)
        pq.put({"msg": "normal"}, MessagePriority.NORMAL)
        msg = pq.get()
        assert msg["msg"] == "normal"

    def test_priority_order(self):
        pq = MessagePriorityQueue(max_size=10)
        pq.put({"msg": "normal"}, MessagePriority.NORMAL)
        pq.put({"msg": "critical"}, MessagePriority.CRITICAL)
        pq.put({"msg": "important"}, MessagePriority.IMPORTANT)
        pq.put({"msg": "transient"}, MessagePriority.TRANSIENT)

        assert pq.get()["msg"] == "critical"
        assert pq.get()["msg"] == "important"
        assert pq.get()["msg"] == "normal"
        assert pq.get()["msg"] == "transient"

    def test_size(self):
        pq = MessagePriorityQueue(max_size=10)
        pq.put({"msg": "a"}, MessagePriority.NORMAL)
        pq.put({"msg": "b"}, MessagePriority.NORMAL)
        assert pq.size() == 2

    def test_has_critical(self):
        pq = MessagePriorityQueue(max_size=10)
        assert pq.has_critical() is False
        pq.put({"msg": "critical"}, MessagePriority.CRITICAL)
        assert pq.has_critical() is True

    def test_clear(self):
        pq = MessagePriorityQueue(max_size=10)
        pq.put({"msg": "a"}, MessagePriority.NORMAL)
        pq.clear()
        assert pq.size() == 0

    def test_max_size_transient_drops(self):
        pq = MessagePriorityQueue(max_size=2)
        pq.put({"msg": "t1"}, MessagePriority.TRANSIENT)
        pq.put({"msg": "t2"}, MessagePriority.TRANSIENT)
        pq.put({"msg": "t3"}, MessagePriority.TRANSIENT)  # Should drop t1
        assert pq.size() == 2
        msg = pq.get()
        assert msg["msg"] == "t2"  # t1 was dropped

    def test_max_size_critical_never_drops(self):
        pq = MessagePriorityQueue(max_size=2)
        pq.put({"msg": "c1"}, MessagePriority.CRITICAL)
        pq.put({"msg": "c2"}, MessagePriority.CRITICAL)
        pq.put({"msg": "c3"}, MessagePriority.CRITICAL)  # Should not drop
        assert pq.size() == 3  # Critical messages are not dropped


# ---------------------------------------------------------------------------
# ServerConnectionTracker tests
# ---------------------------------------------------------------------------

class TestServerConnectionTracker:
    def test_register_and_count(self):
        tracker = ServerConnectionTracker(max_subscribers=10)
        ws = MagicMock()
        assert tracker.register(ws, client_type="dashboard", user="admin") is True
        assert tracker.count() == 1

    def test_unregister(self):
        tracker = ServerConnectionTracker(max_subscribers=10)
        ws = MagicMock()
        tracker.register(ws, client_type="dashboard")
        tracker.unregister(ws)
        assert tracker.count() == 0

    def test_max_capacity(self):
        tracker = ServerConnectionTracker(max_subscribers=2)
        ws1 = MagicMock()
        ws2 = MagicMock()
        ws3 = MagicMock()
        tracker.register(ws1)
        tracker.register(ws2)
        assert tracker.register(ws3) is False

    def test_record_message(self):
        tracker = ServerConnectionTracker(max_subscribers=10)
        ws = MagicMock()
        tracker.register(ws)
        tracker.record_message(ws, sent=True)
        info = tracker.get_all()
        assert ws in info
        assert info[ws]["messages_sent"] == 1

    def test_get_stale_connections(self):
        tracker = ServerConnectionTracker(max_subscribers=10)
        ws = MagicMock()
        tracker.register(ws)
        # Immediately after registration, should not be stale
        stale = tracker.get_stale_connections(timeout=0.1)
        assert len(stale) == 0

    def test_thread_safety(self):
        tracker = ServerConnectionTracker(max_subscribers=100)
        def register_client():
            ws = MagicMock()
            tracker.register(ws)
            tracker.record_message(ws)

        threads = [threading.Thread(target=register_client) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert tracker.count() == 20


# ---------------------------------------------------------------------------
# ReconnectionManager tests
# ---------------------------------------------------------------------------

class TestReconnectionManager:
    def test_should_reconnect(self):
        rm = ReconnectionManager(max_attempts=0)  # Infinite
        assert rm.should_reconnect() is True

    def test_max_attempts(self):
        rm = ReconnectionManager(max_attempts=3)
        assert rm.should_reconnect() is True
        rm.record_attempt(success=False)
        rm.record_attempt(success=False)
        rm.record_attempt(success=False)
        assert rm.should_reconnect() is False

    def test_success_resets(self):
        rm = ReconnectionManager(max_attempts=3)
        rm.record_attempt(success=False)
        rm.record_attempt(success=False)
        rm.record_attempt(success=True)
        assert rm.should_reconnect() is True
        assert rm.to_dict()["attempt"] == 0

    def test_get_delay(self):
        rm = ReconnectionManager(base_delay=1.0, max_delay=30.0)
        delay = rm.get_delay()
        assert 0.5 <= delay <= 30.0

    def test_to_dict(self):
        rm = ReconnectionManager()
        state = rm.to_dict()
        assert "attempt" in state
        assert "max_attempts" in state
        assert "consecutive_failures" in state


# ---------------------------------------------------------------------------
# StateResynchronizer tests
# ---------------------------------------------------------------------------

class TestStateResynchronizer:
    def test_needs_sync(self):
        sr = StateResynchronizer()
        assert sr.needs_sync("fleet") is True

    def test_record_sync(self):
        sr = StateResynchronizer()
        sr.record_sync("fleet")
        assert sr.last_sync is not None

    def test_get_sync_plan(self):
        sr = StateResynchronizer()
        plan = sr.get_sync_plan()
        assert len(plan) > 0
        assert ("fleet", "/api/fleet/summary") in plan


# ---------------------------------------------------------------------------
# WebSocketMetrics tests
# ---------------------------------------------------------------------------

class TestWebSocketMetrics:
    def test_record(self):
        metrics = WebSocketMetrics()
        metrics.record("messages_sent")
        metrics.record("messages_sent")
        assert metrics.get("messages_sent") == 2

    def test_get_all(self):
        metrics = WebSocketMetrics()
        metrics.record("messages_sent")
        all_metrics = metrics.get_all()
        assert "messages_sent" in all_metrics
        assert "messages_received" in all_metrics

    def test_reset(self):
        metrics = WebSocketMetrics()
        metrics.record("messages_sent")
        metrics.reset()
        assert metrics.get("messages_sent") == 0

    def test_negative_value(self):
        metrics = WebSocketMetrics()
        metrics.record("connections_active")
        metrics.record("connections_active", -1)
        assert metrics.get("connections_active") == 0


# ---------------------------------------------------------------------------
# validate_message tests
# ---------------------------------------------------------------------------

class TestValidateMessage:
    def test_valid_heartbeat(self):
        raw = json.dumps({"type": "heartbeat", "bus_id": "BUS-001"})
        valid, msg = validate_message(raw)
        assert valid is True

    def test_valid_hello(self):
        raw = json.dumps({"type": "hello", "bus_id": "BUS-001"})
        valid, msg = validate_message(raw)
        assert valid is True

    def test_valid_subscribe_alerts(self):
        raw = json.dumps({"type": "subscribe_alerts", "token": "abc123"})
        valid, msg = validate_message(raw)
        assert valid is True

    def test_missing_type(self):
        raw = json.dumps({"bus_id": "BUS-001"})
        valid, msg = validate_message(raw)
        assert valid is False
        assert "missing" in msg["error"]

    def test_missing_bus_id(self):
        raw = json.dumps({"type": "hello"})
        valid, msg = validate_message(raw)
        assert valid is False
        assert "bus_id" in msg["error"]

    def test_invalid_json(self):
        valid, msg = validate_message("not json")
        assert valid is False
        assert "JSON" in msg["error"]

    def test_empty_message(self):
        valid, msg = validate_message("")
        assert valid is False

    def test_not_object(self):
        valid, msg = validate_message(json.dumps([1, 2, 3]))
        assert valid is False

    def test_valid_bus_state(self):
        raw = json.dumps({"type": "bus_state", "bus_id": "BUS-001", "state": "normal"})
        valid, msg = validate_message(raw)
        assert valid is True

    def test_bus_state_missing_state(self):
        raw = json.dumps({"type": "bus_state", "bus_id": "BUS-001"})
        valid, msg = validate_message(raw)
        assert valid is False
        assert "state" in msg["error"]

    def test_valid_event(self):
        raw = json.dumps({
            "type": "event",
            "bus_id": "BUS-001",
            "event": {"event_type": "OVERSPEED", "severity": "HIGH"}
        })
        valid, msg = validate_message(raw)
        assert valid is True


# ---------------------------------------------------------------------------
# classify_message_priority tests
# ---------------------------------------------------------------------------

class TestClassifyMessagePriority:
    def test_critical_alert(self):
        msg = {"type": "alert", "alert": {"severity": "CRITICAL"}}
        assert classify_message_priority(msg) == MessagePriority.CRITICAL

    def test_high_alert(self):
        msg = {"type": "alert", "alert": {"severity": "HIGH"}}
        assert classify_message_priority(msg) == MessagePriority.CRITICAL

    def test_medium_alert(self):
        msg = {"type": "alert", "alert": {"severity": "MEDIUM"}}
        assert classify_message_priority(msg) == MessagePriority.IMPORTANT

    def test_state_snapshot(self):
        msg = {"type": "state_snapshot"}
        assert classify_message_priority(msg) == MessagePriority.IMPORTANT

    def test_bus_state(self):
        msg = {"type": "bus_state", "bus_id": "BUS-001"}
        assert classify_message_priority(msg) == MessagePriority.TRANSIENT

    def test_heartbeat(self):
        msg = {"type": "heartbeat", "bus_id": "BUS-001"}
        assert classify_message_priority(msg) == MessagePriority.TRANSIENT

    def test_critical_event(self):
        msg = {"type": "event", "event": {"severity": "CRITICAL"}}
        assert classify_message_priority(msg) == MessagePriority.CRITICAL

    def test_normal_event(self):
        msg = {"type": "event", "event": {"severity": "LOW"}}
        assert classify_message_priority(msg) == MessagePriority.NORMAL


# ---------------------------------------------------------------------------
# calculate_backoff tests
# ---------------------------------------------------------------------------

class TestCalculateBackoff:
    def test_increasing_delay(self):
        delays = [calculate_backoff(i, base=1.0, max_delay=30.0) for i in range(5)]
        # All should be at least 0.5 (with jitter)
        for d in delays:
            assert d >= 0.5
        # All should be at most 30
        for d in delays:
            assert d <= 30.0

    def test_max_delay_cap(self):
        for i in range(10):
            delay = calculate_backoff(i, base=1.0, max_delay=5.0)
            assert delay <= 5.0


# ---------------------------------------------------------------------------
# preserve_data_source tests
# ---------------------------------------------------------------------------

class TestPreserveDataSource:
    def test_preserves_simulation(self):
        original = {"data_source": "SIMULATION", "simulation": True}
        result = preserve_data_source(original)
        assert result["data_source"] == "SIMULATION"
        assert result["simulation"] is True

    def test_valid_override(self):
        original = {"data_source": "SIMULATION"}
        override = {"data_source": "LIVE", "simulation": False}
        result = preserve_data_source(original, override)
        assert result["data_source"] == "LIVE"
        assert result["simulation"] is False

    def test_invalid_override(self):
        original = {"data_source": "SIMULATION"}
        override = {"data_source": "INVALID"}
        result = preserve_data_source(original, override)
        assert result["data_source"] == "SIMULATION"


# ---------------------------------------------------------------------------
# create_ws_message tests
# ---------------------------------------------------------------------------

class TestCreateWsMessage:
    def test_basic_message(self):
        msg = create_ws_message("alert", {"severity": "HIGH"})
        assert msg["type"] == "alert"
        assert msg["severity"] == "HIGH"
        assert msg["ok"] is True
        assert "timestamp" in msg

    def test_with_source(self):
        msg = create_ws_message("bus_state", {"bus_id": "BUS-001"}, source="SIMULATION")
        assert msg["source"] == "SIMULATION"
        assert msg["simulation"] is True
        assert msg["data_source"] == "SIMULATION"


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_non_coalesced_types(self):
        assert "incident_created" in NON_COALESCED_TYPES
        assert "alert_created" in NON_COALESCED_TYPES
        assert "crash" in NON_COALESCED_TYPES

    def test_coalesced_types(self):
        assert "health_update" in COALESCED_TYPES
        assert "eta_update" in COALESCED_TYPES
        assert "occupancy_update" in COALESCED_TYPES

    def test_close_codes(self):
        assert CLOSE_AUTH_FAILED == 4001
        assert CLOSE_RATE_LIMITED == 4002
        assert CLOSE_STALE == 4003

    def test_config_values(self):
        assert RECONNECT_BASE_DELAY == 1.0
        assert RECONNECT_MAX_DELAY == 30.0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestPhase18Integration:
    def test_full_dedup_workflow(self):
        dedup = MessageDeduplicator(window_s=60)
        events = [
            {"event_id": "EVT-001", "type": "alert"},
            {"event_id": "EVT-002", "type": "alert"},
            {"event_id": "EVT-001", "type": "alert"},  # Duplicate
            {"event_id": "EVT-003", "type": "alert"},
            {"event_id": "EVT-002", "type": "alert"},  # Duplicate
        ]

        unique_count = 0
        for event in events:
            if not dedup.is_duplicate(event["event_id"]):
                unique_count += 1

        assert unique_count == 3
        assert dedup.size() == 3

    def test_full_priority_workflow(self):
        pq = MessagePriorityQueue(max_size=10)
        messages = [
            {"type": "bus_state", "bus_id": "BUS-001"},
            {"type": "alert", "alert": {"severity": "CRITICAL"}},
            {"type": "heartbeat", "bus_id": "BUS-001"},
            {"type": "alert", "alert": {"severity": "MEDIUM"}},
        ]

        for msg in messages:
            priority = classify_message_priority(msg)
            pq.put(msg, priority)

        # Should get critical alert first
        first = pq.get()
        assert first["type"] == "alert"
        assert first["alert"]["severity"] == "CRITICAL"

    def test_connection_lifecycle(self):
        csm = ConnectionStateManager()
        tracker = ServerConnectionTracker(max_subscribers=10)
        metrics = WebSocketMetrics()

        # Simulate connection lifecycle
        csm.set_state(ConnectionState.CONNECTING)
        ws = MagicMock()
        tracker.register(ws, client_type="dashboard", user="admin")
        metrics.record("connections_total")
        metrics.record("connections_active")

        csm.set_state(ConnectionState.CONNECTED)
        csm.record_message()
        tracker.record_message(ws, sent=True)
        metrics.record("messages_sent")

        csm.set_state(ConnectionState.READY)

        assert csm.is_ready
        assert tracker.count() == 1
        assert metrics.get("messages_sent") == 1

        # Simulate disconnect
        tracker.unregister(ws)
        csm.set_state(ConnectionState.DISCONNECTED)
        metrics.record("connections_active", -1)

        assert tracker.count() == 0
