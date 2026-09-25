"""
persistence.py
Lightweight SQLite persistence layer for the FLEET-IQ event/incident log.

Sits beneath the in-memory EventStore:
  - every event is written to SQLite as it enters the store,
  - history is reloaded into the in-memory store on backend startup,
  - incident/event status changes (ack / review / resolve / status overrides)
    are re-persisted so the log survives backend restarts.

Python standard library only (sqlite3). No ORM, no external framework.
Simulation/live labels are stored verbatim per event, so history stays
correctly labelled across restarts.
"""

import json
import sqlite3
import threading
from pathlib import Path

DB_PATH = None
_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    event_type      TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    bus_id          TEXT,
    route_code      TEXT,
    severity        TEXT,
    status          TEXT,
    data_source     TEXT,
    simulation      INTEGER,
    latitude        REAL,
    longitude       REAL,
    sensor_source   TEXT,
    confidence      REAL,
    details         TEXT,
    reviewed_by     TEXT,
    acknowledged_by TEXT,
    resolved_by     TEXT,
    updated_by      TEXT,
    payload         TEXT NOT NULL
);
"""

# Authentication tables (Phase 5). Created idempotently alongside the event
# log so existing databases migrate in place without deleting history.
# Passwords are NEVER stored plaintext; only pbkdf2-hmac hashes live here
# (see auth.py). Sessions are opaque server-side bearer tokens with expiry.
_SCHEMA_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('operator', 'supervisor', 'admin')),
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""

_SCHEMA_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  REAL NOT NULL
);
"""

# Phase 12 — road intelligence persistence
_SCHEMA_ROAD_CLUSTERS = """
CREATE TABLE IF NOT EXISTS road_clusters (
    cluster_id      TEXT PRIMARY KEY,
    representative_lat REAL NOT NULL,
    representative_lon REAL NOT NULL,
    radius_m        INTEGER NOT NULL DEFAULT 200,
    event_count     INTEGER NOT NULL DEFAULT 0,
    severity        TEXT NOT NULL DEFAULT 'INFO',
    first_detected  TEXT NOT NULL,
    last_detected   TEXT NOT NULL,
    affected_buses  TEXT NOT NULL DEFAULT '[]',
    affected_routes TEXT NOT NULL DEFAULT '[]',
    source          TEXT NOT NULL DEFAULT 'UNKNOWN',
    status          TEXT NOT NULL DEFAULT 'ACTIVE',
    evidence        TEXT NOT NULL DEFAULT '',
    event_types     TEXT NOT NULL DEFAULT '[]',
    payload         TEXT NOT NULL DEFAULT '{}'
);
"""

_SCHEMA_ROAD_RISK_ZONES = """
CREATE TABLE IF NOT EXISTS road_risk_zones (
    zone_id         TEXT PRIMARY KEY,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    radius_m        INTEGER NOT NULL DEFAULT 200,
    risk_score      REAL NOT NULL DEFAULT 0,
    risk_level      TEXT NOT NULL DEFAULT 'LOW',
    defect_count    INTEGER NOT NULL DEFAULT 0,
    total_detections INTEGER NOT NULL DEFAULT 0,
    routes_affected TEXT NOT NULL DEFAULT '[]',
    affected_buses  TEXT NOT NULL DEFAULT '[]',
    top_defect_type TEXT NOT NULL DEFAULT 'pothole',
    evidence        TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'UNKNOWN',
    first_detected  TEXT NOT NULL,
    last_detected   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at      TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}'
);
"""


def default_db_path():
    return Path(__file__).resolve().parent / "data" / "control_centre.db"


def init_db(path=None, force=False):
    """Initialise the SQLite database (idempotent). Returns the DB path."""
    global DB_PATH
    if DB_PATH is not None and not force:
        return DB_PATH
    target = Path(path) if path else default_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        DB_PATH = str(target)
        conn = _conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(_SCHEMA)
            conn.execute(_SCHEMA_USERS)
            conn.execute(_SCHEMA_SESSIONS)
            conn.execute(_SCHEMA_ROAD_CLUSTERS)
            conn.execute(_SCHEMA_ROAD_RISK_ZONES)
            conn.commit()
        finally:
            conn.close()
    return DB_PATH


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _enabled():
    return DB_PATH is not None


