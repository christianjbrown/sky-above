"""One look at the sky: cast a plane in an emergency if the antenna hears one, else what
is overhead, then once it has gone, whatever is on standby (a followed flight), or hand
the screen back."""

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.clock import Clock
from flights_watcher.display import Display
from flights_watcher.sources import AircraftSource
from flights_watcher.zone import Sighting


class SightingFinder(Protocol):
    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]: ...


class MessageBuilder(Protocol):
    def build(self, sightings: list[Sighting], aircraft: Iterable[Aircraft]) -> dict[str, Any]: ...


class Schedule(Protocol):
    def is_quiet(self, now: datetime) -> bool: ...


class GracePeriod(Protocol):
    def seen(self, nearest: str) -> None: ...

    def expired(self) -> bool: ...

    def reset(self) -> None: ...


class Standby(Protocol):
    def message(self, aircraft: Sequence[Aircraft]) -> dict[str, Any] | None:
        """What to show while no plane is overhead, or None for nothing."""
        ...


class Emergency(Protocol):
    def message(self, aircraft: Sequence[Aircraft]) -> dict[str, Any] | None:
        """The card for planes in an emergency, however far away, or None while there are none."""
        ...


class RareAircraft(Protocol):
    def includes_aircraft(self, plane: Aircraft) -> bool: ...


class SightingObserver(Protocol):
    def note(self, sightings: list[Sighting]) -> None: ...


class ArrivalLog:
    """Logs each plane once as it comes into the zone."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._present: set[str] = set()

    def note(self, sightings: list[Sighting]) -> None:
        current = {s.aircraft.hex for s in sightings}
        for sighting in sightings:
            if sighting.aircraft.hex not in self._present:
                plane = sighting.aircraft
                self._logger.info(
                    "%s overhead: %.1f km away at %s ft",
                    plane.callsign or plane.hex,
                    sighting.distance_km,
                    plane.altitude_ft,
                )
        self._present = current


class Watcher:
    def __init__(
        self,
        source: AircraftSource,
        zone: SightingFinder,
        messages: MessageBuilder,
        display: Display,
        quiet_hours: Schedule,
        linger: GracePeriod,
        arrivals: SightingObserver,
        clock: Clock,
        standby: Standby,
        rare: RareAircraft,
        due_seconds: float,
        surroundings: SightingFinder,
        emergencies: Emergency,
    ) -> None:
        self._source = source
        self._zone = zone
        self._messages = messages
        self._display = display
        self._quiet_hours = quiet_hours
        self._linger = linger
        self._arrivals = arrivals
        self._clock = clock
        self._standby = standby
        self._rare = rare
        self._due_seconds = due_seconds
        self._surroundings = surroundings
        self._emergencies = emergencies
        # "emergency", "planes", "standby" or None for nothing of ours on screen.
        self._showing: str | None = None
        # The plane at the top of the card.
        self._current: str | None = None

    def tick(self) -> None:
        quiet = self._quiet_hours.is_quiet(self._clock.now())
        heard = self._source.aircraft()
        # In quiet hours only the rare kinds, such as helicopters, get a card.
        aircraft = [plane for plane in heard if not quiet or self._rare.includes_aircraft(plane)]
        # Looked for every time, even under an emergency, as finding them learns from each look.
        sightings = self._zone.sightings(aircraft)
        self._arrivals.note([sighting for sighting in sightings if not sighting.afar])
        # An emergency goes before anything else, at any hour, wherever the plane is.
        emergency = self._emergencies.message(heard)
        if emergency is not None:
            self._display.show(emergency)
            self._showing, self._current = "emergency", None
            self._linger.reset()
            return
        if sightings and not self._waits_its_turn(sightings):
            self._current = sightings[0].aircraft.hex
            self._linger.seen(self._current)
            self._display.show(self._messages.build(sightings, aircraft))
            self._showing = "planes"
            return
        if self._showing == "planes":
            if not self._linger.expired():
                self._follow_leaving(aircraft)
                return
            self._linger.reset()
        waiting = None if quiet else self._standby.message(aircraft)
        if waiting is not None:
            self._display.show(waiting)
            self._showing = "standby"
        elif self._showing is not None:
            self._display.clear()
            self._showing = None

    def _follow_leaving(self, aircraft: list[Aircraft]) -> None:
        """Keeps the card moving with the plane that has just left, while its time is up."""
        leaving = [s for s in self._surroundings.sightings(aircraft) if s.aircraft.hex == self._current]
        if leaving:
            self._display.show(self._messages.build(leaving, aircraft))

    def _waits_its_turn(self, sightings: list[Sighting]) -> bool:
        """A plane only on its way, or one far off, while the card is still showing one that
        has just left, waits until that card's time is up. One in the zone takes over straight
        away, and so does one due overhead within due_seconds, which would be gone before its
        turn came."""
        top = sightings[0]
        gone = self._current not in {s.aircraft.hex for s in sightings}
        due = top.overhead_in_seconds is not None and top.overhead_in_seconds <= self._due_seconds
        waits = (top.approaching and not due) or top.afar
        return self._showing == "planes" and waits and gone and not self._linger.expired()
