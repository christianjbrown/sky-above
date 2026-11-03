"""What has changed about a followed flight that is worth saying out loud: a new gate,
a bigger or smaller delay, cancelled or diverted, taken off, nearly down, landed, and
the baggage belt.

Each kind of change compares the flight now with how it was the last time that change
was spoken, or when the flight first came on, so a delay that creeps up a minute at a
time is still announced once it has moved by enough, and nothing is said about how a
flight already was when it first turned up."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Any, Protocol

from flights_watcher.clock import Clock
from flights_watcher.following import Followed
from flights_watcher.speech import SpeechFailed

BEFORE_TAKE_OFF = ("waiting",)
DOWN = ("landed", "arrived")


@dataclass(frozen=True)
class FlightState:
    """The parts of a followed flight's card the announcements are about."""

    phase: str | None
    cancelled: bool
    diverted: bool
    departure_delay_minutes: int | None
    our_estimate: bool
    departs_at: datetime | None
    lands_at: datetime | None
    gate: str | None
    belt: str | None
    # How long until it lands, from when this state was taken.
    lands_in: timedelta | None

    @classmethod
    def of(cls, flight: dict[str, Any], now: datetime) -> "FlightState":
        lands_at = _when(flight.get("landsAt"))
        return cls(
            phase=flight.get("phase"),
            cancelled=flight.get("phase") == "cancelled",
            diverted=bool(flight.get("diverted")),
            departure_delay_minutes=flight.get("departureDelayMinutes"),
            our_estimate=flight.get("departureEstimate") == "ours",
            departs_at=_when(flight.get("departsAt")),
            lands_at=lands_at,
            gate=flight.get("gateOrigin"),
            belt=flight.get("baggageClaim"),
            lands_in=lands_at - now if lands_at else None,
        )


class Change(Protocol):
    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        """What to say, after the flight's name, if it has changed since then."""
        ...


class Cancelled:
    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        return "has been cancelled" if now.cancelled and not then.cancelled else None


class Diverted:
    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        return "has been diverted" if now.diverted and not then.diverted else None


class DelayMoved:
    """A delay is announced once it reaches late_minutes and again each time it moves by
    step_minutes, either way, and when it goes back to on time."""

    def __init__(self, late_minutes: int, step_minutes: int, zone: tzinfo) -> None:
        self._late_minutes = late_minutes
        self._step_minutes = step_minutes
        self._zone = zone

    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        if now.phase not in BEFORE_TAKE_OFF or now.cancelled or now.departs_at is None:
            return None
        was, delay = max(then.departure_delay_minutes or 0, 0), max(now.departure_delay_minutes or 0, 0)
        if abs(delay - was) < self._step_minutes or max(was, delay) < self._late_minutes:
            return None
        leaving = _clock(now.departs_at, self._zone)
        if delay < self._late_minutes:
            return f"is back on time, leaving at {leaving}"
        if now.our_estimate:
            return f"now looks likely to leave {_minutes(delay)} late, at {leaving}"
        return f"is now delayed by {_minutes(delay)}, leaving at {leaving}"


class GateChanged:
    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        if now.phase not in BEFORE_TAKE_OFF or now.cancelled or not now.gate or now.gate == then.gate:
            return None
        return f"has moved to gate {now.gate}" if then.gate else f"will leave from gate {now.gate}"


class TookOff:
    def __init__(self, zone: tzinfo) -> None:
        self._zone = zone

    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        if now.phase != "flying" or then.phase == "flying":
            return None
        if now.lands_at is None:
            return "has taken off"
        return f"has taken off, and should land at {_clock(now.lands_at, self._zone)}"


class LandingSoon:
    """Once, as the time left to landing drops to within."""

    def __init__(self, within: timedelta) -> None:
        self._within = within

    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        if now.phase != "flying" or now.lands_in is None or then.lands_in is None:
            return None
        if not timedelta(0) < now.lands_in <= self._within < then.lands_in:
            return None
        return f"lands in about {_minutes(round(now.lands_in.total_seconds() / 60))}"


class Landed:
    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        return "has landed" if now.phase in DOWN and then.phase not in DOWN else None


