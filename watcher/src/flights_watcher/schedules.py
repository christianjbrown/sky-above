"""Where a particular flight is up to, from FlightAware's AeroAPI: its times, gates,
baggage belt, the plane flying it and the leg that plane flies in on first."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote

from flights_watcher.flightaware import aeroapi_airport, aeroapi_get
from flights_watcher.http import JsonHttp
from flights_watcher.lookups import Airport


@dataclass(frozen=True)
class Flight:
    fa_flight_id: str
    ident: str
    operator: str | None
    origin: Airport | None
    destination: Airport | None
    origin_timezone: str | None
    destination_timezone: str | None
    scheduled_out: datetime | None
    estimated_out: datetime | None
    actual_out: datetime | None
    actual_off: datetime | None
    estimated_on: datetime | None
    actual_on: datetime | None
    scheduled_in: datetime | None
    estimated_in: datetime | None
    actual_in: datetime | None
    gate_origin: str | None
    terminal_origin: str | None
    gate_destination: str | None
    terminal_destination: str | None
    baggage_claim: str | None
    status: str | None
    cancelled: bool
    diverted: bool
    registration: str | None
    aircraft_type: str | None
    inbound_id: str | None

    @property
    def departs_at(self) -> datetime | None:
        """When it leaves the gate, as best known: actual, then expected, then timetabled."""
        return self.actual_out or self.estimated_out or self.scheduled_out

    @property
    def arrives_at(self) -> datetime | None:
        return self.actual_in or self.estimated_in or self.scheduled_in

    @property
    def lands_at(self) -> datetime | None:
        return self.actual_on or self.estimated_on

    @property
    def airborne(self) -> bool:
        return self.actual_off is not None and self.actual_on is None


@dataclass(frozen=True)
class Position:
    lat: float
    lon: float
    track_deg: float | None
    altitude_ft: int | None
    speed_kt: float | None
    at: datetime | None


class FlightSchedules(Protocol):
    def flights(self, ident: str) -> list[Flight]:
        """Recent and upcoming flights under a flight number, a couple of days either way. Raises LookupFailed."""
        ...

    def flight(self, fa_flight_id: str) -> Flight | None:
        """Raises LookupFailed."""
        ...

    def position(self, fa_flight_id: str) -> Position | None:
        """Raises LookupFailed."""
        ...


class AeroApiSchedules:
    def __init__(self, base_url: str, http: JsonHttp) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

    def flights(self, ident: str) -> list[Flight]:
        return self._flights(f"/flights/{quote(ident)}?max_pages=1")

    def flight(self, fa_flight_id: str) -> Flight | None:
        return next(iter(self._flights(f"/flights/{quote(fa_flight_id)}?ident_type=fa_flight_id")), None)

    def position(self, fa_flight_id: str) -> Position | None:
        found = aeroapi_get(self._http, f"{self._base_url}/flights/{quote(fa_flight_id)}/position")
        last = found.get("last_position") if isinstance(found, dict) else None
        if not isinstance(last, dict) or last.get("latitude") is None or last.get("longitude") is None:
            return None
        # A plane FlightAware has no position for, such as one taxiing at an airport its
        # feeders cannot see the ground of, comes back at 0, 0.
        if last["latitude"] == 0 and last["longitude"] == 0:
            return None
        altitude = last.get("altitude")
        return Position(
            lat=float(last["latitude"]),
            lon=float(last["longitude"]),
            track_deg=last.get("heading"),
            # AeroAPI gives altitude in hundreds of feet.
            altitude_ft=altitude * 100 if isinstance(altitude, int) else None,
            speed_kt=last.get("groundspeed"),
            at=_time(last.get("timestamp")),
        )

    def _flights(self, path: str) -> list[Flight]:
        found = aeroapi_get(self._http, f"{self._base_url}{path}")
        raw = found.get("flights") if isinstance(found, dict) else None
        return [_flight(item) for item in raw or [] if isinstance(item, dict) and item.get("fa_flight_id")]


def _flight(raw: dict[str, Any]) -> Flight:
    origin, destination = raw.get("origin") or {}, raw.get("destination") or {}
    return Flight(
        fa_flight_id=raw["fa_flight_id"],
        ident=raw.get("ident_iata") or raw.get("ident") or raw["fa_flight_id"],
        operator=raw.get("operator_icao") or raw.get("operator"),
        origin=aeroapi_airport(origin),
        destination=aeroapi_airport(destination),
        origin_timezone=origin.get("timezone") if isinstance(origin, dict) else None,
        destination_timezone=destination.get("timezone") if isinstance(destination, dict) else None,
        scheduled_out=_time(raw.get("scheduled_out")),
        estimated_out=_time(raw.get("estimated_out")),
        actual_out=_time(raw.get("actual_out")),
        actual_off=_time(raw.get("actual_off")),
        estimated_on=_time(raw.get("estimated_on")),
        actual_on=_time(raw.get("actual_on")),
        scheduled_in=_time(raw.get("scheduled_in")),
        estimated_in=_time(raw.get("estimated_in")),
        actual_in=_time(raw.get("actual_in")),
        gate_origin=raw.get("gate_origin"),
        terminal_origin=raw.get("terminal_origin"),
        gate_destination=raw.get("gate_destination"),
        terminal_destination=raw.get("terminal_destination"),
        baggage_claim=raw.get("baggage_claim"),
        status=raw.get("status"),
        cancelled=bool(raw.get("cancelled")),
        diverted=bool(raw.get("diverted")),
        registration=raw.get("registration"),
        aircraft_type=raw.get("aircraft_type"),
        inbound_id=raw.get("inbound_fa_flight_id"),
    )


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
