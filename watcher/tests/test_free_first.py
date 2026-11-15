import logging
import math
from datetime import timedelta

import pytest

from fakes import FakeClock, FakeHttp, http_error, plane
from flights_watcher.free_first import ByCallsign, FirstOperatorName, FreeFirstRoutes
from flights_watcher.geo import Location
from flights_watcher.lookups import AdsbdbOperatorNames, AdsbdbRouteLookup, Airport, LookupFailed, NoOperatorNames, Route
from flights_watcher.memory import FreshKeptRoutes, KeptRoutes, NeverFresh, SqliteAnswerStore, YoungerThan
from flights_watcher.route_fit import OnTheWay, off_path_km

LOG = logging.getLogger("t")
GATWICK = Location(51.148, -0.190)
DOUGLAS = Location(54.083, -4.624)
OUT = Route(
    "easyJet",
    "EZY839",
    Airport("LGW", "Gatwick", "London", "GB", *vars(GATWICK).values()),
    Airport("IOM", "Ronaldsway", "Douglas", "IM", *vars(DOUGLAS).values()),
)
BACK = Route("easyJet", "EZY840", OUT.destination, OUT.origin)
FIT = OnTheWay(path_km=50, airport_km=80, heading_deg=90, level_fpm=500)


def between(start: Location, end: Location, fraction: float) -> Location:
    """The point fraction of the way along the great circle from start to end."""

    def vector(at: Location) -> tuple[float, float, float]:
        lat, lon = math.radians(at.lat), math.radians(at.lon)
        return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)

    a, b = vector(start), vector(end)
    x, y, z = (p + (q - p) * fraction for p, q in zip(a, b, strict=True))
    return Location(math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x)))


def flying(at: Location, track: float | None = None, rate: int | None = 0, callsign: str = "EZY839"):
    return plane(lat=at.lat, lon=at.lon, track_deg=track, vertical_rate_fpm=rate, callsign=callsign)


MIDWAY = between(GATWICK, DOUGLAS, 0.5)
TOWARDS_DOUGLAS = MIDWAY.bearing_deg(DOUGLAS)


def test_off_path_is_the_distance_to_the_stretch_between_the_ends():
    assert off_path_km(GATWICK, DOUGLAS, MIDWAY) < 1
    behind = Location(50.0, 1.5)
    assert off_path_km(GATWICK, DOUGLAS, behind) == pytest.approx(GATWICK.distance_km(behind))
    beyond = Location(55.0, -6.0)
    assert off_path_km(GATWICK, DOUGLAS, beyond) == pytest.approx(DOUGLAS.distance_km(beyond))
    aside = Location(MIDWAY.lat, MIDWAY.lon + 2)
    assert 100 < off_path_km(GATWICK, DOUGLAS, aside) < MIDWAY.distance_km(aside) + 1


def test_a_route_fits_a_plane_on_its_way_along_it():
    assert FIT.fits(OUT, flying(MIDWAY, TOWARDS_DOUGLAS))
    assert FIT.fits(OUT, flying(MIDWAY, None))


def test_the_other_leg_of_a_round_trip_does_not_fit_out_in_the_open():
    assert not FIT.fits(BACK, flying(MIDWAY, TOWARDS_DOUGLAS))


def test_a_route_far_from_the_plane_does_not_fit():
    assert not FIT.fits(OUT, flying(Location(48.86, 2.35), 330))


def test_near_an_airport_the_climb_or_descent_says_which_leg():
    leaving = between(GATWICK, DOUGLAS, 0.05)
    assert FIT.fits(OUT, flying(leaving, 0, rate=2000))
    assert FIT.fits(OUT, flying(leaving, 0, rate=None))
    assert not FIT.fits(OUT, flying(leaving, 0, rate=-1500))
    arriving = between(GATWICK, DOUGLAS, 0.95)
    assert FIT.fits(OUT, flying(arriving, 180, rate=-1200))
    assert not FIT.fits(OUT, flying(arriving, 180, rate=2000))


def test_a_route_that_cannot_be_checked_does_not_fit():
    unplaced = Route("easyJet", "EZY839", Airport("LGW", "Gatwick", "London"), OUT.destination)
    assert not FIT.fits(unplaced, flying(MIDWAY, TOWARDS_DOUGLAS))
    assert not FIT.fits(Route("easyJet", "EZY839", None, OUT.destination), flying(MIDWAY))
    assert not FIT.fits(OUT, plane(location=None, callsign="EZY839"))


class Routes:
    def __init__(self, answer: Route | Exception | None) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def route(self, callsign: str) -> Route | None:
        self.asked.append(callsign)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class Keeper:
    def __init__(self) -> None:
        self.kept: list[tuple[str, Route]] = []

    def keep(self, callsign: str, route: Route) -> None:
        self.kept.append((callsign, route))


def free_first(kept, free, paid, keeper=None):
    return FreeFirstRoutes(kept, free, paid, keeper or Keeper(), FIT, LOG)


