"""Where the cards end up: the Nest Hub, or the log until the Cast app is registered."""

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from flights_watcher.clock import Clock


class Display(Protocol):
    def show(self, message: dict[str, Any]) -> bool:
        """Put the message on screen. False when the screen is busy with something else."""
        ...

    def clear(self) -> None:
        """Take our page down, if it is still the one showing."""
        ...


class CastDevice(Protocol):
    def running_app_id(self) -> str | None: ...

    def is_idle(self) -> bool: ...

    def is_hidden(self) -> bool:
        """Whether our card has said the Hub put something over it since it was launched."""
        ...

    def launch(self, app_id: str) -> None: ...

    def send(self, payload: dict[str, Any]) -> None: ...

    def quit(self) -> None: ...


class CastDisplay:
    """A plane comes first: takes the screen from whatever is on it, music and films
    included, and only gives back what it took."""

    def __init__(self, device: CastDevice, app_id: str, logger: logging.Logger) -> None:
        self._device = device
        self._app_id = app_id
        self._logger = logger

    def show(self, message: dict[str, Any]) -> bool:
        running = self._device.running_app_id()
        if running != self._app_id:
            if self._device.is_idle():
                self._logger.info("casting to the Hub")
            else:
                self._logger.info("casting to the Hub over %s", running)
            self._device.launch(self._app_id)
        elif self._device.is_hidden():
            self._logger.info("the Hub covered the card, launching it again")
            self._device.quit()
            self._device.launch(self._app_id)
        self._device.send(message)
        return True

    def clear(self) -> None:
        if self._device.running_app_id() == self._app_id:
            self._logger.info("sky is clear, handing the Hub back")
            self._device.quit()


class LoggingDisplay:
    """Stands in for the Hub before CAST_APP_ID is set, so the rest can be watched working."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._nearest: str | None = None

    def show(self, message: dict[str, Any]) -> bool:
        if message.get("type") == "followed":
            flight = message["flight"]
            if flight["ident"] != self._nearest:
                self._nearest = flight["ident"]
                self._logger.info("would show followed flight %s, %s", flight["ident"], flight.get("phase"))
            return True
        plane = message["planes"][0]
        if plane["hex"] != self._nearest:
            self._nearest = plane["hex"]
            route = " to ".join(end["code"] for end in (plane.get("origin"), plane.get("destination")) if end and end.get("code"))
            self._logger.info(
                "would show %s %s %s at %s ft, %.1f km away",
                plane.get("flightNumber") or plane.get("callsign") or plane["hex"],
                plane.get("aircraft") or "",
                route,
                plane.get("altitudeFt"),
                plane["distanceKm"],
            )
        return True

    def clear(self) -> None:
        if self._nearest is not None:
            self._nearest = None
            self._logger.info("would hand the Hub back")


class FanOutDisplay:
    """Shows every message on several displays at once, such as the Hub and the browser page."""

    def __init__(self, displays: Sequence[Display]) -> None:
        self._displays = displays

    def show(self, message: dict[str, Any]) -> bool:
        return any(self._each(lambda display: display.show(message)))

    def clear(self) -> None:
        self._each(lambda display: display.clear())

    def _each(self, action: Callable[[Display], Any]) -> list[Any]:
        """Runs the action on every display, so one failing does not starve the rest, then re-raises."""
        results, failure = [], None
        for display in self._displays:
            try:
                results.append(action(display))
            except Exception as error:
                failure = failure or error
        if failure is not None:
            raise failure
        return results


class Stamped:
    """Adds the same fields to every message on its way to another display, such as which
    country home is in."""

    def __init__(self, inner: Display, fields: dict[str, Any]) -> None:
        self._inner = inner
        self._fields = fields

    def show(self, message: dict[str, Any]) -> bool:
        return self._inner.show({**message, **self._fields})

    def clear(self) -> None:
        self._inner.clear()


class CoolingOff(Exception):
    pass


class CoolingOffDevice:
    """Wraps a Cast device so that after a failure it is left alone for a while,
    rather than rediscovered or relaunched every second while the Hub is away."""

    def __init__(self, inner: CastDevice, clock: Clock, seconds: float, logger: logging.Logger) -> None:
        self._inner = inner
        self._clock = clock
        self._seconds = seconds
        self._logger = logger
        self._resume_at: float | None = None

    def running_app_id(self) -> str | None:
        return self._guard(self._inner.running_app_id)

    def is_idle(self) -> bool:
        return self._guard(self._inner.is_idle)

    def is_hidden(self) -> bool:
        return self._guard(self._inner.is_hidden)

    def launch(self, app_id: str) -> None:
        self._guard(lambda: self._inner.launch(app_id))

    def send(self, payload: dict[str, Any]) -> None:
        self._guard(lambda: self._inner.send(payload))

    def quit(self) -> None:
        self._guard(self._inner.quit)

    def _guard[R](self, call: Callable[[], R]) -> R:
        if self._resume_at is not None and self._clock.monotonic() < self._resume_at:
            raise CoolingOff(f"leaving the Hub alone after a failure, retrying in {self._seconds:.0f} s")
        try:
            result = call()
        except Exception:
            self._resume_at = self._clock.monotonic() + self._seconds
            raise
        self._resume_at = None
        return result
