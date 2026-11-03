"""Routes learned from the planes that really came overhead.

A plane climbing out of a nearby airport turns onto its departure route a minute or so
before it reaches home, and until the turn is done its straight line points somewhere
else. But planes off the same runway fly the same route, so once two earlier planes have
come overhead along it, a new one at the same spot, height and heading is on its way too,
turn and all. Each runway, and each direction the airport is working in, is a route of its
own, learned separately, and a plane on a route that has never brought anything overhead
matches nothing."""

import json
import logging
import math
import pathlib
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.approach import SightingFinder
from flights_watcher.clock import Clock
from flights_watcher.geo import Location
from flights_watcher.zone import Sighting


@dataclass(frozen=True)
class Fix:
    """One point on a learned path, and how long the plane flying it took from there to its closest point."""

    location: Location
    altitude_ft: int
    track_deg: float
    seconds_to_closest: float


@dataclass(frozen=True)
class LearnedPath:
    hex: str
    learned_at: datetime
    fixes: tuple[Fix, ...]


@dataclass(frozen=True)
class Likeness:
    """How near a plane has to be to a point on a path, in place, height and heading, to be on it."""

    within_km: float
    within_ft: int
    within_deg: float

    def matches(self, plane: Aircraft, fix: Fix) -> bool:
        if plane.location is None or plane.altitude_ft is None or plane.track_deg is None:
            return False
        if abs(plane.altitude_ft - fix.altitude_ft) > self.within_ft:
            return False
        if abs((plane.track_deg - fix.track_deg + 180) % 360 - 180) > self.within_deg:
            return False
        return plane.location.distance_km(fix.location) <= self.within_km


class PathStore(Protocol):
    def load(self) -> list[LearnedPath]: ...

    def save(self, paths: Sequence[LearnedPath]) -> None: ...


class JsonPathStore:
    """The learned paths in a file, so a restart or a deploy does not forget them.
    A missing or broken file is logged and treated as no paths yet."""

    def __init__(self, path: pathlib.Path, logger: logging.Logger) -> None:
        self._path = path
        self._logger = logger

    def load(self) -> list[LearnedPath]:
        try:
            saved = json.loads(self._path.read_text())
            return [
                LearnedPath(
                    entry["hex"],
                    datetime.fromisoformat(entry["learnedAt"]),
                    tuple(
                        Fix(Location(lat, lon), int(alt), float(track), float(seconds)) for lat, lon, alt, track, seconds in entry["fixes"]
                    ),
                )
                for entry in saved
            ]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._logger.warning("could not read the learned paths, starting again: %s", error)
            return []

    def save(self, paths: Sequence[LearnedPath]) -> None:
        entries = [
            {
                "hex": path.hex,
                "learnedAt": path.learned_at.isoformat(),
                "fixes": [
                    [
                        round(f.location.lat, 5),
                        round(f.location.lon, 5),
                        f.altitude_ft,
                        round(f.track_deg, 1),
                        round(f.seconds_to_closest, 1),
                    ]
                    for f in path.fixes
                ],
            }
            for path in paths
        ]
        try:
            partial = self._path.with_suffix(".part")
            partial.write_text(json.dumps(entries))
            partial.replace(self._path)
        except OSError as error:
            self._logger.warning("could not keep the learned paths: %s", error)


class LearnedPaths:
    """The most recent paths, none older than max_age, and which of them a plane is on."""

    def __init__(self, store: PathStore, likeness: Likeness, max_paths: int, max_age: timedelta, clock: Clock) -> None:
        self._store = store
        self._likeness = likeness
        self._max_paths = max_paths
        self._max_age = max_age
        self._clock = clock
        self._paths = store.load()

    def add(self, path: LearnedPath) -> None:
        since = self._clock.now() - self._max_age
        self._paths = [*[p for p in self._paths if p.learned_at >= since][-(self._max_paths - 1) :], path]
        self._store.save(self._paths)

    def on(self, plane: Aircraft) -> dict[str, float]:
        """For each earlier plane whose path this one is on, how long it took from here to its closest point."""
        found: dict[str, float] = {}
        for path in self._paths:
            fix = next((f for f in path.fixes if self._likeness.matches(plane, f)), None)
            if fix is not None:
                found[path.hex] = fix.seconds_to_closest
        return found


