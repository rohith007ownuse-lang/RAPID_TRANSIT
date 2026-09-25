"""
operations_analytics.py
Operations analytics aggregate for the Analytics page.

Combines five analytical lenses over data the store already holds:
  - maintenance : which buses can't safely wait more than 3 days
  - traffic     : congestion hotspots from the traffic heat-map engine
  - road_quality: pothole workload, recurrence and daily trend
  - punctuality : per-route on-time / delay distribution (ETA heuristic)
  - demand      : per-route occupancy / load pressure

All values are honest views over the current in-memory store (simulated or
live); nothing here fabricates new measurements.
"""

import random
from collections import Counter
from datetime import datetime

from data_store import store, mode_state
from predictive_health import get_fleet_maintenance_risk, DataSource
from traffic_engine import traffic_monitor
from eta import eta_engine


def _punctuality():
    buses = store.get_buses()
    by_route = {}
    for b in buses:
        by_route.setdefault(b.get("route_code") or "UNKNOWN", []).append(b)

    rows = []
    fleet_counts = Counter()
    for rc, bts in by_route.items():
        delays = Counter()
        speeds = []
        moving = 0
        for bus in bts:
            try:
                rng = random.Random(f"{bus['bus_id']}-eta")
                res = eta_engine.compute_eta(bus, rng)
                band = res.get("delay_summary", "UNKNOWN") if isinstance(res, dict) else getattr(res, "delay_summary", "UNKNOWN")
            except Exception:
                band = "UNKNOWN"
            delays[band] += 1
            fleet_counts[band] += 1
            state = (bus.get("journey") or {}).get("state")
            if state in ("MOVING", "ARRIVING"):
                moving += 1
            sp = bus.get("speed_kmh")
            if isinstance(sp, (int, float)):
                speeds.append(sp)
        total = len(bts)
        rows.append({
            "route_code": rc,
            "route_name": bts[0].get("route", rc),
            "buses": total,
            "moving_buses": moving,
            "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "on_time_pct": round(100 * delays.get("ON_TIME", 0) / total, 1),
            "delays": dict(delays),
        })
    rows.sort(key=lambda r: r["on_time_pct"])
    fleet_total = sum(fleet_counts.values())
    return {
        "routes": rows,
        "fleet_on_time_pct": round(100 * fleet_counts.get("ON_TIME", 0) / fleet_total, 1) if fleet_total else None,
        "counts": dict(fleet_counts),
    }


def _road_quality():
    defects = store.get_road_defects()
    unique = len(defects)
    total_detections = sum(d.get("detection_count", 1) for d in defects)
    recurrence = max(0, total_detections - unique)
    recurring_spots = sum(1 for d in defects if d.get("detection_count", 0) >= 3)
    active = sum(1 for d in defects if d.get("status") == "ACTIVE")

    by_day = Counter()
    for d in defects:
        ts = d.get("first_detected") or d.get("last_detected")
        if ts:
            try:
                day = datetime.fromisoformat(str(ts)).date().isoformat()
                by_day[day] += d.get("detection_count", 1)
            except Exception:
                continue
    trend = [{"date": day, "detections": n} for day, n in sorted(by_day.items())[-7:]]

    return {
        "unique_defects": unique,
        "total_detections": total_detections,
        "active_defects": active,
        "recurrence_count": recurrence,
        "recurrence_rate": round(recurrence / total_detections, 3) if total_detections else None,
        "recurring_spots": recurring_spots,
        "trend": trend,
    }


def _demand():
    buses = store.get_buses()
    try:
        from demand_intelligence import get_route_demand_summary, get_fleet_load_summary
        routes = {k: v for k, v in get_route_demand_summary(buses).items()}
        fleet = get_fleet_load_summary(buses)
    except Exception:
        routes, fleet = {}, {}

    per_route_occ = {}
    for b in buses:
        rc = b.get("route_code") or "UNKNOWN"
        occ = b.get("occupancy", {})
        pct = occ.get("percentage")
        entry = per_route_occ.setdefault(rc, {"buses": 0, "occupancy": [], "capacity": []})
        entry["buses"] += 1
        if isinstance(pct, (int, float)):
            entry["occupancy"].append(pct)
        cap = occ.get("capacity")
        if isinstance(cap, (int, float)):
            entry["capacity"].append(cap)
    per_route = [{
        "route_code": rc,
        "buses": e["buses"],
        "avg_occupancy_pct": round(sum(e["occupancy"]) / len(e["occupancy"]), 1) if e["occupancy"] else None,
        "avg_capacity": round(sum(e["capacity"]) / len(e["capacity"]), 1) if e["capacity"] else None,
    } for rc, e in sorted(per_route_occ.items())]

    return {"routes": per_route, "route_demand": routes, "fleet": fleet}


def operations_analytics() -> dict:
    data_source = DataSource.SIMULATION if mode_state.is_simulation else DataSource.LIVE
    return {
        "maintenance": get_fleet_maintenance_risk(data_source),
        "traffic": traffic_monitor.analytics(),
        "road_quality": _road_quality(),
        "punctuality": _punctuality(),
        "demand": _demand(),
        "simulation": mode_state.is_simulation,
        "mode": mode_state.mode,
    }