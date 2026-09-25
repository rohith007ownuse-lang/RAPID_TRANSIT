"""One-off: pin Rapid-Tracker emergency facilities to exact OSM locations.

Instead of free-text geocoding (noisy), fetch ALL tagged facility objects in
the Chennai bbox from the Overpass API (amenity=hospital / fire_station /
police), then match our facility names against them locally. Writes
/tmp/facility_pin.json for review.
"""
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, "/home/rohith/Desktop/Rapid-Tracker/control_centre/backend")
import emergency_data as ED

OUT = "/tmp/facility_pin.json"
BBOX = "12.85,80.10,13.35,80.40"  # Chennai metropolitan area (compact)
CACHE_DIR = "/tmp"
OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

STOP = {"government", "general", "hospital", "college", "station", "fire",
        "rescue", "police", "traffic", "chennai", "the", "and", "&", "of",
        "for", "institute", "medical", "women", "children", "childrens",
        "district", "headquarters", "control", "room", "force", "services"}
MAX_DIST_M = 5000


def norm(s):
    return re.sub(r"\s+", " ", s.lower()).strip()


def tokens(name):
    words = re.findall(r"[a-z0-9]+", norm(name))
    core = {w for w in words if w not in STOP and len(w) > 1}
    return core or set(words)


def jaccard(a, b):
    """Symmetric similarity: |A∩B| / |A∪B|, plus containment bonus."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    contain = inter / min(len(a), len(b)) if min(len(a), len(b)) else 0
    return max(inter / union, contain * 0.9)


def fetch_overpass(amenity):
    cache = os.path.join(CACHE_DIR, f"osm_{amenity}.json")
    if os.environ.get("FORCE_REFETCH") or not os.path.exists(cache):
        q = f"""
[out:json][timeout:180];
(
  node["amenity"="{amenity}"]({BBOX});
  way["amenity"="{amenity}"]({BBOX});
  relation["amenity"="{amenity}"]({BBOX});
  node["building"="{amenity}"]({BBOX});
  way["building"="{amenity}"]({BBOX});
);
out center tags;
"""
        data = urllib.parse.urlencode({"data": q}).encode()
        js = None
        for attempt in range(3):
            for ep in OVERPASS_ENDPOINTS:
                try:
                    req = urllib.request.Request(ep, data=data, headers={"User-Agent": "RapidTransitPinner/1.0"})
                    with urllib.request.urlopen(req, timeout=180) as r:
                        js = json.load(r)
                    break
                except Exception as e:
                    print(f"  ! {ep.split('/')[2]} failed: {e}")
            if js is not None:
                break
            print(f"  …retry {attempt+2}/3 after 20s")
            time.sleep(20)
        if js is None:
            raise RuntimeError("all Overpass endpoints failed")
        out = []
        for el in js.get("elements", []):
            tags = el.get("tags", {})
            name = tags.get("name") or tags.get("name:en") or ""
            if not name:
                continue
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat is None:
                continue
            out.append({
                "name": name, "lat": lat, "lon": lon,
                "osm_type": el["type"], "osm_id": el["id"],
                "operator": tags.get("operator", ""),
                "emergency": tags.get("emergency", ""),
            })
        with open(cache, "w") as fp:
            json.dump(out, fp)
    with open(cache) as fp:
        return json.load(fp)


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def best_match(f, pool):
    """Rank candidates by name similarity AND proximity to the old coord.

    The legacy coordinate is an approximate centroid for the right
    neighborhood, so it is a good prior: candidates farther than MAX_DIST_M
    are ignored; among the rest score = 0.75*name + 0.25*proximity.
    """
    ft = tokens(f["name"])
    # Neighborhood hint from "Name (Area)" patterns
    m = re.search(r"\(([^)]+)\)", f["name"])
    area_tokens = tokens(m.group(1)) if m else set()

    olat, olon = f["latitude"], f["longitude"]
    scored = []
    for c in pool:
        d = haversine_m(olat, olon, c["lat"], c["lon"])
        if d > MAX_DIST_M:
            continue
        ct = tokens(c["name"])
        s = jaccard(ft, ct)
        # bonus if the area hint appears in the OSM name
        if area_tokens and area_tokens & ct:
            s = min(1.0, s + 0.15)
        prox = max(0.0, 1 - d / MAX_DIST_M)
        total = 0.75 * s + 0.25 * prox
        if total > 0:
            scored.append((total, s, d, c))
    scored.sort(key=lambda x: -x[0])
    out = []
    for total, s, d, c in scored[:3]:
        cc = dict(c)
        cc["dist_m"] = int(d)
        out.append((total, s, cc))
    return out


def main():
    print("Fetching OSM facility objects via Overpass…")
    pools = {
        "hospital": fetch_overpass("hospital") + fetch_overpass("clinic"),
        "fire_station": fetch_overpass("fire_station"),
        "police": fetch_overpass("police"),
    }
    print(f"OSM objects: hospital/clinic={len(pools['hospital'])}, "
          f"fire={len(pools['fire_station'])}, police={len(pools['police'])}")

    groups = [
        (ED.GOVERNMENT_HOSPITALS, "hospital"),
        (ED.FIRE_STATIONS, "fire_station"),
        (ED.POLICE_STATIONS, "police"),
        (ED.TRAFFIC_POLICE, "police"),
    ]
    results = []
    for facilities, pool_name in groups:
        pool = pools[pool_name]
        for f in facilities:
            top = best_match(f, pool)
            best = top[0] if top else (0.0, 0.0, None)
            results.append({
                "facility_id": f["facility_id"],
                "name": f["name"],
                "old": [f["latitude"], f["longitude"]],
                "score": round(best[0], 2),
                "name_sim": round(best[1], 2),
                "match": best[2],
                "runners_up": [
                    {"name": c["name"], "score": round(t, 2), "dist_m": c.get("dist_m")}
                    for t, s, c in top[1:3]
                ],
            })
            b = best[2] or {}
            print(f"{f['facility_id']} s={best[0]:.2f} ns={best[1]:.2f} d={b.get('dist_m','—'):>5} "
                  f"{f['name'][:40]:42s} -> {b.get('name','—')[:44]}")

    with open(OUT, "w") as fp:
        json.dump(results, fp, indent=1)
    exact = sum(1 for r in results if r["score"] >= 0.5)
    print(f"\nwrote {OUT}: {exact}/{len(results)} matches ≥0.5")


if __name__ == "__main__":
    main()
