"""
lifecycle.py
Application lifecycle management for the FLEET-IQ Control Centre.

Manages the startup, running, and shutdown phases of the application.
Consolidates the lifecycle operations that were previously scattered
across server.py's main() function and _graceful_shutdown().
"""

import os
import signal
import threading
from enum import Enum
from typing import Optional, Callable, List
from dataclasses import dataclass


class AppState(Enum):
    """Application lifecycle states."""
    INITIALIZING = "initializing"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class SubsystemInfo:
    """Information about a managed subsystem."""
    name: str
    start_fn: Optional[Callable] = None
    stop_fn: Optional[Callable] = None
    is_running: bool = False
    error: Optional[str] = None


class ApplicationLifecycle:
    """Manages the application lifecycle and subsystem coordination.
    
    This class consolidates the lifecycle operations that were previously
    scattered across server.py. It provides a clear state machine for
    the application and manages subsystem startup/shutdown ordering.
    """
    
    def __init__(self):
        self._state = AppState.INITIALIZING
        self._subsystems: List[SubsystemInfo] = []
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()
        self._on_state_change: Optional[Callable] = None
        # Extra ordered-stop hooks (simulator / DDS / camera / WebSocket).
        # They run in the given order between "stop accepting new work" and
        # "exit", preserving the historical graceful-shutdown contract.
        self._cleanup_fns: List[Callable] = []

    def add_cleanup_fn(self, fn: Callable):
        """Register a callable to run during graceful shutdown (in order)."""
        if fn not in self._cleanup_fns:
            self._cleanup_fns.append(fn)
    
    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state
    
    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_event.is_set()
    
    def register_subsystem(self, name: str, start_fn: Optional[Callable] = None,
                          stop_fn: Optional[Callable] = None):
        """Register a subsystem for lifecycle management."""
        self._subsystems.append(SubsystemInfo(
            name=name,
            start_fn=start_fn,
            stop_fn=stop_fn,
        ))
    
    def set_state_change_callback(self, callback: Optional[Callable]):
        """Set a callback to be called when state changes."""
        self._on_state_change = callback
    
    def _set_state(self, new_state: AppState):
        """Transition to a new state."""
        with self._lock:
            old_state = self._state
            self._state = new_state
        if self._on_state_change:
            try:
                self._on_state_change(old_state, new_state)
            except Exception:
                pass
    
    def start(self):
        """Transition to RUNNING state."""
        self._set_state(AppState.STARTING)
        self._set_state(AppState.RUNNING)
    
    def request_shutdown(self):
        """Request graceful shutdown."""
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        self._set_state(AppState.STOPPING)
    
    def stop(self):
        """Run the full graceful-shutdown sequence and stop subsystems."""
        self.request_shutdown()

        self.run_cleanup()

        # Stop registered subsystems in reverse order
        for subsystem in reversed(self._subsystems):
            if subsystem.is_running and subsystem.stop_fn:
                try:
                    subsystem.stop_fn()
                    subsystem.is_running = False
                except Exception as e:
                    subsystem.error = str(e)

        self._set_state(AppState.STOPPED)

    def run_cleanup(self):
        """Run registered cleanup hooks exactly once (ordered, error-tolerant)."""
        for fn in self._cleanup_fns:
            try:
                fn()
            except Exception as e:
                print(f"[control-centre] Cleanup hook error: {e}")
        self._cleanup_fns.clear()
    
    def start_subsystems(self):
        """Start all registered subsystems."""
        for subsystem in self._subsystems:
            if subsystem.start_fn:
                try:
                    subsystem.start_fn()
                    subsystem.is_running = True
                except Exception as e:
                    subsystem.error = str(e)
    
    def setup_signal_handlers(self):
        """Setup SIGINT/SIGTERM handlers for graceful shutdown."""
        def _signal_handler(signum, frame):
            print(f"[control-centre] Received signal {signum}")
            # Ordered cleanup (simulator -> DDS -> session capture -> camera ->
            # WebSocket), then force exit so the interpreter cannot hang on
            # non-daemon threads (historical contract: SIGTERM always exits).
            self.stop()
            os._exit(0)
        
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    
    def capture_dds_session(self):
        """Capture the final DDS session into the shared store.
        
        Dedupes on (event_type, timestamp, details) so a session only captured
        once even if the live event callback already ingested parts of it.
        """
        try:
            from ai.dds.dds_log_reader import get_dds_log_files, read_dds_events
            from data_store import store
            
            files = get_dds_log_files()
            if not files:
                return
            
            events = read_dds_events(files[0])
            if not events:
                return
            
            existing = set()
            for e in store.get_events(limit=5000):
                existing.add((e.get("event_type"), e.get("timestamp"), e.get("details")))
            
            added = 0
            for ev in events:
                key = (ev.get("event_type"), ev.get("timestamp"), ev.get("details"))
                if key in existing:
                    continue
                ev.setdefault("simulation", False)
                ev.setdefault("data_source", "live")
                store.add_event(ev)
                added += 1
                existing.add(key)
            
            print(f"[control-centre] DDS session captured: {added} new events from {files[0]}")
        except Exception as e:
            print(f"[control-centre] DDS session capture error: {e}")


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

_lifecycle: Optional[ApplicationLifecycle] = None


def get_lifecycle() -> ApplicationLifecycle:
    """Get the application lifecycle singleton."""
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = ApplicationLifecycle()
    return _lifecycle


def is_shutting_down() -> bool:
    """Check if the application is shutting down."""
    return get_lifecycle().is_shutting_down
