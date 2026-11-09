"""Spoken announcements: the words, a clip from a Piper speech server, and a file the Hub can play.

The Pi only makes the audio file. The card on the Hub fetches it from the
receiver page and plays it through the Hub's own speaker."""

import io
import json
import logging
import re
import socket
import wave
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any, BinaryIO, Protocol

from flights_watcher.announced import AnnouncedFlights
from flights_watcher.files import KeptFiles
from flights_watcher.geo import Location
from flights_watcher.heard import SpeechTiming, ahead


class SpeechFailed(Exception):
    pass


COMPASS_POINTS = (
    "Northerly",
    "North-North-Easterly",
    "North-Easterly",
    "East-North-Easterly",
    "Easterly",
    "East-South-Easterly",
    "South-Easterly",
    "South-South-Easterly",
    "Southerly",
    "South-South-Westerly",
    "South-Westerly",
    "West-South-Westerly",
    "Westerly",
    "West-North-Westerly",
    "North-Westerly",
    "North-North-Westerly",
)


class SpokenWhereabouts:
    """Where the plane is from home and which way it is flying, for saying out loud:
    "1.1 kilometres away, in a North-North-Easterly direction, heading West"."""

    def __init__(self, home: Location) -> None:
        self._home = home

    def phrase(self, card: dict[str, Any]) -> str | None:
        if card.get("lat") is None or card.get("lon") is None:
            return None
        plane = Location(card["lat"], card["lon"])
        km = self._home.distance_km(plane)
        point = COMPASS_POINTS[round(self._home.bearing_deg(plane) / 22.5) % 16]
        article = "an" if point.startswith("E") else "a"
        where = f"{_spoken_distance(km)} away, in {article} {point} direction"
        if card.get("trackDeg") is None:
            return where
        heading = COMPASS_POINTS[round(card["trackDeg"] / 22.5) % 16].removesuffix("erly")
        return f"{where}, heading {heading}"


def _spoken_distance(km: float) -> str:
    if km < 1:
        metres = max(100, round(km * 10) * 100)
        return f"{metres} metres"
    return "1 kilometre" if round(km, 1) == 1 else f"{round(km, 1):g} kilometres"


def _spoken_wait(seconds: float) -> str:
    if seconds < 15:
        return "a few seconds"
    if seconds < 55:
        return f"about {round(seconds / 10) * 10} seconds"
    minutes = round(seconds / 60)
    return "about a minute" if minutes <= 1 else f"about {minutes} minutes"


class Whereabouts(Protocol):
    def phrase(self, card: dict[str, Any]) -> str | None: ...


class Arrival(Protocol):
    def phrase(self, card: dict[str, Any]) -> str | None: ...


class SpokenArrival:
    """The last words of an announcement, about the plane as it will be when they have
    been heard: "It's overhead now." once it is within overhead_km of home, or "It will
    be overhead in about 30 seconds." for one still on its way, and nothing for one that
    has gone past."""

    def __init__(self, home: Location, overhead_km: float) -> None:
        self._home = home
        self._overhead_km = overhead_km

    def phrase(self, card: dict[str, Any]) -> str | None:
        located = card.get("lat") is not None and card.get("lon") is not None
        if located and self._home.distance_km(Location(card["lat"], card["lon"])) <= self._overhead_km:
            return "It's overhead now."
        if card.get("overheadInSeconds"):
            return f"It will be overhead in {_spoken_wait(card['overheadInSeconds'])}."
        return None


