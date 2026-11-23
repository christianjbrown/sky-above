"""How often planes at a spot near home really came overhead.

A straight line or a learned path only says a plane could be on its way. Whether it is
depends on where it is: Heathrow's arrivals cross the same few kilometres level at 8,000 ft
every evening, pointing at home, and nearly all of them turn onto final before they get
there, while departures off one runway come over every time. So every plane that flies near
home is counted at each spot it passed through on the way in, a spot being a square of
ground, a band of height and a band of heading, along with whether it then came within the
zone. A plane at a spot where most earlier planes turned away is not believed (see
PoorOdds), however well its line or path lines up.

Two tallies are kept: one of the spots where a plane's straight line ran through the zone,
for the straight-line finder, and one of every spot planes flew through, for the learned
paths. Old counts fade by half every half_life, so a change of runway or route shows within
days, and a spot nothing has passed for kept is forgotten."""

import logging
import math
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.approach import KM_PER_DEGREE_LAT, KM_PER_DEGREE_LON_AT_EQUATOR
from flights_watcher.clock import Clock
from flights_watcher.geo import Location
from flights_watcher.paths import Fix, Flight

FULL_TURN_DEG = 360.0
HALF = 0.5


@dataclass(frozen=True)
class SpotSize:
    """How big a spot is: a square of ground km across, a band of height ft deep and a band
    of heading deg wide."""

    km: float
    ft: int
    deg: float


class SpotGrid:
    """Which spot a place, height and heading near centre falls in, named so that spots of
    another size never share a name."""

    def __init__(self, centre: Location, size: SpotSize) -> None:
        self._centre = centre
        self._size = size
        self._km_per_degree_lon = KM_PER_DEGREE_LON_AT_EQUATOR * math.cos(math.radians(centre.lat))

    def of(self, location: Location, altitude_ft: int, track_deg: float) -> str:
        east = (location.lon - self._centre.lon) * self._km_per_degree_lon
        north = (location.lat - self._centre.lat) * KM_PER_DEGREE_LAT
        size = self._size
        cells = (
            math.floor(east / size.km),
            math.floor(north / size.km),
            math.floor(altitude_ft / size.ft),
            math.floor((track_deg % FULL_TURN_DEG) / size.deg),
        )
        return f"{size.km:g}/{size.ft}/{size.deg:g}:" + ":".join(str(cell) for cell in cells)


@dataclass(frozen=True)
class Tally:
    """How many planes passed a spot, and how many of them came overhead."""

    seen: float
    came: float
    at: datetime


@dataclass(frozen=True)
class Odds:
    seen: float
    came: float

    @property
    def share(self) -> float:
        return self.came / self.seen if self.seen else 0.0


NO_ODDS = Odds(0.0, 0.0)


class SpotStore(Protocol):
    def load(self, since: datetime) -> dict[str, Tally]:
        """The tallies changed since then."""
        ...

    def save(self, tallies: Mapping[str, Tally]) -> None: ...


class SqliteSpotStore:
    """One tally in a table shared with the other, so a restart or a deploy forgets
    nothing. A broken database is logged and treated as empty, so it never stops the card."""

    def __init__(self, path: str, kind: str, logger: logging.Logger) -> None:
        self._path = path
        self._kind = kind
        self._logger = logger

    def load(self, since: datetime) -> dict[str, Tally]:
        try:
            with closing(self._connect()) as db, db:
                db.execute("DELETE FROM spots WHERE kind = ? AND at < ?", (self._kind, _utc(since)))
                rows = db.execute("SELECT spot, seen, came, at FROM spots WHERE kind = ?", (self._kind,)).fetchall()
        except sqlite3.Error as error:
            self._logger.warning("could not read the %s spots, starting again: %s", self._kind, error)
            return {}
        return {spot: Tally(seen, came, datetime.fromisoformat(at)) for spot, seen, came, at in rows}

    def save(self, tallies: Mapping[str, Tally]) -> None:
        try:
            with closing(self._connect()) as db, db:
                db.executemany(
                    "INSERT OR REPLACE INTO spots (kind, spot, seen, came, at) VALUES (?, ?, ?, ?, ?)",
                    [(self._kind, spot, t.seen, t.came, _utc(t.at)) for spot, t in tallies.items()],
                )
        except sqlite3.Error as error:
            self._logger.warning("could not keep the %s spots: %s", self._kind, error)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path)
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS spots ("
                "kind TEXT NOT NULL, spot TEXT NOT NULL, seen REAL NOT NULL, came REAL NOT NULL, at TEXT NOT NULL, "
                "PRIMARY KEY (kind, spot))"
            )
        except sqlite3.Error:
            db.close()
            raise
        return db


