from datetime import datetime

import pytest

from fakes import FakeClock, FakeHttp, http_error
from flights_watcher.budget import BudgetedHttp, BudgetSpent, MonthlyBudget
from flights_watcher.caching import CachedOperatorNames, TtlCache
from flights_watcher.flightaware import AeroApiOperatorNames, AeroApiRouteLookup
from flights_watcher.lookups import Airport, LookupFailed, Route

BASE = "https://aeroapi.test/aeroapi"
FLIGHTS_URL = f"{BASE}/flights/EWG6U?ident_type=designator&max_pages=1"
OPERATOR_URL = f"{BASE}/operators/EWG"
BERLIN = {"code": "EDDB", "code_icao": "EDDB", "code_iata": "BER", "name": "Berlin Brandenburg", "city": "Berlin / Brandenburg Berlin"}
HEATHROW = {"code": "EGLL", "code_icao": "EGLL", "code_iata": "LHR", "name": "London Heathrow", "city": "London"}
FLIGHTS = {
    "flights": [
        {"ident_iata": "EW8462", "operator_icao": "EWG", "origin": HEATHROW, "destination": BERLIN, "actual_off": None, "actual_on": None},
        {
            "ident_iata": "EW8461",
            "operator_icao": "EWG",
            "origin": BERLIN,
            "destination": HEATHROW,
            "actual_off": "2026-11-02T08:05:00Z",
            "actual_on": None,
        },
        {
            "ident_iata": "EW8461",
            "operator_icao": "EWG",
            "origin": BERLIN,
            "destination": HEATHROW,
            "actual_off": "2026-11-01T08:04:00Z",
            "actual_on": "2026-11-01T09:10:00Z",
        },
    ]
}


def lookup(answers):
    http = FakeHttp(answers)
    return AeroApiRouteLookup(BASE + "/", http, AeroApiOperatorNames(BASE, http), ("EZY",)), http


def test_the_flight_in_the_air_gives_the_real_number_and_direction():
    routes, _ = lookup({FLIGHTS_URL: FLIGHTS, OPERATOR_URL: {"name": "Eurowings GmbH", "shortname": "Eurowings"}})
    assert routes.route("EWG6U") == Route(
        airline="Eurowings",
        flight_number="EW8461",
        origin=Airport("BER", "Berlin Brandenburg", "Berlin"),
        destination=Airport("LHR", "London Heathrow", "London"),
    )


def test_easyjet_flights_keep_their_ezy_number():
    url = f"{BASE}/flights/EZY47FG?ident_type=designator&max_pages=1"
    flight = {**FLIGHTS["flights"][1], "operator_icao": "EZY", "ident_iata": "U2839", "ident_icao": "EZY839"}
    routes, _ = lookup({url: {"flights": [flight]}, f"{BASE}/operators/EZY": {"shortname": "easyJet"}})
    assert routes.route("EZY47FG").flight_number == "EZY839"


def test_no_flight_in_the_air_or_an_unknown_callsign_is_no_route():
    landed = {"flights": [FLIGHTS["flights"][0], FLIGHTS["flights"][2]]}
    assert lookup({FLIGHTS_URL: landed})[0].route("EWG6U") is None
    assert lookup({FLIGHTS_URL: http_error(404)})[0].route("EWG6U") is None
    # A registration flown as a callsign is no designator, and AeroAPI says so with a 400.
    assert lookup({FLIGHTS_URL: http_error(400)})[0].route("EWG6U") is None


def test_an_outage_or_a_refused_key_is_a_failure():
    for code in (401, 503):
        with pytest.raises(LookupFailed):
            lookup({FLIGHTS_URL: http_error(code)})[0].route("EWG6U")


def test_operator_names_are_asked_for_once():
    http = FakeHttp({OPERATOR_URL: {"name": "Eurowings GmbH"}})
    names = CachedOperatorNames(AeroApiOperatorNames(BASE, http), TtlCache(FakeClock(), 60, 10))
    assert names.name("EWG") == names.name("EWG") == "Eurowings GmbH"
    assert http.requested == [OPERATOR_URL]


def test_the_monthly_budget_stops_lookups_and_survives_a_restart(tmp_path):
    clock = FakeClock(datetime(2026, 11, 30, 23, 0))
    http = FakeHttp({OPERATOR_URL: {"name": "Eurowings"}})
    budgeted = BudgetedHttp(http, MonthlyBudget(2, tmp_path / "aeroapi.json", clock))
    budgeted.get_json(OPERATOR_URL)
    restarted = BudgetedHttp(http, MonthlyBudget(2, tmp_path / "aeroapi.json", clock))
    restarted.get_json(OPERATOR_URL)
    with pytest.raises(BudgetSpent):
        restarted.get_json(OPERATOR_URL)
    assert len(http.requested) == 2
    clock.at = datetime(2026, 12, 1, 0, 0)
    restarted.get_json(OPERATOR_URL)
    assert len(http.requested) == 3


def test_an_operator_flightaware_does_not_know_has_no_name():
    http = FakeHttp({OPERATOR_URL: http_error(404)})
    assert AeroApiOperatorNames(BASE, http).name("EWG") is None


def test_a_dropped_connection_or_garbled_answer_is_a_failure():
    for error in (TimeoutError("no answer"), ValueError("not json")):
        with pytest.raises(LookupFailed):
            lookup({FLIGHTS_URL: error})[0].route("EWG6U")


def test_a_flight_without_airports_still_gives_its_number():
    flight = {**FLIGHTS["flights"][1], "origin": None, "destination": None}
    route = lookup({FLIGHTS_URL: {"flights": [flight]}, OPERATOR_URL: {"name": "Eurowings"}})[0].route("EWG6U")
    assert route.flight_number == "EW8461"
    assert route.origin is None and route.destination is None
