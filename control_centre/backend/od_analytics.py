"""
od_analytics.py
Origin-Destination analytics for the Analytics page.

Builds an OD flow matrix from boarding data the store already holds. The
simulator records daily boardings per stop per hour
(``boarding_by_stop_hour`` on each bus) plus the route's stop sequence. There
is no per-rider alighting sensor, so journeys are ESTIMATED with a documented
HEURISTIC:

  * Passengers boarding at stop i are distributed to downstream stops j>i
    (outbound) proportionally to destination attractiveness.
  * Destination attractiveness is a gravity-style function of the downstream
    stop's weight (major terminal >> normal) and distance (further stops get
    a modestly larger share for longer routes).

Methodology: HEURISTIC. Source labels are never implied as ML, and the note
field states exactly how OD flows were produced. No fabricated sensors, no
fake confidence.
"""

import threading
from collections import Counter

from data_store import store

# Gravity-model taste parameters (documented tunables, not measurements).
MAJOR_ATTRACTION = 4.0   # a major terminal attracts ~4x normal stop share
DISTANCE_POWER = 0.35    # mild distance weighting so long trips inherit more
MIN_SHARE = 0.02         # every downstream stop keeps a small base share


def _share_for(distance_idx):
    """Normalised attention share for a downstream stop `distance_idx` hops away."""
    return MIN_SHARE + (distance_idx ** DISTANCE_POWER)


def _build_route_matrix(stops, boarding_by_stop_hour, route_code):
    """OD matrix (origin index → destination index → riders) for one route.

    Boardings at each origin stop are apportioned across the stops ahead of it
    (forward direction only — return trips are a separate direction vector the
    profile data does not break out, so we stay honest and only model the
    outbound leg documented by the profile).
    """
    n = len(stops)
    boardings = []
    for s in stops:
        cell = boarding_by_stop_hour.get(s["stop"]) or {}
        boardings.append(sum(v for v in cell.values() if isinstance(v, (int, float))))

    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n - 1):
        origin_pax = boardings[i]
        if origin_pax <= 0 or i >= n - 1:
            continue
        downstream = [(j, stops[j]) for j in range(i + 1, n)]
        weights = []
        total_w = 0.0
        for j, s in downstream:
            w = _share_for(j - i) * (MAJOR_ATTRACTION if s.get("major") else 1.0)
            weights.append(w)
            total_w += w
        for (j, _s), w in zip(downstream, weights):
            matrix[i][j] = round(origin_pax * w / total_w, 2)

    return matrix, boardings, stops


def compute_od(limit=None):
    """Flatten per-route OD matrices into a fleetwide flow summary.

    Returns top OD pairs, per-origin outflow, per-destination inflow and the
    honest source note. `limit` caps the route set for quick views.
    """
    buses = store.get_buses()
    if limit is not None:
        buses = buses[:limit]

    pairs = Counter()      # (origin, destination) -> riders
    inflow = Counter()
    outflow = Counter()
    routes_covered = set()
    total_riders = 0
    matrix_count = 0

    for bus in buses:
        rc = bus.get("route_code")
        if not rc:
            continue
        bsh = bus.get("boarding_by_stop_hour")
        journey = bus.get("journey") or {}
        stops = journey.get("stops")
        if not bsh or not stops:
            continue
        routes_covered.add(rc)
        try:
            matrix, boardings, _ = _build_route_matrix(stops, bsh, rc)
        except Exception:
            continue
        matrix_count += 1
        origin_total = sum(boardings)
        total_riders += origin_total
        for i in range(len(stops)):
            for j in range(len(stops)):
                riders = matrix[i][j]
                if riders <= 0:
                    continue
                o = stops[i]["stop"]
                d = stops[j]["stop"]
                pairs[(o, d)] += riders
                outflow[o] += riders
                inflow[d] += riders

    top = []
    for (o, d), riders in pairs.most_common(12):
        top.append({"origin": o, "destination": d, "riders": round(riders, 0)})

    # Attach lat/lon for the top pairs when the origin stop is known to a route.
    stop_coords = _resolve_stop_coords()
    for t in top:
        if t["origin"] in stop_coords:
            t["origin_lat"], t["origin_lon"] = stop_coords[t["origin"]]
        if t["destination"] in stop_coords:
            t["dest_lat"], t["dest_lon"] = stop_coords[t["destination"]]

    return {
        "source": "HEURISTIC",
        "method": "gravity-style downstream apportionment of boarding_by_stop_hour",
        "note": "Origin-Destination flows are ESTIMATED. Boardings are real (simulated/store) per-stop totals; alighting is modelled with a gravity heuristic on downstream stop weight + distance. No per-rider alighting sensor is present, so OD cells are approximations, not measurements.",
        "routes_covered": sorted(routes_covered),
        "matrix_count": matrix_count,
        "buses_analyzed": len(buses),
        "total_riders_estimated": round(total_riders, 0),
        "top_pairs": top,
        "inflow_top": [{"stop": s, "riders": round(r, 0)} for s, r in inflow.most_common(8)],
        "outflow_top": [{"stop": s, "riders": round(r, 0)} for s, r in outflow.most_common(8)],
    }


_stop_coords_cache = None


def _resolve_stop_coords():
    """Build a stop-name -> (lat, lon) map from all buses' journey stops."""
    global _stop_coords_cache
    if _stop_coords_cache:
        return _stop_coords_cache
    coords = {}
    for bus in store.get_buses():
        for s in (bus.get("journey") or {}).get("stops") or []:
            if s.get("stop") and s.get("lat") is not None:
                coords.setdefault(s["stop"], (round(s["lat"], 5), round(s["lon"], 5)))
    _stop_coords_cache = coords
    return coords


od_analytics = compute_od