def _utc(moment: datetime) -> str:
    """Stored in UTC, so the times compare as text whatever the season."""
    return moment.astimezone(UTC).isoformat()


class SpotOdds(Protocol):
    def odds(self, plane: Aircraft) -> Odds:
        """How often planes where this one is now went on to come overhead."""
        ...


class LearnedSpots:
    """The tallies, kept in memory and written through to the store. Counts halve every
    half_life, and a spot untouched for kept is forgotten when the watcher starts."""

    def __init__(self, store: SpotStore, grid: SpotGrid, half_life: timedelta, kept: timedelta, clock: Clock) -> None:
        self._store = store
        self._grid = grid
        self._half_life = half_life
        self._clock = clock
        self._tallies = store.load(clock.now() - kept)

    def count(self, fixes: Iterable[Fix], came: bool) -> None:
        """One plane passed through these points, and came overhead or did not."""
        now = self._clock.now()
        changed = {}
        for spot in {self._grid.of(f.location, f.altitude_ft, f.track_deg) for f in fixes}:
            odds = self._faded(spot, now)
            changed[spot] = Tally(odds.seen + 1, odds.came + float(came), now)
        self._tallies.update(changed)
        if changed:
            self._store.save(changed)

    def odds(self, plane: Aircraft) -> Odds:
        if plane.location is None or plane.altitude_ft is None or plane.track_deg is None:
            return NO_ODDS
        return self._faded(self._grid.of(plane.location, plane.altitude_ft, plane.track_deg), self._clock.now())

    def _faded(self, spot: str, now: datetime) -> Odds:
        tally = self._tallies.get(spot)
        if tally is None:
            return NO_ODDS
        weight = HALF ** ((now - tally.at) / self._half_life)
        return Odds(tally.seen * weight, tally.came * weight)


class CountAimed:
    """Counts a plane at each spot where its straight line ran through the zone, before it
    was closest to home."""

    def __init__(self, spots: LearnedSpots, radius_km: float) -> None:
        self._spots = spots
        self._radius_km = radius_km

    def learn(self, hex_code: str, flight: Flight, learned_at: datetime) -> None:
        self._spots.count((fix for at, fix in flight.aimed if at < flight.closest_at), flight.closest_km <= self._radius_km)


class CountFlown:
    """Counts a plane at each spot it flew through on its way to its closest point."""

    def __init__(self, spots: LearnedSpots, radius_km: float) -> None:
        self._spots = spots
        self._radius_km = radius_km

    def learn(self, hex_code: str, flight: Flight, learned_at: datetime) -> None:
        self._spots.count((fix for at, fix in flight.fixes if at < flight.closest_at), flight.closest_km <= self._radius_km)


class PoorOdds:
    """A plane at a spot at least min_seen earlier planes passed, fewer than min_share of
    which came overhead. A spot too few have passed to tell says nothing either way."""

    def __init__(self, spots: SpotOdds, min_seen: float, min_share: float) -> None:
        self._spots = spots
        self._min_seen = min_seen
        self._min_share = min_share

    def excludes(self, plane: Aircraft, distance_km: float, seconds_to_closest: float) -> bool:
        odds = self._spots.odds(plane)
        return odds.seen >= self._min_seen and odds.share < self._min_share
