"""
ai_copilot.py
V2 AI Control Centre Copilot.

Interactive query interface for operators to ask natural language questions
about fleet status, incidents, risks, and recommendations.

The copilot retrieves information from the system's actual APIs/data.
It does NOT invent fleet status, incidents, locations, statistics,
or recommendations.

Supported query categories:
- Fleet status queries
- Bus-specific queries
- Incident queries
- Risk queries
- Demand queries
- Emergency facility queries
- Route queries

DATA CLASSIFICATION: QUERY INTERFACE (retrieves from existing data stores)
No ML/LLM integration. Pattern-matched query routing to existing APIs.
"""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
import re


class AICopilot:
    """
    Interactive AI Copilot for the Control Centre.

    Routes natural language queries to appropriate system data sources
    and returns structured, honest responses.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._query_patterns = self._build_query_patterns()

    def query(self, question: str, context: Dict = None) -> Dict:
        """
        Process a natural language query and return system-sourced answer.

        Args:
            question: Operator's natural language question
            context: Optional context (current bus, route, etc.)

        Returns:
            Structured response with answer, data source, and confidence.
        """
        context = context or {}
        question_lower = question.lower().strip()

        # Match query to category
        query_match = self._match_query(question_lower)

        if not query_match:
            return {
                "answer": (
                    "I can help with fleet status, bus details, incidents, "
                    "risks, demand, and emergency facilities. "
                    "Please try rephrasing your question."
                ),
                "category": "UNKNOWN",
                "confidence": 0,
                "data_source": "NONE",
                "suggestions": self._get_suggestions(),
            }

        category = query_match["category"]
        params = query_match.get("params", {})

        # Route to appropriate handler
        handler_map = {
            "fleet_status": self._handle_fleet_status,
            "bus_status": self._handle_bus_status,
            "highest_risk": self._handle_highest_risk,
            "bus_risk": self._handle_bus_risk,
            "incidents": self._handle_incidents,
            "critical_incidents": self._handle_critical_incidents,
            "bus_history": self._handle_bus_history,
            "demand": self._handle_demand,
            "emergency": self._handle_emergency,
            "route_info": self._handle_route_info,
            "interventions": self._handle_interventions,
            "rebalancing": self._handle_rebalancing,
        }

        handler = handler_map.get(category)
        if handler:
            return handler(question, params, context)

        return {
            "answer": f"Query category '{category}' recognized but not yet implemented.",
            "category": category,
            "confidence": 0,
            "data_source": "SYSTEM",
        }

    def _build_query_patterns(self) -> List[Dict]:
        """Build regex patterns for query matching."""
        return [
            {
                "pattern": r"(?:which|what|show|list|how many).*(?:buses?|fleet).*(?:highest|risk|danger)",
                "category": "highest_risk",
            },
            {
                "pattern": r"(?:why|what|how).*(?:is|bus|route).*(?:high risk|risky|dangerous)",
                "category": "bus_risk",
            },
            {
                "pattern": r"(?:which|what|show|list).*(?:routes?|demand|passenger|ridership)",
                "category": "demand",
            },
            {
                "pattern": r"(?:show|what|which|list).*(?:critical|serious|severe).*(?:incidents?|alerts?)",
                "category": "critical_incidents",
            },
            {
                "pattern": r"(?:what|show|list).*(?:happened|events?|history|timeline).*(?:bus|route)",
                "category": "bus_history",
            },
            {
                "pattern": r"(?:which|what|show|recommend).*(?:emergency|hospital|fire|police|nearest)",
                "category": "emergency",
            },
            {
                "pattern": r"(?:what|show|need).*(?:intervention|action|attention|relief)",
                "category": "interventions",
            },
            {
                "pattern": r"(?:rebalance|deploy|additional|more buses|fleet management)",
                "category": "rebalancing",
            },
            {
                "pattern": r"(?:status|overview|summary|how is|fleet)",
                "category": "fleet_status",
            },
            {
                "pattern": r"(?:bus|route)\s*(\d+\w*|[A-Z]+-?\d+)",
                "category": "bus_status",
            },
            {
                "pattern": r"(?:incident|alert|event|active)",
                "category": "incidents",
            },
            {
                "pattern": r"(?:risk|risky|danger|safe|safety)",
                "category": "bus_risk",
            },
            {
                "pattern": r"(?:demand|passenger|ridership|capacity|overcrowd)",
                "category": "demand",
            },
        ]

    def _match_query(self, question: str) -> Optional[Dict]:
        """Match question to a query category."""
        for pattern_info in self._query_patterns:
            if re.search(pattern_info["pattern"], question, re.IGNORECASE):
                # Extract bus ID if present
                bus_match = re.search(
                    r"(?:bus|route)\s*(\d+\w*|[A-Z]+-?\d+)",
                    question, re.IGNORECASE
                )
                params = {}
                if bus_match:
                    params["bus_id"] = bus_match.group(1)

                return {
                    "category": pattern_info["category"],
                    "params": params,
                }
        return None

    # ── Query Handlers ──

    def _handle_fleet_status(self, question, params, context) -> Dict:
        """Handle fleet status overview queries."""
        from data_store import store
        from risk_engine import fleet_risk

        buses = store.get_buses()
        events = store.get_events(limit=100)
        risk_items = fleet_risk(buses)

        total = len(buses)
        active = sum(1 for b in buses if b.get("_live") or b.get("data_source") == "live")
        high_risk = sum(1 for r in risk_items if r.get("risk_level") in ("HIGH", "CRITICAL"))
        avg_risk = sum(r.get("risk_score", 0) for r in risk_items) / max(1, len(risk_items))

        # Count recent events
        recent_events = len(events)

        answer = (
            f"Fleet Overview: {total} buses total, {active} live-connected. "
            f"Average risk score: {avg_risk:.0f}/100. "
            f"{high_risk} bus(es) at HIGH/CRITICAL risk. "
            f"{recent_events} recent events in system."
        )

        return {
            "answer": answer,
            "category": "fleet_status",
            "data": {
                "total_buses": total,
                "active_buses": active,
                "avg_risk": round(avg_risk, 1),
                "high_risk_count": high_risk,
                "recent_events": recent_events,
            },
            "confidence": 1.0,
            "data_source": "LIVE SYSTEM DATA",
        }

    def _handle_bus_status(self, question, params, context) -> Dict:
        """Handle individual bus status queries."""
        from data_store import store

        bus_id = params.get("bus_id", context.get("bus_id", ""))
        if not bus_id:
            return {
                "answer": "Please specify a bus ID (e.g., 'Bus 247' or 'Bus PROTO-001').",
                "category": "bus_status",
                "confidence": 0,
                "data_source": "NONE",
            }

        bus = store.get_bus(bus_id)
        if not bus:
            return {
                "answer": f"Bus {bus_id} not found in the system.",
                "category": "bus_status",
                "confidence": 0,
                "data_source": "SYSTEM",
            }

        driver = bus.get("driver") or {}
        vehicle = bus.get("vehicle") or {}
        risk = bus.get("risk") or {}
        load = bus.get("load") or {}

        answer = (
            f"Bus {bus_id} ({bus.get('route', 'Unknown route')}): "
            f"Speed {bus.get('speed_kmh', 0):.0f} km/h. "
            f"Driver: {driver.get('state', 'UNKNOWN')}. "
            f"Vehicle: {vehicle.get('health', 'UNKNOWN')}. "
            f"Risk: {risk.get('score', 0)}/100 ({risk.get('level', 'UNKNOWN')}). "
            f"Load: {load.get('status', 'UNKNOWN')}."
        )

        return {
            "answer": answer,
            "category": "bus_status",
            "data": {
                "bus_id": bus_id,
                "route": bus.get("route", ""),
                "speed": bus.get("speed_kmh", 0),
                "driver_state": driver.get("state", "UNKNOWN"),
                "vehicle_health": vehicle.get("health", "UNKNOWN"),
                "risk_score": risk.get("score", 0),
                "risk_level": risk.get("level", "UNKNOWN"),
                "load_status": load.get("status", "UNKNOWN"),
            },
            "confidence": 1.0,
            "data_source": "LIVE SYSTEM DATA",
        }

    def _handle_highest_risk(self, question, params, context) -> Dict:
        """Handle queries about highest risk buses."""
        from data_store import store
        from risk_engine import fleet_risk

        buses = store.get_buses()
        risk_items = fleet_risk(buses)

        # Sort by risk score
        risk_items.sort(key=lambda r: r.get("risk_score", 0), reverse=True)
        top_risk = risk_items[:5]

        if not top_risk:
            return {
                "answer": "No risk data available for the fleet.",
                "category": "highest_risk",
                "confidence": 0,
                "data_source": "SYSTEM",
            }

        lines = ["Highest risk buses:"]
        for i, r in enumerate(top_risk, 1):
            lines.append(
                f"{i}. Bus {r['bus_id']}: {r.get('risk_score', 0)}/100 "
                f"({r.get('risk_level', 'UNKNOWN')})"
            )

        answer = " ".join(lines)

        return {
            "answer": answer,
            "category": "highest_risk",
            "data": {
                "buses": [
                    {
                        "bus_id": r["bus_id"],
                        "risk_score": r.get("risk_score", 0),
                        "risk_level": r.get("risk_level", "UNKNOWN"),
                    }
                    for r in top_risk
                ]
            },
            "confidence": 1.0,
            "data_source": "LIVE RISK ENGINE",
        }

    def _handle_bus_risk(self, question, params, context) -> Dict:
        """Handle bus risk explanation queries."""
        from data_store import store
        from risk_engine import bus_risk

        bus_id = params.get("bus_id", "")
        if not bus_id:
            return {
                "answer": "Please specify a bus ID to check its risk.",
                "category": "bus_risk",
                "confidence": 0,
                "data_source": "NONE",
            }

        bus = store.get_bus(bus_id)
        if not bus:
            return {
                "answer": f"Bus {bus_id} not found.",
                "category": "bus_risk",
                "confidence": 0,
                "data_source": "SYSTEM",
            }

        events = store.get_events(limit=200)
        risk = bus_risk(bus, events)

        top_factors = risk.get("top_contributors", [])
        factors_str = ", ".join(
            f"{f.get('factor', '')} ({f.get('contribution_pct', 0)}%)"
            for f in top_factors[:3]
        )

        answer = (
            f"Bus {bus_id} risk: {risk.get('risk_score', 0)}/100 "
            f"({risk.get('risk_level', 'UNKNOWN')}). "
            f"Top factors: {factors_str if factors_str else 'none identified'}. "
            f"Trend: {risk.get('trend', 'UNKNOWN')}."
        )

        return {
            "answer": answer,
            "category": "bus_risk",
            "data": risk,
            "confidence": 1.0,
            "data_source": "LIVE RISK ENGINE",
        }

    def _handle_incidents(self, question, params, context) -> Dict:
        """Handle incident queries."""
        from data_store import store

        events = store.get_events(limit=50)
        active = [e for e in events if e.get("status") == "ACTIVE"]

        answer = (
            f"Active incidents: {len(active)}. "
            f"Total recent events: {len(events)}."
        )

        if active:
            top_3 = active[:3]
            details = []
            for e in top_3:
                details.append(
                    f"- {e.get('event_type', '')} on Bus {e.get('bus_id', '')} "
                    f"({e.get('severity', '')})"
                )
            answer += " Top: " + "; ".join(details)

        return {
            "answer": answer,
            "category": "incidents",
            "data": {
                "active_count": len(active),
                "total_events": len(events),
                "top_events": [
                    {
                        "event_type": e.get("event_type", ""),
                        "bus_id": e.get("bus_id", ""),
                        "severity": e.get("severity", ""),
                    }
                    for e in active[:5]
                ],
            },
            "confidence": 1.0,
            "data_source": "LIVE EVENT STORE",
        }

    def _handle_critical_incidents(self, question, params, context) -> Dict:
        """Handle critical incident queries."""
        from data_store import store

        events = store.get_events(limit=100)
        critical = [
            e for e in events
            if e.get("severity") in ("HIGH", "CRITICAL")
            and e.get("status") == "ACTIVE"
        ]

        answer = (
            f"Critical/High severity active incidents: {len(critical)}."
        )

        if critical:
            for e in critical[:3]:
                answer += (
                    f" Bus {e.get('bus_id', '')}: "
                    f"{e.get('event_type', '')} ({e.get('severity', '')})."
                )

        return {
            "answer": answer,
            "category": "critical_incidents",
            "data": {
                "critical_count": len(critical),
                "incidents": [
                    {
                        "bus_id": e.get("bus_id", ""),
                        "event_type": e.get("event_type", ""),
                        "severity": e.get("severity", ""),
                        "timestamp": e.get("timestamp", ""),
                    }
                    for e in critical[:10]
                ],
            },
            "confidence": 1.0,
            "data_source": "LIVE EVENT STORE",
        }

    def _handle_bus_history(self, question, params, context) -> Dict:
        """Handle bus history/timeline queries."""
        from data_store import store

        bus_id = params.get("bus_id", "")
        if not bus_id:
            return {
                "answer": "Please specify a bus ID to view its history.",
                "category": "bus_history",
                "confidence": 0,
                "data_source": "NONE",
            }

        events = store.get_events(limit=200)
        bus_events = [e for e in events if e.get("bus_id") == bus_id]
        bus_events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        answer = f"Bus {bus_id}: {len(bus_events)} events recorded."
        if bus_events:
            recent = bus_events[:3]
            for e in recent:
                answer += (
                    f" {e.get('event_type', '')} ({e.get('severity', '')})"
                    f" at {e.get('timestamp', '')[:19]}."
                )

        return {
            "answer": answer,
            "category": "bus_history",
            "data": {
                "bus_id": bus_id,
                "total_events": len(bus_events),
                "recent_events": [
                    {
                        "event_type": e.get("event_type", ""),
                        "severity": e.get("severity", ""),
                        "timestamp": e.get("timestamp", ""),
                    }
                    for e in bus_events[:10]
                ],
            },
            "confidence": 1.0,
            "data_source": "LIVE EVENT STORE",
        }

    def _handle_demand(self, question, params, context) -> Dict:
        """Handle demand/passenger queries."""
        from data_store import store

        buses = store.get_buses()

        # Analyze occupancy
        total_occ = 0
        high_occ = 0
        for bus in buses:
            occ = (bus.get("occupancy") or {}).get("pct", 0)
            total_occ += occ
            if occ > 85:
                high_occ += 1

        avg_occ = total_occ / max(1, len(buses))

        answer = (
            f"Fleet average occupancy: {avg_occ:.0f}%. "
            f"{high_occ} bus(es) above 85% occupancy."
        )

        return {
            "answer": answer,
            "category": "demand",
            "data": {
                "avg_occupancy": round(avg_occ, 1),
                "high_occupancy_count": high_occ,
                "total_buses": len(buses),
            },
            "confidence": 1.0,
            "data_source": "LIVE OCCUPANCY DATA",
        }

    def _handle_emergency(self, question, params, context) -> Dict:
        """Handle emergency facility queries."""
        from emergency_data import emergency_store

        hospitals = emergency_store.get_all("hospital")
        fire = emergency_store.get_all("fire")
        police = emergency_store.get_all("police")

        answer = (
            f"Emergency facilities in database: "
            f"{len(hospitals)} hospitals, "
            f"{len(fire)} fire stations, "
            f"{len(police)} police stations."
        )

        return {
            "answer": answer,
            "category": "emergency",
            "data": {
                "hospitals": len(hospitals),
                "fire_stations": len(fire),
                "police_stations": len(police),
            },
            "confidence": 1.0,
            "data_source": "EMERGENCY FACILITY DATABASE",
        }

    def _handle_route_info(self, question, params, context) -> Dict:
        """Handle route information queries."""
        from data_store import store

        buses = store.get_buses()
        route_buses = {}
        for bus in buses:
            route = bus.get("route_code", "unknown")
            if route not in route_buses:
                route_buses[route] = []
            route_buses[route].append(bus.get("bus_id", ""))

        answer = f"Active routes: {len(route_buses)}. "
        for route, bus_list in list(route_buses.items())[:5]:
            answer += f"Route {route}: {len(bus_list)} buses. "

        return {
            "answer": answer,
            "category": "route_info",
            "data": {
                "routes": {r: len(b) for r, b in route_buses.items()},
            },
            "confidence": 1.0,
            "data_source": "LIVE FLEET DATA",
        }

    def _handle_interventions(self, question, params, context) -> Dict:
        """Handle intervention needs queries."""
        from data_store import store
        from risk_engine import fleet_risk

        buses = store.get_buses()
        events = store.get_events(limit=200)
        risk_items = fleet_risk(buses)

        needs_intervention = [
            r for r in risk_items
            if r.get("risk_level") in ("HIGH", "CRITICAL")
        ]

        answer = f"{len(needs_intervention)} bus(es) need intervention. "
        for r in needs_intervention[:3]:
            answer += (
                f"Bus {r['bus_id']}: risk {r.get('risk_score', 0)}/100. "
            )

        return {
            "answer": answer,
            "category": "interventions",
            "data": {
                "count": len(needs_intervention),
                "buses": [
                    {
                        "bus_id": r["bus_id"],
                        "risk_score": r.get("risk_score", 0),
                        "risk_level": r.get("risk_level", ""),
                    }
                    for r in needs_intervention
                ],
            },
            "confidence": 1.0,
            "data_source": "LIVE RISK ENGINE",
        }

    def _handle_rebalancing(self, question, params, context) -> Dict:
        """Handle fleet rebalancing queries."""
        from fleet_decision_engine import fleet_decision_engine
        from data_store import store
        from risk_engine import fleet_risk

        buses = store.get_buses()
        events = store.get_events(limit=100)
        risk_items = fleet_risk(buses)

        analysis = fleet_decision_engine.analyze_fleet(
            buses, events, {"risk_items": risk_items}
        )

        summary = analysis.get("summary", {})
        actions = analysis.get("priority_actions", [])

        answer = (
            f"Fleet health: {summary.get('fleet_health_score', 0)}/100. "
            f"{summary.get('total_actions', 0)} recommended actions "
            f"({summary.get('high_priority_actions', 0)} high priority)."
        )

        if actions:
            top = actions[0]
            answer += f" Top: {top.get('action', top.get('reason', ''))}"

        return {
            "answer": answer,
            "category": "rebalancing",
            "data": analysis,
            "confidence": 1.0,
            "data_source": "FLEET DECISION ENGINE",
        }

    def _get_suggestions(self) -> List[str]:
        """Return suggested queries."""
        return [
            "What is the fleet status?",
            "Which buses are at highest risk?",
            "Why is Bus 247 high risk?",
            "Show critical incidents",
            "What happened to Bus 247?",
            "Which emergency facility is recommended?",
            "Which buses need intervention?",
            "Show demand overview",
            "Rebalancing recommendations",
        ]


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
ai_copilot = AICopilot()
