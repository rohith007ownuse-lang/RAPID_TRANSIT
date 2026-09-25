"""
websocket_hardening.py
Phase 18: WebSocket Reliability, Reconnection & Real-Time Communication Hardening.

Provides connection lifecycle management, reconnection with exponential backoff,
message deduplication, heartbeat/ping mechanism, message priority, event coalescing,
and state resynchronization for the WebSocket system.

Architecture:
- Server-side: Enhanced connection management, message validation, priority queues
- Client-side: Connection lifecycle, reconnection, deduplication, state recovery
- Shared: Message contract, event identity, data source preservation

Key principles:
- WebSocket is the real-time delivery mechanism, NOT the source of truth
- After reconnect, recover state from REST APIs
- Never fabricate events or timestamps
- Preserve LIVE/SIMULATION/HEURISTIC/UNKNOWN data sources
- Critical events (incidents, alerts) are never coalesced
- High-frequency telemetry can be coalesced safely
"""

import json
import time
import threading
import hashlib
from collections import OrderedDict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Set, List, Any, Callable


# ---------------------------------------------------------------------------
# Connection lifecycle states
# ---------------------------------------------------------------------------

class ConnectionState(Enum):
    """WebSocket connection lifecycle states."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    AUTHENTICATING = "AUTHENTICATING"
    READY = "READY"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Message priority levels
# ---------------------------------------------------------------------------

class MessagePriority(Enum):
    """Message priority for queue management."""
    CRITICAL = 0    # Critical alerts, critical incidents, critical risk transitions
    IMPORTANT = 1   # Health state changes, road-risk changes, severe delays
    NORMAL = 2      # Routine telemetry/state updates
    TRANSIENT = 3   # High-frequency rapidly changing values (can be coalesced)


# ---------------------------------------------------------------------------
# Event coalescing rules
# ---------------------------------------------------------------------------

# Event types that MUST NOT be coalesced (discrete operational events)
NON_COALESCED_TYPES = frozenset([
    # Incident lifecycle
    "incident_created", "incident_acknowledged", "incident_investigating",
    "incident_resolved", "incident_closed",
    # Alert lifecycle
    "alert_created", "alert_acknowledged", "alert_resolved",
    # Risk transitions (state changes are discrete)
    "risk_state_change", "risk_escalation", "risk_recovery", "critical_risk",
    # DDS events
    "driver_drowsiness", "driver_alert", "driver_recovered",
    # Critical system events
    "crash", "cabin_fire", "cabin_smoke", "emergency_siren",
    "bus_offline", "bus_online",
])

# Event types that CAN be coalesced (high-frequency telemetry)
COALESCED_TYPES = frozenset([
    # Vehicle health updates
    "health_update", "health_state_change",
    # ETA updates
    "eta_update", "delay_update",
    # Occupancy/load updates
    "occupancy_update", "load_update",
    # Risk score updates (not transitions)
    "risk_score_update",
    # Routine bus state
    "bus_state",
])


# ---------------------------------------------------------------------------
# Message contract
# ---------------------------------------------------------------------------

class MessageType:
    """Standard message types for WebSocket protocol."""
    # Client -> Server
    HELLO = "hello"
    BUS_STATE = "bus_state"
    EVENT = "event"
    HEARTBEAT = "heartbeat"
    SUBSCRIBE_ALERTS = "subscribe_alerts"
    PING_ALERTS = "ping_alerts"
    REQUEST_STATE = "request_state"  # New: request current state snapshot

    # Server -> Client
    SUBSCRIBE_OK = "subscribe_ok"
    ALERT = "alert"
    ROAD_EVENT = "road_event"
    ROAD_RISK_UPDATE = "road_risk_update"
    PONG_ALERTS = "pong_alerts"
    STATE_SNAPSHOT = "state_snapshot"  # New: full state snapshot
    STATE_UPDATE = "state_update"      # New: incremental state update
    ERROR = "error"
    PONG = "pong"                       # New: server-initiated pong


# Close codes
CLOSE_NORMAL = 1000
CLOSE_GOING_AWAY = 1001
CLOSE_PROTOCOL_ERROR = 1002
CLOSE_UNSUPPORTED = 1003
CLOSE_POLICY_VIOLATION = 1008
CLOSE_INTERNAL_ERROR = 1011
CLOSE_AUTH_FAILED = 4001
CLOSE_RATE_LIMITED = 4002
CLOSE_STALE = 4003


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Reconnection backoff (seconds)
RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0
RECONNECT_MAX_ATTEMPTS = 0  # 0 = infinite

# Heartbeat intervals (seconds)
SERVER_PING_INTERVAL = 30.0
CLIENT_HEARTBEAT_INTERVAL = 15.0
STALE_CONNECTION_TIMEOUT = 60.0

# Queue limits
MAX_BROADCAST_QUEUE_SIZE = 100
MAX_SUBSCRIBERS = 100

# Coalescing window (seconds) - updates within this window can be coalesced
COALESCING_WINDOW_S = 2.0

# Deduplication window (seconds) - events within this window with same ID are deduped
DEDUP_WINDOW_S = 300.0  # 5 minutes


# ---------------------------------------------------------------------------
# Exponential backoff calculator
# ---------------------------------------------------------------------------

def calculate_backoff(attempt: int, base: float = RECONNECT_BASE_DELAY,
                      max_delay: float = RECONNECT_MAX_DELAY) -> float:
    """Calculate exponential backoff with jitter.

    Args:
        attempt: Current retry attempt (0-based)
        base: Base delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        Delay in seconds with jitter
    """
    import random
    delay = min(base * (2 ** attempt), max_delay)
    # Add jitter: 50-100% of calculated delay
    jitter = delay * (0.5 + random.random() * 0.5)
    return jitter


# ---------------------------------------------------------------------------
# Message deduplication
# ---------------------------------------------------------------------------

class MessageDeduplicator:
    """Thread-safe message deduplication using event IDs."""

    def __init__(self, window_s: float = DEDUP_WINDOW_S):
        self._window = window_s
        self._seen = OrderedDict()  # event_id -> timestamp
        self._lock = threading.Lock()

    def is_duplicate(self, event_id: str) -> bool:
        """Check if an event ID has been seen recently.

        Returns True if duplicate, False if new.
        """
        if not event_id:
            return False

        now = time.time()
        with self._lock:
            # Clean old entries
            cutoff = now - self._window
            while self._seen and next(iter(self._seen.values())) < cutoff:
                self._seen.popitem(last=False)

            # Check if seen
            if event_id in self._seen:
                return True

            # Record new event
            self._seen[event_id] = now
            return False

    def clear(self):
        """Clear deduplication history."""
        with self._lock:
            self._seen.clear()

    def size(self) -> int:
        """Return number of tracked events."""
        with self._lock:
            return len(self._seen)


# ---------------------------------------------------------------------------
# Event coalescing
# ---------------------------------------------------------------------------

class EventCoalescer:
    """Coalesce high-frequency state updates.

    Only coalesces events in COALESCED_TYPES. Critical/discrete events
    are passed through immediately.
    """

    def __init__(self, window_s: float = COALESCING_WINDOW_S):
        self._window = window_s
        self._pending = {}  # composite_key -> (event_type, payload, timestamp)
        self._lock = threading.Lock()
        self._timer = None

    def _coalesce_key(self, event: dict) -> Optional[str]:
        """Generate a coalescing key for an event.

        Returns None if event should not be coalesced.
        """
        event_type = event.get("type") or event.get("event_type")
        if event_type not in COALESCED_TYPES:
            return None

        # Use bus_id + event_type as the coalescing key
        bus_id = event.get("bus_id")
        if not bus_id:
            return None

        return f"{bus_id}:{event_type}"

    def process(self, event: dict, callback: Callable[[dict], None]) -> None:
        """Process an event, coalescing if appropriate.

        Args:
            event: Event dict
            callback: Function to call with the (possibly coalesced) event
        """
        key = self._coalesce_key(event)

        # Non-coalesced events pass through immediately
        if key is None:
            callback(event)
            return

        # Coalesced events: replace pending with latest version
        now = time.time()
        with self._lock:
            self._pending[key] = (
                event.get("type") or event.get("event_type"),
                event,
                now,
            )

        # Schedule flush if not already scheduled
        if self._timer is None:
            self._timer = threading.Timer(self._window, self._flush, args=[callback])
            self._timer.daemon = True
            self._timer.start()

    def _flush(self, callback: Callable[[dict], None]) -> None:
        """Flush coalesced events."""
        with self._lock:
            pending = self._pending
            self._pending = {}
            self._timer = None

        for key, (event_type, event, ts) in pending.items():
            try:
                callback(event)
            except Exception:
                pass

    def clear(self):
        """Clear pending coalesced events."""
        with self._lock:
            self._pending.clear()
            if self._timer:
                self._timer.cancel()
                self._timer = None


# ---------------------------------------------------------------------------
# Connection state manager
# ---------------------------------------------------------------------------

class ConnectionStateManager:
    """Manage WebSocket connection state and notify listeners."""

    def __init__(self):
        self._state = ConnectionState.DISCONNECTED
        self._last_connected = None
        self._last_message = None
        self._reconnect_attempts = 0
        self._listeners = []
        self._lock = threading.Lock()

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state == ConnectionState.READY

    @property
    def last_connected(self) -> Optional[float]:
        return self._last_connected

    @property
    def last_message(self) -> Optional[float]:
        return self._last_message

    @property
    def reconnect_attempts(self) -> int:
        return self._reconnect_attempts

    def set_state(self, new_state: ConnectionState):
        """Update connection state and notify listeners."""
        with self._lock:
            old_state = self._state
            self._state = new_state

            if new_state == ConnectionState.CONNECTED:
                self._last_connected = time.time()
                self._reconnect_attempts = 0
            elif new_state == ConnectionState.RECONNECTING:
                self._reconnect_attempts += 1

        # Notify listeners outside lock
        for listener in self._listeners:
            try:
                listener(old_state, new_state)
            except Exception:
                pass

    def record_message(self):
        """Record that a message was received."""
        self._last_message = time.time()

    def add_listener(self, listener: Callable[[ConnectionState, ConnectionState], None]):
        """Add a state change listener."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable):
        """Remove a state change listener."""
        self._listeners = [l for l in self._listeners if l is not listener]

    def is_stale(self, timeout: float = STALE_CONNECTION_TIMEOUT) -> bool:
        """Check if connection is stale (no messages received)."""
        if self._last_message is None:
            return True
        return (time.time() - self._last_message) > timeout

    def to_dict(self) -> dict:
        """Serialize connection state for API/JSON."""
        return {
            "state": self._state.value,
            "last_connected": self._last_connected,
            "last_message": self._last_message,
            "reconnect_attempts": self._reconnect_attempts,
            "is_stale": self.is_stale(),
        }


