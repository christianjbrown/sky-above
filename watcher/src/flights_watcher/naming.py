"""Names people recognise, from the codes and shouting capitals in the feed."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from importlib.resources import files
from typing import Protocol

from flights_watcher.aircraft import Aircraft
from flights_watcher.geo import Location
from flights_watcher.lookups import Airport

_AIRLINE_CALLSIGN = re.compile(r"^([A-Z]{3})\d")


def airline_code(callsign: str | None) -> str | None:
    """The ICAO operator code at the front of an airline callsign: BAW for BAW86S.
    None for a registration used as a callsign, such as GEUYM."""
    match = _AIRLINE_CALLSIGN.match(callsign or "")
    return match.group(1) if match else None


class AircraftNames:
    """AIRBUS A-320neo becomes Airbus A320neo, BOEING 737 MAX 8 becomes Boeing 737 MAX 8."""

    def tidy(self, description: str | None) -> str | None:
        if not description:
            return None
        words = [_word(word) for word in description.split()]
        if len(words) > 1 and words[1].startswith(words[0] + "-"):
            words[1] = words[1][len(words[0]) + 1 :]
        return re.sub(r"\bA-(\d)", r"A\1", " ".join(words))


def _word(word: str) -> str:
    # Maker names and other plain words get a capital; codes like MAX, ATR and ERJ-190 stay as they are.
    return word.capitalize() if word.isalpha() and word.isupper() and len(word) > 3 else word


@dataclass(frozen=True)
class Service:
    # What the card and the voice call it.
    name: str
    # What the receiver page styles it by.
    kind: str


class Services:
    """Emergency services, known by the operator code their callsigns start with. Some
    countries give all of one service a single code, whoever operates the aircraft (in the
    UK every air ambulance flies as HLE and every police aircraft as UKP), which beats a
    list of registrations that goes stale as aircraft come and go."""

    def __init__(self, services: Mapping[str, Service]) -> None:
        self._services = services

    def of(self, plane: Aircraft) -> Service | None:
        code = airline_code(plane.callsign)
        return self._services.get(code) if code else None


class MilitaryService:
    """Military aircraft, as the decoder's database marks them, named by who flies them
    when it knows ("Royal Air Force")."""

    def of(self, plane: Aircraft) -> Service | None:
        return Service(plane.operator or "Military aircraft", "military") if plane.military else None


class ServiceFinder(Protocol):
    def of(self, plane: Aircraft) -> Service | None: ...


class FirstService:
    """The first of several ways of telling a service that knows the plane."""

    def __init__(self, finders: Sequence[ServiceFinder]) -> None:
        self._finders = finders

    def of(self, plane: Aircraft) -> Service | None:
        return next((service for finder in self._finders if (service := finder.of(plane))), None)


class AirportCities:
    """The place a departures board would name for an airport. The route services give the
    town the airport stands in, which is mostly the city it serves but now and then is not
    (Vantaa for Helsinki), and sometimes add the local name in brackets: "Turin (Torino)"."""

    def __init__(self, corrections: Mapping[str, str]) -> None:
        self._corrections = corrections

    def tidy(self, airport: Airport) -> Airport:
        return replace(airport, city=self._city(airport.code, airport.city))

    def _city(self, code: str | None, city: str | None) -> str | None:
        if code is not None and code in self._corrections:
            return self._corrections[code]
        if not city:
            return None
        return re.sub(r"\s*\(.*\)$", "", city).strip() or None


class AirportCountries:
    """Which country each airport is in, by IATA code, from the table that
    tools/fetch_airports.py writes."""

    def __init__(self, countries: Mapping[str, str]) -> None:
        self._countries = countries

    @classmethod
    def bundled(cls) -> "AirportCountries":
        table = json.loads(files("flights_watcher").joinpath("airport_countries.json").read_text())
        return cls(table["countries"])

    def tidy(self, airport: Airport) -> Airport:
        return replace(airport, country=self._countries.get(airport.code or ""))


class AirportPlaces:
    """Where each airport is, by IATA code, from the table that tools/fetch_airports.py
    writes, so the map can draw a line to it."""

    def __init__(self, places: Mapping[str, Sequence[float]]) -> None:
        self._places = places

    @classmethod
    def bundled(cls) -> "AirportPlaces":
        table = json.loads(files("flights_watcher").joinpath("airport_places.json").read_text())
        return cls(table["places"])

    def tidy(self, airport: Airport) -> Airport:
        place = self._places.get(airport.code or "")
        return replace(airport, lat=place[0], lon=place[1]) if place else airport


class NearestAirportCountry:
    """A guess at the country home is in, from the nearest airport in the tables
    tools/fetch_airports.py writes, for when HOME_COUNTRY is not set. Near a border the
    nearest airport can be over it."""

    def __init__(self, places: Mapping[str, Sequence[float]], countries: Mapping[str, str]) -> None:
        self._places = places
        self._countries = countries

    @classmethod
    def bundled(cls) -> "NearestAirportCountry":
        package = files("flights_watcher")
        places = json.loads(package.joinpath("airport_places.json").read_text())["places"]
        countries = json.loads(package.joinpath("airport_countries.json").read_text())["countries"]
        return cls(places, countries)

    def of(self, home: Location) -> str | None:
        located = [code for code in self._places if code in self._countries]
        if not located:
            return None
        nearest = min(located, key=lambda code: home.distance_km(Location(*self._places[code])))
        return self._countries[nearest]
