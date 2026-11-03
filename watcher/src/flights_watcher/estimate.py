"""Our own guess at when a followed flight can leave, from the plane flying it.

Airlines are slow to admit a delay: the board says on time until the inbound plane is
plainly not going to make it. So we work it out ourselves, leg by leg along the plane's
day. Each earlier leg leaves when it is due, or when its plane is ready if that is later,
takes as long as that flight has actually taken on recent days, and then needs a turn
round before the plane can go again. The card shows whichever of ours and the airline's
is later."""

import logging
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.clock import Clock
from flights_watcher.following import Estimate, Followed
from flights_watcher.lookups import LookupFailed
from flights_watcher.schedules import Flight, FlightSchedules
from flights_watcher.standby import CurrentFlight


class BlockTimes(Protocol):
    def typical(self, ident: str) -> timedelta | None:
        """How long the flight number typically takes from gate to gate."""
        ...


class Turnarounds(Protocol):
    def shortest(self, aircraft_type: str | None) -> timedelta:
        """The least time a plane of the type needs between arriving and leaving again."""
        ...


@dataclass(frozen=True)
class TurnaroundRule:
    # ICAO type designators starting with any of these, such as "B77" for every 777.
    type_prefixes: tuple[str, ...]
    turnaround: timedelta


class TurnaroundsByType:
    """The first rule whose prefixes match the type, or the default for anything else."""

    def __init__(self, rules: Sequence[TurnaroundRule], default: timedelta) -> None:
        self._rules = rules
        self._default = default

    def shortest(self, aircraft_type: str | None) -> timedelta:
        kind = (aircraft_type or "").upper()
        for rule in self._rules:
            if kind and kind.startswith(rule.type_prefixes):
                return rule.turnaround
        return self._default


class RecentBlockTimes:
    """The middle of the gate-to-gate times the flight number has actually flown in the
    last week or so. AeroAPI hands those back with the flight list anyway, so it costs one
    lookup per flight number, kept for keep_for seconds."""

    def __init__(self, schedules: FlightSchedules, keep_for: float, clock: Clock, logger: logging.Logger) -> None:
        self._schedules = schedules
        self._keep_for = keep_for
        self._clock = clock
        self._logger = logger
        self._kept: dict[str, tuple[timedelta | None, float]] = {}

    def typical(self, ident: str) -> timedelta | None:
        kept = self._kept.get(ident)
        if kept is not None and self._clock.monotonic() - kept[1] < self._keep_for:
            return kept[0]
        asked_at = self._clock.monotonic()
        try:
            flown = [
                f.actual_in - f.actual_out
                for f in self._schedules.flights(ident)
                if f.actual_out is not None and f.actual_in is not None and f.actual_in > f.actual_out
            ]
        except LookupFailed as error:
            # Waits its turn like an answer, keeping whatever was known before.
            self._logger.warning("could not look up recent %s flights: %s", ident, error)
            self._kept[ident] = (kept[0] if kept else None, asked_at)
            return self._kept[ident][0]
        typical = timedelta(seconds=statistics.median(d.total_seconds() for d in flown)) if flown else None
        self._kept[ident] = (typical, asked_at)
        return typical


class DepartureEstimator:
    def __init__(self, block_times: BlockTimes, turnarounds: Turnarounds, clock: Clock) -> None:
        self._block_times = block_times
        self._turnarounds = turnarounds
        self._clock = clock

    def estimate(self, followed: Followed) -> Estimate | None:
        """None once the plane has left, or with no earlier leg to go on."""
        flight = followed.flight
        if flight.actual_out is not None or flight.cancelled or not followed.earlier_legs:
            return None
        estimate: Estimate | None = None
        # Oldest leg first, each one's ready time holding up the next.
        for leg in reversed(followed.earlier_legs):
            arrives = self._arrives(leg, estimate.ready if estimate else None)
            if arrives is None:
                return None
            turnaround = self._turnarounds.shortest(leg.aircraft_type or flight.aircraft_type)
            estimate = Estimate(inbound_arrives=arrives, turnaround=turnaround, ready=arrives + turnaround)
        return estimate

    def _arrives(self, leg: Flight, ready: datetime | None) -> datetime | None:
        if leg.actual_in is not None:
            return leg.actual_in
        if leg.actual_out is not None:
            # In the air FlightAware's own arrival time already follows where it is.
            if leg.estimated_in is not None:
                return leg.estimated_in
            block = self._block(leg)
            return leg.actual_out + block if block else leg.arrives_at
        # Still to go: when it is due, unless its plane is not ready yet or it is already late.
        leaves = max(t for t in (leg.departs_at, ready, self._clock.now()) if t is not None)
        block = self._block(leg)
        return leaves + block if block else leg.arrives_at

    def _block(self, leg: Flight) -> timedelta | None:
        typical = self._block_times.typical(leg.ident)
        if typical is not None:
            return typical
        if leg.scheduled_out is not None and leg.scheduled_in is not None:
            return leg.scheduled_in - leg.scheduled_out
        return None


class EstimatedFollowedFlights:
    """The followed flight on now, with our own estimate of when its plane is ready."""

    def __init__(self, flights: CurrentFlight, estimator: DepartureEstimator) -> None:
        self._flights = flights
        self._estimator = estimator

    def current(self, aircraft: Sequence[Aircraft]) -> Followed | None:
        followed = self._flights.current(aircraft)
        if followed is None:
            return None
        return replace(followed, estimate=self._estimator.estimate(followed))
