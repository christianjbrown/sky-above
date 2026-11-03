"""Air ambulances and police aircraft keep the card once they have it."""

from collections.abc import Collection, Iterable
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location
from flights_watcher.naming import Service
from flights_watcher.zone import Sighting


class SightingFinder(Protocol):
    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]: ...


class ServiceFinder(Protocol):
    def of(self, plane: Aircraft) -> Service | None: ...


class ServicesStay:
    """Puts an emergency service's aircraft first once it has come into the zone, and keeps
    it there until it is further than hold_km from home, lands or is no longer heard. A
    plane coming into the zone meanwhile waits until it has gone, and one circling just
    outside the zone keeps its card."""

    def __init__(self, inner: SightingFinder, services: ServiceFinder, kinds: Collection[str], home: Location, hold_km: float) -> None:
        self._inner = inner
        self._services = services
        self._kinds = kinds
        self._home = home
        self._hold_km = hold_km
        # In the order they came into the zone.
        self._held: dict[str, None] = {}

    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]:
        planes = list(aircraft)
        found = self._inner.sightings(planes)
        for sighting in found:
            if not sighting.approaching and self._is_held_kind(sighting.aircraft):
                self._held.setdefault(sighting.aircraft.hex, None)
        heard = {plane.hex: plane for plane in planes}
        inner = {sighting.aircraft.hex: sighting for sighting in found}
        held = [near for hex_code in list(self._held) if (near := self._still_near(heard.get(hex_code), inner))]
        self._held = dict.fromkeys(sighting.aircraft.hex for sighting in held)
        return held + [sighting for sighting in found if sighting.aircraft.hex not in self._held]

    def _is_held_kind(self, plane: Aircraft) -> bool:
        service = self._services.of(plane)
        return service is not None and service.kind in self._kinds

    def _still_near(self, plane: Aircraft | None, inner: dict[str, Sighting]) -> Sighting | None:
        if plane is None or plane.location is None or plane.on_ground:
            return None
        distance = self._home.distance_km(plane.location)
        if distance > self._hold_km:
            return None
        return inner.get(plane.hex) or Sighting(plane, distance)
