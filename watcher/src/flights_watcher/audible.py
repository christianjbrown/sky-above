"""Which planes on the card are worth saying out loud. Every plane on the card is shown, but
only some are announced: an air ambulance, the police or a famous owner's plane, wherever
it is and however high, and any flight in the zone or on course into it that will be low enough over home to
be heard. A plane in an emergency has its own announcement (see emergency_speech)."""

from collections.abc import Collection, Sequence
from typing import Any, Protocol

FEET_PER_KM = 3280.84
SECONDS_PER_MINUTE = 60


class SpokenRule(Protocol):
    def includes(self, card: dict[str, Any]) -> bool: ...


class SpokenServices:
    """A plane flying one of these kinds of service."""

    def __init__(self, kinds: Collection[str]) -> None:
        self._kinds = kinds

    def includes(self, card: dict[str, Any]) -> bool:
        return card.get("service") in self._kinds


class FamousOwners:
    """A plane whose owner is somebody you have heard of."""

    def includes(self, card: dict[str, Any]) -> bool:
        return bool(card.get("owner"))


class HeardFromTheGround:
    """A flight in the zone, or on course to pass through it, at a height below below_km as
    it passes home: where it is now for one in the zone, and where its climb or descent will
    have taken it for one still on its way. A plane that does not say how high it is, or
    that is outside the zone with no closest approach inside it, stays quiet."""

    def __init__(self, below_km: float, zone_radius_km: float) -> None:
        self._below_ft = below_km * FEET_PER_KM
        self._zone_radius_km = zone_radius_km

    def includes(self, card: dict[str, Any]) -> bool:
        altitude = card.get("altitudeFt")
        if altitude is None or not self._passes_home(card):
            return False
        rate, seconds = card.get("verticalRateFpm"), card.get("overheadInSeconds")
        passing = altitude + rate * seconds / SECONDS_PER_MINUTE if rate and seconds else altitude
        return bool(passing < self._below_ft)

    def _passes_home(self, card: dict[str, Any]) -> bool:
        # overheadInSeconds is only set for a plane whose course takes it into the zone.
        return card.get("overheadInSeconds") is not None or card.get("distanceKm", float("inf")) <= self._zone_radius_km


class AnyOf:
    def __init__(self, rules: Sequence[SpokenRule]) -> None:
        self._rules = rules

    def includes(self, card: dict[str, Any]) -> bool:
        return any(rule.includes(card) for rule in self._rules)