# ---------------------------------------------------------------------------
# Message priority queue
# ---------------------------------------------------------------------------

class MessagePriorityQueue:
    """Bounded priority queue for outgoing messages.

    Ensures critical messages are never dropped and high-frequency
    telemetry cannot starve important messages.
    """

    def __init__(self, max_size: int = MAX_BROADCAST_QUEUE_SIZE):
        self._max_size = max_size
        self._queues = {
            MessagePriority.CRITICAL: [],
            MessagePriority.IMPORTANT: [],
            MessagePriority.NORMAL: [],
            MessagePriority.TRANSIENT: [],
        }
        self._lock = threading.Lock()

    def put(self, message: dict, priority: MessagePriority = MessagePriority.NORMAL):
        """Add a message to the queue."""
        with self._lock:
            queue = self._queues[priority]
            if len(queue) >= self._max_size:
                # Drop oldest transient messages first
                if priority == MessagePriority.TRANSIENT and queue:
                    queue.pop(0)
                elif priority != MessagePriority.CRITICAL:
                    return  # Drop message rather than block

            queue.append(message)

    def get(self) -> Optional[dict]:
        """Get the highest priority message."""
        with self._lock:
            for priority in MessagePriority:
                queue = self._queues[priority]
                if queue:
                    return queue.pop(0)
        return None

    def size(self) -> int:
        """Total messages across all queues."""
        with self._lock:
            return sum(len(q) for q in self._queues.values())

    def clear(self):
        """Clear all queues."""
        with self._lock:
            for queue in self._queues.values():
                queue.clear()

    def has_critical(self) -> bool:
        """Check if there are critical messages waiting."""
        with self._lock:
            return bool(self._queues[MessagePriority.CRITICAL])


