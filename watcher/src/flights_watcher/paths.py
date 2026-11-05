"""Routes learned from the planes that really came overhead.

A plane climbing out of a nearby airport turns onto its departure route a minute or so
before it reaches home, and until the turn is done its straight line points somewhere
else. But planes off the same runway fly the same route, so once two earlier planes have
come overhead along it, a new one at the same spot, height and heading is on its way too,
turn and all. Each runway, and each direction the airport is working in, is a route of its
own, learned separately, and a plane on a route that has never brought anything overhead
matches nothing. Planes off one runway share the climb out and split later, by where they are
going, so each path keeps which way its plane was bound, and a plane is only on the paths of
planes bound the same way as it (see flights_watcher.bound).

The misses are learned too. A plane whose straight line ran through the zone but which then
turned away without coming in leaves the points where it looked to be on its way, and once
two bound the same way have missed from the same spot, with nothing bound that way ever coming
overhead from there, a straight line from that spot is no longer believed (see MissedBefore)."""

import json
import logging
import math
import pathlib
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.approach import SightingFinder
from flights_watcher.bound import Bound, SameWay
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
    # Which way the plane was bound, as a compass bearing, if that was known.
    bound_deg: float | None = None


@dataclass(frozen=True)
class Passing:
    """An earlier plane whose path a plane is on: which way it was bound, and how long it
    took from there to its closest point."""

    hex: str
    bound_deg: float | None
    seconds_to_closest: float


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


