"""
congestion_heatmap.py
Congestion heat-map layer for the fleet map.

Builds a discretized intensity grid over current bus positions. Each bus that
carries a valid GPS fix contributes to its grid cell a weight that combines:
  - presence                    (it is here)
  - speed-derived congestion    (slow / stopped buses weight more)

This is an honest positional view over the in-memory store (simulated or
live). Buses are clustered into roughly (CELL_DEG)² cells; each cell becomes a
`heat` entry carrying its centroid, bus count and a normalised intensity
(0..1) the UI layers as a translucent colour spot. Nothing here invents
traffic — the same data the traffic_engine already reasons over.
"""

import threading
import time
from collections import defaultdict

# Grid cell size in degrees (~0.004 lat deg ≈ 440 m). A helper scale keeps the
# grid coarse enough to be readable but fine enough to show corridors.
CELL_DEG = 0.004
# Stopped/creeping speed below which a bus is treated as congested (km/h).
CONGESTED_KMH = 15.0

# Intensity calibration: a lone moving bus ~= warm edge; a cluster of stuck
# buses saturates. These are honest tunables, not measurements.
WEIGHT_MOVING = 1.0
WEIGHT_CONGESTED = 3.0
WINDOW_SEC = 300.0          # cells age out after this long without a sighting
SAMPLE_THRESHOLD = 2        # cells below this many bus samples stay faint


def _grid_key(lat, lon):
    return (round(lat / CELL_DEG), round(lon / CELL_DEG))


class CongestionHeatmap:
    """Accumulates a positional congestion grid for map overlay."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cells = {}   # (kx, ky) -> {lat, lon, samples, weight, last}
        self._last_update = None

    def update(self, buses, now=None):
        """Feed current bus positions; call on the standard cadence."""
        now = now if now is not None else time.time()
        samples = defaultdict(lambda: {"lat": 0.0, "lon": 0.0, "count": 0, "weight": 0.0})
        for b in buses:
            lat, lon = b.get("latitude"), b.get("longitude")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            speed = b.get("speed_kmh")
            weight = WEIGHT_MOVING
            if isinstance(speed, (int, float)) and speed < CONGESTED_KMH:
                weight = WEIGHT_CONGESTED
            key = _grid_key(lat, lon)
            cell = samples[key]
            cell["lat"] += lat
            cell["lon"] += lon
            cell["count"] += 1
            cell["weight"] += weight

        with self._lock:
            seen = set()
            for key, agg in samples.items():
                seen.add(key)
                lat = agg["lat"] / agg["count"]
                lon = agg["lon"] / agg["count"]
                if key in self._cells:
                    # Exponential smoothing so a single passing bus does not
                    # spike the cell; a sustained cluster accumulates.
                    old = self._cells[key]
                    alpha = 0.5
                    w = old["weight"] + alpha * (agg["weight"] - old["weight"])
                    self._cells[key] = {
                        "lat": old["lat"] + 0.3 * (lat - old["lat"]),
                        "lon": old["lon"] + 0.3 * (lon - old["lon"]),
                        "samples": old["samples"] + agg["count"],
                        "weight": w,
                        "last": now,
                    }
                else:
                    self._cells[key] = {
                        "lat": lat, "lon": lon,
                        "samples": agg["count"], "weight": float(agg["weight"]),
                        "last": now,
                    }

            # Age out stale cells.
            for key in [k for k, c in self._cells.items() if now - c["last"] > WINDOW_SEC]:
                del self._cells[key]
            self._last_update = now

    def get_heat(self, now=None):
        """Normalised heat spots. Highest weight cell = intensity 1.0."""
        now = now if now is not None else time.time()
        with self._lock:
            cells = [dict(c) for c in self._cells.values()]
            for c in cells:
                c["last_seen_sec"] = round(now - c["last"], 1)
        if not cells:
            return {"cells": [], "max_cell_buses": 0, "hot_bus_count": 0}

        max_w = max(c["weight"] for c in cells)
        max_buses = max(c["samples"] for c in cells) if cells else 0
        hot = [c for c in cells if c["weight"] >= WEIGHT_CONGESTED * SAMPLE_THRESHOLD]
        for c in cells:
            # Faint cells stay visible but low; strong ones heat up non-linearly
            # so the map reads blue → red instead of a wash of mid-tones.
            c["intensity"] = round(min(1.0, (c["weight"] / max_w) ** 1.25), 3)
            c["heat_buses"] = c["samples"]
        cells.sort(key=lambda c: c["intensity"], reverse=True)
        return {
            "cells": cells,
            "max_cell_buses": max_buses,
            "hot_bus_count": len(hot),
            "hotspots_declared": int(max_w >= WEIGHT_CONGESTED * SAMPLE_THRESHOLD),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }


# Singleton shared by the routes/server.
congestion_heatmap = CongestionHeatmap()