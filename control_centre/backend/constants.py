"""
constants.py
Shared constants and utilities for the Rapid Tracker backend.

Centralizes severity ranks, priority ranks, status definitions,
and time utilities to avoid duplication across modules.
"""

from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Chennai IST timezone (UTC+5:30)
# ---------------------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    """Return current time in IST."""
    return datetime.now(IST)


def now_utc():
    """Return current time in UTC."""
    return datetime.now(timezone.utc)


def now_iso():
    """Return current UTC time as ISO string."""
    return now_utc().isoformat(timespec="seconds")


def to_ist(dt_str):
    """Convert an ISO datetime string to IST datetime. Handles Z suffix."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return dt.astimezone(IST)
    except (ValueError, TypeError):
        return None


def to_ist_hour(dt_str):
    """Extract the IST hour (0-23) from an ISO datetime string."""
    ist_dt = to_ist(dt_str)
    if ist_dt:
        return ist_dt.hour
    return None


def parse_timestamp(ts):
    """Parse an ISO timestamp string to a datetime object (UTC-aware)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Severity and priority ranks (shared across all modules)
# ---------------------------------------------------------------------------

INCIDENT_SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
INCIDENT_PRIORITIES = ("LOW", "MEDIUM", "HIGH", "URGENT")
INCIDENT_STATUSES_ORIGINAL = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "CLOSED")

# Extended lifecycle statuses (Phase C)
INCIDENT_STATUSES_EXTENDED = (
    "DETECTED", "CONFIRMED", "ASSIGNED", "RESPONDING",
    "OPEN", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "CLOSED"
)

SEVERITY_RANK = {s: i for i, s in enumerate(INCIDENT_SEVERITIES)}
PRIORITY_RANK = {p: i for i, p in enumerate(INCIDENT_PRIORITIES)}

# Event severity to incident severity mapping
EVENT_TO_INCIDENT_SEVERITY = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "WARNING": "MEDIUM",
    "INFO": "LOW",
}

# Risk level to severity mapping
RISK_LEVEL_SEVERITY = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MODERATE": "WARNING",
    "MEDIUM": "WARNING",
    "LOW": None,
}

# Road index risk levels
ROAD_INDEX_RISKY = {"HIGH", "CRITICAL"}
