"""Which way a plane is bound: the direction of where it is flying to.

Planes off the same runway climb out along the same line, and only turn onto their own
departure route a minute or so later, picked by the direction of their destination. So two
planes at the same spot, height and heading are only on the same route when they are bound
the same way, and that tells a plane that will come overhead from one that turns away."""

import logging
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location
from flights_watcher.lookups import LookupFailed, RouteLookup


class Bound(Protocol):
    def of(self, plane: Aircraft) -> float | None:
        """The compass bearing towards where the plane is flying, or None when that is not known."""
        ...


class DestinationBound:
    """The bearing from home to a plane's destination airport along the great circle, from
    its route. None for a plane with no callsign, no known route, or a destination with no
    known place, and when the route cannot be looked up just now."""

    def __init__(self, routes: RouteLookup, centre: Location, logger: logging.Logger) -> None:
        self._routes = routes
        self._centre = centre
        self._logger = logger

    def of(self, plane: Aircraft) -> float | None:
        if not plane.callsign:
            return None
        try:
            route = self._routes.route(plane.callsign)
        except LookupFailed as error:
            self._logger.warning("lookup for %s failed: %s", plane.callsign, error)
            return None
        destination = route.destination if route else None
        if destination is None or destination.lat is None or destination.lon is None:
            return None
        return self._centre.bearing_deg(Location(destination.lat, destination.lon))


class SameWay:
    """Whether two planes are bound within within_deg of each other. A plane whose
    destination is not known could be bound anywhere, so it is taken to be going the same
    way as any other."""

    def __init__(self, within_deg: float) -> None:
        self._within_deg = within_deg

    def alike(self, bound_deg: float | None, other_deg: float | None) -> bool:
        if bound_deg is None or other_deg is None:
            return True
        return abs((bound_deg - other_deg + 180) % 360 - 180) <= self._within_deg
