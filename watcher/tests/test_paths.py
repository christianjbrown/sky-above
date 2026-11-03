import logging
import math
from datetime import timedelta

import pytest

from fakes import HOME, FakeClock
from fakes import plane as fake_plane
from flights_watcher.geo import Location
from flights_watcher.paths import (
    FirstFound,
    Fix,
    JsonPathStore,
    LearnedPath,
    LearnedPaths,
    Likeness,
    Observing,
    PathFinder,
    PathRecorder,
)
from flights_watcher.zone import Sighting

KM_PER_DEGREE_LON = 111.32 * math.cos(math.radians(HOME.lat))
LIKENESS = Likeness(within_km=0.5, within_ft=1500, within_deg=15)
LOGGER = logging.getLogger("test")


def at(east_km: float, north_km: float = 0.0) -> Location:
    return Location(HOME.lat + north_km / 110.574, HOME.lon + east_km / KM_PER_DEGREE_LON)


def plane(hex_code: str, where: Location, **fields):
    return fake_plane(hex_code, lat=where.lat, lon=where.lon, **{"altitude_ft": 4000, "vertical_rate_fpm": 1500, **fields})


class MemoryStore:
    def __init__(self, paths=()) -> None:
        self.paths = list(paths)

    def load(self):
        return list(self.paths)

    def save(self, paths) -> None:
        self.paths = list(paths)


def departure(hex_code: str) -> LearnedPath:
    """Climbing out 8 km east of home heading north, then turning west to pass overhead."""
    return LearnedPath(
        hex_code,
        FakeClock().now(),
        (
            Fix(at(8, -4), 3000, 0.0, 70.0),
            Fix(at(8, 0), 3500, 300.0, 50.0),
            Fix(at(4, 0), 4000, 270.0, 30.0),
        ),
    )


def learned(*paths: LearnedPath, clock: FakeClock | None = None) -> LearnedPaths:
    return LearnedPaths(MemoryStore(paths), LIKENESS, 60, timedelta(days=90), clock or FakeClock())


def test_a_plane_turning_onto_a_route_two_earlier_planes_flew_overhead_is_on_its_way():
    finder = PathFinder(learned(departure("one"), departure("two")), HOME, 1.0, 2, 3)
    turning = plane("new", at(8.1, -0.1), track_deg=310.0, altitude_ft=3400)
    assert not finder.sightings([turning])
    assert not finder.sightings([turning])
    [found] = finder.sightings([turning])
    assert found.aircraft.hex == "new" and found.approaching
    assert found.overhead_in_seconds == 50.0


def test_one_earlier_plane_is_not_enough_to_trust_a_route():
    finder = PathFinder(learned(departure("one")), HOME, 1.0, 2, 1)
    assert not finder.sightings([plane("new", at(8, 0), track_deg=300.0, altitude_ft=3500)])


def test_the_other_runway_or_a_plane_far_higher_is_not_on_the_route():
    finder = PathFinder(learned(departure("one"), departure("two")), HOME, 1.0, 2, 1)
    other_way = plane("other", at(8, 0), track_deg=120.0, altitude_ft=3500)
    high = plane("high", at(8, 0), track_deg=300.0, altitude_ft=12000)
    elsewhere = plane("elsewhere", at(8, 3), track_deg=300.0, altitude_ft=3500)
    assert not finder.sightings([other_way, high, elsewhere])


def test_a_plane_on_its_way_is_dropped_once_it_leaves_the_route():
    finder = PathFinder(learned(departure("one"), departure("two")), HOME, 1.0, 2, 1)
    assert finder.sightings([plane("new", at(8, 0), track_deg=300.0, altitude_ft=3500)])
    assert finder.sightings([plane("new", at(4, 0), track_deg=270.0, altitude_ft=4000)])
    assert not finder.sightings([plane("new", at(4, 2), track_deg=0.0, altitude_ft=4500)])


def test_a_plane_inside_the_zone_is_left_to_the_zone():
    finder = PathFinder(learned(departure("one"), departure("two")), HOME, 5.0, 2, 1)
    assert not finder.sightings([plane("new", at(4, 0), track_deg=270.0, altitude_ft=4000)])


def test_the_path_of_a_plane_that_came_overhead_is_learned_once_it_has_gone():
    clock = FakeClock()
    store = MemoryStore()
    recorder = PathRecorder(LearnedPaths(store, LIKENESS, 60, timedelta(days=90), clock), HOME, 1.0, 25, 2, 60, clock, LOGGER)
    for east_km in range(10, -4, -1):
        recorder.observe([plane("passing", at(east_km), track_deg=270.0)])
        clock.seconds += 4
    [path] = store.paths
    assert path.hex == "passing"
    assert [f.seconds_to_closest for f in path.fixes][:2] == [40.0, 36.0]
    assert path.fixes[-1].seconds_to_closest == 4.0


def test_a_plane_that_never_came_within_the_zone_teaches_nothing():
    clock = FakeClock()
    store = MemoryStore()
    recorder = PathRecorder(LearnedPaths(store, LIKENESS, 60, timedelta(days=90), clock), HOME, 1.0, 25, 2, 60, clock, LOGGER)
    for east_km in range(10, -4, -1):
        recorder.observe([plane("wide", at(east_km, 3), track_deg=270.0)])
        clock.seconds += 4
    assert not store.paths