class AnnouncementWording:
    """FR20SW, from Alicante, to London Stansted, 1.1 kilometres away, in a
    North-North-Easterly direction, heading West. A flight with no route known goes by its
    callsign and what it is instead. Airports that share their city with others are named
    in full, everywhere else by its city, and flight numbers are read letter by letter."""

    def __init__(self, named_airports: Collection[str], whereabouts: Whereabouts) -> None:
        self._named = named_airports
        self._whereabouts = whereabouts

    def text(self, card: dict[str, Any]) -> str | None:
        lead_in = self.lead_in(card)
        if lead_in is None:
            return None
        where = self._whereabouts.phrase(card)
        return (f"{lead_in}, {where}" if where else lead_in) + "."

    def lead_in(self, card: dict[str, Any]) -> str | None:
        """The flight and its route, read before where the plane is. An air ambulance, the
        police or the military have no route, so they go by what they are, and a military
        plane by what it is too: "Royal Air Force, Airbus A400M Atlas". A charter, a private
        plane, or any flight FlightAware has no route for, goes by its callsign and what it
        is: "S X N, 3 9, Agusta AW-139 helicopter". A notable aircraft says who it belongs
        to after that. One whose callsign is not heard yet waits for it, as the callsign is
        half of what makes it a flight already announced."""
        if card.get("service") and card.get("airline"):
            if card["service"] == "military" and card.get("aircraft"):
                return f"{card['airline']}, {card['aircraft']}"
            return f"{card['airline']} helicopter" if card.get("helicopter") else card["airline"]
        flight = card.get("flightNumber") or card.get("callsign")
        if not flight:
            return None
        origin, destination = self._place(card.get("origin")), self._place(card.get("destination"))
        # The commas give the voice a breath after the flight number and between the parts.
        owner = f"belonging to {card['owner']}" if card.get("owner") else None
        if origin and destination:
            parts = [spelled_flight(flight), f"from {origin}", f"to {destination}", owner]
        else:
            parts = [spelled_flight(flight), _what_it_is(card), owner]
        return ", ".join(part for part in parts if part)

    def _place(self, airport: dict[str, Any] | None) -> str | None:
        if not airport:
            return None
        name = re.sub(r" (International|Intl)?\s*Airport$| Intl$| International$", "", airport.get("name") or "")
        city = airport.get("city")
        if airport.get("code") in self._named and name and city:
            # adsbdb says "London Stansted Airport", FlightAware just "Stansted".
            return name if name.startswith(city) else f"{city} {name}"
        return city or name or None


def _what_it_is(card: dict[str, Any]) -> str | None:
    aircraft = card.get("aircraft")
    if not card.get("helicopter") or "helicopter" in (aircraft or "").lower():
        return aircraft
    return f"{aircraft} helicopter" if aircraft else "helicopter"


# Three letters (BAW86S) or two characters (BA1340, U21234) before the number starts.
_AIRLINE_DESIGNATOR = re.compile(r"^([A-Z]{3}|[A-Z0-9]{2})(?=\d)")


def spelled_flight(flight: str) -> str:
    """Read out a character at a time, with a comma between the airline and the number:
    "B A, 1 3 4 0". Without it the voice runs the A into the 1. A registration has no
    airline to split off, so G-EUYM is just "G E U Y M"."""
    match = _AIRLINE_DESIGNATOR.match(flight)
    if match is None:
        return " ".join(flight)
    return f"{' '.join(match.group(1))}, {' '.join(flight[match.end() :])}"


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> bytes:
        """A WAV file of the text being read out. Raises SpeechFailed."""
        ...


class WyomingSpeech:
    """Talks the Wyoming protocol to a wyoming-piper server: one synthesize event in,
    audio-start, audio-chunk and audio-stop events back."""

    def __init__(self, host: str, port: int, timeout_seconds: float) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds

    def synthesize(self, text: str) -> bytes:
        try:
            with socket.create_connection((self._host, self._port), timeout=self._timeout_seconds) as connection:
                request = {"type": "synthesize", "data": {"text": text}}
                connection.sendall((json.dumps(request) + "\n").encode())
                return self._read_audio(connection.makefile("rb"))
        except (OSError, ValueError, KeyError) as error:
            raise SpeechFailed(f"{type(error).__name__}: {error}") from error

    def _read_audio(self, stream: BinaryIO) -> bytes:
        pcm = io.BytesIO()
        audio_format: dict[str, Any] | None = None
        while True:
            line = stream.readline()
            if not line:
                raise SpeechFailed("speech server closed the connection early")
            header = json.loads(line)
            data = header.get("data") or {}
            if header.get("data_length"):
                data.update(json.loads(stream.read(header["data_length"])))
            payload = stream.read(header["payload_length"]) if header.get("payload_length") else b""
            if header["type"] == "audio-start":
                audio_format = data
            elif header["type"] == "audio-chunk":
                pcm.write(payload)
            elif header["type"] == "audio-stop":
                break
        if audio_format is None:
            raise SpeechFailed("no audio-start from the speech server")
        return _wav(pcm.getvalue(), audio_format)


