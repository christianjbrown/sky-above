"""Planes not overhead yet, but flying a line that will take them through the zone.

Each plane is taken to carry straight on at its current speed and track, which is
good enough to say roughly when it will be overhead. Over flat ground near home
the Earth's curve makes no difference worth the maths."""

import math
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location
from flights_watcher.zone import Sighting

KM_PER_DEGREE_LAT = 110.574
KM_PER_DEGREE_LON_AT_EQUATOR = 111.32
KM_PER_HOUR_PER_KNOT = 1.852


class ClosestApproach:
    """When a plane will be closest to home, and how close, if it carries straight on.
    None when it is not flying (on the ground, hovering, no track) or the closest point
    is already behind it."""

    def __init__(self, centre: Location, min_speed_kt: float) -> None:
        self._centre = centre
        self._min_speed_kt = min_speed_kt

    def of(self, plane: Aircraft) -> tuple[float, float] | None:
        """Seconds until the closest point, and how far from home that point is in km."""
        if plane.location is None or plane.on_ground or plane.track_deg is None or plane.ground_speed_kt is None:
            return None
        if plane.ground_speed_kt < self._min_speed_kt:
            return None
        x, y = self._offset_km(plane.location)
        speed = plane.ground_speed_kt * KM_PER_HOUR_PER_KNOT / 3600
        track = math.radians(plane.track_deg)
        vx, vy = speed * math.sin(track), speed * math.cos(track)
        seconds = -(x * vx + y * vy) / (speed * speed)
        if seconds <= 0:
            return None
        return seconds, math.hypot(x + vx * seconds, y + vy * seconds)

    def _offset_km(self, place: Location) -> tuple[float, float]:
        km_per_degree_lon = KM_PER_DEGREE_LON_AT_EQUATOR * math.cos(math.radians(self._centre.lat))
        return (place.lon - self._centre.lon) * km_per_degree_lon, (place.lat - self._centre.lat) * KM_PER_DEGREE_LAT


class ApproachFinder:
    """Planes outside the zone whose closest point to home is inside it.

    Planes near airports turn a lot, and a turning plane's straight line sweeps across
    the sky, so for a moment it can point at home without coming anywhere near. A plane
    only starts to count once its line has passed through the zone for steady_polls
    looks in a row, and steady_polls_per_km more for every km it is beyond the zone,
    while its track turned no more than max_turn_deg. The further out a plane is, the
    more a small turn moves where its line crosses, and the more time it has to change
    course, so the more of a run it needs before it is believed. A plane any of the
    exclusions rules out never counts (see LandsFirst, SteeredIn and MissedBefore). A plane
    climbing out after take-off does count: its departure route may still turn it away, but it
    is low and only heard a minute or so out, so waiting for it to climb means no warning at
    all. Once planes have been seen turning away from that spot, MissedBefore stops it.
    From then on it is followed through until it has passed its closest point, unless it
    turns enough that its line misses the zone by more than wander_km, so a small drift
    near the edge does not flick it off and on."""

    def __init__(
        self,
        closest: ClosestApproach,
        centre: Location,
        radius_km: float,
        steady_polls: int,
        steady_polls_per_km: float,
        max_turn_deg: float,
        wander_km: float,
        exclusions: Sequence["Exclusion"],
    ) -> None:
        self._closest = closest
        self._exclusions = exclusions
        self._centre = centre
        self._radius_km = radius_km
        self._steady_polls = steady_polls
        self._steady_polls_per_km = steady_polls_per_km
        self._max_turn_deg = max_turn_deg
        self._wander_km = wander_km
        self._tracks: dict[str, list[float]] = {}
        self._following: set[str] = set()

    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]:
        found, tracks = [], {}
        for plane in aircraft:
            if plane.location is None or plane.track_deg is None:
                continue
            distance_km = self._centre.distance_km(plane.location)
            if distance_km <= self._radius_km:
                continue
            closest = self._closest.of(plane)
            if closest is None:
                continue
            if plane.hex in self._following:
                if closest[1] > self._radius_km + self._wander_km:
                    continue
            else:
                if closest[1] > self._radius_km:
                    continue
                if any(rule.excludes(plane, distance_km, closest[0]) for rule in self._exclusions):
                    continue
                needed = self._needed(distance_km)
                tracks[plane.hex] = [*self._tracks.get(plane.hex, []), plane.track_deg][-needed:]
                if not self._steady(tracks[plane.hex], needed):
                    continue
            found.append(Sighting(plane, distance_km, closest[0], approaching=True))
        self._tracks = tracks
        self._following = {s.aircraft.hex for s in found}
        return sorted(found, key=lambda s: s.overhead_in_seconds or 0.0)

    def _needed(self, distance_km: float) -> int:
        return self._steady_polls + math.ceil((distance_km - self._radius_km) * self._steady_polls_per_km)

    def _steady(self, tracks: list[float], needed: int) -> bool:
        if len(tracks) < needed:
            return False
        latest = tracks[-1]
        return all(abs((track - latest + 180) % 360 - 180) <= self._max_turn_deg for track in tracks)


class Exclusion(Protocol):
    def excludes(self, plane: Aircraft, distance_km: float, seconds_to_closest: float) -> bool:
        """Whether a plane whose line passes through the zone is still not on its way."""
        ...


class LandsFirst:
    """A plane coming down that, keeping its rate of descent, reaches the ground before it
    reaches home: landing at a nearby airport, say."""

    def excludes(self, plane: Aircraft, distance_km: float, seconds_to_closest: float) -> bool:
        if plane.altitude_ft is None or plane.vertical_rate_fpm is None or plane.vertical_rate_fpm >= 0:
            return False
        return plane.altitude_ft / -plane.vertical_rate_fpm * 60 < seconds_to_closest


class SteeredIn:
    """A plane coming down low a long way out, which air traffic control is steering in to
    land a heading at a time, so its line means little."""

    def __init__(self, below_ft: int, beyond_km: float, descending_fpm: int) -> None:
        self._below_ft = below_ft
        self._beyond_km = beyond_km
        self._descending_fpm = descending_fpm

    def excludes(self, plane: Aircraft, distance_km: float, seconds_to_closest: float) -> bool:
        if plane.altitude_ft is None or plane.vertical_rate_fpm is None:
            return False
        low_and_descending = plane.altitude_ft < self._below_ft and plane.vertical_rate_fpm < self._descending_fpm
        return low_and_descending and distance_km > self._beyond_km


class SightingFinder(Protocol):
    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]: ...


class OverheadAndApproaching:
    """The planes in the zone, nearest first, then those on their way, soonest first.
    A plane already in the zone but still closing in on home gets its time to the
    closest point too, unless that is only a moment away."""

    def __init__(self, zone: SightingFinder, approaches: SightingFinder, closest: ClosestApproach, min_seconds: float) -> None:
        self._zone = zone
        self._approaches = approaches
        self._closest = closest
        self._min_seconds = min_seconds

    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]:
        planes = list(aircraft)
        overhead = [self._timed(s) for s in self._zone.sightings(planes)]
        inside = {s.aircraft.hex for s in overhead}
        return overhead + [s for s in self._approaches.sightings(planes) if s.aircraft.hex not in inside]

    def _timed(self, sighting: Sighting) -> Sighting:
        closest = self._closest.of(sighting.aircraft)
        if closest is None or closest[0] < self._min_seconds:
            return sighting
        return replace(sighting, overhead_in_seconds=closest[0])