def _aware(moment: datetime) -> datetime:
    """Early versions wrote the time without its zone, in UTC. Left naive, it cannot be
    compared with the clock's and every new path failed to save."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


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
                    _aware(datetime.fromisoformat(entry["learnedAt"])),
                    tuple(
                        Fix(Location(lat, lon), int(alt), float(track), float(seconds)) for lat, lon, alt, track, seconds in entry["fixes"]
                    ),
                    entry.get("boundDeg"),
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
                "boundDeg": None if path.bound_deg is None else round(path.bound_deg, 1),
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

    def on(self, plane: Aircraft) -> list[Passing]:
        """The earlier planes whose paths this one is on, one each, wherever they were bound."""
        found: dict[str, Passing] = {}
        for path in self._paths:
            fix = next((f for f in path.fixes if self._likeness.matches(plane, f)), None)
            if fix is not None:
                found[path.hex] = Passing(path.hex, path.bound_deg, fix.seconds_to_closest)
        return list(found.values())


class Flight:
    """One plane's track near home so far: where it has been, where its line ran through
    the zone, and when it was closest."""

    def __init__(self, plane: Aircraft, now: float) -> None:
        self.plane = plane
        self.fixes: list[tuple[float, Fix]] = []
        self.aimed: list[tuple[float, Fix]] = []
        self.closest_km = math.inf
        self.closest_at = now
        self.last_seen = now

    def note(self, plane: Aircraft, fix: Fix, distance_km: float, aimed: bool, now: float, every_seconds: float) -> None:
        self.plane, self.last_seen = plane, now
        if not self.fixes or now - self.fixes[-1][0] >= every_seconds:
            self.fixes.append((now, fix))
        if aimed and (not self.aimed or now - self.aimed[-1][0] >= every_seconds):
            self.aimed.append((now, fix))
        if distance_km < self.closest_km:
            self.closest_km, self.closest_at = distance_km, now

    def gone_past(self, distance_km: float, radius_km: float) -> bool:
        """Outside the zone and well past its closest point."""
        return distance_km > radius_km and distance_km > self.closest_km + 1

    def timed(self, fixes: Iterable[tuple[float, Fix]]) -> tuple[Fix, ...]:
        """The fixes, each with how long the plane took from there to its closest point."""
        return tuple(replace(fix, seconds_to_closest=self.closest_at - at) for at, fix in fixes)


class Lesson(Protocol):
    def learn(self, hex_code: str, flight: Flight, learned_at: datetime) -> None:
        """Keep what a plane that has gone on its way showed, if anything."""
        ...


class CameOverhead:
    """The path a plane that came within radius_km flew to get there, and which way it was bound."""

    def __init__(self, paths: LearnedPaths, bound: Bound, radius_km: float, logger: logging.Logger) -> None:
        self._paths = paths
        self._bound = bound
        self._radius_km = radius_km
        self._logger = logger

    def learn(self, hex_code: str, flight: Flight, learned_at: datetime) -> None:
        if flight.closest_km > self._radius_km:
            return
        fixes = flight.timed((at, fix) for at, fix in flight.fixes if at < flight.closest_at)
        if len(fixes) >= 2:
            self._paths.add(LearnedPath(hex_code, learned_at, fixes, self._bound.of(flight.plane)))
            self._logger.info("learned the path %s flew overhead, %d points", hex_code, len(fixes))


class MissedIt:
    """Where a plane was while its line ran through the zone, if it then went past without
    coming within radius_km. Only a plane whose destination is known teaches anything, since
    a miss says nothing about planes bound elsewhere."""

    def __init__(self, misses: LearnedPaths, bound: Bound, radius_km: float, logger: logging.Logger) -> None:
        self._misses = misses
        self._bound = bound
        self._radius_km = radius_km
        self._logger = logger

    def learn(self, hex_code: str, flight: Flight, learned_at: datetime) -> None:
        if flight.closest_km <= self._radius_km or not flight.aimed:
            return
        bound_deg = self._bound.of(flight.plane)
        if bound_deg is None:
            return
        fixes = flight.timed(flight.aimed)
        self._misses.add(LearnedPath(hex_code, learned_at, fixes, bound_deg))
        self._logger.info("learned where %s looked on its way but missed, %d points", hex_code, len(fixes))


class Approach(Protocol):
    def of(self, plane: Aircraft) -> tuple[float, float] | None:
        """Seconds until the plane is closest to home on its straight line, and how close, in km."""
        ...


class PathRecorder:
    """Watches every plane near home, from as far out as path_km, and when one has gone on
    its way hands what it did to each of the lessons."""

    def __init__(
        self,
        lessons: Sequence[Lesson],
        closest: Approach,
        centre: Location,
        radius_km: float,
        path_km: float,
        every_seconds: float,
        gone_seconds: float,
        clock: Clock,
    ) -> None:
        self._lessons = lessons
        self._closest = closest
        self._centre = centre
        self._radius_km = radius_km
        self._path_km = path_km
        self._every_seconds = every_seconds
        self._gone_seconds = gone_seconds
        self._clock = clock
        self._flying: dict[str, Flight] = {}

    def observe(self, aircraft: Iterable[Aircraft]) -> None:
        now = self._clock.monotonic()
        for plane in aircraft:
            if plane.location is None or plane.on_ground or plane.altitude_ft is None or plane.track_deg is None:
                continue
            distance_km = self._centre.distance_km(plane.location)
            if distance_km > self._path_km:
                continue
            flight = self._flying.setdefault(plane.hex, Flight(plane, now))
            fix = Fix(plane.location, plane.altitude_ft, plane.track_deg, 0.0)
            flight.note(plane, fix, distance_km, distance_km > self._radius_km and self._aimed(plane), now, self._every_seconds)
            if flight.gone_past(distance_km, self._radius_km):
                self._finish(plane.hex)
        for hex_code in [h for h, f in self._flying.items() if now - f.last_seen > self._gone_seconds]:
            self._finish(hex_code)

    def _aimed(self, plane: Aircraft) -> bool:
        closest = self._closest.of(plane)
        return closest is not None and closest[1] <= self._radius_km

    def _finish(self, hex_code: str) -> None:
        flight = self._flying.pop(hex_code)
        for lesson in self._lessons:
            lesson.learn(hex_code, flight, self._clock.now())


class MissedBefore:
    """A plane where at least min_misses earlier planes bound the same way looked to be on
    their way and then missed, when no plane bound that way has come overhead from there: a
    departure route that turns away before home, say. Its straight line has been wrong
    before, so it is not believed. A plane whose destination is not known is believed, so
    nothing is missed for want of a lookup."""

    def __init__(self, misses: LearnedPaths, hits: LearnedPaths, bound: Bound, way: SameWay, min_misses: int) -> None:
        self._misses = misses
        self._hits = hits
        self._bound = bound
        self._way = way
        self._min_misses = min_misses

    def excludes(self, plane: Aircraft, distance_km: float, seconds_to_closest: float) -> bool:
        misses = self._misses.on(plane)
        if len(misses) < self._min_misses:
            return False
        bound_deg = self._bound.of(plane)
        if bound_deg is None:
            return False
        if sum(self._way.alike(m.bound_deg, bound_deg) for m in misses) < self._min_misses:
            return False
        return not any(self._way.alike(h.bound_deg, bound_deg) for h in self._hits.on(plane))


class PathFinder:
    """Planes outside the zone on the path at least min_paths earlier planes bound the same
    way flew overhead, for held_polls looks in a row. From then on one is followed while it
    is still on any of them, and given the time those planes took from there to their
    closest point. Which way a plane is bound is only looked up once it is on enough paths."""

    def __init__(
        self, paths: LearnedPaths, bound: Bound, way: SameWay, centre: Location, radius_km: float, min_paths: int, held_polls: int
    ) -> None:
        self._paths = paths
        self._bound = bound
        self._way = way
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
            following = plane.hex in self._following
            needed = 1 if following else self._min_paths
            on = self._paths.on(plane)
            if len(on) < needed:
                continue
            bound_deg = self._bound.of(plane)
            on = [p for p in on if self._way.alike(p.bound_deg, bound_deg)]
            if len(on) < needed:
                continue
            if not following:
                held[plane.hex] = self._held.get(plane.hex, 0) + 1
                if held[plane.hex] < self._held_polls:
                    continue
            found.append(Sighting(plane, distance_km, statistics.median(p.seconds_to_closest for p in on), approaching=True))
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