def test_a_plane_that_vanishes_after_coming_overhead_is_learned_too():
    clock = FakeClock()
    store = MemoryStore()
    recorder = PathRecorder(LearnedPaths(store, LIKENESS, 60, timedelta(days=90), clock), HOME, 1.0, 25, 2, 60, clock, LOGGER)
    for east_km in (3, 2, 1, 0.2):
        recorder.observe([plane("lost", at(east_km), track_deg=270.0)])
        clock.seconds += 4
    clock.seconds += 61
    recorder.observe([])
    assert [p.hex for p in store.paths] == ["lost"]


def test_only_the_most_recent_paths_are_kept_and_old_ones_are_forgotten():
    clock = FakeClock()
    old = LearnedPath("old", clock.now() - timedelta(days=100), departure("old").fixes)
    store = MemoryStore([old, departure("a"), departure("b")])
    paths = LearnedPaths(store, LIKENESS, 2, timedelta(days=90), clock)
    paths.add(departure("c"))
    assert [p.hex for p in store.paths] == ["b", "c"]


def test_learned_paths_survive_a_restart(tmp_path):
    store = JsonPathStore(tmp_path / "paths.json", LOGGER)
    store.save([departure("one")])
    [path] = JsonPathStore(tmp_path / "paths.json", LOGGER).load()
    assert (path.hex, path.learned_at) == ("one", departure("one").learned_at)
    points = [(f.location.lat, f.location.lon, f.altitude_ft, f.track_deg, f.seconds_to_closest) for f in path.fixes]
    expected = [(f.location.lat, f.location.lon, f.altitude_ft, f.track_deg, f.seconds_to_closest) for f in departure("one").fixes]
    assert points == [pytest.approx(p, abs=1e-4) for p in expected]


def test_a_broken_paths_file_starts_again(tmp_path):
    (tmp_path / "paths.json").write_text("{not json")
    assert JsonPathStore(tmp_path / "paths.json", LOGGER).load() == []
    assert JsonPathStore(tmp_path / "missing.json", LOGGER).load() == []


class Fixed:
    def __init__(self, *sightings: Sighting) -> None:
        self._sightings = list(sightings)
        self.seen: list = []

    def sightings(self, aircraft):
        self.seen = list(aircraft)
        return self._sightings

    def observe(self, aircraft) -> None:
        self.seen = list(aircraft)


def test_first_found_keeps_the_first_finders_sighting_of_a_plane_and_orders_by_time():
    a = plane("a", at(5))
    b = plane("b", at(6))
    straight = Fixed(Sighting(a, 5.0, 40.0, approaching=True))
    learned_route = Fixed(Sighting(a, 5.0, 30.0, approaching=True), Sighting(b, 6.0, 20.0, approaching=True))
    found = FirstFound([straight, learned_route]).sightings([a, b])
    assert [(s.aircraft.hex, s.overhead_in_seconds) for s in found] == [("b", 20.0), ("a", 40.0)]


def test_observing_shows_the_observer_every_plane_before_finding():
    observer, finder = Fixed(), Fixed()
    a = plane("a", at(5))
    Observing(observer, finder).sightings(iter([a]))
    assert observer.seen == [a] and finder.seen == [a]


def test_a_plane_missing_its_height_or_heading_is_on_no_path():
    assert not LIKENESS.matches(plane("new", at(8, 0), track_deg=None), departure("one").fixes[1])


def test_a_paths_file_that_cannot_be_written_is_logged_and_the_paths_kept_in_memory(tmp_path, caplog):
    store = JsonPathStore(tmp_path / "missing-folder" / "paths.json", LOGGER)
    with caplog.at_level(logging.WARNING, logger="test"):
        store.save([departure("one")])
    assert "could not keep the learned paths" in caplog.text


def test_only_planes_in_the_air_with_a_position_within_reach_are_recorded():
    clock = FakeClock()
    store = MemoryStore()
    recorder = PathRecorder(LearnedPaths(store, LIKENESS, 60, timedelta(days=90), clock), HOME, 1.0, 25, 2, 60, clock, LOGGER)
    for east_km in range(3, -4, -1):
        recorder.observe(
            [
                plane("parked", at(east_km), on_ground=True),
                plane("far", at(east_km + 40), track_deg=270.0),
                plane("unplaced", at(east_km), location=None),
                plane("dawdling", at(0.5 + abs(east_km) / 10), track_deg=270.0),
            ]
        )
        clock.seconds += 4
    clock.seconds += 61
    recorder.observe([])
    assert [p.hex for p in store.paths] == ["dawdling"]


def test_a_plane_with_no_position_is_not_on_its_way():
    finder = PathFinder(learned(departure("one"), departure("two")), HOME, 1.0, 2, 1)
    assert not finder.sightings([plane("new", at(8, 0), location=None, track_deg=300.0)])


def test_a_plane_seen_more_often_than_every_couple_of_seconds_keeps_one_point_per_couple():
    clock = FakeClock()
    store = MemoryStore()
    recorder = PathRecorder(LearnedPaths(store, LIKENESS, 60, timedelta(days=90), clock), HOME, 1.0, 25, 2, 60, clock, LOGGER)
    for east_km in (3, 2.5, 2, 1.5, 1, 0.5, 0, -1, -2, -3):
        recorder.observe([plane("often", at(east_km), track_deg=270.0)])
        clock.seconds += 1
    [path] = store.paths
    assert len(path.fixes) == 3
