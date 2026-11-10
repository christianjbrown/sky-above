"""Which planes on the card are worth saying out loud. Every plane overhead is shown, but
only the ones worth listening out for are announced: an air ambulance, the police, the
military or a famous owner's plane, wherever it is, and a flight going somewhere known
that will be low enough over home to be heard."""

from collections.abc import Collection, Sequence
from typing import Any, Protocol

FEET_PER_KM = 3280.84
SECONDS_PER_MINUTE = 60


class SpokenRule(Protocol):
    def includes(self, card: dict[str, Any]) -> bool: ...


class SpecialAircraft:
    """A plane with one of these kinds of service, or with a famous owner."""

    def __init__(self, kinds: Collection[str]) -> None:
        self._kinds = kinds

    def includes(self, card: dict[str, Any]) -> bool:
        return card.get("service") in self._kinds or bool(card.get("owner"))


class HeardFromTheGround:
    """A flight whose destination is known, at a height below below_km as it passes home:
    where it is now for one in the zone, and where its climb or descent will have taken it
    for one still on its way. A plane that does not say how high it is stays quiet."""

    def __init__(self, below_km: float) -> None:
        self._below_ft = below_km * FEET_PER_KM

    def includes(self, card: dict[str, Any]) -> bool:
        altitude = card.get("altitudeFt")
        if not card.get("destination") or altitude is None:
            return False
        rate, seconds = card.get("verticalRateFpm"), card.get("overheadInSeconds")
        passing = altitude + rate * seconds / SECONDS_PER_MINUTE if rate and seconds else altitude
        return bool(passing < self._below_ft)


class AnyOf:
    def __init__(self, rules: Sequence[SpokenRule]) -> None:
        self._rules = rules

    def includes(self, card: dict[str, Any]) -> bool:
        return any(rule.includes(card) for rule in self._rules)
