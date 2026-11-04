"""Hours when the screen or the voice is left alone."""

from collections.abc import Sequence
from datetime import datetime, time, timedelta

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class QuietWindow:
    """One stretch of quiet, every day or only on some days of the week. A window that
    wraps midnight belongs to the day it starts on, so "Fri 23:00-07:00" runs from
    Friday night into Saturday morning."""

    def __init__(self, start: time, end: time, days: frozenset[int]) -> None:
        self._start = start
        self._end = end
        self._days = days

    @classmethod
    def parse(cls, spec: str) -> "QuietWindow":
        """ "23:00-07:00" is every night; "Sat 00:00-10:00" and "Mon-Fri 09:00-17:00" only
        on those days."""
        days, _, hours = spec.strip().rpartition(" ")
        start, sep, end = hours.partition("-")
        if not sep:
            raise ValueError(f"quiet hours should look like 23:00-07:00, not {spec.strip()!r}")
        return cls(time.fromisoformat(start.strip()), time.fromisoformat(end.strip()), _days(days))

    def is_quiet(self, now: datetime) -> bool:
        at = now.time()
        if self._start <= self._end:
            return now.weekday() in self._days and self._start <= at < self._end
        yesterday = (now - timedelta(days=1)).weekday()
        return (now.weekday() in self._days and at >= self._start) or (yesterday in self._days and at < self._end)


def _days(spec: str) -> frozenset[int]:
    """ "" is every day, "Wed" one day, "Mon-Fri" a run of them that may wrap the week."""
    if not spec.strip():
        return frozenset(range(7))
    first, _, last = spec.strip().partition("-")
    start, end = _day(first), _day(last or first)
    return frozenset((start + step) % 7 for step in range((end - start) % 7 + 1))


def _day(name: str) -> int:
    word = name.strip().lower()
    for number, day in enumerate(DAYS):
        if len(word) >= 3 and day.startswith(word):
            return number
    raise ValueError(f"{name.strip()!r} is not a day of the week")


class QuietHours:
    """Quiet whenever any of its windows is."""

    def __init__(self, windows: Sequence[QuietWindow]) -> None:
        self._windows = windows

    @classmethod
    def parse(cls, spec: str) -> "QuietHours":
        """Comma separated windows, such as "00:00-08:00, Sat 00:00-10:00"; an empty string
        means never quiet."""
        return cls([QuietWindow.parse(part) for part in spec.split(",") if part.strip()])

    def is_quiet(self, now: datetime) -> bool:
        return any(window.is_quiet(now) for window in self._windows)