def _wav(pcm: bytes, audio_format: dict[str, Any]) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as clip:
        clip.setnchannels(audio_format["channels"])
        clip.setsampwidth(audio_format["width"])
        clip.setframerate(audio_format["rate"])
        clip.writeframes(pcm)
    return out.getvalue()


class SaidAsWords:
    """Piper spells out a word written in capitals, which is right for most of them in an
    aircraft's name but wrong where the capitals are only styling: a Boeing 737 MAX is
    said "max", not "M A X". Each such word is written the way it is said before the
    text reaches the voice."""

    def __init__(self, inner: SpeechSynthesizer, words: Mapping[str, str]) -> None:
        self._inner = inner
        self._pattern = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b") if words else None
        self._words = words

    def synthesize(self, text: str) -> bytes:
        if self._pattern is not None:
            text = self._pattern.sub(lambda match: self._words[match.group(1)], text)
        return self._inner.synthesize(text)


class AirbusNumbersSaid:
    """Piper reads an Airbus type the way it reads any number, "A three hundred and
    twenty", where everyone who flies them says "A three twenty": the first digit, then
    the other two as one number, or "hundred" for the A300. The variant after it, such as
    the 1000 in A350-1000 or the neo in A320neo, follows as a word of its own, instead of
    after a minus or run into the number."""

    _TYPE = re.compile(r"\bA(\d)(\d\d)(?:-(\d+))?([a-z]*)\b")

    def __init__(self, inner: SpeechSynthesizer) -> None:
        self._inner = inner

    def synthesize(self, text: str) -> bytes:
        return self._inner.synthesize(self._TYPE.sub(_said_airbus, text))


def _said_airbus(match: re.Match[str]) -> str:
    first, rest, *after = match.groups()
    return " ".join(["A", first, "hundred" if rest == "00" else rest, *(part for part in after if part)])


class BoeingNumbersSaid:
    """Piper reads a Boeing type as a number, "seven hundred and eighty seven", where
    everyone says it a digit at a time: "seven eight seven". The variant after it, such
    as the 9 in 787-9, follows as a word of its own instead of after a minus."""

    _TYPE = re.compile(r"\b7(\d)7(?:-(\w+))?\b")

    def __init__(self, inner: SpeechSynthesizer) -> None:
        self._inner = inner

    def synthesize(self, text: str) -> bytes:
        return self._inner.synthesize(self._TYPE.sub(_said_boeing, text))


def _said_boeing(match: re.Match[str]) -> str:
    middle, variant = match.groups()
    return " ".join(["7", middle, "7", *([variant] if variant else [])])


class SpeechClips:
    """One WAV per sentence, kept in a folder the receiver serves, so a repeated announcement
    is not synthesised twice."""

    def __init__(self, files: KeptFiles, synthesizer: SpeechSynthesizer) -> None:
        self._files = files
        self._synthesizer = synthesizer

    def url_for(self, text: str) -> str:
        return self._files.url_for(text, lambda: self._synthesizer.synthesize(text))


class SpeechPicker(Protocol):
    def speech_for(self, card: dict[str, Any]) -> str | None: ...

    def ended(self) -> None: ...


class Wording(Protocol):
    def lead_in(self, card: dict[str, Any]) -> str | None: ...

    def text(self, card: dict[str, Any]) -> str | None: ...


class ClipMaker(Protocol):
    def url_for(self, text: str) -> str: ...


