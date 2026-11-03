import logging

import pytest

from fakes import HOME, FakeClock, FakeHttp, http_error, plane
from flights_watcher.caching import CachedPhotoLookup, CachedRouteLookup, TtlCache
from flights_watcher.cards import CardBuilder
from flights_watcher.geo import Location
from flights_watcher.lookups import (
    AdsbdbRouteLookup,
    Airport,
    LookupFailed,
    NoPhotos,
    NoRoutes,
    Photo,
    PlanespottersPhotoLookup,
    Route,
    TidiedRoutes,
)
from flights_watcher.messages import PlanesMessageBuilder
from flights_watcher.naming import (
    AircraftNames,
    AirportCities,
    AirportCountries,
    AirportPlaces,
    FirstService,
    MilitaryService,
    NearestAirportCountry,
    Service,
    Services,
    airline_code,
)
from flights_watcher.zone import Sighting, Zone

ROUTE_URL = "https://adsbdb.test/v0/callsign/BAW86S"
PHOTO_URL = "https://planespotters.test/pub/photos/reg/G-EUYM"
ADSBDB_ANSWER = {
    "response": {
        "flightroute": {
            "callsign": "BAW86S",
            "callsign_iata": "BA86S",
            "airline": {"name": "British Airways"},
            "origin": {"iata_code": "PRG", "name": "Václav Havel Airport Prague", "municipality": "Prague"},
            "destination": {"iata_code": "LHR", "name": "London Heathrow Airport", "municipality": "London"},
        }
    }
}
PLANESPOTTERS_ANSWER = {
    "photos": [
        {
            "thumbnail_large": {"src": "https://t.plnspttrs.net/1_280.jpg"},
            "link": "https://www.planespotters.net/photo/1",
            "photographer": "Borut Smrdelj",
        }
    ]
}


def test_route_lookup_reads_adsbdb():
    route = AdsbdbRouteLookup("https://adsbdb.test/v0/", FakeHttp({ROUTE_URL: ADSBDB_ANSWER})).route("BAW86S")
    assert route == Route(
        airline="British Airways",
        flight_number="BA86S",
        origin=Airport("PRG", "Václav Havel Airport Prague", "Prague"),
        destination=Airport("LHR", "London Heathrow Airport", "London"),
    )


def test_unknown_callsign_is_none_but_an_outage_is_a_failure():
    unknown = FakeHttp({ROUTE_URL: http_error(404)})
    assert AdsbdbRouteLookup("https://adsbdb.test/v0", unknown).route("BAW86S") is None
    down = FakeHttp({ROUTE_URL: http_error(503)})
    with pytest.raises(LookupFailed):
        AdsbdbRouteLookup("https://adsbdb.test/v0", down).route("BAW86S")
    unreachable = FakeHttp({ROUTE_URL: OSError("no route")})
    with pytest.raises(LookupFailed):
        AdsbdbRouteLookup("https://adsbdb.test/v0", unreachable).route("BAW86S")


def test_photo_lookup_reads_planespotters():
    photo = PlanespottersPhotoLookup("https://planespotters.test/pub", FakeHttp({PHOTO_URL: PLANESPOTTERS_ANSWER})).photo("G-EUYM")
    assert photo == Photo("https://t.plnspttrs.net/1_280.jpg", "Borut Smrdelj", "https://www.planespotters.net/photo/1")
    empty = FakeHttp({PHOTO_URL: {"photos": []}})
    assert PlanespottersPhotoLookup("https://planespotters.test/pub", empty).photo("G-EUYM") is None


def test_cache_answers_repeats_and_expires():
    clock = FakeClock()
    http = FakeHttp({ROUTE_URL: ADSBDB_ANSWER})
    routes = CachedRouteLookup(AdsbdbRouteLookup("https://adsbdb.test/v0", http), TtlCache(clock, 60, 10))
    routes.route("BAW86S")
    routes.route("BAW86S")
    assert len(http.requested) == 1
    clock.seconds = 61
    routes.route("BAW86S")
    assert len(http.requested) == 2


def test_cache_remembers_none_but_not_failures():
    clock = FakeClock()
    http = FakeHttp({PHOTO_URL: {"photos": []}})
    photos = CachedPhotoLookup(PlanespottersPhotoLookup("https://planespotters.test/pub", http), TtlCache(clock, 60, 10))
    assert photos.photo("G-EUYM") is None
    assert photos.photo("G-EUYM") is None
    assert len(http.requested) == 1
    http.responses[PHOTO_URL] = OSError("down")
    with pytest.raises(LookupFailed):
        CachedPhotoLookup(PlanespottersPhotoLookup("https://planespotters.test/pub", http), TtlCache(clock, 60, 10)).photo("G-EUYM")


