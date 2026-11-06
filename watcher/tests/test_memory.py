import logging
from datetime import datetime, timedelta

import pytest

from fakes import FakeClock
from flights_watcher.caching import CachedRouteLookup, TtlCache
from flights_watcher.lookups import Airport, LookupFailed, Route
from flights_watcher.memory import (
    AllFresh,
    KeptRouteLookup,
    Memory,
    RememberedOperatorNames,
    RememberedRouteLookup,
    SameTimetable,
    SqliteAnswerStore,
    YoungerThan,
)

LOG = logging.getLogger("t")
BA879 = Route(
    "British Airways",
    "BA879",
    Airport("OTP", "Henri Coanda International", "Bucharest"),
    Airport("LHR", "London Heathrow", "London"),
)


class StubRoutes:
    def __init__(self, answer: Route | None = BA879) -> None:
        self.answer: Route | Exception | None = answer
        self.asked = 0

    def route(self, callsign: str) -> Route | None:
        self.asked += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def remembered(tmp_path, clock, inner, freshness=None):
    store = SqliteAnswerStore(str(tmp_path / "lookups.sqlite3"), "route", LOG)
    return RememberedRouteLookup(inner, Memory(store, freshness or YoungerThan(timedelta(days=7)), clock, LOG))


def test_a_kept_route_is_used_without_asking_for_a_week(tmp_path):
    clock, inner = FakeClock(), StubRoutes()
    assert remembered(tmp_path, clock, inner).route("BAW879") == BA879
    clock.at += timedelta(days=6)
    assert remembered(tmp_path, clock, StubRoutes(None)).route("BAW879") == BA879
    assert inner.asked == 1


def test_a_stale_route_is_asked_for_again_and_replaced(tmp_path):
    clock = FakeClock()
    remembered(tmp_path, clock, StubRoutes()).route("BAW879")
    clock.at += timedelta(days=8)
    moved = Route("British Airways", "BA879", BA879.origin, Airport("LGW", "London Gatwick", "London"))
    inner = StubRoutes(moved)
    assert remembered(tmp_path, clock, inner).route("BAW879") == moved
    assert remembered(tmp_path, clock, StubRoutes(None)).route("BAW879") == moved
    assert inner.asked == 1


def test_a_stale_route_stands_in_when_asking_fails_or_finds_nothing(tmp_path):
    clock = FakeClock()
    remembered(tmp_path, clock, StubRoutes()).route("BAW879")
    clock.at += timedelta(days=30)
    assert remembered(tmp_path, clock, StubRoutes(LookupFailed("budget spent"))).route("BAW879") == BA879
    assert remembered(tmp_path, clock, StubRoutes(None)).route("BAW879") == BA879


def test_with_nothing_kept_a_failure_still_fails_and_nothing_is_none(tmp_path):
    clock = FakeClock()
    with pytest.raises(LookupFailed):
        remembered(tmp_path, clock, StubRoutes(LookupFailed("down"))).route("BAW879")
    inner = StubRoutes(None)
    assert remembered(tmp_path, clock, inner).route("HCR10") is None
    assert remembered(tmp_path, clock, inner).route("HCR10") is None
    assert inner.asked == 2


def test_a_route_missing_an_end_is_given_but_not_kept(tmp_path):
    clock = FakeClock()
    positioning = Route("Swiss", "LX3EZ", Airport("LUX", "Luxembourg", "Luxembourg"), None)
    assert remembered(tmp_path, clock, StubRoutes(positioning)).route("SWR3EZ") == positioning
    assert remembered(tmp_path, clock, StubRoutes(None)).route("SWR3EZ") is None


def test_a_one_off_flight_does_not_replace_the_kept_route(tmp_path):
    clock = FakeClock()
    remembered(tmp_path, clock, StubRoutes()).route("BAW879")
    clock.at += timedelta(days=8)
    one_off = Route("British Airways", "BA879", BA879.origin, None)
    assert remembered(tmp_path, clock, StubRoutes(one_off)).route("BAW879") == one_off
    assert remembered(tmp_path, clock, StubRoutes(LookupFailed("down"))).route("BAW879") == BA879


def test_operator_names_are_kept_too(tmp_path):
    class Names:
        asked = 0

        def name(self, icao):
            Names.asked += 1
            return "British Airways"

    clock = FakeClock()
    memory = Memory(SqliteAnswerStore(str(tmp_path / "a.sqlite3"), "operator", LOG), YoungerThan(timedelta(days=365)), clock, LOG)
    assert RememberedOperatorNames(Names(), memory).name("BAW") == "British Airways"
    assert RememberedOperatorNames(Names(), memory).name("BAW") == "British Airways"
    assert Names.asked == 1


def test_routes_and_operators_share_a_file_without_mixing(tmp_path):
    path, now = str(tmp_path / "a.sqlite3"), datetime(2026, 11, 2, 9, 0)
    SqliteAnswerStore(path, "route", LOG).put("BAW", {"x": 1}, now)
    assert SqliteAnswerStore(path, "operator", LOG).get("BAW") is None
    assert SqliteAnswerStore(path, "route", LOG).get("BAW").value == {"x": 1}


def test_an_unreadable_file_counts_as_empty(tmp_path):
    (tmp_path / "broken.sqlite3").write_text("not a database")
    store = SqliteAnswerStore(str(tmp_path / "broken.sqlite3"), "route", LOG)
    assert store.get("BAW879") is None
    store.put("BAW879", {}, datetime(2026, 11, 2))


def test_the_timetable_changeover_makes_routes_stale():
    rule = SameTimetable()
    # Winter timetables started on Sunday 25 October 2026; summer ones start on 28 March 2027.
    assert rule.is_fresh(datetime(2026, 10, 25, 9), datetime(2026, 11, 2, 9))
    assert not rule.is_fresh(datetime(2026, 10, 24, 9), datetime(2026, 10, 25, 9))
    assert rule.is_fresh(datetime(2027, 3, 27, 9), datetime(2027, 3, 27, 23))
    assert not rule.is_fresh(datetime(2027, 3, 27, 9), datetime(2027, 3, 28, 9))
    assert not rule.is_fresh(datetime(2025, 12, 1), datetime(2026, 11, 2))


def test_all_fresh_needs_every_rule():
    week = YoungerThan(timedelta(days=7))
    both = AllFresh([week, SameTimetable()])
    assert both.is_fresh(datetime(2026, 10, 26), datetime(2026, 11, 1))
    assert not both.is_fresh(datetime(2026, 10, 24), datetime(2026, 10, 26))
    assert not both.is_fresh(datetime(2026, 11, 1), datetime(2026, 11, 9))


def test_the_memory_cache_asks_again_about_nothing_sooner_than_a_route():
    clock = FakeClock()
    inner = StubRoutes(None)
    routes = CachedRouteLookup(inner, TtlCache(clock, 6 * 3600, 10, 600))
    routes.route("BAW879")
    clock.seconds = 601
    inner.answer = BA879
    assert routes.route("BAW879") == BA879
    clock.seconds = 601 + 3600
    assert routes.route("BAW879") == BA879
    assert inner.asked == 2


def test_a_kept_route_is_given_however_old_without_ever_asking(tmp_path):
    clock = FakeClock()
    store = SqliteAnswerStore(str(tmp_path / "lookups.sqlite3"), "route", LOG)
    kept = KeptRouteLookup(store)
    assert kept.route("BAW879") is None
    remembered(tmp_path, clock, StubRoutes()).route("BAW879")
    clock.at += timedelta(days=60)
    assert kept.route("BAW879") == BA879
