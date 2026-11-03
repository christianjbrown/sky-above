"""How long the card stays up after the last plane has gone."""

from typing import Protocol

from flights_watcher.clock import Clock


class GracePeriod(Protocol):
    def seen(self, nearest: str) -> None: ...

    def expired(self) -> bool: ...

    def reset(self) -> None: ...


class Linger:
    def __init__(self, seconds: float, clock: Clock) -> None:
        self._seconds = seconds
        self._clock = clock
        self._last_seen: float | None = None

    def seen(self, nearest: str) -> None:
        self._last_seen = self._clock.monotonic()

    def expired(self) -> bool:
        return self._last_seen is not None and self._clock.monotonic() - self._last_seen >= self._seconds

    def reset(self) -> None:
        self._last_seen = None


class MinimumShowing:
    """Keeps each plane's card up for at least a set time from when it became the
    nearest, however soon it leaves the zone. A plane that takes over starts the
    time again, so a closer flight still replaces the card straight away."""

    def __init__(self, inner: GracePeriod, seconds: float, clock: Clock) -> None:
        self._inner = inner
        self._seconds = seconds
        self._clock = clock
        self._nearest: str | None = None
        self._since: float | None = None

    def seen(self, nearest: str) -> None:
        if nearest != self._nearest:
            self._nearest = nearest
            self._since = self._clock.monotonic()
        self._inner.seen(nearest)

    def expired(self) -> bool:
        shown_long_enough = self._since is not None and self._clock.monotonic() - self._since >= self._seconds
        return shown_long_enough and self._inner.expired()

    def reset(self) -> None:
        self._nearest, self._since = None, None
        self._inner.reset()