def test_a_kept_route_that_fits_costs_nothing():
    free, paid = Routes(BACK), Routes(BACK)
    assert free_first(Routes(OUT), free, paid).route_of(flying(MIDWAY, TOWARDS_DOUGLAS)) == OUT
    assert free.asked == paid.asked == []


def test_a_free_route_that_fits_is_used_and_kept():
    keeper, paid = Keeper(), Routes(BACK)
    assert free_first(Routes(BACK), Routes(OUT), paid, keeper).route_of(flying(MIDWAY, TOWARDS_DOUGLAS)) == OUT
    assert keeper.kept == [("EZY839", OUT)]
    assert paid.asked == []


def test_the_paid_lookup_answers_when_nothing_free_fits():
    keeper, paid = Keeper(), Routes(OUT)
    assert free_first(Routes(None), Routes(BACK), paid, keeper).route_of(flying(MIDWAY, TOWARDS_DOUGLAS)) == OUT
    assert paid.asked == ["EZY839"]
    assert keeper.kept == []


def test_a_failed_free_lookup_falls_through_to_the_paid_one(caplog):
    paid = Routes(OUT)
    assert free_first(Routes(None), Routes(LookupFailed("down")), paid).route_of(flying(MIDWAY, TOWARDS_DOUGLAS)) == OUT
    assert "free route lookup for EZY839 failed" in caplog.text


def test_a_plane_with_no_callsign_has_no_route():
    paid = Routes(OUT)
    assert free_first(Routes(OUT), Routes(OUT), paid).route_of(plane(callsign=None)) is None
    assert ByCallsign(paid).route_of(plane(callsign=None)) is None
    assert paid.asked == []


def test_without_a_paid_lookup_the_free_route_is_used_unchecked():
    assert ByCallsign(Routes(BACK)).route_of(flying(MIDWAY, TOWARDS_DOUGLAS)) == BACK


class Names:
    def __init__(self, answer: str | Exception | None) -> None:
        self.answer = answer

    def name(self, icao: str) -> str | None:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_an_airline_name_comes_free_first(caplog):
    assert FirstOperatorName(Names("Royal Air Force"), Names(AssertionError("paid")), LOG).name("RRR") == "Royal Air Force"
    assert FirstOperatorName(Names(None), Names("easyJet"), LOG).name("EZY") == "easyJet"
    assert FirstOperatorName(Names(LookupFailed("down")), Names("easyJet"), LOG).name("EZY") == "easyJet"
    assert "free airline lookup for EZY failed" in caplog.text
    assert NoOperatorNames().name("EZY") is None


AIRLINE_URL = "https://adsbdb.test/v0/airline/RRR"


def test_adsbdb_names_airlines():
    names = AdsbdbOperatorNames(
        "https://adsbdb.test/v0/", FakeHttp({AIRLINE_URL: {"response": [{"name": "Royal Air Force", "icao": "RRR"}]}})
    )
    assert names.name("RRR") == "Royal Air Force"
    for answer in (http_error(404), {"response": []}, {"response": "unknown airline"}):
        assert AdsbdbOperatorNames("https://adsbdb.test/v0", FakeHttp({AIRLINE_URL: answer})).name("RRR") is None
    with pytest.raises(LookupFailed):
        AdsbdbOperatorNames("https://adsbdb.test/v0", FakeHttp({AIRLINE_URL: http_error(503)})).name("RRR")


def test_adsbdb_gives_icao_numbered_airlines_their_icao_flight_number():
    url = "https://adsbdb.test/v0/callsign/EZY839"
    found = {"callsign": "EZY839", "callsign_icao": "EZY839", "callsign_iata": "U2839", "airline": {"name": "easyJet", "icao": "EZY"}}
    answer = FakeHttp({url: {"response": {"flightroute": found}}})
    assert AdsbdbRouteLookup("https://adsbdb.test/v0", answer, ["EZY"]).route("EZY839").flight_number == "EZY839"
    assert AdsbdbRouteLookup("https://adsbdb.test/v0", answer, []).route("EZY839").flight_number == "U2839"
    no_iata = FakeHttp({url: {"response": {"flightroute": {"callsign": "EZY839", "airline": None}}}})
    assert AdsbdbRouteLookup("https://adsbdb.test/v0", no_iata, []).route("EZY839").flight_number == "EZY839"


def test_kept_routes_are_kept_with_both_ends_and_trusted_while_fresh(tmp_path):
    clock = FakeClock()
    store = SqliteAnswerStore(str(tmp_path / "lookups.sqlite3"), "route", LOG)
    keeper, fresh = KeptRoutes(store, clock), FreshKeptRoutes(store, YoungerThan(timedelta(days=7)), clock)
    keeper.keep("EZY839", OUT)
    keeper.keep("EZY99", Route("easyJet", "EZY99", None, OUT.destination))
    assert fresh.route("EZY839") == OUT
    assert fresh.route("EZY99") is None
    clock.at += timedelta(days=8)
    assert fresh.route("EZY839") is None
    assert not NeverFresh().is_fresh(clock.at, clock.at)
