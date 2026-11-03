"""Ticks the watcher until told to stop, and survives a bad tick."""

import logging
import threading
from typing import Protocol

from flights_watcher.display import Display


class Tickable(Protocol):
    def tick(self) -> None: ...


class Looks(Protocol):
    def looked(self, failure: str | None) -> None:
        """One look at the sky is over, and why it failed if it did."""
        ...


class Runner:
    def __init__(self, watcher: Tickable, display: Display, interval_seconds: float, looks: Looks, logger: logging.Logger) -> None:
        self._watcher = watcher
        self._display = display
        self._looks = looks
        self._interval_seconds = interval_seconds
        self._logger = logger

    def run(self, stop: threading.Event) -> None:
        last_error: str | None = None
        while not stop.is_set():
            try:
                self._watcher.tick()
                last_error = None
                self._looks.looked(None)
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                self._looks.looked(message)
                if message != last_error:
                    self._logger.warning("tick failed: %s", message)
                    last_error = message
            stop.wait(self._interval_seconds)
        try:
            self._display.clear()
        except Exception as error:
            self._logger.warning("could not hand the Hub back on shutdown: %s", error)
