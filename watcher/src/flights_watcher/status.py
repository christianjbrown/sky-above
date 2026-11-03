"""How the watcher is getting on, for the watchdog to check from outside it."""

import logging
import threading
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.clock import Clock
from flights_watcher.sources import AircraftSource
from flights_watcher.zone import Sighting


class WatchStatus:
    """The latest of what the watcher has reported about itself, safe to read from the
    live page's thread: when it last looked at the sky, since when every look has been
    failing and why, how many aircraft the antenna last heard and when it last heard
    any, and how many planes have come by today."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last_look: datetime | None = None
        self._failing_since: datetime | None = None
        self._failure: str | None = None
        self._aircraft = 0
        self._heard_at: datetime | None = None
        self._planes_today = 0

    def looked(self, failure: str | None) -> None:
        now = self._clock.now()
        with self._lock:
            self._last_look = now
            if failure is None:
                self._failing_since, self._failure = None, None
            else:
                self._failing_since = self._failing_since or now
                self._failure = failure

    def heard(self, aircraft: int) -> None:
        now = self._clock.now()
        with self._lock:
            self._aircraft = aircraft
            if aircraft:
                self._heard_at = now

    def tallied(self, planes_today: int) -> None:
        with self._lock:
            self._planes_today = planes_today

    def latest(self) -> dict[str, Any]:
        with self._lock:
            return {
                "lastLook": _iso(self._last_look),
                "failingSince": _iso(self._failing_since),
                "failure": self._failure,
                "aircraft": self._aircraft,
                "aircraftHeardAt": _iso(self._heard_at),
                "planesToday": self._planes_today,
            }


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


class Hearing(Protocol):
    def heard(self, aircraft: int) -> None: ...


class HeardSource:
    """An aircraft source that reports how many aircraft each look heard."""

    def __init__(self, inner: AircraftSource, hearing: Hearing) -> None:
        self._inner = inner
        self._hearing = hearing

    def aircraft(self) -> list[Aircraft]:
        found = self._inner.aircraft()
        self._hearing.heard(len(found))
        return found


class Tally(Protocol):
    def tallied(self, planes_today: int) -> None: ...


class DailyTally:
    """Counts the planes that come by each day, those overhead and those on their way,
    each once, and logs the day's count when the next day starts."""

    def __init__(self, tally: Tally, clock: Clock, logger: logging.Logger) -> None:
        self._tally = tally
        self._clock = clock
        self._logger = logger
        self._day: date = clock.now().date()
        self._seen: set[str] = set()

    def note(self, sightings: list[Sighting]) -> None:
        today = self._clock.now().date()
        if today != self._day:
            self._logger.info("%d planes came by on %s", len(self._seen), self._day.isoformat())
            self._day, self._seen = today, set()
        self._seen.update(s.aircraft.hex for s in sightings)
        self._tally.tallied(len(self._seen))


class SightingObserver(Protocol):
    def note(self, sightings: list[Sighting]) -> None: ...


class AllObservers:
    """Shows each look's sightings to several observers in turn."""

    def __init__(self, observers: Sequence[SightingObserver]) -> None:
        self._observers = observers

    def note(self, sightings: list[Sighting]) -> None:
        for observer in self._observers:
            observer.note(sightings)
