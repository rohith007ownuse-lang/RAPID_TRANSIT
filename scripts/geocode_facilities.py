"""One-off: geocode Rapid-Tracker emergency facilities against OSM Nominatim.

Reads the facility lists from emergency_data.py, queries Nominatim (rate
limited), validates each candidate (Chennai bounding box + name-token
overlap), and writes /tmp/facility_geocode.json for review.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, "/home/rohith/Desktop/Rapid-Tracker/control_centre/backend")
import emergency_data as ED

OUT = "/tmp/facility_geocode.json"
UA = "RapidTransitGeocoder/1.0 (local development pinning; contact: rohith)"

# Chennai metropolitan area bounding box (generous)
CHENNAI_BBOX = (12.80, 79.95, 13.45, 80.40)  # S, W, N, E

STOP = {"government", "general", "hospital", "college", "station", "fire",
        "police", "traffic", "chennai", "the", "and", "&", "institute"}


def name_tokens(name):
    words = re.findall(r"[a-zA-Z0-9]+", name.lower())
    return {w for w in words if w not in STOP and len(w) > 1} or set(words)


def norm(s):
    return re.sub(r"\s+", " ", s.lower()).strip()


def query_nominatim(q, limit=3):
    url = ("https://nominatim.openstreetmap.org/search?q=" +
           urllib.parse.quote(q) +
           f"&format=json&limit={limit}&countrycodes=in&addressdetails=1")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def score_candidate(cand, tokens):
    """0..1 name-token overlap; also flag whether inside Chennai bbox."""
    lat, lon = float(cand["lat"]), float(cand["lon"])
    in_bbox = CHENNAI_BBOX[0] <= lat <= CHENNAI_BBOX[2] and \
        CHENNAI_BBOX[1] <= lon <= CHENNAI_BBOX[3]
    cname = norm(cand.get("name") or cand.get("display_name") or "")
    ctokens = name_tokens(cname)
    if tokens and ctokens:
        overlap = len(tokens & ctokens) / len(tokens)
    else:
        overlap = 0.0
    return overlap, in_bbox


def geocode_all(facilities):
    results = []
    for i, f in enumerate(facilities):
        name = f["name"]
        tokens = name_tokens(name)
        short = " ".join(sorted(tokens)) or name
        queries = [
            f"{name}, Chennai",
            f"{short}, Chennai, Tamil Nadu",
            f"{name}, Tamil Nadu",
        ]
        best = None
        for q in queries:
            try:
                cands = query_nominatim(q)
            except Exception as e:
                print(f"  ! query failed: {e}")
                cands = []
            for c in cands:
                overlap, in_bbox = score_candidate(c, tokens)
                if not in_bbox:
                    continue
                if best is None or overlap > best["overlap"]:
                    best = {
                        "overlap": round(overlap, 2),
                        "lat": float(c["lat"]),
                        "lon": float(c["lon"]),
                        "osm_name": c.get("name") or "",
                        "display_name": c.get("display_name") or "",
                        "osm_type": c.get("osm_type"),
                        "osm_id": c.get("osm_id"),
                        "class": c.get("class"),
                        "type": c.get("type"),
                        "query": q,
                    }
                if overlap >= 0.6:
                    break
            if best and best["overlap"] >= 0.6:
                break
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        results.append({
            "facility_id": f["facility_id"],
            "name": name,
            "old": [f["latitude"], f["longitude"]],
            "match": best,
        })
        m = best or {}
        print(f"[{i+1}/{len(facilities)}] {f['facility_id']} "
              f"ov={m.get('overlap')} -> ({m.get('lat')}, {m.get('lon')}) "
              f"{m.get('osm_name','')[:60]}")
    return results


def main():
    facilities = (ED.GOVERNMENT_HOSPITALS + ED.FIRE_STATIONS +
                  ED.POLICE_STATIONS + ED.TRAFFIC_POLICE)
    print(f"Geocoding {len(facilities)} facilities…")
    results = geocode_all(facilities)
    with open(OUT, "w") as fp:
        json.dump(results, fp, indent=1)
    good = sum(1 for r in results if r["match"] and r["match"]["overlap"] >= 0.5)
    print(f"\nwrote {OUT}: {good}/{len(results)} confident matches")


if __name__ == "__main__":
    main()
