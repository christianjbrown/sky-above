"""The message sent to the receiver page: the nearest planes as cards, the other planes
around for the map (just where they are and which way they point), and where home is.

It only ever travels inside the home network, to the Hub and the receiver page."""

from collections.abc import Iterable
from typing import Any, Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location
from flights_watcher.naming import Service
from flights_watcher.zone import Sighting


class CardMaker(Protocol):
    def card(self, sighting: Sighting) -> dict[str, Any]: ...


class SpeechPicker(Protocol):
    def speech_for(self, card: dict[str, Any]) -> str | None: ...


class ServiceFinder(Protocol):
    def of(self, plane: Aircraft) -> Service | None: ...


class SightingFinder(Protocol):
    def sightings(self, aircraft: Iterable[Aircraft]) -> list[Sighting]: ...


class PlanesMessageBuilder:
    def __init__(
        self,
        cards: CardMaker,
        speech: SpeechPicker,
        home: Location,
        radius_km: float,
        max_cards: int,
        surroundings: SightingFinder,
        max_others: int,
        services: ServiceFinder,
    ) -> None:
        self._cards = cards
        self._speech = speech
        self._home = home
        self._radius_km = radius_km
        self._max_cards = max_cards
        self._surroundings = surroundings
        self._max_others = max_others
        self._services = services

    def build(self, sightings: list[Sighting], aircraft: Iterable[Aircraft]) -> dict[str, Any]:
        cards = [self._cards.card(s) for s in sightings[: self._max_cards]]
        nearest = cards[0]["hex"] if cards else None
        others = [s.aircraft for s in self._surroundings.sightings(aircraft) if s.aircraft.hex != nearest]
        return {
            "type": "planes",
            "home": {"lat": self._home.lat, "lon": self._home.lon},
            "radiusKm": self._radius_km,
            "total": len(sightings),
            "planes": cards,
            "speech": self._speech.speech_for(cards[0]) if cards else None,
            "others": [self._marker(plane, plane.location) for plane in others[: self._max_others] if plane.location],
        }

    def _marker(self, plane: Aircraft, location: Location) -> dict[str, Any]:
        service = self._services.of(plane)
        return {
            "hex": plane.hex,
            "lat": round(location.lat, 5),
            "lon": round(location.lon, 5),
            "trackDeg": plane.track_deg,
            "category": plane.category,
            "typeCode": plane.type_code,
            "service": service.kind if service else None,
        }
