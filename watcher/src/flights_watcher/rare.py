"""The kinds of aircraft rare enough to be let through quiet hours, chosen by name in
QUIET_HOURS_EXCEPT: helicopters and military aircraft, or neither."""

from collections.abc import Collection
from typing import Any

from flights_watcher.aircraft import Aircraft

# ADS-B emitter category for helicopters.
ROTORCRAFT = "A7"
KINDS = ("helicopters", "military")


class RareKinds:
    def __init__(self, kinds: Collection[str]) -> None:
        self._kinds = set(kinds)

    def includes_aircraft(self, plane: Aircraft) -> bool:
        return self._includes(plane.category == ROTORCRAFT, plane.military)

    def includes_card(self, card: dict[str, Any]) -> bool:
        return self._includes(bool(card.get("helicopter")), bool(card.get("military")))

    def _includes(self, helicopter: bool, military: bool) -> bool:
        return ("helicopters" in self._kinds and helicopter) or ("military" in self._kinds and military)
