"""A record of every plane that gets the card, kept on the Pi, so what flew over can be
looked back on: when, which flight, where it was going, how close it came, and who the
famous ones belong to.

It never leaves the Pi, apart from the page on the home network that reads it back."""

import logging
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from flights_watcher.clock import Clock

# The only message that puts a plane on screen; standby and clear do not.
PLANES = "planes"


class Kind(StrEnum):
    """What sort of flight it was, for the history page to filter by."""

    AIRLINE = "airline"
    MILITARY = "military"
    POLICE = "police"
    AMBULANCE = "ambulance"
    PRIVATE_HELICOPTER = "private-helicopter"
    PRIVATE_PLANE = "private-plane"


# The card's service kinds that are kinds of their own here.
SERVICE_KINDS = {"military": Kind.MILITARY, "police": Kind.POLICE, "ambulance": Kind.AMBULANCE}


@dataclass(frozen=True)
class Shown:
    """One plane's time on the card, from when it took the screen."""

    hex: str
    shown_at: str
    kind: str
    callsign: str | None
    flight_number: str | None
    registration: str | None
    aircraft: str | None
    type_code: str | None
    airline: str | None
    origin: str | None
    destination: str | None
    owner: str | None
    owner_category: str | None
    emergency: str | None
    closest_km: float
    lowest_ft: int | None
    # When the plane was last on the card, so a visit can carry on after the watcher restarts.
    seen_at: str


_COLUMNS = (
    "hex, shown_at, kind, callsign, flight_number, registration, aircraft, type_code, airline, "
    "origin, destination, owner, owner_category, emergency, closest_km, lowest_ft, seen_at"
)
_TABLE = (
    "CREATE TABLE IF NOT EXISTS shown ("
    "hex TEXT NOT NULL, shown_at TEXT NOT NULL, kind TEXT NOT NULL, callsign TEXT, flight_number TEXT, "
    "registration TEXT, aircraft TEXT, type_code TEXT, airline TEXT, origin TEXT, destination TEXT, "
    "owner TEXT, owner_category TEXT, emergency TEXT, closest_km REAL NOT NULL, lowest_ft INTEGER, "
    "seen_at TEXT, PRIMARY KEY (hex, shown_at))"
)
_INDEX = "CREATE INDEX IF NOT EXISTS shown_at ON shown (shown_at)"
# A history kept before seen_at existed gets the column, empty, which reads as shown_at.
_SEEN_COLUMN = "seen_at"
_TABLE_COLUMNS = "SELECT name FROM pragma_table_info('shown')"
_ADD_SEEN = f"ALTER TABLE shown ADD COLUMN {_SEEN_COLUMN} TEXT"
_KEEP = (
    f"INSERT OR REPLACE INTO shown ({_COLUMNS}) VALUES (:hex, :shown_at, :kind, :callsign, :flight_number, "  # noqa: S608
    ":registration, :aircraft, :type_code, :airline, :origin, :destination, :owner, :owner_category, "
    ":emergency, :closest_km, :lowest_ft, :seen_at)"
)
_ALL = f"SELECT {_COLUMNS} FROM shown ORDER BY shown_at DESC"  # noqa: S608 - no outside input
_LAST = f"SELECT {_COLUMNS} FROM shown WHERE hex = ? ORDER BY shown_at DESC LIMIT 1"  # noqa: S608
# Only airline flights are forgotten: everything else is rare enough to keep for good.
_FORGET = "DELETE FROM shown WHERE shown_at < ? AND kind = ?"


class Visits(Protocol):
    def keep(self, shown: Shown) -> None:
        """Adds a plane's time on the card, or replaces what was kept for it so far."""
        ...

    def last_visit(self, hex_code: str) -> Shown | None:
        """The plane's latest time on the card, if it has had one."""
        ...


class ShownStore(Visits, Protocol):
    def everything(self) -> list[Shown]:
        """Every plane kept, newest first."""
        ...


class ForgettableStore(ShownStore, Protocol):
    def forget_airlines_before(self, cutoff: datetime) -> None:
        """Drops the airline flights shown before cutoff, keeping everything rarer."""
        ...


class SqliteShownStore:
    """The history in an SQLite file in STATE_DIR. A broken database is logged and treated
    as empty, so it never stops the card."""

    def __init__(self, path: str, logger: logging.Logger) -> None:
        self._path = path
        self._logger = logger

    def keep(self, shown: Shown) -> None:
        self._write(_KEEP, asdict(shown), f"could not keep {shown.hex} in the history")

    def forget_airlines_before(self, cutoff: datetime) -> None:
        self._write(_FORGET, (_stamp(cutoff), Kind.AIRLINE), "could not forget old flights")

    def everything(self) -> list[Shown]:
        return self._read(_ALL, ())

    def last_visit(self, hex_code: str) -> Shown | None:
        rows = self._read(_LAST, (hex_code,))
        return rows[0] if rows else None

    def _read(self, statement: str, values: Any) -> list[Shown]:
        try:
            with closing(self._connect()) as db:
                db.row_factory = sqlite3.Row
                rows = db.execute(statement, values).fetchall()
        except sqlite3.Error as error:
            self._logger.warning("could not read the history: %s", error)
            return []
        return [_row(row) for row in rows]

    def _write(self, statement: str, values: Any, failure: str) -> None:
        try:
            with closing(self._connect()) as db, db:
                db.execute(statement, values)
        except sqlite3.Error as error:
            self._logger.warning("%s: %s", failure, error)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path)
        try:
            db.execute(_TABLE)
            db.execute(_INDEX)
            if (_SEEN_COLUMN,) not in db.execute(_TABLE_COLUMNS).fetchall():
                db.execute(_ADD_SEEN)
        except sqlite3.Error:
            db.close()
            raise
        return db


