"""
data_source_manager.py
Abstraction layer for data sources in the Rapid Transit system.

Provides a unified interface for both SIMULATION and LIVE data sources,
allowing the system to switch between them without changing the AI/pipeline code.

Architecture:
    DATA SOURCES
    ├── GTFS (real) ──────────────┐
    ├── Emergency Facilities (real)┤
    ├── Simulator (simulated) ─────┤
    ├── Bus Node (live when connected)
    └── Traffic API (future) ──────┘
             │
             ▼
    DATA SOURCE MANAGER (this module)
             │
             ▼
    COMMON DATA INGESTION LAYER
             │
             ▼
    AI / EVENT PIPELINE (unchanged)
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable


class DataSourceType:
    """Enum for data source types."""
    SIMULATION = "simulation"
    LIVE = "live"
    GTFS = "gtfs"
    EMERGENCY = "emergency"
    TRAFFIC_API = "traffic_api"


class DataSourceStatus:
    """Status of a data source."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    DEGRADED = "degraded"


class DataSource:
    """Represents a single data source with its metadata and callbacks."""

    def __init__(self, source_id: str, source_type: str, name: str, description: str = ""):
        self.source_id = source_id
        self.source_type = source_type
        self.name = name
        self.description = description
        self.status = DataSourceStatus.INACTIVE
        self.last_update = None
        self.error_count = 0
        self.update_count = 0
        self._callbacks: List[Callable] = []
        self._lock = threading.Lock()

    def register_callback(self, callback: Callable):
        """Register a callback for data updates."""
        with self._lock:
            self._callbacks.append(callback)

    def notify_update(self, data: Dict):
        """Notify all registered callbacks of a data update."""
        with self._lock:
            self.last_update = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.update_count += 1
            for callback in self._callbacks:
                try:
                    callback(data)
                except Exception as e:
                    print(f"[data-source-manager] Callback error for {self.source_id}: {e}")

    def set_status(self, status: str, error: str = None):
        """Update the source status."""
        with self._lock:
            self.status = status
            if error:
                self.error_count += 1
                self.last_error = error

    def get_info(self) -> Dict:
        """Get source metadata."""
        with self._lock:
            return {
                "source_id": self.source_id,
                "source_type": self.source_type,
                "name": self.name,
                "description": self.description,
                "status": self.status,
                "last_update": self.last_update,
                "update_count": self.update_count,
                "error_count": self.error_count,
            }


