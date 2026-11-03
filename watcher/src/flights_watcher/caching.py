"""Remembering lookup answers, so each plane is asked about once."""

from collections import OrderedDict

from flights_watcher.clock import Clock
from flights_watcher.flightaware import OperatorNames
from flights_watcher.lookups import Photo, PhotoLookup, Route, RouteLookup


class TtlCache[V]:
    """Answers expire after ttl_seconds, or none_ttl_seconds for a None answer when given;
    the oldest go first once max_entries is reached."""

    def __init__(self, clock: Clock, ttl_seconds: float, max_entries: int, none_ttl_seconds: float | None = None) -> None:
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._none_ttl_seconds = ttl_seconds if none_ttl_seconds is None else none_ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> tuple[bool, V | None]:
        entry = self._entries.get(key)
        if entry is None or self._clock.monotonic() > entry[0]:
            return False, None
        return True, entry[1]

    def put(self, key: str, value: V) -> None:
        ttl = self._none_ttl_seconds if value is None else self._ttl_seconds
        self._entries[key] = (self._clock.monotonic() + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


class CachedRouteLookup:
    def __init__(self, inner: RouteLookup, cache: TtlCache[Route | None]) -> None:
        self._inner = inner
        self._cache = cache

    def route(self, callsign: str) -> Route | None:
        hit, value = self._cache.get(callsign)
        if hit:
            return value
        value = self._inner.route(callsign)
        self._cache.put(callsign, value)
        return value


class CachedPhotoLookup:
    def __init__(self, inner: PhotoLookup, cache: TtlCache[Photo | None]) -> None:
        self._inner = inner
        self._cache = cache

    def photo(self, registration: str) -> Photo | None:
        hit, value = self._cache.get(registration)
        if hit:
            return value
        value = self._inner.photo(registration)
        self._cache.put(registration, value)
        return value


class CachedOperatorNames:
    def __init__(self, inner: OperatorNames, cache: TtlCache[str | None]) -> None:
        self._inner = inner
        self._cache = cache

    def name(self, icao: str) -> str | None:
        hit, value = self._cache.get(icao)
        if hit:
            return value
        value = self._inner.name(icao)
        self._cache.put(icao, value)
        return value
