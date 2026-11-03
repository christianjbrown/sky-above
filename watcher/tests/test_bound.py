import logging

import pytest

from fakes import HOME
from fakes import plane as fake_plane
from flights_watcher.bound import DestinationBound, SameWay
from flights_watcher.lookups import Airport, LookupFailed, Route

LOGGER = logging.getLogger("test")


class Routes:
    def __init__(self, route: Route | None = None, fail: bool = False) -> None:
        self._route = route
        self._fail = fail
        self.asked: list[str] = []

    def route(self, callsign: str) -> Route | None:
        self.asked.append(callsign)
        if self._fail:
            raise LookupFailed("no answer")
        return self._route


def to(lat: float | None, lon: float | None) -> Route:
    return Route("British Airways", "BA784", Airport("LHR", "Heathrow", "London"), Airport("ARN", "Arlanda", "Stockholm", "SE", lat, lon))


def test_a_plane_is_bound_the_way_of_its_destination_along_the_great_circle():
    bound = DestinationBound(Routes(to(59.65, 17.92)), HOME, LOGGER)
    # Stockholm is east-north-east on a flat map, but the shortest way there leaves London north-east.
    assert bound.of(fake_plane("one")) == pytest.approx(HOME.bearing_deg(HOME.__class__(59.65, 17.92)))
    assert 40 < bound.of(fake_plane("one")) < 60


def test_a_plane_with_no_callsign_is_not_looked_up():
    routes = Routes(to(59.65, 17.92))
    assert DestinationBound(routes, HOME, LOGGER).of(fake_plane("one", callsign=None)) is None
    assert routes.asked == []


@pytest.mark.parametrize("route", [None, Route("British Airways", "BA784", None, None), to(None, None)])
def test_a_plane_whose_destination_or_where_it_is_is_not_known_is_bound_nowhere_known(route):
    assert DestinationBound(Routes(route), HOME, LOGGER).of(fake_plane("one")) is None


def test_a_failed_lookup_is_logged_and_bound_nowhere_known(caplog):
    with caplog.at_level(logging.WARNING, logger="test"):
        assert DestinationBound(Routes(fail=True), HOME, LOGGER).of(fake_plane("one")) is None
    assert "lookup for BAW86S failed" in caplog.text


def test_planes_are_bound_the_same_way_within_the_given_degrees_across_north_too():
    way = SameWay(within_deg=30)
    assert way.alike(10.0, 35.0)
    assert way.alike(350.0, 15.0)
    assert not way.alike(10.0, 100.0)
    assert way.alike(None, 100.0) and way.alike(10.0, None)
