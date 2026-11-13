"""Aircraft worth naming who they belong to: a pop star's jet, a football club's 737.

The list is plane-alert-db (https://github.com/sdr-enthusiasts/plane-alert-db, Open
Database License), fetched from the web onto the Pi and kept fresh there, so the repo
holds no copy. It names each aircraft's operator, which for a celebrity is often a
company standing in for them ("Island Jet Inc"), so a names file kept on the Pi can say
who a registration really belongs to, and add aircraft the list leaves out."""

import csv
import io
import logging
import pathlib
import threading
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.clock import Clock
from flights_watcher.http import TextHttp
from flights_watcher.zone import Sighting

# What a plane only in the names file is filed under.
NAMED = "Named"


@dataclass(frozen=True)
class Notable:
    who: str
    category: str
    # The Wikipedia article about them, when it is not simply their name.
    article: str | None = None

    @property
    def about(self) -> str:
        return self.article or self.who


@dataclass(frozen=True)
class Owner:
    who: str
    article: str | None = None


class NotableFinder(Protocol):
    def of(self, plane: Aircraft) -> Notable | None: ...


class TextSource(Protocol):
    def text(self) -> str | None:
        """The text, or None while there is none."""
        ...


class NoText:
    def text(self) -> str | None:
        return None


class LocalText:
    """A file on the Pi, which may not be there."""

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path

    def text(self) -> str | None:
        try:
            return self._path.read_text(encoding="utf-8")
        except OSError:
            return None


class MirroredText:
    """A copy of a file on the web, kept at path and fetched again once it is older than
    max_age_seconds. When the web is down the copy it has stands in."""

    def __init__(self, url: str, path: pathlib.Path, max_age_seconds: float, http: TextHttp, clock: Clock, logger: logging.Logger) -> None:
        self._url = url
        self._path = path
        self._max_age_seconds = max_age_seconds
        self._http = http
        self._clock = clock
        self._logger = logger

    def text(self) -> str | None:
        if self._stale():
            self._fetch()
        return LocalText(self._path).text()

    def _stale(self) -> bool:
        try:
            age = self._clock.now().timestamp() - self._path.stat().st_mtime
        except OSError:
            return True
        return age >= self._max_age_seconds

    def _fetch(self) -> None:
        try:
            body = self._http.get_text(self._url)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            partial = self._path.with_name(self._path.name + ".partial")
            partial.write_text(body, encoding="utf-8")
            partial.replace(self._path)
        except (OSError, ValueError) as error:
            self._logger.warning("could not fetch %s: %s", self._url, error)


def plane_alert_table(text: str, categories: Collection[str]) -> dict[str, Notable]:
    """The aircraft in a plane-alert-db CSV in any of these categories, by ICAO hex."""
    table: dict[str, Notable] = {}
    for row in csv.DictReader(io.StringIO(text)):
        hex_code, who, category = (row.get(column, "").strip() for column in ("$ICAO", "$Operator", "Category"))
        if hex_code and who and category in categories:
            table[hex_code.lower()] = Notable(who, category)
    return table


def owner_names(text: str) -> dict[str, Owner]:
    """A names file: a registration, then who it belongs to, a plane to a line, such as
    "N621MM Taylor Swift". Where their Wikipedia article goes by another name, it follows
    a bar: "G-XXEB The King | Charles III". Blank lines and lines starting with # are left
    out."""
    names: dict[str, Owner] = {}
    for line in text.splitlines():
        registration, _, rest = line.strip().partition(" ")
        who, _, article = (part.strip() for part in rest.partition("|"))
        if registration and not registration.startswith("#") and who:
            names[_registration(registration)] = Owner(who, article or None)
    return names


def _registration(registration: str) -> str:
    # The feed writes G-EUYM, people often write GEUYM.
    return registration.replace("-", "").upper()


class Starter(Protocol):
    def start(self, work: Callable[[], None]) -> None: ...


class ThreadStarter:
    def start(self, work: Callable[[], None]) -> None:
        threading.Thread(target=work, name="background-refresh", daemon=True).start()


class InBackground[T]:
    """The latest of something slow to get, got again every every_seconds by work of its
    own, so asking for it never waits. It is the empty value until the first is in."""

    def __init__(self, load: Callable[[], T], empty: T, clock: Clock, every_seconds: float, starter: Starter) -> None:
        self._load = load
        self._value = empty
        self._clock = clock
        self._every_seconds = every_seconds
        self._starter = starter
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._loading = False

    def value(self) -> T:
        with self._lock:
            now = self._clock.monotonic()
            due = self._started_at is None or now - self._started_at >= self._every_seconds
            if due and not self._loading:
                self._started_at, self._loading = now, True
                self._starter.start(self._refresh)
            return self._value

    def _refresh(self) -> None:
        try:
            value = self._load()
            with self._lock:
                self._value = value
        finally:
            with self._lock:
                self._loading = False


class Current[T](Protocol):
    def value(self) -> T: ...


class NotableAircraft:
    """A plane's entry in the list, with the names file's word on who it belongs to put
    first, as it is the one kept by hand."""

    def __init__(self, table: Current[Mapping[str, Notable]], names: Current[Mapping[str, Owner]]) -> None:
        self._table = table
        self._names = names

    def of(self, plane: Aircraft) -> Notable | None:
        listed = self._table.value().get(plane.hex.lower())
        named = self._names.value().get(_registration(plane.registration)) if plane.registration else None
        if named:
            return Notable(named.who, listed.category if listed else NAMED, named.article)
        return listed


class CardMaker(Protocol):
    def card(self, sighting: Sighting) -> dict[str, Any]: ...


class PortraitLookup(Protocol):
    def portrait(self, article: str) -> str | None: ...


class OwnedCards:
    """Each card with who its plane belongs to, what they are listed under, and a picture
    of them, when it is a notable one."""

    def __init__(self, cards: CardMaker, notables: NotableFinder, portraits: PortraitLookup) -> None:
        self._cards = cards
        self._notables = notables
        self._portraits = portraits

    def card(self, sighting: Sighting) -> dict[str, Any]:
        notable = self._notables.of(sighting.aircraft)
        return {
            **self._cards.card(sighting),
            "owner": notable.who if notable else None,
            "ownerCategory": notable.category if notable else None,
            "ownerPortrait": self._portraits.portrait(notable.about) if notable else None,
        }
