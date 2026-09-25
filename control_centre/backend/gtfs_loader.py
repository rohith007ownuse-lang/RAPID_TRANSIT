"""
gtfs_loader.py
Lightweight GTFS (General Transit Feed Specification) parser.

Reads a GTFS zip archive and provides structured access to:
  - agencies
  - routes
  - stops
  - trips
  - stop_times

No external dependencies — uses stdlib csv + zipfile.

Data source: https://github.com/ungalsoththu/ChennaiGTFS
License: ODbL (Open Database License)
"""

import csv
import io
import logging
import zipfile
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)


class GTFSLoader:
    """Parse a GTFS zip file and expose its contents as Python dicts/lists."""

    REQUIRED_FILES = {"agency.txt", "routes.txt", "stops.txt", "trips.txt", "stop_times.txt"}
    OPTIONAL_FILES = {"calendar.txt", "calendar_dates.txt", "shapes.txt", "feed_info.txt"}

    def __init__(self, zip_path: str):
        self.zip_path = Path(zip_path)
        self.agencies = []          # list of dicts
        self.routes = []            # list of dicts
        self.stops = []             # list of dicts
        self.trips = []             # list of dicts
        self.stop_times = []        # list of dicts
        self.shapes = {}            # shape_id -> list of {shape_pt_lat, shape_pt_lon, shape_pt_sequence}
        self.calendar = []          # list of dicts
        self.feed_info = {}

        # Indexes for fast lookup
        self._routes_by_id = {}     # route_id -> route dict
        self._stops_by_id = {}      # stop_id -> stop dict
        self._trips_by_id = {}      # trip_id -> trip dict
        self._trips_by_route = defaultdict(list)   # route_id -> [trip dicts]
        self._stop_times_by_trip = defaultdict(list)  # trip_id -> [stop_time dicts, sorted]
        self._routes_by_agency = defaultdict(list)  # agency_id -> [route dicts]

        self._loaded = False

    def load(self):
        """Load and index all GTFS files from the zip."""
        if self._loaded:
            return

        if not self.zip_path.exists():
            log.error("GTFS zip not found: %s", self.zip_path)
            return

        log.info("Loading GTFS from %s", self.zip_path)

        with zipfile.ZipFile(self.zip_path, "r") as zf:
            available = set(zf.namelist())

            missing = self.REQUIRED_FILES - available
            if missing:
                log.error("GTFS zip missing required files: %s", missing)
                return

            self.agencies = self._read_csv(zf, "agency.txt")
            self.routes = self._read_csv(zf, "routes.txt")
            self.stops = self._read_csv(zf, "stops.txt")
            self.trips = self._read_csv(zf, "trips.txt")
            self.stop_times = self._read_csv(zf, "stop_times.txt")

            if "calendar.txt" in available:
                self.calendar = self._read_csv(zf, "calendar.txt")
            if "shapes.txt" in available:
                self._load_shapes(zf)
            if "feed_info.txt" in available:
                info = self._read_csv(zf, "feed_info.txt")
                if info:
                    self.feed_info = info[0]

        self._build_indexes()
        self._loaded = True

        log.info(
            "GTFS loaded: %d agencies, %d routes, %d stops, %d trips, %d stop_times",
            len(self.agencies), len(self.routes), len(self.stops),
            len(self.trips), len(self.stop_times),
        )

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_route(self, route_id: str):
        return self._routes_by_id.get(route_id)

    def get_stop(self, stop_id: str):
        return self._stops_by_id.get(stop_id)

    def get_trip(self, trip_id: str):
        return self._trips_by_id.get(trip_id)

    def get_trips_for_route(self, route_id: str):
        return self._trips_by_route.get(route_id, [])

    def get_stop_times_for_trip(self, trip_id: str):
        return self._stop_times_by_trip.get(trip_id, [])

    def get_routes_for_agency(self, agency_id: str):
        return self._routes_by_agency.get(agency_id, [])

    def get_shape(self, shape_id: str):
        return self.shapes.get(shape_id, [])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _read_csv(zf: zipfile.ZipFile, filename: str):
        """Read a GTFS CSV file and return a list of dicts."""
        with zf.open(filename) as f:
            text = io.TextIOWrapper(f, encoding="utf-8-sig")
            reader = csv.DictReader(text)
            return [row for row in reader]

    def _load_shapes(self, zf: zipfile.ZipFile):
        """Load shapes.txt into a dict keyed by shape_id."""
        rows = self._read_csv(zf, "shapes.txt")
        for row in rows:
            sid = row.get("shape_id", "")
            if sid not in self.shapes:
                self.shapes[sid] = []
            try:
                self.shapes[sid].append({
                    "lat": float(row["shape_pt_lat"]),
                    "lon": float(row["shape_pt_lon"]),
                    "sequence": int(row["shape_pt_sequence"]),
                })
            except (ValueError, KeyError):
                continue

        # Sort each shape by sequence
        for sid in self.shapes:
            self.shapes[sid].sort(key=lambda p: p["sequence"])

        log.info("Loaded %d shapes", len(self.shapes))

    def _build_indexes(self):
        """Build lookup indexes for fast access."""
        for route in self.routes:
            rid = route.get("route_id", "")
            self._routes_by_id[rid] = route
            self._routes_by_agency[route.get("agency_id", "")].append(route)

        for stop in self.stops:
            self._stops_by_id[stop.get("stop_id", "")] = stop

        for trip in self.trips:
            tid = trip.get("trip_id", "")
            self._trips_by_id[tid] = trip
            self._trips_by_route[trip.get("route_id", "")].append(trip)

        # Stop times must be sorted by trip_id + stop_sequence for efficient access
        self.stop_times.sort(key=lambda st: (st.get("trip_id", ""), int(st.get("stop_sequence", 0))))

        for st in self.stop_times:
            self._stop_times_by_trip[st.get("trip_id", "")].append(st)

    def stats(self):
        """Return a summary dict of the loaded GTFS data."""
        return {
            "agencies": len(self.agencies),
            "routes": len(self.routes),
            "stops": len(self.stops),
            "trips": len(self.trips),
            "stop_times": len(self.stop_times),
            "shapes": len(self.shapes),
        }