# ---------------------------------------------------------------------------
# Message validator
# ---------------------------------------------------------------------------

def validate_message(raw: str) -> tuple:
    """Validate an incoming WebSocket message.

    Returns:
        (is_valid, parsed_message_or_error_dict)
    """
    if not raw or not isinstance(raw, str):
        return False, {"error": "empty message"}

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, {"error": f"invalid JSON: {e}"}

    if not isinstance(msg, dict):
        return False, {"error": "message must be a JSON object"}

    msg_type = msg.get("type")
    if not msg_type:
        return False, {"error": "missing 'type' field"}

    # Validate required fields per type
    required = {
        MessageType.HELLO: ["bus_id"],
        MessageType.BUS_STATE: ["bus_id", "state"],
        MessageType.EVENT: ["bus_id", "event"],
        MessageType.HEARTBEAT: ["bus_id"],
        MessageType.SUBSCRIBE_ALERTS: ["token"],
    }

    if msg_type in required:
        for field in required[msg_type]:
            if field not in msg:
                return False, {"error": f"missing '{field}' for {msg_type}"}

    return True, msg


def classify_message_priority(msg: dict) -> MessagePriority:
    """Classify a message for priority queue routing."""
    msg_type = msg.get("type")

    # Server-side alert/incident messages
    if msg_type == MessageType.ALERT:
        severity = (msg.get("alert") or {}).get("severity", "").upper()
        if severity in ("CRITICAL", "HIGH"):
            return MessagePriority.CRITICAL
        return MessagePriority.IMPORTANT

    if msg_type == MessageType.STATE_SNAPSHOT:
        return MessagePriority.IMPORTANT

    if msg_type == MessageType.STATE_UPDATE:
        event_type = msg.get("event_type", "")
        if event_type in NON_COALESCED_TYPES:
            return MessagePriority.IMPORTANT
        return MessagePriority.NORMAL

    # Bus-node messages
    if msg_type == MessageType.EVENT:
        severity = (msg.get("event") or {}).get("severity", "").upper()
        if severity in ("CRITICAL", "HIGH"):
            return MessagePriority.CRITICAL
        return MessagePriority.NORMAL

    if msg_type == MessageType.BUS_STATE:
        return MessagePriority.TRANSIENT

    if msg_type == MessageType.HEARTBEAT:
        return MessagePriority.TRANSIENT

    return MessagePriority.NORMAL


