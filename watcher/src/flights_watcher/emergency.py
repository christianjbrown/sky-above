"""Aircraft in an emergency, wherever the antenna hears them, however far from home.

A crew says so by squawking 7700, 7600 or 7500, and most planes say it again in their
ADS-B emergency status, which readsb passes on as the emergency field. A plane falling
or climbing far faster than any normal flight says it without anyone setting a code.
An emergency takes the screen over everything else, at any hour, until it is over."""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.clock import Clock
from flights_watcher.geo import Location
from flights_watcher.rare import ROTORCRAFT
from flights_watcher.zone import Sighting

# The squawks and the kind of emergency each one means.
SQUAWKS = {"7700": "general", "7600": "nordo", "7500": "unlawful"}
# The emergency statuses that count. A lifeguard flight is only asking for priority, and
# minimum fuel is a warning that it soon may be one, so neither does.
DECLARED_KINDS = ("general", "nordo", "unlawful", "downed")
# What the card calls each kind.
LABELS = {
    "general": "General emergency",
    "nordo": "Radio failure",
    "unlawful": "Unlawful interference",
    "downed": "Aircraft down",
    "descent": "Rapid descent",
    "climb": "Rapid climb",
}
# ADS-B emitter category for high performance aircraft, such as fast jets.
HIGH_PERFORMANCE = "A6"


@dataclass(frozen=True)
class Emergency:
    kind: str
    # The squawk that says so, when there is one.
    squawk: str | None = None

    @property
    def label(self) -> str:
        return LABELS[self.kind]


@dataclass(frozen=True)
class Distress:
    sighting: Sighting
    emergency: Emergency


class EmergencyReader(Protocol):
    def of(self, plane: Aircraft) -> Emergency | None: ...


class DeclaredEmergency:
    """The emergency a plane's crew has declared, by its squawk or its emergency status.
    The status names the kind when both are there."""

    def of(self, plane: Aircraft) -> Emergency | None:
        squawk = plane.squawk if plane.squawk in SQUAWKS else None
        if plane.emergency in DECLARED_KINDS:
            return Emergency(plane.emergency, squawk)
        return Emergency(SQUAWKS[squawk], squawk) if squawk else None


class SteepClimbOrDescent:
    """A plane coming down or going up far faster than any departure or arrival: an
    emergency descent after losing cabin pressure, or one out of control. Helicopters,
    military aircraft and fast jets climb and dive steeply in the normal way of things,
    so they are left out."""

    def __init__(self, descent_fpm: int, climb_fpm: int) -> None:
        self._descent_fpm = descent_fpm
        self._climb_fpm = climb_fpm

    def of(self, plane: Aircraft) -> Emergency | None:
        rate = plane.vertical_rate_fpm
        if rate is None or plane.on_ground or plane.military or plane.category in (ROTORCRAFT, HIGH_PERFORMANCE):
            return None
        if rate <= -self._descent_fpm:
            return Emergency("descent")
        return Emergency("climb") if rate >= self._climb_fpm else None


class Emergencies(Protocol):
    def current(self, aircraft: Sequence[Aircraft]) -> list[Distress]: ...


class HeldEmergencies:
    """The planes in an emergency now, the first to have one first.

    A squawk misread from a weak signal can say 7700 for a single look, and a climb rate
    can jump for one, so a plane only counts once its emergency has held for held_polls
    looks in a row. From then on it stays until clear_seconds have passed without a look
    that showed it, so a squawk that flickers, or a plane that drops out of hearing for a
    moment, keeps its card. The card has to say where the plane is, so one with no
    position waits until it has one; after that, its last known position stands in for a
    look without."""

    def __init__(self, reader: EmergencyReader, home: Location, held_polls: int, clear_seconds: float, clock: Clock) -> None:
        self._reader = reader
        self._home = home
        self._held_polls = held_polls
        self._clear_seconds = clear_seconds
        self._clock = clock
        self._streaks: dict[str, int] = {}
        # In the order they started, with when each was last seen in its emergency.
        self._active: dict[str, tuple[Distress, float]] = {}

    def current(self, aircraft: Sequence[Aircraft]) -> list[Distress]:
        now = self._clock.monotonic()
        heard = {plane.hex: (plane, emergency) for plane in aircraft if (emergency := self._reader.of(plane))}
        self._streaks = {hex_code: self._streaks.get(hex_code, 0) + 1 for hex_code in heard}
        for hex_code, (plane, emergency) in heard.items():
            known = self._active.get(hex_code)
            location = plane.location or (known[0].sighting.aircraft.location if known else None)
            if location is not None and (known or self._streaks[hex_code] >= self._held_polls):
                sighting = Sighting(replace(plane, location=location), self._home.distance_km(location))
                self._active[hex_code] = (Distress(sighting, emergency), now)
        self._active = {hex_code: kept for hex_code, kept in self._active.items() if now - kept[1] < self._clear_seconds}
        return [distress for distress, _ in self._active.values()]


