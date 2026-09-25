"""
incident_replay.py
V2 Incident Timeline & Replay System.

Creates structured incident timelines from stored system events and
supports replay of incident sequences using actual stored data.

Features:
- Incident timeline reconstruction from event history
- Multi-event correlation timeline
- Time-ordered event sequence with context
- Event-to-incident causal chain visualization data
- Replay data preparation (step-by-step state reconstruction)

Uses ACTUAL stored system events only.
No fabricated historical events.

DATA CLASSIFICATION: EVENT HISTORY (uses stored events from persistence layer)
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from collections import defaultdict


class IncidentReplay:
    """
    Reconstructs incident timelines from stored system events
    and supports replay of incident sequences.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def build_timeline(
        self,
        bus_id: str,
        events: List[Dict],
        risk_history: List[Dict] = None,
        incidents: List[Dict] = None,
        time_window_minutes: int = 60,
    ) -> Dict:
        """
        Build a chronological timeline of events for a bus.

        Uses actual stored events only. No fabrication.
        """
        risk_history = risk_history or []
        incidents = incidents or []

        # Filter events for this bus within time window
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)
        bus_events = []

        for event in events:
            if event.get("bus_id") != bus_id:
                continue
            e_ts = event.get("timestamp", "")
            try:
                e_dt = datetime.fromisoformat(e_ts.replace("Z", "+00:00"))
                if e_dt >= cutoff:
                    bus_events.append(event)
            except (ValueError, TypeError):
                pass

        # Sort by timestamp
        bus_events.sort(key=lambda e: e.get("timestamp", ""))

        # Build timeline entries
        timeline = []
        for event in bus_events:
            entry = self._event_to_timeline_entry(event)
            timeline.append(entry)

        # Add risk state changes
        for rh in risk_history:
            if rh.get("bus_id") == bus_id:
                entry = self._risk_to_timeline_entry(rh)
                if entry:
                    timeline.append(entry)

        # Add incident state changes
        for inc in incidents:
            if inc.get("bus_id") == bus_id:
                for tl_entry in inc.get("timeline", []):
                    timeline.append({
                        "timestamp": tl_entry.get("timestamp", ""),
                        "type": "INCIDENT_STATE_CHANGE",
                        "title": f"Incident {tl_entry.get('new_status', '')}",
                        "detail": tl_entry.get("details", ""),
                        "severity": "INFO",
                        "icon": "📋",
                    })

        # Sort all entries by timestamp
        timeline.sort(key=lambda t: t.get("timestamp", ""))

        # Build causal chain
        causal_chain = self._build_causal_chain(timeline)

        # Build summary
        summary = self._build_timeline_summary(timeline, bus_id)

        return {
            "bus_id": bus_id,
            "timeline": timeline,
            "total_events": len(timeline),
            "causal_chain": causal_chain,
            "summary": summary,
            "time_window_minutes": time_window_minutes,
            "data_source": "STORED EVENTS (no fabrication)",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def build_incident_replay(
        self,
        incident_id: str,
        events: List[Dict],
        incidents: List[Dict] = None,
    ) -> Dict:
        """
        Build a step-by-step replay of an incident from stored events.

        Returns ordered steps showing the incident progression.
        """
        incidents = incidents or []

        # Find the incident
        incident = None
        for inc in incidents:
            if inc.get("incident_id") == incident_id:
                incident = inc
                break

        if not incident:
            return {
                "incident_id": incident_id,
                "error": "Incident not found",
                "replay_steps": [],
            }

        # Get triggering event and related events
        triggering_event_id = incident.get("triggering_event_id", "")
        bus_id = incident.get("bus_id", "")
        category = incident.get("category", "")
        created_at = incident.get("created_at", "")

        # Find the triggering event
        triggering_event = None
        for e in events:
            if e.get("event_id") == triggering_event_id:
                triggering_event = e
                break

        # Build replay steps
        replay_steps = []

        # Step 1: Incident creation
        replay_steps.append({
            "step": 1,
            "timestamp": created_at,
            "type": "INCIDENT_CREATED",
            "title": f"Incident Created: {incident.get('event_type', '')}",
            "detail": (
                f"Bus {bus_id}: {incident.get('event_type', '')} "
                f"detected. Severity: {incident.get('severity', '')}. "
                f"Category: {category}."
            ),
            "severity": incident.get("severity", "INFO"),
            "state": "OPEN",
        })

        # Step 2: Triggering event details
        if triggering_event:
            replay_steps.append({
                "step": 2,
                "timestamp": triggering_event.get("timestamp", ""),
                "type": "TRIGGERING_EVENT",
                "title": f"Trigger: {triggering_event.get('event_type', '')}",
                "detail": (
                    f"Event severity: {triggering_event.get('severity', '')}. "
                    f"Location: ({triggering_event.get('latitude', 0):.4f}, "
                    f"{triggering_event.get('longitude', 0):.4f}). "
                    f"Source: {triggering_event.get('sensor_source', '')}."
                ),
                "severity": triggering_event.get("severity", "INFO"),
                "state": "TRIGGERED",
            })

        # Step 3: Context events (before the incident)
        related_events = [
            e for e in events
            if e.get("bus_id") == bus_id
            and e.get("event_id") != triggering_event_id
            and self._is_before(e.get("timestamp", ""), created_at)
        ]
        related_events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        step_num = 3
        for rel_event in related_events[:5]:  # Max 5 context events
            replay_steps.append({
                "step": step_num,
                "timestamp": rel_event.get("timestamp", ""),
                "type": "CONTEXT_EVENT",
                "title": f"Context: {rel_event.get('event_type', '')}",
                "detail": (
                    f"Prior event on bus {bus_id}: "
                    f"{rel_event.get('event_type', '')} "
                    f"({rel_event.get('severity', '')})."
                ),
                "severity": rel_event.get("severity", "INFO"),
                "state": "CONTEXT",
            })
            step_num += 1

        # Step 4: Incident timeline entries
        for tl_entry in incident.get("timeline", []):
            replay_steps.append({
                "step": step_num,
                "timestamp": tl_entry.get("timestamp", ""),
                "type": "INCIDENT_UPDATE",
                "title": f"Status: {tl_entry.get('new_status', '')}",
                "detail": tl_entry.get("details", ""),
                "severity": "INFO",
                "state": tl_entry.get("new_status", ""),
            })
            step_num += 1

        # Sort by timestamp
        replay_steps.sort(key=lambda s: s.get("timestamp", ""))

        # Renumber steps
        for i, step in enumerate(replay_steps):
            step["step"] = i + 1

        return {
            "incident_id": incident_id,
            "bus_id": bus_id,
            "event_type": incident.get("event_type", ""),
            "severity": incident.get("severity", ""),
            "category": category,
            "total_steps": len(replay_steps),
            "replay_steps": replay_steps,
            "summary": self._build_replay_summary(incident, replay_steps),
            "data_source": "STORED EVENTS (no fabrication)",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def get_event_sequence(
        self,
        bus_id: str,
        events: List[Dict],
        start_time: str = None,
        end_time: str = None,
    ) -> List[Dict]:
        """Get ordered event sequence for a bus within a time range."""
        bus_events = [e for e in events if e.get("bus_id") == bus_id]

        if start_time:
            bus_events = [
                e for e in bus_events
                if self._is_after(e.get("timestamp", ""), start_time)
            ]
        if end_time:
            bus_events = [
                e for e in bus_events
                if self._is_before(e.get("timestamp", ""), end_time)
            ]

        bus_events.sort(key=lambda e: e.get("timestamp", ""))
        return bus_events

    # ── Internal methods ──

    def _event_to_timeline_entry(self, event: Dict) -> Dict:
        """Convert an event to a timeline entry."""
        severity = event.get("severity", "INFO")
        icon_map = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
            "INFO": "🔵",
            "LOW": "⚪",
        }

        return {
            "timestamp": event.get("timestamp", ""),
            "type": "EVENT",
            "event_type": event.get("event_type", ""),
            "title": f"{event.get('event_type', 'EVENT')} ({severity})",
            "detail": self._build_event_detail(event),
            "severity": severity,
            "icon": icon_map.get(severity, "🔵"),
            "event_id": event.get("event_id", ""),
            "status": event.get("status", "ACTIVE"),
        }

    def _risk_to_timeline_entry(self, risk_record: Dict) -> Optional[Dict]:
        """Convert a risk history record to a timeline entry."""
        score = risk_record.get("risk_score")
        level = risk_record.get("risk_level")
        ts = risk_record.get("timestamp", "")

        if score is None or not ts:
            return None

        return {
            "timestamp": ts,
            "type": "RISK_CHANGE",
            "title": f"Risk: {level} ({score}/100)",
            "detail": f"Bus risk assessed at {score}/100 ({level})",
            "severity": level if level else "INFO",
            "icon": "🎯",
            "risk_score": score,
            "risk_level": level,
        }

    def _build_event_detail(self, event: Dict) -> str:
        """Build detailed description of an event."""
        event_type = event.get("event_type", "")
        additional = event.get("additional_data") or {}

        details = [f"Event: {event_type}"]
        if additional.get("note"):
            details.append(f"Note: {additional['note']}")
        if additional.get("fatigue_stage"):
            details.append(f"Fatigue: {additional['fatigue_stage']}")
        if additional.get("gvw_kg"):
            details.append(f"GVW: {additional['gvw_kg']} kg")

        return ". ".join(details)

    def _build_causal_chain(self, timeline: List[Dict]) -> List[Dict]:
        """Build causal chain from timeline events."""
        chain = []
        event_types_seen = set()

        for entry in timeline:
            if entry.get("type") == "EVENT":
                event_type = entry.get("event_type", "")
                if event_type not in event_types_seen:
                    event_types_seen.add(event_type)
                    chain.append({
                        "timestamp": entry.get("timestamp", ""),
                        "event_type": event_type,
                        "severity": entry.get("severity", "INFO"),
                        "description": entry.get("title", ""),
                    })

        return chain

    def _build_timeline_summary(
        self, timeline: List[Dict], bus_id: str
    ) -> Dict:
        """Build summary of the timeline."""
        total = len(timeline)
        events = sum(1 for t in timeline if t.get("type") == "EVENT")
        risk_changes = sum(1 for t in timeline if t.get("type") == "RISK_CHANGE")
        incidents = sum(1 for t in timeline if t.get("type") == "INCIDENT_STATE_CHANGE")

        critical = sum(1 for t in timeline if t.get("severity") == "CRITICAL")
        high = sum(1 for t in timeline if t.get("severity") == "HIGH")

        return {
            "bus_id": bus_id,
            "total_entries": total,
            "event_count": events,
            "risk_change_count": risk_changes,
            "incident_count": incidents,
            "critical_events": critical,
            "high_events": high,
            "has_escalation": critical > 0 or high > 0,
        }

    def _build_replay_summary(
        self, incident: Dict, steps: List[Dict]
    ) -> Dict:
        """Build summary of the incident replay."""
        return {
            "incident_id": incident.get("incident_id", ""),
            "event_type": incident.get("event_type", ""),
            "severity": incident.get("severity", ""),
            "category": incident.get("category", ""),
            "total_steps": len(steps),
            "time_span": self._compute_time_span(steps),
            "key_moments": [
                s for s in steps
                if s.get("type") in ("INCIDENT_CREATED", "TRIGGERING_EVENT", "INCIDENT_UPDATE")
            ][:5],
        }

    def _compute_time_span(self, steps: List[Dict]) -> str:
        """Compute time span of the replay."""
        if len(steps) < 2:
            return "N/A"

        first = steps[0].get("timestamp", "")
        last = steps[-1].get("timestamp", "")

        try:
            t1 = datetime.fromisoformat(first.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(last.replace("Z", "+00:00"))
            diff = (t2 - t1).total_seconds()
            if diff < 60:
                return f"{diff:.0f} seconds"
            elif diff < 3600:
                return f"{diff / 60:.1f} minutes"
            else:
                return f"{diff / 3600:.1f} hours"
        except (ValueError, TypeError):
            return "N/A"

    @staticmethod
    def _is_before(ts1: str, ts2: str) -> bool:
        try:
            t1 = datetime.fromisoformat(ts1.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(ts2.replace("Z", "+00:00"))
            return t1 < t2
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _is_after(ts1: str, ts2: str) -> bool:
        try:
            t1 = datetime.fromisoformat(ts1.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(ts2.replace("Z", "+00:00"))
            return t1 > t2
        except (ValueError, TypeError):
            return False


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
incident_replay = IncidentReplay()
