"""A record of every plane that gets the card, kept on the Pi, so what flew over can be
looked back on: when, which flight, where it was going, how close it came, and who the
famous ones belong to.

It never leaves the Pi, apart from the page on the home network that reads it back."""

import logging
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from flights_watcher.clock import Clock

# The only message that puts a plane on screen; standby and clear do not.
PLANES = "planes"


@dataclass(frozen=True)
class Shown:
    """One plane's time on the card, from when it took the screen."""

    hex: str
    shown_at: str
    callsign: str | None
    flight_number: str | None
    registration: str | None
    aircraft: str | None
    type_code: str | None
    airline: str | None
    service: str | None
    origin: str | None
    destination: str | None
    owner: str | None
    owner_category: str | None
    emergency: str | None
    closest_km: float
    lowest_ft: int | None


_COLUMNS = (
    "hex, shown_at, callsign, flight_number, registration, aircraft, type_code, airline, service, "
    "origin, destination, owner, owner_category, emergency, closest_km, lowest_ft"
)
_KEEP = (
    f"INSERT OR REPLACE INTO shown ({_COLUMNS}) VALUES (:hex, :shown_at, :callsign, :flight_number, :registration, "  # noqa: S608
    ":aircraft, :type_code, :airline, :service, :origin, :destination, :owner, :owner_category, :emergency, "
    ":closest_km, :lowest_ft)"
)
_RECENT = f"SELECT {_COLUMNS} FROM shown ORDER BY shown_at DESC LIMIT ?"  # noqa: S608 - no outside input
_FAMOUS = f"SELECT {_COLUMNS} FROM shown WHERE owner IS NOT NULL ORDER BY shown_at DESC LIMIT ?"  # noqa: S608 - no outside input


class ShownStore(Protocol):
    def keep(self, shown: Shown) -> None:
        """Adds a plane's time on the card, or replaces what was kept for it so far."""
        ...

    def recent(self, limit: int) -> list[Shown]:
        """The latest planes shown, newest first."""
        ...

    def famous(self, limit: int) -> list[Shown]:
        """The latest planes shown that belong to somebody famous, newest first."""
        ...


class SqliteShownStore:
    """The history in an SQLite file in STATE_DIR. A broken database is logged and treated
    as empty, so it never stops the card."""

    def __init__(self, path: str, logger: logging.Logger) -> None:
        self._path = path
        self._logger = logger

    def keep(self, shown: Shown) -> None:
        try:
            with closing(self._connect()) as db, db:
                db.execute(_KEEP, asdict(shown))
        except sqlite3.Error as error:
            self._logger.warning("could not keep %s in the history: %s", shown.hex, error)

    def recent(self, limit: int) -> list[Shown]:
        return self._select(_RECENT, limit)

    def famous(self, limit: int) -> list[Shown]:
        return self._select(_FAMOUS, limit)

    def _select(self, query: str, limit: int) -> list[Shown]:
        try:
            with closing(self._connect()) as db:
                rows = db.execute(query, (limit,)).fetchall()
        except sqlite3.Error as error:
            self._logger.warning("could not read the history: %s", error)
            return []
        return [Shown(*row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path)
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS shown ("
                "hex TEXT NOT NULL, shown_at TEXT NOT NULL, callsign TEXT, flight_number TEXT, registration TEXT, "
                "aircraft TEXT, type_code TEXT, airline TEXT, service TEXT, origin TEXT, destination TEXT, "
                "owner TEXT, owner_category TEXT, emergency TEXT, closest_km REAL NOT NULL, lowest_ft INTEGER, "
                "PRIMARY KEY (hex, shown_at))"
            )
            db.execute("CREATE INDEX IF NOT EXISTS shown_owner ON shown (owner, shown_at)")
        except sqlite3.Error:
            db.close()
            raise
        return db


class ShownHistory:
    """Sits beside the real displays and keeps each plane that takes the card, once for each
    time it does. It is written down as soon as it is shown, and again once it gives the card
    up, with the closest it came and the lowest it flew while it had it. Draws nothing itself."""

    def __init__(self, store: ShownStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock
        self._showing: Shown | None = None
        self._written: Shown | None = None

    def show(self, message: dict[str, Any]) -> bool:
        cards = message.get("planes") or []
        if message.get("type") != PLANES or not cards:
            return False
        card = cards[0]
        if self._showing is not None and self._showing.hex == card["hex"]:
            self._showing = _closer(self._showing, card)
        else:
            self._finish()
            self._showing = self._write(_shown(card, self._clock.now()))
        return False

    def clear(self) -> None:
        self._finish()

    def _finish(self) -> None:
        if self._showing is not None and self._showing != self._written:
            self._write(self._showing)
        self._showing = self._written = None

    def _write(self, shown: Shown) -> Shown:
        self._store.keep(shown)
        self._written = shown
        return shown


def _shown(card: dict[str, Any], now: datetime) -> Shown:
    emergency = card.get("emergency")
    return Shown(
        hex=card["hex"],
        # In UTC, so the newest sorts first across a change of the clocks.
        shown_at=now.astimezone(UTC).isoformat(timespec="seconds"),
        callsign=card.get("callsign"),
        flight_number=card.get("flightNumber"),
        registration=card.get("registration"),
        aircraft=card.get("aircraft"),
        type_code=card.get("typeCode"),
        airline=card.get("airline"),
        service=card.get("service"),
        origin=_place(card.get("origin")),
        destination=_place(card.get("destination")),
        owner=card.get("owner"),
        owner_category=card.get("ownerCategory"),
        emergency=emergency.get("label") if emergency else None,
        closest_km=card["distanceKm"],
        lowest_ft=card.get("altitudeFt"),
    )


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
    """The history for the live server: the latest planes shown, and the latest famous ones."""

    def __init__(self, store: ShownStore, recent: int, famous: int) -> None:
        self._store = store
        self._recent = recent
        self._famous = famous

    def latest(self) -> dict[str, Any]:
        return {"recent": _rows(self._store.recent(self._recent)), "famous": _rows(self._store.famous(self._famous))}


def _rows(shown: Sequence[Shown]) -> list[dict[str, Any]]:
    return [asdict(s) for s in shown]
