"""The message for a followed flight's card: where it is up to, its times, gates and
belt, and why it is late when the plane's earlier legs say so.

Times go out in UTC; the page shows them in UK time and, where it differs, the time
at the other end, and counts down to them itself. Before take-off the departure is the
later of the airline's and our own estimate from the plane's earlier legs, and the
landing moves with it."""

import logging
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from flights_watcher.following import Followed
from flights_watcher.lookups import Airport, AirportTidier, LookupFailed
from flights_watcher.schedules import Flight, Position


class OperatorNames(Protocol):
    def name(self, icao: str) -> str | None:
        """Raises LookupFailed."""
        ...


class FollowedCardBuilder:
    """late_minutes is how far behind its timetable a leg has to be to count as late."""

    def __init__(
        self,
        home_timezone: str,
        tidiers: Sequence[AirportTidier],
        operators: OperatorNames,
        late_minutes: int,
        logger: logging.Logger,
    ) -> None:
        self._home_timezone = home_timezone
        self._tidiers = tidiers
        self._operators = operators
        self._late_minutes = late_minutes
        self._logger = logger

    def build(self, followed: Followed) -> dict[str, Any]:
        flight = followed.flight
        later = _later_by(followed)
        departs = _plus(flight.departs_at, later)
        arrives = _plus(flight.arrives_at, later)
        return {
            "type": "followed",
            "homeTimezone": self._home_timezone,
            "flight": {
                "ident": flight.ident,
                "airline": self._airline(flight.operator),
                "airlineCode": flight.operator,
                "phase": _phase(followed),
                "status": flight.status,
                "diverted": flight.diverted,
                "origin": self._airport(flight.origin, flight.origin_timezone),
                "destination": self._airport(flight.destination, flight.destination_timezone),
                "scheduledOut": _iso(flight.scheduled_out),
                "departsAt": _iso(departs),
                "airlineDepartsAt": _iso(flight.departs_at),
                "departureEstimate": "ours" if later else "airline",
                "actualOff": _iso(flight.actual_off),
                "landsAt": _iso(_plus(flight.lands_at, later)),
                "scheduledIn": _iso(flight.scheduled_in),
                "arrivesAt": _iso(arrives),
                "departureDelayMinutes": _minutes_late(departs, flight.scheduled_out),
                "arrivalDelayMinutes": _minutes_late(arrives, flight.scheduled_in),
                "gateOrigin": flight.gate_origin,
                "terminalOrigin": flight.terminal_origin,
                "gateDestination": flight.gate_destination,
                "terminalDestination": flight.terminal_destination,
                "baggageClaim": flight.baggage_claim,
                "registration": flight.registration,
                "aircraftType": flight.aircraft_type,
            },
            "earlierLegs": [self._leg(leg) for leg in followed.earlier_legs],
            "reason": self._our_reason(followed, departs) if later else self._reason(followed),
            "position": _position(followed.position),
        }

    def _airline(self, operator: str | None) -> str | None:
        if not operator:
            return None
        try:
            return self._operators.name(operator)
        except LookupFailed as error:
            self._logger.warning("could not name operator %s: %s", operator, error)
            return None

    def _airport(self, airport: Airport | None, zone: str | None) -> dict[str, Any] | None:
        tidied = self._tidy(airport)
        return {**asdict(tidied), "timezone": zone} if tidied else None

    def _tidy(self, airport: Airport | None) -> Airport | None:
        if airport is None:
            return None
        for tidier in self._tidiers:
            airport = tidier.tidy(airport)
        return airport

    def _city(self, leg: Flight) -> str:
        origin = self._tidy(leg.origin)
        return (origin.city or origin.name or origin.code or "its last stop") if origin else "its last stop"

    def _leg(self, leg: Flight) -> dict[str, Any]:
        return {
            "ident": leg.ident,
            "origin": self._airport(leg.origin, leg.origin_timezone),
            "departed": leg.actual_out is not None,
            "departsAt": _iso(leg.departs_at),
            "landed": leg.actual_in is not None,
            "arrivesAt": _iso(leg.arrives_at),
            "arrivalDelayMinutes": _minutes_late(leg.arrives_at, leg.scheduled_in),
        }

    def _our_reason(self, followed: Followed, departs: datetime | None) -> str | None:
        """Why our sums say it will be late: when its plane gets in, too late to turn round in time."""
        estimate, flight = followed.estimate, followed.flight
        if estimate is None or (_minutes_late(departs, flight.scheduled_out) or 0) < self._late_minutes:
            return None
        arrives = estimate.inbound_arrives.astimezone(ZoneInfo(self._home_timezone)).strftime("%H:%M")
        return f"Its plane isn't due in from {self._city(followed.earlier_legs[0])} until {arrives}"

    def _reason(self, followed: Followed) -> str | None:
        """Blames the plane coming in late, when it is, as far back as the lateness goes."""
        flight = followed.flight
        if flight.cancelled or (_minutes_late(flight.departs_at, flight.scheduled_out) or 0) < self._late_minutes:
            return None
        late = [leg for leg in followed.earlier_legs if (_minutes_late(leg.arrives_at, leg.scheduled_in) or 0) >= self._late_minutes]
        if not late or late[0] is not followed.earlier_legs[0]:
            return None
        reason = f"The plane is running late coming in from {self._city(late[0])}"
        if len(late) > 1 and late[1] is followed.earlier_legs[1]:
            reason += f", after a late start from {self._city(late[1])}"
        return reason


def _later_by(followed: Followed) -> timedelta | None:
    """How much later than the airline's time our own estimate has it leaving, if it does."""
    official, estimate = followed.flight.departs_at, followed.estimate
    if estimate is None or official is None or estimate.ready - official < timedelta(minutes=1):
        return None
    return estimate.ready - official


def _plus(moment: datetime | None, later: timedelta | None) -> datetime | None:
    return moment + later if moment is not None and later else moment


def _phase(followed: Followed) -> str:
    flight = followed.flight
    if flight.cancelled:
        return "cancelled"
    if flight.actual_in is not None:
        return "arrived"
    if flight.actual_on is not None:
        return "landed"
    # A position before FlightAware has the take-off is our own receiver seeing it in the air.
    if flight.actual_off is not None or (flight.actual_out is not None and followed.position is not None):
        return "flying"
    if flight.actual_out is not None:
        return "taxiing"
    return "waiting"


def _minutes_late(expected: datetime | None, timetabled: datetime | None) -> int | None:
    if expected is None or timetabled is None:
        return None
    return round((expected - timetabled).total_seconds() / 60)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z") if moment else None


def _position(position: Position | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "lat": round(position.lat, 5),
        "lon": round(position.lon, 5),
        "trackDeg": position.track_deg,
        "altitudeFt": position.altitude_ft,
        "speedKt": position.speed_kt,
        "at": _iso(position.at),
    }