class FirstEmergencies:
    """Every plane in any of several kinds of emergency, each once, by the first that
    knows it: a declared emergency before one only guessed from how it is flying."""

    def __init__(self, finders: Sequence[Emergencies]) -> None:
        self._finders = finders

    def current(self, aircraft: Sequence[Aircraft]) -> list[Distress]:
        found: dict[str, Distress] = {}
        for finder in self._finders:
            for distress in finder.current(aircraft):
                found.setdefault(distress.sighting.aircraft.hex, distress)
        return list(found.values())


class EmergencyLog:
    """Logs each emergency as it starts or changes kind, and once it is over."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._kinds: dict[str, str] = {}

    def note(self, distresses: Iterable[Distress]) -> None:
        kinds: dict[str, str] = {}
        for distress in distresses:
            plane, hex_code = distress.sighting.aircraft, distress.sighting.aircraft.hex
            kinds[hex_code] = distress.emergency.kind
            if self._kinds.get(hex_code) != distress.emergency.kind:
                self._logger.warning(
                    "%s emergency: %s%s, %.1f km away at %s ft",
                    plane.callsign or hex_code,
                    distress.emergency.label,
                    f", squawking {distress.emergency.squawk}" if distress.emergency.squawk else "",
                    distress.sighting.distance_km,
                    plane.altitude_ft,
                )
        for hex_code in self._kinds.keys() - kinds.keys():
            self._logger.info("%s emergency is over", hex_code)
        self._kinds = kinds


class MessageBuilder(Protocol):
    def build(self, sightings: list[Sighting], aircraft: Iterable[Aircraft]) -> dict[str, Any]: ...


class SpeechPicker(Protocol):
    def speech_for(self, card: dict[str, Any]) -> str | None: ...


class EmergencyMessages:
    """The planes message for an emergency: each plane's own card, with what is wrong,
    and the announcement for the first. Its planes builder should stay silent, as the
    announcement is this one's to make."""

    def __init__(self, planes: MessageBuilder, speech: SpeechPicker) -> None:
        self._planes = planes
        self._speech = speech

    def build(self, distresses: list[Distress], aircraft: Iterable[Aircraft]) -> dict[str, Any]:
        message = self._planes.build([d.sighting for d in distresses], aircraft)
        cards = [{**card, "emergency": _described(d.emergency)} for card, d in zip(message["planes"], distresses, strict=False)]
        return {**message, "planes": cards, "speech": self._speech.speech_for(cards[0])}


def _described(emergency: Emergency) -> dict[str, Any]:
    return {"kind": emergency.kind, "squawk": emergency.squawk, "label": emergency.label}


class Observer(Protocol):
    def note(self, distresses: Iterable[Distress]) -> None: ...


class EmergencyBuilder(Protocol):
    def build(self, distresses: list[Distress], aircraft: Iterable[Aircraft]) -> dict[str, Any]: ...


class EmergencyAlert:
    """The card for the planes in an emergency, or None while there are none."""

    def __init__(self, emergencies: Emergencies, messages: EmergencyBuilder, log: Observer) -> None:
        self._emergencies = emergencies
        self._messages = messages
        self._log = log

    def message(self, aircraft: Sequence[Aircraft]) -> dict[str, Any] | None:
        distresses = self._emergencies.current(aircraft)
        self._log.note(distresses)
        return self._messages.build(distresses, aircraft) if distresses else None
