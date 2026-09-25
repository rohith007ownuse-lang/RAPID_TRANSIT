"""
mtc_transit_provider.py
MTC (Metropolitan Transport Corporation) transit data provider.

Wraps GTFSLoader to provide MTC-specific Chennai bus data in formats
needed by the simulator, API, and frontend.

Filters out CMRL metro, suburban rail, and any non-MTC agencies.
Only MTC bus data reaches the Rapid Transit map.

Data source: https://github.com/ungalsoththu/ChennaiGTFS (ODbL)
"""

import logging
import random
from collections import defaultdict
from pathlib import Path

from gtfs_loader import GTFSLoader

log = logging.getLogger(__name__)

# MTC agency_id in the ChennaiGTFS dataset
MTC_AGENCY_ID = "69"

# GTFS route_type 3 = Bus (we only want buses)
BUS_ROUTE_TYPE = "3"

# Default GTFS zip location
DEFAULT_GTFS_PATH = str(Path(__file__).parent / "data" / "mtc-gtfs.zip")


class MTCTransitProvider:
    """Provides MTC Chennai bus transit data from GTFS.

    Public API:
        get_routes()       -> list of route dicts
        get_stops()        -> list of stop dicts
        get_trips()        -> list of trip dicts
        get_stop_times()   -> list of stop_time dicts
        get_route_stops()  -> route_id -> ordered list of stops
        get_trip_sequence() -> trip_id -> ordered list of stops with timing

        to_simulator_routes() -> ROUTES format for FleetSimulator
        get_route_polyline()  -> route_id -> list of (lat, lon) for map display
    """

    def __init__(self, gtfs_path: str = None):
        self.gtfs_path = gtfs_path or DEFAULT_GTFS_PATH
        self._loader = GTFSLoader(self.gtfs_path)
        self._loaded = False

        # MTC-filtered data
        self._mtc_routes = []       # MTC bus routes only
        self._mtc_stops = {}        # stop_id -> stop dict (only stops used by MTC routes)
        self._mtc_trips = []        # MTC trips only
        self._route_stops = {}      # route_id -> ordered list of {stop_id, stop_name, lat, lon, sequence}
        self._stop_routes = defaultdict(list)  # stop_id -> list of route short_names serving it

        # Simulator-compatible format (cached)
        self._sim_routes = None

    def load(self):
        """Load GTFS data and filter to MTC buses only."""
        if self._loaded:
            return

        self._loader.load()
        if not self._loader._loaded:
            log.error("Failed to load GTFS data")
            return

        self._filter_mtc()
        self._loaded = True

        log.info(
            "MTC provider ready: %d routes, %d stops, %d trips",
            len(self._mtc_routes), len(self._mtc_stops), len(self._mtc_trips),
        )

    def _filter_mtc(self):
        """Filter GTFS data to MTC bus routes only."""
        # Filter routes: MTC agency + bus type
        for route in self._loader.routes:
            agency_id = route.get("agency_id", "")
            route_type = route.get("route_type", "")
            if agency_id == MTC_AGENCY_ID and route_type == BUS_ROUTE_TYPE:
                self._mtc_routes.append(route)

        log.info("Filtered %d MTC bus routes from %d total routes",
                 len(self._mtc_routes), len(self._loader.routes))

        # Collect all trip IDs for MTC routes
        mtc_route_ids = {r["route_id"] for r in self._mtc_routes}

        for trip in self._loader.trips:
            if trip.get("route_id") in mtc_route_ids:
                self._mtc_trips.append(trip)

        log.info("Found %d trips for MTC routes", len(self._mtc_trips))

        # Collect stop_ids used by MTC trips
        mtc_trip_ids = {t["trip_id"] for t in self._mtc_trips}

        for st in self._loader.stop_times:
            if st.get("trip_id") in mtc_trip_ids:
                stop_id = st.get("stop_id", "")
                if stop_id not in self._mtc_stops:
                    stop = self._loader.get_stop(stop_id)
                    if stop:
                        self._mtc_stops[stop_id] = stop

        log.info("Found %d unique stops for MTC trips", len(self._mtc_stops))

        # Build route -> stops mapping (using the longest trip per route as reference)
        self._build_route_stops()

        # Build stop -> routes mapping
        self._build_stop_routes()

    def _build_route_stops(self):
        """For each MTC route, find the best reference trip and extract its stop sequence."""
        # Group trips by route
        trips_by_route = defaultdict(list)
        for trip in self._mtc_trips:
            trips_by_route[trip["route_id"]].append(trip)

        for route in self._mtc_routes:
            route_id = route["route_id"]
            trips = trips_by_route.get(route_id, [])
            if not trips:
                continue

            # Pick the trip with the most stop_times as reference
            best_trip = None
            best_count = 0
            for trip in trips:
                stop_times = self._loader.get_stop_times_for_trip(trip["trip_id"])
                if len(stop_times) > best_count:
                    best_count = len(stop_times)
                    best_trip = trip

            if not best_trip or best_count == 0:
                continue

            stop_times = self._loader.get_stop_times_for_trip(best_trip["trip_id"])
            route_stops = []
            for st in stop_times:
                stop_id = st.get("stop_id", "")
                stop = self._mtc_stops.get(stop_id) or self._loader.get_stop(stop_id)
                if stop:
                    try:
                        route_stops.append({
                            "stop_id": stop_id,
                            "stop_name": stop.get("stop_name", ""),
                            "lat": float(stop.get("stop_lat", 0)),
                            "lon": float(stop.get("stop_lon", 0)),
                            "sequence": int(st.get("stop_sequence", 0)),
                            "arrival_time": st.get("arrival_time", ""),
                            "departure_time": st.get("departure_time", ""),
                        })
                    except (ValueError, KeyError):
                        continue

            route_stops.sort(key=lambda s: s["sequence"])
            self._route_stops[route_id] = route_stops

        log.info("Built stop sequences for %d routes", len(self._route_stops))

    def _build_stop_routes(self):
        """Map each stop to the routes that serve it."""
        for route in self._mtc_routes:
            route_id = route["route_id"]
            short_name = route.get("route_short_name", route_id)
            stops = self._route_stops.get(route_id, [])
            for stop in stops:
                self._stop_routes[stop["stop_id"]].append(short_name)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_routes(self):
        """Return all MTC bus routes."""
        return self._mtc_routes

    def get_stops(self):
        """Return all MTC bus stops."""
        return list(self._mtc_stops.values())

    def get_trips(self):
        """Return all MTC trips."""
        return self._mtc_trips

    def get_stop_times(self):
        """Return all stop_times for MTC trips."""
        return self._loader.stop_times

    def get_route_stops(self, route_id: str):
        """Return ordered list of stops for a route."""
        return self._route_stops.get(route_id, [])

    def get_trip_sequence(self, trip_id: str):
        """Return ordered stop sequence for a trip."""
        return self._loader.get_stop_times_for_trip(trip_id)

    def get_stop_info(self, stop_id: str):
        """Return stop details."""
        return self._mtc_stops.get(stop_id)

    def get_routes_serving_stop(self, stop_id: str):
        """Return list of route short_names serving a stop."""
        return self._stop_routes.get(stop_id, [])

    def get_route_polyline(self, route_id: str):
        """Return list of (lat, lon) tuples for rendering a route on the map.

        Uses stop-to-stop interpolation (no shapes.txt in this dataset).
        """
        stops = self._route_stops.get(route_id, [])
        return [(s["lat"], s["lon"]) for s in stops]

    def search(self, query: str):
        """Search routes and stops by name/ID. Returns dict with 'routes' and 'stops'."""
        q = query.strip().lower()
        if not q:
            return {"routes": [], "stops": []}

        matched_routes = []
        for route in self._mtc_routes:
            short = route.get("route_short_name", "").lower()
            long = route.get("route_long_name", "").lower()
            rid = route.get("route_id", "").lower()
            if q in short or q in long or q in rid:
                matched_routes.append({
                    "route_id": route["route_id"],
                    "route_short_name": route.get("route_short_name", ""),
                    "route_long_name": route.get("route_long_name", ""),
                })

        matched_stops = []
        for stop in self._mtc_stops.values():
            name = stop.get("stop_name", "").lower()
            sid = stop.get("stop_id", "").lower()
            if q in name or q in sid:
                matched_stops.append({
                    "stop_id": stop["stop_id"],
                    "stop_name": stop.get("stop_name", ""),
                    "lat": float(stop.get("stop_lat", 0)),
                    "lon": float(stop.get("stop_lon", 0)),
                    "routes": self.get_routes_serving_stop(stop["stop_id"]),
                })

        return {"routes": matched_routes[:20], "stops": matched_stops[:20]}

    # ------------------------------------------------------------------
    # Simulator integration
    # ------------------------------------------------------------------

    def to_simulator_routes(self, max_routes=None):
        """Convert MTC GTFS data to the ROUTES format expected by FleetSimulator.

        Returns list of dicts:
            {"code": "29A", "name": "29A - Anna Square to Perambur", "stops": [...], "ev": False}

        The 'stops' list matches the simulator's expected format:
            {"stop": name, "lat": float, "lon": float, "major": bool}
        """
        if self._sim_routes is not None and max_routes is None:
            return self._sim_routes

        sim_routes = []
        for route in self._mtc_routes:
            route_id = route["route_id"]
            short_name = route.get("route_short_name", route_id)
            long_name = route.get("route_long_name", short_name)
            stops = self._route_stops.get(route_id, [])

            if len(stops) < 2:
                continue  # Skip routes with fewer than 2 stops

            sim_stops = []
            for i, s in enumerate(stops):
                # First and last stops are "major" (terminals)
                # Stops with arrival_time indicating a longer dwell are also major
                is_terminal = (i == 0 or i == len(stops) - 1)
                sim_stops.append({
                    "stop": s["stop_name"],
                    "lat": s["lat"],
                    "lon": s["lon"],
                    "major": is_terminal,
                })

            sim_routes.append({
                "code": short_name,
                "name": f"{short_name} - {long_name}",
                "stops": sim_stops,
                "ev": False,  # GTFS doesn't distinguish EV/diesel; default to diesel
                "route_id": route_id,  # Keep GTFS route_id for reference
            })

            if max_routes and len(sim_routes) >= max_routes:
                break

        if max_routes is None:
            self._sim_routes = sim_routes

        log.info("Generated %d simulator routes from GTFS", len(sim_routes))
        return sim_routes

    def summary(self):
        """Return a summary dict for the API."""
        return {
            "source": "GTFS",
            "source_url": "https://github.com/ungalsoththu/ChennaiGTFS",
            "license": "ODbL",
            "agency": "MTC (Metropolitan Transport Corporation)",
            "routes": len(self._mtc_routes),
            "stops": len(self._mtc_stops),
            "trips": len(self._mtc_trips),
            "scope": "MTC buses only (CMRL metro and suburban rail excluded)",
            "data_type": "Static GTFS (schedule, not real-time)",
            "shapes_available": len(self._loader.shapes) > 0,
            "limitations": [
                "Straight-line route shapes (no OSM road matching yet)",
                "Static schedule data (no real-time GPS)",
                "Simulated bus movement based on GTFS stop sequences",
            ],
        }
