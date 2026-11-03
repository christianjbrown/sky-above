"""The circle around home that counts as overhead."""

from collections.abc import Iterable
from dataclasses import dataclass

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location


@dataclass(frozen=True)
class Sighting:
    aircraft: Aircraft
    distance_km: float
    # For a plane not in the zone yet but on its way: roughly when it will be overhead.
    overhead_in_seconds: float | None = None
    # Not in the zone yet: only on a line that will bring it over.
    approaching: bool = False


class Zone:
    def __init__(self, centre: Location, radius_km: float) -> None:
        self._centre = centre
        self._radius_km = radius_km

    @property
    def radius_km(self) -> float:
        return self._radius_km

    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]:
        """Airborne aircraft inside the circle, nearest first."""
        found = [
            Sighting(plane, self._centre.distance_km(plane.location))
            for plane in aircraft
            if plane.location is not None and not plane.on_ground
        ]
        return sorted((s for s in found if s.distance_km <= self._radius_km), key=lambda s: s.distance_km)
