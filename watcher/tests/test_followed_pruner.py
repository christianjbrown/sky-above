import logging
import pathlib
import threading
from datetime import datetime

import pytest

from fakes import FakeClock
from flights_watcher import followed_pruner
from flights_watcher.followed_pruner import FollowedListPruner

LOG = logging.getLogger("test")
TODAY = datetime(2027, 3, 10, 9, 0)
LIST = (
    "# Flights to follow\n"
    "2027-03-07 BA111\n"
    "2027-03-08 BA222  # two days ago, may still be in the air somewhere\n"
    "\n"
    "not a flight\n"
    "2027-03-12 BA333\n"
)


def pruner(path: pathlib.Path) -> FollowedListPruner:
    return FollowedListPruner(path, FakeClock(TODAY), LOG)


def test_flights_that_are_over_are_taken_off_and_everything_else_is_left_alone(tmp_path, caplog):
    path = tmp_path / "flights.txt"
    path.write_text(LIST)
    path.chmod(0o640)
    caplog.set_level(logging.INFO)
    assert pruner(path).prune() == ["2027-03-07 BA111\n"]
    assert path.read_text() == LIST.replace("2027-03-07 BA111\n", "")
    assert path.stat().st_mode & 0o777 == 0o640
    assert "2027-03-07 BA111 is over" in caplog.text
    assert [p.name for p in tmp_path.iterdir()] == ["flights.txt"]


def test_a_list_with_nothing_over_is_not_rewritten(tmp_path):
    path = tmp_path / "flights.txt"
    path.write_text("2027-03-12 BA333")
    before = path.stat().st_ino
    assert pruner(path).prune() == []
    assert path.stat().st_ino == before


def test_a_missing_list_is_nothing_to_do(tmp_path):
    assert pruner(tmp_path / "missing.txt").prune() == []


def test_a_list_that_cannot_be_read_is_complained_about(tmp_path, caplog):
    assert pruner(tmp_path).prune() == []
    assert "cannot read" in caplog.text


def test_a_list_that_cannot_be_rewritten_is_left_as_it_was(tmp_path, caplog, monkeypatch):
    path = tmp_path / "flights.txt"
    path.write_text(LIST)

    def refuse(*_: object) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(pathlib.Path, "replace", refuse)
    assert pruner(path).prune() == []
    assert path.read_text() == LIST
    assert "cannot rewrite" in caplog.text
    assert [p.name for p in tmp_path.iterdir()] == ["flights.txt"]


def test_main_prunes_at_start_and_then_every_few_hours_until_told_to_stop(tmp_path, monkeypatch):
    path = tmp_path / "flights.txt"
    path.write_text("2000-01-01 BA111\n")
    prunes = []
    real = FollowedListPruner.prune
    monkeypatch.setattr(followed_pruner, "CHECK_EVERY_SECONDS", 0)
    monkeypatch.setattr(followed_pruner.signal, "signal", lambda *_: None)
    stop = threading.Event()

    def counted(self: FollowedListPruner) -> list[str]:
        prunes.append(1)
        if len(prunes) == 2:
            stop.set()
        return real(self)

    monkeypatch.setattr(FollowedListPruner, "prune", counted)
    followed_pruner.main({"FOLLOWED_FILE": str(path), "TZ": "Europe/London"}, stop)
    assert prunes == [1, 1]
    assert path.read_text() == ""


@pytest.mark.parametrize("signum", [followed_pruner.signal.SIGTERM, followed_pruner.signal.SIGINT])
def test_main_stops_on_sigterm_or_sigint(tmp_path, monkeypatch, signum):
    handlers = {}
    monkeypatch.setattr(followed_pruner.signal, "signal", lambda s, handler: handlers.update({s: handler}))
    stop = threading.Event()
    stop.set()
    followed_pruner.main({"FOLLOWED_FILE": str(tmp_path / "flights.txt")}, stop)
    stop.clear()
    handlers[signum](signum, None)
    assert stop.is_set()
