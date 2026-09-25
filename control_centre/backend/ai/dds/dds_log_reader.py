"""
dds_log_reader.py
Reads DDS session logs and converts them to FLEET-IQ events.

The original DDS logs events to:
    src/logs/events_*.csv
    src/logs/summary_*.txt

This module reads those logs and converts them to FLEET-IQ event format.
"""

import csv
import glob
import os
import time
from datetime import datetime, timezone

DDS_LOG_DIR = "/home/rohith/Documents/D.D.S/DriverDrowsinessDetectionSystem/src/logs"


def get_dds_log_files():
    """Get all DDS log files sorted by modification time (newest first)."""
    pattern = os.path.join(DDS_LOG_DIR, "events_*.csv")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def get_dds_summary_files():
    """Get all DDS summary files sorted by modification time (newest first)."""
    pattern = os.path.join(DDS_LOG_DIR, "summary_*.txt")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def read_dds_events(log_file, since_timestamp=None):
    """Read DDS event log and convert to FLEET-IQ event format.

    DDS CSV format (from enhanced_logger.py):
        timestamp, event, details

    Returns list of FLEET-IQ compatible event dicts.
    """
    events = []
    if not os.path.exists(log_file):
        return events

    try:
        with open(log_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                timestamp_str = row.get("timestamp", "")
                event_type = row.get("event", "")
                details = row.get("details", "")

                # Parse timestamp
                try:
                    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    if since_timestamp and ts < since_timestamp:
                        continue
                except:
                    ts = datetime.now(timezone.utc)

                # Map DDS events to FLEET-IQ event types
                fleet_event = _map_dds_event(event_type, details, ts)
                if fleet_event:
                    events.append(fleet_event)

    except Exception as e:
        print(f"[dds_log_reader] Error reading {log_file}: {e}")

    return events


def read_dds_summary(summary_file):
    """Read DDS summary file and extract session statistics."""
    if not os.path.exists(summary_file):
        return None

    try:
        with open(summary_file, "r") as f:
            content = f.read()
        return content
    except Exception as e:
        print(f"[dds_log_reader] Error reading {summary_file}: {e}")
        return None


def get_latest_dds_session():
    """Get the most recent DDS session summary."""
    summaries = get_dds_summary_files()
    if not summaries:
        return None

    content = read_dds_summary(summaries[0])
    if not content:
        return None

    return {
        "file": summaries[0],
        "content": content,
        "timestamp": datetime.fromtimestamp(
            os.path.getmtime(summaries[0]), tz=timezone.utc
        ).isoformat(),
    }


def _map_dds_event(dds_event, details, timestamp):
    """Map a DDS event type to FLEET-IQ event format."""
    # Map DDS event names to FLEET-IQ event types
    event_mapping = {
        "DROWSINESS DETECTED": "DRIVER_DROWSINESS",
        "DROWSINESS DETECTED (PERCLOS)": "DRIVER_DROWSINESS",
        "HEAD NOD DETECTED": "DRIVER_DROWSINESS",
        "HEAD POSE ALERT": "DRIVER_DROWSINESS",
        "EYES CLOSED": "DRIVER_DROWSINESS",
        "PHONE USE DETECTED": "DRIVER_DISTRACTION",
        "DRINKING DETECTED": "DRIVER_DISTRACTION",
        "EMERGENCY_STOP": "DRIVER_EMERGENCY_STOP",
        "SESSION_START": "DDS_SESSION_START",
        "SESSION_END": "DDS_SESSION_END",
        "CALIBRATION": "DDS_CALIBRATION",
    }

    fleet_event_type = event_mapping.get(dds_event)
    if not fleet_event_type:
        return None

    # Determine severity
    severity = "INFO"
    if "DROWSINESS" in dds_event or "EMERGENCY" in dds_event:
        severity = "CRITICAL"
    elif "HEAD" in dds_event or "CLOSED" in dds_event:
        severity = "WARNING"
    elif "PHONE" in dds_event or "DRINK" in dds_event:
        severity = "INFO"

    return {
        "event_type": fleet_event_type,
        "bus_id": "PROTO-001",
        "camera_id": "driver",
        "data_source": "live",
        "timestamp": timestamp.isoformat(),
        "dds_event": dds_event,
        "details": details,
        "severity": severity,
    }
