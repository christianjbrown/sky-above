"""Which followed flight is on now, kept up to date without asking FlightAware too often.

A flight comes on lead before it is due to leave and goes tail after it reaches the
gate. FlightAware is asked again more often as it gets close to leaving, and the
plane's earlier legs are watched until it has set off, since a late inbound plane is
the usual reason for a late departure. In the air its position comes from our own
receiver when it is in range, and otherwise from FlightAware every few minutes."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flights_watcher.aircraft import Aircraft
from flights_watcher.clock import Clock
from flights_watcher.followed_list import FollowedEntry, FollowedList
from flights_watcher.lookups import LookupFailed
from flights_watcher.schedules import Flight, FlightSchedules, Position

# How many legs back to look for the reason a plane is late.
EARLIER_LEGS = 2


@dataclass(frozen=True)
class FollowTiming:
    """How long a flight shows for around its own times, and how often each thing is
    asked again, in seconds."""

    lead: timedelta
    tail: timedelta
    before_showing_every: float
    hours_to_go_every: float
    last_hour_every: float
    under_way_every: float
    earlier_leg_every: float
    position_every: float
    not_found_every: float


@dataclass(frozen=True)
class Estimate:
    """Our own sums for the plane flying a followed flight: when it should get in from its
    last leg, the turnaround it needs, and so the earliest it can leave again."""

    inbound_arrives: datetime
    turnaround: timedelta
    ready: datetime


@dataclass(frozen=True)
class Followed:
    flight: Flight
    # The leg the plane flies in on first, then the one before that.
    earlier_legs: list[Flight]
    position: Position | None
    estimate: Estimate | None = None


class _Kept[T]:
    """An answer and when it was last asked for."""

    def __init__(self, value: T | None, asked_at: float) -> None:
        self.value = value
        self.asked_at = asked_at


class FollowedFlights:
    def __init__(
        self,
        followed: FollowedList,
        schedules: FlightSchedules,
        timing: FollowTiming,
        clock: Clock,
        logger: logging.Logger,
    ) -> None:
        self._followed = followed
        self._schedules = schedules
        self._timing = timing
        self._clock = clock
        self._logger = logger
        self._flights: dict[FollowedEntry, _Kept[Flight]] = {}
        self._legs: dict[str, _Kept[Flight]] = {}
        self._positions: dict[str, _Kept[Position]] = {}

    def current(self, aircraft: Sequence[Aircraft]) -> Followed | None:
        """The followed flight on now, the soonest to leave if two overlap."""
        now = self._clock.now()
        on = [
            flight
            for entry in self._followed.entries()
            if abs((entry.day - now.date()).days) <= 1
            for flight in [self._flight(entry, now)]
            if flight is not None and self._showing(flight, now)
        ]
        if not on:
            return None
        flight = min(on, key=lambda f: f.departs_at or now)
        return Followed(flight, self._earlier_legs(flight), self._position(flight, aircraft, now))

    def _showing(self, flight: Flight, now: datetime) -> bool:
        times = [t for t in (flight.scheduled_out, flight.departs_at) if t is not None]
        if not times:
            return False
        ends = flight.scheduled_out if flight.cancelled else flight.arrives_at
        return min(times) - self._timing.lead <= now <= (ends or max(times)) + self._timing.tail

    def _flight(self, entry: FollowedEntry, now: datetime) -> Flight | None:
        kept = self._flights.get(entry)
        if kept is not None and self._clock.monotonic() - kept.asked_at < self._every(kept.value, now):
            return kept.value
        known = kept.value if kept else None
        fresh = self._ask(
            lambda: self._schedules.flight(known.fa_flight_id) if known else _on_day(self._schedules.flights(entry.ident), entry.day),
            f"{entry.ident} on {entry.day}",
        )
        self._flights[entry] = _Kept(fresh.value if fresh.value is not None else known, fresh.asked_at)
        return self._flights[entry].value

    def _every(self, flight: Flight | None, now: datetime) -> float:
        timing = self._timing
        if flight is None:
            return timing.not_found_every
        if not self._showing(flight, now):
            return timing.before_showing_every
        if flight.actual_out is not None or flight.cancelled:
            return timing.under_way_every
        departs = flight.departs_at
        if departs is not None and departs - now > timedelta(hours=1):
            return timing.hours_to_go_every
        return timing.last_hour_every

    def _earlier_legs(self, flight: Flight) -> list[Flight]:
        """Only until the plane sets off: after that its earlier legs no longer matter."""
        legs: list[Flight] = []
        leg_id = None if flight.actual_out else flight.inbound_id
        while leg_id and len(legs) < EARLIER_LEGS:
            leg = self._leg(leg_id)
            if leg is None:
                break
            legs.append(leg)
            leg_id = None if leg.actual_out else leg.inbound_id
        return legs

    def _leg(self, fa_flight_id: str) -> Flight | None:
        kept = self._legs.get(fa_flight_id)
        finished = kept is not None and kept.value is not None and kept.value.actual_in is not None
        if kept is not None and (finished or self._clock.monotonic() - kept.asked_at < self._timing.earlier_leg_every):
            return kept.value
        fresh = self._ask(lambda: self._schedules.flight(fa_flight_id), f"earlier leg {fa_flight_id}")
        self._legs[fa_flight_id] = _Kept(fresh.value or (kept.value if kept else None), fresh.asked_at)
        return self._legs[fa_flight_id].value

    def _position(self, flight: Flight, aircraft: Sequence[Aircraft], now: datetime) -> Position | None:
        """Where the plane is in the air. Our own receiver can see it take off before
        FlightAware is next asked, so once the plane has left the gate it counts too; before
        that, the same plane in the air is still flying in on its earlier leg."""
        if flight.actual_out is None or flight.actual_on is not None:
            return None
        ours = _ours(flight.registration, aircraft, now)
        if ours is not None:
            return ours
        if not flight.airborne:
            return None
        kept = self._positions.get(flight.fa_flight_id)
        if kept is not None and self._clock.monotonic() - kept.asked_at < self._timing.position_every:
            return kept.value
        fresh = self._ask(lambda: self._schedules.position(flight.fa_flight_id), f"position of {flight.ident}")
        self._positions[flight.fa_flight_id] = _Kept(fresh.value or (kept.value if kept else None), fresh.asked_at)
        return self._positions[flight.fa_flight_id].value

    def _ask[T](self, question: Callable[[], T | None], about: str) -> _Kept[T]:
        """Asks, noting the time either way, so a failure waits its turn like an answer does."""
        asked_at = self._clock.monotonic()
        try:
            return _Kept(question(), asked_at)
        except LookupFailed as error:
            self._logger.warning("could not look up %s: %s", about, error)
            return _Kept(None, asked_at)


def _on_day(flights: list[Flight], day: date) -> Flight | None:
    """The one due to leave on day, in the time where it leaves from."""
    return next((f for f in flights if f.scheduled_out is not None and _local_day(f.scheduled_out, f.origin_timezone) == day), None)


def _local_day(departs: datetime, timezone: str | None) -> date:
    try:
        zone = ZoneInfo(timezone) if timezone else UTC
    except ZoneInfoNotFoundError:
        zone = UTC
    return departs.astimezone(zone).date()


def _ours(registration: str | None, aircraft: Sequence[Aircraft], now: datetime) -> Position | None:
    """Where our own receiver puts the plane in the air, if it is in range: fresher than
    FlightAware, and free."""
    if not registration:
        return None
    wanted = registration.replace("-", "").upper()
    for plane in aircraft:
        if plane.on_ground or plane.location is None:
            continue
        if (plane.registration or "").replace("-", "").upper() == wanted:
            return Position(plane.location.lat, plane.location.lon, plane.track_deg, plane.altitude_ft, plane.ground_speed_kt, now)
    return None