class DataSourceManager:
    """
    Central manager for all data sources in the Rapid Transit system.

    Provides:
    - Registration of data sources
    - Status monitoring
    - Unified data ingestion interface
    - Source switching (simulation ↔ live)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sources: Dict[str, DataSource] = {}
        self._active_mode = DataSourceType.SIMULATION
        self._ingestion_callbacks: List[Callable] = []

    @property
    def active_mode(self) -> str:
        """Get the currently active data mode."""
        return self._active_mode

    @property
    def is_simulation(self) -> bool:
        """Check if in simulation mode."""
        return self._active_mode == DataSourceType.SIMULATION

    @property
    def is_live(self) -> bool:
        """Check if in live mode."""
        return self._active_mode == DataSourceType.LIVE

    def register_source(self, source: DataSource):
        """Register a data source."""
        with self._lock:
            self._sources[source.source_id] = source
            print(f"[data-source-manager] Registered source: {source.name} ({source.source_type})")

    def get_source(self, source_id: str) -> Optional[DataSource]:
        """Get a registered data source."""
        return self._sources.get(source_id)

    def get_all_sources(self) -> List[Dict]:
        """Get info for all registered sources."""
        with self._lock:
            return [source.get_info() for source in self._sources.values()]

    def get_sources_by_type(self, source_type: str) -> List[DataSource]:
        """Get all sources of a specific type."""
        with self._lock:
            return [s for s in self._sources.values() if s.source_type == source_type]

    def switch_mode(self, new_mode: str) -> tuple:
        """
        Switch between simulation and live modes.

        Returns:
            (success: bool, message: str)
        """
        if new_mode not in (DataSourceType.SIMULATION, DataSourceType.LIVE):
            return False, f"Invalid mode: {new_mode}"

        with self._lock:
            old_mode = self._active_mode
            self._active_mode = new_mode

            # Update source statuses based on new mode
            for source in self._sources.values():
                if source.source_type == DataSourceType.SIMULATION:
                    source.set_status(
                        DataSourceStatus.ACTIVE if new_mode == DataSourceType.SIMULATION
                        else DataSourceStatus.INACTIVE
                    )
                elif source.source_type == DataSourceType.LIVE:
                    source.set_status(
                        DataSourceStatus.ACTIVE if new_mode == DataSourceType.LIVE
                        else DataSourceStatus.INACTIVE
                    )

        print(f"[data-source-manager] Mode switched: {old_mode} → {new_mode}")
        return True, f"Switched from {old_mode} to {new_mode}"

    def register_ingestion_callback(self, callback: Callable):
        """Register a callback for all data ingestion events."""
        with self._lock:
            self._ingestion_callbacks.append(callback)

    def ingest_data(self, source_id: str, data_type: str, data: Dict):
        """
        Ingest data from a source into the common pipeline.

        This is the unified entry point for all data entering the system.
        """
        source = self._sources.get(source_id)
        if not source:
            print(f"[data-source-manager] Unknown source: {source_id}")
            return

        # Enrich data with source metadata
        enriched_data = {
            "source_id": source_id,
            "source_type": source.source_type,
            "data_type": data_type,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": self._active_mode,
            "payload": data,
        }

        # Notify source-specific callbacks
        source.notify_update(enriched_data)

        # Notify global ingestion callbacks
        for callback in self._ingestion_callbacks:
            try:
                callback(enriched_data)
            except Exception as e:
                print(f"[data-source-manager] Ingestion callback error: {e}")

    def get_status_summary(self) -> Dict:
        """Get a summary of all data source statuses."""
        with self._lock:
            active = sum(1 for s in self._sources.values() if s.status == DataSourceStatus.ACTIVE)
            inactive = sum(1 for s in self._sources.values() if s.status == DataSourceStatus.INACTIVE)
            error = sum(1 for s in self._sources.values() if s.status == DataSourceStatus.ERROR)

            return {
                "active_mode": self._active_mode,
                "total_sources": len(self._sources),
                "active_sources": active,
                "inactive_sources": inactive,
                "error_sources": error,
                "sources": self.get_all_sources(),
            }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

data_source_manager = DataSourceManager()


# ---------------------------------------------------------------------------
# Initialization helpers
# ---------------------------------------------------------------------------

def initialize_data_sources():
    """Initialize and register all known data sources."""

    # GTFS Data Source (always available)
    gtfs_source = DataSource(
        source_id="gtfs",
        source_type=DataSourceType.GTFS,
        name="Chennai GTFS",
        description="Chennai MTC transit data (4611 routes, 5477 stops)"
    )
    gtfs_source.set_status(DataSourceStatus.ACTIVE)
    data_source_manager.register_source(gtfs_source)

    # Emergency Facility Data Source (always available)
    emergency_source = DataSource(
        source_id="emergency",
        source_type=DataSourceType.EMERGENCY,
        name="Emergency Facilities",
        description="Chennai hospitals, fire stations, police stations"
    )
    emergency_source.set_status(DataSourceStatus.ACTIVE)
    data_source_manager.register_source(emergency_source)

    # Simulation Data Source
    sim_source = DataSource(
        source_id="simulator",
        source_type=DataSourceType.SIMULATION,
        name="Fleet Simulator",
        description="300-vehicle Chennai MTC fleet simulation"
    )
    sim_source.set_status(DataSourceStatus.ACTIVE)
    data_source_manager.register_source(sim_source)

    # Live Bus Node Data Source
    live_source = DataSource(
        source_id="bus_node",
        source_type=DataSourceType.LIVE,
        name="Live Bus Node",
        description="Real-time bus node data (when connected)"
    )
    live_source.set_status(DataSourceStatus.INACTIVE)
    data_source_manager.register_source(live_source)

    print("[data-source-manager] Initialized with 4 data sources")
    return data_source_manager
