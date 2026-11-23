import itertools
import json
import logging
import math
import pathlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone

from fakes import HOME, FakeClock
from fakes import plane as fake_plane
from flights_watcher.approach import ApproachFinder, ClosestApproach
from flights_watcher.geo import Location
from flights_watcher.paths import Fix, Flight, PathRecorder
from flights_watcher.spots import (
    CountAimed,
    CountFlown,
    LearnedSpots,
    Odds,
    PoorOdds,
    SpotGrid,
    SpotSize,
    SqliteSpotStore,
    Tally,
)

KM_PER_DEGREE_LON = 111.32 * math.cos(math.radians(HOME.lat))
LOGGER = logging.getLogger("test")
SIZE = SpotSize(km=2, ft=1000, deg=20)
RADIUS_KM = 2.0
TRACKS = json.loads((pathlib.Path(__file__).parent / "tracks" / "one_spot_most_turn_away.json").read_text())["planes"]


def at(east_km: float, north_km: float = 0.0) -> Location:
    return Location(HOME.lat + north_km / 110.574, HOME.lon + east_km / KM_PER_DEGREE_LON)


def fix(east_km: float, north_km: float = 0.0, altitude_ft: int = 8000, track_deg: float = 270.0) -> Fix:
    return Fix(at(east_km, north_km), altitude_ft, track_deg, 0.0)


class MemorySpots:
    def __init__(self, tallies: dict[str, Tally] | None = None) -> None:
        self.tallies = dict(tallies or {})
        self.since: datetime | None = None

    def load(self, since: datetime) -> dict[str, Tally]:
        self.since = since
        return dict(self.tallies)

    def save(self, tallies) -> None:
        self.tallies.update(tallies)


def learned(store: MemorySpots | None = None, clock: FakeClock | None = None) -> LearnedSpots:
    return LearnedSpots(store or MemorySpots(), SpotGrid(HOME, SIZE), timedelta(days=14), timedelta(days=60), clock or FakeClock())


def logged(index: int) -> list:
    """One logged plane, a look a second as the watcher has them, flying straight between
    the points it was heard at."""
    points = TRACKS[index]["points"]
    looks = []
    for (start, east0, north0, *_), (end, east1, north1, feet, track, knots) in itertools.pairwise(points):
        for second in range(end - start):
            share = second / (end - start)
            where = at(east0 + (east1 - east0) * share, north0 + (north1 - north0) * share)
            looks.append(
                fake_plane(f"logged{index}", lat=where.lat, lon=where.lon, altitude_ft=feet, track_deg=track, ground_speed_kt=knots)
            )
    return looks


def replay(recorder: PathRecorder, clock: FakeClock, indices) -> None:
    for index in indices:
        for look in logged(index):
            recorder.observe([look])
            clock.seconds += 1
        clock.seconds += 120
        recorder.observe([])


def finder(spots: LearnedSpots) -> ApproachFinder:
    """The straight-line finder as the watcher runs it, except that with only seven planes to
    learn from, two at a spot are enough to go on, where the watcher waits for aimed_min_seen."""
    return ApproachFinder(ClosestApproach(HOME, 60), HOME, RADIUS_KM, 5, 2, 3, 0.3, [PoorOdds(spots, 2, 0.5)])


def called(spots: LearnedSpots, index: int) -> bool:
    approaching = finder(spots)
    return any(approaching.sightings([look]) for look in logged(index))


def test_the_logged_planes_are_mostly_ones_that_turned_away():
    assert [p["came"] for p in TRACKS].count(True) == 1 and len(TRACKS) == 8


def test_a_plane_where_most_earlier_planes_turned_away_is_not_called_though_its_line_runs_through_the_zone():
    clock = FakeClock()
    aimed = learned(clock=clock)
    recorder = PathRecorder([CountAimed(aimed, RADIUS_KM)], ClosestApproach(HOME, 60), HOME, RADIUS_KM, 25, 2, 60, clock)
    last_miss = len(TRACKS) - 1
    assert called(aimed, last_miss)
    replay(recorder, clock, range(last_miss))
    assert not called(aimed, last_miss)


def test_the_plane_that_came_over_is_still_called_at_a_spot_nothing_has_taught_anything():
    came = next(i for i, p in enumerate(TRACKS) if p["came"])
    assert called(learned(), came)


def test_a_spot_is_named_by_its_square_height_heading_and_size():
    grid = SpotGrid(HOME, SIZE)
    assert grid.of(at(3.1, -0.5), 8400, 265.0) == "2/1000/20:1:-1:8:13"
    assert grid.of(at(3.1, -0.5), 8400, 625.0) == grid.of(at(3.9, -1.9), 8999, 260.0)
    assert SpotGrid(HOME, SpotSize(km=1.5, ft=1000, deg=20)).of(at(3.1, -0.5), 8400, 265.0).startswith("1.5/1000/20:")


def test_each_spot_counts_a_plane_once_and_whether_it_came():
    spots = learned()
    spots.count([fix(10), fix(10.5), fix(6)], came=False)
    spots.count([fix(10.2)], came=True)
    assert spots.odds(fake_plane(lat=at(10.9).lat, lon=at(10.9).lon, altitude_ft=8000)) == Odds(2.0, 1.0)
    assert spots.odds(fake_plane(lat=at(6).lat, lon=at(6).lon, altitude_ft=8000)) == Odds(1.0, 0.0)


