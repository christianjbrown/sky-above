"""Things worth knowing about a plane that its broadcast does not say."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote

from flights_watcher.http import JsonHttp


class LookupFailed(Exception):
    """The service could not be asked. Unlike a None answer, this is worth trying again."""


@dataclass(frozen=True)
class Airport:
    code: str | None
    name: str | None
    city: str | None
    # ISO 3166 country code, such as FI, and where the airport is; the route services leave them out.
    country: str | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class Route:
    airline: str | None
    flight_number: str | None
    origin: Airport | None
    destination: Airport | None


@dataclass(frozen=True)
class Photo:
    url: str
    photographer: str | None
    link: str | None


class RouteLookup(Protocol):
    def route(self, callsign: str) -> Route | None:
        """None when the callsign has no known route. Raises LookupFailed."""
        ...


class PhotoLookup(Protocol):
    def photo(self, registration: str) -> Photo | None:
        """None when there is no photo of this airframe. Raises LookupFailed."""
        ...


class AdsbdbRouteLookup:
    def __init__(self, base_url: str, http: JsonHttp) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

    def route(self, callsign: str) -> Route | None:
        try:
            data = self._http.get_json(f"{self._base_url}/callsign/{quote(callsign)}")
        except HTTPError as error:
            # It holds the response, and with it the connection.
            error.close()
            if error.code == 404:
                return None
            raise LookupFailed(str(error)) from error
        except (OSError, ValueError) as error:
            raise LookupFailed(str(error)) from error
        response = data.get("response") if isinstance(data, dict) else None
        found = response.get("flightroute") if isinstance(response, dict) else None
        if not isinstance(found, dict):
            return None
        airline = found.get("airline") or {}
        return Route(
            airline=airline.get("name"),
            flight_number=found.get("callsign_iata") or found.get("callsign"),
            origin=_airport(found.get("origin")),
            destination=_airport(found.get("destination")),
        )


class PlanespottersPhotoLookup:
    def __init__(self, base_url: str, http: JsonHttp) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

    def photo(self, registration: str) -> Photo | None:
        try:
            data = self._http.get_json(f"{self._base_url}/photos/reg/{quote(registration)}")
        except (OSError, ValueError) as error:
            raise LookupFailed(str(error)) from error
        photos = data.get("photos") if isinstance(data, dict) else None
        if not photos:
            return None
        first = photos[0]
        image = first.get("thumbnail_large") or first.get("thumbnail") or {}
        if not image.get("src"):
            return None
        return Photo(url=image["src"], photographer=first.get("photographer"), link=first.get("link"))


class NoRoutes:
    """Used when ROUTE_API_URL is empty: no callsign is ever sent out of the house."""

    def route(self, callsign: str) -> Route | None:
        return None


class NoPhotos:
    """Used when PHOTO_API_URL is empty: every card gets the plain plane symbol."""

    def photo(self, registration: str) -> Photo | None:
        return None


def _airport(raw: Any) -> Airport | None:
    if not isinstance(raw, dict):
        return None
    return Airport(code=raw.get("iata_code") or raw.get("icao_code"), name=raw.get("name"), city=raw.get("municipality"))


class AirportTidier(Protocol):
    def tidy(self, airport: Airport) -> Airport: ...


class TidiedRoutes:
    """Routes from another lookup, with each airport passed through the tidiers in turn:
    its city as people name it, its country, and so on."""

    def __init__(self, inner: RouteLookup, tidiers: Sequence[AirportTidier]) -> None:
        self._inner = inner
        self._tidiers = tidiers

    def route(self, callsign: str) -> Route | None:
        route = self._inner.route(callsign)
        if route is None:
            return None
        return replace(route, origin=self._tidied(route.origin), destination=self._tidied(route.destination))

    def _tidied(self, airport: Airport | None) -> Airport | None:
        if airport is None:
            return None
        for tidier in self._tidiers:
            airport = tidier.tidy(airport)
        return airport
