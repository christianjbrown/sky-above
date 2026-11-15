"""Free answers first, and a paid lookup only when the free ones will not do."""

import logging
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.flightaware import OperatorNames
from flights_watcher.lookups import LookupFailed, Route, RouteLookup
from flights_watcher.route_fit import RouteFit


class PlaneRoutes(Protocol):
    def route_of(self, plane: Aircraft) -> Route | None:
        """None when the plane has no known route. Raises LookupFailed."""
        ...


class RouteKeeper(Protocol):
    def keep(self, callsign: str, route: Route) -> None: ...


class ByCallsign:
    """A plane's route straight from its callsign, unchecked: for when there is no paid
    lookup to fall back on, so a doubtful route is still better than none."""

    def __init__(self, routes: RouteLookup) -> None:
        self._routes = routes

    def route_of(self, plane: Aircraft) -> Route | None:
        return self._routes.route(plane.callsign) if plane.callsign else None


class FreeFirstRoutes:
    """The route already kept for a callsign, when it is fresh and fits the plane; else the
    free list's route, when it fits, kept for next time; else the paid lookup. Most flights
    overhead are on the routes they always fly, so the month's paid lookups go on the ones
    the free list does not know or has wrong."""

    def __init__(
        self,
        kept: RouteLookup,
        free: RouteLookup,
        paid: RouteLookup,
        keeper: RouteKeeper,
        fit: RouteFit,
        logger: logging.Logger,
    ) -> None:
        self._kept = kept
        self._free = free
        self._paid = paid
        self._keeper = keeper
        self._fit = fit
        self._logger = logger

    def route_of(self, plane: Aircraft) -> Route | None:
        callsign = plane.callsign
        if not callsign:
            return None
        kept = self._kept.route(callsign)
        if kept is not None and self._fit.fits(kept, plane):
            return kept
        free = self._free_route(callsign)
        if free is not None and self._fit.fits(free, plane):
            self._keeper.keep(callsign, free)
            return free
        return self._paid.route(callsign)

    def _free_route(self, callsign: str) -> Route | None:
        try:
            return self._free.route(callsign)
        except LookupFailed as error:
            self._logger.warning("free route lookup for %s failed: %s", callsign, error)
            return None


class FirstOperatorName:
    """An airline's name from the free list, else from the paid one."""

    def __init__(self, free: OperatorNames, paid: OperatorNames, logger: logging.Logger) -> None:
        self._free = free
        self._paid = paid
        self._logger = logger

    def name(self, icao: str) -> str | None:
        try:
            found = self._free.name(icao)
        except LookupFailed as error:
            self._logger.warning("free airline lookup for %s failed: %s", icao, error)
            found = None
        return found or self._paid.name(icao)
