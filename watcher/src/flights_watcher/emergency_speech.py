"""The announcement for a plane in an emergency. Unlike the planes overhead, it is made
at any hour."""

import collections
import logging
from typing import Any, Protocol

from flights_watcher.speech import SpeechFailed, spelled_flight


class FlightWording(Protocol):
    def lead_in(self, card: dict[str, Any]) -> str | None: ...


class Whereabouts(Protocol):
    def phrase(self, card: dict[str, Any]) -> str | None: ...


# What a crew is saying when it declares each kind without a squawk.
REPORTING = {
    "general": "reporting a general emergency",
    "nordo": "reporting a radio failure",
    "unlawful": "reporting unlawful interference",
    "downed": "reporting it is going down",
}


class EmergencyWording:
    """Emergency. B A, 1 2 3, from Alicante, to London Stansted, squawking 7 7 0 0, general
    emergency, 42 kilometres away, in a North-Westerly direction, heading South.

    A plane with no route known goes by its callsign or registration and what it is, and
    one only flying steeply by how fast it is going up or down."""

    def __init__(self, flights: FlightWording, whereabouts: Whereabouts) -> None:
        self._flights = flights
        self._whereabouts = whereabouts

    def text(self, card: dict[str, Any]) -> str:
        emergency = card["emergency"]
        parts = [self._who(card), self._what(emergency, card), self._whereabouts.phrase(card)]
        heading = "Emergency" if emergency["kind"] in REPORTING else emergency["label"]
        return f"{heading}. " + ", ".join(part for part in parts if part) + "."

    def _who(self, card: dict[str, Any]) -> str:
        lead_in = self._flights.lead_in(card)
        if lead_in:
            return lead_in
        named = card.get("flightNumber") or card.get("callsign") or card.get("registration")
        parts = [spelled_flight(named) if named else None, card.get("aircraft")]
        return ", ".join(part for part in parts if part) or "An aircraft"

    def _what(self, emergency: dict[str, Any], card: dict[str, Any]) -> str:
        if emergency["squawk"]:
            return f"squawking {' '.join(emergency['squawk'])}, {emergency['label'].lower()}"
        if emergency["kind"] in REPORTING:
            return REPORTING[emergency["kind"]]
        rate = round(abs(card.get("verticalRateFpm") or 0), -2)
        going = "coming down" if emergency["kind"] == "descent" else "climbing"
        return f"{going} at {rate:,} feet a minute"


class Wording(Protocol):
    def text(self, card: dict[str, Any]) -> str: ...


class ClipMaker(Protocol):
    def url_for(self, text: str) -> str: ...


class EmergencyAnnouncer:
    """Announces each plane's emergency once, and again only if it becomes another kind
    (7600 turning into 7700, say). The clip is handed out with every update while that
    emergency stays first on the card, as the card may still be launching."""

    def __init__(self, wording: Wording, clips: ClipMaker, remembered: int, logger: logging.Logger) -> None:
        self._wording = wording
        self._clips = clips
        self._logger = logger
        self._announced: collections.deque[str] = collections.deque(maxlen=remembered)
        self._current: str | None = None
        self._url: str | None = None

    def speech_for(self, card: dict[str, Any]) -> str | None:
        emergency = f"{card['hex']}/{card['emergency']['kind']}"
        if emergency != self._current:
            self._current = emergency
            self._url = None if emergency in self._announced else self._make(card)
            self._announced.append(emergency)
        return self._url

    def _make(self, card: dict[str, Any]) -> str | None:
        text = self._wording.text(card)
        try:
            return self._clips.url_for(text)
        except (SpeechFailed, OSError) as error:
            self._logger.warning("could not make the announcement %r: %s", text, error)
            return None