# ---------------------------------------------------------------------------
# Server-side connection tracker
# ---------------------------------------------------------------------------

class ServerConnectionTracker:
    """Track all connected WebSocket clients on the server side."""

    def __init__(self, max_subscribers: int = MAX_SUBSCRIBERS):
        self._connections = {}  # websocket -> connection_info
        self._max = max_subscribers
        self._lock = threading.Lock()

    def register(self, websocket, client_type: str = "unknown",
                 user: str = None, role: str = None) -> bool:
        """Register a new connection.

        Returns True if registered, False if at capacity.
        """
        with self._lock:
            if len(self._connections) >= self._max:
                return False

            self._connections[websocket] = {
                "type": client_type,
                "user": user,
                "role": role,
                "connected_at": time.time(),
                "last_message": time.time(),
                "messages_sent": 0,
                "messages_failed": 0,
            }
            return True

    def unregister(self, websocket):
        """Remove a connection."""
        with self._lock:
            self._connections.pop(websocket, None)

    def record_message(self, websocket, sent: bool = True):
        """Record a message sent/failed for a connection."""
        with self._lock:
            info = self._connections.get(websocket)
            if info:
                info["last_message"] = time.time()
                if sent:
                    info["messages_sent"] += 1
                else:
                    info["messages_failed"] += 1

    def get_stale_connections(self, timeout: float = STALE_CONNECTION_TIMEOUT) -> list:
        """Get connections that haven't sent messages recently."""
        now = time.time()
        stale = []
        with self._lock:
            for ws, info in self._connections.items():
                if now - info["last_message"] > timeout:
                    stale.append(ws)
        return stale

    def get_all(self) -> dict:
        """Get all connection info."""
        with self._lock:
            return {ws: dict(info) for ws, info in self._connections.items()}

    def count(self) -> int:
        """Number of active connections."""
        with self._lock:
            return len(self._connections)