class _Flight:
    """One plane's track near home so far: where it has been, and when it was closest."""

    def __init__(self, now: float) -> None:
        self.fixes: list[tuple[float, Fix]] = []
        self.closest_km = math.inf
        self.closest_at = now
        self.last_seen = now

    def note(self, fix: Fix, distance_km: float, now: float, every_seconds: float) -> None:
        self.last_seen = now
        if not self.fixes or now - self.fixes[-1][0] >= every_seconds:
            self.fixes.append((now, fix))
        if distance_km < self.closest_km:
            self.closest_km, self.closest_at = distance_km, now

    def gone_past(self, distance_km: float, radius_km: float) -> bool:
        """Outside the zone and well past its closest point."""
        return distance_km > radius_km and distance_km > self.closest_km + 1

    def path(self, hex_code: str, radius_km: float, learned_at: datetime) -> LearnedPath | None:
        """The way it came, if it came within radius_km, timed to its closest point."""
        if self.closest_km > radius_km:
            return None
        fixes = tuple(replace(fix, seconds_to_closest=self.closest_at - at) for at, fix in self.fixes if at < self.closest_at)
        return LearnedPath(hex_code, learned_at, fixes) if len(fixes) >= 2 else None


class PathRecorder:
    """Watches every plane near home, and when one that came within radius_km has gone
    on its way, keeps the path it flew to get there, from as far out as path_km."""

    def __init__(
        self,
        paths: LearnedPaths,
        centre: Location,
        radius_km: float,
        path_km: float,
        every_seconds: float,
        gone_seconds: float,
        clock: Clock,
        logger: logging.Logger,
    ) -> None:
        self._paths = paths
        self._centre = centre
        self._radius_km = radius_km
        self._path_km = path_km
        self._every_seconds = every_seconds
        self._gone_seconds = gone_seconds
        self._clock = clock
        self._logger = logger
        self._flying: dict[str, _Flight] = {}

    def observe(self, aircraft: Iterable[Aircraft]) -> None:
        now = self._clock.monotonic()
        for plane in aircraft:
            if plane.location is None or plane.on_ground or plane.altitude_ft is None or plane.track_deg is None:
                continue
            distance_km = self._centre.distance_km(plane.location)
            if distance_km > self._path_km:
                continue
            flight = self._flying.setdefault(plane.hex, _Flight(now))
            flight.note(Fix(plane.location, plane.altitude_ft, plane.track_deg, 0.0), distance_km, now, self._every_seconds)
            if flight.gone_past(distance_km, self._radius_km):
                self._finish(plane.hex)
        for hex_code in [h for h, f in self._flying.items() if now - f.last_seen > self._gone_seconds]:
            self._finish(hex_code)

    def _finish(self, hex_code: str) -> None:
        path = self._flying.pop(hex_code).path(hex_code, self._radius_km, self._clock.now())
        if path is not None:
            self._paths.add(path)
            self._logger.info("learned the path %s flew overhead, %d points", hex_code, len(path.fixes))


class PathFinder:
    """Planes outside the zone on the path at least min_paths earlier planes flew overhead,
    for held_polls looks in a row. From then on one is followed while it is still on
    any of them, and given the time those planes took from there to their closest point."""

    def __init__(self, paths: LearnedPaths, centre: Location, radius_km: float, min_paths: int, held_polls: int) -> None:
        self._paths = paths
        self._centre = centre
        self._radius_km = radius_km
        self._min_paths = min_paths
        self._held_polls = held_polls
        self._held: dict[str, int] = {}
        self._following: set[str] = set()

    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]:
        found, held = [], {}
        for plane in aircraft:
            if plane.location is None or plane.on_ground:
                continue
            distance_km = self._centre.distance_km(plane.location)
            if distance_km <= self._radius_km:
                continue
            on = self._paths.on(plane)
            if plane.hex in self._following:
                if not on:
                    continue
            else:
                if len(on) < self._min_paths:
                    continue
                held[plane.hex] = self._held.get(plane.hex, 0) + 1
                if held[plane.hex] < self._held_polls:
                    continue
            found.append(Sighting(plane, distance_km, statistics.median(on.values()), approaching=True))
        self._held = held
        self._following = {s.aircraft.hex for s in found}
        return found


class Observer(Protocol):
    def observe(self, aircraft: Iterable[Aircraft]) -> None: ...


class Observing:
    """A finder that lets an observer see every plane first, so paths are learned from
    the same looks the planes are found in."""

    def __init__(self, observer: Observer, finder: SightingFinder) -> None:
        self._observer = observer
        self._finder = finder

    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]:
        planes = list(aircraft)
        self._observer.observe(planes)
        return self._finder.sightings(planes)


class FirstFound:
    """Planes on their way by any of the finders, each once, as the first finder to see
    it has it, soonest overhead first."""

    def __init__(self, finders: Sequence[SightingFinder]) -> None:
        self._finders = finders

    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]:
        planes = list(aircraft)
        found: dict[str, Sighting] = {}
        for finder in self._finders:
            for sighting in finder.sightings(planes):
                found.setdefault(sighting.aircraft.hex, sighting)
        return sorted(found.values(), key=lambda s: s.overhead_in_seconds or 0.0)
