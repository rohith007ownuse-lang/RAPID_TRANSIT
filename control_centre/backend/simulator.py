"""
simulator.py
Demo fleet simulation for the Control Centre UI.

Produces evolving bus states and occasional events so the dashboard behaves
like a real operations centre. ALL output is synthetic demo data and is
never presented as real measurement; the UI labels it SIMULATION.

Realistic demo model:
  * Bus identity is the MTC route code (e.g. "19D"), with multiple buses on
    the same corridor named "19D .1", "19D .2", ...  Each bus also carries a
    Chennai TN registration number (e.g. TN-01-F-0234).
  * Each route is a sequence of bus stops. A bus progresses stop by stop,
    pausing at each stop long enough for a small, realistic number of
    passengers to board on a ticket (2-3 at normal stops, 10-12 at major
    terminals such as Tambaram/Pallavaram/Chromepet). Tickets are therefore
    tied to stop boardings, never to hundreds-per-second.
  * Vehicles are EV or diesel. EV reports battery %, diesel reports fuel %.
    4-wheel tyre pressure in PSI is tracked, plus running speed.
  * Load is payload (passengers + luggage) bounded to the payload limit
    (6,000 kg); GVW = tare (11,000) + payload, bounded ~17,000 kg.

Real bus data will replace this in a later phase (bus_node -> WebSocket).
"""

import random
import threading
import time
from collections import deque
from math import hypot

from data_store import store, mode_state, utcnow_iso
from predictive_health import tick_all, DataSource, generate_health_events

SIMULATION = True