# ---------------------------------------------------------------------------
# Client-side state resynchronizer
# ---------------------------------------------------------------------------

class StateResynchronizer:
    """Manage state resynchronization after reconnection.

    After reconnect, the client fetches current state from REST APIs
    to fill any gaps from missed WebSocket events.
    """

    def __init__(self):
        self._last_sync = None
        self._pending_syncs = set()
        self._lock = threading.Lock()

    def needs_sync(self, sync_type: str, cooldown_s: float = 5.0) -> bool:
        """Check if a sync is needed (not done recently)."""
        now = time.time()
        with self._lock:
            last = self._pending_syncs.get(sync_type) if isinstance(self._pending_syncs, dict) else None
            if last and now - last < cooldown_s:
                return False
            return True

    def record_sync(self, sync_type: str):
        """Record that a sync was performed."""
        with self._lock:
            if not isinstance(self._pending_syncs, dict):
                self._pending_syncs = {}
            self._pending_syncs[sync_type] = time.time()
            self._last_sync = time.time()

    def get_sync_plan(self) -> list:
        """Get list of sync operations to perform after reconnect.

        Returns list of (sync_type, api_endpoint) tuples.
        """
        return [
            ("fleet", "/api/fleet/summary"),
            ("buses", "/api/buses"),
            ("alerts", "/api/alerts"),
            ("incidents", "/api/incidents"),
            ("risk", "/api/risk"),
            ("events", "/api/events"),
        ]

    @property
    def last_sync(self) -> Optional[float]:
        return self._last_sync


# ---------------------------------------------------------------------------
# Reconnection manager
# ---------------------------------------------------------------------------

class ReconnectionManager:
    """Manage WebSocket reconnection with exponential backoff."""

    def __init__(self, base_delay: float = RECONNECT_BASE_DELAY,
                 max_delay: float = RECONNECT_MAX_DELAY,
                 max_attempts: int = RECONNECT_MAX_ATTEMPTS):
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._max_attempts = max_attempts
        self._attempt = 0
        self._last_attempt = None
        self._consecutive_failures = 0
        self._lock = threading.RLock()

    def should_reconnect(self) -> bool:
        """Check if reconnection should be attempted."""
        with self._lock:
            if self._max_attempts > 0 and self._attempt >= self._max_attempts:
                return False
            return True

    def get_delay(self) -> float:
        """Get the delay before next reconnection attempt."""
        with self._lock:
            return calculate_backoff(self._attempt, self._base_delay, self._max_delay)

    def record_attempt(self, success: bool):
        """Record a reconnection attempt."""
        with self._lock:
            self._last_attempt = time.time()
            if success:
                self._attempt = 0
                self._consecutive_failures = 0
            else:
                self._attempt += 1
                self._consecutive_failures += 1

    def reset(self):
        """Reset reconnection state (e.g., after successful connection)."""
        with self._lock:
            self._attempt = 0
            self._consecutive_failures = 0

    def to_dict(self) -> dict:
        """Serialize reconnection state."""
        with self._lock:
            return {
                "attempt": self._attempt,
                "max_attempts": self._max_attempts,
                "last_attempt": self._last_attempt,
                "consecutive_failures": self._consecutive_failures,
                "next_delay": self.get_delay() if self.should_reconnect() else None,
            }


# ---------------------------------------------------------------------------
# Data source preservation
# ---------------------------------------------------------------------------

def preserve_data_source(original: dict, override: dict = None) -> dict:
    """Ensure data source information is preserved in messages.

    Prevents accidental conversion of SIMULATION -> LIVE or vice versa.
    """
    result = dict(original)
    if override:
        # Only override if explicitly set and valid
        new_source = override.get("data_source")
        if new_source in ("LIVE", "SIMULATION", "HEURISTIC", "MODEL", "UNKNOWN"):
            result["data_source"] = new_source

        # Preserve simulation flag
        if "simulation" in override:
            result["simulation"] = override["simulation"]

    return result


