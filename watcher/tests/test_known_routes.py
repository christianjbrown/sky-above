from datetime import datetime, timedelta

from fakes import FakeClock
from flights_watcher.known_routes import KnownRoutesPage
from flights_watcher.lookups import Airport, LookupFailed, Route

NOW = datetime(2026, 11, 13, 12, 0)
BA879 = Route(
    "British Airways", "BA879", Airport("OTP", "Henri Coanda International", "Bucharest", "RO"), Airport("LHR", "Heathrow", "London", "GB")
)


class Saved:
    def saved(self):
        return [
            ("BAW879", NOW - timedelta(days=1)),
            ("EZY1", NOW - timedelta(days=30)),
            ("GONE1", NOW),
            ("FAIL1", NOW),
        ]


class Routes:
    def route(self, callsign):
        if callsign == "FAIL1":
            raise LookupFailed("broken")
        return {"BAW879": BA879, "EZY1": Route("easyJet", None, None, Airport("ALC", None, "Alicante"))}.get(callsign)


class YoungerThanAWeek:
    def is_fresh(self, saved_at, now):
        return now - saved_at < timedelta(days=7)


def test_each_kept_route_is_listed_with_its_airports_and_whether_it_is_still_trusted():
    page = KnownRoutesPage(Saved(), Routes(), YoungerThanAWeek(), FakeClock(NOW)).latest()
    assert page == {
        "routes": [
            {
                "callsign": "BAW879",
                "flight_number": "BA879",
                "airline": "British Airways",
                "origin": {"code": "OTP", "name": "Henri Coanda International", "city": "Bucharest", "country": "RO"},
                "destination": {"code": "LHR", "name": "Heathrow", "city": "London", "country": "GB"},
                "saved_at": "2026-11-12T12:00:00",
                "fresh": True,
            },
            {
                "callsign": "EZY1",
                "flight_number": None,
                "airline": "easyJet",
                "origin": None,
                "destination": {"code": "ALC", "name": None, "city": "Alicante", "country": None},
                "saved_at": "2026-10-14T12:00:00",
                "fresh": False,
            },
        ]
    }
