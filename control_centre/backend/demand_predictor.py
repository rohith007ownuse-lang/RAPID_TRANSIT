"""
demand_predictor.py
V2 Predictive Demand & Overcrowding Intelligence.

Upgrades existing demand intelligence to predict:
- Predicted passenger demand (next 30/60 min)
- Overcrowding risk per route
- Capacity shortfall predictions
- Recommended deployment responses

Uses real GTFS route/stop data + simulated passenger telemetry.
Clearly labels simulated values.

DATA CLASSIFICATION: RULE-BASED PREDICTIVE
Uses time-of-day demand profiles + route characteristics.
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import math


# Time-of-day demand multiplier (IST hours)
DEMAND_MULTIPLIERS = {
    0: 0.15, 1: 0.10, 2: 0.08, 3: 0.05, 4: 0.10, 5: 0.25,
    6: 0.50, 7: 0.85, 8: 1.00, 9: 0.95, 10: 0.75, 11: 0.65,
    12: 0.70, 13: 0.65, 14: 0.60, 15: 0.65, 16: 0.80, 17: 0.95,
    18: 1.00, 19: 0.90, 20: 0.70, 21: 0.50, 22: 0.35, 23: 0.20,
}

# Overcrowding risk thresholds
OVERCROWDING_THRESHOLDS = {
    "LOW": (0, 30),
    "MODERATE": (30, 60),
    "HIGH": (60, 80),
    "CRITICAL": (80, 100),
}


class DemandPredictor:
    """
    Predicts future passenger demand and overcrowding risk per route.

    Uses time-of-day profiles + current occupancy + route characteristics
    to forecast demand 30-60 minutes ahead.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def predict_demand(
        self,
        buses: List[Dict],
        events: List[Dict] = None,
        minutes_ahead: int = 30,
    ) -> Dict:
        """
        Predict passenger demand for the fleet.

        Returns per-route predictions with overcrowding risk.
        """
        events = events or []

        # Group buses by route
        route_buses = defaultdict(list)
        for bus in buses:
            route = bus.get("route_code", "unknown")
            route_buses[route].append(bus)

        # Current time
        now = datetime.now(timezone.utc)
        # Convert to IST (UTC+5:30)
        ist_hour = (now.hour + 5) % 24  # Simplified IST conversion

        # Get current demand multiplier
        current_multiplier = DEMAND_MULTIPLIERS.get(ist_hour, 0.5)

        # Predict for future time
        future_now = now + timedelta(minutes=minutes_ahead)
        future_ist_hour = (future_now.hour + 5) % 24
        future_multiplier = DEMAND_MULTIPLIERS.get(future_ist_hour, 0.5)

        # Calculate predictions per route
        route_predictions = []
        for route_code, route_bus_list in route_buses.items():
            pred = self._predict_route_demand(
                route_code, route_bus_list, current_multiplier,
                future_multiplier, minutes_ahead
            )
            route_predictions.append(pred)

        # Sort by overcrowding risk
        route_predictions.sort(
            key=lambda p: p.get("overcrowding_risk_score", 0), reverse=True
        )

        # Fleet summary
        total_current_load = sum(
            p.get("current_avg_occupancy", 0) for p in route_predictions
        )
        avg_current = total_current_load / max(1, len(route_predictions))

        total_predicted_load = sum(
            p.get("predicted_avg_occupancy", 0) for p in route_predictions
        )
        avg_predicted = total_predicted_load / max(1, len(route_predictions))

        high_risk_routes = sum(
            1 for p in route_predictions
            if p.get("overcrowding_risk") in ("HIGH", "CRITICAL")
        )

        return {
            "predictions": route_predictions,
            "fleet_summary": {
                "total_routes": len(route_predictions),
                "current_avg_occupancy": round(avg_current, 1),
                "predicted_avg_occupancy": round(avg_predicted, 1),
                "demand_trend": (
                    "INCREASING" if avg_predicted > avg_current + 5
                    else "DECREASING" if avg_predicted < avg_current - 5
                    else "STABLE"
                ),
                "high_risk_routes": high_risk_routes,
                "minutes_ahead": minutes_ahead,
            },
            "time_context": {
                "current_ist_hour": ist_hour,
                "future_ist_hour": future_ist_hour,
                "current_demand_multiplier": current_multiplier,
                "future_demand_multiplier": future_multiplier,
            },
            "data_source": "RULE-BASED PREDICTIVE (simulated passenger data)",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def predict_overcrowding(
        self,
        buses: List[Dict],
        threshold_pct: float = 85.0,
    ) -> Dict:
        """Predict which routes face overcrowding risk."""
        route_buses = defaultdict(list)
        for bus in buses:
            route = bus.get("route_code", "unknown")
            route_buses[route].append(bus)

        overcrowding_risks = []

        for route_code, route_bus_list in route_buses.items():
            # Current occupancy stats
            occupancies = []
            for bus in route_bus_list:
                occ = (bus.get("occupancy") or {}).get("pct", 0)
                occupancies.append(occ)

            if not occupancies:
                continue

            avg_occ = sum(occupancies) / len(occupancies)
            max_occ = max(occupancies)
            overloaded_count = sum(1 for o in occupancies if o >= threshold_pct)

            # Predict based on trend
            now = datetime.now(timezone.utc)
            ist_hour = (now.hour + 5) % 24
            multiplier = DEMAND_MULTIPLIERS.get(ist_hour, 0.5)

            # If in peak hours, predict increase
            if multiplier > 0.8:
                predicted_avg = min(100, avg_occ * 1.15)
            elif multiplier < 0.4:
                predicted_avg = max(0, avg_occ * 0.85)
            else:
                predicted_avg = avg_occ

            # Overcrowding risk score
            risk_score = min(100, (predicted_avg / threshold_pct) * 80)

            if predicted_avg >= 95:
                risk_level = "CRITICAL"
            elif predicted_avg >= 85:
                risk_level = "HIGH"
            elif predicted_avg >= 70:
                risk_level = "MODERATE"
            else:
                risk_level = "LOW"

            overcrowding_risks.append({
                "route_code": route_code,
                "bus_count": len(route_bus_list),
                "current_avg_occupancy": round(avg_occ, 1),
                "current_max_occupancy": round(max_occ, 1),
                "predicted_avg_occupancy": round(predicted_avg, 1),
                "overloaded_buses": overloaded_count,
                "overcrowding_risk_score": round(risk_score, 1),
                "overcrowding_risk": risk_level,
                "recommendation": self._get_overcrowding_recommendation(
                    route_code, risk_level, predicted_avg, len(route_bus_list)
                ),
            })

        overcrowding_risks.sort(key=lambda r: r["overcrowding_risk_score"], reverse=True)

        return {
            "overcrowding_risks": overcrowding_risks,
            "high_risk_routes": sum(
                1 for r in overcrowding_risks
                if r["overcrowding_risk"] in ("HIGH", "CRITICAL")
            ),
            "data_source": "RULE-BASED PREDICTIVE (simulated passenger data)",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _predict_route_demand(
        self,
        route_code: str,
        route_buses: List[Dict],
        current_multiplier: float,
        future_multiplier: float,
        minutes_ahead: int,
    ) -> Dict:
        """Predict demand for a single route."""
        # Current metrics
        occupancies = []
        loads = []
        for bus in route_buses:
            occ = (bus.get("occupancy") or {}).get("pct", 0)
            load = (bus.get("load") or {}).get("load_pct", 0)
            occupancies.append(occ)
            loads.append(load)

        avg_occ = sum(occupancies) / max(1, len(occupancies))
        avg_load = sum(loads) / max(1, len(loads))

        # Predict future occupancy
        demand_change = (future_multiplier - current_multiplier) / max(0.01, current_multiplier)
        predicted_occ = min(100, max(0, avg_occ * (1 + demand_change)))

        # Overcrowding risk
        if predicted_occ >= 95:
            risk = "CRITICAL"
            risk_score = 95
        elif predicted_occ >= 85:
            risk = "HIGH"
            risk_score = 80
        elif predicted_occ >= 70:
            risk = "MODERATE"
            risk_score = 60
        else:
            risk = "LOW"
            risk_score = max(0, predicted_occ * 0.5)

        return {
            "route_code": route_code,
            "bus_count": len(route_buses),
            "current_avg_occupancy": round(avg_occ, 1),
            "current_avg_load": round(avg_load, 1),
            "predicted_avg_occupancy": round(predicted_occ, 1),
            "overcrowding_risk": risk,
            "overcrowding_risk_score": round(risk_score, 1),
            "demand_trend": (
                "INCREASING" if demand_change > 0.05
                else "DECREASING" if demand_change < -0.05
                else "STABLE"
            ),
            "recommendation": self._get_demand_recommendation(
                route_code, risk, predicted_occ, len(route_buses)
            ),
        }

    def _get_overcrowding_recommendation(
        self, route_code: str, risk_level: str, predicted_occ: float, bus_count: int
    ) -> str:
        """Get recommendation for overcrowding risk."""
        if risk_level == "CRITICAL":
            return (
                f"IMMEDIATE: Deploy additional bus to route {route_code}. "
                f"Predicted occupancy {predicted_occ:.0f}% exceeds capacity. "
                f"Consider express service or skip-stop boarding."
            )
        elif risk_level == "HIGH":
            return (
                f"Deploy relief bus to route {route_code} "
                f"before predicted occupancy reaches {predicted_occ:.0f}%."
            )
        elif risk_level == "MODERATE":
            return (
                f"Monitor route {route_code}. "
                f"Prepare standby bus for potential deployment."
            )
        else:
            return f"Route {route_code} operating within normal capacity."

    def _get_demand_recommendation(
        self, route_code: str, risk_level: str, predicted_occ: float, bus_count: int
    ) -> str:
        """Get demand-based recommendation."""
        if risk_level in ("HIGH", "CRITICAL"):
            return f"Add bus to route {route_code} (predicted {predicted_occ:.0f}% occupancy)"
        elif risk_level == "MODERATE":
            return f"Monitor route {route_code} for demand changes"
        else:
            return f"Route {route_code} demand normal"


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
demand_predictor = DemandPredictor()
