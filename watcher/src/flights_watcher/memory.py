"""Lookup answers kept on disk, so the same flights passing every day are asked about
once a week rather than every time, and still have a route when FlightAware cannot be reached."""

import json
import logging
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from flights_watcher.clock import Clock
from flights_watcher.flightaware import OperatorNames
from flights_watcher.lookups import Airport, LookupFailed, Route, RouteLookup


@dataclass(frozen=True)
class Kept:
    value: Any
    saved_at: datetime


class AnswerStore(Protocol):
    def get(self, key: str) -> Kept | None: ...

    def put(self, key: str, value: Any, saved_at: datetime) -> None: ...


class SqliteAnswerStore:
    """One kind of answer (routes, operators) in a table shared with the others.
    A broken database is logged and treated as empty, so it never stops the card."""

    def __init__(self, path: str, kind: str, logger: logging.Logger) -> None:
        self._path = path
        self._kind = kind
        self._logger = logger

    def get(self, key: str) -> Kept | None:
        try:
            with closing(self._connect()) as db:
                row = db.execute("SELECT value, saved_at FROM answers WHERE kind = ? AND key = ?", (self._kind, key)).fetchone()
        except sqlite3.Error as error:
            self._logger.warning("could not read the %s answer for %s: %s", self._kind, key, error)
            return None
        return Kept(json.loads(row[0]), datetime.fromisoformat(row[1])) if row else None

    def put(self, key: str, value: Any, saved_at: datetime) -> None:
        try:
            with closing(self._connect()) as db, db:
                db.execute(
                    "INSERT OR REPLACE INTO answers (kind, key, value, saved_at) VALUES (?, ?, ?, ?)",
                    (self._kind, key, json.dumps(value), saved_at.isoformat()),
                )
        except sqlite3.Error as error:
            self._logger.warning("could not keep the %s answer for %s: %s", self._kind, key, error)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path)
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS answers ("
                "kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, saved_at TEXT NOT NULL, "
                "PRIMARY KEY (kind, key))"
            )
        except sqlite3.Error:
            db.close()
            raise
        return db


class Freshness(Protocol):
    def is_fresh(self, saved_at: datetime, now: datetime) -> bool: ...


class YoungerThan:
    def __init__(self, age: timedelta) -> None:
        self._age = age

    def is_fresh(self, saved_at: datetime, now: datetime) -> bool:
        return now - saved_at < self._age


class SameTimetable:
    """Airlines swap between summer and winter timetables on the last Sundays of March
    and October, which is when a callsign is most likely to start flying somewhere else."""

    def is_fresh(self, saved_at: datetime, now: datetime) -> bool:
        return not any(
            saved_at.date() < changeover <= now.date()
            for year in range(saved_at.year, now.year + 1)
            for changeover in (_last_sunday(year, 3), _last_sunday(year, 10))
        )


class AllFresh:
    def __init__(self, rules: Sequence[Freshness]) -> None:
        self._rules = rules

    def is_fresh(self, saved_at: datetime, now: datetime) -> bool:
        return all(rule.is_fresh(saved_at, now) for rule in self._rules)


class Memory:
    """A fresh kept answer is used without asking. A stale one is asked for again, and
    given back when asking fails or comes back empty. Empty answers are never kept, and
    neither is any answer worth_keeping turns down."""

    def __init__(self, store: AnswerStore, freshness: Freshness, clock: Clock, logger: logging.Logger) -> None:
        self._store = store
        self._freshness = freshness
        self._clock = clock
        self._logger = logger

    def recall[T](
        self,
        key: str,
        ask: Callable[[], T | None],
        encode: Callable[[T], Any],
        decode: Callable[[Any], T],
        worth_keeping: Callable[[T], bool] = lambda _: True,
    ) -> T | None:
        now = self._clock.now()
        kept = self._store.get(key)
        if kept is not None and self._freshness.is_fresh(kept.saved_at, now):
            return decode(kept.value)
        try:
            answer = ask()
        except LookupFailed as error:
            if kept is None:
                raise
            self._logger.info("lookup for %s failed (%s), so using the answer kept on %s", key, error, kept.saved_at.date())
            return decode(kept.value)
        if answer is None:
            return decode(kept.value) if kept is not None else None
        if worth_keeping(answer):
            self._store.put(key, encode(answer), now)
        return answer


class RememberedRouteLookup:
    def __init__(self, inner: RouteLookup, memory: Memory) -> None:
        self._inner = inner
        self._memory = memory

    def route(self, callsign: str) -> Route | None:
        return self._memory.recall(callsign, lambda: self._inner.route(callsign), asdict, _route, _both_ends)


class KeptRouteLookup:
    """The route kept on disk for a callsign, however old, without ever asking for one.
    For working out where a plane that is not on the card is going: most of those never
    come near, and a paid lookup for each would spend the month's allowance in days. The
    planes that do get a card are looked up then, and kept, so a flight that passes
    every day is known from its second day on."""

    def __init__(self, store: AnswerStore) -> None:
        self._store = store

    def route(self, callsign: str) -> Route | None:
        kept = self._store.get(callsign)
        return _route(kept.value) if kept else None


class RememberedOperatorNames:
    def __init__(self, inner: OperatorNames, memory: Memory) -> None:
        self._inner = inner
        self._memory = memory

    def name(self, icao: str) -> str | None:
        return self._memory.recall(icao, lambda: self._inner.name(icao), str, str)


def _both_ends(route: Route) -> bool:
    """A route missing an end is usually a one-off flight off the timetable, which says
    nothing about where the callsign goes next time."""
    return route.origin is not None and route.destination is not None


def _route(value: dict[str, Any]) -> Route:
    return Route(
        airline=value.get("airline"),
        flight_number=value.get("flight_number"),
        origin=Airport(**value["origin"]) if value.get("origin") else None,
        destination=Airport(**value["destination"]) if value.get("destination") else None,
    )


def _last_sunday(year: int, month: int) -> date:
    last_day = date(year, month + 1, 1) - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - 6) % 7)
