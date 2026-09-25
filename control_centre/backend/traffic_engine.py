"""
traffic_engine.py
Traffic heat-map engine — detects congestion hotspots from live bus positions.

A high-traffic area ("red dot") is declared when EIGHT or more buses are within
HOTSPOT_RADIUS_M (50 m) of each other for longer than ACTIVE_WINDOW_SEC. When
six or more active red dots cluster within SUPER_RADIUS_M they are reported as
ONE large merged zone that only BLINKS (no expanding waves). Active hotspots
are surfaced to the dashboard / live-feed map and to the analytics page as
congestion telemetry.

Because clustering links neighbours, a queue of buses queued 50 m apart forms
one connected cluster that spans hundreds of metres. A red hotspot has to mean
"this many buses inside one radius", so every cluster is reduced to its DENSEST
CORE — the largest subset that genuinely fits inside HOTSPOT_RADIUS_KM — and
that core is what gets counted, located and reported. A long thin queue of
eight buses therefore never lights up red.

HONESTY: this is a positional detector over whatever bus data the store holds
(simulation or live). It never fabricates a hotspot — a spot only lights up when
the sustained-bunch condition is actually met.
"""

import threading
import time
import math
from datetime import datetime, timezone

# Detection parameters
HOTSPOT_RADIUS_M = 50.0
HOTSPOT_RADIUS_KM = HOTSPOT_RADIUS_M / 1000.0
MIN_BUSES = 8                 # eight or more buses ...
ACTIVE_WINDOW_SEC = 60.0      # ... together inside one 50 m circle for over a minute

# Hotspot IDENTITY radius, deliberately wider than the detection radius. A jam
# that crawls along a corridor must keep the same hotspot (and the same 60 s
# activation timer) instead of shedding a trail of brand-new spots behind it.
MATCH_RADIUS_M = 150.0
MATCH_KM = MATCH_RADIUS_M / 1000.0
EVICT_AFTER_SEC = 120.0

# Super-hotspot merge: six or more active red dots (hotspots) whose centroids
# fall within SUPER_RADIUS_M of each other are reported as ONE large red zone
# — a corridor-scale jam rather than a scatter of small alerts. The merged
# zone BLINKS ONLY on the map: no expanding waves, no moving parts.
SUPER_RADIUS_M = 200.0
SUPER_RADIUS_KM = SUPER_RADIUS_M / 1000.0
SUPER_MIN_HOTSPOTS = 6


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cluster_buses(buses):
    """Group busy positions into connected components within HOTSPOT_RADIUS_KM.

    Returns a list of clusters; each cluster is a list of dicts with
    bus_id/latitude/longitude.
    """
    points = [{
        "bus_id": b.get("bus_id"),
        "latitude": float(b.get("latitude")),
        "longitude": float(b.get("longitude")),
        "speed_kmh": b.get("speed_kmh"),
    } for b in buses if _valid_pos(b)]

    clusters = []
    remaining = set(range(len(points)))
    while remaining:
        seed = min(remaining)
        component = [seed]
        remaining.discard(seed)
        frontier = [seed]
        while frontier:
            i = frontier.pop()
            to_join = []
            for j in remaining:
                d = _haversine_km(points[i]["latitude"], points[i]["longitude"],
                                  points[j]["latitude"], points[j]["longitude"])
                if d <= HOTSPOT_RADIUS_KM:
                    to_join.append(j)
            for j in to_join:
                remaining.discard(j)
                component.append(j)
                frontier.append(j)
        clusters.append([points[i] for i in component])
    return clusters


def _valid_pos(b):
    lat = b.get("latitude")
    lon = b.get("longitude")
    return isinstance(lat, (int, float)) and isinstance(lon, (int, float))


def _densest_core(cluster):
    """Reduce a linked cluster to the largest subset inside one radius.

    `_cluster_buses` links neighbours, so buses queued 50 m apart end up in one
    component that can span hundreds of metres. A red hotspot must mean "N
    buses within R metres", so the reported zone is the densest sub-group that
    genuinely fits inside HOTSPOT_RADIUS_KM — measured from a real bus
    position, not from a centroid that might sit outside the group.

    Returns the densest subset (a list of point dicts), or [] if there is none.
    """
    best = []
    for anchor in cluster:
        within = [p for p in cluster
                  if _haversine_km(anchor["latitude"], anchor["longitude"],
                                   p["latitude"], p["longitude"]) <= HOTSPOT_RADIUS_KM]
        if len(within) > len(best):
            best = within
    return best