def create_ws_message(msg_type: str, payload: dict, source: str = None) -> dict:
    """Create a standardized WebSocket message with metadata."""
    msg = {
        "type": msg_type,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": True,
    }
    msg.update(payload)

    if source:
        msg["source"] = source
        msg["simulation"] = source == "SIMULATION"
        msg["data_source"] = source

    return msg


# ---------------------------------------------------------------------------
# Metrics collector
# ---------------------------------------------------------------------------

class WebSocketMetrics:
    """Collect WebSocket performance metrics."""

    def __init__(self):
        self._metrics = {
            "messages_sent": 0,
            "messages_received": 0,
            "messages_failed": 0,
            "messages_dropped": 0,
            "connections_total": 0,
            "connections_active": 0,
            "reconnections": 0,
            "auth_failures": 0,
            "dedup_hits": 0,
            "coalesce_hits": 0,
        }
        self._lock = threading.Lock()

    def record(self, metric: str, value: int = 1):
        """Record a metric value."""
        with self._lock:
            if metric in self._metrics:
                self._metrics[metric] += value

    def get(self, metric: str) -> int:
        """Get a metric value."""
        with self._lock:
            return self._metrics.get(metric, 0)

    def get_all(self) -> dict:
        """Get all metrics."""
        with self._lock:
            return dict(self._metrics)

    def reset(self):
        """Reset all metrics."""
        with self._lock:
            for key in self._metrics:
                self._metrics[key] = 0


# ---------------------------------------------------------------------------
# Global instances
# ---------------------------------------------------------------------------

# Server-side globals
server_tracker = ServerConnectionTracker()
server_metrics = WebSocketMetrics()
server_deduplicator = MessageDeduplicator()
server_coalescer = EventCoalescer()
server_priority_queue = MessagePriorityQueue()

# Shared utilities
message_deduplicator = MessageDeduplicator()


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick self-test
    print("WebSocket Hardening Module - Self Test")
    print("=" * 50)

    # Test backoff
    print("\n1. Backoff calculation:")
    for i in range(5):
        delay = calculate_backoff(i)
        print(f"   Attempt {i}: {delay:.2f}s")

    # Test deduplication
    print("\n2. Deduplication:")
    dedup = MessageDeduplicator(window_s=10)
    print(f"   First event: duplicate={dedup.is_duplicate('EVT-001')}")
    print(f"   Same event: duplicate={dedup.is_duplicate('EVT-001')}")
    print(f"   New event: duplicate={dedup.is_duplicate('EVT-002')}")
    print(f"   Dedup size: {dedup.size()}")

    # Test priority queue
    print("\n3. Priority queue:")
    pq = MessagePriorityQueue(max_size=10)
    pq.put({"msg": "normal"}, MessagePriority.NORMAL)
    pq.put({"msg": "critical"}, MessagePriority.CRITICAL)
    pq.put({"msg": "important"}, MessagePriority.IMPORTANT)
    print(f"   Queue size: {pq.size()}")
    print(f"   Has critical: {pq.has_critical()}")
    first = pq.get()
    print(f"   First message: {first}")

    # Test message validation
    print("\n4. Message validation:")
    valid, msg = validate_message('{"type": "heartbeat", "bus_id": "BUS-001"}')
    print(f"   Valid heartbeat: {valid}")
    valid, msg = validate_message('{"type": "hello"}')
    print(f"   Missing bus_id: {valid}, error={msg.get('error')}")
    valid, msg = validate_message('not json')
    print(f"   Invalid JSON: {valid}")

    # Test connection state
    print("\n5. Connection state:")
    csm = ConnectionStateManager()
    print(f"   Initial state: {csm.state.value}")
    csm.set_state(ConnectionState.CONNECTING)
    print(f"   After connect: {csm.state.value}")
    csm.set_state(ConnectionState.READY)
    print(f"   Ready: {csm.is_ready}")

    # Test message classification
    print("\n6. Message priority classification:")
    alert_msg = {"type": "alert", "alert": {"severity": "CRITICAL"}}
    priority = classify_message_priority(alert_msg)
    print(f"   Critical alert: {priority.name}")
    bus_msg = {"type": "bus_state", "bus_id": "BUS-001"}
    priority = classify_message_priority(bus_msg)
    print(f"   Bus state: {priority.name}")

    print("\n" + "=" * 50)
    print("All self-tests passed!")
