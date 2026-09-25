"""One-off: apply hand-verified OSM coordinates to emergency_data.py.

Only records whose OSM match passed manual review are touched (coord_source:
"osm-exact"). All other records keep their approximate centroids, as declared
in the module docstring.
"""
import re
import sys

PATH = "/home/rohith/Desktop/Rapid-Tracker/control_centre/backend/emergency_data.py"

# facility_id -> (lat, lon, osm_name) — hand-verified against OSM objects
# (name similarity + proximity sanity + manual review of wrong pairings).
# Records NOT listed here keep their documented approximate centroids —
# no verified distinct OSM object was found for them (GH-013/014/016/017/020).
PINS = {
    # ── Hospitals (verified OSM buildings) ──
    "GH-001": (13.080897, 80.277328, "Rajiv Gandhi Government General Hospital"),
    "GH-002": (13.104217, 80.283195, "Stanley Medical College and Hospital"),
    "GH-005": (13.073582, 80.257066, "Institute of Child Health & Hospital for Children (Egmore)"),
    "GH-006": (13.114293, 80.284452, "Chennai Corporation Hospital (Tondiarpet)"),
    "GH-007": (12.945050, 80.134560, "Government Hospital, Tambaram"),
    "GH-011": (13.033662, 80.257247, "Corporation Hospital (Mylapore area)"),
    "GH-012": (12.997950, 80.256212, "Government Hospital, Adyar"),
    "GH-018": (13.088700, 80.256712, "Chennai Corporation Hospital (Perambur area)"),
    # ── Fire stations (verified OSM buildings) ──
    "FS-001": (13.086478, 80.286063, "Esplanade Fire Station (serves George Town)"),
    "FS-002": (13.105508, 80.278214, "Moolakothalam Fire Station (serves Tondiarpet)"),
    # ── Police stations (verified OSM buildings) ──
    "PS-001": (13.086472, 80.285370, "Esplanade PS (George Town)"),
    "PS-003": (13.075072, 80.257014, "F2 Egmore Police Station"),
    "PS-004": (13.035987, 80.270142, "Mylapore E1 PS"),
    "PS-005": (12.997814, 80.255718, "Adyar J2 PS"),
    "PS-006": (13.009353, 80.210692, "Guindy J3 Police station"),
    "PS-008": (13.107314, 80.152557, "Ambattur T1 Police Station"),
    "PS-009": (13.069641, 80.200459, "Koyambedu Police Station"),
    "PS-010": (12.980944, 80.220923, "Velachery Police Station"),
    "PS-016": (13.059617, 80.242768, "Nungambakkam F3 police station"),
    # ── Traffic police units (co-located with the corresponding PS — realistic) ──
    "TP-002": (13.061062, 80.262232, "D2 Anna Salai (Mount Road) Police Station"),
    "TP-004": (12.997814, 80.255718, "Adyar J2 PS (traffic unit co-located)"),
    "TP-005": (13.009353, 80.210692, "Guindy J3 PS (traffic unit co-located)"),
    "TP-006": (13.069641, 80.200459, "Koyambedu PS (traffic unit co-located)"),
    "TP-007": (12.980944, 80.220923, "Velachery PS (traffic unit co-located)"),
    "TP-008": (13.035987, 80.270142, "Mylapore E1 PS (traffic unit co-located)"),
}


def main():
    with open(PATH) as f:
        src = f.read()

    changed = 0
    for fid, (lat, lon, osm_name) in PINS.items():
        # Find the record block for this facility_id
        idx = src.find(f'"facility_id": "{fid}"')
        if idx == -1:
            print(f"!! {fid} not found")
            continue
        block_start = src.rfind("{", 0, idx)
        block_end = src.find("}", idx)
        block = src[block_start:block_end]

        new_block = re.sub(
            r'("latitude":\s*)[-\d.]+',
            lambda m: f"{m.group(1)}{lat}",
            block,
        )
        new_block = re.sub(
            r'("longitude":\s*)[-\d.]+',
            lambda m: f"{m.group(1)}{lon}",
            new_block,
        )
        if '"coord_source"' not in new_block:
            new_block = new_block.replace(
                f'"facility_id": "{fid}",',
                f'"facility_id": "{fid}",\n        "coord_source": "osm-exact",',
                1,
            )
            new_block = new_block.replace(
                '"last_updated": "2025-01-01"',
                f'"last_updated": "2026-09-12",\n        "osm_ref": "{osm_name}"',
                1,
            )
        src = src[:block_start] + new_block + src[block_end:]
        changed += 1
        print(f"✓ {fid} -> ({lat}, {lon})")

    with open(PATH, "w") as f:
        f.write(src)
    print(f"\npatched {changed}/{len(PINS)} records")


if __name__ == "__main__":
    main()
