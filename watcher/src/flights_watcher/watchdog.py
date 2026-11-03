"""Keeps an eye on the watcher from outside it, and says when it stops working.

Docker restarts a watcher that crashes, but not one that is still running and getting
nowhere: stuck, failing every look because the Hub or the antenna's feed has gone, or
hearing no aircraft at all because the antenna has. So this runs on its own, reads the
watcher's /status.json every minute, and sends an alert when one of those starts and
another when it is over. ALERT_URL takes the alerts as a plain text POST, as an ntfy
topic does; without one they are only logged.

    python -m flights_watcher.watchdog
"""

import json
import logging
import os
import signal
import threading
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from flights_watcher.clock import Clock, SystemClock

CHECK_EVERY_SECONDS = 60
STOPPED_AFTER = timedelta(minutes=3)
FAILING_FOR = timedelta(minutes=5)
DEAF_FOR = timedelta(minutes=60)


class StatusSource(Protocol):
    def status(self) -> dict[str, Any] | None:
        """The watcher's latest status, or None when it does not answer."""
        ...


class HttpStatus:
    def __init__(self, url: str, timeout_seconds: float) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds

    def status(self) -> dict[str, Any] | None:
        try:
            with urllib.request.urlopen(self._url, timeout=self._timeout_seconds) as response:  # noqa: S310 - checked in WatchdogSettings
                found = json.loads(response.read())
        except (OSError, ValueError):
            return None
        return found if isinstance(found, dict) else None


class Check(Protocol):
    name: str

    def problem(self, status: dict[str, Any] | None, now: datetime) -> str | None:
        """What is wrong, in a sentence, or None when this is fine."""
        ...


def _since(status: dict[str, Any], key: str, now: datetime) -> timedelta | None:
    value = status.get(key)
    return now - datetime.fromisoformat(value) if value else None


class Stopped:
    """The watcher does not answer, or has not looked at the sky for a while."""

    name = "stopped"

    def __init__(self, after: timedelta) -> None:
        self._after = after

    def problem(self, status: dict[str, Any] | None, now: datetime) -> str | None:
        if status is None:
            return "The watcher is not answering."
        since = _since(status, "lastLook", now)
        if since is None or since > self._after:
            return "The watcher has stopped looking at the sky."
        return None


class KeepsFailing:
    """Every look has failed for a while, such as when the Hub cannot be reached."""

    name = "failing"

    def __init__(self, after: timedelta) -> None:
        self._after = after

    def problem(self, status: dict[str, Any] | None, now: datetime) -> str | None:
        if status is None:
            return None
        since = _since(status, "failingSince", now)
        if since is None or since < self._after:
            return None
        return f"The watcher has been failing for {int(since.total_seconds() // 60)} minutes: {status.get('failure')}"


class HearsNothing:
    """No aircraft heard for a while, which means the antenna or its receiver has stopped."""

    name = "deaf"

    def __init__(self, after: timedelta) -> None:
        self._after = after

    def problem(self, status: dict[str, Any] | None, now: datetime) -> str | None:
        if status is None or not status.get("lastLook"):
            return None
        since = _since(status, "aircraftHeardAt", now)
        if since is not None and since < self._after:
            return None
        return f"The antenna has not heard an aircraft for over {int(self._after.total_seconds() // 60)} minutes."


class Alerts(Protocol):
    def send(self, text: str) -> None: ...


class PostedAlerts:
    """Posts each alert as plain text, as an ntfy topic takes them. A failed post is logged."""

    def __init__(self, url: str, timeout_seconds: float, logger: logging.Logger) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds
        self._logger = logger

    def send(self, text: str) -> None:
        request = urllib.request.Request(self._url, data=text.encode(), headers={"Title": "Sky Above"}, method="POST")  # noqa: S310 - checked in WatchdogSettings
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds):  # noqa: S310 - checked in WatchdogSettings
                pass
        except OSError as error:
            self._logger.warning("could not send the alert %r: %s", text, error)


class LoggedAlerts:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def send(self, text: str) -> None:
        self._logger.warning("alert: %s", text)


class Watchdog:
    """Runs every check against the latest status, and alerts once when a problem starts
    and once when it clears, rather than every minute it lasts."""

    def __init__(self, source: StatusSource, checks: Sequence[Check], alerts: Alerts, clock: Clock) -> None:
        self._source = source
        self._checks = checks
        self._alerts = alerts
        self._clock = clock
        self._open: dict[str, str] = {}

    def check(self) -> None:
        status = self._source.status()
        now = self._clock.now()
        for check in self._checks:
            problem = check.problem(status, now)
            if problem is not None and check.name not in self._open:
                self._open[check.name] = problem
                self._alerts.send(problem)
            elif problem is None and check.name in self._open:
                self._alerts.send(f"Working again: {self._open.pop(check.name)}")


@dataclass(frozen=True)
class WatchdogSettings:
    """Where the watcher's status is, and where alerts go. Both must be web addresses."""

    status_url: str
    alert_url: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "WatchdogSettings":
        settings = cls(env.get("STATUS_URL") or "http://localhost:8091/status.json", env.get("ALERT_URL", "").strip() or None)
        for url in (settings.status_url, settings.alert_url or "http://"):
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"{url!r} is not a web address")
        return settings


def build(settings: WatchdogSettings, logger: logging.Logger) -> Watchdog:
    alerts: Alerts = PostedAlerts(settings.alert_url, 10, logger) if settings.alert_url else LoggedAlerts(logger)
    checks: list[Check] = [Stopped(STOPPED_AFTER), KeepsFailing(FAILING_FOR), HearsNothing(DEAF_FOR)]
    return Watchdog(HttpStatus(settings.status_url, 10), checks, alerts, SystemClock(UTC))


def main(environ: Mapping[str, str], stop: threading.Event) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("watchdog")
    settings = WatchdogSettings.from_env(environ)
    watchdog = build(settings, logger)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logger.info("watching %s, alerts %s", settings.status_url, "posted" if settings.alert_url else "logged only")
    while not stop.wait(CHECK_EVERY_SECONDS):
        watchdog.check()


if __name__ == "__main__":
    main(os.environ, threading.Event())
