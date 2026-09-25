"""
fleet_summary.py
Phase 8: fleet-level operational aggregation for the command dashboard.

Pure module (no Flask/threading imports) so it is unit-testable. It consumes
the SAME intelligence the rest of FLEET-IQ already produces — risk engine
items, bus telemetry, event log, road-risk index — and repackages them into
one operator-oriented summary with an explicit source/severity on every
reason. It never invents alert conditions or measurements.

Severity vocabulary reused from the existing risk engine / event system:
CRITICAL > HIGH > WARNING > OFFLINE > INFO. No conflicting severity set.
"""

import time
from datetime import datetime, timezone

STALE_SECONDS = 30.0
SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "WARNING": 2, "OFFLINE": 1, "INFO": 0}
RISK_LEVEL_SEVERITY = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MODERATE": "WARNING", "MEDIUM": "WARNING", "LOW": None}
ROAD_INDEX_RISKY = {"HIGH", "CRITICAL"}


def _epoch(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _is_live_asset(bus):
    return bool(bus.get("_live") or bus.get("live") or bus.get("data_source") == "live")


def _is_offline(bus, now):
    """A bus is offline only when it is a live asset whose telemetry is stale."""
    if not _is_live_asset(bus):
        return False
    if bus.get("_live") is False:
        return True
    ts = _epoch(bus.get("last_update"))
    return ts is None or (now - ts) > STALE_SECONDS


def _offline_age_seconds(bus, now):
    ts = _epoch(bus.get("last_update"))
    if ts is None:
        return None
    return max(0, int(now - ts))


# ------------------------------------------------------------------ reasons
def _driver_reason(bus):
    d = bus.get("driver") or {}
    state = (d.get("state") or "NORMAL").upper()
    if state == "DROWSY":
        stage = (d.get("fatigue_stage") or "WATCH").upper()
        return {
            "source": "driver_safety",
            "severity": "CRITICAL" if stage == "CRITICAL" else "HIGH",
            "text": f"Driver drowsiness detected ({stage})",
        }
    if state == "ATTENTION":
        return {
            "source": "driver_safety",
            "severity": "WARNING",
            "text": "Driver attention required",
        }
    return None


def _vehicle_reason(bus):
    v = bus.get("vehicle") or {}
    health = (v.get("health") or "NORMAL").upper()
    if health == "INSPECTION REQUIRED":
        return {"source": "vehicle_health", "severity": "HIGH",
                "text": "Vehicle inspection required"}
    if health == "WARNING":
        return {"source": "vehicle_health", "severity": "WARNING",
                "text": "Vehicle health warning"}
    return None


def _load_reason(bus):
    l = bus.get("load") or {}
    status = (l.get("status") or "NORMAL").upper()
    pct = l.get("load_pct")
    if status == "CRITICAL OVERLOAD":
        return {"source": "load", "severity": "CRITICAL",
                "text": f"Critical overload ({pct}%)" if pct is not None else "Critical overload"}
    if status == "HIGH LOAD":
        return {"source": "load", "severity": "WARNING",
                "text": f"High load ({pct}%)" if pct is not None else "High load"}
    return None


def _occupancy_reason(bus):
    """Telemetry/simulated occupancy from bus.occupancy (existing labels)."""
    o = bus.get("occupancy") or {}
    crowd = (o.get("crowd") or "NORMAL").upper()
    pct = o.get("pct")
    sentinel = {"source": "occupancy", "severity": None, "text": None}
    if crowd in ("CRITICAL CROWDING", "OVERCROWDED"):
        sentinel.update(severity="CRITICAL",
                        text=f"Critical crowding ({pct}%)" if pct is not None else "Critical crowding")
        return sentinel
    if crowd in ("HIGH", "CROWDED"):
        sentinel.update(severity="WARNING",
                        text=f"High occupancy ({pct}%)" if pct is not None else "High occupancy")
        return sentinel
    return None


def _cabin_reason(bus):
    co = bus.get("cabin_occupancy") or {}
    if co.get("status") != "CONNECTED":
        return None
    level = (co.get("crowding_level") or "NORMAL").upper()
    if level == "CRITICAL":
        return {"source": "cabin_camera", "severity": "CRITICAL",
                "text": f"Cabin camera crowding {co.get('occupancy_percentage')}%"}
    if level == "HIGH":
        return {"source": "cabin_camera", "severity": "WARNING",
                "text": f"Cabin camera crowding {co.get('occupancy_percentage')}%"}
    return None


def _risk_reasons(risk_item):
    if not risk_item:
        return []
    return [{"source": "risk", "severity": RISK_LEVEL_SEVERITY[risk_item["risk_level"]],
             "text": r} for r in (risk_item.get("reasons") or [])[:2]]


def _cabin_camera_used(bus):
    co = bus.get("cabin_occupancy") or {}
    return co.get("status") == "CONNECTED"


# --------------------------------------------------------------- summary
def build_fleet_summary(buses, events, risk_items, mode, zones=None, route_index=None, defects=None, eta_summary=None, demand_summary=None):
    """Assemble the operator-oriented fleet summary.

    buses: store buses (list of dicts)
    events: store events (list of dicts, newest first)
    risk_items: fleet_risk() output (list of per-bus risk dicts, sorted desc)
    mode: {"mode", "simulation", "connected_nodes"} (connected_nodes: {bus_id: node})
    zones/route_index/defects: road-risk engine outputs (optional)
    eta_summary: fleet ETA summary from eta.get_fleet_eta_summary() (optional)
    demand_summary: fleet demand intelligence from demand_intelligence.get_fleet_load_summary() (optional)
    """
    simulation = bool(mode.get("simulation"))
    now = time.time()
    risk_by_id = {r["bus_id"]: r for r in (risk_items or [])}

    categories = {"total_buses": len(buses), "active": 0, "normal": 0,
                  "warning": 0, "critical": 0, "offline": 0}
    fleet = {
        "normal": [], "warning": [], "critical": [], "offline": [],
    }
    attention = []
    driver = {"normal": 0, "attention": 0, "drowsy": 0, "unavailable": 0}
    vehicle = {"NORMAL": 0, "WARNING": 0, "INSPECTION REQUIRED": 0, "unknown": 0}
    occupancy = {"normal": 0, "moderate": 0, "high": 0, "critical": 0,
                 "camera_based": 0, "simulated": 0, "unavailable": 0}
    load = {"normal": 0, "high": 0, "critical": 0}

    for bus in buses:
        bus_id = bus.get("bus_id")
        risk_item = risk_by_id.get(bus_id)

        offline = _is_offline(bus, now)
        if offline:
            categories["offline"] += 1
            fleet["offline"].append(bus_id)
            driver["unavailable"] += 1
            vehicle["unknown"] += 1
            occupancy["unavailable"] += 1
            age = _offline_age_seconds(bus, now)
            attention.append({
                "bus_id": bus_id,
                "reg_no": bus.get("reg_no") or bus_id,
                "route": bus.get("route") or bus.get("route_code") or "",
                "severity": "OFFLINE",
                "offline": True,
                "staleness_seconds": age,
                "risk_score": None,
                "risk_level": None,
                "reasons": [{
                    "source": "fleet",
                    "severity": "OFFLINE",
                    "text": f"Telemetry stale" + (f" ({age} s)" if age is not None else ""),
                }],
                "metrics": {},
            })
            continue

        categories["active"] += 1

        # --- per-condition reasons from existing intelligence ---
        reasons = []
        for fn in (_driver_reason, _vehicle_reason, _load_reason,
                   _occupancy_reason, _cabin_reason):
            r = fn(bus)
            if r:
                reasons.append(r)
        reasons.extend(_risk_reasons(risk_item))
        reasons = [r for r in reasons if r.get("severity")]

        # fleet category
        max_sev = max((SEVERITY_RANK.get(r["severity"], 0) for r in reasons), default=0)
        if max_sev >= SEVERITY_RANK["CRITICAL"]:
            category = "critical"
        elif max_sev >= SEVERITY_RANK["HIGH"]:
            category = "warning"  # HIGH severity buses are counted as the fleet "warning" tier
            # keep warning bucket for HIGH (risk HIGH or drowsy); critical stays CRITICAL
        elif max_sev >= SEVERITY_RANK["WARNING"]:
            category = "warning"
        else:
            category = "normal"

        if category == "critical":
            categories["critical"] += 1
            fleet["critical"].append(bus_id)
        elif category == "warning":
            categories["warning"] += 1
            fleet["warning"].append(bus_id)
        else:
            categories["normal"] += 1
            fleet["normal"].append(bus_id)

        # --- driver safety distribution ---
        d = bus.get("driver") or {}
        ds = (d.get("state") or "NORMAL").upper()
        if ds == "DROWSY":
            driver["drowsy"] += 1
        elif ds == "ATTENTION":
            driver["attention"] += 1
        else:
            driver["normal"] += 1

        # --- vehicle health distribution (faithful to backend values) ---
        vh = (bus.get("vehicle") or {}).get("health") or "NORMAL"
        if vh == "WARNING":
            vehicle["WARNING"] += 1
        elif vh == "INSPECTION REQUIRED":
            vehicle["INSPECTION REQUIRED"] += 1
        else:
            vehicle["NORMAL"] += 1

        # --- load distribution ---
        ls = ((bus.get("load") or {}).get("status") or "NORMAL").upper()
        if ls == "CRITICAL OVERLOAD":
            load["critical"] += 1
        elif ls == "HIGH LOAD":
            load["high"] += 1
        else:
            load["normal"] += 1

        # --- occupancy: camera-based vs simulated/telemetry, never mixed ---
        camera_used = _cabin_camera_used(bus)
        if camera_used:
            occupancy["camera_based"] += 1
            level = ((bus.get("cabin_occupancy") or {}).get("crowding_level") or "NORMAL").upper()
            bucket = {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "moderate"}.get(level, "normal")
            occupancy[bucket] += 1
        else:
            occupancy["simulated"] += 1
            crowd = ((bus.get("occupancy") or {}).get("crowd") or "NORMAL").upper()
            if crowd in ("CRITICAL CROWDING", "OVERCROWDED"):
                occupancy["critical"] += 1
            elif crowd in ("HIGH", "CROWDED"):
                occupancy["high"] += 1
            elif crowd == "MODERATE":
                occupancy["moderate"] += 1
            else:
                occupancy["normal"] += 1

        # --- attention list entry (only non-nominal buses) ---
        if max_sev >= SEVERITY_RANK["WARNING"]:
            attention.append({
                "bus_id": bus_id,
                "reg_no": bus.get("reg_no") or bus_id,
                "route": bus.get("route") or bus.get("route_code") or "",
                "severity": max((r["severity"] for r in reasons),
                                key=lambda s: SEVERITY_RANK.get(s, 0)),
                "offline": False,
                "staleness_seconds": None,
                "risk_score": risk_item["risk_score"] if risk_item else None,
                "risk_level": risk_item["risk_level"] if risk_item else None,
                "reasons": reasons[:4],
                "metrics": {
                    "speed_kmh": bus.get("speed_kmh"),
                    "load_pct": (bus.get("load") or {}).get("load_pct"),
                    "occupancy_pct": (bus.get("occupancy") or {}).get("pct"),
                    "driver_state": ((bus.get("driver") or {}).get("state") or "NORMAL"),
                },
            })

    # --- incident summary from the incident intelligence system ---
    try:
        from incident_intelligence import incident_store
        all_incidents = incident_store.get_incidents(limit=10000)
        inc_sev_counter = {}
        inc_status_counter = {}
        for inc in all_incidents:
            inc_sev_counter[inc.severity] = inc_sev_counter.get(inc.severity, 0) + 1
            inc_status_counter[inc.status] = inc_status_counter.get(inc.status, 0) + 1
        incidents = {
            "total": len(all_incidents),
            "severity": inc_sev_counter,
            "status": inc_status_counter,
            "open": (inc_status_counter.get("OPEN", 0) + inc_status_counter.get("INVESTIGATING", 0)),
            "acknowledged": inc_status_counter.get("ACKNOWLEDGED", 0),
            "resolved": inc_status_counter.get("RESOLVED", 0),
        }
    except Exception:
        # Fallback: count from raw events if incident store unavailable
        sev_counter = {}
        status_counter = {}
        for e in events:
            sev_counter[e.get("severity") or "INFO"] = sev_counter.get(e.get("severity") or "INFO", 0) + 1
            status_counter[e.get("status") or "ACTIVE"] = status_counter.get(e.get("status") or "ACTIVE", 0) + 1
        incidents = {
            "total": len(events),
            "severity": sev_counter,
            "status": status_counter,
            "open": (status_counter.get("ACTIVE", 0) + status_counter.get("REVIEWING", 0)),
            "acknowledged": status_counter.get("ACKNOWLEDGED", 0),
            "resolved": status_counter.get("RESOLVED", 0),
        }

    # --- fleet risk aggregate ---
    by_level = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for r in risk_items or []:
        by_level[r["risk_level"]] = by_level.get(r["risk_level"], 0) + 1
    avg_score = round(sum(r.get("risk_score", 0) for r in risk_items or []) / len(risk_items), 1) if risk_items else 0

    # --- road risk (only metrics that actually exist in the road engine) ---
    route_index = route_index or {}
    risky_routes = [rc for rc, info in route_index.items() if info.get("level") in ROAD_INDEX_RISKY]
    active_defects = sum(1 for d in (defects or []) if d.get("status") == "ACTIVE")
    affected_buses = sum(
        1 for b in buses if b.get("route_code") and b.get("route_code") in set(risky_routes)
    )

    # Phase 12: enhanced road intelligence summary
    exposed_buses = 0
    approaching_buses = 0
    high_risk_zones = 0
    for z in (zones or []):
        if isinstance(z, dict) and z.get("risk_level") in ("HIGH", "CRITICAL"):
            high_risk_zones += 1

    # Count exposed buses from risk items
    for r in (risk_items or []):
        if r.get("road_exposure") == "EXPOSED":
            exposed_buses += 1
        elif r.get("road_exposure") == "APPROACHING":
            approaching_buses += 1

    road = {
        "high_risk_routes": len(risky_routes),
        "risky_routes": risky_routes,
        "active_defects": active_defects,
        "affected_buses": affected_buses,
        "zones": len(zones or []),
        "high_risk_zones": high_risk_zones,
        "exposed_buses": exposed_buses,
        "approaching_buses": approaching_buses,
    }

    # --- ETA / delay intelligence (Phase 13) ---
    eta = eta_summary or {}
    eta_delay_dist = eta.get("delay_distribution", {})
    on_time_pct = eta.get("on_time_percentage", 0)
    delayed_pct = eta.get("delayed_percentage", 0)
    severe_buses = eta.get("severe_delay_buses", [])

    # --- demand / capacity intelligence (Phase 14) ---
    demand = demand_summary or {}
    demand_load_dist = demand.get("load_distribution", {})
    demand_crowd_dist = demand.get("crowding_distribution", {})
    overloaded_buses = demand.get("overloaded_buses", [])
    near_capacity_buses = demand.get("near_capacity_buses", [])
    unknown_occ_buses = demand.get("unknown_occupancy_buses", [])

    # --- prioritisation: CRITICAL > HIGH > WARNING > OFFLINE > INFO; then bus_id ---
    attention.sort(key=lambda a: (-SEVERITY_RANK.get(a["severity"], 0), a["bus_id"]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode.get("mode", "simulation"),
        "simulation": simulation,
        "live_prototype_connected": len(mode.get("connected_nodes") or {}) > 0,
        "connected_nodes": len(mode.get("connected_nodes") or {}),
        "fleet": fleet,
        "fleet_counts": categories,
        "risk": {"avg_score": avg_score, "by_level": by_level},
        "incidents": incidents,
        "driver_safety": driver,
        "vehicle_health": vehicle,
        "occupancy": occupancy,
        "load": load,
        "road": road,
        "eta": {
            "on_time_percentage": on_time_pct,
            "delayed_percentage": delayed_pct,
            "severe_delay_buses": severe_buses,
            "delay_distribution": eta_delay_dist,
            "source": eta.get("source", "HEURISTIC"),
        },
        "demand": {
            "load_distribution": demand_load_dist,
            "crowding_distribution": demand_crowd_dist,
            "overloaded_buses": overloaded_buses,
            "near_capacity_buses": near_capacity_buses,
            "unknown_occupancy_buses": unknown_occ_buses,
            "overloaded_percentage": demand.get("overloaded_percentage", 0),
            "high_utilization_percentage": demand.get("high_utilization_percentage", 0),
            "source": demand.get("source", "HEURISTIC"),
        },
        "attention": attention,
    }