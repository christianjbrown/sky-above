import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fakes import FakeClock
from flights_watcher.followed_news import (
    AnnouncedFollowedCards,
    BeltChanged,
    Cancelled,
    DelayMoved,
    Diverted,
    FollowedAnnouncer,
    FollowedNews,
    GateChanged,
    Landed,
    LandingSoon,
    TookOff,
)
from flights_watcher.speech import SpeechFailed

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2027, 3, 12, 14, 0, tzinfo=UTC)
LOG = logging.getLogger("test")


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def card(**flight: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "ident": "BA4321",
        "phase": "waiting",
        "diverted": False,
        "destination": {"code": "BER", "city": "Berlin"},
        "scheduledOut": "2027-03-12T16:25:00Z",
        "departsAt": "2027-03-12T16:25:00Z",
        "departureEstimate": "airline",
        "departureDelayMinutes": 0,
        "landsAt": "2027-03-12T18:20:00Z",
        "gateOrigin": None,
        "baggageClaim": None,
    }
    fields.update(flight)
    return {"type": "followed", "flight": fields}


def news(clock: FakeClock | None = None) -> FollowedNews:
    return FollowedNews(
        [
            Cancelled(),
            Diverted(),
            DelayMoved(10, 10, LONDON),
            GateChanged(),
            TookOff(LONDON),
            LandingSoon(timedelta(minutes=20)),
            Landed(),
            BeltChanged(),
        ],
        clock or FakeClock(NOW),
        LOG,
    )


def test_nothing_is_said_about_how_a_flight_was_when_it_first_turned_up():
    told = news()
    assert told.text(card(gateOrigin="B32", departureDelayMinutes=40)) is None
    assert told.text(card(gateOrigin="B32", departureDelayMinutes=40)) is None


def test_a_gate_given_out_then_changed():
    told = news()
    told.text(card())
    assert told.text(card(gateOrigin="B32")) == "B A, 4 3 2 1 to Berlin will leave from gate B32."
    assert told.text(card(gateOrigin="B41")) == "B A, 4 3 2 1 to Berlin has moved to gate B41."


def test_a_delay_is_announced_once_it_has_moved_far_enough_either_way():
    told = news()
    told.text(card())
    assert told.text(card(departureDelayMinutes=9, departsAt="2027-03-12T16:34:00Z")) is None
    assert (
        told.text(card(departureDelayMinutes=12, departsAt="2027-03-12T16:37:00Z"))
        == "B A, 4 3 2 1 to Berlin is now delayed by 12 minutes, leaving at 16:37."
    )
    assert told.text(card(departureDelayMinutes=21, departsAt="2027-03-12T16:46:00Z")) is None
    assert (
        told.text(card(departureDelayMinutes=85, departsAt="2027-03-12T17:50:00Z"))
        == "B A, 4 3 2 1 to Berlin is now delayed by an hour and 25 minutes, leaving at 17:50."
    )
    assert told.text(card(departureDelayMinutes=0)) == "B A, 4 3 2 1 to Berlin is back on time, leaving at 16:25."


def test_our_own_estimate_is_called_likely():
    told = news()
    told.text(card())
    assert (
        told.text(card(departureDelayMinutes=25, departsAt="2027-03-12T16:50:00Z", departureEstimate="ours"))
        == "B A, 4 3 2 1 to Berlin now looks likely to leave 25 minutes late, at 16:50."
    )


def test_cancelled_says_only_that():
    told = news()
    told.text(card(gateOrigin="B32"))
    assert told.text(card(phase="cancelled", gateOrigin="B32", departureDelayMinutes=None)) == (
        "B A, 4 3 2 1 to Berlin has been cancelled."
    )


def test_diverted():
    told = news()
    told.text(card(phase="flying"))
    assert told.text(card(phase="flying", diverted=True)) == "B A, 4 3 2 1 to Berlin has been diverted."


def test_taking_off_says_when_it_should_land_in_home_time():
    told = news()
    told.text(card(phase="taxiing"))
    assert told.text(card(phase="flying")) == "B A, 4 3 2 1 to Berlin has taken off, and should land at 18:20."
    assert told.text(card(phase="flying")) is None


