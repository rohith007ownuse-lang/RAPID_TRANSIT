"""
test_gtfs_memory.py
The GTFS timetable (1.36M stop_times rows) must exist in memory exactly ONCE
and must be released after init — a duplicated load once pushed total RSS past
1.4GB and OOM-killed the 1GB Railway trial deployment.

Covers: shared single load via _ensure_gtfs_loaded, shape-manager init from
the shared loader, release_bulk() freeing the tables, post-release accessors
returning [] instead of crashing, and the provider/shape manager still
answering from their precomputed structures.
"""

import simulator as sim_mod


def test_shared_load_release_cycle():
    sim_mod._ensure_gtfs_loaded()
    provider = sim_mod.mtc_provider
    assert provider is not None
    loader = provider._loader
    assert loader._loaded

    # Pre-release: the bulk tables are populated (compact tuples, never dicts).
    assert loader._stop_times_count > 1_000_000
    sample_trip = next(iter(loader._stop_times_by_trip))
    rows = loader.get_stop_times_for_trip(sample_trip)
    assert rows
    assert len(rows[0]) == 4  # (stop_id, sequence, arrival, departure)

    # Shape manager consumes the shared loader (no second GTFSLoader().load()).
    from gtfs_shape_interpolator import route_shape_manager
    route_shape_manager.initialize_from_gtfs(loader)
    assert len(route_shape_manager._route_stops) > 100

    # Provider answers from precomputed structures before release.
    route_id = next(iter(provider._route_stops))
    assert len(provider.get_route_stops(route_id)) > 0
    assert len(provider.get_route_polyline(route_id)) > 0

    # Release drops the bulk tables (no flat list exists at all anymore)...
    loader.release_bulk()
    assert not hasattr(loader, "stop_times")
    assert loader._stop_times_by_trip == {}

    # ...accessors degrade to [] instead of crashing...
    assert loader.get_stop_times_for_trip(sample_trip) == []
    assert provider.get_trip_sequence(sample_trip) == []
    assert provider.get_stop_times() == []

    # ...and everything precomputed keeps working.
    assert len(provider.get_route_stops(route_id)) > 0
    assert len(provider.get_route_polyline(route_id)) > 0
    assert len(route_shape_manager._route_stops) > 100
    assert provider.search("beach")["routes"] or provider.search("beach")["stops"]