def test_cache_drops_the_oldest_when_full():
    cache: TtlCache[int] = TtlCache(FakeClock(), 60, 2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") == (False, None)
    assert cache.get("c") == (True, 3)


class StubRoutes:
    def __init__(self, answer=None, error: Exception | None = None) -> None:
        self.answer, self.error = answer, error

    def route(self, callsign):
        if self.error:
            raise self.error
        return self.answer


class StubPhotos(StubRoutes):
    def photo(self, registration):
        return self.route(registration)


def test_card_carries_what_the_page_draws():
    route = Route("British Airways", "BA86S", Airport("PRG", "Prague airport", "Prague"), Airport("LHR", "Heathrow", "London"))
    photo = Photo("https://img.test/1.jpg", "Borut Smrdelj", "https://planespotters.test/1")
    card = CardBuilder(StubRoutes(route), StubPhotos(photo), AircraftNames(), Services({}), logging.getLogger("t")).card(
        Sighting(plane(), 1.234)
    )
    assert card["airline"] == "British Airways"
    assert card["flightNumber"] == "BA86S"
    assert card["origin"] == {"code": "PRG", "name": "Prague airport", "city": "Prague", "country": None, "lat": None, "lon": None}
    assert card["destination"]["code"] == "LHR"
    assert card["aircraft"] == "Airbus A320"
    assert card["airlineCode"] == "BAW"
    assert not card["helicopter"]
    assert card["registration"] == "G-EUYM"
    assert card["altitudeFt"] == 4000
    assert card["distanceKm"] == 1.23
    assert card["overheadInSeconds"] is None
    assert (card["lat"], card["lon"]) == (round(HOME.lat + 0.004, 5), HOME.lon)
    assert card["photo"] == {"url": "https://img.test/1.jpg", "photographer": "Borut Smrdelj", "link": "https://planespotters.test/1"}


def test_card_says_when_a_plane_on_its_way_will_be_overhead():
    builder = CardBuilder(StubRoutes(None), StubPhotos(None), AircraftNames(), Services({}), logging.getLogger("t"))
    assert builder.card(Sighting(plane(), 20.0, 161.6))["overheadInSeconds"] == 162


def test_card_survives_failed_and_missing_lookups():
    builder = CardBuilder(StubRoutes(error=LookupFailed("down")), StubPhotos(None), AircraftNames(), Services({}), logging.getLogger("t"))
    card = builder.card(Sighting(plane(callsign=None), 2.0))
    assert card["airline"] is None
    assert card["origin"] is None
    assert card["photo"] is None
    assert card["callsign"] is None


def test_a_failed_lookup_is_logged_and_the_card_goes_on_without_it(caplog):
    builder = CardBuilder(StubRoutes(error=LookupFailed("down")), StubPhotos(None), AircraftNames(), Services({}), logging.getLogger("t"))
    card = builder.card(Sighting(plane(), 2.0))
    assert card["origin"] is None
    assert "lookup for BAW86S failed: down" in caplog.text


class FixedSpeech:
    def speech_for(self, card):
        return f"speech/{card['hex']}.wav"


def test_message_holds_the_nearest_cards_and_the_full_count():
    builder = CardBuilder(StubRoutes(None), StubPhotos(None), AircraftNames(), Services({}), logging.getLogger("t"))
    sightings = [Sighting(plane(f"p{i}"), float(i)) for i in range(5)]
    message = PlanesMessageBuilder(builder, FixedSpeech(), HOME, 3.0, 2, Zone(HOME, 9.0), 10, Services({})).build(sightings, [])
    assert message["type"] == "planes"
    assert message["radiusKm"] == 3.0
    assert message["home"] == {"lat": HOME.lat, "lon": HOME.lon}
    assert message["speech"] == "speech/p0.wav"
    assert message["total"] == 5
    assert [card["hex"] for card in message["planes"]] == ["p0", "p1"]
    assert message["others"] == []


def test_message_marks_the_other_planes_around_for_the_map():
    builder = CardBuilder(StubRoutes(None), StubPhotos(None), AircraftNames(), Services({}), logging.getLogger("t"))
    nearest = plane("near", lat=HOME.lat + 0.001)
    also_in_zone = plane("second", lat=HOME.lat + 0.02, track_deg=90.0)
    outside_zone = plane("outside", lat=HOME.lat + 0.05)
    far_away = plane("far", lat=HOME.lat + 0.5)
    landed = plane("landed", lat=HOME.lat + 0.01, on_ground=True)
    sky = [far_away, outside_zone, also_in_zone, nearest, landed]
    zone = Zone(HOME, 3.0)
    builder = PlanesMessageBuilder(builder, FixedSpeech(), HOME, 3.0, 2, Zone(HOME, 9.0), 10, Services({}))
    message = builder.build(zone.sightings(sky), sky)
    assert message["others"] == [
        {
            "hex": "second",
            "lat": round(HOME.lat + 0.02, 5),
            "lon": HOME.lon,
            "trackDeg": 90.0,
            "category": None,
            "typeCode": "A320",
            "service": None,
        },
        {
            "hex": "outside",
            "lat": round(HOME.lat + 0.05, 5),
            "lon": HOME.lon,
            "trackDeg": 270.0,
            "category": None,
            "typeCode": "A320",
            "service": None,
        },
    ]


def test_message_keeps_only_the_nearest_others():
    builder = CardBuilder(StubRoutes(None), StubPhotos(None), AircraftNames(), Services({}), logging.getLogger("t"))
    sky = [plane(f"p{i}", lat=HOME.lat + 0.001 * (i + 1)) for i in range(6)]
    message = PlanesMessageBuilder(builder, FixedSpeech(), HOME, 3.0, 1, Zone(HOME, 9.0), 3, Services({})).build(
        Zone(HOME, 3.0).sightings(sky), sky
    )
    assert [other["hex"] for other in message["others"]] == ["p1", "p2", "p3"]


def test_no_photos_stands_in_when_the_service_is_off():
    assert NoPhotos().photo("G-EUYM") is None


def test_no_routes_stands_in_when_the_service_is_off():
    assert NoRoutes().route("BAW86S") is None


SERVICES = Services({"HLE": Service("Air ambulance", "ambulance"), "UKP": Service("Police", "police")})


def test_a_police_helicopter_is_named_without_a_route():
    builder = CardBuilder(StubRoutes(None), StubPhotos(None), AircraftNames(), SERVICES, logging.getLogger("t"))
    card = builder.card(Sighting(plane(callsign="UKP15", category="A7", description="EUROCOPTER EC-135"), 1.0))
    assert card["airline"] == "Police"
    assert card["service"] == "police"
    assert card["airlineCode"] == "UKP"
    assert card["helicopter"]
    assert card["category"] == "A7"
    assert card["aircraft"] == "Eurocopter EC-135"


def test_an_air_ambulance_never_takes_flightawares_guess_at_a_route():
    routes = StubRoutes(error=AssertionError("asked FlightAware for a route"))
    card = CardBuilder(routes, StubPhotos(None), AircraftNames(), SERVICES, logging.getLogger("t")).card(
        Sighting(plane(callsign="HLE27", category="A7"), 1.0)
    )
    assert card["airline"] == "Air ambulance"
    assert card["service"] == "ambulance"
    assert card["origin"] is None


def test_the_map_marks_emergency_services_among_the_other_planes():
    builder = CardBuilder(StubRoutes(None), StubPhotos(None), AircraftNames(), SERVICES, logging.getLogger("t"))
    sky = [plane("near", lat=HOME.lat + 0.001), plane("police", lat=HOME.lat + 0.002, callsign="UKP15")]
    message = PlanesMessageBuilder(builder, FixedSpeech(), HOME, 3.0, 1, Zone(HOME, 9.0), 3, SERVICES).build(
        Zone(HOME, 3.0).sightings(sky), sky
    )
    assert [(other["hex"], other["service"]) for other in message["others"]] == [("police", "police")]


def test_airline_codes_come_only_from_airline_callsigns():
    assert airline_code("BAW86S") == "BAW"
    assert airline_code("EZY41ZQ") == "EZY"
    assert airline_code("GEUYM") is None
    assert airline_code(None) is None


def test_aircraft_names_read_like_people_say_them():
    names = AircraftNames()
    assert names.tidy("AIRBUS A-380-800") == "Airbus A380-800"
    assert names.tidy("AIRBUS A-320neo") == "Airbus A320neo"
    assert names.tidy("BOEING 737 MAX 8") == "Boeing 737 MAX 8"
    assert names.tidy("BOEING 787-9 Dreamliner") == "Boeing 787-9 Dreamliner"
    assert names.tidy("ATR ATR-72-600") == "ATR 72-600"
    assert names.tidy("EMBRAER ERJ-190-100") == "Embraer ERJ-190-100"
    assert names.tidy(None) is None


def test_airports_are_named_by_the_city_people_would_say():
    cities = AirportCities({"HEL": "Helsinki"})
    assert cities.tidy(Airport("HEL", "Vantaa", "Vantaa")).city == "Helsinki"
    assert cities.tidy(Airport("TRN", "Caselle", "Turin (Torino)")).city == "Turin"
    assert cities.tidy(Airport("AMS", "Schiphol", "Amsterdam")).city == "Amsterdam"
    assert cities.tidy(Airport("XXX", None, None)).city is None


def test_airports_know_their_country_from_the_bundled_table():
    countries = AirportCountries.bundled()
    assert countries.tidy(Airport("HEL", "Vantaa", "Helsinki")).country == "FI"
    assert countries.tidy(Airport("LTN", "Luton", "London")).country == "GB"
    assert countries.tidy(Airport(None, "Somewhere", None)).country is None


def test_airports_know_where_they_are_from_the_bundled_table():
    places = AirportPlaces.bundled()
    heathrow = places.tidy(Airport("LHR", "Heathrow", "London"))
    assert round(heathrow.lat or 0, 1) == 51.5 and round(heathrow.lon or 0, 1) == -0.5
    assert places.tidy(Airport(None, "Somewhere", None)).lat is None


def test_routes_come_back_with_their_airports_tidied():
    route = Route("Finnair", "AY1331", Airport("HEL", "Vantaa", "Vantaa"), Airport("LHR", "Heathrow", "London"))
    tidied = TidiedRoutes(StubRoutes(route), [AirportCities({"HEL": "Helsinki"}), AirportCountries({"HEL": "FI", "LHR": "GB"})])
    assert tidied.route("FIN7GK").origin == Airport("HEL", "Vantaa", "Helsinki", "FI")
    assert tidied.route("FIN7GK").destination == Airport("LHR", "Heathrow", "London", "GB")
    assert TidiedRoutes(StubRoutes(None), []).route("FIN7GK") is None


def test_home_country_comes_from_the_nearest_airport():
    near = NearestAirportCountry({"LCY": [51.505, 0.055], "CDG": [49.01, 2.55]}, {"LCY": "GB", "CDG": "FR"})
    assert near.of(HOME) == "GB"
    assert near.of(Location(48.86, 2.35)) == "FR"
    assert NearestAirportCountry({}, {}).of(HOME) is None
    assert NearestAirportCountry.bundled().of(Location(40.71, -74.0)) == "US"


def test_military_planes_are_a_service_named_by_who_flies_them():
    raf = plane("raf", callsign="RRR4321", military=True, operator="Royal Air Force")
    finder = FirstService([Services({"HLE": Service("Air ambulance", "ambulance")}), MilitaryService()])
    assert finder.of(raf) == Service("Royal Air Force", "military")
    assert finder.of(plane("unnamed", military=True, operator=None)) == Service("Military aircraft", "military")
    assert finder.of(plane("hems", callsign="HLE27")) == Service("Air ambulance", "ambulance")
    assert finder.of(plane()) is None


def test_an_answer_with_no_route_in_it_is_no_route():
    for answer in ({"response": "unknown callsign"}, {"response": {"flightroute": None}}):
        assert AdsbdbRouteLookup("https://adsbdb.test/v0", FakeHttp({ROUTE_URL: answer})).route("BAW86S") is None


def test_a_route_missing_an_airport_keeps_the_airport_empty():
    flightroute = {key: value for key, value in ADSBDB_ANSWER["response"]["flightroute"].items() if key != "origin"}
    route = AdsbdbRouteLookup("https://adsbdb.test/v0", FakeHttp({ROUTE_URL: {"response": {"flightroute": flightroute}}})).route("BAW86S")
    assert route.origin is None
    assert TidiedRoutes(StubRoutes(route), [AirportCities({})]).route("BAW86S").origin is None


def test_a_photo_without_an_image_is_no_photo():
    answer = FakeHttp({PHOTO_URL: {"photos": [{"photographer": "Borut Smrdelj", "thumbnail_large": {}}]}})
    assert PlanespottersPhotoLookup("https://planespotters.test/pub", answer).photo("G-EUYM") is None