def save_event(event):
    """Persist a single event (INSERT OR REPLACE keyed on event_id). No-op
    until init_db() has been called.

    Phase 19: Records health status for persistence operations.
    """
    if not _enabled():
        return
    ev = dict(event)
    ev.setdefault("timestamp", "")
    conn = _conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO events (
                event_id, event_type, timestamp, bus_id, route_code, severity,
                status, data_source, simulation, latitude, longitude,
                sensor_source, confidence, details, reviewed_by,
                acknowledged_by, resolved_by, updated_by, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ev.get("event_id", ""),
                ev.get("event_type", ""),
                str(ev.get("timestamp", "")),
                ev.get("bus_id"),
                ev.get("route_code"),
                ev.get("severity"),
                ev.get("status"),
                ev.get("data_source"),
                int(1) if ev.get("simulation") else 0,
                ev.get("latitude"),
                ev.get("longitude"),
                ev.get("sensor_source"),
                ev.get("confidence"),
                ev.get("details"),
                ev.get("reviewed_by"),
                ev.get("acknowledged_by"),
                ev.get("resolved_by"),
                ev.get("updated_by"),
                json.dumps(ev, default=str),
            ),
        )
        conn.commit()
        # Phase 19: Record successful persistence
        _record_persistence_success()
    except Exception as exc:
        # Phase 19: Record persistence failure
        _record_persistence_failure(str(exc))
        raise
    finally:
        conn.close()


def _record_persistence_success():
    """Record successful persistence operation for health tracking."""
    try:
        from system_health import record_subsystem_success
        record_subsystem_success("persistence")
    except ImportError:
        pass


def _record_persistence_failure(error: str):
    """Record failed persistence operation for health tracking."""
    try:
        from system_health import record_subsystem_failure
        record_subsystem_failure("persistence", error, critical=False)
    except ImportError:
        pass


def load_events():
    """Load all persisted events in chronological order (oldest first)."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT payload FROM events ORDER BY rowid ASC"
        ).fetchall()
        events = []
        for row in rows:
            try:
                events.append(json.loads(row["payload"]))
            except (TypeError, ValueError):
                pass
        return events
    finally:
        conn.close()


def count_events():
    if not _enabled():
        return 0
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()


def truncate():
    """Delete all persisted rows (events, users, sessions, road data). Used by
    tests for full isolation."""
    if not _enabled():
        return
    conn = _conn()
    try:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM road_clusters")
        conn.execute("DELETE FROM road_risk_zones")
        try:
            conn.execute("DELETE FROM eta_snapshots")
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM load_snapshots")
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM risk_events")
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM incidents")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 12 — road intelligence persistence
# ---------------------------------------------------------------------------

def save_road_cluster(cluster: dict) -> None:
    """Persist a road cluster (INSERT OR REPLACE keyed on cluster_id)."""
    if not _enabled():
        return
    conn = _conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO road_clusters (
                cluster_id, representative_lat, representative_lon, radius_m,
                event_count, severity, first_detected, last_detected,
                affected_buses, affected_routes, source, status, evidence,
                event_types, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cluster.get("cluster_id", ""),
                cluster.get("representative_lat", 0),
                cluster.get("representative_lon", 0),
                cluster.get("radius_m", 200),
                cluster.get("event_count", 0),
                cluster.get("severity", "INFO"),
                cluster.get("first_detected", ""),
                cluster.get("last_detected", ""),
                json.dumps(cluster.get("affected_buses", [])),
                json.dumps(cluster.get("affected_routes", [])),
                cluster.get("source", "UNKNOWN"),
                cluster.get("status", "ACTIVE"),
                cluster.get("evidence", ""),
                json.dumps(cluster.get("event_types", [])),
                json.dumps(cluster, default=str),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_road_clusters() -> list:
    """Load all persisted road clusters."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT payload FROM road_clusters ORDER BY rowid ASC"
        ).fetchall()
        clusters = []
        for row in rows:
            try:
                clusters.append(json.loads(row["payload"]))
            except (TypeError, ValueError):
                pass
        return clusters
    finally:
        conn.close()