class BeltChanged:
    def phrase(self, then: FlightState, now: FlightState) -> str | None:
        if not now.belt or now.belt == then.belt:
            return None
        return f"has its bags on belt {now.belt}" if not then.belt else f"has moved its bags to belt {now.belt}"


class FollowedNews:
    """Turns each update of a followed flight's card into the sentence to announce, if
    anything worth saying has changed: "B A 4 3 2 1 to Berlin has moved to gate B41."
    Two changes at once make two sentences, the second starting "It"."""

    def __init__(self, changes: Sequence[Change], clock: Clock, logger: logging.Logger) -> None:
        self._changes = changes
        self._clock = clock
        self._logger = logger
        # For each flight, how it was when each change was last spoken.
        self._then: dict[tuple[str, str | None], list[FlightState]] = {}

    def text(self, card: dict[str, Any]) -> str | None:
        flight = card["flight"]
        now = FlightState.of(flight, self._clock.now())
        key = (flight["ident"], flight.get("scheduledOut"))
        then = self._then.setdefault(key, [now] * len(self._changes))
        said: list[str] = []
        for index, change in enumerate(self._changes):
            phrase = change.phrase(then[index], now)
            if phrase:
                said.append(phrase)
                then[index] = now
        if not said:
            return None
        text = f"{_name(card)} {said[0]}." + "".join(f" It {phrase}." for phrase in said[1:])
        self._logger.info("followed flight news: %s", text)
        return text


class SpeechPicker(Protocol):
    def speech_for(self, card: dict[str, Any]) -> str | None: ...


class FollowedCards(Protocol):
    def build(self, followed: Followed) -> dict[str, Any]: ...


class News(Protocol):
    def text(self, card: dict[str, Any]) -> str | None: ...


class AnnouncedFollowedCards:
    """Adds the news to each followed card as "announcement", and the clip of it, if the
    voice will say it, as "speech"."""

    def __init__(self, cards: FollowedCards, news: News, voice: SpeechPicker) -> None:
        self._cards = cards
        self._news = news
        self._voice = voice

    def build(self, followed: Followed) -> dict[str, Any]:
        card = self._cards.build(followed)
        card["announcement"] = self._news.text(card)
        card["speech"] = self._voice.speech_for(card)
        return card


class ClipMaker(Protocol):
    def url_for(self, text: str) -> str: ...


class FollowedAnnouncer:
    """Makes the clip for a followed card's announcement and hands it out with each update
    for keep_seconds, so a card still launching gets to play it, and then stops, so a card
    launched afresh later does not play old news. Each announcement gets its own address,
    since the page plays a clip only when its address is new and the same words can be
    news twice."""

    def __init__(self, clips: ClipMaker, keep_seconds: float, clock: Clock, logger: logging.Logger) -> None:
        self._clips = clips
        self._keep_seconds = keep_seconds
        self._clock = clock
        self._logger = logger
        self._count = 0
        self._url: str | None = None
        self._made_at = 0.0

    def speech_for(self, card: dict[str, Any]) -> str | None:
        text = card.get("announcement")
        if text:
            self._count += 1
            self._made_at = self._clock.monotonic()
            try:
                self._url = f"{self._clips.url_for(text)}?{self._count}"
            except (SpeechFailed, OSError) as error:
                self._url = None
                self._logger.warning("could not make the announcement %r: %s", text, error)
        if self._url is None or self._clock.monotonic() - self._made_at > self._keep_seconds:
            return None
        return self._url

    def ended(self) -> None:
        self._url = None


def _name(card: dict[str, Any]) -> str:
    """The flight number letter by letter, and where it is going."""
    flight = card["flight"]
    destination = flight.get("destination") or {}
    to = destination.get("city") or destination.get("name") or destination.get("code")
    spoken = " ".join(flight["ident"])
    return f"{spoken} to {to}" if to else spoken


def _minutes(minutes: int) -> str:
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append("an hour" if hours == 1 else f"{hours} hours")
    if minutes or not hours:
        parts.append("1 minute" if minutes == 1 else f"{minutes} minutes")
    return " and ".join(parts)


def _clock(moment: datetime, zone: tzinfo) -> str:
    return moment.astimezone(zone).strftime("%H:%M")


def _when(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None