class Announcer:
    """Announces the nearest plane each time a new one takes over, once per flight, as
    soon as its card has something to say about it: one that was announced and
    comes back to being nearest stays quiet, so two planes swapping places do not talk
    over each other. The clip is handed out with
    every update while its plane stays nearest, until the card is taken down; a card
    launched afresh for the same plane gets no clip to play a second time, even after a
    restart, since the flights announced are kept (see RememberedFlights). Where the
    plane is gets worked out for when those words will be heard, and whether it is
    overhead yet for when the whole announcement has been."""

    def __init__(
        self,
        wording: Wording,
        arrival: Arrival,
        timing: SpeechTiming,
        clips: ClipMaker,
        announced: AnnouncedFlights,
        logger: logging.Logger,
    ) -> None:
        self._wording = wording
        self._arrival = arrival
        self._timing = timing
        self._clips = clips
        self._logger = logger
        self._announced = announced
        self._hex: str | None = None
        self._url: str | None = None
        self._settled = False
        self._launching = False

    def speech_for(self, card: dict[str, Any]) -> str | None:
        if card["hex"] != self._hex:
            self._launching = self._hex is None
            self._hex, self._url, self._settled = card["hex"], None, False
        # A card can go up before the plane's callsign or route is known, so it is
        # announced on the first update that has something to say, not only the first one.
        lead_in = None if self._settled else self._wording.lead_in(card)
        if lead_in is not None:
            # The same airframe back hours later as another flight is worth announcing.
            flight = f"{card['hex']}/{card.get('callsign')}"
            if not self._announced.has(flight):
                self._url = self._make(card, lead_in, self._launching)
            self._announced.add(flight)
            self._settled = True
        # Only the first update goes out with the launch; any later one finds the card up.
        self._launching = False
        return self._url

    def ended(self) -> None:
        self._hex, self._url = None, None

    def _make(self, card: dict[str, Any], lead_in: str, launching: bool) -> str | None:
        said = self._wording.text(card) or lead_in
        draft = _joined(said, self._arrival.phrase(card))
        said = self._wording.text(ahead(card, self._timing.until(draft, len(lead_in), launching))) or said
        finished = ahead(card, self._timing.until(draft, len(draft), launching))
        text = _joined(said, self._arrival.phrase(finished))
        try:
            return self._clips.url_for(text)
        except (SpeechFailed, OSError) as error:
            self._logger.warning("could not make the announcement %r: %s", text, error)
            return None


def _joined(said: str, arrival: str | None) -> str:
    return f"{said} {arrival}" if arrival else said


class QuietSchedule(Protocol):
    def is_quiet(self, now: datetime) -> bool: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class RareCards(Protocol):
    def includes_card(self, card: dict[str, Any]) -> bool: ...


class QuietVoice:
    """Keeps the announcements quiet during its hours, except for the rare kinds of
    aircraft (helicopters and military ones, unless told otherwise), which are worth
    hearing at any time."""

    def __init__(self, inner: SpeechPicker, quiet_hours: QuietSchedule, clock: Clock, rare: RareCards) -> None:
        self._inner = inner
        self._quiet_hours = quiet_hours
        self._clock = clock
        self._rare = rare

    def speech_for(self, card: dict[str, Any]) -> str | None:
        if self._quiet_hours.is_quiet(self._clock.now()) and not self._rare.includes_card(card):
            return None
        return self._inner.speech_for(card)

    def ended(self) -> None:
        self._inner.ended()


class Silence:
    """Stands in for the Announcer when SPEECH_SERVER is empty."""

    def speech_for(self, card: dict[str, Any]) -> str | None:
        return None

    def ended(self) -> None:
        pass


class Voice(Protocol):
    def ended(self) -> None: ...


class EndOfShowing:
    """Sits beside the real displays and tells the voice when the card is taken down,
    so it stops handing out the last clip. Draws nothing itself."""

    def __init__(self, voice: Voice) -> None:
        self._voice = voice

    def show(self, message: dict[str, Any]) -> bool:
        return False

    def clear(self) -> None:
        self._voice.ended()


class InterruptedByEmergency:
    """Sits beside the real displays and tells the voice when an emergency takes the card,
    so the plane it was announcing does not get its clip played again once the emergency
    is over. Draws nothing itself."""

    def __init__(self, voice: Voice) -> None:
        self._voice = voice

    def show(self, message: dict[str, Any]) -> bool:
        cards = message.get("planes") or [{}]
        if cards[0].get("emergency"):
            self._voice.ended()
        return False

    def clear(self) -> None:
        pass