def test_nearly_down_is_said_once_as_it_comes_within_twenty_minutes():
    clock = FakeClock(NOW)
    told = news(clock)
    told.text(card(phase="flying"))
    clock.at = datetime(2027, 3, 12, 17, 55, tzinfo=UTC)
    assert told.text(card(phase="flying")) is None
    clock.at = datetime(2027, 3, 12, 18, 1, tzinfo=UTC)
    assert told.text(card(phase="flying")) == "B A, 4 3 2 1 to Berlin lands in about 19 minutes."
    clock.at = datetime(2027, 3, 12, 18, 5, tzinfo=UTC)
    assert told.text(card(phase="flying")) is None


def test_landing_and_the_belt_and_two_at_once():
    told = news()
    told.text(card(phase="flying"))
    assert told.text(card(phase="landed", baggageClaim="7")) == ("B A, 4 3 2 1 to Berlin has landed. It has its bags on belt 7.")
    assert told.text(card(phase="arrived", baggageClaim="7")) is None
    assert told.text(card(phase="arrived", baggageClaim="9")) == "B A, 4 3 2 1 to Berlin has moved its bags to belt 9."


def test_each_flight_and_day_is_kept_apart():
    told = news()
    told.text(card(gateOrigin="B32"))
    assert told.text(card(gateOrigin="B32", scheduledOut="2027-03-13T16:25:00Z")) is None


class Clips:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.made: list[str] = []

    def url_for(self, text: str) -> str:
        if self.fail:
            raise SpeechFailed("no speech server")
        self.made.append(text)
        return "speech/abc.wav"


def test_the_announcer_hands_out_the_clip_for_a_while_with_its_own_address():
    clock = FakeClock(NOW)
    clips = Clips()
    voice = FollowedAnnouncer(clips, 60, clock, LOG)
    assert voice.speech_for({"announcement": None}) is None
    assert voice.speech_for({"announcement": "Gate B32."}) == "speech/abc.wav?1"
    clock.seconds = 30
    assert voice.speech_for({"announcement": None}) == "speech/abc.wav?1"
    clock.seconds = 61
    assert voice.speech_for({"announcement": None}) is None
    assert voice.speech_for({"announcement": "Gate B32."}) == "speech/abc.wav?2"
    assert clips.made == ["Gate B32.", "Gate B32."]


def test_the_announcer_survives_the_speech_server_failing():
    voice = FollowedAnnouncer(Clips(fail=True), 60, FakeClock(NOW), LOG)
    assert voice.speech_for({"announcement": "Gate B32."}) is None


class Built:
    def __init__(self, message: dict[str, Any]) -> None:
        self.message = message

    def build(self, followed: Any) -> dict[str, Any]:
        return dict(self.message)


class Saying:
    def text(self, card: dict[str, Any]) -> str | None:
        return "Gate B32."


class Voice:
    def speech_for(self, card: dict[str, Any]) -> str | None:
        return "clip:" + card["announcement"]


def test_the_card_carries_the_announcement_and_its_clip():
    cards = AnnouncedFollowedCards(Built(card()), Saying(), Voice())
    message = cards.build(None)
    assert message["announcement"] == "Gate B32."
    assert message["speech"] == "clip:Gate B32."


def test_a_delay_of_whole_hours_leaves_out_the_minutes():
    told = news()
    told.text(card())
    assert (
        told.text(card(departureDelayMinutes=120, departsAt="2027-03-12T18:25:00Z"))
        == "B A, 4 3 2 1 to Berlin is now delayed by 2 hours, leaving at 18:25."
    )


def test_taking_off_without_a_landing_time_says_only_that():
    told = news()
    told.text(card(phase="taxiing"))
    assert told.text(card(phase="flying", landsAt=None)) == "B A, 4 3 2 1 to Berlin has taken off."


def test_the_announcer_drops_its_clip_when_the_flight_ends():
    voice = FollowedAnnouncer(Clips(), 60, FakeClock(NOW), LOG)
    assert voice.speech_for({"announcement": "Gate B32."}) == "speech/abc.wav?1"
    voice.ended()
    assert voice.speech_for({"announcement": None}) is None
