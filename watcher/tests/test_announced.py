import logging
from datetime import timedelta

from fakes import FakeClock
from flights_watcher.announced import RememberedFlights

LOG = logging.getLogger("test")


def test_a_flight_announced_before_a_restart_is_still_announced_after_it(tmp_path):
    clock = FakeClock()
    RememberedFlights(tmp_path / "announced.json", timedelta(hours=6), clock, LOG).add("4ca7b5/BAW86S")
    again = RememberedFlights(tmp_path / "announced.json", timedelta(hours=6), clock, LOG)
    assert again.has("4ca7b5/BAW86S")
    assert not again.has("4ca7b5/BAW87T")


def test_a_flight_is_forgotten_once_its_time_is_up_and_dropped_from_the_file(tmp_path):
    clock = FakeClock()
    flights = RememberedFlights(tmp_path / "announced.json", timedelta(hours=6), clock, LOG)
    flights.add("old/EZY1")
    clock.at += timedelta(hours=6)
    assert not flights.has("old/EZY1")
    flights.add("new/EZY2")
    assert "old/EZY1" not in (tmp_path / "announced.json").read_text()


def test_a_missing_file_is_nothing_announced_and_a_broken_one_starts_again(tmp_path, caplog):
    assert not RememberedFlights(tmp_path / "none.json", timedelta(hours=6), FakeClock(), LOG).has("a/B1")
    (tmp_path / "broken.json").write_text("[not json")
    with caplog.at_level(logging.WARNING, logger="test"):
        assert not RememberedFlights(tmp_path / "broken.json", timedelta(hours=6), FakeClock(), LOG).has("a/B1")
    assert "could not read the announced flights" in caplog.text


def test_flights_that_cannot_be_written_down_are_still_remembered_until_a_restart(tmp_path, caplog):
    flights = RememberedFlights(tmp_path / "gone" / "announced.json", timedelta(hours=6), FakeClock(), LOG)
    with caplog.at_level(logging.WARNING, logger="test"):
        flights.add("a/B1")
    assert flights.has("a/B1")
    assert "could not keep the announced flights" in caplog.text
