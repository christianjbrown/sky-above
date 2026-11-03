import json
import logging
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from fakes import RecordingDisplay
from flights_watcher.display import FanOutDisplay, Stamped
from flights_watcher.live import LatestCard, LiveServer

LOG = logging.getLogger("test")
MESSAGE = {"type": "planes", "radiusKm": 3, "total": 1, "planes": [{"hex": "abc123"}]}


def test_latest_card_remembers_the_last_message_until_cleared():
    card = LatestCard()
    assert card.latest() == {"type": "clear"}
    assert card.show(MESSAGE)
    assert card.latest() == MESSAGE
    card.clear()
    assert card.latest() == {"type": "clear"}


@pytest.fixture
def served():
    card = LatestCard()
    server = LiveServer({"/planes.json": card}, "127.0.0.1", 0, LOG)
    port = server.start()
    yield card, f"http://127.0.0.1:{port}"
    server.stop()
    server.stop()


def test_server_hands_out_the_latest_message_uncached(served):
    card, base = served
    card.show(MESSAGE)
    with urlopen(f"{base}/planes.json?t=1") as response:
        assert response.headers["Cache-Control"] == "no-store"
        assert json.load(response) == MESSAGE


def test_server_answers_nothing_else(served):
    _, base = served
    with pytest.raises(HTTPError) as error:
        urlopen(f"{base}/other")
    error.value.close()
    assert error.value.code == 404


def test_fan_out_shows_and_clears_everywhere():
    first, second = RecordingDisplay(), RecordingDisplay()
    fan = FanOutDisplay([first, second])
    assert fan.show(MESSAGE)
    fan.clear()
    assert first.shown == second.shown == [MESSAGE]
    assert first.clears == second.clears == 1


class BusyDisplay(RecordingDisplay):
    def show(self, message):
        super().show(message)
        return False


def test_fan_out_reports_busy_only_when_every_display_is():
    busy, free = BusyDisplay(), RecordingDisplay()
    assert FanOutDisplay([busy, free]).show(MESSAGE)
    assert not FanOutDisplay([busy]).show(MESSAGE)
    assert free.shown == [MESSAGE]


class BrokenDisplay(RecordingDisplay):
    def show(self, message):
        raise ConnectionError("Hub unreachable")


def test_fan_out_still_feeds_the_others_when_one_fails():
    free = RecordingDisplay()
    with pytest.raises(ConnectionError):
        FanOutDisplay([BrokenDisplay(), free]).show(MESSAGE)
    assert free.shown == [MESSAGE]


class Kept:
    def __init__(self) -> None:
        self.shown: list[dict] = []
        self.cleared = 0

    def show(self, message: dict) -> bool:
        self.shown.append(message)
        return True

    def clear(self) -> None:
        self.cleared += 1


def test_stamped_adds_its_fields_to_every_message():
    kept = Kept()
    stamped = Stamped(kept, {"homeCountry": "GB"})
    assert stamped.show({"type": "planes"})
    stamped.clear()
    assert kept.shown == [{"type": "planes", "homeCountry": "GB"}]
    assert kept.cleared == 1


def test_server_hands_out_each_of_its_snapshots_by_path():
    card, status = LatestCard(), LatestCard()
    status.show({"lastLook": "now"})
    server = LiveServer({"/planes.json": card, "/status.json": status}, "127.0.0.1", 0, LOG)
    port = server.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/status.json") as response:
            assert json.load(response) == {"lastLook": "now"}
    finally:
        server.stop()
