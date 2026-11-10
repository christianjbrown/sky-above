"""Aircraft worth a card wherever the antenna hears them: air ambulances, the police, the
military and famous owners' planes. They go after the planes overhead, nearest first."""

from collections.abc import Collection, Iterable, Sequence
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location
from flights_watcher.naming import Service
from flights_watcher.notable import Notable
from flights_watcher.zone import Sighting


class SpecialRule(Protocol):
    def includes_aircraft(self, plane: Aircraft) -> bool: ...


class ServiceFinder(Protocol):
    def of(self, plane: Aircraft) -> Service | None: ...


class NotableFinder(Protocol):
    def of(self, plane: Aircraft) -> Notable | None: ...


class SightingFinder(Protocol):
    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]: ...


class ServiceKinds:
    def __init__(self, services: ServiceFinder, kinds: Collection[str]) -> None:
        self._services = services
        self._kinds = kinds

    def includes_aircraft(self, plane: Aircraft) -> bool:
        service = self._services.of(plane)
        return service is not None and service.kind in self._kinds


class FamousOwner:
    def __init__(self, notables: NotableFinder) -> None:
        self._notables = notables

    def includes_aircraft(self, plane: Aircraft) -> bool:
        return self._notables.of(plane) is not None


class AnySpecial:
    def __init__(self, rules: Sequence[SpecialRule]) -> None:
        self._rules = rules

    def includes_aircraft(self, plane: Aircraft) -> bool:
        return any(rule.includes_aircraft(plane) for rule in self._rules)


class HeardAnywhere:
    """The planes the inner finder found, then every special one it did not, however far
    from home, in the air and with a position, nearest first."""

    def __init__(self, inner: SightingFinder, special: SpecialRule, home: Location) -> None:
        self._inner = inner
        self._special = special
        self._home = home

    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]:
        planes = list(aircraft)
        found = self._inner.sightings(planes)
        shown = {sighting.aircraft.hex for sighting in found}
        afar = [
            Sighting(plane, self._home.distance_km(plane.location), afar=True)
            for plane in planes
            if plane.location is not None and not plane.on_ground and plane.hex not in shown and self._special.includes_aircraft(plane)
        ]
        return found + sorted(afar, key=lambda sighting: sighting.distance_km)
