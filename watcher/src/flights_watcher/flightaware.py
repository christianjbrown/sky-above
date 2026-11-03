"""Routes from FlightAware's AeroAPI, which follows each flight as it is flown today.

adsbdb's fixed list gave old routes, the wrong leg of a round trip and a
callsign in place of the flight number. AeroAPI knows which flight a callsign
is right now, so the card gets the real flight number and direction."""

from collections.abc import Collection
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote

from flights_watcher.http import JsonHttp
from flights_watcher.lookups import Airport, LookupFailed, Route


class OperatorNames(Protocol):
    def name(self, icao: str) -> str | None:
        """None when the operator is unknown. Raises LookupFailed."""
        ...


class AeroApiOperatorNames:
    def __init__(self, base_url: str, http: JsonHttp) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

    def name(self, icao: str) -> str | None:
        found = aeroapi_get(self._http, f"{self._base_url}/operators/{quote(icao)}")
        if not isinstance(found, dict):
            return None
        return found.get("shortname") or found.get("name")


class AeroApiRouteLookup:
    """icao_numbered lists airlines whose flights people know by their ICAO number,
    such as easyJet's EZY839, rather than the IATA one (U2839)."""

    def __init__(self, base_url: str, http: JsonHttp, operators: OperatorNames, icao_numbered: Collection[str]) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._operators = operators
        self._icao_numbered = icao_numbered

    def route(self, callsign: str) -> Route | None:
        found = aeroapi_get(self._http, f"{self._base_url}/flights/{quote(callsign)}?ident_type=designator&max_pages=1")
        flights = found.get("flights") if isinstance(found, dict) else None
        flight = _airborne(flights or [])
        if flight is None:
            return None
        operator = flight.get("operator_icao") or flight.get("operator")
        number = flight.get("ident_iata")
        if operator in self._icao_numbered or not number:
            number = flight.get("ident_icao") or flight.get("ident")
        return Route(
            airline=self._operators.name(operator) if operator else None,
            flight_number=number,
            origin=aeroapi_airport(flight.get("origin")),
            destination=aeroapi_airport(flight.get("destination")),
        )


def _airborne(flights: list[Any]) -> dict[str, Any] | None:
    """The flight under this callsign that has taken off and not yet landed, the
    latest if there are several. A callsign is reused every day, and for each leg
    of a round trip, so only the one in the air is the plane overhead."""
    flying = [f for f in flights if isinstance(f, dict) and f.get("actual_off") and not f.get("actual_on") and not f.get("cancelled")]
    return max(flying, key=lambda f: f["actual_off"], default=None)


def aeroapi_get(http: JsonHttp, url: str) -> Any:
    try:
        return http.get_json(url)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise LookupFailed(str(error)) from error
    except (OSError, ValueError) as error:
        raise LookupFailed(str(error)) from error


def aeroapi_airport(raw: Any) -> Airport | None:
    if not isinstance(raw, dict):
        return None
    code = raw.get("code_iata") or raw.get("code_icao") or raw.get("code")
    # Some cities come with the airport tacked on, as in "Faro / Algarve Int. Faro".
    city = (raw.get("city") or "").split(" / ")[0].strip() or None
    return Airport(code=code, name=raw.get("name"), city=city)
