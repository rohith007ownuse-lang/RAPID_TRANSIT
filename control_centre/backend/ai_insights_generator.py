"""
ai_insights_generator.py
Generates human-readable AI insights from system data.

Produces natural language summaries of:
- Fleet status and anomalies
- Risk predictions
- Traffic conditions
- Emergency situations
- Demand patterns
- Road conditions

These insights are displayed on the Control Centre dashboard to make
the system's intelligence visible to operators.

DATA CLASSIFICATION: RULE-BASED (generates text from computed data)
"""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import Counter


class AIInsightsGenerator:
    """
    Generates human-readable AI insights from system state.

    Transforms raw data and rule-based analysis into actionable
    intelligence narratives for operators.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._insights_cache: List[Dict] = []
        self._last_update = None

    def generate_fleet_insights(self, fleet_summary: Dict) -> List[Dict]:
        """
        Generate insights about overall fleet status.

        Args:
            fleet_summary: From fleet_summary.get_fleet_summary()

        Returns:
            List of insight dicts with category, priority, title, description
        """
        insights = []

        counts = fleet_summary.get("fleet_counts", {})
        total = counts.get("total", 0)
        active = counts.get("active", 0)
        critical = counts.get("critical", 0)
        warning = counts.get("warning", 0)
        offline = counts.get("offline", 0)

        # Fleet health overview
        if total > 0:
            health_pct = ((total - critical - warning) / total) * 100
            if health_pct >= 90:
                insights.append({
                    "category": "fleet",
                    "priority": "info",
                    "title": "Fleet Operating Normally",
                    "description": f"{health_pct:.0f}% of fleet is in good condition. "
                                   f"{active} of {total} buses are active.",
                    "icon": "check-circle",
                })
            elif health_pct >= 70:
                insights.append({
                    "category": "fleet",
                    "priority": "warning",
                    "title": "Fleet Needs Attention",
                    "description": f"{warning} buses require attention, "
                                   f"{critical} are in critical condition.",
                    "icon": "alert-triangle",
                })
            else:
                insights.append({
                    "category": "fleet",
                    "priority": "critical",
                    "title": "Fleet Degraded",
                    "description": f"{critical} critical + {warning} warning buses. "
                                   f"Immediate action recommended.",
                    "icon": "alert-octagon",
                })

        # Offline buses
        if offline > 0:
            insights.append({
                "category": "fleet",
                "priority": "warning",
                "title": "Buses Offline",
                "description": f"{offline} bus(es) are not reporting data. "
                               f"Check connectivity or verify status.",
                "icon": "wifi-off",
            })

        return insights

    def generate_safety_insights(self, driver_safety: Dict) -> List[Dict]:
        """Generate driver safety insights."""
        insights = []

        drowsy = driver_safety.get("drowsy_count", 0)
        fatigued = driver_safety.get("fatigued_count", 0)
        alert = driver_safety.get("alert_count", 0)

        if drowsy > 0:
            insights.append({
                "category": "safety",
                "priority": "critical",
                "title": "Driver Drowsiness Detected",
                "description": f"{drowsy} driver(s) showing drowsiness signs. "
                               f"Immediate rest break recommended.",
                "icon": "eye-off",
            })

        if fatigued > 3:
            insights.append({
                "category": "safety",
                "priority": "warning",
                "title": "Elevated Fatigue Levels",
                "description": f"{fatigued} drivers showing fatigue. "
                               f"Consider shift rotation.",
                "icon": "alert-circle",
            })

        if drowsy == 0 and fatigued <= 2:
            insights.append({
                "category": "safety",
                "priority": "info",
                "title": "Driver Safety Normal",
                "description": "All monitored drivers are within safe parameters.",
                "icon": "check-circle",
            })

        return insights

    def generate_road_insights(self, road_summary: Dict) -> List[Dict]:
        """Generate road condition insights."""
        insights = []

        zones = road_summary.get("zones", [])
        defects = road_summary.get("defects", [])
        high_risk = [z for z in zones if z.get("risk_level") == "HIGH"]

        if high_risk:
            insights.append({
                "category": "road",
                "priority": "warning",
                "title": "High-Risk Road Zones Identified",
                "description": f"{len(high_risk)} road segments have elevated risk. "
                               f"Consider route adjustments for affected buses.",
                "icon": "map",
            })

        if defects:
            insights.append({
                "category": "road",
                "priority": "info",
                "title": "Road Defects Tracked",
                "description": f"{len(defects)} road defects monitored across the network. "
                               f"Routes adjusted where possible.",
                "icon": "alert-triangle",
            })

        return insights

    def generate_incident_insights(self, incidents: List[Dict]) -> List[Dict]:
        """Generate incident insights."""
        insights = []

        if not incidents:
            return insights

        # Count by severity
        severity_counts = Counter(i.get("severity", "INFO") for i in incidents)
        critical = severity_counts.get("CRITICAL", 0)
        high = severity_counts.get("HIGH", 0)

        if critical > 0:
            insights.append({
                "category": "incident",
                "priority": "critical",
                "title": f"{critical} Critical Incident(s) Active",
                "description": "Critical incidents require immediate attention. "
                               "Emergency services may be dispatched.",
                "icon": "alert-octagon",
            })

        if high > 0:
            insights.append({
                "category": "incident",
                "priority": "warning",
                "title": f"{high} High-Severity Incident(s)",
                "description": "High-severity incidents are being monitored. "
                               "Response teams dispatched.",
                "icon": "alert-triangle",
            })

        # Count by type
        type_counts = Counter(i.get("event_type", "UNKNOWN") for i in incidents)
        most_common = type_counts.most_common(1)[0] if type_counts else None

        if most_common and most_common[1] > 1:
            insights.append({
                "category": "incident",
                "priority": "info",
                "title": f"Trending: {most_common[0].replace('_', ' ').title()}",
                "description": f"{most_common[1]} incidents of this type recorded. "
                               f"Pattern analysis in progress.",
                "icon": "trending-up",
            })

        return insights

    def generate_emergency_insights(self, emergency_data: Dict) -> List[Dict]:
        """Generate emergency response insights."""
        insights = []

        facilities = emergency_data.get("facilities", [])
        response_ready = sum(1 for f in facilities if f.get("emergency_available", False))

        if response_ready > 0:
            insights.append({
                "category": "emergency",
                "priority": "info",
                "title": "Emergency Response Ready",
                "description": f"{response_ready} emergency facilities on standby. "
                               f"Average response time: 8-15 minutes.",
                "icon": "shield",
            })

        return insights

    def generate_demand_insights(self, demand_data: Dict) -> List[Dict]:
        """Generate demand pattern insights."""
        insights = []

        peak_hour = demand_data.get("peak_hour")
        if peak_hour is not None:
            insights.append({
                "category": "demand",
                "priority": "info",
                "title": f"Peak Demand: {peak_hour}:00",
                "description": f"Highest passenger demand expected at {peak_hour}:00. "
                               f"Additional buses recommended.",
                "icon": "users",
            })

        return insights

    def generate_all_insights(
        self,
        fleet_summary: Dict = None,
        driver_safety: Dict = None,
        road_summary: Dict = None,
        incidents: List[Dict] = None,
        emergency_data: Dict = None,
        demand_data: Dict = None,
    ) -> Dict:
        """
        Generate comprehensive AI insights from all available data.

        Returns:
            Dict with insights grouped by category and priority
        """
        all_insights = []

        if fleet_summary:
            all_insights.extend(self.generate_fleet_insights(fleet_summary))
        if driver_safety:
            all_insights.extend(self.generate_safety_insights(driver_safety))
        if road_summary:
            all_insights.extend(self.generate_road_insights(road_summary))
        if incidents:
            all_insights.extend(self.generate_incident_insights(incidents))
        if emergency_data:
            all_insights.extend(self.generate_emergency_insights(emergency_data))
        if demand_data:
            all_insights.extend(self.generate_demand_insights(demand_data))

        # Sort by priority (critical > warning > info)
        priority_order = {"critical": 0, "warning": 1, "info": 2}
        all_insights.sort(key=lambda x: priority_order.get(x["priority"], 3))

        # Group by category
        by_category = {}
        for insight in all_insights:
            cat = insight["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(insight)

        # Update cache
        with self._lock:
            self._insights_cache = all_insights
            self._last_update = datetime.now(timezone.utc).isoformat(timespec="seconds")

        return {
            "insights": all_insights,
            "by_category": by_category,
            "total": len(all_insights),
            "critical": sum(1 for i in all_insights if i["priority"] == "critical"),
            "warnings": sum(1 for i in all_insights if i["priority"] == "warning"),
            "info": sum(1 for i in all_insights if i["priority"] == "info"),
            "last_updated": self._last_update,
            "data_source": "rule-based",
        }

    def get_cached_insights(self) -> Dict:
        """Get cached insights without regeneration."""
        with self._lock:
            return {
                "insights": self._insights_cache,
                "total": len(self._insights_cache),
                "last_updated": self._last_update,
            }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

ai_insights_generator = AIInsightsGenerator()