def test_counts_fade_by_half_every_half_life_and_are_kept():
    clock = FakeClock()
    store = MemorySpots()
    spots = learned(store, clock)
    spots.count([fix(10)], came=True)
    spots.count([fix(10)], came=False)
    clock.at += timedelta(days=14)
    assert spots.odds(fake_plane(lat=at(10).lat, lon=at(10).lon, altitude_ft=8000)) == Odds(1.0, 0.5)
    spots.count([fix(10)], came=False)
    assert list(store.tallies.values()) == [Tally(2.0, 0.5, clock.at)]


def test_no_points_change_nothing():
    store = MemorySpots()
    learned(store).count([], came=True)
    assert store.tallies == {}


def test_spots_untouched_for_too_long_are_not_loaded():
    store = MemorySpots()
    learned(store)
    assert store.since == FakeClock().now() - timedelta(days=60)


def test_a_plane_with_no_position_height_or_heading_has_no_odds():
    spots = learned()
    spots.count([fix(0)], came=True)
    assert spots.odds(fake_plane(location=None)) == Odds(0.0, 0.0)
    assert spots.odds(fake_plane(altitude_ft=None)) == Odds(0.0, 0.0)
    assert spots.odds(fake_plane(track_deg=None)) == Odds(0.0, 0.0)
    assert Odds(0.0, 0.0).share == 0.0


def test_a_spot_too_few_planes_passed_is_taken_on_trust():
    class Fixed:
        def __init__(self, odds: Odds) -> None:
            self._odds = odds

        def odds(self, plane) -> Odds:
            return self._odds

    rule = PoorOdds
    assert not rule(Fixed(Odds(2.0, 0.0)), 3, 0.5).excludes(fake_plane(), 10, 60)
    assert rule(Fixed(Odds(4.0, 1.0)), 3, 0.5).excludes(fake_plane(), 10, 60)
    assert not rule(Fixed(Odds(4.0, 2.0)), 3, 0.5).excludes(fake_plane(), 10, 60)


def flight_through(aimed_east: list[float], flown_east: list[float], closest_km: float) -> Flight:
    flight = Flight(fake_plane(), 0.0)
    flight.fixes = [(float(i), fix(east)) for i, east in enumerate(flown_east)]
    flight.aimed = [(float(i), fix(east)) for i, east in enumerate(aimed_east)]
    flight.closest_km, flight.closest_at = closest_km, 2.0
    return flight


def test_only_the_points_before_the_plane_was_closest_are_counted():
    clock = FakeClock()
    aimed, flown = learned(clock=clock), learned(clock=clock)
    flight = flight_through([10, 8, 4], [12, 10, 8, -4], 1.0)
    CountAimed(aimed, RADIUS_KM).learn("x", flight, clock.now())
    CountFlown(flown, RADIUS_KM).learn("x", flight, clock.now())

    def odds(spots: LearnedSpots, east_km: float) -> Odds:
        return spots.odds(fake_plane(lat=at(east_km).lat, lon=at(east_km).lon, altitude_ft=8000))

    assert odds(aimed, 10) == Odds(1.0, 1.0) and odds(aimed, 4) == Odds(0.0, 0.0)
    assert odds(flown, 12) == Odds(1.0, 1.0) and odds(flown, -4) == Odds(0.0, 0.0)
    CountFlown(flown, RADIUS_KM).learn("y", flight_through([], [12], 3.0), clock.now())
    assert odds(flown, 12) == Odds(2.0, 1.0)


def test_the_tallies_are_kept_in_sqlite_by_kind(tmp_path):
    path = str(tmp_path / "spots.sqlite3")
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone(timedelta(hours=1)))
    aimed, flown = SqliteSpotStore(path, "aimed", LOGGER), SqliteSpotStore(path, "flown", LOGGER)
    aimed.save({"a": Tally(3.0, 1.0, now), "old": Tally(1.0, 0.0, now - timedelta(days=90))})
    flown.save({"a": Tally(5.0, 5.0, now)})
    assert aimed.load(now - timedelta(days=60)) == {"a": Tally(3.0, 1.0, now)}
    assert aimed.load(now - timedelta(days=200)) == {"a": Tally(3.0, 1.0, now)}
    assert flown.load(now - timedelta(days=60)) == {"a": Tally(5.0, 5.0, now)}
    assert flown.load(now)["a"].at.tzinfo == UTC


def test_a_broken_database_is_logged_and_treated_as_empty(tmp_path, caplog):
    path = tmp_path / "spots.sqlite3"
    path.write_text("not a database")
    store = SqliteSpotStore(str(path), "aimed", LOGGER)
    assert store.load(datetime(2026, 11, 1, tzinfo=UTC)) == {}
    store.save({"a": Tally(1.0, 0.0, datetime(2026, 11, 1, tzinfo=UTC))})
    assert "could not read the aimed spots" in caplog.text and "could not keep the aimed spots" in caplog.text


def test_a_database_whose_table_cannot_be_made_is_closed_and_logged(tmp_path, caplog):
    path = tmp_path / "spots.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE VIEW spots AS SELECT 1")
    assert SqliteSpotStore(str(path), "aimed", LOGGER).load(datetime(2026, 11, 1, tzinfo=UTC)) == {}
    assert "could not read the aimed spots" in caplog.text