class TrafficMonitor:
    """Tracks sustained bus bunches and exposes active traffic hotspots."""

    def __init__(self):
        self._lock = threading.Lock()
        self._hotspots = {}          # hotspot_id -> state dict
        self._next_id = 1
        self._history = []           # rolling observation log for analytics
        self._last_update = None

    # -- public API ---------------------------------------------------------

    def update(self, buses, now=None):
        """Feed the current bus positions. Call on a fixed cadence (e.g. 5s)."""
        now = now if now is not None else time.time()
        clusters = _cluster_buses(buses)

        with self._lock:
            seen = set()
            for cluster in clusters:
                if not cluster:
                    continue
                # Only the dense core counts — a spread-out chain of neighbours
                # is not "N buses within HOTSPOT_RADIUS_M".
                core = _densest_core(cluster)
                if not core:
                    continue
                c_lat = sum(p["latitude"] for p in core) / len(core)
                c_lon = sum(p["longitude"] for p in core) / len(core)
                hid, hotspot = self._match_hotspot(c_lat, c_lon, now)
                seen.add(hid)

                hotspot["last_sighting"] = now
                hotspot["count"] = len(core)
                hotspot["bus_ids"] = sorted(p["bus_id"] for p in core)
                hotspot["max_count"] = max(hotspot.get("max_count", 0), len(core))
                hotspot["centroid"] = [round(c_lat, 5), round(c_lon, 5)]

                # Consecutive-active bookkeeping with a small hysteresis so a
                # momentary dip doesn't instantly silence a legitimate zone.
                # NOTE: a fresh activation always starts at `now` — backdating
                # with the absolute dip timestamp produced epoch-era
                # active_since values and absurd durations.
                if len(core) >= MIN_BUSES:
                    if hotspot.get("active_since") is None:
                        hotspot["active_since"] = now
                    hotspot["dip_since"] = None
                else:
                    if hotspot.get("dip_since") is None:
                        hotspot["dip_since"] = now
                    if hotspot["active_since"] is not None and now - hotspot["dip_since"] >= 10.0:
                        hotspot["active_since"] = None

            # Forget hotspots that vanished a while ago; moments not seen in this
            # update stop contributing to activity immediately (blink goes out).
            for hid in list(self._hotspots.keys()):
                if hid not in seen:
                    self._hotspots[hid]["count"] = 0
                    if now - self._hotspots[hid]["last_sighting"] > EVICT_AFTER_SEC:
                        del self._hotspots[hid]

            # rolling log for analytics (cap at 240 samples)
            active = sum(1 for h in self._hotspots.values() if self._is_active(h, now))
            self._history.append({"at": _utcnow_iso(), "active": active,
                                  "total": len(self._hotspots)})
            if len(self._history) > 240:
                self._history = self._history[-240:]
            self._last_update = now

    def get_hotspots(self, now=None):
        """Active hotspots to draw on the map (rippling red zones).

        When SUPER_MIN_HOTSPOTS or more active hotspots cluster within
        SUPER_RADIUS_M of each other, they are merged into a single
        super-hotspot entry (level CRITICAL) so the map shows one big wave
        instead of many small ones.
        """
        now = now if now is not None else time.time()
        with self._lock:
            active = [(hid, h) for hid, h in self._hotspots.items()
                      if self._is_active(h, now)]
        items = [self._to_dict(hid, h, now) for hid, h in active]
        items.sort(key=lambda h: h["bus_count"], reverse=True)
        return self._merge_super_hotspots(items, now=now)

    @staticmethod
    def _merge_super_hotspots(hotspots, now=None):
        """Merge >= SUPER_MIN_HOTSPOTS nearby active red dots into one zone.

        Connected-component grouping on the centroid distance (chain members
        may be further apart than any two neighbours — a corridor is one jam).
        The merged zone keeps a representative centroid (member average), the
        union of bus ids and the peak duration. It reports `blink_only: True`
        so the UI renders a blinking ring with no expanding waves.
        """
        if len(hotspots) < SUPER_MIN_HOTSPOTS:
            return hotspots

        n = len(hotspots)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        for i in range(n):
            for j in range(i + 1, n):
                d = _haversine_km(hotspots[i]["latitude"], hotspots[i]["longitude"],
                                  hotspots[j]["latitude"], hotspots[j]["longitude"])
                if d <= SUPER_RADIUS_KM:
                    union(i, j)

        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(hotspots[i])

        out = []
        for members in groups.values():
            if len(members) < SUPER_MIN_HOTSPOTS:
                out.extend(members)
                continue
            bus_ids = []
            for m in members:
                for b in m.get("bus_ids", []):
                    if b not in bus_ids:
                        bus_ids.append(b)
            durations = [m["duration_sec"] for m in members if m.get("duration_sec") is not None]
            out.append({
                "id": "TH-SUPER-" + "-".join(m["id"] for m in members[:3]),
                "latitude": round(sum(m["latitude"] for m in members) / len(members), 5),
                "longitude": round(sum(m["longitude"] for m in members) / len(members), 5),
                "bus_count": sum(m["bus_count"] for m in members),
                "max_bus_count": max(m.get("max_bus_count", 0) for m in members),
                "bus_ids": sorted(bus_ids),
                "level": "CRITICAL",
                "duration_sec": max(durations) if durations else None,
                "first_sighted": min(m.get("first_sighted") or "" for m in members) or None,
                "last_sighted": max(m.get("last_sighted") or "" for m in members) or None,
                "merged": True,
                "blink_only": True,
                "member_count": len(members),
                "member_ids": [m["id"] for m in members],
                "radius_m": SUPER_RADIUS_M,
            })
        return out

    def analytics(self, now=None):
        """Congestion telemetry for the analytics page."""
        now = now if now is not None else time.time()
        with self._lock:
            active = []
            for hid, h in self._hotspots.items():
                if self._is_active(h, now):
                    active.append(self._to_dict(hid, h, now))
            active.sort(key=lambda a: a["duration_sec"], reverse=True)
            reported = self._merge_super_hotspots(active, now=now)
            supers = [r for r in reported if r.get("merged")]
            return {
                "active_hotspots": reported,
                "active_count": len(reported),
                "super_hotspots": supers,
                "super_count": len(supers),
                "max_buses_in_one_zone": max((a["bus_count"] for a in reported), default=0),
                "tracked_zones": len(self._hotspots),
                "history": list(self._history[-120:]),
            }

    # -- internals ----------------------------------------------------------

    def _match_hotspot(self, lat, lon, now):
        for hid, h in self._hotspots.items():
            c = h.get("centroid")
            if c is None:
                continue
            if _haversine_km(c[0], c[1], lat, lon) <= MATCH_KM:
                return hid, h
        hid = f"TH-{self._next_id:04d}"
        self._next_id += 1
        self._hotspots[hid] = {
            "centroid": [round(lat, 5), round(lon, 5)],
            "count": 0,
            "bus_ids": [],
            "max_count": 0,
            "first_sighting": now,
            "last_sighting": now,
            "active_since": None,
            "dip_since": None,
        }
        return hid, self._hotspots[hid]

    def _is_active(self, h, now):
        if h.get("active_since") is None:
            return False
        if h.get("count", 0) < MIN_BUSES:
            return False
        return (now - h["active_since"]) >= ACTIVE_WINDOW_SEC

    def _to_dict(self, hid, h, now):
        duration = None
        if h.get("active_since") is not None:
            duration = round(now - h["active_since"], 1)
        return {
            "id": hid,
            "latitude": round(h["centroid"][0], 5),
            "longitude": round(h["centroid"][1], 5),
            "bus_count": h.get("count", 0),
            "max_bus_count": h.get("max_count", 0),
            "bus_ids": h.get("bus_ids", []),
            "level": "HIGH",
            "duration_sec": duration,
            "first_sighted": h.get("first_sighting"),
            "last_sighted": h.get("last_sighting"),
            # The rule that produced this dot, so the UI never has to hardcode it.
            "radius_m": HOTSPOT_RADIUS_M,
            "min_buses": MIN_BUSES,
        }


traffic_monitor = TrafficMonitor()