"""The routes the watcher has looked up and kept, for the /flights page: which flight each
callsign is, where it flies, when it was asked about, and whether that answer is still
trusted or will be asked for again the next time the flight comes by.

It never leaves the Pi, apart from the page on the home network that reads it back."""

from datetime import datetime
from typing import Any, Protocol

from flights_watcher.clock import Clock
from flights_watcher.lookups import Airport, LookupFailed, RouteLookup


class SavedAnswers(Protocol):
    def saved(self) -> list[tuple[str, datetime]]:
        """Every key kept, with when its answer was saved, newest first."""
        ...


class Freshness(Protocol):
    def is_fresh(self, saved_at: datetime, now: datetime) -> bool: ...


class KnownRoutesPage:
    """Every kept route for the live server, newest first, each with its airports named as
    the card names them."""

    def __init__(self, saved: SavedAnswers, routes: RouteLookup, freshness: Freshness, clock: Clock) -> None:
        self._saved = saved
        self._routes = routes
        self._freshness = freshness
        self._clock = clock

    def latest(self) -> dict[str, Any]:
        now = self._clock.now()
        rows = []
        for callsign, saved_at in self._saved.saved():
            try:
                route = self._routes.route(callsign)
            except LookupFailed:
                continue
            if route is None:
                continue
            rows.append(
                {
                    "callsign": callsign,
                    "flight_number": route.flight_number,
                    "airline": route.airline,
                    "origin": _airport(route.origin),
                    "destination": _airport(route.destination),
                    "saved_at": saved_at.isoformat(timespec="seconds"),
                    "fresh": self._freshness.is_fresh(saved_at, now),
                }
            )
        return {"routes": rows}


def _airport(airport: Airport | None) -> dict[str, Any] | None:
    if airport is None:
        return None
    return {"code": airport.code, "name": airport.name, "city": airport.city, "country": airport.country}
