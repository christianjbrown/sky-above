"""Turning a sighting into the card the receiver page draws."""

import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.lookups import Airport, LookupFailed, PhotoLookup, RouteLookup
from flights_watcher.naming import Service, airline_code
from flights_watcher.rare import ROTORCRAFT
from flights_watcher.zone import Sighting


class AircraftNamer(Protocol):
    def tidy(self, description: str | None) -> str | None: ...


class ServiceFinder(Protocol):
    def of(self, plane: Aircraft) -> Service | None: ...


class CardBuilder:
    def __init__(
        self,
        routes: RouteLookup,
        photos: PhotoLookup,
        aircraft_names: AircraftNamer,
        services: ServiceFinder,
        logger: logging.Logger,
    ) -> None:
        self._routes = routes
        self._photos = photos
        self._aircraft_names = aircraft_names
        self._services = services
        self._logger = logger

    def card(self, sighting: Sighting) -> dict[str, Any]:
        plane = sighting.aircraft
        service = self._services.of(plane)
        # Emergency and military flights keep no timetable, so there is no route to ask about, and
        # FlightAware's guess at one names some other operator and a spot on a map.
        route = None if service else self._ask(self._routes.route, plane.callsign)
        photo = self._ask(self._photos.photo, plane.registration)
        code = airline_code(plane.callsign)
        return {
            "hex": plane.hex,
            "callsign": plane.callsign,
            "flightNumber": route.flight_number if route else None,
            "airline": service.name if service else (route.airline if route else None),
            "service": service.kind if service else None,
            "airlineCode": code,
            "helicopter": plane.category == ROTORCRAFT,
            "military": plane.military,
            "category": plane.category,
            "origin": _airport(route.origin) if route else None,
            "destination": _airport(route.destination) if route else None,
            "aircraft": self._aircraft_names.tidy(plane.description),
            "typeCode": plane.type_code,
            "registration": plane.registration,
            "altitudeFt": plane.altitude_ft,
            "speedKt": plane.ground_speed_kt,
            "verticalRateFpm": plane.vertical_rate_fpm,
            "trackDeg": plane.track_deg,
            "lat": round(plane.location.lat, 5) if plane.location else None,
            "lon": round(plane.location.lon, 5) if plane.location else None,
            "distanceKm": round(sighting.distance_km, 2),
            "overheadInSeconds": round(sighting.overhead_in_seconds) if sighting.overhead_in_seconds else None,
            "photo": asdict(photo) if photo else None,
        }

    def _ask[V](self, lookup: Callable[[str], V], key: str | None) -> V | None:
        if key is None:
            return None
        try:
            return lookup(key)
        except LookupFailed as error:
            self._logger.warning("lookup for %s failed: %s", key, error)
            return None


def _airport(airport: Airport | None) -> dict[str, Any] | None:
    return asdict(airport) if airport else None
