import logging
from datetime import UTC, datetime, timedelta

from fakes import FakeClock
from fakes import plane as fake_plane
from flights_watcher.status import AllObservers, DailyTally, HeardSource, WatchStatus
from flights_watcher.zone import Sighting

LOG = logging.getLogger("test")
NOON = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def sighting(hex_code: str) -> Sighting:
    return Sighting(fake_plane(hex_code), 1.0)


def test_a_status_says_when_the_watcher_last_looked_and_since_when_it_has_been_failing():
    clock = FakeClock(NOON)
    status = WatchStatus(clock)
    assert status.latest() == {
        "lastLook": None,
        "failingSince": None,
        "failure": None,
        "aircraft": 0,
        "aircraftHeardAt": None,
        "planesToday": 0,
    }
    status.looked("ConnectionError: Hub gone")
    clock.at += timedelta(minutes=1)
    status.looked("TimeoutError: still gone")
    latest = status.latest()
    assert latest["lastLook"] == (NOON + timedelta(minutes=1)).isoformat()
    assert latest["failingSince"] == NOON.isoformat()
    assert latest["failure"] == "TimeoutError: still gone"
    status.looked(None)
    assert status.latest()["failingSince"] is None and status.latest()["failure"] is None


def test_the_antenna_is_heard_through_the_aircraft_each_look_finds():
    clock = FakeClock(NOON)
    status = WatchStatus(clock)

    class Source:
        def __init__(self, *found) -> None:
            self.found = list(found)

        def aircraft(self):
            return self.found

    assert HeardSource(Source(fake_plane("a"), fake_plane("b")), status).aircraft()
    clock.at += timedelta(minutes=5)
    HeardSource(Source(), status).aircraft()
    assert status.latest()["aircraft"] == 0
    assert status.latest()["aircraftHeardAt"] == NOON.isoformat()


def test_each_plane_is_counted_once_a_day_and_the_day_is_logged_when_it_ends(caplog):
    clock = FakeClock(NOON)
    status = WatchStatus(clock)
    tally = DailyTally(status, clock, LOG)
    tally.note([sighting("a"), sighting("b")])
    tally.note([sighting("a")])
    assert status.latest()["planesToday"] == 2
    clock.at += timedelta(days=1)
    with caplog.at_level(logging.INFO, logger="test"):
        tally.note([sighting("c")])
    assert "2 planes came by on 2026-11-01" in caplog.text
    assert status.latest()["planesToday"] == 1


def test_every_observer_sees_each_look():
    seen: list[list[str]] = []

    class Observer:
        def note(self, sightings) -> None:
            seen.append([s.aircraft.hex for s in sightings])

    AllObservers([Observer(), Observer()]).note([sighting("a")])
    assert seen == [["a"], ["a"]]
