"""
risk_predictor.py
Predicts future risk levels based on current trends and patterns.

Provides:
- 30-minute risk prediction
- Risk trend analysis
- Factor contribution forecasting
- Alert generation for predicted high-risk situations

DATA CLASSIFICATION: RULE-BASED (uses current risk + trend extrapolation)
"""

import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import math


class RiskPredictor:
    """
    Predicts future risk levels using trend extrapolation and pattern analysis.

    Uses historical risk data to forecast risk levels for the next 30 minutes.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._risk_history: Dict[str, List[Dict]] = defaultdict(list)  # bus_id -> [{timestamp, score, factors}]
        self._prediction_cache: Dict[str, Dict] = {}
        self._cache_expiry = 60  # seconds

    def record_risk(self, bus_id: str, risk_score: float, factors: Dict = None):
        """
        Record a risk measurement for trend analysis.

        Args:
            bus_id: Bus identifier
            risk_score: Current risk score (0-100)
            factors: Optional factor breakdown
        """
        with self._lock:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "score": risk_score,
                "factors": factors or {},
            }
            self._risk_history[bus_id].append(entry)

            # Keep only last 2 hours of history
            cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
            self._risk_history[bus_id] = [
                h for h in self._risk_history[bus_id]
                if self._parse_timestamp(h["timestamp"]) > cutoff
            ]

    def predict_risk(
        self, bus_id: str, minutes_ahead: int = 30
    ) -> Dict:
        """
        Predict risk level for a bus at a future time.

        Args:
            bus_id: Bus identifier
            minutes_ahead: How far ahead to predict (default 30 min)

        Returns:
            Dict with prediction details
        """
        with self._lock:
            history = self._risk_history.get(bus_id, [])

            if len(history) < 3:
                return {
                    "bus_id": bus_id,
                    "current_score": None,
                    "predicted_score": None,
                    "confidence": 0.3,
                    "trend": "unknown",
                    "factors": {},
                    "alerts": [],
                    "note": "Insufficient history for prediction",
                }

            # Calculate trend
            recent_scores = [h["score"] for h in history[-10:]]
            trend = self._calculate_trend(recent_scores)

            # Current score (most recent)
            current_score = history[-1]["score"]

            # Predict based on trend
            predicted_score = self._extrapolate_score(
                current_score, trend, minutes_ahead
            )

            # Calculate confidence based on data consistency
            confidence = self._calculate_confidence(recent_scores)

            # Identify contributing factors
            factors = self._analyze_factors(history)

            # Generate alerts if predicted high risk
            alerts = self._generate_prediction_alerts(
                bus_id, current_score, predicted_score, factors
            )

            # Cache the prediction
            prediction = {
                "bus_id": bus_id,
                "current_score": round(current_score, 1),
                "predicted_score": round(predicted_score, 1),
                "predicted_level": self._score_to_level(predicted_score),
                "minutes_ahead": minutes_ahead,
                "confidence": round(confidence, 2),
                "trend": trend,
                "trend_strength": self._calculate_trend_strength(recent_scores),
                "factors": factors,
                "alerts": alerts,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }

            self._prediction_cache[bus_id] = {
                "prediction": prediction,
                "cached_at": time.time(),
            }

            return prediction

    def predict_fleet_risk(self, minutes_ahead: int = 30) -> Dict:
        """
        Predict risk for all buses in the fleet.

        Returns:
            Dict with fleet-wide risk predictions
        """
        from data_store import store

        buses = store.get_buses()
        predictions = []

        for bus in buses:
            bus_id = bus.get("bus_id", "")
            pred = self.predict_risk(bus_id, minutes_ahead)
            predictions.append(pred)

        # Aggregate predictions
        valid = [p for p in predictions if p.get("predicted_score") is not None]
        if not valid:
            return {
                "predictions": predictions,
                "fleet_summary": {
                    "avg_predicted_risk": 0,
                    "high_risk_count": 0,
                    "increasing_count": 0,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }

        avg_predicted = sum(p["predicted_score"] for p in valid) / len(valid)
        high_risk = sum(1 for p in valid if p.get("predicted_level") in ("HIGH", "CRITICAL"))
        increasing = sum(1 for p in valid if p.get("trend") == "increasing")

        return {
            "predictions": predictions,
            "fleet_summary": {
                "avg_predicted_risk": round(avg_predicted, 1),
                "high_risk_count": high_risk,
                "increasing_count": increasing,
                "total_predicted": len(valid),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _calculate_trend(self, scores: List[float]) -> str:
        """Calculate trend direction from recent scores."""
        if len(scores) < 2:
            return "stable"

        # Simple linear regression slope
        n = len(scores)
        x_vals = list(range(n))
        x_mean = sum(x_vals) / n
        y_mean = sum(scores) / n

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, scores))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)

        if denominator == 0:
            return "stable"

        slope = numerator / denominator

        if slope > 0.5:
            return "increasing"
        elif slope < -0.5:
            return "decreasing"
        else:
            return "stable"

    def _calculate_trend_strength(self, scores: List[float]) -> float:
        """Calculate how strong the trend is (0-1)."""
        if len(scores) < 3:
            return 0.0

        # Calculate R-squared
        n = len(scores)
        x_vals = list(range(n))
        x_mean = sum(x_vals) / n
        y_mean = sum(scores) / y_mean if (y_mean := sum(scores) / n) else 0

        ss_res = sum((y - y_mean) ** 2 for y in scores)
        if ss_res == 0:
            return 1.0

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, scores))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)

        if denominator == 0:
            return 0.0

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        ss_tot = ss_res
        ss_reg = sum(((slope * x + intercept) - y_mean) ** 2 for x, y in zip(x_vals, scores))

        r_squared = ss_reg / ss_tot if ss_tot > 0 else 0
        return min(1.0, max(0.0, r_squared))

    def _extrapolate_score(
        self, current: float, trend: str, minutes: int
    ) -> float:
        """Extrapolate current score based on trend."""
        # Rate of change per minute (estimated)
        rates = {
            "increasing": 0.5,
            "decreasing": -0.5,
            "stable": 0.0,
        }

        rate = rates.get(trend, 0.0)
        predicted = current + (rate * minutes)

        # Clamp to 0-100
        return max(0.0, min(100.0, predicted))

    def _calculate_confidence(self, scores: List[float]) -> float:
        """Calculate prediction confidence based on data consistency."""
        if len(scores) < 3:
            return 0.3

        # Lower variance = higher confidence
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std_dev = math.sqrt(variance)

        # Normalize: std_dev of 20 = 50% confidence, std_dev of 5 = 90% confidence
        confidence = 1.0 - (std_dev / 40.0)
        return max(0.3, min(0.95, confidence))

    def _analyze_factors(self, history: List[Dict]) -> Dict:
        """Analyze which factors contribute most to risk trends."""
        recent = history[-5:] if len(history) >= 5 else history

        factor_trends = defaultdict(list)
        for entry in recent:
            for factor, value in entry.get("factors", {}).items():
                if isinstance(value, (int, float)):
                    factor_trends[factor].append(value)

        analysis = {}
        for factor, values in factor_trends.items():
            if len(values) >= 2:
                trend = "increasing" if values[-1] > values[0] else "decreasing" if values[-1] < values[0] else "stable"
                analysis[factor] = {
                    "current": values[-1],
                    "trend": trend,
                    "change": round(values[-1] - values[0], 2),
                }

        return analysis

    def _generate_prediction_alerts(
        self, bus_id: str, current: float, predicted: float, factors: Dict
    ) -> List[Dict]:
        """Generate alerts based on risk predictions."""
        alerts = []

        if predicted >= 80 and current < 80:
            alerts.append({
                "type": "PREDICTED_CRITICAL",
                "severity": "CRITICAL",
                "message": f"Bus {bus_id} predicted to reach CRITICAL risk in 30 minutes",
                "action": "Immediate intervention recommended",
            })
        elif predicted >= 60 and current < 60:
            alerts.append({
                "type": "PREDICTED_HIGH",
                "severity": "HIGH",
                "message": f"Bus {bus_id} trending toward HIGH risk",
                "action": "Monitor closely, consider preventive action",
            })

        # Factor-based alerts
        for factor, info in factors.items():
            if info.get("trend") == "increasing" and info.get("current", 0) > 70:
                alerts.append({
                    "type": "FACTOR_DEGRADATION",
                    "severity": "WARNING",
                    "message": f"Bus {bus_id}: {factor} factor increasing",
                    "action": f"Investigate {factor} conditions",
                })

        return alerts

    @staticmethod
    def _score_to_level(score: float) -> str:
        """Convert risk score to level string (HIGH starts at 60, aligned
        with the risk engine's level_for_score)."""
        if score >= 80:
            return "CRITICAL"
        elif score >= 60:
            return "HIGH"
        elif score >= 30:
            return "MODERATE"
        else:
            return "LOW"

    @staticmethod
    def _parse_timestamp(ts: str) -> datetime:
        """Parse ISO timestamp to datetime."""
        try:
            ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

risk_predictor = RiskPredictor()


# Import time for cache
import time
