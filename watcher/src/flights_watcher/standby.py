"""What the screen shows when no plane is overhead: the followed flight on now, if any."""

from collections.abc import Sequence
from typing import Any, Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.following import Followed


class CurrentFlight(Protocol):
    def current(self, aircraft: Sequence[Aircraft]) -> Followed | None: ...


class FollowedCards(Protocol):
    def build(self, followed: Followed) -> dict[str, Any]: ...


class FollowedStandby:
    def __init__(self, flights: CurrentFlight, cards: FollowedCards) -> None:
        self._flights = flights
        self._cards = cards

    def message(self, aircraft: Sequence[Aircraft]) -> dict[str, Any] | None:
        followed = self._flights.current(aircraft)
        return self._cards.build(followed) if followed else None


class NothingOnStandby:
    def message(self, aircraft: Sequence[Aircraft]) -> dict[str, Any] | None:
        return None
