"""Time, behind an interface so tests can move it."""

from datetime import datetime, tzinfo
from time import monotonic
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...


class SystemClock:
    def __init__(self, zone: tzinfo) -> None:
        self._zone = zone

    def monotonic(self) -> float:
        return monotonic()

    def now(self) -> datetime:
        return datetime.now(self._zone)