# ---------------------------------------------------------------------------
# Routes with realistic Chennai/North-India MTC stop sequences.
# Each stop: {"stop": name, "lat": .., "lon": .., "major": bool}
# Major stops (terminals / junctions) board more passengers than minor stops.
# 70V runs the classic Koyambedu (CMBT) -> Kilambakkam (KCBT) corridor (~20 stops).
# ---------------------------------------------------------------------------
ROUTES = [
    {
        "code": "1A", "name": "1A - Thiruvottiyur to Broadway",
        "stops": [
            {"stop": "Thiruvottiyur", "lat": 13.1600, "lon": 80.2980, "major": True},
            {"stop": "Thangal", "lat": 13.1420, "lon": 80.2920, "major": False},
            {"stop": "Toll Gate", "lat": 13.1250, "lon": 80.2860, "major": False},
            {"stop": "Vyasarpadi", "lat": 13.1190, "lon": 80.2830, "major": False},
            {"stop": "Konnur", "lat": 13.1120, "lon": 80.2820, "major": False},
            {"stop": "Tondiarpet", "lat": 13.1150, "lon": 80.2830, "major": False},
            {"stop": "Manali", "lat": 13.1050, "lon": 80.2820, "major": False},
            {"stop": "Old Jail Road", "lat": 13.0960, "lon": 80.2800, "major": False},
            {"stop": "Washermanpet", "lat": 13.0990, "lon": 80.2810, "major": False},
            {"stop": "HK Road", "lat": 13.0890, "lon": 80.2780, "major": False},
            {"stop": "Broadway", "lat": 13.0827, "lon": 80.2747, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "19D", "name": "19D - Thambaram to Beach",
        "stops": [
            {"stop": "Thambaram", "lat": 12.9250, "lon": 80.1270, "major": True},
            {"stop": "Tambaram Sanatorium", "lat": 12.9350, "lon": 80.1400, "major": False},
            {"stop": "Chromepet", "lat": 12.9510, "lon": 80.1530, "major": True},
            {"stop": "Pallavaram", "lat": 12.9680, "lon": 80.1600, "major": True},
            {"stop": "Tirusulam", "lat": 12.9890, "lon": 80.1670, "major": False},
            {"stop": "Meenambakkam", "lat": 12.9941, "lon": 80.1707, "major": False},
            {"stop": "Guindy", "lat": 13.0080, "lon": 80.2220, "major": True},
            {"stop": "Saidapet", "lat": 13.0200, "lon": 80.2230, "major": True},
            {"stop": "Teynampet", "lat": 13.0280, "lon": 80.2500, "major": False},
            {"stop": "Anna Salai", "lat": 13.0550, "lon": 80.2600, "major": False},
            {"stop": "LIC", "lat": 13.0660, "lon": 80.2700, "major": False},
            {"stop": "Fort", "lat": 13.0780, "lon": 80.2740, "major": False},
            {"stop": "Beach", "lat": 13.0827, "lon": 80.2747, "major": True},
        ],
        "ev": True,
    },
    {
        "code": "23C", "name": "23C - T.Nagar to Koyambedu",
        "stops": [
            {"stop": "T.Nagar", "lat": 13.0320, "lon": 80.2350, "major": True},
            {"stop": "Lloyds Road", "lat": 13.0360, "lon": 80.2370, "major": False},
            {"stop": "Ashok Pillar", "lat": 13.0380, "lon": 80.2070, "major": False},
            {"stop": "Jafferkhanpet", "lat": 13.0480, "lon": 80.2200, "major": False},
            {"stop": "Valasaravakkam", "lat": 13.0480, "lon": 80.2050, "major": False},
            {"stop": "Vadapalani", "lat": 13.0510, "lon": 80.2150, "major": False},
            {"stop": "Virugambakkam", "lat": 13.0550, "lon": 80.2100, "major": False},
            {"stop": "Alwarthirunagar", "lat": 13.0700, "lon": 80.2050, "major": False},
            {"stop": "Nerkundram", "lat": 13.0840, "lon": 80.1980, "major": False},
            {"stop": "Koyambedu Theater", "lat": 13.0860, "lon": 80.2020, "major": False},
            {"stop": "Koyambedu", "lat": 13.0830, "lon": 80.2050, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "28B", "name": "28B - Adyar to Avadi",
        "stops": [
            {"stop": "Adyar", "lat": 13.0063, "lon": 80.2569, "major": True},
            {"stop": "Guindy", "lat": 13.0080, "lon": 80.2220, "major": False},
            {"stop": "Nandanam", "lat": 13.0280, "lon": 80.2280, "major": False},
            {"stop": "Kotturpuram", "lat": 13.0200, "lon": 80.2400, "major": False},
            {"stop": "Choolai", "lat": 13.0820, "lon": 80.2650, "major": False},
            {"stop": "Kilpauk", "lat": 13.0750, "lon": 80.2450, "major": False},
            {"stop": "Anna Nagar", "lat": 13.0886, "lon": 80.2101, "major": True},
            {"stop": "Koyambedu", "lat": 13.0830, "lon": 80.2050, "major": False},
            {"stop": "Padi", "lat": 13.0930, "lon": 80.1850, "major": False},
            {"stop": "Avadi", "lat": 13.1100, "lon": 80.1000, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "52K", "name": "52K - Anna Nagar to Velachery",
        "stops": [
            {"stop": "Anna Nagar", "lat": 13.0886, "lon": 80.2101, "major": True},
            {"stop": "Shanthi Colony", "lat": 13.0890, "lon": 80.2150, "major": False},
            {"stop": "Ayyavoo Colony", "lat": 13.0850, "lon": 80.2200, "major": False},
            {"stop": "K.K.Nagar", "lat": 13.0700, "lon": 80.2180, "major": False},
            {"stop": "Kasi Theatre", "lat": 13.0500, "lon": 80.2300, "major": False},
            {"stop": "Teynampet", "lat": 13.0280, "lon": 80.2500, "major": False},
            {"stop": "Nandanam", "lat": 13.0280, "lon": 80.2280, "major": False},
            {"stop": "MRTS Road", "lat": 13.0100, "lon": 80.2350, "major": False},
            {"stop": "Central Library", "lat": 12.9920, "lon": 80.2320, "major": False},
            {"stop": "OMR Junction", "lat": 12.9850, "lon": 80.2250, "major": False},
            {"stop": "Velachery", "lat": 12.9810, "lon": 80.2200, "major": True},
        ],
        "ev": True,
    },
    {
        "code": "M57", "name": "M57 - Guindy to Marina",
        "stops": [
            {"stop": "Guindy", "lat": 13.0080, "lon": 80.2220, "major": True},
            {"stop": "Gandhi Mandapam", "lat": 13.0170, "lon": 80.2320, "major": False},
            {"stop": "Gandhi Statue", "lat": 13.0400, "lon": 80.2550, "major": False},
            {"stop": "Mandaveli", "lat": 13.0200, "lon": 80.2650, "major": False},
            {"stop": "Foreshore Estate", "lat": 13.0330, "lon": 80.2700, "major": False},
            {"stop": "Anna Square", "lat": 13.0450, "lon": 80.2790, "major": False},
            {"stop": "Lady Doak College", "lat": 13.0550, "lon": 80.2710, "major": False},
            {"stop": "Fort St. George", "lat": 13.0700, "lon": 80.2600, "major": False},
            {"stop": "Queens Road", "lat": 13.0630, "lon": 80.2760, "major": False},
            {"stop": "Marina", "lat": 13.0500, "lon": 80.2820, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "70V", "name": "70V - Koyambedu to Kilambakkam",
        "stops": [
            {"stop": "Koyambedu (CMBT)", "lat": 13.0830, "lon": 80.2050, "major": True},
            {"stop": "Vadapalani", "lat": 13.0529, "lon": 80.2010, "major": False},
            {"stop": "Ashok Nagar", "lat": 13.0400, "lon": 80.2080, "major": False},
            {"stop": "Kodambakkam", "lat": 13.0510, "lon": 80.2310, "major": False},
            {"stop": "T Nagar", "lat": 13.0329, "lon": 80.2420, "major": False},
            {"stop": "Saidapet", "lat": 13.0210, "lon": 80.2240, "major": False},
            {"stop": "Guindy", "lat": 13.0080, "lon": 80.2220, "major": True},
            {"stop": "Kathipara", "lat": 13.0000, "lon": 80.2050, "major": False},
            {"stop": "Alandur", "lat": 12.9990, "lon": 80.2050, "major": False},
            {"stop": "St.Thomas Mount", "lat": 12.9940, "lon": 80.1950, "major": True},
            {"stop": "Nanganallur", "lat": 12.9870, "lon": 80.1810, "major": False},
            {"stop": "Pallavaram", "lat": 12.9680, "lon": 80.1590, "major": True},
            {"stop": "Chromepet", "lat": 12.9520, "lon": 80.1530, "major": True},
            {"stop": "Tambaram", "lat": 12.9250, "lon": 80.1270, "major": True},
            {"stop": "Perungalathur", "lat": 12.9040, "lon": 80.1420, "major": False},
            {"stop": "Vandalur", "lat": 12.8880, "lon": 80.0820, "major": False},
            {"stop": "Kelambakkam Rd", "lat": 12.8750, "lon": 80.1200, "major": False},
            {"stop": "Guduvancherry", "lat": 12.8480, "lon": 80.0670, "major": False},
            {"stop": "Urapakkam", "lat": 12.8320, "lon": 80.1450, "major": False},
            {"stop": "Kilambakkam (KCBT)", "lat": 12.8800, "lon": 80.1900, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "88", "name": "88 - Velachery to Kelambakkam OMR",
        "stops": [
            {"stop": "Velachery", "lat": 12.9810, "lon": 80.2200, "major": True},
            {"stop": "Thiruvanmiyur", "lat": 12.9840, "lon": 80.2530, "major": False},
            {"stop": "Tarapore Towers", "lat": 12.9800, "lon": 80.2490, "major": False},
            {"stop": "Perungudi", "lat": 12.9600, "lon": 80.2420, "major": False},
            {"stop": "Thoraipakkam", "lat": 12.9320, "lon": 80.2380, "major": False},
            {"stop": "Kottivakkam", "lat": 12.9650, "lon": 80.2470, "major": False},
            {"stop": "Sholinganallur", "lat": 12.9690, "lon": 80.2310, "major": False},
            {"stop": "Padur", "lat": 12.8950, "lon": 80.2290, "major": False},
            {"stop": "Semmancheri", "lat": 12.8680, "lon": 80.2350, "major": False},
            {"stop": "Kelambakkam", "lat": 12.8400, "lon": 80.2200, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "102", "name": "102 - Broadway to T.Nagar",
        "stops": [
            {"stop": "Broadway", "lat": 13.0827, "lon": 80.2747, "major": True},
            {"stop": "Rajiv Gandhi Salai", "lat": 13.0500, "lon": 80.2450, "major": False},
            {"stop": "Saidapet", "lat": 13.0200, "lon": 80.2230, "major": False},
            {"stop": "Nandanam", "lat": 13.0280, "lon": 80.2280, "major": False},
            {"stop": "Beach Station", "lat": 13.0820, "lon": 80.2790, "major": False},
            {"stop": "Anna Salai", "lat": 13.0550, "lon": 80.2600, "major": False},
            {"stop": "LIC", "lat": 13.0660, "lon": 80.2700, "major": False},
            {"stop": "Central", "lat": 13.0827, "lon": 80.2747, "major": False},
            {"stop": "Egmore", "lat": 13.0770, "lon": 80.2590, "major": False},
            {"stop": "Shenoy Nagar", "lat": 13.0700, "lon": 80.2470, "major": False},
            {"stop": "T.Nagar", "lat": 13.0320, "lon": 80.2350, "major": True},
        ],
        "ev": True,
    },
    {
        "code": "146C", "name": "146C - Ambattur to Anna Nagar",
        "stops": [
            {"stop": "Ambattur", "lat": 13.1130, "lon": 80.1600, "major": True},
            {"stop": "Pattabiram", "lat": 13.1230, "lon": 80.1400, "major": False},
            {"stop": "Mangadu", "lat": 13.0060, "lon": 80.1750, "major": False},
            {"stop": "Tirumullaivoyal", "lat": 13.1200, "lon": 80.1250, "major": False},
            {"stop": "Padi", "lat": 13.0930, "lon": 80.1850, "major": False},
            {"stop": "Korattur", "lat": 13.1150, "lon": 80.1900, "major": False},
            {"stop": "Mogappair", "lat": 13.0860, "lon": 80.1980, "major": False},
            {"stop": "Nolambur", "lat": 13.0770, "lon": 80.1920, "major": False},
            {"stop": "Thirumangalam", "lat": 13.0830, "lon": 80.1960, "major": False},
            {"stop": "Anna Nagar Tower", "lat": 13.0860, "lon": 80.2050, "major": False},
            {"stop": "Anna Nagar", "lat": 13.0886, "lon": 80.2101, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "18E", "name": "18E - T.Nagar to Parrys",
        "stops": [
            {"stop": "T.Nagar", "lat": 13.0320, "lon": 80.2350, "major": True},
            {"stop": "Raja Annamalai Puram", "lat": 13.0500, "lon": 80.2500, "major": False},
            {"stop": "Royapettah", "lat": 13.0390, "lon": 80.2640, "major": False},
            {"stop": "Triplicane", "lat": 13.0770, "lon": 80.2680, "major": False},
            {"stop": "Chintadripet", "lat": 13.0720, "lon": 80.2700, "major": False},
            {"stop": "Nungambakkam Post Office", "lat": 13.0630, "lon": 80.2460, "major": False},
            {"stop": "Spur Tank Road", "lat": 13.0690, "lon": 80.2520, "major": False},
            {"stop": "Kilpauk", "lat": 13.0750, "lon": 80.2450, "major": False},
            {"stop": "Chetpet", "lat": 13.0700, "lon": 80.2510, "major": False},
            {"stop": "Money Compound", "lat": 13.0850, "lon": 80.2700, "major": False},
            {"stop": "Parrys", "lat": 13.0900, "lon": 80.2790, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "5", "name": "5 - High Court to Tambaram",
        "stops": [
            {"stop": "High Court", "lat": 13.0827, "lon": 80.2747, "major": True},
            {"stop": "Teynampet", "lat": 13.0280, "lon": 80.2500, "major": False},
            {"stop": "Saidapet", "lat": 13.0200, "lon": 80.2230, "major": False},
            {"stop": "Guindy", "lat": 13.0080, "lon": 80.2220, "major": False},
            {"stop": "Guindy Railway", "lat": 13.0100, "lon": 80.2120, "major": False},
            {"stop": "Meenambakkam", "lat": 12.9941, "lon": 80.1707, "major": False},
            {"stop": "Pallavaram", "lat": 12.9680, "lon": 80.1600, "major": True},
            {"stop": "Chromepet", "lat": 12.9510, "lon": 80.1530, "major": True},
            {"stop": "Thambaram Sanatorium", "lat": 12.9350, "lon": 80.1400, "major": False},
            {"stop": "Tambaram", "lat": 12.9250, "lon": 80.1270, "major": True},
        ],
        "ev": False,
    },
    {
        "code": "A11", "name": "A11 - Airport to Central",
        "stops": [
            {"stop": "Airport (MAA)", "lat": 12.9941, "lon": 80.1707, "major": True},
            {"stop": "Tirusulam", "lat": 12.9890, "lon": 80.1670, "major": False},
            {"stop": "Pallavaram", "lat": 12.9680, "lon": 80.1600, "major": False},
            {"stop": "Saidapet", "lat": 13.0200, "lon": 80.2230, "major": False},
            {"stop": "Egmore", "lat": 13.0770, "lon": 80.2590, "major": False},
            {"stop": "Mint", "lat": 13.0870, "lon": 80.2700, "major": False},
            {"stop": "Chennai Fort", "lat": 13.0750, "lon": 80.2600, "major": False},
            {"stop": "LIC", "lat": 13.0660, "lon": 80.2700, "major": False},
            {"stop": "Mount Road QMC", "lat": 13.0600, "lon": 80.2630, "major": False},
            {"stop": "Central", "lat": 13.0827, "lon": 80.2747, "major": True},
        ],
        "ev": True,
    },
    {
        "code": "45", "name": "45 - T.Nagar to St.Thomas Mount",
        "stops": [
            {"stop": "T.Nagar", "lat": 13.0320, "lon": 80.2350, "major": True},
            {"stop": "Saidapet", "lat": 13.0200, "lon": 80.2230, "major": False},
            {"stop": "Guindy", "lat": 13.0080, "lon": 80.2220, "major": False},
            {"stop": "Ekkattuthangal", "lat": 13.0140, "lon": 80.2010, "major": False},
            {"stop": "Kathipara", "lat": 13.0000, "lon": 80.2050, "major": False},
            {"stop": "Alandur", "lat": 12.9990, "lon": 80.2050, "major": False},
            {"stop": "Nanganallur", "lat": 12.9870, "lon": 80.1810, "major": False},
            {"stop": "Thirumudivakkam", "lat": 12.9800, "lon": 80.1830, "major": False},
            {"stop": "Pallavaram", "lat": 12.9680, "lon": 80.1600, "major": True},
            {"stop": "St.Thomas Mount", "lat": 12.9930, "lon": 80.2000, "major": True},
        ],
        "ev": False,
    },
]

TARE_KG = 11000          # unladen bus
MAX_GVW_KG = 17000       # GVW bound (~11000 tare + 6000 payload)
PAYLOAD_LIMIT_KG = 6000  # max passenger+luggage payload

DRIVER_STATES = ["NORMAL", "NORMAL", "NORMAL", "ATTENTION", "DROWSY"]
HEALTH_STATES = ["NORMAL", "NORMAL", "NORMAL", "NORMAL", "WARNING", "INSPECTION REQUIRED"]
VEHICLE_ANOMALIES = ["none", "none", "none", "excessive vibration", "harsh braking"]
CROWD_LEVELS = ["NORMAL", "NORMAL", "MODERATE", "HIGH", "CRITICAL CROWDING"]

EVENT_TYPES = [
    "DRIVER_DROWSINESS", "POTHOLE", "EMERGENCY_SIREN", "OVERLOAD",
    "VEHICLE_ANOMALY", "CRASH", "CABIN_FIRE", "CABIN_SMOKE", "CABIN_INCIDENT",
]

# Fleet expansion: ~100 MTC-schedule services. Only a fraction of buses are
# "alert-prone", so the feed stays calm even at this fleet size.
NUM_BUSES = 100

# Average ticket price (₹) for every bus in the demo fleet.
AVG_FARE = 18.5

# Realistic MTC fare card (₹ per ticket by distance band, demo).
FARE_BY_BAND = [(0, 15, 6), (15, 29, 10), (29, 43, 15), (43, 60, 20), (60, 999, 30)]

# Simulated service-day clock. MTC starts ~4:30-5 AM and rotates until ~11 PM.
SERVICE_START_MIN = 4 * 60     # 04:00
SERVICE_END_MIN = 23 * 60      # 23:00 (last rotation)
SIM_MIN_PER_TICK = 2.0         # sim minutes per tick (~19 h day loops every ~9.5 min real)

# Relative boarding demand by hour (morning + evening rush peaks, lunch/afternoon lull).
HOURLY_DEMAND = {
    4: 0.25, 5: 0.5, 6: 1.0, 7: 2.2, 8: 2.6, 9: 1.9, 10: 1.2, 11: 1.0,
    12: 0.9, 13: 0.8, 14: 0.55, 15: 0.7, 16: 1.1, 17: 1.9, 18: 2.3,
    19: 1.6, 20: 1.0, 21: 0.6, 22: 0.3,
}


def fare_for_stops(num_stops):
    """Approx ₹ fare from number of stops travelled (demo MTC fare card)."""
    # longer journey = more bands
    km = num_stops * 2.5
    for lo, hi, fare in FARE_BY_BAND:
        if lo <= km < hi:
            return float(fare)
    return 30.0


def max_gv_kw() -> int:
    return MAX_GVW_KG


class FleetSimulator:
    DRIVER_NAMES = [
        "Rosina", "Karthik", "Priya", "Muthukumar", "Selvam", "Anitha",
        "Ramesh", "Lakshmi", "Venkatesh", "Deepa", "Arun", "Meena",
        "Suresh", "Kavitha", "Ravi", "Divya",
    ]

    def __init__(self, tick=1.0):
        self.tick = tick
        self._stop = False
        self._thread = None
        self._next_event = {}
        self._prone = set()          # only these buses may raise alerts
        self._ear_hist = {}          # bus_id -> rolling EAR window (PERCLOS)
        self._prev_stage = {}        # bus_id -> last fatigue stage (transition detection)
        self.sim_minutes = SERVICE_START_MIN   # service-day clock starts 04:00
        self._init_buses()
        self._seed_initial()

    def _scan_interval(self):
        """Per-tick sleep in seconds, read from settings so the control room can
        change the scan cadence without a backend restart (defaults to self.tick)."""
        sim_cfg = store.get_settings().get("simulator") or {}
        try:
            return max(0.1, float(sim_cfg.get("scan_interval_s", self.tick)))
        except (TypeError, ValueError):
            return self.tick

    def sim_hour(self):
        """Current service-day hour (0-23) for the simulated clock."""
        return int(self.sim_minutes // 60) % 24

    # ------------------------------------------------------------------ init
    def _init_buses(self):
        rng = random.Random(2026)
        zones = ["A", "B", "F", "N", "Q", "R", "U", "D", "M", "G"]
        instances = {}  # route code -> bus index on that route (1.1, 1.2, ..)
        reg_base = 2400  # realistic registration numbers
        created = 0
        i = 0
        while created < NUM_BUSES:
            route = ROUTES[i % len(ROUTES)]
            idx = instances.get(route["code"], 0) + 1
            instances[route["code"]] = idx
            # bus name = "19D" for the first, "19D .2" for later buses
            bus_name = route["code"] if idx == 1 else f"{route['code']} .{idx}"
            if created % 5 == 0 and len(self._prone) < 5:   # ~5 alert-prone services max
                self._prone.add(bus_name)
            zone = zones[(created + 3) % len(zones)]
            reg_no = f"TN-01-{zone}-{reg_base + created:04d}"

            first_stop = route["stops"][0]
            bus = {
                "bus_id": bus_name,          # "19D" / "19D .2"
                "reg_no": reg_no,            # "TN-01-F-0234"
                "route_code": route["code"],  # "19D"
                "route": route["name"],      # "19D - Thambaram to Beach"
                "latitude": first_stop["lat"] + rng.uniform(-0.002, 0.002),
                "longitude": first_stop["lon"] + rng.uniform(-0.002, 0.002),
                "speed_kmh": 0.0,
                "vehicle_type": "EV" if route["ev"] else "DIESEL",
                "driver": {"state": "NORMAL", "name": self.DRIVER_NAMES[created % len(self.DRIVER_NAMES)],
                           "ear": 0.30, "mar": 0.35,
                           "head_pitch_deg": 0.0, "closed_sec": 0.0, "drowsy": False,
                           "fatigue_stage": "WATCH",
                           "fatigue_lt": round(rng.uniform(2.0, 14.0), 1),
                           "fatigue_st": 0.0, "perclos": 0.0, "episode": None},
                "occupancy": {"passengers": 0, "pct": 0, "crowd": "NORMAL", "capacity": 60},
                "energy": self._fresh_energy(rng, route["ev"]),
                "wheels": self._fresh_wheels(rng),
                "load": self._fresh_load(rng, 0),
                "vehicle": {"health": "NORMAL", "anomaly": "none",
                            "vibration": rng.uniform(0.1, 0.5),
                            "braking_events": 0, "maintenance_priority": "LOW",
                            "type": "EV" if route["ev"] else "DIESEL"},
                "journey": self._fresh_journey(route),
                "ticketing": self._fresh_ticketing(rng),
                "last_update": utcnow_iso(),
                "simulation": True,
            }
            self._build_boarding_profile(bus, rng)
            store.upsert_bus(bus)
            self._next_event[bus_name] = time.time() + rng.uniform(15, 90)
            i += 1
            created += 1

    def _build_boarding_profile(self, bus, rng):
        """Pre-compute realistic daily boarding analytics for this bus.

        How many passengers get on at each stop during each hour of the MTC
        service day. Mirrors the real pattern: a strong morning rush (7-9 AM),
        a secondary evening rush (5-8 PM), and a quiet afternoon lull where
        only a handful board (e.g. ~2 at 2-3 PM). Major stops/terminals (like
        Koyambedu / Tambaram) attract far more riders than minor stops.
        """
        rdef = next(r for r in ROUTES if r["code"] == bus["route_code"])
        stops = rdef["stops"]
        total = rng.randint(540, 740)               # realistic passengers/day per bus
        hours = sorted(HOURLY_DEMAND)
        sum_demand = sum(HOURLY_DEMAND[h] for h in hours)
        stop_w = [(7 if i == 0 else 4 if s["major"] else 1) for i, s in enumerate(stops)]
        sum_w = sum(stop_w)

        by_hour = {h: 0 for h in range(24)}
        by_stop_hour = {s["stop"]: {h: 0 for h in range(24)} for s in stops}
        for h in hours:
            h_total = round(total * HOURLY_DEMAND[h] / sum_demand)
            cum = 0
            for i, s in enumerate(stops):
                share = max(0, round(h_total * stop_w[i] / sum_w + rng.uniform(-0.6, 0.6)))
                by_stop_hour[s["stop"]][h] = share
                cum += share
            if cum != h_total:  # soak rounding drift into the busiest stop
                top = max(stops, key=lambda s: by_stop_hour[s["stop"]][h])
                by_stop_hour[top["stop"]][h] += h_total - cum
            by_hour[h] = h_total

        peak_hour = max(hours, key=lambda h: by_hour[h])
        bus["boarding_by_hour"] = by_hour
        bus["boarding_by_stop_hour"] = by_stop_hour
        bus["daily_boarding_total"] = total
        bus["boarding_peak_hour"] = peak_hour

    def _fresh_journey(self, route):
        """Describe the stop-by-stop journey for this route."""
        stops = [{"stop": s["stop"], "lat": s["lat"], "lon": s["lon"],
                  "major": s["major"], "boarded": 0} for s in route["stops"]]
        return {
            "start": stops[0]["stop"],
            "destination": stops[-1]["stop"],
            "total_stops": len(stops),
            "current_index": 0,
            "next_index": 1,
            "state": "AT_STOP",          # AT_STOP | MOVING | ARRIVING
            "progress": 0.0,             # 0..1 between current and next stop
            "stops": stops,              # each has a boarded count
        }

    def _fresh_energy(self, rng, is_ev):
        if is_ev:
            return {"type": "EV", "percent": round(rng.uniform(62, 96), 1), "kwh": round(rng.uniform(50, 260), 1)}
        return {"type": "DIESEL", "percent": round(rng.uniform(18, 82), 1), "litres": round(rng.uniform(20, 180), 1)}

    def _fresh_wheels(self, rng):
        return [round(rng.uniform(78, 92), 1) for _ in range(4)]  # approx PSI (x100 kPa)

    def _fresh_load(self, rng, passengers):
        # payload = riders + luggage; bound within 6000 kg
        payload = max(400, min(PAYLOAD_LIMIT_KG, passengers * 68 + rng.uniform(200, 1800)))
        return self._make_load(payload)

    def _make_load(self, payload_kg):
        payload_kg = max(0.0, min(float(payload_kg), float(PAYLOAD_LIMIT_KG)))
        gvw = TARE_KG + payload_kg
        gvw = min(float(gvw), float(MAX_GVW_KG))
        pct = round(100 * payload_kg / PAYLOAD_LIMIT_KG)
        if pct > 100:
            status = "CRITICAL OVERLOAD"
        elif pct > 90:
            status = "HIGH LOAD"
        else:
            status = "NORMAL"
        return {
            "gvw_kg": round(gvw), "tare_kg": TARE_KG, "payload_kg": round(payload_kg),
            "payload_limit_kg": PAYLOAD_LIMIT_KG, "load_pct": pct, "status": status,
        }

    def _fresh_ticketing(self, rng):
        return {
            "tickets_today": 0,
            "passengers_total": 0,
            "fare_collected": 0.0,
            "avg_fare": AVG_FARE,
            "avg_km": round(rng.uniform(4.0, 14.0), 1),
            "device": "MTC ticket machine TMS-5",
        }

    def _seed_initial(self):
        rng = random.Random(7)
        buses = [b for b in store.get_buses() if b["bus_id"] in self._prone]
        if not buses:
            return
        # start the alert-prone subset with believable mid-shift fatigue so the
        # risk feed is not flat at login; stages set so no burst of events fires
        for b in buses:
            d = b["driver"]
            d["fatigue_lt"] = round(rng.uniform(35.0, 75.0), 1)
            d["fatigue_stage"] = "ALERT" if d["fatigue_lt"] < 65 else "CRITICAL"
            d["_prev_stage"] = d["fatigue_stage"]
        type_pool = ["DRIVER_DROWSINESS", "OVERLOAD", "VEHICLE_ANOMALY", "CABIN_INCIDENT", "DRIVER_DROWSINESS"]
        seeds = [(0.91, "CRITICAL"), (0.78, "WARNING"), (0.83, "WARNING"),
                 (0.70, "INFO"), (0.88, "WARNING")]
        for i, (etype, (conf, sev)) in enumerate(zip(type_pool, seeds)):
            bus = rng.choice(buses)
            event = {
                "bus_id": bus["bus_id"],
                "event_type": etype,
                "latitude": round(bus["latitude"] + rng.uniform(-0.02, 0.02), 6),
                "longitude": round(bus["longitude"] + rng.uniform(-0.02, 0.02), 6),
                "severity": sev,
                "confidence": conf,
                "sensor_source": self._source_for(etype),
                "status": rng.choices(["ACTIVE", "ACKNOWLEDGED", "RESOLVED"],
                                      weights=[2, 2, 2])[0],
                "simulation": True,
                "additional_data": {"note": "Seeded demo history"},
            }
            store.add_event(event)

        for d_idx in range(2):
            anchor_bus = buses[d_idx % len(buses)]
            lat, lon = anchor_bus["latitude"], anchor_bus["longitude"]
            key = f"{round(lat, 3)}_{round(lon, 3)}"
            detecting = [anchor_bus["bus_id"]]
            for _ in range(rng.randint(0, 1)):
                b2 = rng.choice(buses)
                if b2["bus_id"] not in detecting:
                    detecting.append(b2["bus_id"])
            defect = {
                "defect_id": key, "type": "pothole",
                "latitude": round(lat, 4), "longitude": round(lon, 4),
                "detection_count": rng.randint(2, 4),
                "confidence": round(rng.uniform(0.6, 0.9), 2),
                "first_detected": utcnow_iso(),
                "last_detected": utcnow_iso(),
                "buses": detecting, "status": "ACTIVE",
                "image": f"pothole-seed-{d_idx}.jpg", "last_image": f"pothole-seed-{d_idx}.jpg",
            }
            store.upsert_road_defect(key, defect)

    # ------------------------------------------------------------------ run
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def _run(self):
        while not self._stop:
            try:
                # Only tick in simulation mode
                if mode_state.is_simulation and not self._stop:
                    self._tick()
            except Exception as e:  # keep sim alive
                print(f"[simulator] tick error: {e}")
            time.sleep(self._scan_interval())

    def _tick(self):
        rng = random.Random()
        now = time.time()
        self.sim_minutes += SIM_MIN_PER_TICK
        if self.sim_minutes >= SERVICE_END_MIN:
            self.sim_minutes = SERVICE_START_MIN   # next service-day rotation
            # a fresh shift: reset driver fatigue accumulators for every bus
            for b in store.get_buses():
                d = b.get("driver")
                if not d:
                    continue
                d["fatigue_stage"] = "WATCH"
                d["fatigue_lt"] = round(rng.uniform(2.0, 10.0), 1)
                d["fatigue_st"] = 0.0
                d["perclos"] = 0.0
                d["episode"] = None
                d["_prev_stage"] = "WATCH"
                d.pop("last_cabin_alert_min", None)
            self._ear_hist.clear()
        for bus in store.get_buses():
            if bus.get("_live"):
                continue
            self._tick_bus(bus, rng)
            if bus["bus_id"] in self._prone and now >= self._next_event.get(bus["bus_id"], 0):
                self._emit_event(bus, rng)
                self._next_event[bus["bus_id"]] = now + rng.uniform(150, 320)
        # predictive health tick (runs after all bus updates)
        tick_all(store.get_buses(), rng, DataSource.SIMULATION)
        # generate health events for alerts/incidents
        generate_health_events(DataSource.SIMULATION)

    # ------------------------------------------------------------ tick logic
    def _tick_bus(self, bus, rng):
        self._advance_stop(bus, rng)

        # driver state — temporal fatigue timeline + PERCLOS (see _tick_driver)
        d = bus["driver"]
        self._tick_driver(bus, rng)
        d = bus["driver"]

        bus["cabin_alert"] = {
            "sent": d["drowsy"] and d["state"] == "DROWSY",
            "type": "AUDIO_WARNING",
            "channel": "speakers",
            "message": "DRIVER ALERT - wake up",
        } if d["state"] in ("ATTENTION", "DROWSY") else None

        # energy drain / tyres
        self._tick_energy(bus, rng)
        self._tick_wheels(bus, rng)

        # rebuild load from current passengers (bounded within limits)
        occ = bus["occupancy"]
        bus["load"] = self._make_load(occ["passengers"] * 68)

        # vehicle health
        v = bus["vehicle"]
        if rng.random() < 0.015:
            v["health"] = rng.choice(HEALTH_STATES)
        v["anomaly"] = "none" if v["health"] == "NORMAL" else rng.choice(VEHICLE_ANOMALIES[1:])
        v["vibration"] = round(min(1.0, v["vibration"] + rng.uniform(-0.03, 0.03)), 3)
        if v["health"] == "INSPECTION REQUIRED":
            v["maintenance_priority"] = "HIGH"
        elif v["health"] == "WARNING":
            v["maintenance_priority"] = "MEDIUM"
        else:
            v["maintenance_priority"] = "LOW"

        bus["last_update"] = utcnow_iso()
        # transient tracking fields are computed fresh on the next tick
        bus["driver"].pop("_prev_stage", None)
        store.upsert_bus(bus)

    def _advance_stop(self, bus, rng):
        """Move the bus along its stop sequence. Pauses at each stop and lets a
        realistic number of passengers board on a ticket. Emits a stop log."""
        j = bus["journey"]
        current = j["stops"][j["current_index"]]

        if j["state"] == "AT_STOP":
            # Bus is standing at this stop.
            bus["speed_kmh"] = 0.0
            # A small, realistic boarding pulse. Not every stop visit boards,
            # and counts are small (1-4 normal, up to ~12 at major terminals).
            if not j.get("_boarded_flag") and rng.random() < 0.09:
                major = current.get("major", False)
                boarded = rng.randint(6, 10) if major else rng.randint(1, 3)
                current["boarded"] += boarded
                self._add_boardings(bus, boarded)
                j["boarded_here"] = boarded
                j["_boarded_flag"] = True
                bus["last_stop_update"] = {
                    "stop": current["stop"],
                    "action": "BOARDED",
                    "passengers": boarded,
                    "timestamp": utcnow_iso(),
                }
            else:
                j["boarded_here"] = 0

            # leave the stop after a short dwell
            if rng.random() < 0.08:
                if j["current_index"] >= j["total_stops"] - 1:
                    # reached destination -> start return (reset journey)
                    j["current_index"] = 0
                    j["next_index"] = 1
                    j["state"] = "MOVING"
                    j["progress"] = 0.0
                    j["_boarded_flag"] = False
                    j["boarded_here"] = 0
                    for s in j["stops"]:
                        s["boarded"] = 0
                    return
                j["state"] = "MOVING"
                j["progress"] = 0.0
                j["_boarded_flag"] = False
        elif j["state"] == "MOVING":
            # driving between stops — buses are always moving at a real speed
            j["progress"] += 0.02 + rng.uniform(0, 0.012)
            bus["speed_kmh"] = round(rng.uniform(24, 45), 1)
            if j["progress"] >= 0.5:
                j["state"] = "ARRIVING"
            else:
                self._interp(bus, j)
        elif j["state"] == "ARRIVING":
            # slowing down as it pulls into the stop
            j["progress"] += 0.024 + rng.uniform(0, 0.012)
            bus["speed_kmh"] = round(max(6.0, 34 - j["progress"] * 26), 1)
            if j["progress"] >= 1.0:
                j["state"] = "AT_STOP"
                j["current_index"] = j["next_index"]
                j["next_index"] = min(j["current_index"] + 1, j["total_stops"] - 1)
                j["_boarded_flag"] = False
                s = j["stops"][j["current_index"]]
                bus["latitude"] = s["lat"] + rng.uniform(-0.001, 0.001)
                bus["longitude"] = s["lon"] + rng.uniform(-0.001, 0.001)
                bus["speed_kmh"] = 0.0
            else:
                self._interp(bus, j)
        else:
            bus["speed_kmh"] = round(rng.uniform(20, 55), 1)

    def _interp(self, bus, j):
        """Move the bus along roads (a grid-aligned EW/NS street path) rather
        than a straight line, so it never cuts across buildings."""
        a = j["stops"][j["current_index"]]
        b = j["stops"][j["next_index"]]
        lat, lon = self._point_on_path(self._road_path(a, b),
                                       max(0.0, min(1.0, j["progress"])))
        bus["latitude"] = round(lat, 6)
        bus["longitude"] = round(lon, 6)

    _GRID = 0.0018   # ~200 m apparent street spacing

    def _snap(self, x):
        return round(x / self._GRID) * self._GRID

    def _road_path(self, a, b):
        """Build an axis-aligned, grid-snapped street path from stop a to b.

        Every segment is a pure east/west or north/south street run (like a
        city block grid), so the marker follows roads between the two stops.
        """
        a_lat, a_lon = a["lat"], a["lon"]
        b_lat, b_lon = b["lat"], b["lon"]
        pts = [(a_lat, a_lon)]
        prev_lat, prev_lon = a_lat, a_lon
        n = 4
        for i in range(1, n + 1):
            t = i / n
            cur_lat = self._snap(a_lat + (b_lat - a_lat) * t)
            cur_lon = self._snap(a_lon + (b_lon - a_lon) * t)
            if cur_lon != prev_lon:
                pts.append((prev_lat, cur_lon))   # EW run along a street
            if cur_lat != prev_lat:
                pts.append((cur_lat, cur_lon))     # NS run along a street
            prev_lat, prev_lon = cur_lat, cur_lon
        # pull into the destination stop (EW then NS)
        if b_lon != prev_lon:
            pts.append((prev_lat, b_lon))
        if b_lat != prev_lat:
            pts.append((b_lat, b_lon))
        out = [pts[0]]
        for p in pts[1:]:
            if p != out[-1]:
                out.append(p)
        return out

    def _point_on_path(self, pts, t):
        """Return a point at fraction t (0..1) along a polyline path."""
        if len(pts) == 1:
            return pts[0]
        segs = []
        total = 0.0
        for i in range(len(pts) - 1):
            d = hypot(pts[i][0] - pts[i + 1][0], pts[i][1] - pts[i + 1][1])
            segs.append(d)
            total += d
        if total <= 0:
            return pts[-1]
        target = t * total
        acc = 0.0
        for i, d in enumerate(segs):
            if acc + d >= target:
                if d <= 0:
                    return pts[i]
                f = (target - acc) / d
                return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f,
                        pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f)
            acc += d
        return pts[-1]

    def _add_boardings(self, bus, boarded):
        """Board n riders, update occupancy + ticket/fare counters (realistic
        small numbers, not hundreds per second)."""
        occ = bus["occupancy"]
        capacity = occ.get("capacity", 60)
        occ["passengers"] = max(0, min(capacity, occ["passengers"] + boarded))
        occ["pct"] = round(100 * occ["passengers"] / capacity)
        occ["crowd"] = CROWD_LEVELS[min(4, occ["pct"] // 25)]

        tkt = bus.get("ticketing") or self._fresh_ticketing(random.Random())
        fare = AVG_FARE
        tkt["tickets_today"] = (tkt.get("tickets_today", 0) or 0) + boarded
        tkt["passengers_total"] = (tkt.get("passengers_total", 0) or 0) + boarded
        tkt["fare_collected"] = round((tkt.get("fare_collected", 0) or 0) + boarded * fare, 2)
        tkt["avg_fare"] = AVG_FARE
        bus["ticketing"] = tkt

    def _tick_driver(self, bus, rng):
        """Temporal fatigue model for the demo driver.

        Cumulative (long-term) fatigue rises while the bus is driven and decays
        at rest; beyond thresholds the driver enters episodic drowsy episodes
        with escalating grades. A PERCLOS-style index is derived from a rolling
        window of EAR samples. All output is synthetic demo behaviour.
        """
        d = bus["driver"]
        prone = bus["bus_id"] in self._prone
        detection = store.get_settings().get("detection") or {}
        ear_th = float(detection.get("ear_threshold", 0.23))

        ep = d.get("episode") or {}
        in_episode = bool(ep.get("ticks_left", 0) > 0)

        # ---- cumulative fatigue (driving time since last rest) ----
        driving = (bus.get("journey") or {}).get("state") != "AT_STOP" or float(bus.get("speed_kmh", 0)) > 0
        if in_episode:
            # mid-episode load counts double
            d["fatigue_lt"] = min(100.0, float(d.get("fatigue_lt", 0.0)) + rng.uniform(0.5, 0.9))
        elif driving:
            # driving builds fatigue; prone drivers tire much faster
            rise = (0.45 + rng.uniform(0.0, 0.20)) if prone else (0.16 + rng.uniform(0.0, 0.12))
            d["fatigue_lt"] = min(100.0, float(d.get("fatigue_lt", 0.0)) + rise)
        else:
            # resting at a stop: fatigue fades (moreso at major terminals)
            decay = 0.6 + rng.uniform(0.0, 0.4)
            if (bus.get("journey") or {}).get("stops") and \
               (bus["journey"]["stops"][bus["journey"].get("current_index", 0)]).get("major"):
                decay *= 2.2   # driver gets a solid rest at a terminal
            if prone:
                decay *= 1.5
            d["fatigue_lt"] = max(0.0, float(d.get("fatigue_lt", 0.0)) - decay)

        # non-prone drivers rarely stay deep in fatigue: pull back above 40
        lt = float(d.get("fatigue_lt", 0.0))
        if not prone and lt > 40:
            d["fatigue_lt"] = max(40.0, lt - (lt - 40) * 0.08)

        # clear refresh flag when fatigue drops sufficiently (proper rest achieved)
        if d.get("needs_refresh") and lt < 40:
            d["needs_refresh"] = False

        # ---- fatigue stage from cumulative fatigue ----
        lt = float(d.get("fatigue_lt", 0.0))
        d["fatigue_stage"] = "CRITICAL" if lt >= 65 else ("ALERT" if lt >= 40 else "WATCH")

        # ---- emission on entering CRITICAL (once per escalation, not per episode) ----
        prev_stage = self._prev_stage.get(bus["bus_id"], "WATCH")
        if prone and d["fatigue_stage"] == "CRITICAL" and prev_stage != "CRITICAL":
            self._emit_drowsiness_event(bus)
        self._prev_stage[bus["bus_id"]] = d["fatigue_stage"]

        # ---- start a drowsy episode when the stage allows ----
        if not in_episode:
            chance = {"WATCH": 0.0, "ALERT": 0.04, "CRITICAL": 0.09}.get(d["fatigue_stage"], 0.0)
            if prone:
                chance *= 1.8
            if chance and rng.random() < chance:
                grade = (1 if rng.random() < 0.65 else 2) if d["fatigue_stage"] == "ALERT" else rng.choice([2, 3])
                ticks_total = rng.randint(4, 10) + grade
                d["episode"] = {
                    "grade": grade,
                    "ticks_left": ticks_total,
                    "ticks_total": ticks_total,
                    "emitted": False,
                    "started_sim_min": round(self.sim_minutes),
                    "stage_before": d["fatigue_stage"],
                }
                ep = d["episode"]
                in_episode = True
                # timeline entry for episode start
                timeline = d.setdefault("fatigue_timeline", [])
                timeline.append({
                    "ts": utcnow_iso(),
                    "type": "EPISODE_START",
                    "stage_before": d["fatigue_stage"],
                    "grade": grade,
                    "location": (bus.get("journey") or {}).get("stops", [{}])[
                        (bus.get("journey") or {}).get("current_index", 0)
                    ].get("stop", "en route"),
                })
                if len(timeline) > 20:
                    d["fatigue_timeline"] = timeline[-20:]

        if in_episode:
            grade = ep["grade"]
            ep["ticks_left"] -= 1
            if grade == 1:
                d["state"] = "ATTENTION"
                d["ear"] = round(rng.uniform(0.20, 0.24), 3)
                d["closed_sec"] = round(rng.uniform(0.3, 0.9), 2)
            elif grade == 2:
                d["state"] = "DROWSY" if rng.random() < 0.5 else "ATTENTION"
                d["ear"] = round(rng.uniform(0.15, 0.20), 3)
                d["closed_sec"] = round(rng.uniform(0.6, 1.4), 2)
            else:
                d["state"] = "DROWSY"
                d["ear"] = round(rng.uniform(0.10, 0.18), 3)
                d["closed_sec"] = round(rng.uniform(1.3, 3.8), 2)
                if not ep.get("emitted") and prone:
                    ep["emitted"] = True
                    # cabin audio warning, throttled so a long critical day
                    # does not spam the alert feed
                    last_alert = float(d.get("last_cabin_alert_min") or -999.0)
                    if self.sim_minutes - last_alert >= 25:
                        self._emit_cabin_alert(bus)
                        d["last_cabin_alert_min"] = float(self.sim_minutes)
            d["drowsy"] = d["state"] == "DROWSY"
            d["head_pitch_deg"] = round(rng.uniform(-12, 6), 1) if d["state"] == "DROWSY" else round(rng.uniform(-4, 3), 1)
            if ep["ticks_left"] <= 0:
                # episode ends: driver recovers
                recovered_at = utcnow_iso()
                d["recovered_at"] = recovered_at
                d["last_recovery_grade"] = ep["grade"]
                # emit recovery event
                store.add_event({
                    "bus_id": bus["bus_id"],
                    "reg_no": bus.get("reg_no"),
                    "event_type": "DRIVER_RECOVERED",
                    "latitude": round(bus["latitude"], 6),
                    "longitude": round(bus["longitude"], 6),
                    "severity": "INFO",
                    "confidence": 0.85,
                    "sensor_source": "driver_ai",
                    "status": "ACTIVE",
                    "simulation": True,
                    "additional_data": {
                        "note": f"Driver recovered from grade {ep['grade']} fatigue episode.",
                        "recovery_grade": ep["grade"],
                        "episode_duration_ticks": ep.get("ticks_total", ep["grade"] * 3 + 4),
                        "fatigue_lt_at_end": round(float(d.get("fatigue_lt", 0.0)), 1),
                        "perclos_at_end": d.get("perclos"),
                    },
                })
                # timeline entry
                timeline = d.setdefault("fatigue_timeline", [])
                timeline.append({
                    "ts": recovered_at,
                    "type": "RECOVERED",
                    "stage_before": ep.get("stage_before") or d.get("fatigue_stage"),
                    "grade": ep["grade"],
                    "duration_ticks": ep.get("ticks_total", ep["grade"] * 3 + 4),
                    "location": (bus.get("journey") or {}).get("stops", [{}])[
                        (bus.get("journey") or {}).get("current_index", 0)
                    ].get("stop", "en route"),
                })
                # keep last 20 timeline entries
                if len(timeline) > 20:
                    d["fatigue_timeline"] = timeline[-20:]
                # if cumulative fatigue still high after recovery, flag refresh needed
                if float(d.get("fatigue_lt", 0.0)) >= 55:
                    if not d.get("needs_refresh"):
                        d["needs_refresh"] = True
                        # emit refresh required event (once per escalation above threshold)
                        store.add_event({
                            "bus_id": bus["bus_id"],
                            "reg_no": bus.get("reg_no"),
                            "event_type": "DRIVER_REFRESH_REQUIRED",
                            "latitude": round(bus["latitude"], 6),
                            "longitude": round(bus["longitude"], 6),
                            "severity": "WARNING",
                            "confidence": 0.9,
                            "sensor_source": "driver_ai",
                            "status": "ACTIVE",
                            "simulation": True,
                            "additional_data": {
                                "note": "Long-term fatigue elevated; driver requires extended rest/refresh.",
                                "fatigue_lt": round(float(d.get("fatigue_lt", 0.0)), 1),
                                "fatigue_stage": d.get("fatigue_stage"),
                            },
                        })
                d["episode"] = None
        else:
            # alert-normal driving: baseline EAR with occasional blinks
            d["ear"] = round(min(0.42, max(0.27, float(d.get("ear", 0.30)) + rng.uniform(-0.01, 0.01))), 3)
            if rng.random() < 0.06:
                d["ear"] = round(max(0.15, d["ear"] - rng.uniform(0.05, 0.10)), 3)
            d["closed_sec"] = 0.0
            d["drowsy"] = False
            d["state"] = "NORMAL"
            d["head_pitch_deg"] = round(rng.uniform(-3, 3), 1)

        d["mar"] = round(rng.uniform(0.25, 0.65), 3)

        # ---- PERCLOS from a rolling window of EAR samples ----
        hist = self._ear_hist.setdefault(bus["bus_id"], deque(maxlen=30))
        hist.append((d["ear"], d["ear"] < ear_th))
        d["perclos"] = round(100.0 * sum(1 for _, closed in hist if closed) / len(hist), 1) if len(hist) >= 5 else 0.0

        # ---- short-term fatigue (recent drowsiness, 0-100) ----
        if d["state"] != "NORMAL":
            d["fatigue_st"] = min(100.0, float(d.get("fatigue_st", 0.0)) + 7 + rng.uniform(0, 8))
        else:
            d["fatigue_st"] = max(0.0, float(d.get("fatigue_st", 0.0)) - 5)

    def _emit_drowsiness_event(self, bus):
        store.add_event({
            "bus_id": bus["bus_id"],
            "reg_no": bus.get("reg_no"),
            "event_type": "DRIVER_DROWSINESS",
            "latitude": round(bus["latitude"], 6),
            "longitude": round(bus["longitude"], 6),
            "severity": "CRITICAL",
            "confidence": round(min(0.99, float(bus["driver"].get("perclos", 40.0)) / 40.0 + 0.4), 2),
            "sensor_source": "driver_ai",
            "status": "ACTIVE",
            "simulation": True,
            "additional_data": {
                "note": "Critical fatigue episode; drowsy driving via temporal fatigue + PERCLOS.",
                "perclos": bus["driver"].get("perclos"),
                "fatigue_lt": round(float(bus["driver"].get("fatigue_lt", 0.0)), 1),
                "fatigue_stage": bus["driver"].get("fatigue_stage"),
            },
        })

    def _tick_energy(self, bus, rng):
        e = bus.get("energy")
        drain = 0.04 if e["type"] == "EV" else 0.05
        e["percent"] = round(max(0.0, e.get("percent", 100) - drain * rng.uniform(0.5, 1.5)), 1)
        if e["type"] == "EV":
            e["kwh"] = round(max(0.0, e.get("kwh", 0) - 0.3 * rng.uniform(0.5, 1.5)), 1)
        else:
            e["litres"] = round(max(0.0, e.get("litres", 0) - 0.2 * rng.uniform(0.5, 1.5)), 1)

    def _tick_wheels(self, bus, rng):
        w = bus.get("wheels")
        if not w:
            return
        for i in range(len(w)):
            target = 85.0
            w[i] = round(min(95.0, max(60.0, w[i] + (target - w[i]) * 0.01 + rng.uniform(-0.6, 0.6))), 1)

    # ---------------------------------------------------------------- events
    def _emit_cabin_alert(self, bus):
        store.add_event({
            "bus_id": bus["bus_id"],
            "reg_no": bus.get("reg_no"),
            "event_type": "DRIVER_ALERT",
            "latitude": round(bus["latitude"], 6),
            "longitude": round(bus["longitude"], 6),
            "severity": "CRITICAL",
            "confidence": round(bus["driver"].get("ear", 0.3) * 3 + 0.4, 2),
            "sensor_source": "driver_ai",
            "status": "ACTIVE",
            "simulation": True,
            "additional_data": {
                "note": "Drowsiness detected; cabin audio warning issued (speakers).",
                "perclos": bus["driver"].get("perclos"),
                "fatigue_lt": round(float(bus["driver"].get("fatigue_lt", 0.0)), 1),
                "fatigue_stage": bus["driver"].get("fatigue_stage"),
                "cabin_action": {"type": "AUDIO_WARNING", "channel": "speakers",
                                 "message": "DRIVER ALERT - wake up"},
            },
        })

    def _emit_event(self, bus, rng):
        kind = rng.choice(EVENT_TYPES)
        severity = rng.choices(["CRITICAL", "WARNING", "INFO"], weights=[0.25, 0.45, 0.30])[0]
        event = {
            "bus_id": bus["bus_id"],
            "event_type": kind,
            "latitude": round(bus["latitude"], 6),
            "longitude": round(bus["longitude"], 6),
            "severity": severity,
            "confidence": round(rng.uniform(0.55, 0.97), 2),
            "sensor_source": self._source_for(kind),
            "status": "ACTIVE",
            "simulation": True,
            "additional_data": {"note": "Simulated demo event"},
        }
        store.add_event(event)

        if kind == "OVERLOAD":
            load = bus["load"]
            load["payload_kg"] = round(min(PAYLOAD_LIMIT_KG, load["payload_limit_kg"] * rng.uniform(0.95, 1.0)))
            load["gvw_kg"] = round(min(MAX_GVW_KG, TARE_KG + load["payload_kg"]))
            load["load_pct"] = round(100 * load["payload_kg"] / load["payload_limit_kg"])
            load["status"] = "HIGH LOAD" if load["load_pct"] > 90 else "NORMAL"

        if kind == "POTHOLE":
            key = f"{round(bus['latitude'], 3)}_{round(bus['longitude'], 3)}"
            now = utcnow_iso()
            image_ref = f"pothole-{bus['bus_id'].lower().replace(' ','-')}-{int(time.time())}.jpg"
            defect = store.get_road_defect(key)
            if defect is None:
                defect = {
                    "defect_id": key, "type": "pothole",
                    "latitude": round(bus["latitude"], 4), "longitude": round(bus["longitude"], 4),
                    "detection_count": 1, "confidence": round(rng.uniform(0.5, 0.95), 2),
                    "first_detected": now, "last_detected": now,
                    "buses": [bus["bus_id"]], "status": "ACTIVE",
                    "image": image_ref, "last_image": image_ref,
                }
            else:
                defect["detection_count"] += 1
                defect["confidence"] = round(min(0.99, defect["confidence"] + 0.05), 2)
                defect["last_detected"] = now
                defect["last_image"] = image_ref
                if bus["bus_id"] not in defect["buses"]:
                    defect["buses"].append(bus["bus_id"])
            store.upsert_road_defect(key, defect)

    @staticmethod
    def _source_for(kind):
        mapping = {
            "DRIVER_DROWSINESS": "driver_ai", "POTHOLE": "road_ai",
            "EMERGENCY_SIREN": "microphone", "OVERLOAD": "load_cell",
            "VEHICLE_ANOMALY": "vehicle_health", "CRASH": "imu",
            "CABIN_FIRE": "cabin_ai", "CABIN_SMOKE": "cabin_ai",
            "CABIN_INCIDENT": "cabin_ai", "DRIVER_ALERT": "driver_ai",
        }
        return mapping.get(kind, "unknown")


simulator = FleetSimulator()