class Forgetting:
    """Keeps planes in a store, and each time forgets the airline flights older than kept, so
    the history never outgrows the Pi."""

    def __init__(self, store: ForgettableStore, kept: timedelta, clock: Clock) -> None:
        self._store = store
        self._kept = kept
        self._clock = clock

    def keep(self, shown: Shown) -> None:
        self._store.keep(shown)
        self._store.forget_airlines_before(self._clock.now() - self._kept)

    def everything(self) -> list[Shown]:
        return self._store.everything()

    def last_visit(self, hex_code: str) -> Shown | None:
        return self._store.last_visit(hex_code)


def _row(row: sqlite3.Row) -> Shown:
    """A kept plane, with one kept before seen_at existed last seen when it took the card."""
    fields = dict(row)
    return Shown(**{**fields, _SEEN_COLUMN: fields[_SEEN_COLUMN] or fields["shown_at"]})


class ShownHistory:
    """Sits beside the real displays and keeps each visit a plane makes, once. It is written
    down as soon as it takes the card, and again once it gives the card up, with the closest it
    came, the lowest it flew and when it was last seen. A plane that takes the card back within
    same_visit of last being seen, because another plane had the top spot for a moment, the card
    cleared and came back, or the watcher restarted, carries on the visit it already has rather
    than starting another. The visit is looked up in the store, so it survives a restart.
    Draws nothing itself."""

    def __init__(self, store: Visits, clock: Clock, same_visit: timedelta) -> None:
        self._store = store
        self._clock = clock
        self._same_visit = same_visit
        self._showing: Shown | None = None

    def show(self, message: dict[str, Any]) -> bool:
        cards = message.get("planes") or []
        if message.get("type") != PLANES or not cards:
            return False
        card = cards[0]
        if self._showing is not None and self._showing.hex == card["hex"]:
            self._showing = _closer(self._showing, card)
            return False
        self._finish()
        now = self._clock.now()
        earlier = self._store.last_visit(card["hex"])
        if earlier is not None and now - datetime.fromisoformat(earlier.seen_at) <= self._same_visit:
            self._showing = self._write(_closer(earlier, card), now)
        else:
            self._showing = self._write(_shown(card, now), now)
        return False

    def clear(self) -> None:
        self._finish()

    def _finish(self) -> None:
        if self._showing is not None:
            self._write(self._showing, self._clock.now())
        self._showing = None

    def _write(self, shown: Shown, seen: datetime) -> Shown:
        seen_now = replace(shown, seen_at=_stamp(seen))
        self._store.keep(seen_now)
        return seen_now


def _shown(card: dict[str, Any], now: datetime) -> Shown:
    emergency = card.get("emergency")
    return Shown(
        hex=card["hex"],
        shown_at=_stamp(now),
        kind=_kind(card),
        callsign=card.get("callsign"),
        flight_number=card.get("flightNumber"),
        registration=card.get("registration"),
        aircraft=card.get("aircraft"),
        type_code=card.get("typeCode"),
        airline=card.get("airline"),
        origin=_place(card.get("origin")),
        destination=_place(card.get("destination")),
        owner=card.get("owner"),
        owner_category=card.get("ownerCategory"),
        emergency=emergency.get("label") if emergency else None,
        closest_km=card["distanceKm"],
        lowest_ft=card.get("altitudeFt"),
        seen_at=_stamp(now),
    )


def _stamp(moment: datetime) -> str:
    """In UTC, so the newest sorts first across a change of the clocks."""
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _kind(card: dict[str, Any]) -> Kind:
    """A service or military plane is that. One with an airline, or flying under an airline
    callsign when its route could not be looked up, is an airline flight, unless it is a famous
    owner's; that, and anything flying under its registration, is private."""
    service = SERVICE_KINDS.get(card.get("service") or "")
    if service:
        return service
    if card.get("military"):
        return Kind.MILITARY
    if (card.get("airline") or card.get("airlineCode")) and not card.get("owner"):
        return Kind.AIRLINE
    return Kind.PRIVATE_HELICOPTER if card.get("helicopter") else Kind.PRIVATE_PLANE


def _closer(shown: Shown, card: dict[str, Any]) -> Shown:
    heights = [a for a in (shown.lowest_ft, card.get("altitudeFt")) if a is not None]
    return replace(shown, closest_km=min(shown.closest_km, card["distanceKm"]), lowest_ft=min(heights) if heights else None)


def _place(airport: dict[str, Any] | None) -> str | None:
    """Where a flight is from or going, as the card names it: "Alicante (ALC)"."""
    if not airport:
        return None
    name = airport.get("city") or airport.get("name")
    code = airport.get("code")
    return f"{name} ({code})" if name and code else name or code


class HistoryPage:
    """The whole history for the live server, newest first, for the page to filter."""

    def __init__(self, store: ShownStore) -> None:
        self._store = store

    def latest(self) -> dict[str, Any]:
        return {"shown": [asdict(s) for s in self._store.everything()]}
