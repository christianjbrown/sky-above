"""Whether a route fits the plane said to be flying it.

The free route list knows what a callsign usually flies, not what it is flying today, so
it gives old routes and the wrong leg of a round trip. A route that fits where the plane
is and which way it is going is right far more often than not, and only one that does
not fit is worth paying FlightAware to check."""

import math
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import EARTH_RADIUS_KM, Location
from flights_watcher.lookups import Airport, Route

HALF_TURN_DEG = 180.0
FULL_TURN_DEG = 360.0


class RouteFit(Protocol):
    def fits(self, route: Route, plane: Aircraft) -> bool: ...


class OnTheWay:
    """A route fits when the plane is within path_km of the great circle between its
    airports and is going the right way along it. Within airport_km of an end, where
    planes climb out and come in by whatever line the runway gives them, the right way is
    climbing away from the origin or descending towards the destination: a plane coming
    down near the airport it is said to have left is on the other leg. Further out, the
    right way is a track within heading_deg of the destination. A route with an airport
    whose place is not known, or a plane with no position, cannot be checked, so it does
    not fit."""

    def __init__(self, path_km: float, airport_km: float, heading_deg: float, level_fpm: float) -> None:
        self._path_km = path_km
        self._airport_km = airport_km
        self._heading_deg = heading_deg
        self._level_fpm = level_fpm

    def fits(self, route: Route, plane: Aircraft) -> bool:
        origin, destination, here = _place(route.origin), _place(route.destination), plane.location
        if origin is None or destination is None or here is None:
            return False
        if off_path_km(origin, destination, here) > self._path_km:
            return False
        from_origin, to_destination = here.distance_km(origin), here.distance_km(destination)
        rate = plane.vertical_rate_fpm
        if min(from_origin, to_destination) <= self._airport_km:
            if rate is None:
                return True
            return rate >= -self._level_fpm if from_origin <= to_destination else rate <= self._level_fpm
        if plane.track_deg is None:
            return True
        return _turn_deg(plane.track_deg, here.bearing_deg(destination)) <= self._heading_deg


def off_path_km(start: Location, end: Location, here: Location) -> float:
    """How far here is from the great circle between start and end, counting only the
    stretch between them: past either end it is the distance to that end."""
    angle_from_start = start.distance_km(here) / EARTH_RADIUS_KM
    length = start.distance_km(end) / EARTH_RADIUS_KM
    turn = math.radians(start.bearing_deg(here) - start.bearing_deg(end))
    across = math.asin(math.sin(angle_from_start) * math.sin(turn))
    along = math.acos(max(-1.0, min(1.0, math.cos(angle_from_start) / math.cos(across))))
    if math.cos(turn) < 0:
        return start.distance_km(here)
    if along > length:
        return end.distance_km(here)
    return abs(across) * EARTH_RADIUS_KM


def _turn_deg(a: float, b: float) -> float:
    return abs((a - b + HALF_TURN_DEG) % FULL_TURN_DEG - HALF_TURN_DEG)


def _place(airport: Airport | None) -> Location | None:
    if airport is None or airport.lat is None or airport.lon is None:
        return None
    return Location(airport.lat, airport.lon)
