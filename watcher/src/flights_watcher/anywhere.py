"""Aircraft worth a card wherever the antenna hears them: famous owners' planes. They go
after the planes overhead, nearest first. Air ambulances, the police and the military are
shown like any other plane, in the zone or on their way into it."""

from collections.abc import Iterable
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location
from flights_watcher.notable import Notable
from flights_watcher.zone import Sighting


class SpecialRule(Protocol):
    def includes_aircraft(self, plane: Aircraft) -> bool: ...


class NotableFinder(Protocol):
    def of(self, plane: Aircraft) -> Notable | None: ...


class SightingFinder(Protocol):
    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]: ...


class FamousOwner:
    def __init__(self, notables: NotableFinder) -> None:
        self._notables = notables

    def includes_aircraft(self, plane: Aircraft) -> bool:
        return self._notables.of(plane) is not None


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