def save_road_risk_zone(zone: dict) -> None:
    """Persist a road risk zone (INSERT OR REPLACE keyed on zone_id)."""
    if not _enabled():
        return
    conn = _conn()
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT OR REPLACE INTO road_risk_zones (
                zone_id, lat, lon, radius_m, risk_score, risk_level,
                defect_count, total_detections, routes_affected, affected_buses,
                top_defect_type, evidence, source, first_detected, last_detected,
                status, created_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                zone.get("zone_id", ""),
                zone.get("lat", 0),
                zone.get("lon", 0),
                zone.get("radius_m", 200),
                zone.get("risk_score", 0),
                zone.get("risk_level", "LOW"),
                zone.get("defect_count", 0),
                zone.get("total_detections", 0),
                json.dumps(zone.get("routes_affected", [])),
                json.dumps(zone.get("affected_buses", [])),
                zone.get("top_defect_type", "pothole"),
                zone.get("evidence", ""),
                zone.get("source", "UNKNOWN"),
                zone.get("first_detected", ""),
                zone.get("last_detected", ""),
                zone.get("status", "ACTIVE"),
                now,
                json.dumps(zone, default=str),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_road_risk_zones() -> list:
    """Load all persisted road risk zones."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT payload FROM road_risk_zones ORDER BY rowid ASC"
        ).fetchall()
        zones = []
        for row in rows:
            try:
                zones.append(json.loads(row["payload"]))
            except (TypeError, ValueError):
                pass
        return zones
    finally:
        conn.close()


# lazy import for utcnow_iso in save functions
from datetime import datetime, timezone


def _ensure_eta_table(conn):
    """Create eta_snapshots table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eta_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_id TEXT NOT NULL,
            delay_summary TEXT,
            total_remaining_distance_km REAL,
            total_remaining_time_sec REAL,
            delay_causes_json TEXT,
            source TEXT,
            simulation INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    conn.commit()


def persist_eta_snapshot(bus_id: str, delay_summary: str, total_remaining_distance_km: float,
                         total_remaining_time_sec: float, delay_causes: list,
                         source: str = "HEURISTIC", simulation: bool = True):
    """Persist a meaningful ETA snapshot for a bus. Called periodically."""
    if not _enabled():
        return
    conn = _conn()
    try:
        _ensure_eta_table(conn)
        conn.execute("""
            INSERT INTO eta_snapshots
            (bus_id, delay_summary, total_remaining_distance_km, total_remaining_time_sec,
             delay_causes_json, source, simulation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bus_id,
            delay_summary,
            total_remaining_distance_km,
            total_remaining_time_sec,
            json.dumps(delay_causes) if delay_causes else "[]",
            source,
            1 if simulation else 0,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def load_eta_snapshots(bus_id: str = None, limit: int = 100) -> list:
    """Load recent ETA snapshots. If bus_id given, filter to that bus."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        _ensure_eta_table(conn)
        if bus_id:
            rows = conn.execute(
                "SELECT * FROM eta_snapshots WHERE bus_id = ? ORDER BY rowid DESC LIMIT ?",
                (bus_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM eta_snapshots ORDER BY rowid DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 14 — load/occupancy persistence
# ---------------------------------------------------------------------------

def _ensure_load_table(conn):
    """Create load_snapshots table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS load_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_id TEXT NOT NULL,
            route_code TEXT,
            passengers INTEGER,
            capacity INTEGER,
            utilization_pct REAL,
            load_state TEXT,
            crowd_level TEXT,
            source TEXT,
            simulation INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    conn.commit()


def persist_load_snapshot(bus_id: str, route_code: str, passengers: int,
                          capacity: int, utilization_pct: float,
                          load_state: str, crowd_level: str,
                          source: str = "HEURISTIC", simulation: bool = True):
    """Persist a meaningful load snapshot. Called on significant state changes."""
    if not _enabled():
        return
    conn = _conn()
    try:
        _ensure_load_table(conn)
        conn.execute("""
            INSERT INTO load_snapshots
            (bus_id, route_code, passengers, capacity, utilization_pct,
             load_state, crowd_level, source, simulation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bus_id, route_code, passengers, capacity, utilization_pct,
            load_state, crowd_level, source, 1 if simulation else 0,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def load_load_snapshots(bus_id: str = None, limit: int = 100) -> list:
    """Load recent load snapshots. If bus_id given, filter to that bus."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        _ensure_load_table(conn)
        if bus_id:
            rows = conn.execute(
                "SELECT * FROM load_snapshots WHERE bus_id = ? ORDER BY rowid DESC LIMIT ?",
                (bus_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM load_snapshots ORDER BY rowid DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_route_demand_history(route_code: str, limit: int = 50) -> list:
    """Load recent load snapshots for a route (for demand analysis)."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        _ensure_load_table(conn)
        rows = conn.execute(
            "SELECT * FROM load_snapshots WHERE route_code = ? ORDER BY rowid DESC LIMIT ?",
            (route_code, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 15 — risk event persistence
# ---------------------------------------------------------------------------

def _ensure_risk_table(conn):
    """Create risk_events table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            risk_score REAL,
            risk_level TEXT,
            from_state TEXT,
            to_state TEXT,
            from_score REAL,
            to_score REAL,
            evidence TEXT,
            top_contributors TEXT,
            cross_system_evidence TEXT,
            data_coverage TEXT,
            data_quality TEXT,
            simulation INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    conn.commit()


def persist_risk_event(bus_id: str, event_type: str, risk_score: float,
                       risk_level: str, from_state: str = None,
                       to_state: str = None, from_score: float = None,
                       to_score: float = None, evidence: list = None,
                       top_contributors: list = None,
                       cross_system_evidence: list = None,
                       data_coverage: str = None, data_quality: str = None,
                       simulation: bool = True):
    """Persist a meaningful risk event (state transition, critical risk, etc.)."""
    if not _enabled():
        return
    conn = _conn()
    try:
        _ensure_risk_table(conn)
        conn.execute("""
            INSERT INTO risk_events
            (bus_id, event_type, risk_score, risk_level, from_state, to_state,
             from_score, to_score, evidence, top_contributors,
             cross_system_evidence, data_coverage, data_quality, simulation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bus_id,
            event_type,
            risk_score,
            risk_level,
            from_state,
            to_state,
            from_score,
            to_score,
            json.dumps(evidence) if evidence else "[]",
            json.dumps(top_contributors) if top_contributors else "[]",
            json.dumps(cross_system_evidence) if cross_system_evidence else "[]",
            data_coverage,
            data_quality,
            1 if simulation else 0,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def load_risk_events(bus_id: str = None, limit: int = 100) -> list:
    """Load recent risk events. If bus_id given, filter to that bus."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        _ensure_risk_table(conn)
        if bus_id:
            rows = conn.execute(
                "SELECT * FROM risk_events WHERE bus_id = ? ORDER BY rowid DESC LIMIT ?",
                (bus_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM risk_events ORDER BY rowid DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 16 — incident intelligence persistence
# ---------------------------------------------------------------------------

def _ensure_incidents_table(conn):
    """Create incidents table if it doesn't exist. Extended lifecycle support."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id     TEXT PRIMARY KEY,
            title           TEXT,
            category        TEXT,
            severity        TEXT,
            priority        TEXT,
            status          TEXT,
            bus_id          TEXT,
            route           TEXT,
            location        TEXT,
            source          TEXT,
            data_source     TEXT,
            description     TEXT,
            evidence        TEXT,
            related_event_ids TEXT,
            related_alert_ids TEXT,
            risk_info       TEXT,
            created_at      TEXT,
            updated_at      TEXT,
            acknowledged_by TEXT,
            acknowledged_at TEXT,
            resolved_by     TEXT,
            resolved_at     TEXT,
            investigation_notes TEXT,
            timeline        TEXT,
            event_count     INTEGER,
            assigned_to     TEXT,
            assigned_at     TEXT,
            responding_at   TEXT,
            confirmed_at    TEXT,
            response_time_seconds REAL,
            resolution_time_seconds REAL,
            payload         TEXT NOT NULL
        )
    """)
    # Add new columns if they don't exist (migration for existing databases)
    for col, default in [
        ("assigned_to", "NULL"), ("assigned_at", "NULL"),
        ("responding_at", "NULL"), ("confirmed_at", "NULL"),
        ("response_time_seconds", "NULL"), ("resolution_time_seconds", "NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE incidents ADD COLUMN {col} TEXT")
        except Exception:
            pass
    conn.commit()


def save_incident(incident: dict) -> None:
    """Persist an incident (INSERT OR REPLACE keyed on incident_id)."""
    if not _enabled():
        return
    conn = _conn()
    try:
        _ensure_incidents_table(conn)
        conn.execute("""
            INSERT OR REPLACE INTO incidents (
                incident_id, title, category, severity, priority, status,
                bus_id, route, location, source, data_source, description,
                evidence, related_event_ids, related_alert_ids, risk_info,
                created_at, updated_at, acknowledged_by, acknowledged_at,
                resolved_by, resolved_at, investigation_notes, timeline,
                event_count, assigned_to, assigned_at, responding_at,
                confirmed_at, response_time_seconds, resolution_time_seconds,
                payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident.get("incident_id", ""),
            incident.get("title", ""),
            incident.get("category", "SYSTEM"),
            incident.get("severity", "MEDIUM"),
            incident.get("priority", "MEDIUM"),
            incident.get("status", "OPEN"),
            incident.get("bus_id"),
            incident.get("route"),
            incident.get("location"),
            incident.get("source", "SYSTEM"),
            incident.get("data_source", "SIMULATION"),
            incident.get("description", ""),
            json.dumps(incident.get("evidence", [])),
            json.dumps(incident.get("related_event_ids", [])),
            json.dumps(incident.get("related_alert_ids", [])),
            json.dumps(incident.get("risk_info", {})),
            incident.get("created_at", ""),
            incident.get("updated_at", ""),
            incident.get("acknowledged_by"),
            incident.get("acknowledged_at"),
            incident.get("resolved_by"),
            incident.get("resolved_at"),
            json.dumps(incident.get("investigation_notes", [])),
            json.dumps(incident.get("timeline", [])),
            incident.get("event_count", 0),
            incident.get("assigned_to"),
            incident.get("assigned_at"),
            incident.get("responding_at"),
            incident.get("confirmed_at"),
            incident.get("response_time_seconds"),
            incident.get("resolution_time_seconds"),
            json.dumps(incident, default=str),
        ))
        conn.commit()
    finally:
        conn.close()


def load_incidents() -> list:
    """Load all persisted incidents."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        _ensure_incidents_table(conn)
        rows = conn.execute(
            "SELECT payload FROM incidents ORDER BY rowid DESC"
        ).fetchall()
        incidents = []
        for row in rows:
            try:
                incidents.append(json.loads(row["payload"]))
            except (TypeError, ValueError):
                pass
        return incidents
    finally:
        conn.close()


def load_incidents_for_bus(bus_id: str, limit: int = 50) -> list:
    """Load recent incidents for a specific bus."""
    if not _enabled():
        return []
    conn = _conn()
    try:
        _ensure_incidents_table(conn)
        rows = conn.execute(
            "SELECT payload FROM incidents WHERE bus_id = ? ORDER BY rowid DESC LIMIT ?",
            (bus_id, limit)
        ).fetchall()
        incidents = []
        for row in rows:
            try:
                incidents.append(json.loads(row["payload"]))
            except (TypeError, ValueError):
                pass
        return incidents
    finally:
        conn.close()


def load_incident(incident_id: str) -> dict:
    """Load a single incident by ID."""
    if not _enabled():
        return None
    conn = _conn()
    try:
        _ensure_incidents_table(conn)
        row = conn.execute(
            "SELECT payload FROM incidents WHERE incident_id = ?",
            (incident_id,)
        ).fetchone()
        if row:
            return json.loads(row["payload"])
        return None
    finally:
        conn.close()