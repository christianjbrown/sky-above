"""The flights already announced, so a plane is only ever introduced once."""

import json
import logging
import pathlib
from datetime import datetime, timedelta
from typing import Protocol

from flights_watcher.clock import Clock


class AnnouncedFlights(Protocol):
    def has(self, flight: str) -> bool: ...

    def add(self, flight: str) -> None: ...


class RememberedFlights:
    """The flights announced in the last max_age, kept in a file, so a restart such as a
    deploy does not announce the plane on the card a second time. A flight is gone long
    before max_age is up, and the same airframe on another flight is another key. A
    missing or broken file is logged and treated as nothing announced yet, and one that
    cannot be written leaves the flights remembered until the next restart."""

    def __init__(self, path: pathlib.Path, max_age: timedelta, clock: Clock, logger: logging.Logger) -> None:
        self._path = path
        self._max_age = max_age
        self._clock = clock
        self._logger = logger
        self._flights = self._load()

    def has(self, flight: str) -> bool:
        said = self._flights.get(flight)
        return said is not None and self._clock.now() - said < self._max_age

    def add(self, flight: str) -> None:
        now = self._clock.now()
        self._flights = {f: at for f, at in self._flights.items() if now - at < self._max_age} | {flight: now}
        try:
            partial = self._path.with_suffix(".part")
            partial.write_text(json.dumps({f: at.isoformat() for f, at in self._flights.items()}))
            partial.replace(self._path)
        except OSError as error:
            self._logger.warning("could not keep the announced flights: %s", error)

    def _load(self) -> dict[str, datetime]:
        try:
            return {flight: datetime.fromisoformat(at) for flight, at in json.loads(self._path.read_text()).items()}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, AttributeError, TypeError) as error:
            self._logger.warning("could not read the announced flights, starting again: %s", error)
            return {}
