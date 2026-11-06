"""Helicopters known by their type, for those that never say what kind of aircraft they are."""

import json
from collections.abc import Collection
from dataclasses import replace
from importlib.resources import files

from flights_watcher.aircraft import Aircraft
from flights_watcher.rare import ROTORCRAFT
from flights_watcher.sources import AircraftSource


class KnownRotorcraft:
    """The aircraft another source hears, with the rotorcraft category filled in from the
    plane's ICAO type designator when the plane sends no category of its own. A helicopter
    with only a Mode S transponder, as many police helicopters have, says who it is and
    how high it is flying but not what kind of aircraft it is, while the decoder's
    database still knows its type."""

    def __init__(self, source: AircraftSource, types: Collection[str]) -> None:
        self._source = source
        self._types = frozenset(types)

    @classmethod
    def bundled(cls, source: AircraftSource) -> "KnownRotorcraft":
        """With the table tools/fetch_rotorcraft_types.py writes."""
        table = json.loads(files("flights_watcher").joinpath("rotorcraft_types.json").read_text())
        return cls(source, table["types"])

    def aircraft(self) -> list[Aircraft]:
        return [self._known(plane) for plane in self._source.aircraft()]

    def _known(self, plane: Aircraft) -> Aircraft:
        return replace(plane, category=ROTORCRAFT) if plane.category is None and plane.type_code in self._types else plane
