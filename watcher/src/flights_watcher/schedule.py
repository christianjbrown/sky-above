"""Hours when the screen is left alone."""

from datetime import time


class QuietHours:
    def __init__(self, start: time | None, end: time | None) -> None:
        self._start = start
        self._end = end

    @classmethod
    def parse(cls, spec: str) -> "QuietHours":
        """ "23:00-07:00" means quiet overnight; an empty string means never quiet."""
        spec = spec.strip()
        if not spec:
            return cls(None, None)
        start, end = (time.fromisoformat(part.strip()) for part in spec.split("-", 1))
        return cls(start, end)

    def is_quiet(self, now: time) -> bool:
        if self._start is None or self._end is None:
            return False
        if self._start <= self._end:
            return self._start <= now < self._end
        return now >= self._start or now < self._end
